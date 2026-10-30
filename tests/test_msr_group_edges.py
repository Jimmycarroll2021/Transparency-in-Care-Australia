"""Tests for scrapers/build_msr_group_edges.py. Inline synthetic fixtures, no network.

Every entity name below is invented. No real individual is named.
"""

from __future__ import annotations

import csv
import io
import json

import pytest
from scrapers import build_msr_group_edges as msr

RESOURCES_HTML = """
<html><body>
<a href="/resources/statement-information-2026_2026-10-31.csv">2026</a>
<a href="/resources/all-statement-information_2026-10-31.csv">All statements</a>
</body></html>
"""

CSV_HEADER = [
    "IDX",
    "PeriodStart",
    "PeriodEnd",
    "Type",
    "VoluntaryCompliance",
    "HeadquarteredCountries",
    "AnnualRevenue",
    "ReportingEntities",
    "IncludedEntities",
    "ABN",
    "ACN",
    "ARBN",
    "Link",
    "IndustrySectors",
    "RelatedStatements",
]


def csv_row(idx, page_id, reporting, abns, included="", type_="Single", start="2024-01-01"):
    return {
        "IDX": idx,
        "PeriodStart": start,
        "PeriodEnd": start[:4] + "-12-31",
        "Type": type_,
        "VoluntaryCompliance": "Not assessed",
        "HeadquarteredCountries": "Australia",
        "AnnualRevenue": "100-150M",
        "ReportingEntities": reporting,
        "IncludedEntities": included,
        "ABN": abns,
        "ACN": "",
        "ARBN": "",
        "Link": f"https://modernslaveryregister.gov.au/statements/{page_id}/",
        "IndustrySectors": "Education and research",
        "RelatedStatements": "",
    }


def csv_text(rows, header=CSV_HEADER):
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=header)
    writer.writeheader()
    for r in rows:
        writer.writerow({k: r.get(k, "") for k in header})
    return buf.getvalue()


def entity_div(name, abn=None):
    abn_html = ""
    if abn:
        spaced = f"{abn[:2]} {abn[2:5]} {abn[5:8]} {abn[8:]}"
        abn_html = f'<p>ABN: <a href="/statements/?abn={abn}" target="_blank">{spaced}</a></p>'
    return f"""
      <div class="statement-entity">
        <div class="statement-entity__name">
          <a class="statement-entity__name-link" href="/statements/?company_name={name}&"
             target="_blank">{name} </a>
        </div>
        {abn_html}
        <p>
        </p>
      </div>"""


def statement_page(reporting, included=()):
    rep = "".join(entity_div(n, a) for n, a in reporting)
    inc = "".join(entity_div(*n) if isinstance(n, tuple) else entity_div(n) for n in included)
    inc_block = ""
    if included:
        inc_block = f"""
<div class="accordion statement__accordion" id="statement-included-entities-accordion">
  <h3 class="accordion__title">Included entities</h3>
  <div id="statement-included-entities" class="accordion__content collapse hide">{inc}
  </div>
</div>"""
    return f"""<html><head><title>Statement #2024-1</title></head><body>
<div class="accordion statement__accordion" id="statement-reporting-entities-accordion">
  <h3 class="accordion__title">Reporting entities</h3>
  <div id="statement-reporting-entities" class="accordion__content collapse show">{rep}
  </div>
</div>{inc_block}
<div class="related"><p>Reporting entity:</p><p>EXAMPLE OTHER LIMITED (11 111 111 111)</p></div>
</body></html>"""


# Providers: ACECQA profile rows (all providers) and provider-abn rows (priority subset).
PROFILES = [
    {
        "provider_approval_number": "PR-00000001",
        "legal_name": "Kookaburra Learning Group Ltd",
        "entity_form": "company",
        "name_withheld": "false",
    },
    {
        "provider_approval_number": "PR-00000002",
        "legal_name": "Wattle Kids Pty Ltd",
        "entity_form": "company",
        "name_withheld": "false",
    },
    {
        "provider_approval_number": "PR-00000003",
        "legal_name": "Banksia Early Years Pty. Limited",
        "entity_form": "company",
        "name_withheld": "false",
    },
    {
        "provider_approval_number": "PR-00000004",
        "legal_name": "Gumnut Care Pty Ltd",
        "entity_form": "company",
        "name_withheld": "false",
    },
    {
        "provider_approval_number": "PR-00000005",
        "legal_name": "Gumnut Care Pty Ltd",
        "entity_form": "company",
        "name_withheld": "false",
    },
    {
        "provider_approval_number": "PR-00000006",
        "legal_name": "Lilly Pilly Childcare Pty Ltd",
        "entity_form": "company",
        "name_withheld": "false",
    },
    {
        "provider_approval_number": "PR-00000007",
        "legal_name": "Waratah Centres Pty Ltd",
        "entity_form": "company",
        "name_withheld": "false",
    },
    {
        "provider_approval_number": "PR-00000008",
        "legal_name": "Sample Person",
        "entity_form": "likely_individual",
        "name_withheld": "false",
    },
    {
        "provider_approval_number": "PR-00000009",
        "legal_name": "Grevillea Kindergarten Pty Ltd",
        "entity_form": "company",
        "name_withheld": "false",
    },
]
ABN_ROWS = [
    {
        "provider_approval_number": "PR-00000001",
        "legal_name": "Kookaburra Learning Group Ltd",
        "abn": "11000000001",
        "abr_entity_name": "KOOKABURRA LEARNING GROUP LIMITED",
        "entity_type_code": "PUB",
        "match_kind": "accepted_unique",
    },
    {
        "provider_approval_number": "PR-00000002",
        "legal_name": "Wattle Kids Pty Ltd",
        "abn": "11000000002",
        "abr_entity_name": "WATTLE KIDS PTY LTD",
        "entity_type_code": "PRV",
        "match_kind": "accepted_unique",
    },
    {
        "provider_approval_number": "PR-00000003",
        "legal_name": "Banksia Early Years Pty. Limited",
        "abn": "11000000003",
        "abr_entity_name": "BANKSIA EARLY YEARS PTY LIMITED",
        "entity_type_code": "PRV",
        "match_kind": "accepted_unique",
    },
    {
        "provider_approval_number": "PR-00000006",
        "legal_name": "Lilly Pilly Childcare Pty Ltd",
        "abn": "11000000006",
        "abr_entity_name": "LILLY PILLY HOLDINGS PTY LTD",
        "entity_type_code": "PRV",
        "match_kind": "accepted_unique",
    },
    {
        "provider_approval_number": "PR-00000008",
        "legal_name": "",
        "abn": "",
        "abr_entity_name": "",
        "entity_type_code": "",
        "match_kind": "excluded_individual_or_unknown",
    },
    {
        "provider_approval_number": "PR-00000007",
        "legal_name": "Waratah Centres Pty Ltd",
        "abn": "",
        "abr_entity_name": "",
        "entity_type_code": "",
        "match_kind": "no_match",
    },
]


# ---------------------------------------------------------------------------
# Download and privacy filter
# ---------------------------------------------------------------------------


def test_find_all_statements_link_picks_the_all_years_file():
    url = msr.find_all_statements_link(RESOURCES_HTML)
    assert url == (
        "https://modernslaveryregister.gov.au/resources/all-statement-information_2026-10-31.csv"
    )


def test_find_all_statements_link_none_when_absent():
    assert msr.find_all_statements_link("<html><a href='/x.csv'>x</a></html>") is None


def test_privacy_filter_keeps_entity_columns_and_drops_person_columns():
    header = CSV_HEADER + ["SignatoryName", "ApproverFullName", "ContactEmail"]
    row = csv_row(
        "2024-1", "100", "KOOKABURRA LEARNING GROUP LIMITED (11 000 000 001)", "11000000001"
    )
    row.update(SignatoryName="A Person", ApproverFullName="B Person", ContactEmail="x@example.org")
    text = csv_text([row], header)
    out, kept, dropped = msr.privacy_filter_csv(text)
    assert dropped == ["SignatoryName", "ApproverFullName", "ContactEmail"]
    assert kept == CSV_HEADER
    assert "A Person" not in out and "B Person" not in out and "example.org" not in out
    assert "KOOKABURRA" in out


def test_privacy_filter_is_identity_when_nothing_to_drop():
    text = csv_text([csv_row("2024-1", "100", "X LTD (11 000 000 001)", "11000000001")])
    out, kept, dropped = msr.privacy_filter_csv(text)
    assert dropped == []
    assert kept == CSV_HEADER
    assert out == text


# ---------------------------------------------------------------------------
# CSV parsing and candidates
# ---------------------------------------------------------------------------


def test_parse_statements_reads_abns_and_page_id():
    text = csv_text(
        [
            csv_row(
                "2024-7",
                "200",
                "A LTD (11 000 000 001), B PTY LTD (11 000 000 002)",
                "11000000001, 11000000002",
                type_="Joint",
            )
        ]
    )
    (s,) = msr.parse_statements_csv(text)
    assert s["statement_id"] == "2024-7"
    assert s["page_id"] == "200"
    assert s["abns"] == ["11000000001", "11000000002"]
    assert s["reporting_period"] == "2024-01-01 to 2024-12-31"
    assert s["statement_url"] == "https://modernslaveryregister.gov.au/statements/200/"


def test_parse_statements_handles_bom_and_blank_abn():
    text = "﻿" + csv_text([csv_row("2024-8", "201", "NO ABN ENTITY INC", "")])
    (s,) = msr.parse_statements_csv(text)
    assert s["abns"] == []


def test_select_candidates_by_abn_and_by_childcare_term():
    rows = [
        csv_row("2024-1", "1", "KOOKABURRA LEARNING GROUP LIMITED (11 000 000 001)", "11000000001"),
        csv_row(
            "2024-2", "2", "BOTTLEBRUSH EARLY LEARNING PTY LTD (22 000 000 002)", "22000000002"
        ),
        csv_row("2024-3", "3", "IRONBARK MINING LIMITED (33 000 000 003)", "33000000003"),
        csv_row("2024-4", "4", "Coolabah Child Care Ltd", ""),
    ]
    statements = msr.parse_statements_csv(csv_text(rows))
    cands = msr.select_candidates(statements, {"11000000001"})
    by_id = {c["statement_id"]: c for c in cands}
    assert set(by_id) == {"2024-1", "2024-2", "2024-4"}
    assert by_id["2024-1"]["candidate_reason"] == "abn_match"
    assert by_id["2024-2"]["candidate_reason"] == "childcare_term"
    assert by_id["2024-4"]["candidate_reason"] == "childcare_term"


def test_childcare_term_matches_listed_terms_only():
    for name in [
        "X EARLY LEARNING",
        "X Childcare",
        "X CHILD CARE",
        "X Kindergarten",
        "X EDUCATION",
    ]:
        assert msr.CHILDCARE_TERMS.search(name)
    assert not msr.CHILDCARE_TERMS.search("IRONBARK MINING LIMITED")


# ---------------------------------------------------------------------------
# Statement page parsing
# ---------------------------------------------------------------------------


def test_parse_statement_page_reporting_and_included():
    page = statement_page(
        [("KOOKABURRA LEARNING GROUP LIMITED", "11000000001")],
        [
            "Wattle Kids Pty Ltd",
            "Wattle Kids Pty Ltd",
            "Sunrise Property Trust",
            ("Banksia Early Years Pty Ltd", "11000000003"),
        ],
    )
    parsed = msr.parse_statement_page(page)
    assert parsed["reporting"] == [
        {"name": "KOOKABURRA LEARNING GROUP LIMITED", "abn": "11000000001"}
    ]
    # duplicates listed on the page are kept once; an included entity's ABN is kept when given
    assert parsed["included"] == [
        {"name": "Wattle Kids Pty Ltd", "abn": None},
        {"name": "Sunrise Property Trust", "abn": None},
        {"name": "Banksia Early Years Pty Ltd", "abn": "11000000003"},
    ]


def test_parse_statement_page_without_included_section_and_without_abn():
    page = statement_page([("FOREIGN PARENT INC", None)])
    parsed = msr.parse_statement_page(page)
    assert parsed["reporting"] == [{"name": "FOREIGN PARENT INC", "abn": None}]
    assert parsed["included"] == []


def test_parse_statement_page_ignores_related_reports_text():
    parsed = msr.parse_statement_page(statement_page([("A LTD", "11000000001")]))
    assert all("EXAMPLE OTHER" not in r["name"] for r in parsed["reporting"])


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "a,b",
    [
        ("Banksia Early Years Pty. Limited", "BANKSIA EARLY YEARS PTY LTD"),
        ("Banksia Early Years Proprietary Limited", "banksia  early years pty ltd"),
        ("The Wattle Kids Pty Ltd", "Wattle Kids Pty. Ltd."),
    ],
)
def test_normalise_equivalences(a, b):
    assert msr.normalise(a) == msr.normalise(b)


def test_normalise_does_not_merge_different_tails():
    assert msr.normalise("Wattle Kids Pty Ltd") != msr.normalise("Wattle Kids Ltd")


# ---------------------------------------------------------------------------
# Matching and review queue
# ---------------------------------------------------------------------------

PARENT = {"name": "PARENT LTD", "abn": "99000000009"}
KOOKABURRA = {"name": "KOOKABURRA LEARNING GROUP LIMITED", "abn": "11000000001"}


def stmt(reporting, included=(), *, type_="Single", year=2024, page=None, idx=None):
    page = str(page or 100 + year % 100)
    return {
        "statement_id": idx or f"{year + 1}-{page}",
        "page_id": page,
        "statement_url": f"https://modernslaveryregister.gov.au/statements/{page}/",
        "reporting_period": f"{year}-01-01 to {year}-12-31",
        "period_end": f"{year}-12-31",
        "type": type_,
        "captured_at": "2026-10-31T00:00:00+00:00",
        "page_sha256": "abc",
        "parsed": {
            "reporting": list(reporting),
            "included": [
                {"name": i[0], "abn": i[1]} if isinstance(i, tuple) else {"name": i, "abn": None}
                for i in included
            ],
        },
    }


def layer(*statements, profiles=PROFILES, abr_types=None):
    return msr.build_layer(list(statements), profiles, ABN_ROWS, abr_types=abr_types)


def abr(code, name="PARENT LTD", abn="99000000009"):
    return {abn: {"entity_type_code": code, "entity_name": name, "source": "test"}}


def test_included_entity_by_name_needs_acecqa_and_abr_agreement():
    out = layer(
        stmt([KOOKABURRA], ["Wattle Kids Pty. Ltd.", "Banksia Early Years Proprietary Limited"])
    )
    edges = sorted(out["edges"], key=lambda e: e["provider_approval_number"])
    assert [e["provider_approval_number"] for e in edges] == ["PR-00000002", "PR-00000003"]
    assert all(e["group_key"] == "11000000001" for e in edges)
    assert all(e["match_method"] == "included_name_equals_acecqa_and_abr_name" for e in edges)


def test_included_entity_by_abn():
    out = layer(stmt([PARENT], [("Renamed Wattle Co", "11000000002")]))
    (e,) = out["edges"]
    assert e["provider_approval_number"] == "PR-00000002"
    assert e["match_method"] == "included_entity_abn_equals_provider_abn"
    assert e["group_key"] == "99000000009"
    assert out["review"] == []


def test_included_abn_beats_included_name_in_same_statement():
    out = layer(stmt([PARENT], ["Wattle Kids Pty Ltd", ("Wattle Kids Pty Ltd", "11000000002")]))
    (e,) = out["edges"]
    assert e["match_method"] == "included_entity_abn_equals_provider_abn"


def test_abr_name_disagreement_goes_to_review():
    out = layer(stmt([PARENT], ["Lilly Pilly Childcare Pty Ltd"]))
    assert out["edges"] == []
    (r,) = out["review"]
    assert r["reason"] == "abr_name_disagrees"
    assert r["candidate_provider_approval_numbers"] == "PR-00000006"


def test_ambiguous_name_goes_to_review_never_edges():
    out = layer(stmt([PARENT], ["Gumnut Care Pty Ltd"]))
    assert out["edges"] == []
    (r,) = out["review"]
    assert r["reason"] == "ambiguous_matches_several_providers"
    assert r["candidate_provider_approval_numbers"] == "PR-00000004; PR-00000005"


def test_unique_name_without_provider_abn_goes_to_review():
    out = layer(stmt([PARENT], ["Waratah Centres Pty Ltd"]))
    assert out["edges"] == []
    assert out["review"][0]["reason"] == "name_unique_provider_without_abn"


def test_fuzzy_suffix_match_goes_to_review():
    out = layer(stmt([PARENT], ["Grevillea Kindergarten"]))
    assert out["edges"] == []
    (r,) = out["review"]
    assert r["reason"] == "fuzzy_corporate_suffix_differs"
    assert r["candidate_provider_approval_numbers"] == "PR-00000009"


def test_msr_abn_that_differs_from_provider_abn_goes_to_review():
    out = layer(stmt([PARENT], [("Wattle Kids Pty Ltd", "55000000005")]))
    assert out["edges"] == []
    assert out["review"][0]["reason"] == "msr_abn_differs_from_provider_abn"
    assert out["review"][0]["msr_entity_abn"] == "55000000005"


def test_msr_abn_with_provider_abn_unresolved_goes_to_review():
    out = layer(stmt([{"name": "Waratah Centres Pty Ltd", "abn": "66000000006"}]))
    assert out["edges"] == []
    assert out["review"][0]["reason"] == "name_match_provider_abn_not_resolved"


def test_reporting_entity_name_only_goes_to_review():
    out = layer(stmt([{"name": "Waratah Centres Pty Ltd", "abn": None}]))
    assert out["edges"] == [] and out["heads"] == []
    assert out["review"][0]["reason"] == "reporting_entity_name_only"
    assert out["review"][0]["msr_role"] == "reporting_entity"


def test_individual_provider_never_appears():
    out = layer(stmt([PARENT], ["Sample Person"]))
    assert out["edges"] == [] and out["review"] == [] and out["relations"] == []
    assert out["stats"]["matches_to_excluded_providers"] == 1
    assert "Sample Person" not in repr(out) and "PR-00000008" not in repr(out)


def test_group_name_shown_only_with_non_individual_abr_type():
    # Codex round 2, finding 1(b)
    (e,) = layer(stmt([PARENT], ["Wattle Kids Pty Ltd"]), abr_types=abr("PRV"))["edges"]
    assert e["group_name"] == "PARENT LTD"
    assert e["group_name_status"] == "shown_abr_organisation_type"
    assert e["group_abr_entity_type"] == "PRV"


def test_group_name_withheld_for_individual_abr_type():
    (e,) = layer(stmt([PARENT], ["Wattle Kids Pty Ltd"]), abr_types=abr("IND"))["edges"]
    assert not e["group_name"]
    assert e["group_name_status"] == "withheld_abr_individual"
    assert "PARENT" not in repr(e)


def test_group_name_withheld_when_abr_type_unknown():
    (e,) = layer(stmt([PARENT], ["Wattle Kids Pty Ltd"]))["edges"]
    assert not e["group_name"]
    assert e["group_name_status"] == "withheld_abr_type_unknown"
    assert e["group_key"] == "99000000009"
    assert "PARENT" not in repr(e)


def test_group_name_withheld_without_abn():
    (e,) = layer(stmt([{"name": "Parent Limited", "abn": None}], ["Wattle Kids Pty Ltd"]))["edges"]
    assert not e["group_name"]
    assert e["group_name_status"] == "withheld_no_abn"


def test_group_name_comes_from_abr_entity_name_not_msr():
    msr_side = {"name": "Kookaburra Learning Group (MSR spelling)", "abn": "11000000001"}
    (e,) = layer(stmt([msr_side], ["Wattle Kids Pty Ltd"]))["edges"]
    assert e["group_name"] == "KOOKABURRA LEARNING GROUP LIMITED"
    assert "MSR spelling" not in repr(e)


def test_edge_carries_provider_identity_and_msr_abn_not_msr_name():
    # Codex round 2, finding 1(c): the included entity's identity is the ACECQA provider.
    (e,) = layer(stmt([PARENT], [("Renamed Wattle Co", "11000000002")]))["edges"]
    assert e["provider_approval_number"] == "PR-00000002"
    assert e["provider_legal_name"] == "Wattle Kids Pty Ltd"
    assert e["msr_entity_abn"] == "11000000002"
    assert "Renamed Wattle" not in repr(e)
    assert "msr_entity_name" not in e


def test_output_column_sets_hold_no_msr_side_names():
    # Codex round 2, finding 1(c): only provider_legal_name (ACECQA) and group_name (ABR gated).
    def names(cols):
        return {c for c in cols if "name" in c}

    assert names(msr.REVIEW_COLUMNS) == set()
    assert names(msr.COREPORTED_COLUMNS) == {"provider_legal_name"}
    assert names(msr.EDGE_COLUMNS) == {"provider_legal_name", "group_name", "group_name_status"}
    assert names(msr.HEAD_COLUMNS) == {"provider_legal_name", "group_name", "group_name_status"}


def test_review_rows_hold_no_names():
    out = layer(stmt([PARENT], ["Gumnut Care Pty Ltd", "Grevillea Kindergarten"]))
    assert out["review"]
    for r in out["review"]:
        assert not {k for k in r if "name" in k} - {"provider_legal_name"}
        assert "Gumnut" not in repr(r) and "Grevillea" not in repr(r)


def test_classifier_display_path_is_gone():
    for attr in ("is_organisation_name", "_shown_name", "ORGANISATION_FORMS", "_ORG_WORDS"):
        assert not hasattr(msr, attr)


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def test_self_relation_is_a_group_head_not_an_edge():
    out = layer(stmt([KOOKABURRA], ["Wattle Kids Pty Ltd", "Kookaburra Learning Group Limited"]))
    assert [e["provider_approval_number"] for e in out["edges"]] == ["PR-00000002"]
    (h,) = out["heads"]
    assert h["provider_approval_number"] == "PR-00000001"
    assert h["relation"] == msr.HEAD
    assert h["group_key"] == "11000000001"
    assert h["controlled_providers_linked"] == 1
    assert h["included_entities_listed"] == 2
    assert all(e["provider_approval_number"] != "PR-00000001" for e in out["edges"])


def test_group_name_is_the_single_reporting_entity():
    out = layer(stmt([KOOKABURRA], ["Wattle Kids Pty Ltd"]))
    (e,) = out["edges"]
    assert e["group_name"] == "KOOKABURRA LEARNING GROUP LIMITED"
    assert ";" not in e["group_name"]
    assert e["group_abn"] == "11000000001"


def test_reporting_entity_without_included_entities_is_written_nowhere():
    out = layer(stmt([KOOKABURRA]))
    assert out["edges"] == [] and out["heads"] == [] and out["coreported"] == []
    (rel,) = out["relations"]
    assert rel["relation"] == msr.SELF_ONLY


def test_joint_statement_rows_never_reach_edges_or_heads():
    joint = stmt(
        [KOOKABURRA, {"name": "WATTLE KIDS PTY LTD", "abn": "11000000002"}],
        ["Banksia Early Years Pty Ltd"],
        type_="Joint",
        page=101,
    )
    out = layer(joint)
    assert out["edges"] == [] and out["heads"] == []
    rows = sorted(out["coreported"], key=lambda r: r["provider_approval_number"])
    assert [r["provider_approval_number"] for r in rows] == [
        "PR-00000001",
        "PR-00000002",
        "PR-00000003",
    ]
    assert {r["relation"] for r in rows} == {msr.JOINT}
    assert {r["caveat"] for r in rows} == {
        "joint statement: co-reporting, not evidence of ownership"
    }
    assert {r["statement_key"] for r in rows} == {"MSR-101"}
    assert rows[2]["msr_role"] == "included_entity"
    for col in msr.COREPORTED_COLUMNS:
        assert col in rows[0]


def test_single_group_joint_statement_is_not_promoted_but_listed_for_confirmation():
    out = layer(stmt([PARENT], ["Wattle Kids Pty Ltd"], type_="Joint", page=150))
    assert out["edges"] == []
    (r,) = out["coreported"]
    assert r["relation"] == msr.JOINT
    (cand,) = msr.joint_manual_candidates(out["coreported"])
    assert cand["statement_url"].endswith("/statements/150/")
    assert cand["reporting_entity_count"] == 1
    assert cand["included_providers"] == ["PR-00000002"]


def test_duplicate_statements_across_years_collapse_to_one_edge():
    out = layer(
        stmt([PARENT], ["Wattle Kids Pty Ltd"], year=2022, page=201),
        stmt([PARENT], [("Wattle Kids Pty Ltd", "11000000002")], year=2024, page=203),
        stmt([PARENT], ["Wattle Kids Pty Ltd"], year=2023, page=202),
    )
    (e,) = out["edges"]
    assert e["provider_approval_number"] == "PR-00000002"
    assert e["group_key"] == "99000000009"
    assert e["statement_count"] == 3
    assert e["statement_url"].endswith("/statements/203/")
    assert e["reporting_period"] == "2024-01-01 to 2024-12-31"
    assert e["statement_ids"] == "2023-201; 2024-202; 2025-203"
    assert e["statement_urls"].count("https://modernslaveryregister.gov.au/statements/") == 3
    assert e["match_methods"] == (
        "included_entity_abn_equals_provider_abn; included_name_equals_acecqa_and_abr_name"
    )


def test_group_key_borrowed_only_when_abr_confirms_the_name():
    statements = (
        stmt([PARENT], ["Wattle Kids Pty Ltd"], year=2023, page=301),
        stmt(
            [{"name": "Parent Limited", "abn": None}], ["Wattle Kids Pty Ltd"], year=2024, page=302
        ),
    )
    (e,) = layer(*statements, abr_types=abr("PRV"))["edges"]
    assert e["group_key"] == "99000000009"
    assert e["group_key_source"] == "abn_of_same_name_on_another_statement_abr_confirmed"
    assert e["statement_count"] == 2
    unconfirmed = layer(*statements)["edges"]
    assert {x["group_key"] for x in unconfirmed} == {"99000000009", "MSR-302"}


def test_group_key_without_any_abn_uses_statement_page_not_name():
    # Codex round 1, finding 1: no key or column is derived from an unmasked name.
    out = layer(stmt([{"name": "Parent Limited", "abn": None}], ["Wattle Kids Pty Ltd"], page=777))
    (e,) = out["edges"]
    assert e["group_key"] == "MSR-777"
    assert e["group_key_source"] == "statement_page_no_abn"
    assert "PARENT" not in e["group_key"]


def test_person_like_reporting_entity_never_reaches_any_output():
    # Codex round 1, finding 1: a reporting entity that may be a person leaves no trace,
    # and its name is never used to borrow an ABN from another statement.
    out = layer(
        stmt([{"name": "Jane Example", "abn": None}], ["Wattle Kids Pty Ltd"], page=778),
        stmt([{"name": "Jane Example", "abn": "77000000007"}], ["Wattle Kids Pty Ltd"], page=779),
    )
    assert "Jane Example" not in repr(out) and "JANE EXAMPLE" not in repr(out)
    keys = {e["group_key"]: e["group_key_source"] for e in out["edges"]}
    assert keys == {"MSR-778": "statement_page_no_abn", "77000000007": "abn_on_statement"}


def test_other_statement_types_are_unclassified():
    rel = {
        "statement_type": "Voluntary",
        "reporting_entity_count": 1,
        "msr_role": "included_entity",
        "included_entities_listed": 1,
    }
    assert msr.classify_relation(rel) == msr.UNCLASSIFIED


def test_every_edge_has_required_columns_and_is_controlled_entity_of():
    out = layer(stmt([KOOKABURRA], ["Wattle Kids Pty Ltd"]))
    for e in out["edges"]:
        for col in msr.EDGE_COLUMNS:
            assert col in e
        assert e["edge_type"] == e["relation"] == msr.CONTROLLED
        assert e["statement_url"].startswith("https://modernslaveryregister.gov.au/statements/")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def test_summary_counts_each_class_separately():
    out = layer(
        stmt([KOOKABURRA], ["Wattle Kids Pty Ltd", "Gumnut Care Pty Ltd"], year=2024, page=401),
        stmt([KOOKABURRA], ["Wattle Kids Pty Ltd"], year=2023, page=400),
        stmt([PARENT], ["Banksia Early Years Pty Ltd"], type_="Joint", page=402),
    )
    services = [
        {"provider_approval_number": "PR-00000001"},
        {"provider_approval_number": "PR-00000001"},
        {"provider_approval_number": "PR-00000002"},
        {"provider_approval_number": "PR-00000003"},
        {"provider_approval_number": "PR-00000009"},
    ]
    s = msr.summarise(out, ABN_ROWS, services, candidates_count=3)
    c = s["counts"]
    ce = c["controlled_entity_of"]
    assert ce["edges"] == 1
    assert ce["distinct_providers"] == 1
    assert ce["groups"] == 1
    assert ce["priority_providers_gained_edge"] == 1
    assert ce["services_of_those_providers"] == 1
    assert c["group_parent_self_not_ownership_edges"]["rows"] == 1
    assert c["group_parent_self_not_ownership_edges"]["services_of_those_providers"] == 2
    joint = c["co_reported_joint_not_ownership"]
    assert joint["rows"] == 1 and joint["statements"] == 1
    assert joint["providers_with_only_joint_relations"] == 1
    assert c["relations_by_class"] == {
        msr.JOINT: 1,
        msr.CONTROLLED: 2,
        msr.HEAD: 2,
    }
    assert c["priority_providers_total"] == len(ABN_ROWS)
    assert c["review_queue"] == 1
    (g,) = s["groups"]
    assert g["group_name"] == "KOOKABURRA LEARNING GROUP LIMITED"
    assert g["group_name_status"] == "shown_abr_organisation_type"
    assert g["head_provider"] == "PR-00000001"
    assert len(s["joint_statements_for_manual_confirmation"]) == 1


def test_only_joint_label_excludes_self_only_providers():
    # Codex round 2, finding 4
    out = layer(
        stmt([KOOKABURRA], year=2024, page=410),
        stmt([PARENT, KOOKABURRA], type_="Joint", page=411),
    )
    s = msr.summarise(out, ABN_ROWS, [], candidates_count=2)
    joint = s["counts"]["co_reported_joint_not_ownership"]
    assert joint["distinct_providers"] == 1
    assert joint["providers_with_only_joint_relations"] == 0


# ---------------------------------------------------------------------------
# Normalisation of numbered entities
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "a,b",
    [
        ("Story House Early Learning No 1 Pty Ltd", "Story House Early Learning No 21 Pty Ltd"),
        (
            "Ramsay Bourne Acquisitions (No. 2) Pty Limited",
            "Ramsay Bourne Acquisitions (No.1) Pty Limited",
        ),
    ],
)
def test_normalise_keeps_numbered_entities_apart(a, b):
    assert msr.normalise(a) != msr.normalise(b)
    assert msr.loose_key(a) != msr.loose_key(b)


def test_numbered_entity_never_matches_another_number():
    profiles = PROFILES + [
        {
            "provider_approval_number": "PR-00000021",
            "legal_name": "Story House Early Learning No 21 Pty Ltd",
            "entity_form": "company",
            "name_withheld": "false",
        },
    ]
    abn_rows = ABN_ROWS + [
        {
            "provider_approval_number": "PR-00000021",
            "legal_name": "Story House Early Learning No 21 Pty Ltd",
            "abn": "21000000021",
            "abr_entity_name": "STORY HOUSE EARLY LEARNING NO 21 PTY LTD",
            "entity_type_code": "PRV",
            "match_kind": "accepted_unique",
        },
    ]
    out = msr.build_layer(
        [stmt([PARENT], ["Story House Early Learning No 1 Pty Ltd"])], profiles, abn_rows
    )
    assert out["edges"] == [] and out["review"] == []


# ---------------------------------------------------------------------------
# Main: exit codes, outputs on disk, services, refresh
# ---------------------------------------------------------------------------

SENTINEL = "SENTINEL FULL STATEMENT TEXT THAT MUST NEVER BE COPIED"


def _write_csv(path, rows, fields):
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A tmp raw dir with one CSV snapshot and two statement pages, and tmp processed inputs."""
    from scrapers import common

    raw = tmp_path / "raw"
    rows = [
        csv_row(
            "2024-501", "501", "KOOKABURRA LEARNING GROUP LIMITED (11 000 000 001)", "11000000001"
        ),
        csv_row(
            "2024-502",
            "502",
            "PARENT LTD (99 000 000 009), BANKSIA EARLY YEARS PTY LTD (11 000 000 003)",
            "99000000009, 11000000003",
            type_="Joint",
        ),
    ]
    (raw / "msr" / "all-statements").mkdir(parents=True)
    (raw / "msr" / "all-statements" / "2026-01-01T0000Z.csv").write_text(
        csv_text(rows), encoding="utf-8"
    )
    pages = {
        "501": statement_page(
            [("KOOKABURRA LEARNING GROUP LIMITED", "11000000001")],
            ["Wattle Kids Pty Ltd", "Gumnut Care Pty Ltd", "Grevillea Kindergarten"],
        ),
        "502": statement_page(
            [("PARENT LTD", "99000000009"), ("BANKSIA EARLY YEARS PTY LTD", "11000000003")],
            ["Lilly Pilly Childcare Pty Ltd"],
        ),
    }
    for pid, html in pages.items():
        d = raw / "msr" / "statements" / pid
        d.mkdir(parents=True)
        html = html.replace("</body>", f"<p>{SENTINEL}</p></body>")
        (d / "2026-01-01T0000Z.html").write_text(html, encoding="utf-8")
    proc = tmp_path / "processed"
    proc.mkdir()
    _write_csv(
        proc / "provider-profile.csv",
        PROFILES,
        ["provider_approval_number", "legal_name", "entity_form", "name_withheld"],
    )
    _write_csv(
        proc / "provider-abn.csv",
        ABN_ROWS,
        [
            "provider_approval_number",
            "legal_name",
            "abn",
            "abr_entity_name",
            "entity_type_code",
            "match_kind",
        ],
    )
    _write_csv(
        proc / "acecqa-services-latest.csv",
        [{"provider_approval_number": "PR-00000002"}],
        ["provider_approval_number"],
    )
    written: dict = {}

    def fake_write_processed(name, rows, fieldnames, **kwargs):
        written[name] = {
            "rows": rows,
            "fieldnames": fieldnames,
            "notes": kwargs.get("notes"),
            "raw_inputs": kwargs.get("raw_inputs"),
        }

    def fake_write_snapshot(source, fetched, ext, **kwargs):
        return common.write_snapshot(source, fetched, ext, base_dir=raw, **kwargs)

    monkeypatch.setattr(
        msr, "list_snapshots", lambda source: common.list_snapshots(source, base_dir=raw)
    )
    monkeypatch.setattr(msr, "write_snapshot", fake_write_snapshot)
    monkeypatch.setattr(common, "PROJECT_ROOT", tmp_path)  # write_snapshot logs a relative path
    monkeypatch.setattr(msr, "write_processed", fake_write_processed)
    monkeypatch.setattr(msr, "PROFILE_CSV", proc / "provider-profile.csv")
    monkeypatch.setattr(msr, "PROVIDER_ABN_CSV", proc / "provider-abn.csv")
    monkeypatch.setattr(msr, "SERVICES_CSV", proc / "acecqa-services-latest.csv")
    _write_csv(
        proc / "abn-details.csv",
        [
            {
                "abn": "88000000008",
                "lookup_status": "excluded_individual",
                "entity_type_code": "IND",
                "entity_name": "",
            }
        ],
        ["abn", "lookup_status", "entity_type_code", "entity_name"],
    )
    monkeypatch.setattr(msr, "ABN_DETAILS_CSV", proc / "abn-details.csv")
    monkeypatch.setattr(msr, "SUMMARY_JSON", proc / "summary.json")
    return {"raw": raw, "proc": proc, "written": written}


def _summary(env):
    return json.loads((env["proc"] / "summary.json").read_text(encoding="utf-8"))


def test_main_exit_0_when_complete(env):
    assert msr.main(["--no-fetch"]) == 0
    assert set(env["written"]) == {
        msr.EDGES_NAME,
        msr.HEADS_NAME,
        msr.COREPORTED_NAME,
        msr.REVIEW_NAME,
    }
    assert (env["proc"] / "summary.json").exists()


def test_main_edges_file_holds_only_controlled_entities(env):
    # A joint relation, a fuzzy match and an ambiguous match can never reach the edges file.
    assert msr.main(["--no-fetch"]) == 0
    edges = env["written"][msr.EDGES_NAME]["rows"]
    assert [e["provider_approval_number"] for e in edges] == ["PR-00000002"]
    assert {e["relation"] for e in edges} == {msr.CONTROLLED}
    joint = env["written"][msr.COREPORTED_NAME]["rows"]
    assert {r["provider_approval_number"] for r in joint} == {"PR-00000003"}
    reasons = {r["reason"] for r in env["written"][msr.REVIEW_NAME]["rows"]}
    assert {"ambiguous_matches_several_providers", "fuzzy_corporate_suffix_differs"} <= reasons
    for pr in ("PR-00000003", "PR-00000004", "PR-00000005", "PR-00000009"):
        assert pr not in repr(edges)


def test_main_outputs_contain_no_raw_statement_text(env):
    assert msr.main(["--no-fetch"]) == 0
    blob = repr(env["written"]) + (env["proc"] / "summary.json").read_text(encoding="utf-8")
    assert SENTINEL not in blob
    assert "<div" not in blob and "statement-entity" not in blob


def test_main_exit_2_and_no_writes_when_a_page_is_missing(env):
    for f in (env["raw"] / "msr" / "statements" / "502").iterdir():
        f.unlink()
    assert msr.main(["--no-fetch"]) == 2
    assert env["written"] == {}
    assert not (env["proc"] / "summary.json").exists()


def test_main_exit_2_when_a_page_is_unparseable(env):
    (env["raw"] / "msr" / "statements" / "502" / "2026-01-01T0000Z.html").write_text(
        "<html><body>maintenance page</body></html>", encoding="utf-8"
    )
    assert msr.main(["--no-fetch"]) == 2
    assert env["written"] == {}
    assert not (env["proc"] / "summary.json").exists()


def test_main_exit_1_when_no_page_is_usable(env):
    for pid in ("501", "502"):
        for f in (env["raw"] / "msr" / "statements" / pid).iterdir():
            f.unlink()
    assert msr.main(["--no-fetch"]) == 1
    assert env["written"] == {}


def test_main_exit_1_when_no_csv_snapshot(env):
    for f in (env["raw"] / "msr" / "all-statements").iterdir():
        f.unlink()
    assert msr.main(["--no-fetch"]) == 1
    assert env["written"] == {}


def test_main_missing_services_is_null_not_zero(env):
    (env["proc"] / "acecqa-services-latest.csv").unlink()
    assert msr.main(["--no-fetch"]) == 0
    s = _summary(env)
    c = s["counts"]
    assert c["services_total"] is None
    assert c["controlled_entity_of"]["services_of_those_providers"] is None
    assert c["group_parent_self_not_ownership_edges"]["services_of_those_providers"] is None
    assert "acecqa-services-latest.csv" in c["services_note"]
    assert all(g["services_of_controlled_providers"] is None for g in s["groups"])


def test_main_services_present_are_counted(env):
    assert msr.main(["--no-fetch"]) == 0
    c = _summary(env)["counts"]
    assert c["services_total"] == 1
    assert c["controlled_entity_of"]["services_of_those_providers"] == 1
    assert c["services_note"] is None


def _fake_fetch(calls):
    from scrapers.common import Fetched

    def fake(url, **kwargs):
        calls.append(url)
        page = statement_page(
            [("KOOKABURRA LEARNING GROUP LIMITED", "11000000001")], ["Wattle Kids Pty Ltd"]
        )
        return Fetched(
            url=url,
            final_url=url,
            status=200,
            content=page.encode("utf-8"),
            content_type="text/html",
            last_modified=None,
            etag=None,
            fetched_at="2026-10-31T01:00:00+00:00",
        )

    return fake


def test_refresh_takes_a_new_snapshot_alongside_the_old(env, monkeypatch):
    calls: list = []
    monkeypatch.setattr(msr, "fetch", _fake_fetch(calls))
    monkeypatch.setattr(msr, "PAGE_DELAY_SECONDS", 0.0)
    page_dir = env["raw"] / "msr" / "statements" / "501"
    (old,) = list(page_dir.iterdir())
    old_bytes = old.read_bytes()
    s = {"page_id": "501", "statement_url": "https://modernslaveryregister.gov.au/statements/501/"}
    path, _ = msr.acquire_page(s, False, [0.0], refresh=True)
    snaps = sorted(p for p in page_dir.iterdir() if not p.name.endswith(".meta.json"))
    assert calls == [s["statement_url"]]
    assert len(snaps) == 2 and old in snaps
    assert old.read_bytes() == old_bytes  # never overwritten
    assert path != old and path in snaps


def test_without_refresh_an_existing_snapshot_is_reused(env, monkeypatch):
    calls: list = []
    monkeypatch.setattr(msr, "fetch", _fake_fetch(calls))
    s = {"page_id": "501", "statement_url": "https://modernslaveryregister.gov.au/statements/501/"}
    path, _ = msr.acquire_page(s, False, [0.0])
    assert calls == []
    assert path.name == "2026-01-01T0000Z.html"


def test_committed_msr_outputs_hold_no_raw_html():
    from scrapers.common import PROCESSED_DIR

    names = [msr.EDGES_NAME, msr.HEADS_NAME, msr.COREPORTED_NAME, msr.REVIEW_NAME]
    paths = [PROCESSED_DIR / f"{n}.csv" for n in names] + [msr.SUMMARY_JSON]
    present = [p for p in paths if p.exists()]
    if not present:
        pytest.skip("no MSR outputs built")
    for p in present:
        text = p.read_text(encoding="utf-8")
        assert "<div" not in text and "<p>" not in text and "statement-entity" not in text


# ---------------------------------------------------------------------------
# Codex round 2: name policy end to end, incomplete pages, failed refresh
# ---------------------------------------------------------------------------

PERSON_BUSINESS = "Jane Example Care Services Pty Ltd"


def add_statement(
    env, idx, page_id, reporting, abns, page_html, *, included_text="", type_="Single"
):
    """Append one CSV row to the env snapshot and write its statement page."""
    snap = env["raw"] / "msr" / "all-statements" / "2026-01-01T0000Z.csv"
    rows = list(csv.DictReader(io.StringIO(snap.read_text(encoding="utf-8"))))
    rows.append(csv_row(idx, page_id, reporting, abns, included=included_text, type_=type_))
    snap.write_text(csv_text(rows), encoding="utf-8")
    d = env["raw"] / "msr" / "statements" / page_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "2026-01-01T0000Z.html").write_text(page_html, encoding="utf-8")


def everything_written(env):
    summary = env["proc"] / "summary.json"
    return repr(env["written"]) + (summary.read_text(encoding="utf-8") if summary.exists() else "")


def test_person_plus_business_word_name_never_appears_in_any_output(env):
    # Codex round 2, finding 5: no ABN, and an ABN that the ABR types as an individual.
    add_statement(
        env,
        "2024-503",
        "503",
        PERSON_BUSINESS,
        "11000000002",
        statement_page([(PERSON_BUSINESS, None)], ["Wattle Kids Pty Ltd"]),
        included_text="Wattle Kids Pty Ltd",
    )
    add_statement(
        env,
        "2024-504",
        "504",
        f"{PERSON_BUSINESS} (88 000 000 008)",
        "88000000008, 11000000002",
        statement_page([(PERSON_BUSINESS, "88000000008")], ["Wattle Kids Pty Ltd"]),
        included_text="Wattle Kids Pty Ltd",
    )
    add_statement(
        env,
        "2024-505",
        "505",
        "KOOKABURRA LEARNING GROUP LIMITED (11 000 000 001)",
        "11000000001",
        statement_page([("KOOKABURRA LEARNING GROUP LIMITED", "11000000001")], [PERSON_BUSINESS]),
        included_text=PERSON_BUSINESS,
        type_="Joint",
    )
    assert msr.main(["--no-fetch"]) == 0
    blob = everything_written(env)
    assert "Jane" not in blob and "JANE" not in blob
    groups = {
        e["group_key"]: e["group_name_status"] for e in env["written"][msr.EDGES_NAME]["rows"]
    }
    assert groups["MSR-503"] == "withheld_no_abn"
    assert groups["88000000008"] == "withheld_abr_individual"


def test_written_name_columns_follow_the_policy(env):
    assert msr.main(["--no-fetch"]) == 0
    w = env["written"]
    assert w[msr.REVIEW_NAME]["fieldnames"] == msr.REVIEW_COLUMNS
    assert w[msr.COREPORTED_NAME]["fieldnames"] == msr.COREPORTED_COLUMNS
    for row in w[msr.REVIEW_NAME]["rows"] + w[msr.COREPORTED_NAME]["rows"]:
        written = {k: row.get(k) for k in w[msr.REVIEW_NAME]["fieldnames"] if k in row}
        assert "Gumnut" not in repr(written) and "Grevillea" not in repr(written)
    s = _summary(env)
    for c in s["candidate_statements"]:
        assert not [k for k in c if "name" in k]
    for c in s["joint_statements_for_manual_confirmation"]:
        assert not [k for k in c if "name" in k]
    for g in s["groups"]:
        assert {k for k in g if "name" in k} == {"group_name", "group_name_status"}
    assert "PARENT LTD" not in everything_written(env)  # MSR-side reporting name, no ABR type


def test_parse_rejects_included_entity_without_a_name_link():
    page = statement_page([("A LTD", "11000000001")], ["Wattle Kids Pty Ltd"]).replace(
        'class="statement-entity__name-link"', 'class="something-else"'
    )
    with pytest.raises(msr.PageParseError):
        msr.parse_statement_page(page)


def test_parse_rejects_included_section_without_entities():
    page = statement_page([("A LTD", "11000000001")], ["Wattle Kids Pty Ltd"])
    start = page.index('<div class="statement-entity">', page.index("statement-included-entities"))
    end = page.index("</div>\n</div>", start)
    page = page[:start] + page[end:]
    with pytest.raises(msr.PageParseError):
        msr.parse_statement_page(page)


def test_parse_accepts_a_statement_with_no_included_section():
    parsed = msr.parse_statement_page(statement_page([("A LTD", "11000000001")]))
    assert parsed["included"] == []


def test_main_exit_2_on_malformed_included_markup(env):
    # Codex round 2, finding 2
    page = env["raw"] / "msr" / "statements" / "501" / "2026-01-01T0000Z.html"
    page.write_text(
        page.read_text(encoding="utf-8").replace(
            'class="statement-entity__name-link"', 'class="renamed-link"'
        ),
        encoding="utf-8",
    )
    assert msr.main(["--no-fetch"]) == 2
    assert env["written"] == {}
    assert not (env["proc"] / "summary.json").exists()


def test_main_exit_2_when_csv_lists_included_entities_but_page_has_none(env):
    # Codex round 2, finding 2: CSV IncludedEntities non-empty, parsed list empty.
    add_statement(
        env,
        "2024-506",
        "506",
        "KOOKABURRA LEARNING GROUP LIMITED (11 000 000 001)",
        "11000000001",
        statement_page([("KOOKABURRA LEARNING GROUP LIMITED", "11000000001")]),
        included_text="Wattle Kids Pty Ltd",
    )
    assert msr.main(["--no-fetch"]) == 2
    assert env["written"] == {}


def test_csv_without_included_entities_and_page_without_section_is_complete(env):
    add_statement(
        env,
        "2024-507",
        "507",
        "KOOKABURRA LEARNING GROUP LIMITED (11 000 000 001)",
        "11000000001",
        statement_page([("KOOKABURRA LEARNING GROUP LIMITED", "11000000001")]),
    )
    assert msr.main(["--no-fetch"]) == 0


def test_failed_refresh_exits_2_and_writes_nothing(env, monkeypatch):
    # Codex round 2, finding 3: never fall back to an older snapshot during a refresh.
    snap = env["raw"] / "msr" / "all-statements" / "2026-01-01T0000Z.csv"
    monkeypatch.setattr(msr, "acquire_csv", lambda no_fetch: (snap, {}))
    monkeypatch.setattr(msr, "PAGE_DELAY_SECONDS", 0.0)

    def failing_fetch(url, **kwargs):
        raise RuntimeError("simulated network failure")

    monkeypatch.setattr(msr, "fetch", failing_fetch)
    assert msr.main(["--refresh"]) == 2
    assert env["written"] == {}
    assert not (env["proc"] / "summary.json").exists()


def test_failed_refresh_of_one_page_returns_no_snapshot(env, monkeypatch):
    def failing_fetch(url, **kwargs):
        raise RuntimeError("simulated network failure")

    monkeypatch.setattr(msr, "fetch", failing_fetch)
    monkeypatch.setattr(msr, "PAGE_DELAY_SECONDS", 0.0)
    s = {"page_id": "501", "statement_url": "https://modernslaveryregister.gov.au/statements/501/"}
    assert msr.acquire_page(s, False, [0.0], refresh=True) == (None, {})
    # a non-refresh run still reuses the snapshot already held
    path, _ = msr.acquire_page(s, False, [0.0])
    assert path.name == "2026-01-01T0000Z.html"


# ---------------------------------------------------------------------------
# Codex round 3
# ---------------------------------------------------------------------------


def _append_details(env, rows):
    path = env["proc"] / "abn-details.csv"
    existing = list(csv.DictReader(io.StringIO(path.read_text(encoding="utf-8"))))
    _write_csv(
        path,
        existing + rows,
        ["abn", "lookup_status", "entity_type_code", "entity_name"],
    )


def test_provider_marked_individual_in_abn_details_never_appears(env):
    # Finding 1: the profile says company and provider-abn.csv says PRV, but the ABR details say
    # individual. Fail closed: the provider is excluded from every output.
    _append_details(
        env,
        [
            {
                "abn": "11000000002",
                "lookup_status": "ok",
                "entity_type_code": "IND",
                "entity_name": "",
            }
        ],
    )
    assert msr.main(["--no-fetch"]) == 0
    blob = everything_written(env)
    assert "PR-00000002" not in blob and "Wattle" not in blob
    excl = _summary(env)["counts"]["provider_exclusions"]
    assert excl["abr_individual"] >= 1
    assert excl["individual_status_conflicts"] >= 1


def test_provider_with_conflicting_abr_types_is_excluded_and_counted(env):
    _append_details(
        env,
        [
            {
                "abn": "11000000002",
                "lookup_status": "ok",
                "entity_type_code": "PUB",
                "entity_name": "X",
            }
        ],
    )
    assert msr.main(["--no-fetch"]) == 0
    assert "PR-00000002" not in everything_written(env)
    assert _summary(env)["counts"]["provider_exclusions"]["abr_type_conflicts"] == 1


def test_provider_marked_individual_by_abr_lookup_kind_is_excluded():
    abn_rows = [dict(r) for r in ABN_ROWS] + [
        {
            "provider_approval_number": "PR-00000009",
            "legal_name": "",
            "abn": "",
            "abr_entity_name": "",
            "entity_type_code": "",
            "match_kind": "excluded_individual_abr",
        }
    ]
    out = msr.build_layer([stmt([PARENT], ["Grevillea Kindergarten"])], PROFILES, abn_rows)
    assert out["review"] == [] and "PR-00000009" not in repr(out)
    assert out["stats"]["providers_excluded_abr_individual"] >= 1


def test_profile_individual_with_abr_company_is_excluded_and_counted():
    profiles = [dict(p) for p in PROFILES]
    for p in profiles:
        if p["provider_approval_number"] == "PR-00000002":
            p["entity_form"] = "likely_individual"
    out = msr.build_layer([stmt([PARENT], [("X", "11000000002")])], profiles, ABN_ROWS)
    assert out["edges"] == [] and "PR-00000002" not in repr(out)
    assert out["stats"]["individual_status_conflicts"] == 1


def test_parse_rejects_mixed_recognised_and_unrecognised_siblings():
    # Finding 2
    page = statement_page([("A LTD", "11000000001")], ["Wattle Kids Pty Ltd"])
    page = page.replace(
        '<div id="statement-included-entities" class="accordion__content collapse hide">',
        '<div id="statement-included-entities" class="accordion__content collapse hide">'
        '<div class="statement-entity-v2"><span>Banksia Early Years Pty Ltd</span></div>',
    )
    with pytest.raises(msr.PageParseError):
        msr.parse_statement_page(page)


def test_parse_rejects_stray_text_in_an_entity_section():
    page = statement_page([("A LTD", "11000000001")], ["Wattle Kids Pty Ltd"])
    page = page.replace(
        '<div id="statement-included-entities" class="accordion__content collapse hide">',
        '<div id="statement-included-entities" class="accordion__content collapse hide">'
        "Banksia Early Years Pty Ltd",
    )
    with pytest.raises(msr.PageParseError):
        msr.parse_statement_page(page)


def test_main_exit_2_on_mixed_included_markup(env):
    page = env["raw"] / "msr" / "statements" / "501" / "2026-01-01T0000Z.html"
    html = page.read_text(encoding="utf-8").replace(
        '<div id="statement-included-entities" class="accordion__content collapse hide">',
        '<div id="statement-included-entities" class="accordion__content collapse hide">'
        '<section class="new-entity">Banksia Early Years Pty Ltd</section>',
    )
    page.write_text(html, encoding="utf-8")
    assert msr.main(["--no-fetch"]) == 2
    assert env["written"] == {}


@pytest.mark.parametrize(
    "text,expected",
    [
        ("", 0),
        ("Wattle Kids Pty Ltd, Banksia Early Years Pty Ltd", 2),
        ("Bilby Education Holdings, LLC, Bilby Education, Inc.", 2),  # comma before the suffix
        ("NUMBAT COLLEGE, QUOKKA (11 111 111 111), Wattle Kids Pty Ltd", 2),
        ("Proversity, Wattle Kids Pty Ltd", 1),  # no suffix: not counted, a lower bound
    ],
)
def test_csv_included_lower_bound(text, expected):
    assert msr.csv_included_lower_bound(text) == expected


def test_main_exit_2_when_page_yields_fewer_entities_than_the_csv_lists(env):
    add_statement(
        env,
        "2024-508",
        "508",
        "KOOKABURRA LEARNING GROUP LIMITED (11 000 000 001)",
        "11000000001",
        statement_page(
            [("KOOKABURRA LEARNING GROUP LIMITED", "11000000001")], ["Wattle Kids Pty Ltd"]
        ),
        included_text="Wattle Kids Pty Ltd, Banksia Early Years Pty Ltd, Lilly Pilly Childcare Pty Ltd",
    )
    assert msr.main(["--no-fetch"]) == 2
    assert env["written"] == {}


def test_main_complete_when_page_yields_at_least_the_csv_count(env):
    add_statement(
        env,
        "2024-509",
        "509",
        "KOOKABURRA LEARNING GROUP LIMITED (11 000 000 001)",
        "11000000001",
        statement_page(
            [("KOOKABURRA LEARNING GROUP LIMITED", "11000000001")],
            ["Wattle Kids Pty Ltd", "Wattle Kids Pty Ltd"],
        ),
        included_text="Wattle Kids Pty Ltd, Wattle Kids Pty Ltd",
    )
    assert msr.main(["--no-fetch"]) == 0


def test_candidate_row_without_page_id_is_kept_for_the_completeness_check():
    # Finding 3
    rows = [csv_row("2024-9", "not-a-number", "KOOKABURRA LEARNING GROUP LIMITED", "11000000001")]
    (c,) = msr.select_candidates(msr.parse_statements_csv(csv_text(rows)), {"11000000001"})
    assert c["page_id"] is None and c["candidate_reason"] == "abn_match"


def test_main_exit_2_when_a_candidate_row_has_no_page_id(env):
    snap = env["raw"] / "msr" / "all-statements" / "2026-01-01T0000Z.csv"
    rows = list(csv.DictReader(io.StringIO(snap.read_text(encoding="utf-8"))))
    rows.append(
        csv_row(
            "2024-510", "x510", "KOOKABURRA LEARNING GROUP LIMITED (11 000 000 001)", "11000000001"
        )
    )
    snap.write_text(csv_text(rows), encoding="utf-8")
    assert msr.main(["--no-fetch"]) == 2
    assert env["written"] == {}


@pytest.mark.parametrize(
    "code,name,status",
    [
        ("DTT", "The Trustee for the Example Family Trust", "withheld_abr_type_not_allowed"),
        ("PRV", "The Trustee for the Example Family Trust", "withheld_name_may_embed_person"),
        ("PRV", "QUOLL HOLDINGS PTY LTD ATF QUOLL UNIT TRUST", "withheld_name_may_embed_person"),
        ("FPT", "PARENT AND PARTNERS", "withheld_abr_type_not_allowed"),
        ("UIE", "PARENT CLUB", "withheld_abr_type_not_allowed"),
    ],
)
def test_group_name_withheld_for_trusts_partnerships_and_trust_wording(code, name, status):
    # Finding 4 (owner rule 2, fail closed)
    (e,) = layer(stmt([PARENT], ["Wattle Kids Pty Ltd"]), abr_types=abr(code, name))["edges"]
    assert not e["group_name"]
    assert e["group_name_status"] == status
    assert "Example" not in repr(e) and "QUOLL" not in repr(e) and "PARTNERS" not in repr(e)


@pytest.mark.parametrize("code", ["PRV", "PUB", "COP", "OIE", "LGE", "LGA", "SGE", "TGE"])
def test_group_name_shown_for_allowed_organisation_types(code):
    (e,) = layer(stmt([PARENT], ["Wattle Kids Pty Ltd"]), abr_types=abr(code))["edges"]
    assert e["group_name"] == "PARENT LTD"


def test_provenance_lists_abr_details_and_services_inputs(env):
    # Finding 5
    assert msr.main(["--no-fetch"]) == 0
    for name in (msr.EDGES_NAME, msr.HEADS_NAME, msr.COREPORTED_NAME, msr.REVIEW_NAME):
        inputs = {p.name for p in env["written"][name]["raw_inputs"]}
        assert {"abn-details.csv", "acecqa-services-latest.csv", "provider-abn.csv"} <= inputs
