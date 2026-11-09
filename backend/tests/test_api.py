import csv
import io
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

from app import main


@pytest.fixture
def client(monkeypatch):
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    test_sessions = sessionmaker(bind=test_engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(main, "engine", test_engine)
    main.Base.metadata.create_all(test_engine)
    with test_sessions() as db:
        db.add(
            main.User(
                email="admin@example.com",
                password_hash=main.password_hash.hash("a-secure-test-password"),
                role="admin",
            )
        )
        db.add(
            main.User(
                email="viewer@example.com",
                password_hash=main.password_hash.hash("a-viewer-test-password"),
                role="viewer",
            )
        )
        db.commit()

    def override_db():
        db = test_sessions()
        try:
            yield db
        finally:
            db.close()

    main.app.dependency_overrides[main.get_db] = override_db
    with TestClient(main.app) as test_client:
        assert test_client.post(
            "/api/auth/login",
            json={"email": "admin@example.com", "password": "a-secure-test-password"},
        ).status_code == 200
        yield test_client
    main.app.dependency_overrides.clear()
    test_engine.dispose()


def test_import_profile_activity_relationship_and_export(client):
    csv_content = (
        "name,category,city,state,source_url,source_title,verification_status,"
        "project_name,project_status,estimated_units,estimated_doors,demand_notes\n"
        "Kashi Design Studio,Architect,Varanasi,Uttar Pradesh,"
        "https://example.com/kashi,Studio profile,verified,"
        "Riverfront Residences,announced,20,80,Illustrative estimate from 4 doors per unit\n"
        "Sarnath Build Co,Builder,Varanasi,Uttar Pradesh,"
        "https://example.com/sarnath,Company page,unverified,,,,\n"
    )
    imported = client.post(
        "/api/import/csv",
        files={"file": ("prospects.csv", csv_content.encode(), "text/csv")},
    )

    assert imported.status_code == 200
    assert {
        key: imported.json()[key]
        for key in ("companies_created", "sources_created", "projects_created")
    } == {
        "companies_created": 2,
        "sources_created": 2,
        "projects_created": 1,
    }
    assert imported.json()["workflow"]["stages"] == [
        "parse",
        "validate_normalize",
        "deduplicate",
        "enrich_and_score",
        "persist",
    ]

    companies = client.get("/api/companies").json()
    architect = next(row for row in companies if row["name"] == "Kashi Design Studio")
    builder = next(row for row in companies if row["name"] == "Sarnath Build Co")
    assert architect["score"] == 60
    assert client.get(f"/api/companies/{architect['id']}").json()["projects"][0]["estimated_doors"] == 80

    activity = client.post(
        f"/api/companies/{architect['id']}/activities",
        json={
            "activity_type": "call",
            "notes": "Discussed project materials",
            "next_action": "Send product catalogue",
            "due_date": "2026-11-20",
        },
    )
    assert activity.status_code == 201
    assert client.get("/api/dashboard/summary").json()["open_follow_ups"] == 1
    assert client.post(f"/api/activities/{activity.json()['id']}/complete").status_code == 200
    assert client.get("/api/dashboard/summary").json()["open_follow_ups"] == 0
    assert client.post(
        "/api/relationships",
        json={
            "company_id": architect["id"],
            "related_company_id": builder["id"],
            "relationship_type": "builder for",
        },
    ).status_code == 201

    profile = client.get(f"/api/companies/{architect['id']}").json()
    assert profile["activities"][0]["next_action"] == "Send product catalogue"
    assert profile["activities"][0]["completed_at"] is not None
    assert profile["relationships"][0]["related_company_name"] == "Sarnath Build Co"
    exported = client.get("/api/export.csv")
    assert exported.status_code == 200
    assert exported.headers["content-type"].startswith("text/csv")
    assert "Kashi Design Studio" in exported.text


def test_import_is_atomic_when_a_row_is_invalid(client):
    csv_content = (
        "name,category,city,state,source_url,estimated_doors\n"
        "Valid Studio,Architect,Varanasi,Uttar Pradesh,https://example.com/valid,20\n"
        "Bad Studio,Architect,Varanasi,Uttar Pradesh,https://example.com/bad,-1\n"
    )
    response = client.post(
        "/api/import/csv",
        files={"file": ("prospects.csv", io.BytesIO(csv_content.encode()), "text/csv")},
    )

    assert response.status_code == 422
    assert client.get("/api/companies").json() == []


def test_csv_export_uses_standard_csv_escaping(client):
    csv_content = (
        "name,category,city,state,source_url\n"
        '"Studio, North",Architect,Varanasi,Uttar Pradesh,https://example.com/studio\n'
        "=1+1,Architect,Varanasi,Uttar Pradesh,https://example.com/formula\n"
    )
    client.post(
        "/api/import/csv",
        files={"file": ("prospects.csv", csv_content.encode(), "text/csv")},
    )

    rows = list(csv.DictReader(io.StringIO(client.get("/api/export.csv").text)))
    assert rows[0]["name"] == "'=1+1"
    assert rows[1]["name"] == "Studio, North"


def test_login_role_guards_audit_and_logout(client):
    created = client.post(
        "/api/users",
        json={"email": "new-sales@example.com", "password": "long-enough-password", "role": "sales"},
    )
    assert created.status_code == 201
    assert client.get("/api/audit").status_code == 200
    login_response = client.post(
        "/api/auth/login",
        json={"email": "admin@example.com", "password": "a-secure-test-password"},
    )
    assert "httponly" in login_response.headers["set-cookie"].lower()

    client.post("/api/auth/logout")
    assert client.get("/api/companies").status_code == 401
    assert client.post(
        "/api/auth/login",
        json={"email": "viewer@example.com", "password": "a-viewer-test-password"},
    ).status_code == 200
    assert client.get("/api/auth/me").json()["role"] == "viewer"
    assert client.post("/api/import/csv", files={"file": ("x.csv", b"", "text/csv")}).status_code == 403
    assert client.post(
        "/api/companies/1/activities",
        json={"activity_type": "call", "notes": "not allowed"},
    ).status_code == 403
    assert client.post(
        "/api/relationships",
        json={"company_id": 1, "related_company_id": 2, "relationship_type": "builder for"},
    ).status_code == 403


def test_project_demand_filters_saved_search_and_audit(client):
    csv_content = (
        "name,category,city,state,source_url,project_name,estimated_units,"
        "doors_per_unit,estimate_basis,demand_confidence\n"
        "Bharat Build,Builder,Varanasi,Uttar Pradesh,https://example.com/build,"
        "Courtyard Homes,12,4,Public project brochure,medium\n"
        "Local Studio,Architect,Varanasi,Uttar Pradesh,https://example.com/studio,,,,,\n"
    )
    response = client.post(
        "/api/import/csv",
        files={"file": ("market.csv", csv_content.encode(), "text/csv")},
    )
    assert response.status_code == 200
    companies = client.get("/api/companies?has_project=true")
    assert companies.headers["X-Total-Count"] == "1"
    company = companies.json()[0]
    project = client.get(f"/api/companies/{company['id']}").json()["projects"][0]
    assert project["estimated_doors"] == 48
    assert project["estimate_method"] == "12 units × 4 doors/unit"
    assert project["demand_confidence"] == "medium"

    updated = client.patch(
        f"/api/projects/{project['id']}/demand",
        json={
            "estimated_units": 12,
            "estimated_doors": 60,
            "doors_per_unit": 4,
            "estimate_basis": "Builder's specification",
            "demand_confidence": "high",
            "demand_notes": None,
        },
    )
    assert updated.json()["estimated_doors"] == 60
    assert updated.json()["estimate_method"] == "Explicit estimate"

    saved = client.post(
        "/api/saved-searches",
        json={"name": "Varanasi projects", "filters": {"city": "Varanasi", "has_project": True}},
    )
    assert saved.status_code == 201
    assert client.get("/api/saved-searches").json()[0]["name"] == "Varanasi projects"
    assert any(event["action"] == "update_demand" for event in client.get("/api/audit").json())
    assert client.delete(f"/api/saved-searches/{saved.json()['id']}").status_code == 204

    saved = client.post(
        "/api/saved-searches",
        json={"name": "Private view", "filters": {"city": "Varanasi"}},
    )
    assert saved.status_code == 201
    client.post("/api/auth/logout")
    client.post(
        "/api/auth/login",
        json={"email": "viewer@example.com", "password": "a-viewer-test-password"},
    )
    assert client.get("/api/saved-searches").json() == []
    assert client.delete(f"/api/saved-searches/{saved.json()['id']}").status_code == 404


def test_workflow_skips_duplicate_rows_and_reports_score_preview(client):
    duplicate_row = (
        "Kashi Design Studio,Architect,Varanasi,Uttar Pradesh,"
        "https://example.com/kashi,Studio profile,verified\n"
    )
    csv_content = "name,category,city,state,source_url,source_title,verification_status\n"
    response = client.post(
        "/api/import/csv",
        files={
            "file": (
                "duplicate.csv",
                (csv_content + duplicate_row + duplicate_row).encode(),
                "text/csv",
            )
        },
    )
    assert response.status_code == 200
    result = response.json()
    assert result["companies_created"] == 1
    assert result["workflow"]["duplicate_rows_skipped"] == 1
    assert result["workflow"]["score_preview"] == {"average": 50.0, "minimum": 50, "maximum": 50}


def test_invalid_csv_stops_before_persist_node(client):
    csv_content = (
        "name,category,city,state,source_url\n"
        "Valid Studio,Architect,Varanasi,Uttar Pradesh,https://example.com/valid\n"
        "Bad Studio,Architect,Varanasi,Uttar Pradesh,file://unsafe/path\n"
    )
    response = client.post(
        "/api/import/csv",
        files={"file": ("invalid.csv", csv_content.encode(), "text/csv")},
    )
    assert response.status_code == 422
    assert client.get("/api/companies").json() == []


def test_research_retrieves_cited_evidence_and_relationship_graph(client):
    csv_content = (
        "name,category,city,state,source_url,source_title,verification_status,source_content\n"
        "Varuna Developers,Builder,Varanasi,Uttar Pradesh,https://example.com/varuna,"
        "Riverfront announcement,verified,The riverfront housing project has 18 residential units.\n"
        "Kashi Architects,Architect,Varanasi,Uttar Pradesh,https://example.com/kashi,"
        "Architect portfolio,unverified,The architecture firm designed the riverfront housing project.\n"
    )
    imported = client.post(
        "/api/import/csv",
        files={"file": ("market.csv", csv_content.encode(), "text/csv")},
    )
    assert imported.status_code == 200
    assert imported.json()["source_contents_added"] == 2
    companies = client.get("/api/companies").json()
    developer = next(row for row in companies if row["name"] == "Varuna Developers")
    architect = next(row for row in companies if row["name"] == "Kashi Architects")
    client.post(
        "/api/relationships",
        json={
            "company_id": developer["id"],
            "related_company_id": architect["id"],
            "relationship_type": "architect for",
        },
    )

    response = client.post(
        "/api/research/query",
        json={"query": "riverfront housing project", "top_k": 5, "include_graph": True},
    )
    result = response.json()
    assert response.status_code == 200
    assert result["mode"] == "retrieval_only"
    assert result["workflow"] == ["retrieve", "graph_expand", "answer_retrieval_only"]
    assert result["evidence"][0]["company_name"] == "Varuna Developers"
    assert "residential units" in result["evidence"][0]["excerpt"]
    assert all(item["citation"].startswith("S") for item in result["evidence"])
    assert result["graph_neighbors"] == 1
    assert any(item.get("neighbor_company", {}).get("name") == "Kashi Architects" for item in result["graph_context"])
    assert any(item["company_name"] == "Kashi Architects" for item in result["evidence"])
    assert result["mode"] in client.get("/api/audit").text


def test_knowledge_graph_exposes_company_project_and_relationship_edges(client):
    csv_content = (
        "name,category,city,state,source_url,verification_status,source_content,"
        "project_name,project_status,estimated_units,estimated_doors\n"
        "Varuna Developers,Builder,Varanasi,Uttar Pradesh,https://example.com/varuna,"
        "verified,Public project announcement,Riverfront Homes,announced,20,80\n"
        "Kashi Architects,Architect,Varanasi,Uttar Pradesh,https://example.com/kashi,"
        "unverified,Architecture portfolio,,,,\n"
    )
    imported = client.post(
        "/api/import/csv",
        files={"file": ("market.csv", csv_content.encode(), "text/csv")},
    )
    assert imported.status_code == 200
    companies = client.get("/api/companies").json()
    developer = next(row for row in companies if row["name"] == "Varuna Developers")
    architect = next(row for row in companies if row["name"] == "Kashi Architects")
    relationship = client.post(
        "/api/relationships",
        json={
            "company_id": developer["id"],
            "related_company_id": architect["id"],
            "relationship_type": "architect for",
        },
    )
    assert relationship.status_code == 201

    graph_response = client.get("/api/knowledge-graph")
    assert graph_response.status_code == 200
    graph = graph_response.json()
    assert graph["total_companies"] == graph["included_companies"] == 2
    assert graph["total_projects"] == graph["included_projects"] == 1
    developer_node = next(
        node for node in graph["nodes"]
        if node["type"] == "company" and node["entity_id"] == developer["id"]
    )
    project_node = next(node for node in graph["nodes"] if node["type"] == "project")
    assert developer_node["verified_sources"] == 1
    assert project_node["estimated_doors"] == 80
    assert any(edge["type"] == "architect for" for edge in graph["edges"])
    assert any(
        edge["source"] == developer_node["id"] and edge["target"] == project_node["id"]
        for edge in graph["edges"]
    )
    assert client.get("/api/knowledge-graph?city=Elsewhere").json()["nodes"] == []
    bounded = client.get("/api/knowledge-graph?limit=1").json()
    assert bounded["included_companies"] == 1
    assert bounded["total_companies"] == 2
    assert bounded["truncated"] is True


def test_ai_answer_generation_requires_explicit_request_and_verified_context(client, monkeypatch):
    monkeypatch.delenv("RAG_OPENAI_API_KEY", raising=False)
    response = client.post(
        "/api/research/query",
        json={"query": "planned construction project", "use_llm": True},
    )
    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]


def test_ai_answer_sends_only_verified_excerpts_and_requires_citations(client, monkeypatch):
    import app.workflows.research as research

    csv_content = (
        "name,category,city,state,source_url,source_title,verification_status,source_content\n"
        "Approved Builder,Builder,Varanasi,Uttar Pradesh,https://example.com/approved,"
        "Public project,verified,Verified public source says construction starts in April.\n"
        "Unreviewed Builder,Builder,Varanasi,Uttar Pradesh,https://example.com/unreviewed,"
        "Unreviewed source,unverified,Secret unreviewed content must never leave the app.\n"
    )
    assert client.post(
        "/api/import/csv",
        files={"file": ("market.csv", csv_content.encode(), "text/csv")},
    ).status_code == 200
    monkeypatch.setenv("RAG_OPENAI_API_KEY", "test-token")

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def read(self):
            return json.dumps(
                {"choices": [{"message": {"content": "Construction starts in April [S1]."}}]}
            ).encode()

    def fake_urlopen(request, timeout):
        body = json.loads(request.data)
        prompt = body["messages"][1]["content"]
        assert timeout == 30
        assert "Verified public source says construction starts in April." in prompt
        assert "Secret unreviewed content" not in prompt
        return FakeResponse()

    monkeypatch.setattr(research, "urlopen", fake_urlopen)
    response = client.post(
        "/api/research/query",
        json={"query": "construction starts", "use_llm": True},
    )
    assert response.status_code == 200
    assert response.json()["mode"] == "openai"
    assert response.json()["evidence"][0]["used_in_answer"] is True
