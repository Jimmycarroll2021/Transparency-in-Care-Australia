"""Offline tests for the VECRA enforcement parser. No network access."""

from __future__ import annotations

import json

from bs4 import BeautifulSoup
from scrapers import parse_vecra_enforcement as vecra

FIXTURE = """
<html><body><main>
<h2>Enforcement action summary table</h2>
<table>
<tr><th scope="col">Compliance action type</th><th scope="col">August 2026</th></tr>
<tr><td><strong>Administrative</strong></td><td>&nbsp;</td></tr>
<tr><td>Caution letter issued</td><td>34</td></tr>
<tr><td>Other*<br/>May include other regulatory notices</td><td>1,010</td></tr>
<tr><td><strong>Statutory</strong></td><td>&nbsp;</td></tr>
<tr><td>Approval cancelled &ndash; provider</td><td>2</td></tr>
<tr><td>Prohibition notice issued</td><td>-</td></tr>
<tr><td>Emergency action notice issued</td><td>&nbsp;</td></tr>
<tr><td><strong>Grand total</strong></td><td>394</td></tr>
</table>
<h2>Enforcement actions &ndash; August 2026</h2>
<table>
<tr><th>Service and, or provider details</th><th>Action taken</th>
<th>Reason for enforcement action</th><th>Date enforcement action issued</th></tr>
<tr>
<td><strong>Service:</strong> Bulsho Family Day Care Pty Ltd<br/>28 Laurel Cres, Campbellfield, Vic, 3061<br/><br/>
<strong>Service approval number:</strong> SE-00012251<br/><br/>
<strong>Approved provider name:</strong> Bulsho Family Day Care Pty Ltd<br/><br/>
<strong>Approved provider number:</strong> PR-00006942</td>
<td>Compliance notice issued</td>
<td><p>Due to non-compliance with the National Law and/or National Regulations:</p><ul>
<li>Regulation 97(3)(ab) - Emergency and evacuation procedures</li>
<li>Regulation 102AAC -<span> </span>Risk assessment</li>
<li>Section 167(1) &ndash; Offence relating to protection of children from harm and hazards</li>
<li>Section on 51(4C) - Conditions on service approval</li>
<li>Section 167(1) - repeated</li></ul></td>
<td>3 August 2026</td>
</tr>
<tr>
<td><p><strong>Service:</strong> Clyde Creek PS TheirCare<br/>Clyde Creek Primary School, 40 Eliston Ave, Clyde, Vic, 3978<br/><br/>
<strong>Service approval number:</strong> SE 40022723</p>
<p><strong>Approved provider name: </strong>Jane Citizen</p>
<p><strong>Approved provider number:</strong> pr-40011145</p></td>
<td>Direction to suspend staff or volunteer (not FDC educator)</td>
<td><p>Due to non-compliance with the National Law and/or National Regulations:</p><ul>
<li>Section 188(2) - Offence to engage person to whom prohibition notice applies. Ms Mary Example was named.</li></ul></td>
<td>14 August 2026</td>
</tr>
</table>
</main></body></html>
"""

DOC = "https://www.vecra.vic.gov.au/enforcement-actions-august-2026"
KWARGS = {
    "source_document": DOC,
    "captured_at": "2026-10-29T03:00:00+00:00",
    "source_snapshot": "data/raw/vecra-enforcement/x.html",
}


def rows() -> list[dict]:
    return vecra.parse_actions(FIXTURE, period_label="August 2026", **KWARGS)


def test_cell_splitting_service_and_address():
    row = rows()[0]
    assert row["service_name"] == "Bulsho Family Day Care Pty Ltd"
    assert row["address"] == "28 Laurel Cres, Campbellfield, Vic, 3061"
    assert (row["suburb"], row["state"], row["postcode"]) == ("Campbellfield", "VIC", "3061")
    assert row["provider_name"] == "Bulsho Family Day Care Pty Ltd"


def test_cell_splitting_with_paragraphs_and_school_address():
    row = rows()[1]
    assert row["service_name"] == "Clyde Creek PS TheirCare"
    assert row["address"] == "Clyde Creek Primary School, 40 Eliston Ave, Clyde, Vic, 3978"
    assert row["suburb"] == "Clyde"
    assert row["postcode"] == "3978"


def test_key_normalisation_keeps_raw():
    first, second = rows()
    assert first["service_approval_number"] == "SE-00012251"
    assert first["provider_approval_number"] == "PR-00006942"
    assert second["service_approval_number_raw"] == "SE 40022723"
    assert second["service_approval_number"] == "SE-40022723"
    assert second["provider_approval_number_raw"] == "pr-40011145"
    assert second["provider_approval_number"] == "PR-40011145"


def test_missing_key_is_null_and_logged():
    html = FIXTURE.replace("SE-00012251", "not stated")
    row = vecra.parse_actions(html, period_label="August 2026", **KWARGS)[0]
    assert row["service_approval_number"] is None
    assert "service approval number missing" in row["notes"]
    assert row["record_id"]  # falls back to the provider key


def test_dates():
    first, second = rows()
    assert first["date_issued"] == "2026-08-03"
    assert first["date_issued_raw"] == "3 August 2026"
    assert second["date_issued"] == "2026-08-14"
    assert vecra.parse_date("31 February 2026") is None
    assert vecra.parse_date("") is None


def test_legal_references_deduplicated_and_cleaned():
    refs = json.loads(rows()[0]["legal_references"])
    assert refs == [
        "Regulation 97(3)(ab)",
        "Regulation 102AAC",
        "Section 167(1)",
        "Section 51(4C)",
    ]


def test_action_type_mapping():
    first, second = rows()
    assert first["action_type"] == "compliance_notice"
    assert second["action_type"] == "direction_to_exclude"
    assert second["action_type_raw"] == "Direction to suspend staff or volunteer (not FDC educator)"
    m = vecra.map_action_type
    assert m("Cancellation of provider approval") == "approval_cancelled"
    assert m("Amendment of service approval") == "approval_amended"
    assert m("Suspension of service approval") == "approval_suspended"
    assert m("Show cause") == "show_cause_notice"
    assert m("Emergency action notice issued") == "emergency_action_notice"
    assert m("Prosecution initiated") == "prosecution"
    assert m("Enforceable undertaking issued") == "enforceable_undertaking"
    assert m("Caution letter issued") == "other"
    assert m("Inappropriate person excluded") == "other"
    assert m("Something new") == "other"


def test_personal_names_removed_and_counted():
    second = rows()[1]
    assert "Mary Example" not in second["reason"]
    assert "[name removed]" in second["reason"]
    assert "1 personal name" in second["notes"]


def test_individual_provider_name_withheld():
    second = rows()[1]
    assert second["provider_name"] is None
    assert "provider name withheld" in second["notes"]
    assert rows()[0]["provider_name"] == "Bulsho Family Day Care Pty Ltd"


def test_record_id_is_stable_and_distinct():
    a = rows()
    b = rows()
    assert [r["record_id"] for r in a] == [r["record_id"] for r in b]
    assert a[0]["record_id"] != a[1]["record_id"]
    expected = vecra.record_hash(
        "VIC", "SE-00012251", "Compliance notice issued", "3 August 2026", a[0]["reason"]
    )
    assert a[0]["record_id"] == expected


def test_rows_have_schema_fields_only():
    for row in rows():
        assert set(row) == set(vecra.FIELDNAMES)
        assert row["jurisdiction"] == "VIC"
        assert row["period_label"] == "August 2026"


def test_count_parsing():
    counts = vecra.parse_counts(FIXTURE, page_period_label="August 2026", **KWARGS)
    by_label = {c["action_type_raw"].split(" May")[0]: c for c in counts}
    assert by_label["Caution letter issued"]["count"] == 34
    assert by_label["Caution letter issued"]["section"] == "Administrative"
    assert by_label["Other*"]["count"] == 1010
    assert by_label["Prohibition notice issued"]["count"] == 0
    assert by_label["Prohibition notice issued"]["count_raw"] == "-"
    assert by_label["Prohibition notice issued"]["section"] == "Statutory"
    # A blank cell on a real row stays null rather than becoming zero.
    assert by_label["Emergency action notice issued"]["count"] is None
    assert by_label["Grand total"]["count"] == 394
    assert by_label["Grand total"]["section"] is None
    assert "Administrative" not in by_label  # section headers are not data rows
    assert all(c["period_label"] == "August 2026" for c in counts)


def test_count_parsing_multi_column_headers():
    html = (
        "<table><tr><th>Compliance action type</th><th>2025</th><th>2026 (Q1)</th></tr>"
        "<tr><td>Caution letter issued</td><td>110</td><td>19</td></tr></table>"
    )
    counts = vecra.parse_counts(html, page_period_label="x", **KWARGS)
    assert [(c["period_label"], c["count"]) for c in counts] == [("2025", 110), ("2026 (Q1)", 19)]


def test_page_discovery_and_archive_links():
    index = """
    <a href="/enforcement-actions-august-2026">a</a>
    <a href="/enforcement-actions-april-may-2026">b</a>
    <a href="/enforcement-actions-january-march-2026">c</a>
    <a href="/enforcement-action-summary-table">d</a>
    <a href="#enforcement-actions-we-can-publish">e</a>
    <a href="/enforcement-actions-we-can-publish">f</a>
    <a href="/sites/default/files/2026-06/Enforcement-actions-2025-National-Law.pdf">g</a>
    <a href="/sites/default/files/2026-06/Enforcement-actions-2025-National-Law.docx">h</a>
    """
    pages = vecra.discover_pages(index)
    assert set(pages) == {
        "august-2026",
        "april-may-2026",
        "january-march-2026",
        vecra.SUMMARY_SLUG,
    }
    assert pages["august-2026"] == "https://www.vecra.vic.gov.au/enforcement-actions-august-2026"
    archives = vecra.discover_archive_links(index)
    assert len(archives) == 2
    assert all("/sites/default/files/" in a for a in archives)
    assert vecra.slug_to_label("april-may-2026") == "April to May 2026"
    assert vecra.slug_to_label("august-2026") == "August 2026"


def test_split_address_unparsable_gives_nulls():
    assert vecra.split_address("Somewhere unknown") == (None, None, None)
    assert vecra.split_address(None) == (None, None, None)


def test_cell_lines_handles_br_and_paragraphs():
    cell = BeautifulSoup("<td>a<br/>b<p>c</p>d</td>", "lxml").td
    assert vecra.cell_lines(cell) == ["a", "b", "c", "d"]
