from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.main import Base, BusinessRelationship, Company, Project, Source
from app.mcp_server import (
    company_profile_data,
    list_projects_data,
    research_market_data,
    search_companies_data,
)


def test_mcp_read_tools_return_scored_companies_projects_and_relationships():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        builder = Company(
            name="Varuna Developers",
            category="Builder",
            city="Varanasi",
            state="Uttar Pradesh",
        )
        architect = Company(
            name="Kashi Architects",
            category="Architect",
            city="Varanasi",
            state="Uttar Pradesh",
        )
        project = Project(
            company=builder,
            name="Riverfront Homes",
            location="Varanasi",
            status="announced",
            estimated_units=20,
            doors_per_unit=4,
            demand_confidence="medium",
        )
        source = Source(
            company=builder,
            project=project,
            url="https://example.com/riverfront",
            title="Public project announcement",
            verification_status="verified",
            content="Verified riverfront homes project is planned for Varanasi.",
            discovered_at=date(2026, 11, 1),
        )
        db.add(
            Source(
                company=architect,
                url="https://example.com/unreviewed",
                title="Unreviewed riverfront notes",
                verification_status="unverified",
                content="This unreviewed content must not be forwarded through MCP research.",
            )
        )
        relation = BusinessRelationship(
            company=builder,
            related_company=architect,
            project=project,
            relationship_type="architect for",
            notes="Internal note must not be exposed through MCP.",
        )
        db.add_all([builder, architect, project, source, relation])
        db.commit()
        builder_id = builder.id

        searched = search_companies_data(db, query="Varuna", city="Varanasi", limit=10)
        profile = company_profile_data(db, builder_id)
        projects = list_projects_data(db, city="Varanasi", status="announced", limit=10)
        research = research_market_data(db, "riverfront homes")

    engine.dispose()
    assert searched["count"] == 1
    assert searched["companies"][0]["verified_source_count"] == 1
    assert profile is not None
    assert profile["projects"][0]["estimated_doors"] == 80
    assert profile["relationships"][0]["related_company"] == "Kashi Architects"
    assert "notes" not in profile["relationships"][0]
    assert profile["sources"][0]["url"] == "https://example.com/riverfront"
    assert projects["count"] == 1
    assert projects["projects"][0]["company"] == "Varuna Developers"
    assert research["answer"] == "Found 1 verified source excerpt(s)."
    assert len(research["evidence"]) == 1
    assert research["evidence"][0]["verification_status"] == "verified"
    assert all(
        "notes" not in item and "Internal note" not in str(item)
        for item in research["graph_context"]
    )
