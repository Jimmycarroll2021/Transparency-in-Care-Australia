"""Offline tests for the South Australian (ESB) enforcement parser. No network access."""

from __future__ import annotations

import json

import pytest
from scrapers import parse_sa_enforcement as sa

CURRENT_FIXTURE = """
<html><body><div class="field--name-body">
<h2>Statutory compliance actions issue by type and year</h2>
<table border="1">
<thead><tr><th scope="col">Type</th><th>2025-26</th><th>2026-27</th></tr></thead>
<tbody>
<tr><td>Emergency action notice issued</td><td>68</td><td>12</td></tr>
<tr><td>Compliance notice issued</td><td>1,162</td><td>-</td></tr>
<tr><td>Total</td><td>1,230</td><td>12</td></tr>
</tbody></table>
<p><em>Table last updated: 18 October 2026</em></p>
<h2>Happy Haven OSHC Mitcham (SE-00010642)</h2>
<p><strong>Address: </strong>41 Example Road, MITCHAM SA 5062 <br/>
<strong>Approved Provider: </strong>HAPPY HAVEN OSHC PTY LTD  (PR-40001361)</p>
<p><strong>Details:</strong> <br/>
A Delegate of the Education Standards Board (ESB) is satisfied that the Approved Provider has contravened: </p>
<ul><li>Section 167(1) &ndash; Offence relating to protection of children from harm and hazards</li>
<li>Regulation 103 - Premises to be safe</li></ul>
<p><strong>Action Taken:</strong> <br/>
Issue of Compliance Notice (Section 177 of the National Law) on Tuesday 6th October 2026 requiring the following by a specified time: </p>
<ol><li>Repair the fence.</li></ol>
<h2>St Michael's College OSHC &ndash; Extend  (SE 00010955)</h2>
<p><strong>Address:</strong> 78 East Avenue, Beverly SA 5009 <br/>
<strong>Approved Provider:</strong> Extend (Australia) Pty Ltd  (PR-00002530)</p>
<p><strong>Action Taken:</strong> <br/>
Pursuant to Section 55 of the National Law, the following conditions were imposed from 12 Aug 2026:</p>
<ol><li>No more than 59 children at any one time.</li></ol>
<h2>Citizen Family Day Care (SE-00011111)</h2>
<p><strong>Address:</strong> 5 Home Street, Elizabeth SA 5112 <br/>
<strong>Approved Provider:</strong> Jane Citizen (PR-00009999)</p>
<p><strong>Action Taken:</strong> <br/>
Issue of Emergency Action Notice (Section 179 of the National Law) on 1 September 2026 requiring the following:</p>
<ol><li>Supervise children.</li></ol>
<h2>Blueskies Early Learning Centre (SE&ndash;00010181)</h2>
<p><strong>Address:</strong> 17 Famechon Crescent MODBURY NORTH SA 5092 <br/>
<strong>Approved Provider:</strong> Smartcare Solutions Pty. Ltd. (PR-400366356)</p>
<p><strong>Action Taken:</strong> <br/>
Issue of Emergency Action Notice (Section 179 of the National Law) on, requiring the following:</p>
<h2>Main navigation</h2>
<p>For families and educators</p>
</div></body></html>
"""

OLD_FIXTURE = """
<html><body><div class="field--name-body">
<p>In this list, the National Law (below) means the Education and Care Services National Law.</p>
<h2>Cobbler Creek OSHC</h2>
<p><strong>Approved provider:</strong> Golden Grove Primary School Council Inc.</p>
<p><strong>Address:</strong> 140 Bicentennial Drive, Golden Grove SA 5125</p>
<p><strong>Date of action:</strong> 9/2/2021</p>
<p><strong>Type of action:</strong> Compliance notice issued pursuant to s 177 of the National Law</p>
<p><strong>Details of action:</strong> The Registrar issued a compliance notice. The matters included:</p>
<ul><li>Protection of children from harm and hazards pursuant to s 167</li>
<li>Requirement to have policies and procedures pursuant to reg 168.</li></ul>
<p><strong>The approved provider has provided evidence that they have complied.</strong></p>
<h2>Little Sprouts Family Day Care</h2>
<p><strong>Approved provider:</strong> Alex Example</p>
<p><strong>Address:</strong> 9 Private Lane, Salisbury SA 5108</p>
<p><strong>Date of action:</strong> 30/10/15</p>
<p><strong>Type of action:</strong> Suspension of service approval without show cause pursuant to s. 73 of the National Law</p>
</div></body></html>
"""


def rows_for(html: str, period: str = "Current compliance action") -> list[dict]:
    return sa.parse_actions(
        html,
        source_document="https://www.esb.sa.gov.au/example",
        captured_at="2026-10-29T03:00:00+00:00",
        period_label=period,
        source_snapshot="data/raw/sa-enforcement/x.html",
    )


def by_service(rows: list[dict], needle: str) -> dict:
    return next(r for r in rows if needle in (r["service_name"] or ""))


def test_sections_become_rows_and_navigation_is_skipped():
    rows = rows_for(CURRENT_FIXTURE)
    assert len(rows) == 4
    assert all(r["jurisdiction"] == "SA" for r in rows)


def test_both_keys_are_normalised_and_raw_kept():
    row = by_service(rows_for(CURRENT_FIXTURE), "Happy Haven")
    assert row["service_approval_number"] == "SE-00010642"
    assert row["service_approval_number_raw"] == "SE-00010642"
    assert row["provider_approval_number"] == "PR-40001361"
    assert row["provider_approval_number_raw"] == "PR-40001361"
    assert row["provider_name"] == "HAPPY HAVEN OSHC PTY LTD"
    assert row["service_name"] == "Happy Haven OSHC Mitcham"
    assert (row["suburb"], row["state"], row["postcode"]) == ("MITCHAM", "SA", "5062")


def test_se_without_hyphen_is_normalised_and_noted():
    row = by_service(rows_for(CURRENT_FIXTURE), "St Michael")
    assert row["service_approval_number"] == "SE-00010955"
    assert row["service_approval_number_raw"] == "SE 00010955"
    assert "without the hyphen" in row["notes"]
    assert row["provider_name"] == "Extend (Australia) Pty Ltd"
    assert row["service_name"] == "St Michael's College OSHC – Extend"


def test_en_dash_in_key_is_normalised_unparsable_pr_is_null():
    row = by_service(rows_for(CURRENT_FIXTURE), "Blueskies")
    assert row["service_approval_number"] == "SE-00010181"
    assert "dash other than a hyphen" in row["notes"]
    assert row["provider_approval_number"] is None
    assert row["provider_approval_number_raw"] == "PR-400366356"
    assert "unparsable" in row["notes"]
    assert "PR-4003" not in (row["provider_name"] or "")
    assert row["suburb"] == "MODBURY NORTH"


def test_individual_provider_is_withheld_everywhere():
    rows = rows_for(CURRENT_FIXTURE)
    row = by_service(rows, "Citizen Family Day Care")
    assert row["provider_name"] is None
    assert row["provider_approval_number"] == "PR-00009999"
    assert row["address"] is None
    assert row["suburb"] == "Elizabeth"
    assert "provider name withheld" in row["notes"]
    assert "Jane" not in json.dumps(rows)


def test_individual_provider_withheld_on_old_page_and_address_dropped():
    rows = rows_for(OLD_FIXTURE, "Historical compliance action 2021")
    row = by_service(rows, "Little Sprouts")
    assert row["provider_name"] is None
    assert row["address"] is None
    assert "Alex" not in json.dumps(rows)
    org = by_service(rows, "Cobbler Creek")
    assert org["provider_name"] == "Golden Grove Primary School Council Inc."


def test_dates_word_ordinal_weekday_abbreviation_numeric_and_partial():
    assert sa.find_date("on Tuesday 6th October 2026 requiring") == (
        "2026-10-06",
        "Tuesday 6th October 2026",
    )
    assert sa.find_date("from 12 Aug 2026:")[0] == "2026-08-12"
    assert sa.find_date("9/2/2021") == ("2021-02-09", "9/2/2021")
    assert sa.find_date("30/10/15")[0] == "2015-10-30"
    assert sa.find_date("31/02/2021")[0] is None
    assert sa.find_date("no date here") == (None, None)
    assert sa.find_partial_date("Notice on 24 October") == "24 October"
    assert sa.find_partial_date("on 24 October 2025") is None


def test_row_dates():
    rows = rows_for(CURRENT_FIXTURE)
    happy = by_service(rows, "Happy Haven")
    assert (happy["date_issued"], happy["date_issued_raw"]) == (
        "2026-10-06",
        "Tuesday 6th October 2026",
    )
    cond = by_service(rows, "St Michael")
    assert cond["date_issued"] == "2026-08-12"
    assert "may be an effective date" in cond["notes"]
    missing = by_service(rows, "Blueskies")
    assert missing["date_issued"] is None
    assert "date missing" in missing["notes"]
    old = rows_for(OLD_FIXTURE, "Historical compliance action 2021")
    assert by_service(old, "Cobbler")["date_issued"] == "2021-02-09"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "Issue of Compliance Notice (Section 177 of the National Law) on 1 May 2026",
            "compliance_notice",
        ),
        (
            "Issue of an Emergency Action Notice (Section 179 of the National Law)",
            "emergency_action_notice",
        ),
        ("Direction to take emergency action pursuant to s 179", "emergency_action_notice"),
        (
            "Pursuant to Section 55 of the National Law, the following conditions were imposed",
            "condition_imposed",
        ),
        (
            "Amendment of service approval by the regulatory authority. The following conditions",
            "condition_imposed",
        ),
        (
            "Suspension of service approval without show cause pursuant to s. 73",
            "approval_suspended",
        ),
        ("Cancellation of provider approval pursuant to s. 33", "approval_cancelled"),
        ("Enforceable Undertaking", "enforceable_undertaking"),
        ("Compliance direction pursuant to s 176", "compliance_direction"),
        ("Prohibition notice issued", "prohibition_notice"),
        ("Show cause notice", "show_cause_notice"),
        ("Direction to suspend staff or volunteer", "direction_to_exclude"),
        ("Enforceable undertaking and Compliance Direction", "other"),
        ("Something the register invented", "other"),
        ("", "other"),
    ],
)
def test_action_type_mapping(raw, expected):
    assert sa.map_action_type(raw) == expected


def test_action_text_and_legal_references():
    row = by_service(rows_for(CURRENT_FIXTURE), "Happy Haven")
    assert row["action_type"] == "compliance_notice"
    assert row["action_type_raw"].startswith("Issue of Compliance Notice (Section 177")
    assert "requiring" not in row["action_type_raw"]
    refs = json.loads(row["legal_references"])
    assert "Section 167(1)" in refs and "Regulation 103" in refs and "Section 177" in refs
    assert row["reason"].startswith("A Delegate of the Education Standards Board")
    assert "Repair the fence" not in row["reason"]
    cond = by_service(rows_for(CURRENT_FIXTURE), "St Michael")
    assert cond["action_type"] == "condition_imposed"
    assert cond["reason"] is None
    assert "no reason or contravention text" in cond["notes"]


def test_old_page_format_type_reason_and_outcome():
    row = by_service(rows_for(OLD_FIXTURE, "Historical compliance action 2021"), "Cobbler")
    assert row["action_type"] == "compliance_notice"
    assert row["service_approval_number"] is None
    assert "service approval number not printed" in row["notes"]
    assert "outcome printed: The approved provider has provided evidence" in row["notes"]
    refs = json.loads(row["legal_references"])
    assert "s 177" in refs and "s 167" in refs and "reg 168" not in refs
    assert "Reg 168" in refs
    assert "provided evidence" not in row["reason"]


def test_year_mismatch_note():
    rows = rows_for(OLD_FIXTURE, "Historical compliance action 2022")
    assert "differs from the 2022 page" in by_service(rows, "Cobbler")["notes"]


def test_record_id_is_stable_and_duplicates_are_marked():
    first = rows_for(CURRENT_FIXTURE)
    second = rows_for(CURRENT_FIXTURE)
    assert [r["record_id"] for r in first] == [r["record_id"] for r in second]
    assert len({r["record_id"] for r in first}) == len(first)
    both = first + second
    assert sa.mark_duplicates(both) == len(first)
    assert "duplicate record_id" in both[-1]["notes"]


def test_summary_counts():
    counts = sa.parse_counts(
        CURRENT_FIXTURE,
        source_document="https://www.esb.sa.gov.au/example",
        captured_at="2026-10-29T03:00:00+00:00",
    )
    assert len(counts) == 6
    first = counts[0]
    assert (first["period_label"], first["action_type_raw"], first["count"]) == (
        "2025-26",
        "Emergency action notice issued",
        68,
    )
    thousand = next(c for c in counts if c["count_raw"] == "1,162")
    assert thousand["count"] == 1162
    dash = next(c for c in counts if c["count_raw"] == "-")
    assert dash["count"] == 0
    assert any(c["action_type_raw"] == "Total" and c["count"] == 12 for c in counts)
    assert sa.table_last_updated(CURRENT_FIXTURE) == "18 October 2026"


def test_split_address():
    assert sa.split_address("78 East Avenue, Beverly SA 5009") == ("Beverly", "SA", "5009")
    assert sa.split_address("29 Jeanette Cres, Aberfoyle Park, SA 5159") == (
        "Aberfoyle Park",
        "SA",
        "5159",
    )
    assert sa.split_address("66-68 Bolton Court, FLAGSTAFF HILL, 5159") == (
        "FLAGSTAFF HILL",
        None,
        "5159",
    )
    assert sa.split_address("2-18 Golden Grove Rd, MODBURY 502") == (None, None, None)
    assert sa.split_address(None) == (None, None, None)


def test_discover_historical_pages_from_link_text_and_sitemap():
    html = """
    <div class="field--name-body">
    <a href="/node/907">Historical compliance action: 2022-23</a>
    <a href="/node/606">Historical compliance action: 2020</a>
    <a href="/node/5">Some other link</a>
    </div>"""
    sitemap = """<urlset>
    <url><loc>https://www.esb.sa.gov.au/historical-compliance-action</loc></url>
    <url><loc>https://www.esb.sa.gov.au/historical-compliance-action-2022</loc></url>
    <url><loc>https://www.esb.sa.gov.au/historical-compliance-action-2020</loc></url>
    <url><loc>https://www.esb.sa.gov.au/about-us</loc></url>
    <url><loc>https://example.org/historical-compliance-action-1999</loc></url>
    </urlset>"""
    assert sa.discover_historical(html, sitemap) == [
        "https://www.esb.sa.gov.au/historical-compliance-action-2022-23",
        "https://www.esb.sa.gov.au/historical-compliance-action-2020",
        "https://www.esb.sa.gov.au/historical-compliance-action-2022",
    ]
    assert len(sa.discover_historical(html)) == 2


def test_canonical_slug_ignores_non_register_nodes():
    page = (
        '<link rel="canonical" href="https://www.esb.sa.gov.au/historical-compliance-action-2018">'
    )
    assert sa.canonical_slug(page) == "historical-compliance-action-2018"
    pdf_node = '<link rel="canonical" href="https://www.esb.sa.gov.au/node/606">'
    assert sa.canonical_slug(pdf_node) is None


def test_slug_and_period_labels():
    assert sa.slug_for("https://www.esb.sa.gov.au/historical-compliance-action-2021") == (
        "historical-compliance-action-2021"
    )
    assert sa.period_label_for("historical-compliance-action-2022-23") == (
        "Historical compliance action 2022-23"
    )
    assert sa.period_label_for(sa.CURRENT_SLUG) == "Current compliance action"


def test_licence_note_uses_page_wording_when_present():
    note = sa.licence_note_from("<p>(c) Government of South Australia. All rights reserved.</p>")
    assert "All rights reserved" in note
    assert "consent" in note
    assert "All rights reserved" in sa.licence_note_from(None)
