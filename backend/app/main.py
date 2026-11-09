from __future__ import annotations

import csv
import hashlib
import io
import os
import re
import secrets
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from typing import Generator

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    func,
    or_,
    select,
    text,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, joinedload, mapped_column, relationship, sessionmaker
from pwdlib import PasswordHash
from app.workflows.prospect_import import run_prospect_import
from app.workflows.research import run_company_enrichment, run_research


DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql+psycopg://vidya:vidya@localhost:5432/vidya_intelligence"
)
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
password_hash = PasswordHash.recommended()
SESSION_COOKIE = "vidya_session"
SESSION_HOURS = 12


class Base(DeclarativeBase):
    pass


class Company(Base):
    __tablename__ = "companies"
    __table_args__ = (
        UniqueConstraint("name", "city", "state", name="uq_company_name_city_state"),
        Index("ix_companies_state_city", "state", "city"),
        CheckConstraint("length(trim(name)) > 0", name="ck_companies_name_nonempty"),
        CheckConstraint("length(trim(category)) > 0", name="ck_companies_category_nonempty"),
        CheckConstraint("length(trim(city)) > 0", name="ck_companies_city_nonempty"),
        CheckConstraint("length(trim(state)) > 0", name="ck_companies_state_nonempty"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    category: Mapped[str] = mapped_column(String(80), index=True)
    city: Mapped[str] = mapped_column(String(100), default="Varanasi", index=True)
    state: Mapped[str] = mapped_column(String(100), default="Uttar Pradesh")
    website: Mapped[str | None] = mapped_column(String(500))
    public_phone: Mapped[str | None] = mapped_column(String(50))
    description: Mapped[str | None] = mapped_column(Text)
    location_id: Mapped[int | None] = mapped_column(ForeignKey("locations.id", ondelete="RESTRICT"), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    location: Mapped[Location | None] = relationship(back_populates="companies")
    sources: Mapped[list[Source]] = relationship(back_populates="company", cascade="all, delete-orphan")
    projects: Mapped[list[Project]] = relationship(back_populates="company", cascade="all, delete-orphan")
    contacts: Mapped[list[CompanyPerson]] = relationship(back_populates="company", cascade="all, delete-orphan")
    activities: Mapped[list[Activity]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint("estimated_units IS NULL OR estimated_units >= 0", name="ck_projects_units_nonnegative"),
        CheckConstraint("estimated_doors IS NULL OR estimated_doors >= 0", name="ck_projects_doors_nonnegative"),
        CheckConstraint(
            "doors_per_unit IS NULL OR (doors_per_unit >= 0 AND doors_per_unit <= 100)",
            name="ck_projects_doors_per_unit_range",
        ),
        CheckConstraint(
            "demand_confidence IN ('unknown', 'low', 'medium', 'high')",
            name="ck_projects_demand_confidence",
        ),
        Index("ix_projects_status_name", "status", "name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    location: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(80), default="announced")
    estimated_units: Mapped[int | None] = mapped_column(Integer)
    estimated_doors: Mapped[int | None] = mapped_column(Integer)
    doors_per_unit: Mapped[float | None] = mapped_column(Float)
    estimate_basis: Mapped[str | None] = mapped_column(String(300))
    demand_confidence: Mapped[str] = mapped_column(String(20), default="unknown")
    demand_notes: Mapped[str | None] = mapped_column(Text)
    location_id: Mapped[int | None] = mapped_column(ForeignKey("locations.id", ondelete="RESTRICT"), index=True)
    company: Mapped[Company] = relationship(back_populates="projects")
    location_ref: Mapped[Location | None] = relationship(back_populates="projects")
    sources: Mapped[list[Source]] = relationship(back_populates="project", cascade="all, delete-orphan")
    relationships: Mapped[list[BusinessRelationship]] = relationship(back_populates="project")


class Source(Base):
    __tablename__ = "sources"
    __table_args__ = (
        CheckConstraint(
            "verification_status IN ('verified', 'unverified', 'rejected')",
            name="ck_sources_verification_status",
        ),
        Index("ix_sources_verification_discovered", "verification_status", "discovered_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int | None] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    url: Mapped[str] = mapped_column(String(1000))
    title: Mapped[str | None] = mapped_column(String(300))
    source_type: Mapped[str] = mapped_column(String(80), default="website")
    verification_status: Mapped[str] = mapped_column(String(30), default="unverified")
    content: Mapped[str | None] = mapped_column(Text)
    discovered_at: Mapped[date] = mapped_column(Date, default=date.today)
    company: Mapped[Company | None] = relationship(back_populates="sources")
    project: Mapped[Project | None] = relationship(back_populates="sources")


class Location(Base):
    __tablename__ = "locations"
    __table_args__ = (
        UniqueConstraint("state_key", "city_key", name="uq_locations_state_city"),
        CheckConstraint("length(trim(city)) > 0", name="ck_locations_city_nonempty"),
        CheckConstraint("length(trim(state)) > 0", name="ck_locations_state_nonempty"),
        Index("ix_locations_state_city", "state", "city"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    city: Mapped[str] = mapped_column(String(100))
    state: Mapped[str] = mapped_column(String(100))
    city_key: Mapped[str] = mapped_column(String(100))
    state_key: Mapped[str] = mapped_column(String(100))
    companies: Mapped[list[Company]] = relationship(back_populates="location")
    projects: Mapped[list[Project]] = relationship(back_populates="location_ref")


class Person(Base):
    __tablename__ = "people"
    __table_args__ = (
        CheckConstraint("length(trim(name)) > 0", name="ck_people_name_nonempty"),
        Index("ix_people_name", "name"),
        Index("uq_people_business_email", func.lower(text("business_email")), unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    business_email: Mapped[str | None] = mapped_column(String(255))
    business_phone: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    companies: Mapped[list[CompanyPerson]] = relationship(back_populates="person", cascade="all, delete-orphan")


class CompanyPerson(Base):
    __tablename__ = "company_people"
    __table_args__ = (
        CheckConstraint("length(trim(job_title)) > 0", name="ck_company_people_job_title_nonempty"),
        Index("ix_company_people_person_id", "person_id"),
    )

    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True
    )
    person_id: Mapped[int] = mapped_column(
        ForeignKey("people.id", ondelete="CASCADE"), primary_key=True
    )
    job_title: Mapped[str | None] = mapped_column(String(120))
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id", ondelete="SET NULL"))
    company: Mapped[Company] = relationship(back_populates="contacts")
    person: Mapped[Person] = relationship(back_populates="companies")
    source: Mapped[Source | None] = relationship()


class BusinessRelationship(Base):
    __tablename__ = "business_relationships"
    __table_args__ = (
        UniqueConstraint(
            "company_id", "related_company_id", "relationship_type", "project_id",
            name="uq_business_relationship",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    related_company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"))
    relationship_type: Mapped[str] = mapped_column(String(80))
    notes: Mapped[str | None] = mapped_column(Text)
    company: Mapped[Company] = relationship(foreign_keys=[company_id])
    related_company: Mapped[Company] = relationship(foreign_keys=[related_company_id])
    project: Mapped[Project | None] = relationship(back_populates="relationships")


class Activity(Base):
    __tablename__ = "activities"
    __table_args__ = (
        CheckConstraint("length(trim(activity_type)) > 0", name="ck_activities_type_nonempty"),
        CheckConstraint("length(trim(notes)) > 0", name="ck_activities_notes_nonempty"),
        CheckConstraint(
            "sales_outcome IS NULL OR sales_outcome IN "
            "('contacted', 'interested', 'qualified', 'proposal_sent', "
            "'won', 'lost', 'not_interested', 'no_response')",
            name="ck_activities_sales_outcome",
        ),
        Index("ix_activities_company_created", "company_id", "created_at"),
        Index("ix_activities_due_date_completed", "due_date", "completed_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    person_id: Mapped[int | None] = mapped_column(ForeignKey("people.id", ondelete="SET NULL"), index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), index=True)
    activity_type: Mapped[str] = mapped_column(String(50))
    notes: Mapped[str] = mapped_column(Text)
    next_action: Mapped[str | None] = mapped_column(String(300))
    sales_outcome: Mapped[str | None] = mapped_column(String(30))
    due_date: Mapped[date | None] = mapped_column(Date)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    company: Mapped[Company] = relationship(back_populates="activities")
    person: Mapped[Person | None] = relationship()
    project: Mapped[Project | None] = relationship()


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(500))
    role: Mapped[str] = mapped_column(String(20), default="sales")
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    action: Mapped[str] = mapped_column(String(80), index=True)
    entity_type: Mapped[str] = mapped_column(String(80), index=True)
    entity_id: Mapped[str | None] = mapped_column(String(80))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )
    actor: Mapped[User | None] = relationship()


class SavedSearch(Base):
    __tablename__ = "saved_searches"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_saved_search_user_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    filters: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class ActivityInput(BaseModel):
    activity_type: str = Field(min_length=1, max_length=50)
    notes: str = Field(min_length=1, max_length=4000)
    next_action: str | None = Field(default=None, max_length=300)
    sales_outcome: str | None = Field(
        default=None,
        pattern="^(contacted|interested|qualified|proposal_sent|won|lost|not_interested|no_response)$",
    )
    due_date: date | None = None
    person_id: int | None = None
    project_id: int | None = None

    @field_validator("activity_type", "notes")
    @classmethod
    def values_must_not_be_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Activity type and notes cannot be blank")
        return normalized


class RelationshipInput(BaseModel):
    company_id: int
    related_company_id: int
    relationship_type: str = Field(min_length=1, max_length=80)
    project_id: int | None = None
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("related_company_id")
    @classmethod
    def companies_must_differ(cls, value: int, info):
        if info.data.get("company_id") == value:
            raise ValueError("A company cannot be related to itself")
        return value


class LoginInput(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=200)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", normalized):
            raise ValueError("Enter a valid email address")
        return normalized


class UserInput(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=12, max_length=200)
    role: str = Field(pattern="^(admin|sales|viewer)$")

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", normalized):
            raise ValueError("Enter a valid email address")
        return normalized


class SavedSearchInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    filters: dict[str, str | int | float | bool | None]

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Saved search name cannot be blank")
        return normalized

    @field_validator("filters")
    @classmethod
    def only_supported_filters(cls, value: dict):
        supported = {"q", "category", "city", "state", "verification", "has_project"}
        if not set(value).issubset(supported):
            raise ValueError("Saved search contains unsupported filters")
        return value


class ProjectDemandInput(BaseModel):
    estimated_units: int | None = Field(default=None, ge=0)
    estimated_doors: int | None = Field(default=None, ge=0)
    doors_per_unit: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    estimate_basis: str | None = Field(default=None, max_length=300)
    demand_confidence: str = Field(default="unknown", pattern="^(unknown|low|medium|high)$")
    demand_notes: str | None = Field(default=None, max_length=4000)


class ResearchQuery(BaseModel):
    query: str = Field(min_length=3, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=10)
    include_graph: bool = True
    use_llm: bool = False

    @field_validator("query")
    @classmethod
    def query_must_not_be_blank(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 3:
            raise ValueError("Query must contain at least three non-space characters")
        return normalized


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="Sign in required")
    session = db.scalar(
        select(AuthSession).where(
            AuthSession.token_hash == token_digest(token),
            AuthSession.expires_at > datetime.now(timezone.utc),
        )
    )
    if not session:
        raise HTTPException(status_code=401, detail="Session expired; sign in again")
    user = db.get(User, session.user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Account is inactive")
    return user


def require_roles(*roles: str):
    def role_dependency(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Your role cannot perform this action")
        return user

    return role_dependency


def audit(
    db: Session,
    actor: User | None,
    action: str,
    entity_type: str,
    entity_id: str | int | None,
    details: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            actor_id=actor.id if actor else None,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            details=details or {},
        )
    )


def project_demand(project: Project) -> dict:
    if project.estimated_doors is not None:
        total_doors = project.estimated_doors
        method = "Explicit estimate"
    elif project.estimated_units is not None and project.doors_per_unit is not None:
        total_doors = round(project.estimated_units * project.doors_per_unit)
        method = (
            f"{project.estimated_units} units × {project.doors_per_unit:g} doors/unit"
        )
    else:
        total_doors = None
        method = "Insufficient inputs"
    return {
        "estimated_doors": total_doors,
        "explicit_estimated_doors": project.estimated_doors,
        "estimate_method": method,
        "estimate_basis": project.estimate_basis,
        "demand_confidence": project.demand_confidence,
    }


def lead_score(company: Company) -> dict:
    category_points = {
        "architect": 30,
        "architecture firm": 30,
        "interior designer": 30,
        "builder": 28,
        "real estate developer": 28,
        "contractor": 24,
        "construction company": 24,
        "dealer": 15,
    }
    category = company.category.lower()
    base = next((points for label, points in category_points.items() if label in category), 10)
    verified = sum(source.verification_status == "verified" for source in company.sources)
    evidence_points = min(20 + (verified - 1) * 5, 30) if verified else 0
    project_points = min(len(company.projects) * 10, 30)
    website_points = 5 if getattr(company, "website", None) else 0
    contact_points = 5 if getattr(company, "contacts", []) else 0
    score = base + evidence_points + project_points + website_points + contact_points
    reasons = [f"{company.category} is a relevant prospect category (+{base})."]
    if verified:
        reasons.append(f"{verified} source(s) have been verified (+{evidence_points}).")
    if company.projects:
        reasons.append(f"{len(company.projects)} linked project(s) (+{project_points}).")
    if website_points:
        reasons.append("A public company website is recorded (+5).")
    if contact_points:
        reasons.append("A professional business contact is linked (+5).")
    return {
        "score": score,
        "reasons": reasons,
        "components": [
            {"key": "business_relevance", "label": "Business relevance", "points": base, "maximum": 30},
            {"key": "verified_evidence", "label": "Verified evidence", "points": evidence_points, "maximum": 30},
            {"key": "project_signals", "label": "Project signals", "points": project_points, "maximum": 30},
            {"key": "public_website", "label": "Public website", "points": website_points, "maximum": 5},
            {"key": "business_contact", "label": "Business contact", "points": contact_points, "maximum": 5},
        ],
    }


def company_opportunity_report(company: Company, score: dict) -> dict:
    verified_sources = sum(source.verification_status == "verified" for source in company.sources)
    unverified_sources = sum(source.verification_status == "unverified" for source in company.sources)
    rejected_sources = sum(source.verification_status == "rejected" for source in company.sources)
    evidence_gaps = []
    recommended_actions = []

    if not verified_sources:
        evidence_gaps.append("No source has been verified.")
        recommended_actions.append(
            "Review a public company or project source and verify its claims before outreach."
        )
    if rejected_sources:
        evidence_gaps.append(f"{rejected_sources} source(s) were rejected and excluded.")
    if not company.projects:
        evidence_gaps.append("No project is linked to this company.")
        recommended_actions.append(
            "Check reviewed public announcements and project portfolios for a relevant active project."
        )
    elif any(project.demand_confidence == "unknown" for project in company.projects):
        evidence_gaps.append("At least one linked project has unknown demand confidence.")
        recommended_actions.append(
            "Confirm project phase, scope, and material requirements from a primary source."
        )
    if not company.website:
        evidence_gaps.append("No public company website is recorded.")
    if not company.contacts:
        evidence_gaps.append("No professional business contact is linked.")
        recommended_actions.append(
            "Identify and verify a role-relevant professional contact using permitted public sources."
        )
    if verified_sources and company.projects and company.contacts:
        recommended_actions.append(
            "Prioritize a human-reviewed outreach that references the verified project evidence."
        )

    open_follow_ups = sorted(
        (
            activity
            for activity in company.activities
            if activity.completed_at is None and activity.next_action
        ),
        key=lambda activity: (
            activity.due_date is None,
            activity.due_date or date.max,
            activity.created_at,
        ),
    )
    latest_outcome = next(
        (
            activity.sales_outcome
            for activity in sorted(
                company.activities,
                key=lambda activity: (activity.created_at, activity.id),
                reverse=True,
            )
            if activity.sales_outcome
        ),
        None,
    )
    if open_follow_ups:
        activity = open_follow_ups[0]
        next_sales_action = {
            "action": activity.next_action,
            "reason": "Complete the open follow-up already recorded for this prospect.",
            "due_date": activity.due_date.isoformat() if activity.due_date else None,
            "activity_id": activity.id,
            "status": "scheduled",
        }
    elif latest_outcome in {"lost", "not_interested"}:
        next_sales_action = {
            "action": "Pause proactive outreach and respect the recorded sales outcome.",
            "reason": f"The latest recorded sales outcome is {latest_outcome.replace('_', ' ')}.",
            "due_date": None,
            "activity_id": None,
            "status": "paused",
        }
    elif latest_outcome == "won":
        next_sales_action = {
            "action": "Schedule an account check-in and confirm the next project requirement.",
            "reason": "The latest recorded sales outcome is a win.",
            "due_date": None,
            "activity_id": None,
            "status": "recommended",
        }
    elif not verified_sources:
        next_sales_action = {
            "action": "Review and verify a public company or project source.",
            "reason": "No verified evidence is available to support personalized outreach.",
            "due_date": None,
            "activity_id": None,
            "status": "recommended",
        }
    elif not company.projects:
        next_sales_action = {
            "action": "Research a relevant active project using permitted public sources.",
            "reason": "No project is linked to this prospect.",
            "due_date": None,
            "activity_id": None,
            "status": "recommended",
        }
    elif not company.contacts:
        next_sales_action = {
            "action": "Identify and verify a role-relevant professional business contact.",
            "reason": "No professional contact is linked to this prospect.",
            "due_date": None,
            "activity_id": None,
            "status": "recommended",
        }
    elif any(project.demand_confidence == "unknown" for project in company.projects):
        next_sales_action = {
            "action": "Confirm the project phase, scope, and material requirements.",
            "reason": "Project demand confidence is unknown.",
            "due_date": None,
            "activity_id": None,
            "status": "recommended",
        }
    else:
        next_sales_action = {
            "action": "Prepare a personalized outreach referencing the verified project evidence.",
            "reason": "The prospect has verified evidence, a linked project, and a business contact.",
            "due_date": None,
            "activity_id": None,
            "status": "recommended",
        }

    return {
        "score": score["score"],
        "score_components": score["components"],
        "priority": (
            "high"
            if score["score"] >= 70 and verified_sources
            else "medium"
            if score["score"] >= 40
            else "low"
        ),
        "positive_signals": score["reasons"],
        "evidence_gaps": evidence_gaps,
        "recommended_actions": recommended_actions,
        "next_sales_action": next_sales_action,
        "latest_sales_outcome": latest_outcome,
        "evidence_summary": {
            "verified_sources": verified_sources,
            "unverified_sources": unverified_sources,
            "rejected_sources": rejected_sources,
            "projects": len(company.projects),
            "professional_contacts": len(company.contacts),
        },
        "human_review_required": True,
    }


def company_summary(company: Company) -> dict:
    score = lead_score(company)
    return {
        "id": company.id,
        "name": company.name,
        "category": company.category,
        "city": company.city,
        "state": company.state,
        "website": company.website,
        "public_phone": company.public_phone,
        "score": score["score"],
        "score_reasons": score["reasons"],
        "score_components": score["components"],
        "verified_source_count": sum(
            source.verification_status == "verified" for source in company.sources
        ),
        "project_count": len(company.projects),
    }


def safe_csv_cell(value: object) -> str:
    text = "" if value is None else str(value)
    if text.lstrip(" \t\r\n").startswith(("=", "+", "-", "@")):
        return f"'{text}"
    return text


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield


app = FastAPI(
    title="Vidya Timber Market Intelligence",
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:5173").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return {"status": "ok", "database": "connected"}


@app.post("/api/auth/login")
def login(payload: LoginInput, response: Response, db: Session = Depends(get_db)) -> dict:
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if not user or not user.is_active or not password_hash.verify(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    now = datetime.now(timezone.utc)
    db.execute(
        AuthSession.__table__.delete().where(AuthSession.expires_at <= now)
    )
    token = secrets.token_urlsafe(48)
    db.add(
        AuthSession(
            user_id=user.id,
            token_hash=token_digest(token),
            expires_at=now + timedelta(hours=SESSION_HOURS),
        )
    )
    audit(db, user, "login", "user", user.id)
    db.commit()
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_HOURS * 3600,
        httponly=True,
        secure=os.getenv("COOKIE_SECURE", "false").lower() == "true",
        samesite="lax",
        path="/",
    )
    return {"id": user.id, "email": user.email, "role": user.role}


@app.post("/api/auth/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        db.execute(AuthSession.__table__.delete().where(AuthSession.token_hash == token_digest(token)))
        db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="lax")
    return {"message": "Signed out"}


@app.get("/api/auth/me")
def auth_me(user: User = Depends(current_user)) -> dict:
    return {"id": user.id, "email": user.email, "role": user.role}


@app.post("/api/users", status_code=201)
def create_user(
    payload: UserInput,
    db: Session = Depends(get_db),
    actor: User = Depends(require_roles("admin")),
) -> dict:
    email = payload.email.lower()
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    user = User(email=email, password_hash=password_hash.hash(payload.password), role=payload.role)
    db.add(user)
    db.flush()
    audit(db, actor, "create", "user", user.id, {"role": user.role})
    db.commit()
    return {"id": user.id, "email": user.email, "role": user.role}


@app.get("/api/dashboard/summary")
def dashboard_summary(
    db: Session = Depends(get_db), _: User = Depends(current_user)
) -> dict:
    next_activity = db.execute(
        select(Activity, Company)
        .join(Company, Activity.company_id == Company.id)
        .where(
            Activity.next_action.is_not(None),
            Activity.next_action != "",
            Activity.completed_at.is_(None),
        )
        .order_by(
            Activity.due_date.is_(None),
            Activity.due_date,
            Activity.created_at,
            Activity.id,
        )
        .limit(1)
    ).first()
    return {
        "companies": db.scalar(select(func.count()).select_from(Company)) or 0,
        "projects": db.scalar(select(func.count()).select_from(Project)) or 0,
        "verified_sources": db.scalar(
            select(func.count()).select_from(Source).where(Source.verification_status == "verified")
        ) or 0,
        "open_follow_ups": db.scalar(
            select(func.count())
            .select_from(Activity)
            .where(
                Activity.next_action.is_not(None),
                Activity.next_action != "",
                Activity.completed_at.is_(None),
            )
        ) or 0,
        "next_action": (
            {
                "activity_id": next_activity.Activity.id,
                "company_id": next_activity.Company.id,
                "company_name": next_activity.Company.name,
                "action": next_activity.Activity.next_action,
                "due_date": (
                    next_activity.Activity.due_date.isoformat()
                    if next_activity.Activity.due_date
                    else None
                ),
            }
            if next_activity
            else None
        ),
    }


@app.get("/api/companies")
def list_companies(
    response: Response,
    q: str | None = None,
    category: str | None = None,
    city: str | None = None,
    state: str | None = None,
    verification: str | None = Query(default=None, pattern="^(verified|unverified)$"),
    has_project: bool | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(current_user),
) -> list[dict]:
    filters = []
    if q:
        term = f"%{q.strip()}%"
        filters.append(
            or_(
                Company.name.ilike(term),
                Company.category.ilike(term),
                Company.city.ilike(term),
                Company.state.ilike(term),
            )
        )
    if category:
        filters.append(Company.category == category)
    if city:
        filters.append(Company.city.ilike(f"%{city.strip()}%"))
    if state:
        filters.append(Company.state.ilike(f"%{state.strip()}%"))
    if verification == "verified":
        filters.append(
            Company.sources.any(Source.verification_status == "verified")
        )
    elif verification == "unverified":
        filters.append(
            Company.sources.any(Source.verification_status == "unverified")
        )
    if has_project is True:
        filters.append(Company.projects.any())
    elif has_project is False:
        filters.append(~Company.projects.any())
    statement = select(Company).where(*filters).order_by(Company.name, Company.city, Company.id)
    total = db.scalar(select(func.count()).select_from(Company).where(*filters)) or 0
    response.headers["X-Total-Count"] = str(total)
    statement = statement.limit(limit).offset(offset)
    companies = db.scalars(statement).unique().all()
    for company in companies:
        _ = company.sources, company.projects
    return [company_summary(company) for company in companies]


@app.get("/api/knowledge-graph")
def get_knowledge_graph(
    q: str | None = None,
    city: str | None = None,
    state: str | None = None,
    limit: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),
    _: User = Depends(current_user),
) -> dict:
    company_filters = []
    if q and q.strip():
        term = f"%{q.strip()}%"
        company_filters.append(
            or_(
                Company.name.ilike(term),
                Company.category.ilike(term),
                Company.city.ilike(term),
                Company.state.ilike(term),
            )
        )
    if city and city.strip():
        company_filters.append(Company.city.ilike(f"%{city.strip()}%"))
    if state and state.strip():
        company_filters.append(Company.state.ilike(f"%{state.strip()}%"))

    company_query = (
        select(Company)
        .where(*company_filters)
        .options(joinedload(Company.sources), joinedload(Company.projects))
        .order_by(Company.name, Company.id)
    )
    total_companies = db.scalar(
        select(func.count()).select_from(Company).where(*company_filters)
    ) or 0
    companies = db.scalars(company_query.limit(limit)).unique().all()
    company_ids = [company.id for company in companies]

    nodes = [
        {
            "id": f"company-{company.id}",
            "type": "company",
            "entity_id": company.id,
            "label": company.name,
            "category": company.category,
            "city": company.city,
            "score": lead_score(company)["score"],
            "verified_sources": sum(
                source.verification_status == "verified" for source in company.sources
            ),
            "project_count": len(company.projects),
        }
        for company in companies
    ]
    edges = []
    project_nodes = []
    if company_ids:
        company_city = {company.id: company.city for company in companies}
        projects = db.scalars(
            select(Project)
            .where(Project.company_id.in_(company_ids))
            .order_by(Project.name, Project.id)
            .limit(300)
        ).all()
        for project in projects:
            project_nodes.append(
                {
                    "id": f"project-{project.id}",
                    "type": "project",
                    "entity_id": project.id,
                    "label": project.name,
                    "status": project.status,
                    "city": project.location or company_city[project.company_id],
                    "company_id": project.company_id,
                    "estimated_units": project.estimated_units,
                    "estimated_doors": project_demand(project)["estimated_doors"],
                    "demand_confidence": project.demand_confidence,
                }
            )
            edges.append(
                {
                    "id": f"company-project-{project.company_id}-{project.id}",
                    "source": f"company-{project.company_id}",
                    "target": f"project-{project.id}",
                    "type": "has project",
                }
            )

        relations = db.scalars(
            select(BusinessRelationship)
            .where(
                BusinessRelationship.company_id.in_(company_ids),
                BusinessRelationship.related_company_id.in_(company_ids),
            )
            .order_by(BusinessRelationship.id)
        ).all()
        for relation in relations:
            edges.append(
                {
                    "id": f"relationship-{relation.id}",
                    "source": f"company-{relation.company_id}",
                    "target": f"company-{relation.related_company_id}",
                    "type": relation.relationship_type,
                    "project_id": relation.project_id,
                }
            )

    total_projects = (
        db.scalar(
            select(func.count())
            .select_from(Project)
            .join(Company, Project.company_id == Company.id)
            .where(*company_filters)
        )
        if total_companies
        else 0
    ) or 0
    return {
        "nodes": nodes + project_nodes,
        "edges": edges,
        "total_companies": total_companies,
        "included_companies": len(companies),
        "total_projects": total_projects,
        "included_projects": len(project_nodes),
        "truncated": total_companies > len(companies) or total_projects > len(project_nodes),
    }


@app.get("/api/categories")
def list_categories(
    db: Session = Depends(get_db), _: User = Depends(current_user)
) -> list[str]:
    categories = db.scalars(
        select(Company.category).distinct().order_by(Company.category)
    ).all()
    return list(categories)


@app.get("/api/companies/{company_id}")
def get_company(
    company_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(current_user),
) -> dict:
    company = db.get(Company, company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    _ = company.sources, company.projects, company.activities
    relations = db.scalars(
        select(BusinessRelationship).where(
            or_(
                BusinessRelationship.company_id == company_id,
                BusinessRelationship.related_company_id == company_id,
            )
        )
    ).all()
    summary = company_summary(company)
    return {
        **summary,
        "description": company.description,
        "opportunity_report": company_opportunity_report(company, lead_score(company)),
        "contacts": [
            {
                "id": link.person.id,
                "name": link.person.name,
                "business_email": link.person.business_email,
                "business_phone": link.person.business_phone,
                "job_title": link.job_title,
                "source_url": link.source.url if link.source else None,
                "verification_status": (
                    link.source.verification_status if link.source else None
                ),
                "discovered_at": (
                    link.source.discovered_at.isoformat() if link.source else None
                ),
            }
            for link in company.contacts
        ],
        "sources": [
            {
                "id": source.id,
                "url": source.url,
                "title": source.title,
                "source_type": source.source_type,
                "verification_status": source.verification_status,
                "discovered_at": source.discovered_at.isoformat(),
                "has_content": bool(source.content and source.content.strip()),
            }
            for source in company.sources
        ],
        "projects": [
            {
                "id": project.id,
                "name": project.name,
                "location": project.location,
                "status": project.status,
                "estimated_units": project.estimated_units,
                **project_demand(project),
                "doors_per_unit": project.doors_per_unit,
                "demand_notes": project.demand_notes,
            }
            for project in company.projects
        ],
        "relationships": [
            {
                "id": relation.id,
                "company_id": relation.company_id,
                "related_company_id": relation.related_company_id,
                "related_company_name": (
                    relation.related_company.name
                    if relation.company_id == company_id
                    else relation.company.name
                ),
                "relationship_type": relation.relationship_type,
                "project_name": relation.project.name if relation.project else None,
                "notes": relation.notes,
            }
            for relation in relations
        ],
        "activities": [
            {
                "id": activity.id,
                "activity_type": activity.activity_type,
                "notes": activity.notes,
                "person_id": activity.person_id,
                "person_name": activity.person.name if activity.person else None,
                "project_id": activity.project_id,
                "project_name": activity.project.name if activity.project else None,
                "next_action": activity.next_action,
                "sales_outcome": activity.sales_outcome,
                "due_date": activity.due_date.isoformat() if activity.due_date else None,
                "completed_at": activity.completed_at.isoformat() if activity.completed_at else None,
                "created_at": activity.created_at.isoformat(),
            }
            for activity in sorted(company.activities, key=lambda item: item.created_at, reverse=True)
        ],
    }


@app.post("/api/companies/{company_id}/ai-enrichment")
def enrich_company_with_ai(
    company_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(current_user),
) -> dict:
    company = db.get(Company, company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    verified_sources = sorted(
        (
            source for source in company.sources
            if source.verification_status == "verified" and source.content
        ),
        key=lambda source: (source.discovered_at, source.id),
        reverse=True,
    )[:5]
    try:
        result = run_company_enrichment(company.name, verified_sources)
    except RuntimeError as exc:
        status_code = 503 if "not configured" in str(exc) else 502
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc

    audit(
        db,
        actor,
        "ai_enrichment",
        "company",
        str(company.id),
        {
            "claims": len(result["claims"]),
            "sources_used": len(result["sources_used"]),
            "model": result["model"],
            "persisted": False,
        },
    )
    db.commit()
    return {
        **result,
        "company_id": company.id,
        "company_name": company.name,
        "persisted": False,
        "human_review_required": True,
    }


@app.post("/api/companies/{company_id}/activities", status_code=201)
def create_activity(
    company_id: int,
    payload: ActivityInput,
    db: Session = Depends(get_db),
    actor: User = Depends(require_roles("admin", "sales")),
) -> dict:
    if not db.get(Company, company_id):
        raise HTTPException(status_code=404, detail="Company not found")
    if payload.person_id is not None and not db.scalar(
        select(CompanyPerson).where(
            CompanyPerson.company_id == company_id,
            CompanyPerson.person_id == payload.person_id,
        )
    ):
        raise HTTPException(status_code=422, detail="Contact must be linked to this company")
    if payload.project_id is not None and not db.scalar(
        select(Project.id).where(
            Project.id == payload.project_id,
            Project.company_id == company_id,
        )
    ):
        raise HTTPException(status_code=422, detail="Project must belong to this company")
    activity = Activity(company_id=company_id, **payload.model_dump())
    db.add(activity)
    db.flush()
    audit(db, actor, "create", "activity", activity.id, {"company_id": company_id})
    db.commit()
    db.refresh(activity)
    return {"id": activity.id, "message": "Activity recorded"}


@app.post("/api/activities/{activity_id}/complete")
def complete_activity(
    activity_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(require_roles("admin", "sales")),
) -> dict:
    activity = db.get(Activity, activity_id)
    if not activity:
        raise HTTPException(status_code=404, detail="Activity not found")
    if activity.completed_at is None:
        activity.completed_at = datetime.now(timezone.utc)
        audit(db, actor, "complete", "activity", activity.id, {"company_id": activity.company_id})
        db.commit()
    return {"id": activity.id, "message": "Follow-up completed"}


@app.post("/api/relationships", status_code=201)
def create_relationship(
    payload: RelationshipInput,
    db: Session = Depends(get_db),
    actor: User = Depends(require_roles("admin", "sales")),
) -> dict:
    source = db.get(Company, payload.company_id)
    target = db.get(Company, payload.related_company_id)
    if not source or not target:
        raise HTTPException(status_code=404, detail="Both companies must exist")
    project = db.get(Project, payload.project_id) if payload.project_id else None
    if payload.project_id and not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if project and project.company_id not in {source.id, target.id}:
        raise HTTPException(status_code=422, detail="Project must belong to one of the linked companies")
    duplicate = db.scalar(
        select(BusinessRelationship.id).where(
            BusinessRelationship.company_id == payload.company_id,
            BusinessRelationship.related_company_id == payload.related_company_id,
            BusinessRelationship.relationship_type == payload.relationship_type,
            BusinessRelationship.project_id == payload.project_id,
        )
    )
    if duplicate is not None:
        raise HTTPException(status_code=409, detail="This relationship already exists")
    relation = BusinessRelationship(**payload.model_dump())
    db.add(relation)
    try:
        db.flush()
        audit(db, actor, "create", "relationship", relation.id)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="This relationship already exists") from exc
    db.refresh(relation)
    return {"id": relation.id, "message": "Relationship recorded"}


@app.delete("/api/relationships/{relationship_id}", status_code=204)
def delete_relationship(
    relationship_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(require_roles("admin", "sales")),
) -> Response:
    relation = db.get(BusinessRelationship, relationship_id)
    if not relation:
        raise HTTPException(status_code=404, detail="Relationship not found")
    audit(
        db,
        actor,
        "delete",
        "relationship",
        relation.id,
        {"company_id": relation.company_id, "related_company_id": relation.related_company_id},
    )
    db.delete(relation)
    db.commit()
    return Response(status_code=204)


@app.patch("/api/projects/{project_id}/demand")
def update_project_demand(
    project_id: int,
    payload: ProjectDemandInput,
    db: Session = Depends(get_db),
    actor: User = Depends(require_roles("admin", "sales")),
) -> dict:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    for key, value in payload.model_dump().items():
        setattr(project, key, value)
    audit(
        db,
        actor,
        "update_demand",
        "project",
        project.id,
        {"estimate_basis": project.estimate_basis, "demand_confidence": project.demand_confidence},
    )
    db.commit()
    return {"id": project.id, **project_demand(project)}


@app.get("/api/saved-searches")
def list_saved_searches(
    db: Session = Depends(get_db), user: User = Depends(current_user)
) -> list[dict]:
    searches = db.scalars(
        select(SavedSearch).where(SavedSearch.user_id == user.id).order_by(SavedSearch.name)
    ).all()
    return [{"id": item.id, "name": item.name, "filters": item.filters} for item in searches]


@app.post("/api/saved-searches", status_code=201)
def create_saved_search(
    payload: SavedSearchInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    search = SavedSearch(user_id=user.id, name=payload.name.strip(), filters=payload.filters)
    db.add(search)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="A saved search with this name already exists") from exc
    db.refresh(search)
    return {"id": search.id, "name": search.name, "filters": search.filters}


@app.delete("/api/saved-searches/{search_id}", status_code=204)
def delete_saved_search(
    search_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> Response:
    search = db.scalar(
        select(SavedSearch).where(SavedSearch.id == search_id, SavedSearch.user_id == user.id)
    )
    if not search:
        raise HTTPException(status_code=404, detail="Saved search not found")
    db.delete(search)
    db.commit()
    return Response(status_code=204)


@app.get("/api/audit")
def list_audit_events(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("admin")),
) -> list[dict]:
    events = db.scalars(
        select(AuditLog).order_by(AuditLog.occurred_at.desc()).limit(limit)
    ).all()
    return [
        {
            "id": item.id,
            "actor_email": item.actor.email if item.actor else None,
            "action": item.action,
            "entity_type": item.entity_type,
            "entity_id": item.entity_id,
            "details": item.details,
            "occurred_at": item.occurred_at.isoformat(),
        }
        for item in events
    ]


@app.post("/api/research/query")
def research_query(
    payload: ResearchQuery,
    db: Session = Depends(get_db),
    actor: User = Depends(current_user),
) -> dict:
    try:
        result = run_research(
            payload.query,
            db,
            top_k=payload.top_k,
            include_graph=payload.include_graph,
            use_llm=payload.use_llm,
        )
    except RuntimeError as exc:
        status_code = 503 if "not configured" in str(exc) else 502
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    audit(
        db,
        actor,
        "research",
        "query",
        None,
        {
            "mode": result["mode"],
            "evidence_count": len(result["evidence"]),
            "graph_neighbor_count": result["graph_neighbors"],
            "used_llm": result["mode"] == "openai",
        },
    )
    db.commit()
    return result


@app.get("/api/research/status")
def research_status(_: User = Depends(current_user)) -> dict:
    return {
        "generation_available": bool(os.getenv("RAG_OPENAI_API_KEY", "").strip()),
        "provider": "OpenAI-compatible API",
        "model": os.getenv("RAG_OPENAI_MODEL", "gpt-4o-mini"),
        "privacy": "AI is opt-in. Only verified source excerpts are sent for explicitly requested answers or enrichment.",
    }


@app.post("/api/import/csv")
async def import_csv(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    actor: User = Depends(require_roles("admin")),
) -> dict:
    raw = await file.read(5_000_001)
    if len(raw) > 5_000_000:
        raise HTTPException(status_code=413, detail="CSV must be 5 MB or smaller")
    try:
        result = run_prospect_import(raw, db)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Import conflicts with records added at the same time; please retry.",
        ) from exc
    if result["fatal_error"]:
        db.rollback()
        raise HTTPException(status_code=400, detail=result["fatal_error"])
    if result["errors"]:
        db.rollback()
        raise HTTPException(status_code=422, detail={"row_errors": result["errors"]})
    counts = result["counts"]
    audit(
        db,
        actor,
        "import",
        "csv",
        None,
        {
            **counts,
            "filename": file.filename,
            "workflow": "prospect_csv_import",
            "workflow_stages": result["stages"],
            "duplicate_rows_skipped": result["duplicate_rows"],
            "score_preview": result["score_summary"],
        },
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Import conflicts with records added at the same time; please retry.",
        ) from exc
    return {
        **counts,
        "workflow": {
            "name": "prospect_csv_import",
            "stages": result["stages"],
            "duplicate_rows_skipped": result["duplicate_rows"],
            "score_preview": result["score_summary"],
        },
    }


@app.get("/api/export.csv")
def export_csv(
    db: Session = Depends(get_db), _: User = Depends(current_user)
):
    companies = db.scalars(
        select(Company)
        .options(
            joinedload(Company.sources),
            joinedload(Company.projects),
            joinedload(Company.contacts).joinedload(CompanyPerson.person),
            joinedload(Company.contacts).joinedload(CompanyPerson.source),
            joinedload(Company.activities),
        )
        .order_by(Company.name, Company.city, Company.id)
    ).unique().all()
    all_relationships = db.scalars(
        select(BusinessRelationship)
        .options(
            joinedload(BusinessRelationship.company),
            joinedload(BusinessRelationship.related_company),
            joinedload(BusinessRelationship.project),
        )
        .order_by(BusinessRelationship.id)
    ).unique().all()
    relationships_by_company: dict[int, list[BusinessRelationship]] = {}
    for relation in all_relationships:
        relationships_by_company.setdefault(relation.company_id, []).append(relation)
        relationships_by_company.setdefault(relation.related_company_id, []).append(relation)
    output = io.StringIO()
    fields = [
        "name", "category", "city", "state", "website", "public_phone", "score",
        "score_reasons", "project_count", "projects", "source_url", "source_type",
        "verification_status", "discovered_at", "source_references", "business_relationships",
        "professional_contacts", "sales_activity", "latest_sales_outcome",
        "next_recommended_action",
    ]
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for company in companies:
        sources = sorted(
            company.sources,
            key=lambda item: (item.discovered_at, item.id),
            reverse=True,
        )
        activities = sorted(
            company.activities,
            key=lambda item: (item.created_at, item.id),
            reverse=True,
        )
        relationships = relationships_by_company.get(company.id, [])
        score = lead_score(company)
        opportunity = company_opportunity_report(company, score)
        source = sources[0] if sources else None
        source_references = " | ".join(
            f"{item.title or item.source_type} [{item.verification_status}] "
            f"{item.url} (discovered {item.discovered_at.isoformat()})"
            for item in sources
        )
        project_signals = " | ".join(
            f"{project.name} [{project.status}]"
            + (f" at {project.location}" if project.location else "")
            for project in sorted(company.projects, key=lambda item: (item.name, item.id))
        )
        relationship_labels = " | ".join(
            (
                f"{relation.company.name} -[{relation.relationship_type}]-> "
                f"{relation.related_company.name}"
            )
            + (f" ({relation.project.name})" if relation.project else "")
            for relation in relationships
        )
        contact_labels = " | ".join(
            f"{link.person.name}"
            + (f" ({link.job_title})" if link.job_title else "")
            + (f" <{link.person.business_email}>" if link.person.business_email else "")
            + (f" {link.person.business_phone}" if link.person.business_phone else "")
            + (f" [{link.source.verification_status}]" if link.source else "")
            for link in company.contacts
        )
        activity_labels = " | ".join(
            f"{item.created_at.date().isoformat()} {item.activity_type}"
            + (f" [{item.sales_outcome}]" if item.sales_outcome else "")
            + f": {item.notes}"
            + (f"; next: {item.next_action}" if item.next_action else "")
            for item in activities
        )
        writer.writerow(
            {
                key: safe_csv_cell(value)
                for key, value in {
                    "name": company.name,
                    "category": company.category,
                    "city": company.city,
                    "state": company.state,
                    "website": company.website or "",
                    "public_phone": company.public_phone or "",
                    "score": score["score"],
                    "score_reasons": " | ".join(score["reasons"]),
                    "project_count": len(company.projects),
                    "projects": project_signals,
                    "source_url": source.url if source else "",
                    "source_type": source.source_type if source else "",
                    "verification_status": source.verification_status if source else "",
                    "discovered_at": source.discovered_at.isoformat() if source else "",
                    "source_references": source_references,
                    "business_relationships": relationship_labels,
                    "professional_contacts": contact_labels,
                    "sales_activity": activity_labels,
                    "latest_sales_outcome": opportunity["latest_sales_outcome"] or "",
                    "next_recommended_action": opportunity["next_sales_action"]["action"],
                }.items()
            }
        )
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="vidya-prospects.csv"'},
    )
