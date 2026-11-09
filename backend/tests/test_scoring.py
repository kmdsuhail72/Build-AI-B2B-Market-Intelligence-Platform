from types import SimpleNamespace

from app.main import lead_score


def test_score_explains_relevance_and_evidence():
    company = SimpleNamespace(
        category="Architect",
        sources=[SimpleNamespace(verification_status="verified")],
        projects=[object()],
    )

    result = lead_score(company)

    assert result["score"] == 60
    assert len(result["reasons"]) == 3


def test_score_is_capped_and_unverified_sources_do_not_add_evidence_points():
    company = SimpleNamespace(
        category="Builder",
        sources=[SimpleNamespace(verification_status="unverified")],
        projects=[object(), object(), object(), object()],
    )

    result = lead_score(company)

    assert result["score"] == 58
    assert all("verified" not in reason for reason in result["reasons"])


def test_score_breakdown_is_transparent_and_caps_at_one_hundred():
    company = SimpleNamespace(
        category="Architect",
        website="https://builder.example",
        sources=[SimpleNamespace(verification_status="verified") for _ in range(5)],
        projects=[object(), object(), object(), object()],
        contacts=[object()],
    )

    result = lead_score(company)

    assert result["score"] == 100
    assert sum(component["points"] for component in result["components"]) == 100
    assert sum(component["maximum"] for component in result["components"]) == 100
