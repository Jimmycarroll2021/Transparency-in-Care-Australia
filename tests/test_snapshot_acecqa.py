"""Unit tests for scrapers/snapshot_acecqa_registers.py. No network."""

from __future__ import annotations

import gzip

import pytest
from scrapers.snapshot_acecqa_registers import (
    PROVIDERS,
    SERVICES,
    ParsedCsv,
    ValidationError,
    build_processed_rows,
    dedupe_names,
    gzip_bytes,
    parse_csv,
    split_columns,
    validate_parsed,
)

SERVICES_CSV = (
    "ServiceApprovalNumber,Provider Approval Number,ServiceName,Phone,Fax,Suburb\n"
    "SE-00001234,PR-00000042,Example Centre,(02) 5550 0000,,Testville\n"
    "se 5,pr-7,Second Centre,,,Otherville\n"
    ",,Third Centre,,,Nowhere\n"
)
PROVIDERS_CSV = (
    "Provider Approval Number,Service Approval Number,Legal Name,State\n"
    "PR-00000042,,Example Pty Ltd,NSW\n"
)


def make(columns: list[str], n_rows: int) -> ParsedCsv:
    return ParsedCsv(columns=columns, rows=[["x"] * len(columns)] * n_rows, encoding="utf-8")


def test_parse_csv_handles_bom_and_counts_rows():
    parsed = parse_csv(b"\xef\xbb\xbf" + SERVICES_CSV.encode())
    assert parsed.columns[0] == "ServiceApprovalNumber"
    assert parsed.row_count == 3


def test_parse_csv_skips_blank_lines():
    parsed = parse_csv(b"A,B\n1,2\n,\n\n3,4\n")
    assert parsed.row_count == 2


def test_parse_csv_empty_file_is_invalid():
    with pytest.raises(ValidationError):
        parse_csv(b"")


def test_validate_services_accepts_good_file():
    validate_parsed(make(["ServiceApprovalNumber", "x"], 10_001), SERVICES)


def test_validate_services_rejects_missing_header():
    with pytest.raises(ValidationError, match="ServiceApprovalNumber"):
        validate_parsed(make(["<html>", "403"], 20_000), SERVICES)


def test_validate_services_rejects_truncated_file():
    with pytest.raises(ValidationError, match="expected more than 10000"):
        validate_parsed(make(["ServiceApprovalNumber"], 10_000), SERVICES)


def test_validate_providers_header_and_threshold():
    validate_parsed(make(["Provider Approval Number"], 5_001), PROVIDERS)
    with pytest.raises(ValidationError):
        validate_parsed(make(["ServiceApprovalNumber"], 6_000), PROVIDERS)
    with pytest.raises(ValidationError):
        validate_parsed(make(["Provider Approval Number"], 5_000), PROVIDERS)


def test_split_columns_drops_contact_fields_only():
    cols = [
        "ServiceApprovalNumber",
        "Phone",
        "Fax",
        "Contact Email",
        "Nominated Supervisor",
        "Conditions on Approval",
        "Suburb",
        "E-mail",
    ]
    kept, dropped = split_columns(cols)
    assert kept == ["ServiceApprovalNumber", "Conditions on Approval", "Suburb"]
    assert dropped == ["Phone", "Fax", "Contact Email", "Nominated Supervisor", "E-mail"]


def test_split_columns_is_case_insensitive():
    kept, dropped = split_columns(["PHONE", "fax", "Name"])
    assert kept == ["Name"]
    assert dropped == ["PHONE", "fax"]


def test_dedupe_names_keeps_every_column():
    assert dedupe_names(["a", "b", "a", "a"]) == ["a", "b", "a__2", "a__3"]


def test_build_processed_rows_services():
    rows, fieldnames, dropped = build_processed_rows(
        parse_csv(SERVICES_CSV.encode()), SERVICES, "Wed, 28 Oct 2026 19:28:15 GMT"
    )
    assert dropped == ["Phone", "Fax"]
    assert "Phone" not in fieldnames and "Fax" not in fieldnames
    assert fieldnames[-3:] == [
        "service_approval_number",
        "provider_approval_number",
        "snapshot_last_modified",
    ]
    assert rows[0]["service_approval_number"] == "SE-00001234"
    assert rows[0]["ServiceApprovalNumber"] == "SE-00001234"  # original kept
    assert rows[1]["service_approval_number"] == "SE-00000005"
    assert rows[1]["provider_approval_number"] == "PR-00000007"
    assert rows[1]["ServiceApprovalNumber"] == "se 5"  # original kept as published
    assert rows[2]["service_approval_number"] is None  # null, not invented
    assert rows[2]["provider_approval_number"] is None
    assert all(r["snapshot_last_modified"] == "Wed, 28 Oct 2026 19:28:15 GMT" for r in rows)
    assert all("(02) 5550 0000" not in r.values() for r in rows)


def test_build_processed_rows_providers_blank_service_number_is_null():
    rows, fieldnames, dropped = build_processed_rows(
        parse_csv(PROVIDERS_CSV.encode()), PROVIDERS, None
    )
    assert dropped == []
    assert rows[0]["provider_approval_number"] == "PR-00000042"
    assert rows[0]["service_approval_number"] is None
    assert rows[0]["snapshot_last_modified"] is None


def test_gzip_bytes_round_trips_and_is_deterministic():
    data = SERVICES_CSV.encode() * 50
    packed = gzip_bytes(data)
    assert gzip.decompress(packed) == data
    assert gzip_bytes(data) == packed
