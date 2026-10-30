"""Tests for the Tasmania (ECU) published enforcement action parser."""

import json
from pathlib import Path

from scrapers.parse_tas_enforcement import (
    INDEX_URL,
    map_tas_action_type,
    parse_page,
)

SCHEMA = json.loads(
    (
        Path(__file__).resolve().parent.parent / "data/schemas/enforcement-action.schema.json"
    ).read_text()
)

TAS_HTML = """
<html><body>
<h2>National Quality Framework – Current Enforcement Action</h2>
<h3>Enforcement Action:</h3>
<p>Service name and number: Lady Gowrie – Gordon Square Education and Care Service, SE-00009943</p>
<p>Address of the Service: 2A Gordon Square, George Town, Tasmania 7253</p>
<p>Approved Provider name and number: Lady Gowrie Tasmania Inc, PR-00005936</p>
<p>Nature of the enforcement action: Emergency Action Notice</p>
<p>Reason for taking the enforcement action: Children left unsupervised</p>
<p>Enforcement action taken and date issued: Emergency action notice issued – 19 May 2025</p>
</body></html>
"""


def test_tas_helpers():
    assert map_tas_action_type("Emergency Action Notice")[0] == "emergency_action_notice"
    assert map_tas_action_type("Compliance Notice")[0] == "compliance_notice"
    assert map_tas_action_type("Suspension of service approval")[0] == "approval_suspended"


def test_tas_parse_page():
    rows = parse_page(TAS_HTML, page_url=INDEX_URL, captured_at="2026-10-29T08:00:00Z")
    assert len(rows) == 1

    r0 = rows[0]
    assert r0["service_name"] == "Lady Gowrie – Gordon Square Education and Care Service"
    assert r0["service_approval_number"] == "SE-00009943"
    assert r0["provider_name"] == "Lady Gowrie Tasmania Inc"
    assert r0["provider_approval_number"] == "PR-00005936"
    assert r0["action_type"] == "emergency_action_notice"
    assert r0["date_issued"] == "2025-05-19"
    assert r0["suburb"] == "George Town" and r0["state"] == "TAS" and r0["postcode"] == "7253"


def test_tas_rows_conform_to_schema():
    rows = parse_page(TAS_HTML, page_url=INDEX_URL, captured_at="2026-10-29T08:00:00Z")
    import jsonschema

    for r in rows:
        jsonschema.validate(r, SCHEMA)


def test_tas_person_named_trust_provider_is_withheld_by_shared_rule():
    html = TAS_HTML.replace(
        "Lady Gowrie Tasmania Inc, PR-00005936",
        "Example Holdings Pty Ltd ATF Jane Example Unit Trust, PR-00005936",
    )
    r0 = parse_page(html, page_url=INDEX_URL, captured_at="2026-10-29T08:00:00Z")[0]
    assert r0["provider_name"] is None
    assert r0["provider_approval_number"] == "PR-00005936"
    assert "Jane" not in json.dumps(r0)


# --- Codex round 1: withheld rows keep no free text, keep keys, ids ignore names -------------

from scrapers.common import FREE_TEXT_WITHHELD_NOTE  # noqa: E402


def _tas_withheld(name="Jane Example"):
    html = TAS_HTML.replace(
        "Lady Gowrie Tasmania Inc, PR-00005936", f"{name}, PR-00005936"
    ).replace("Children left unsupervised", f"{name} left children unsupervised")
    return parse_page(html, page_url=INDEX_URL, captured_at="2026-10-29T08:00:00Z")[0]


def test_withheld_tas_row_keeps_no_free_text_and_keeps_keys():
    r0 = _tas_withheld()
    assert r0["provider_name"] is None
    assert r0["reason"] is None and r0["action_type_raw"] == "(withheld)"
    assert FREE_TEXT_WITHHELD_NOTE in r0["notes"]
    assert r0["service_approval_number"] == "SE-00009943"
    assert r0["provider_approval_number"] == "PR-00005936"
    assert "Jane" not in json.dumps(r0)


def test_tas_record_ids_are_stable():
    assert _tas_withheld("Jane Example")["record_id"] == _tas_withheld("Jane Example")["record_id"]
    assert _tas_withheld("Jane Example")["record_id"] != _tas_withheld("Mary Sample")["record_id"]
