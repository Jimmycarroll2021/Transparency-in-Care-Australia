"""Tests for the South Australia (ESB) compliance action register parser."""

import json
from pathlib import Path

from scrapers.parse_sa_enforcement import (
    INDEX_URL,
    map_sa_action_type,
    parse_page,
    parse_sa_date,
)

SCHEMA = json.loads(
    (Path(__file__).resolve().parent.parent / "data/schemas/enforcement-action.schema.json").read_text()
)

SA_HTML = """
<html><body>
<h2>Statutory compliance actions issue by type and year</h2>
<h3>St Michael's College OSHC – Extend (SE 00010955)</h3>
<p>Address: 78 East Avenue, Beverly SA 5009 Approved Provider: Extend (Australia) Pty Ltd (PR-00002530)</p>
<p>Details: A Delegate of the Education Standards Board (ESB) is satisfied that the Approved Provider has contravened:
Regulation 92 – Medication record</p>
<p>Action Taken: Issue of Compliance Notice (Section 177 of the National Law) on 13 October 2026 requiring the following by a specified time:</p>
<ol><li>Conduct an audit of all complaints.</li></ol>

<h3>Jane Doe Family Care (SE-00099999)</h3>
<p>Address: 10 Main Road, ADELAIDE SA 5000 Approved Provider: Jane Doe</p>
<p>Details: Contravened section 167</p>
<p>Action Taken: Pursuant to Section 55 of the National Law, the following conditions were imposed from 12 August 2026</p>
</body></html>
"""


def test_sa_helpers():
    assert map_sa_action_type("Issue of Compliance Notice")[0] == "compliance_notice"
    assert map_sa_action_type("Issue of Emergency Action Notice")[0] == "emergency_action_notice"
    assert map_sa_action_type("service approval is suspended")[0] == "approval_suspended"
    assert parse_sa_date("on 13 October 2026") == "2026-10-13"
    assert parse_sa_date("on 28th September 2026,") == "2026-09-28"
    assert parse_sa_date("from 12 August 2026:") == "2026-08-12"


def test_sa_parse_page():
    rows = parse_page(SA_HTML, page_url=INDEX_URL, captured_at="2026-10-29T08:00:00Z")
    assert len(rows) == 2

    r0 = rows[0]
    assert r0["service_name"] == "St Michael's College OSHC – Extend"
    assert r0["service_approval_number"] == "SE-00010955"
    assert r0["provider_name"] == "Extend (Australia) Pty Ltd"
    assert r0["provider_approval_number"] == "PR-00002530"
    assert r0["action_type"] == "compliance_notice"
    assert r0["date_issued"] == "2026-10-13"
    assert r0["suburb"] == "Beverly" and r0["state"] == "SA" and r0["postcode"] == "5009"

    r1 = rows[1]
    assert r1["service_approval_number"] == "SE-00099999"
    assert r1["provider_name"] is None
    assert "subject is an individual; name withheld" in r1["notes"]
    assert r1["action_type"] == "condition_imposed"
    assert r1["date_issued"] == "2026-08-12"


def test_sa_rows_conform_to_schema():
    rows = parse_page(SA_HTML, page_url=INDEX_URL, captured_at="2026-10-29T08:00:00Z")
    import jsonschema

    for r in rows:
        jsonschema.validate(r, SCHEMA)
