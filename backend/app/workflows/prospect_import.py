from __future__ import annotations

import csv
import io
from typing import Any, TypedDict
from urllib.parse import urlparse

from langgraph.graph import END, START, StateGraph
from sqlalchemy import func, select
from sqlalchemy.orm import Session


REQUIRED_COLUMNS = {"name", "category", "city", "state", "source_url"}
VERIFICATION_STATES = {"verified", "unverified", "rejected"}
DEMAND_CONFIDENCE = {"unknown", "low", "medium", "high"}
CATEGORY_POINTS = {
    "architect": 30,
    "architecture firm": 30,
    "interior designer": 30,
    "builder": 28,
    "real estate developer": 28,
    "contractor": 24,
    "construction company": 24,
    "dealer": 15,
}


class ImportState(TypedDict):
    raw_csv: bytes
    db: Session
    records: list[dict[str, Any]]
    errors: list[str]
    stages: list[str]
    duplicate_rows: int
    counts: dict[str, int]
    score_summary: dict[str, float | int] | None
    content_sources: int
    fatal_error: str | None


def parse_csv(state: ImportState) -> dict:
    try:
        content = state["raw_csv"].decode("utf-8-sig")
    except UnicodeDecodeError:
        return {
            "fatal_error": "CSV must use UTF-8 encoding",
            "errors": [],
            "records": [],
            "stages": state["stages"] + ["parse"],
        }

    try:
        reader = csv.DictReader(io.StringIO(content))
        if not reader.fieldnames or not REQUIRED_COLUMNS.issubset(set(reader.fieldnames)):
            missing = sorted(REQUIRED_COLUMNS - set(reader.fieldnames or []))
            return {
                "errors": [f"CSV is missing required columns: {', '.join(missing)}"],
                "records": [],
                "stages": state["stages"] + ["parse"],
            }
        records = [
            {"row_number": row_number, **{key: value or "" for key, value in row.items() if key}}
            for row_number, row in enumerate(reader, start=2)
        ]
    except csv.Error as exc:
        return {
            "errors": [f"CSV could not be parsed: {exc}"],
            "records": [],
            "stages": state["stages"] + ["parse"],
        }

    return {
        "records": records,
        "errors": [],
        "fatal_error": None,
        "stages": state["stages"] + ["parse"],
    }


def validate_and_normalize(state: ImportState) -> dict:
    errors = list(state["errors"])
    records = []
    for row in state["records"]:
        number = row["row_number"]
        record = {key: value.strip() for key, value in row.items() if isinstance(value, str)}
        missing = [key for key in ("name", "category", "city", "state", "source_url") if not record.get(key)]
        if missing:
            errors.append(f"Row {number}: {', '.join(missing)} are required")
            continue
        if len(record.get("source_content", "")) > 20000:
            errors.append(f"Row {number}: source_content must be 20,000 characters or fewer")
            continue

        parsed_url = urlparse(record["source_url"])
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            errors.append(f"Row {number}: source_url must be an http or https URL")
            continue

        verification = (record.get("verification_status") or "unverified").lower()
        if verification not in VERIFICATION_STATES:
            errors.append(
                f"Row {number}: verification_status must be verified, unverified, or rejected"
            )
            continue

        invalid = False
        for field in ("estimated_units", "estimated_doors"):
            raw_value = record.get(field, "")
            if raw_value:
                try:
                    value = int(raw_value)
                    if value < 0:
                        raise ValueError
                    record[field] = value
                except ValueError:
                    errors.append(f"Row {number}: {field} must be a non-negative whole number")
                    invalid = True
            else:
                record[field] = None

        raw_doors_per_unit = record.get("doors_per_unit", "")
        if raw_doors_per_unit:
            try:
                doors_per_unit = float(raw_doors_per_unit)
                if not 0 <= doors_per_unit <= 100:
                    raise ValueError
                record["doors_per_unit"] = doors_per_unit
            except ValueError:
                errors.append(f"Row {number}: doors_per_unit must be between 0 and 100")
                invalid = True
        else:
            record["doors_per_unit"] = None

        confidence = (record.get("demand_confidence") or "unknown").lower()
        if confidence not in DEMAND_CONFIDENCE:
            errors.append(
                f"Row {number}: demand_confidence must be unknown, low, medium, or high"
            )
            invalid = True
        record["demand_confidence"] = confidence
        record["verification_status"] = verification
        if not invalid:
            records.append(record)

    return {
        "records": records,
        "errors": errors,
        "stages": state["stages"] + ["validate_normalize"],
    }


def deduplicate(state: ImportState) -> dict:
    seen = set()
    unique_records = []
    duplicate_rows = 0
    for record in state["records"]:
        key = (
            record["name"].casefold(),
            record["city"].casefold(),
            record["source_url"].casefold(),
            record.get("project_name", "").casefold(),
        )
        if key in seen:
            duplicate_rows += 1
            continue
        seen.add(key)
        unique_records.append(record)
    return {
        "records": unique_records,
        "duplicate_rows": duplicate_rows,
        "stages": state["stages"] + ["deduplicate"],
    }


def enrich_and_score(state: ImportState) -> dict:
    records = []
    scores = []
    for record in state["records"]:
        enriched = dict(record)
        if (
            enriched["estimated_doors"] is None
            and enriched["estimated_units"] is not None
            and enriched["doors_per_unit"] is not None
        ):
            enriched["calculated_doors"] = int(
                enriched["estimated_units"] * enriched["doors_per_unit"] + 0.5
            )
        else:
            enriched["calculated_doors"] = enriched["estimated_doors"]

        category = enriched["category"].casefold()
        category_points = next(
            (points for label, points in CATEGORY_POINTS.items() if label in category), 10
        )
        verified_points = 20 if enriched["verification_status"] == "verified" else 0
        project_points = 10 if enriched.get("project_name") else 0
        enriched["score_preview"] = min(
            category_points + verified_points + project_points, 100
        )
        records.append(enriched)
        scores.append(enriched["score_preview"])

    score_summary = None
    if scores:
        score_summary = {
            "average": round(sum(scores) / len(scores), 1),
            "minimum": min(scores),
            "maximum": max(scores),
        }
    return {
        "records": records,
        "score_summary": score_summary,
        "stages": state["stages"] + ["enrich_and_score"],
    }


def persist_records(state: ImportState) -> dict:
    from app.main import Company, Project, Source

    db = state["db"]
    created_companies = created_sources = created_projects = content_sources = 0
    for row in state["records"]:
        company = db.scalar(
            select(Company).where(
                func.lower(Company.name) == row["name"].casefold(),
                func.lower(Company.city) == row["city"].casefold(),
            )
        )
        if company is None:
            company = Company(
                name=row["name"],
                category=row["category"],
                city=row["city"],
                state=row["state"],
                website=row.get("website") or None,
                public_phone=row.get("public_phone") or None,
                description=row.get("description") or None,
            )
            db.add(company)
            db.flush()
            created_companies += 1

        project_name = row.get("project_name", "")
        project = next(
            (item for item in company.projects if item.name.casefold() == project_name.casefold()),
            None,
        ) if project_name else None
        if project_name and project is None:
            project = Project(
                company=company,
                name=project_name,
                location=row.get("project_location") or None,
                status=row.get("project_status") or "announced",
                estimated_units=row.get("estimated_units"),
                estimated_doors=row.get("estimated_doors"),
                doors_per_unit=row.get("doors_per_unit"),
                estimate_basis=row.get("estimate_basis") or None,
                demand_confidence=row["demand_confidence"],
                demand_notes=row.get("demand_notes") or None,
            )
            db.add(project)
            created_projects += 1
        elif project is not None:
            if project.estimated_units is None:
                project.estimated_units = row.get("estimated_units")
            if project.estimated_doors is None:
                project.estimated_doors = row.get("estimated_doors")
            if project.doors_per_unit is None:
                project.doors_per_unit = row.get("doors_per_unit")
            if project.estimate_basis is None:
                project.estimate_basis = row.get("estimate_basis") or None

        source_url = row["source_url"]
        existing_source = next(
            (source for source in company.sources if source.url.casefold() == source_url.casefold()),
            None,
        )
        source_content = row.get("source_content", "").strip()
        if existing_source is None:
            db.add(
                Source(
                    company=company,
                    project=project,
                    url=source_url,
                    title=row.get("source_title") or None,
                    source_type=row.get("source_type") or "website",
                    verification_status=row["verification_status"],
                    content=source_content or None,
                )
            )
            created_sources += 1
            content_sources += int(bool(source_content))
        elif source_content and not existing_source.content:
            existing_source.content = source_content
            content_sources += 1

    counts = {
        "companies_created": created_companies,
        "sources_created": created_sources,
        "projects_created": created_projects,
        "source_contents_added": content_sources,
    }
    return {"counts": counts, "stages": state["stages"] + ["persist"]}


def finish_without_persist(state: ImportState) -> dict:
    return {"stages": state["stages"] + ["persist_skipped"]}


def validation_passed(state: ImportState) -> str:
    return "deduplicate" if not state["errors"] and not state["fatal_error"] else "persist_skipped"


builder = StateGraph(ImportState)
builder.add_node("parse", parse_csv)
builder.add_node("validate_normalize", validate_and_normalize)
builder.add_node("deduplicate", deduplicate)
builder.add_node("enrich_and_score", enrich_and_score)
builder.add_node("persist", persist_records)
builder.add_node("persist_skipped", finish_without_persist)
builder.add_edge(START, "parse")
builder.add_edge("parse", "validate_normalize")
builder.add_conditional_edges(
    "validate_normalize",
    validation_passed,
    {"deduplicate": "deduplicate", "persist_skipped": "persist_skipped"},
)
builder.add_edge("deduplicate", "enrich_and_score")
builder.add_edge("enrich_and_score", "persist")
builder.add_edge("persist", END)
builder.add_edge("persist_skipped", END)
prospect_import_graph = builder.compile()


def run_prospect_import(raw_csv: bytes, db: Session) -> ImportState:
    return prospect_import_graph.invoke(
        {
            "raw_csv": raw_csv,
            "db": db,
            "records": [],
            "errors": [],
            "stages": [],
            "duplicate_rows": 0,
            "counts": {},
            "score_summary": None,
            "content_sources": 0,
            "fatal_error": None,
        }
    )
