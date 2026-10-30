"""Tests for scrapers/build_msr_group_edges.py. Inline synthetic fixtures, no network.

Every entity name below is invented. No real individual is named.
"""

from __future__ import annotations

import csv
import io

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


def layer(*statements, profiles=PROFILES):
    return msr.build_layer(list(statements), profiles, ABN_ROWS)


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


def test_review_withholds_msr_names_that_may_be_individuals():
    profiles = PROFILES + [
        {
            "provider_approval_number": "PR-00000010",
            "legal_name": "Jane Example",
            "entity_form": "company",
            "name_withheld": "false",
        },
    ]
    out = layer(stmt([PARENT], ["Jane Example"]), profiles=profiles)
    (r,) = out["review"]
    assert "Jane Example" not in repr(r)
    assert r["msr_entity_name"] == msr.WITHHELD


def test_unplaceable_organisation_names_are_shown_person_like_names_are_not():
    assert msr._shown_name("WOMBAT UNIVERSITY") == "WOMBAT UNIVERSITY"
    assert msr._shown_name("Jane Example") == msr.WITHHELD


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


def test_group_key_borrowed_from_same_name_on_another_statement():
    out = layer(
        stmt([PARENT], ["Wattle Kids Pty Ltd"], year=2023, page=301),
        stmt(
            [{"name": "Parent Limited", "abn": None}], ["Wattle Kids Pty Ltd"], year=2024, page=302
        ),
    )
    (e,) = out["edges"]
    assert e["group_key"] == "99000000009"
    assert e["group_key_source"] == "abn_of_same_name_on_another_statement"
    assert e["statement_count"] == 2


def test_group_key_falls_back_to_name_without_any_abn():
    out = layer(stmt([{"name": "Parent Limited", "abn": None}], ["Wattle Kids Pty Ltd"]))
    (e,) = out["edges"]
    assert e["group_key"] == "NAME:PARENT LTD"
    assert e["group_key_source"] == "name_only"


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
    assert joint["providers_only_in_joint_statements"] == 1
    assert c["relations_by_class"] == {
        msr.JOINT: 1,
        msr.CONTROLLED: 2,
        msr.HEAD: 2,
    }
    assert c["priority_providers_total"] == len(ABN_ROWS)
    assert c["review_queue"] == 1
    (g,) = s["groups"]
    assert g["group_name"] == "KOOKABURRA LEARNING GROUP LIMITED"
    assert g["head_provider"] == "PR-00000001"
    assert len(s["joint_statements_for_manual_confirmation"]) == 1
