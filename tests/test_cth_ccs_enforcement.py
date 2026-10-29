"""Tests for the Commonwealth CCS enforcement register parser. No network.

The fixture is a best guess at the live structure (the live site was unreachable when the
parser was written), so these tests prove the parsing logic, not the match to the real page.
"""

import json
import re
from pathlib import Path

import httpx
from scrapers import parse_cth_ccs_enforcement as cth
from scrapers.parse_cth_ccs_enforcement import (
    CURRENT_URL,
    PAST_URL,
    map_action_type,
    parse_cth_date,
    parse_location,
    parse_page,
)

SCHEMA = json.loads(
    (
        Path(__file__).resolve().parent.parent / "data/schemas/enforcement-action.schema.json"
    ).read_text()
)

HEAD = (
    "<tr><th>Provider name</th><th>ABN</th><th>Location</th><th>Service type</th>"
    "<th>Type of sanction</th><th>Conditions of approval or grounds for sanction</th>"
    "<th>Date of effect</th><th>End date</th></tr>"
)

CURRENT = f"""
<html><body>
<h2>Enforcement actions in the last 12 months</h2>
<table>{HEAD}
<tr><td>Sunny Days Early Learning Pty Ltd</td><td>12 345 678 901</td><td>Penrith NSW 2750</td>
  <td>Centre Based Day Care</td><td>Cancellation of CCS approval</td>
  <td>Failure to comply with the Family Assistance Law</td><td>1 July 2026</td><td></td></tr>
<tr><td>Little Stars Care Inc</td><td></td><td>QLD</td><td>Outside School Hours Care</td>
  <td>Conditions on approval</td><td>Must provide monthly attendance reports</td>
  <td>15/08/2026</td><td>15/02/2027</td></tr>
<tr><td>Happy Kids Group Ltd</td><td>98765432109</td><td>Perth</td><td>Family Day Care</td>
  <td>Civil penalty order</td><td>Contravention of section 85CB</td><td>03/09/2026</td><td></td></tr>
<tr><td>Bright Futures Pty Ltd</td><td></td><td>Hobart TAS</td><td>Centre Based Day Care</td>
  <td>Criminal conviction</td><td>Fraud offences, Criminal Code</td><td>20 September 2026</td><td></td></tr>
<tr><td>Jane Citizen</td><td>11 222 333 444</td><td>Cairns QLD 4870</td><td>Family Day Care</td>
  <td>Suspension of CCS approval</td><td>Citizen Family Day Care failed to keep records</td>
  <td>01/10/2026</td><td></td></tr>
<tr><td>Old Mill Learning Pty Ltd</td><td></td><td>Bendigo VIC</td><td>Centre Based Day Care</td>
  <td>Suspension of CCS approval lifted</td><td></td><td>05/10/2026</td><td></td></tr>
<tr><td>Numbered Pty Ltd SE-00012345 PR-00054321</td><td></td><td></td><td></td>
  <td>Cancellation of CCS approval</td><td></td><td>unknown date</td><td></td></tr>
</table>
<table><tr><th>Unrelated</th><th>Table</th></tr><tr><td>a</td><td>b</td></tr></table>
</body></html>
"""

PAST = f"""
<html><body><h3>2017-2018 (first half)</h3>
<table>{HEAD}
<tr><td>Ancient Pty Ltd</td><td></td><td>Darwin NT</td><td>Centre Based Day Care</td>
  <td>Cancellation of CCS approval</td><td></td><td>31/12/2017</td><td></td></tr>
</table></body></html>
"""


def current():
    return parse_page(
        CURRENT,
        role="current",
        page_url=CURRENT_URL,
        captured_at="2026-10-29T07:00:00+00:00",
        source_snapshot="x",
    )


def find(substr):
    return next(
        r for r in current() if substr in (r["date_issued_raw"] or "") + r["action_type_raw"]
    )


def test_unrelated_table_ignored_and_rows_counted():
    assert len(current()) == 7


def test_ccs_cancellation_row_with_abn_in_notes():
    r = find("Cancellation of CCS approval")
    assert r["provider_name"] == "Sunny Days Early Learning Pty Ltd"
    assert r["action_type"] == "ccs_sanction"
    assert r["date_issued"] == "2026-07-01"
    assert r["date_issued_raw"] == "1 July 2026"
    assert r["suburb"] == "Penrith" and r["state"] == "NSW" and r["postcode"] == "2750"
    assert "ccs_identifier: ABN 12345678901" in r["notes"]
    assert "service_type: Centre Based Day Care" in r["notes"]
    assert r["reason"] == "Failure to comply with the Family Assistance Law"
    assert r["service_approval_number"] is None and r["provider_approval_number"] is None
    assert r["source_document"] == CURRENT_URL
    assert r["period_label"] == "current register, Enforcement actions in the last 12 months"


def test_conditions_and_end_date():
    r = find("Conditions on approval")
    assert r["action_type"] == "ccs_sanction"
    assert r["state"] == "QLD" and r["suburb"] is None
    assert "end_date: 15/02/2027" in r["notes"]
    assert r["date_issued"] == "2026-08-15"


def test_civil_penalty_is_other_and_conviction_is_prosecution():
    assert find("Civil penalty order")["action_type"] == "other"
    assert find("Civil penalty order")["action_type_raw"] == "Civil penalty order"
    assert find("Criminal conviction")["action_type"] == "prosecution"
    assert "ccs_identifier: ABN 98765432109" in find("Civil penalty order")["notes"]


def test_individual_is_withheld_with_identifiers_and_matching_text():
    r = next(r for r in current() if r["date_issued_raw"] == "01/10/2026")
    assert r["provider_name"] is None
    assert "subject is an individual; name withheld" in r["notes"]
    assert "ccs_identifier" not in r["notes"]
    assert r["reason"] is None
    assert "citizen" not in json.dumps(r).lower()
    assert "11222333444" not in json.dumps(r)


def test_lifted_suspension_is_not_a_new_sanction():
    r = next(r for r in current() if r["date_issued_raw"] == "05/10/2026")
    assert r["action_type"] == "other"


def test_se_pr_only_when_printed_in_full():
    r = next(r for r in current() if r["date_issued_raw"] == "unknown date")
    assert r["service_approval_number"] == "SE-00012345"
    assert r["provider_approval_number"] == "PR-00054321"
    assert r["date_issued"] is None
    assert "date not parsable" in r["notes"]


def test_past_page_labelled():
    rows = parse_page(PAST, role="past", page_url=PAST_URL)
    assert len(rows) == 1
    assert rows[0]["period_label"] == "past register, 2017-2018 (first half)"
    assert rows[0]["source_document"] == PAST_URL
    assert rows[0]["state"] == "NT" and rows[0]["suburb"] == "Darwin"


def test_helpers():
    assert parse_cth_date("5 October 2026") == "2026-10-05"
    assert parse_cth_date("October 2026") is None
    assert parse_location("Somewhere odd")["address"] == "Somewhere odd"
    assert map_action_type("Immediate suspension of approval")[0] == "ccs_sanction"
    assert map_action_type("Infringement notice")[0] == "other"


def test_rows_conform_to_schema():
    props = SCHEMA["properties"]
    for r in current():
        for key in SCHEMA["required"]:
            assert r.get(key) not in (None, ""), key
        assert r["jurisdiction"] == "CTH"
        assert r["action_type"] in props["action_type"]["enum"]
        for key in ("service_approval_number", "provider_approval_number"):
            if r[key] is not None:
                assert re.search(props[key]["pattern"], r[key])
        if r["date_issued"] is not None:
            assert re.search(props["date_issued"]["pattern"], r["date_issued"])
    assert len({r["record_id"] for r in current()}) == len(current())


def test_main_returns_2_when_site_unreachable(monkeypatch):
    def boom(url, **kwargs):
        raise httpx.ConnectError("unreachable")

    monkeypatch.setattr(cth, "fetch", boom)
    assert cth.main([]) == 2
