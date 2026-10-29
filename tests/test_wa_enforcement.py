"""Tests for Western Australia (WA ECRU) enforcement actions parser."""

from __future__ import annotations

from scrapers.parse_wa_enforcement import (
    INDIVIDUAL_NOTE,
    extract_provider_info,
    extract_service_info,
    map_wa_action_type,
    parse_wa_date,
    parse_wa_html_table,
)

SAMPLE_TABLE_HTML = """
<!DOCTYPE html>
<html>
<body>
<table class="cbResultSetTable">
  <tr>
    <th>Year of action</th>
    <th>Date of action</th>
    <th>Provider (provider number)</th>
    <th>Service name</th>
    <th>Compliance action type</th>
    <th>Post code</th>
  </tr>
  <tr>
    <td>Year of action: 2013</td>
    <td>Date of action: 16/09/2013</td>
    <td>Provider (provider number): Lady Bug Holdings Pty Ltd (PR-00007392)</td>
    <td>Service name: Melville Day Care Centre, 39 Rome Road, Melville WA 6158</td>
    <td>Compliance action type: Compliance Notice</td>
    <td>Post code: 6158</td>
  </tr>
  <tr>
    <td>Year of action: 2015</td>
    <td>Date of action: 30/11/2015</td>
    <td>Provider (provider number): Mary Maker (PR-00008204)</td>
    <td>Service name: Nyier Family Day Care (SE-00014349)</td>
    <td>Compliance action type: Suspension of Provider Approval</td>
    <td>Post code: 6090</td>
  </tr>
  <tr>
    <td>Year of action: 2015</td>
    <td>Date of action: 29/12/2015</td>
    <td>Provider (provider number): LPR Holdings Pty Ltd (PR 00007412)</td>
    <td>Service name: St Brigid's Outside School Hours Care (SE 00013119), St Brigid's Primary School at 20 Toodyay Road, Middle Swan</td>
    <td>Compliance action type: Disciplinary Proceedings State Administrative Tribunal</td>
    <td>Post code: 6056</td>
  </tr>
  <tr>
    <td>Year of action: 2015</td>
    <td>Date of action: 18/12/2015</td>
    <td>Provider (provider number): Raima-Leigh ZAHRA (CS-00051586)</td>
    <td>Service name:</td>
    <td>Compliance action type: Prosecution</td>
    <td>Post code: 6000</td>
  </tr>
</table>
</body>
</html>
"""


def test_map_wa_action_type():
    assert map_wa_action_type("Compliance Notice") == ("compliance_notice", None)
    t, note = map_wa_action_type("Disciplinary Proceedings State Administrative Tribunal")
    assert t == "prosecution"
    assert "State Administrative Tribunal" in note
    assert map_wa_action_type("Prosecution") == ("prosecution", None)
    assert map_wa_action_type("Emergency Action Notice") == ("emergency_action_notice", None)
    assert map_wa_action_type("Cancellation of Provider Approval") == ("approval_cancelled", None)
    assert map_wa_action_type("Suspension of Service Approval") == ("approval_suspended", None)
    assert map_wa_action_type("Service Approval Conditions Imposed") == ("condition_imposed", None)
    assert map_wa_action_type("Enforceable Undertaking") == ("enforceable_undertaking", None)


def test_parse_wa_date():
    assert parse_wa_date("16/09/2013") == "2013-09-16"
    assert parse_wa_date("04/03/2016") == "2016-03-04"
    assert parse_wa_date("2024-11-20") == "2024-11-20"
    assert parse_wa_date("") is None
    assert parse_wa_date(None) is None


def test_extract_provider_info_company():
    name, pr, cs, notes = extract_provider_info("Lady Bug Holdings Pty Ltd (PR-00007392)")
    assert name == "Lady Bug Holdings Pty Ltd"
    assert pr == "PR-00007392"
    assert cs is None
    assert INDIVIDUAL_NOTE not in notes


def test_extract_provider_info_individual_withheld():
    name, pr, cs, notes = extract_provider_info("Mary Maker (PR-00008204)")
    assert name is None  # Withheld
    assert pr == "PR-00008204"
    assert cs is None
    assert INDIVIDUAL_NOTE in notes


def test_extract_provider_info_certified_supervisor_withheld():
    name, pr, cs, notes = extract_provider_info("Raima-Leigh ZAHRA (CS-00051586)")
    assert name is None  # Withheld
    assert pr is None
    assert cs == "CS-00051586"
    assert INDIVIDUAL_NOTE in notes
    assert any("certified_supervisor: CS-00051586" in n for n in notes)


def test_extract_service_info():
    srv, se, addr, suburb = extract_service_info("Nyier Family Day Care (SE-00014349)")
    assert srv == "Nyier Family Day Care"
    assert se == "SE-00014349"

    srv, se, addr, suburb = extract_service_info(
        "St Brigid's Outside School Hours Care (SE 00013119), St Brigid's Primary School at 20 Toodyay Road, Middle Swan"
    )
    assert srv == "St Brigid's Outside School Hours Care"
    assert se == "SE-00013119"
    assert "20 Toodyay Road" in addr


def test_parse_wa_html_table():
    rows = parse_wa_html_table(SAMPLE_TABLE_HTML, "sample.html", "2026-10-29T08:00:00Z")
    assert len(rows) == 4

    r0 = rows[0]
    assert r0["jurisdiction"] == "WA"
    assert r0["service_name"] == "Melville Day Care Centre"
    assert r0["provider_name"] == "Lady Bug Holdings Pty Ltd"
    assert r0["provider_approval_number"] == "PR-00007392"
    assert r0["action_type"] == "compliance_notice"
    assert r0["date_issued"] == "2013-09-16"
    assert r0["postcode"] == "6158"

    r1 = rows[1]
    assert r1["provider_name"] is None  # Withheld individual
    assert INDIVIDUAL_NOTE in r1["notes"]
    assert r1["service_approval_number"] == "SE-00014349"
    assert r1["provider_approval_number"] == "PR-00008204"
    assert r1["action_type"] == "approval_suspended"

    r2 = rows[2]
    assert r2["provider_approval_number"] == "PR-00007412"
    assert r2["service_approval_number"] == "SE-00013119"
    assert r2["action_type"] == "prosecution"

    r3 = rows[3]
    assert r3["provider_name"] is None
    assert INDIVIDUAL_NOTE in r3["notes"]
    assert "certified_supervisor: CS-00051586" in r3["notes"]
