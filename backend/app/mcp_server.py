from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

from app.main import (
    BusinessRelationship,
    Company,
    Project,
    SessionLocal,
    company_summary,
    project_demand,
)
from app.workflows.research import run_research


mcp = FastMCP("Vidya Timber Market Intelligence")


def _session() -> Session:
    return SessionLocal()


def search_companies_data(
    db: Session,
    query: str = "",
    city: str = "",
    category: str = "",
    limit: int = 20,
) -> dict[str, Any]:
    filters = []
    if query.strip():
        term = f"%{query.strip()}%"
        filters.append(
            or_(Company.name.ilike(term), Company.category.ilike(term), Company.city.ilike(term))
        )
    if city.strip():
        filters.append(Company.city.ilike(f"%{city.strip()}%"))
    if category.strip():
        filters.append(Company.category.ilike(f"%{category.strip()}%"))

    companies = db.scalars(
        select(Company)
        .where(*filters)
        .options(joinedload(Company.sources), joinedload(Company.projects))
        .order_by(Company.name, Company.city, Company.id)
        .limit(limit)
    ).unique().all()
    return {"count": len(companies), "companies": [company_summary(item) for item in companies]}


def company_profile_data(db: Session, company_id: int) -> dict[str, Any] | None:
    company = db.scalar(
        select(Company)
        .where(Company.id == company_id)
        .options(
            joinedload(Company.sources),
            joinedload(Company.projects).joinedload(Project.sources),
        )
    )
    if company is None:
        return None

    relations = db.scalars(
        select(BusinessRelationship)
        .where(
            or_(
                BusinessRelationship.company_id == company_id,
                BusinessRelationship.related_company_id == company_id,
            )
        )
        .options(
            joinedload(BusinessRelationship.company),
            joinedload(BusinessRelationship.related_company),
            joinedload(BusinessRelationship.project),
        )
        .order_by(BusinessRelationship.id)
    ).unique().all()
    return {
        **company_summary(company),
        "description": company.description,
        "sources": [
            {
                "url": source.url,
                "title": source.title,
                "verification_status": source.verification_status,
                "discovered_at": source.discovered_at.isoformat(),
            }
            for source in company.sources
        ],
        "projects": [
            {
                "name": project.name,
                "location": project.location,
                "status": project.status,
                "estimated_units": project.estimated_units,
                **project_demand(project),
            }
            for project in company.projects
        ],
        "relationships": [
            {
                "related_company": (
                    relation.related_company.name
                    if relation.company_id == company_id
                    else relation.company.name
                ),
                "relationship_type": relation.relationship_type,
                "project": relation.project.name if relation.project else None,
            }
            for relation in relations
        ],
    }


def list_projects_data(
    db: Session,
    city: str = "",
    status: str = "",
    limit: int = 30,
) -> dict[str, Any]:
    filters = []
    if city.strip():
        filters.append(
            or_(
                Project.location.ilike(f"%{city.strip()}%"),
                Company.city.ilike(f"%{city.strip()}%"),
            )
        )
    if status.strip():
        filters.append(Project.status.ilike(f"%{status.strip()}%"))

    projects = db.scalars(
        select(Project)
        .join(Project.company)
        .where(*filters)
        .options(joinedload(Project.company), joinedload(Project.sources))
        .order_by(Project.name, Project.id)
        .limit(limit)
    ).unique().all()
    return {
        "count": len(projects),
        "projects": [
            {
                "name": project.name,
                "company": project.company.name,
                "city": project.location or project.company.city,
                "status": project.status,
                "estimated_units": project.estimated_units,
                **project_demand(project),
                "source_urls": [source.url for source in project.sources],
            }
            for project in projects
        ],
    }


def research_market_data(db: Session, query: str, top_k: int = 5) -> dict[str, Any]:
    result = run_research(
        query,
        db,
        top_k=max(1, min(top_k, 10)),
        include_graph=True,
        use_llm=False,
    )
    verified_evidence = [
        item for item in result["evidence"]
        if item["verification_status"] == "verified"
    ]
    for index, item in enumerate(verified_evidence, start=1):
        item["citation"] = f"S{index}"
        item["used_in_answer"] = False
    result["evidence"] = verified_evidence
    result["answer"] = (
        f"Found {len(verified_evidence)} verified source excerpt(s)."
        if verified_evidence
        else "No matching verified source excerpts were found."
    )
    result["graph_context"] = [
        {key: value for key, value in item.items() if key != "notes"}
        for item in result["graph_context"]
    ]
    return result


@mcp.tool()
def search_companies(
    query: str = "",
    city: str = "",
    category: str = "",
    limit: int = 20,
) -> dict[str, Any]:
    """Search local companies by name, category, or city and return explainable lead scores."""
    bounded_limit = max(1, min(limit, 50))
    with _session() as db:
        return search_companies_data(db, query, city, category, bounded_limit)


@mcp.tool()
def get_company_profile(company_id: int) -> dict[str, Any]:
    """Get one company's public source evidence, projects, lead score, and recorded relationships."""
    with _session() as db:
        profile = company_profile_data(db, company_id)
    if profile is None:
        return {"error": f"No company found with id {company_id}."}
    return profile


@mcp.tool()
def list_projects(city: str = "", status: str = "", limit: int = 30) -> dict[str, Any]:
    """List construction projects with documented demand estimates and source URLs."""
    bounded_limit = max(1, min(limit, 100))
    with _session() as db:
        return list_projects_data(db, city, status, bounded_limit)


@mcp.tool()
def get_company_relationships(company_id: int) -> dict[str, Any]:
    """Return a company's direct recorded business connections and linked project context."""
    with _session() as db:
        profile = company_profile_data(db, company_id)
    if profile is None:
        return {"error": f"No company found with id {company_id}."}
    return {
        "company": profile["name"],
        "relationships": profile["relationships"],
        "projects": profile["projects"],
    }


@mcp.tool()
def research_market(query: str, top_k: int = 5) -> dict[str, Any]:
    """Search verified source excerpts and expand local relationships; never calls an LLM."""
    with _session() as db:
        return research_market_data(db, query, top_k)


if __name__ == "__main__":
    mcp.run(transport="stdio")
