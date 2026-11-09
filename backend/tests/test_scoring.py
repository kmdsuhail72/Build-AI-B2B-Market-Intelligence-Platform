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
