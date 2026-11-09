import csv
from datetime import date
from pathlib import Path

import pytest

import app.workflows.approved_json_feeds as approved_feeds
from app.workflows.approved_json_feeds import (
    FeedCollectionError,
    FeedConfigError,
    collect_records,
    fetch_json,
    validate_config,
    write_csv_atomically,
)


def feed_config():
    return {
        "version": 1,
        "sources": [
            {
                "id": "public-project-feed",
                "name": "Public project feed",
                "access_method": "public_json_feed",
                "endpoint": "https://feed.example.org/api/projects",
                "terms_url": "https://feed.example.org/terms",
                "terms_reviewed_on": "2026-01-15",
                "records_path": "data.projects",
                "fields": {
                    "name": "company.name",
                    "category": "category",
                    "source_url": "url",
                    "project_name": "project.name",
                    "estimated_units": "project.units",
                },
                "defaults": {
                    "city": "Varanasi",
                    "state": "Uttar Pradesh",
                },
            }
        ],
    }


def test_feed_config_requires_approved_https_source_and_terms_review():
    config = feed_config()
    config["sources"][0]["endpoint"] = "http://feed.example.org/api"
    with pytest.raises(FeedConfigError, match="HTTPS"):
        validate_config(config)

    config = feed_config()
    del config["sources"][0]["terms_reviewed_on"]
    with pytest.raises(FeedConfigError, match="terms_reviewed_on"):
        validate_config(config)


def test_feed_config_supports_credentials_by_environment_reference():
    config = feed_config()
    config["sources"][0]["headers_env"] = {"Authorization": "PROJECT_FEED_TOKEN"}
    source = validate_config(config)[0]
    assert source["headers_env"] == {"Authorization": "PROJECT_FEED_TOKEN"}

    config["sources"][0]["headers_env"] = {"Cookie": "PROJECT_FEED_TOKEN"}
    with pytest.raises(FeedConfigError, match="invalid header"):
        validate_config(config)


def test_fetch_blocks_private_hosts(monkeypatch):
    source = validate_config(feed_config())[0]
    monkeypatch.setattr(
        approved_feeds.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, None, ("127.0.0.1", 443))],
    )
    with pytest.raises(FeedCollectionError, match="public IP"):
        fetch_json(source)


def test_fetch_uses_environment_credentials_and_parses_json(monkeypatch):
    source_config = feed_config()
    source_config["sources"][0]["headers_env"] = {"Authorization": "PROJECT_FEED_TOKEN"}
    source = validate_config(source_config)[0]
    monkeypatch.setenv("PROJECT_FEED_TOKEN", "test-token")
    monkeypatch.setattr(
        approved_feeds.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, None, ("93.184.216.34", 443))],
    )
    requests = []

    class FakeResponse:
        headers = type("Headers", (), {"get_content_type": lambda self: "application/json"})()

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def read(self, _limit):
            return b'{"data":{"projects":[]}}'

    class FakeOpener:
        def open(self, request, timeout):
            requests.append((request, timeout))
            return FakeResponse()

    monkeypatch.setattr(approved_feeds.urllib.request, "build_opener", lambda *_: FakeOpener())
    assert fetch_json(source) == {"data": {"projects": []}}
    assert requests[0][0].get_header("Authorization") == "test-token"
    assert requests[0][1] == approved_feeds.FEED_TIMEOUT_SECONDS


def test_redirect_handler_does_not_follow_redirects():
    assert (
        approved_feeds._RejectRedirects().redirect_request(
            None,
            None,
            302,
            "Found",
            {},
            "https://redirect.example.org",
        )
        is None
    )


def test_collect_records_maps_normalizes_and_marks_data_unverified():
    source = validate_config(feed_config())[0]
    payload = {
        "data": {
            "projects": [
                {
                    "company": {"name": "  Kashi   Developers "},
                    "category": "Builder",
                    "url": "https://source.example.org/projects/kashi",
                    "project": {"name": "River Homes", "units": 40},
                }
            ]
        }
    }

    rows, duplicate_count = collect_records(
        [source],
        fetch=lambda _: payload,
        discovered_at=date(2026, 3, 5),
    )

    assert duplicate_count == 0
    assert rows == [
        {
            "name": "Kashi Developers",
            "category": "Builder",
            "city": "Varanasi",
            "state": "Uttar Pradesh",
            "website": "",
            "public_phone": "",
            "description": "",
            "source_url": "https://source.example.org/projects/kashi",
            "source_title": "Public project feed",
            "source_type": "public_json_feed",
            "verification_status": "unverified",
            "discovered_at": "2026-03-05",
            "source_content": "",
            "contact_name": "",
            "contact_role": "",
            "contact_email": "",
            "contact_phone": "",
            "project_name": "River Homes",
            "project_location": "",
            "project_status": "",
            "estimated_units": "40",
            "estimated_doors": "",
            "doors_per_unit": "",
            "estimate_basis": "",
            "demand_confidence": "unknown",
            "demand_notes": "",
        }
    ]


def test_collect_records_skips_duplicate_observations():
    source = validate_config(feed_config())[0]
    item = {
        "company": {"name": "Kashi Developers"},
        "category": "Builder",
        "url": "https://source.example.org/projects/kashi",
        "project": {"name": "River Homes"},
    }
    rows, duplicate_count = collect_records(
        [source],
        fetch=lambda _: {"data": {"projects": [item, item]}},
    )

    assert len(rows) == 1
    assert duplicate_count == 1


def test_collect_records_fails_closed_on_missing_required_fields():
    source = validate_config(feed_config())[0]
    with pytest.raises(FeedCollectionError, match="missing name"):
        collect_records(
            [source],
            fetch=lambda _: {"data": {"projects": [{"url": "https://source.example.org"}]}},
        )


def test_csv_writer_is_atomic_and_compatible_with_import_template(tmp_path: Path):
    source = validate_config(feed_config())[0]
    rows, _ = collect_records(
        [source],
        fetch=lambda _: {
            "data": {
                "projects": [
                    {
                        "company": {"name": "Kashi Homes"},
                        "category": "Builder",
                        "url": "https://source.example.org/kashi",
                    }
                ]
            }
        },
        discovered_at=date(2026, 3, 5),
    )
    output = tmp_path / "collected.csv"

    write_csv_atomically(rows, output)

    with output.open(encoding="utf-8", newline="") as stream:
        imported_rows = list(csv.DictReader(stream))
    assert imported_rows[0]["discovered_at"] == "2026-03-05"
    assert imported_rows[0]["verification_status"] == "unverified"
    assert set(imported_rows[0]) == set(approved_feeds.CSV_FIELDS)


def test_csv_writer_rejects_output_over_import_limit(tmp_path: Path):
    row = {field: "" for field in approved_feeds.CSV_FIELDS}
    row["source_content"] = "x" * 20000
    output = tmp_path / "oversized.csv"

    with pytest.raises(FeedCollectionError, match="5 MB"):
        write_csv_atomically([row] * 260, output)

    assert not output.exists()
    assert list(tmp_path.iterdir()) == []
