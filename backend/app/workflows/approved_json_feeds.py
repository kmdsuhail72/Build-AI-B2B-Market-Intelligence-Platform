from __future__ import annotations

import argparse
import csv
import ipaddress
import io
import json
import math
import os
import re
import socket
import tempfile
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


CSV_FIELDS = (
    "name",
    "category",
    "city",
    "state",
    "website",
    "public_phone",
    "description",
    "source_url",
    "source_title",
    "source_type",
    "verification_status",
    "discovered_at",
    "source_content",
    "contact_name",
    "contact_role",
    "contact_email",
    "contact_phone",
    "project_name",
    "project_location",
    "project_status",
    "estimated_units",
    "estimated_doors",
    "doors_per_unit",
    "estimate_basis",
    "demand_confidence",
    "demand_notes",
)
REQUIRED_FIELDS = ("name", "category", "city", "state")
MAPPABLE_FIELDS = frozenset(CSV_FIELDS) - {"verification_status", "discovered_at"}
FIELD_LIMITS = {
    "name": 200,
    "category": 80,
    "city": 100,
    "state": 100,
    "website": 500,
    "public_phone": 50,
    "source_url": 1000,
    "source_title": 300,
    "source_type": 80,
    "source_content": 20000,
    "contact_name": 200,
    "contact_role": 120,
    "contact_email": 255,
    "contact_phone": 50,
    "project_name": 200,
    "project_location": 200,
    "project_status": 80,
    "estimate_basis": 300,
    "demand_confidence": 20,
}
ACCESS_METHODS = frozenset({"official_api", "public_json_feed", "licensed_api"})
BLOCKED_HEADERS = frozenset(
    {
        "accept",
        "connection",
        "content-length",
        "cookie",
        "host",
        "proxy-authorization",
        "transfer-encoding",
        "user-agent",
    }
)
HEADER_NAME_PATTERN = re.compile(r"^[A-Za-z0-9-]{1,64}$")
ENV_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
MAX_FEEDS = 20
MAX_RECORDS_PER_FEED = 2000
MAX_TOTAL_RECORDS = 2000
MAX_RESPONSE_BYTES = 10_000_000
MAX_CSV_BYTES = 5_000_000
FEED_TIMEOUT_SECONDS = 15
FEED_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
PATH_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")


class FeedConfigError(ValueError):
    pass


class FeedCollectionError(RuntimeError):
    pass


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


def _validate_https_url(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FeedConfigError(f"{field} must be a non-empty HTTPS URL")
    try:
        parsed = urlsplit(value.strip())
        port = parsed.port
    except ValueError as exc:
        raise FeedConfigError(f"{field} is not a valid URL") from exc
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or port not in (None, 443)
    ):
        raise FeedConfigError(f"{field} must be an HTTPS URL without credentials or a custom port")
    return value.strip()


def _validate_mapping(value: object, label: str) -> dict[str, str]:
    if not isinstance(value, dict):
        raise FeedConfigError(f"{label} must be an object")
    result: dict[str, str] = {}
    for field, path in value.items():
        if field not in MAPPABLE_FIELDS:
            raise FeedConfigError(f"{label} contains unsupported field: {field}")
        if not isinstance(path, str) or not PATH_PATTERN.fullmatch(path):
            raise FeedConfigError(f"{label}.{field} must be a dotted JSON field path")
        result[field] = path
    return result


def validate_config(config: object) -> list[dict[str, Any]]:
    if not isinstance(config, dict) or config.get("version") != 1:
        raise FeedConfigError("Feed configuration must be a version 1 JSON object")
    sources = config.get("sources")
    if not isinstance(sources, list) or not sources or len(sources) > MAX_FEEDS:
        raise FeedConfigError(f"Configure between 1 and {MAX_FEEDS} approved sources")

    validated = []
    seen_ids = set()
    for index, source in enumerate(sources, start=1):
        label = f"sources[{index}]"
        if not isinstance(source, dict):
            raise FeedConfigError(f"{label} must be an object")
        source_id = source.get("id")
        if not isinstance(source_id, str) or not FEED_ID_PATTERN.fullmatch(source_id):
            raise FeedConfigError(f"{label}.id must be a lowercase slug")
        if source_id in seen_ids:
            raise FeedConfigError(f"Duplicate source id: {source_id}")
        seen_ids.add(source_id)

        name = source.get("name")
        if not isinstance(name, str) or not name.strip():
            raise FeedConfigError(f"{label}.name must be a non-empty string")
        endpoint = _validate_https_url(source.get("endpoint"), f"{label}.endpoint")
        _validate_https_url(source.get("terms_url"), f"{label}.terms_url")

        access_method = source.get("access_method")
        if not isinstance(access_method, str) or access_method not in ACCESS_METHODS:
            raise FeedConfigError(
                f"{label}.access_method must be one of {', '.join(sorted(ACCESS_METHODS))}"
            )
        raw_reviewed_on = source.get("terms_reviewed_on", "")
        try:
            if (
                not isinstance(raw_reviewed_on, str)
                or len(raw_reviewed_on) != 10
                or raw_reviewed_on[4] != "-"
                or raw_reviewed_on[7] != "-"
            ):
                raise ValueError
            reviewed_on = date.fromisoformat(raw_reviewed_on)
        except (TypeError, ValueError) as exc:
            raise FeedConfigError(f"{label}.terms_reviewed_on must use YYYY-MM-DD") from exc
        if reviewed_on > date.today():
            raise FeedConfigError(f"{label}.terms_reviewed_on cannot be in the future")

        records_path = source.get("records_path", "")
        if not isinstance(records_path, str) or (
            records_path and not PATH_PATTERN.fullmatch(records_path)
        ):
            raise FeedConfigError(f"{label}.records_path must be a dotted JSON field path")

        fields = _validate_mapping(source.get("fields", {}), f"{label}.fields")
        defaults = source.get("defaults", {})
        if not isinstance(defaults, dict) or any(
            field not in MAPPABLE_FIELDS for field in defaults
        ):
            raise FeedConfigError(f"{label}.defaults contains an unsupported field")
        if any(
            not isinstance(value, (str, int, float))
            or isinstance(value, bool)
            or (isinstance(value, float) and not math.isfinite(value))
            for value in defaults.values()
        ):
            raise FeedConfigError(f"{label}.defaults values must be strings or numbers")
        for field in REQUIRED_FIELDS:
            if field not in fields and field not in defaults:
                raise FeedConfigError(f"{label} must map or provide a default for {field}")
        if "source_url" not in fields and "source_url" not in defaults:
            defaults = {**defaults, "source_url": endpoint}
        if "source_title" not in fields and "source_title" not in defaults:
            defaults = {**defaults, "source_title": name.strip()}
        if "source_type" not in fields and "source_type" not in defaults:
            defaults = {**defaults, "source_type": access_method}
        headers_env = source.get("headers_env", {})
        if not isinstance(headers_env, dict):
            raise FeedConfigError(f"{label}.headers_env must be an object")
        validated_headers = {}
        for header, variable in headers_env.items():
            if (
                not isinstance(header, str)
                or not HEADER_NAME_PATTERN.fullmatch(header)
                or header.casefold() in BLOCKED_HEADERS
                or not isinstance(variable, str)
                or not ENV_NAME_PATTERN.fullmatch(variable)
                or header.casefold() in {item.casefold() for item in validated_headers}
            ):
                raise FeedConfigError(f"{label}.headers_env contains an invalid header mapping")
            validated_headers[header] = variable

        validated.append(
            {
                "id": source_id,
                "name": name.strip(),
                "endpoint": endpoint,
                "records_path": records_path,
                "fields": fields,
                "defaults": defaults,
                "headers_env": validated_headers,
            }
        )
    return validated


def load_config(path: Path) -> list[dict[str, Any]]:
    try:
        config = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FeedConfigError(f"Could not read feed configuration: {exc}") from exc
    return validate_config(config)


def _assert_public_host(url: str, source_id: str) -> None:
    host = urlsplit(url).hostname
    if host is None:
        raise FeedCollectionError(f"{source_id}: endpoint has no hostname")
    try:
        addresses = {
            entry[4][0]
            for entry in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        }
    except OSError as exc:
        raise FeedCollectionError(f"{source_id}: endpoint hostname could not be resolved") from exc
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise FeedCollectionError(f"{source_id}: endpoint must resolve only to public IP addresses")


def fetch_json(source: dict[str, Any]) -> Any:
    source_id = source["id"]
    _assert_public_host(source["endpoint"], source_id)
    headers = {
        "Accept": "application/json",
        "User-Agent": "VidyaMarketIntelligence/1.0 (approved public JSON feed)",
    }
    for header, variable in source["headers_env"].items():
        value = os.getenv(variable)
        if not value:
            raise FeedCollectionError(
                f"{source_id}: required credential environment variable {variable} is not set"
            )
        if len(value) > 8192 or "\r" in value or "\n" in value:
            raise FeedCollectionError(f"{source_id}: credential environment variable is invalid")
        headers[header] = value
    request = urllib.request.Request(
        source["endpoint"],
        headers=headers,
        method="GET",
    )
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _RejectRedirects(),
    )
    try:
        with opener.open(request, timeout=FEED_TIMEOUT_SECONDS) as response:
            content_type = response.headers.get_content_type().lower()
            if content_type != "application/json" and not content_type.endswith("+json"):
                raise FeedCollectionError(f"{source_id}: endpoint did not return JSON")
            body = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise FeedCollectionError(f"{source_id}: endpoint returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise FeedCollectionError(f"{source_id}: could not fetch approved endpoint: {exc.reason}") from exc
    except TimeoutError as exc:
        raise FeedCollectionError(f"{source_id}: request timed out") from exc
    if len(body) > MAX_RESPONSE_BYTES:
        raise FeedCollectionError(f"{source_id}: response exceeds the 10 MB limit")
    try:
        return json.loads(body.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise FeedCollectionError(f"{source_id}: response is not valid UTF-8 JSON") from exc


def _read_path(record: Any, path: str) -> Any:
    value = record
    if not path:
        return value
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def _clean_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool) or isinstance(value, (dict, list)):
        raise ValueError("mapped values must be text or numbers")
    return " ".join(str(value).split())


def _source_records(source: dict[str, Any], payload: Any) -> list[Any]:
    records = _read_path(payload, source["records_path"])
    if not isinstance(records, list) or len(records) > MAX_RECORDS_PER_FEED:
        raise FeedCollectionError(
            f"{source['id']}: records path must contain an array of at most "
            f"{MAX_RECORDS_PER_FEED} records"
        )
    if any(not isinstance(record, dict) for record in records):
        raise FeedCollectionError(f"{source['id']}: every feed record must be a JSON object")
    return records


def _map_record(
    source: dict[str, Any],
    record: dict[str, Any],
    index: int,
    discovered_at: str,
) -> dict[str, str]:
    row = {field: "" for field in CSV_FIELDS}
    for field, value in source["defaults"].items():
        row[field] = _clean_value(value)
    for field, path in source["fields"].items():
        value = _read_path(record, path)
        if value is not None:
            try:
                row[field] = _clean_value(value)
            except ValueError as exc:
                raise FeedCollectionError(
                    f"{source['id']}: record {index} field {field} has an unsupported value"
                ) from exc

    if not row["source_url"]:
        row["source_url"] = source["endpoint"]
    if not row["source_title"]:
        row["source_title"] = source["name"]
    if not row["source_type"]:
        row["source_type"] = "public_json_feed"
    row["verification_status"] = "unverified"
    row["discovered_at"] = discovered_at
    if row["contact_email"]:
        row["contact_email"] = row["contact_email"].casefold()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", row["contact_email"]):
            raise FeedCollectionError(
                f"{source['id']}: record {index} contact_email is invalid"
            )
    if any(row[field] for field in ("contact_role", "contact_email", "contact_phone")) and not row[
        "contact_name"
    ]:
        raise FeedCollectionError(
            f"{source['id']}: record {index} contact fields require contact_name"
        )

    for field in (*REQUIRED_FIELDS, "source_url"):
        if not row[field]:
            raise FeedCollectionError(f"{source['id']}: record {index} is missing {field}")
    try:
        parsed_url = urlsplit(row["source_url"])
        if (
            parsed_url.scheme not in {"https", "http"}
            or not parsed_url.hostname
            or parsed_url.username is not None
            or parsed_url.password is not None
        ):
            raise ValueError
    except ValueError as exc:
        raise FeedCollectionError(
            f"{source['id']}: record {index} source_url must be an HTTP or HTTPS URL"
        ) from exc
    try:
        parsed_url.port
    except ValueError as exc:
        raise FeedCollectionError(
            f"{source['id']}: record {index} source_url has an invalid port"
        ) from exc

    for field, limit in FIELD_LIMITS.items():
        if len(row[field]) > limit:
            raise FeedCollectionError(
                f"{source['id']}: record {index} field {field} exceeds {limit} characters"
            )

    for field in ("estimated_units", "estimated_doors"):
        if row[field]:
            try:
                number = int(row[field])
                if number < 0:
                    raise ValueError
                row[field] = str(number)
            except ValueError as exc:
                raise FeedCollectionError(
                    f"{source['id']}: record {index} field {field} must be a non-negative integer"
                ) from exc
    if row["doors_per_unit"]:
        try:
            doors_per_unit = float(row["doors_per_unit"])
            if not math.isfinite(doors_per_unit) or not 0 <= doors_per_unit <= 100:
                raise ValueError
            row["doors_per_unit"] = format(doors_per_unit, "g")
        except ValueError as exc:
            raise FeedCollectionError(
                f"{source['id']}: record {index} field doors_per_unit must be between 0 and 100"
            ) from exc
    confidence = row["demand_confidence"].casefold() or "unknown"
    if confidence not in {"unknown", "low", "medium", "high"}:
        raise FeedCollectionError(
            f"{source['id']}: record {index} field demand_confidence is invalid"
        )
    row["demand_confidence"] = confidence
    return row


def collect_records(
    sources: list[dict[str, Any]],
    fetch: Callable[[dict[str, Any]], Any] = fetch_json,
    discovered_at: date | None = None,
) -> tuple[list[dict[str, str]], int]:
    discovery_date = (discovered_at or date.today()).isoformat()
    rows = []
    seen = set()
    duplicates = 0
    for source in sources:
        records = _source_records(source, fetch(source))
        for index, record in enumerate(records, start=1):
            row = _map_record(source, record, index, discovery_date)
            key = (
                row["name"].casefold(),
                row["city"].casefold(),
                row["source_url"].casefold(),
                row["project_name"].casefold(),
            )
            if key in seen:
                duplicates += 1
                continue
            if len(rows) >= MAX_TOTAL_RECORDS:
                raise FeedCollectionError(
                    f"Collected records exceed the {MAX_TOTAL_RECORDS} record limit"
                )
            seen.add(key)
            rows.append(row)
    if not rows:
        raise FeedCollectionError("Approved feeds returned no usable records")
    return rows, duplicates


def write_csv_atomically(rows: list[dict[str, str]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            buffer = io.StringIO(newline="")
            writer = csv.DictWriter(buffer, fieldnames=CSV_FIELDS)
            writer.writeheader()
            data = buffer.getvalue().encode("utf-8")
            if len(data) > MAX_CSV_BYTES:
                raise FeedCollectionError("Generated CSV exceeds the 5 MB import limit")
            temporary_file.write(data)
            for row in rows:
                buffer.seek(0)
                buffer.truncate(0)
                writer.writerow(row)
                data = buffer.getvalue().encode("utf-8")
                if temporary_file.tell() + len(data) > MAX_CSV_BYTES:
                    raise FeedCollectionError("Generated CSV exceeds the 5 MB import limit")
                temporary_file.write(data)
        os.replace(temporary_path, output_path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Collect records from explicitly approved public JSON feeds."
    )
    parser.add_argument("--config", required=True, type=Path, help="Reviewed JSON feed configuration")
    parser.add_argument("--output", required=True, type=Path, help="CSV file to write for review/import")
    args = parser.parse_args()
    try:
        if args.config.resolve() == args.output.resolve():
            raise FeedConfigError("configuration and output paths must be different")
        sources = load_config(args.config)
        rows, duplicates = collect_records(sources)
        write_csv_atomically(rows, args.output)
    except (FeedConfigError, FeedCollectionError, OSError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(f"Wrote {len(rows)} unverified records to {args.output} ({duplicates} duplicates skipped).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
