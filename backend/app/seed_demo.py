"""Seed fictional, clearly labeled sales-demo records and a demo login."""
from __future__ import annotations

import os
import secrets
from datetime import date, timedelta

from sqlalchemy import select

from app import main


DEMO_MARKER = (
    "SYNTHETIC DEMO ONLY - not real business, contact, project, or source information."
)
COMPANY_SPECS = (
    {
        "name": "DEMO | Ganga Buildworks",
        "category": "Builder",
        "project": "DEMO | Riverfront Homes",
        "contact": "Demo Contact - Asha Rao",
        "email": "asha@ganga-buildworks.example",
        "role": "Procurement Lead",
        "url": "https://example.com/demo/ganga-buildworks",
        "outcome": "interested",
        "action": "DEMO: Share the sample materials catalogue after the walkthrough.",
        "relationship": "architect for",
    },
    {
        "name": "DEMO | Kashi Design Studio",
        "category": "Architect",
        "project": "DEMO | Sarnath Courtyard",
        "contact": "Demo Contact - Kabir Mehta",
        "email": "kabir@kashi-design.example",
        "role": "Studio Director",
        "url": "https://example.com/demo/kashi-design-studio",
        "outcome": "contacted",
        "action": "DEMO: Schedule a sample review meeting.",
        "relationship": None,
    },
    {
        "name": "DEMO | Sarnath Works",
        "category": "Contractor",
        "project": "DEMO | Heritage Market Fit-out",
        "contact": "Demo Contact - Mira Sen",
        "email": "mira@sarnath-works.example",
        "role": "Project Manager",
        "url": "https://example.com/demo/sarnath-works",
        "outcome": "no_response",
        "action": "DEMO: Follow up on the fictional market fit-out.",
        "relationship": None,
    },
)


def seed_demo() -> tuple[str, str, int]:
    password = secrets.token_urlsafe(24)
    with main.SessionLocal() as db:
        user = db.scalar(
            select(main.User).where(main.User.email == "demo@vidya.local")
        )
        if user is None:
            user = main.User(
                email="demo@vidya.local",
                password_hash=main.password_hash.hash(password),
                role="sales",
                is_active=True,
            )
            db.add(user)
        else:
            user.password_hash = main.password_hash.hash(password)
            user.role = "sales"
            user.is_active = True

        admin_email = os.getenv("BOOTSTRAP_ADMIN_EMAIL", "admin@vidya.local")
        admin = db.scalar(select(main.User).where(main.User.email == admin_email))
        city, state = "Varanasi", "Uttar Pradesh"
        location = db.scalar(
            select(main.Location).where(
                main.Location.city_key == city.casefold(),
                main.Location.state_key == state.casefold(),
            )
        )
        if location is None:
            location = main.Location(
                city=city,
                state=state,
                city_key=city.casefold(),
                state_key=state.casefold(),
            )
            db.add(location)
            db.flush()

        companies = {}
        projects = {}
        for spec in COMPANY_SPECS:
            company = db.scalar(
                select(main.Company).where(
                    main.Company.name == spec["name"],
                    main.Company.city == city,
                    main.Company.state == state,
                )
            )
            if company is None:
                company = main.Company(
                    name=spec["name"],
                    category=spec["category"],
                    city=city,
                    state=state,
                    location=location,
                )
                db.add(company)
                db.flush()
            company.description = DEMO_MARKER
            company.location = location

            project = db.scalar(
                select(main.Project).where(
                    main.Project.company_id == company.id,
                    main.Project.name == spec["project"],
                )
            )
            if project is None:
                project = main.Project(
                    company=company,
                    name=spec["project"],
                    location=city,
                    status="planning",
                    estimated_units=24,
                    doors_per_unit=3.0,
                    estimate_basis="Synthetic demo assumptions only",
                    demand_confidence="low",
                    demand_notes=DEMO_MARKER,
                    location_ref=location,
                )
                db.add(project)
                db.flush()

            source = db.scalar(
                select(main.Source).where(main.Source.url == spec["url"])
            )
            if source is None:
                source = main.Source(
                    company=company,
                    project=project,
                    url=spec["url"],
                    title=f"DEMO SOURCE ONLY - {spec['name']}",
                    source_type="demo",
                    verification_status="unverified",
                    content=DEMO_MARKER,
                    discovered_at=date.today(),
                )
                db.add(source)
                db.flush()
            else:
                source.company = company
                source.project = project
                source.title = f"DEMO SOURCE ONLY - {spec['name']}"
                source.source_type = "demo"
                source.verification_status = "unverified"
                source.content = DEMO_MARKER

            person = db.scalar(
                select(main.Person).where(
                    main.Person.business_email == spec["email"]
                )
            )
            if person is None:
                person = main.Person(
                    name=spec["contact"],
                    business_email=spec["email"],
                )
                db.add(person)
                db.flush()
            person.name = spec["contact"]

            link = db.get(main.CompanyPerson, (company.id, person.id))
            if link is None:
                db.add(
                    main.CompanyPerson(
                        company=company,
                        person=person,
                        job_title=spec["role"],
                        source=source,
                    )
                )
            else:
                link.job_title = spec["role"]
                link.source = source

            activity_note = (
                f"{DEMO_MARKER} Demo {spec['outcome'].replace('_', ' ')} call."
            )
            activity = db.scalar(
                select(main.Activity).where(
                    main.Activity.company_id == company.id,
                    main.Activity.notes == activity_note,
                )
            )
            if activity is None:
                db.add(
                    main.Activity(
                        company=company,
                        project=project,
                        person=person,
                        activity_type="call",
                        notes=activity_note,
                        sales_outcome=spec["outcome"],
                        next_action=spec["action"],
                        due_date=date.today() + timedelta(days=1),
                    )
                )
            else:
                activity.project = project
                activity.person = person
                activity.sales_outcome = spec["outcome"]
                activity.next_action = spec["action"]
                activity.due_date = date.today() + timedelta(days=1)
                activity.completed_at = None

            companies[spec["name"]] = company
            projects[spec["name"]] = project

        builder = companies["DEMO | Ganga Buildworks"]
        architect = companies["DEMO | Kashi Design Studio"]
        builder_project = projects["DEMO | Ganga Buildworks"]
        relation = db.scalar(
            select(main.BusinessRelationship).where(
                main.BusinessRelationship.company_id == builder.id,
                main.BusinessRelationship.related_company_id == architect.id,
                main.BusinessRelationship.relationship_type == "architect for",
                main.BusinessRelationship.project_id == builder_project.id,
            )
        )
        if relation is None:
            db.add(
                main.BusinessRelationship(
                    company=builder,
                    related_company=architect,
                    project=builder_project,
                    relationship_type="architect for",
                    notes=DEMO_MARKER,
                )
            )

        if admin is not None:
            db.add(
                main.AuditLog(
                    actor=admin,
                    action="seed_demo",
                    entity_type="demo_dataset",
                    entity_id="vidya-demo-v1",
                    details={
                        "synthetic_companies": len(COMPANY_SPECS),
                        "human_review_required": True,
                    },
                )
            )
        db.commit()
        return "demo@vidya.local", password, len(COMPANY_SPECS)


if __name__ == "__main__":
    email, password, company_count = seed_demo()
    print(f"Demo login: {email}")
    print(f"Demo password: {password}")
    print(f"Synthetic demo prospects seeded: {company_count}")
