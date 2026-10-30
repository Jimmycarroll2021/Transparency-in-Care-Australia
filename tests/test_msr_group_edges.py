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
# Edges and review queue
# ---------------------------------------------------------------------------


def build(statements_and_pages):
    stmts = []
    for i, (reporting, included, extra) in enumerate(statements_and_pages, start=1):
        s = {
            "statement_id": f"2024-{i}",
            "page_id": str(100 + i),
            "statement_url": f"https://modernslaveryregister.gov.au/statements/{100 + i}/",
            "reporting_period": "2024-01-01 to 2024-12-31",
            "type": extra.get("type", "Single"),
            "captured_at": "2026-10-31T00:00:00+00:00",
            "page_sha256": "abc",
            "parsed": {
                "reporting": reporting,
                "included": [
                    {"name": i[0], "abn": i[1]}
                    if isinstance(i, tuple)
                    else {"name": i, "abn": None}
                    for i in included
                ],
            },
        }
        stmts.append(s)
    return msr.build_edges(stmts, PROFILES, ABN_ROWS)


def test_reporting_entity_edge_by_abn():
    edges, review, stats = build(
        [([{"name": "KOOKABURRA LEARNING GROUP LIMITED", "abn": "11000000001"}], [], {})]
    )
    (e,) = edges
    assert e["provider_approval_number"] == "PR-00000001"
    assert e["edge_type"] == "reporting_entity"
    assert e["match_method"] == "reporting_entity_abn_equals_provider_abn"
    assert e["group_key"] == "11000000001"
    assert e["group_name"] == "KOOKABURRA LEARNING GROUP LIMITED"
    assert e["statement_url"].endswith("/statements/101/")
    assert review == []


def test_included_entity_edge_needs_acecqa_and_abr_agreement():
    edges, review, _ = build(
        [
            (
                [{"name": "KOOKABURRA LEARNING GROUP LIMITED", "abn": "11000000001"}],
                ["Wattle Kids Pty. Ltd.", "Banksia Early Years Proprietary Limited"],
                {},
            )
        ]
    )
    inc = sorted(
        (e for e in edges if e["edge_type"] == "included_entity"),
        key=lambda e: e["provider_approval_number"],
    )
    assert [e["provider_approval_number"] for e in inc] == ["PR-00000002", "PR-00000003"]
    assert all(e["group_key"] == "11000000001" for e in inc)
    assert all(e["match_method"] == "included_name_equals_acecqa_and_abr_name" for e in inc)


def test_abr_name_disagreement_goes_to_review():
    edges, review, _ = build(
        [([{"name": "PARENT LTD", "abn": "99000000009"}], ["Lilly Pilly Childcare Pty Ltd"], {})]
    )
    assert edges == []
    (r,) = review
    assert r["reason"] == "abr_name_disagrees"
    assert r["candidate_provider_approval_numbers"] == "PR-00000006"


def test_ambiguous_name_goes_to_review_never_edges():
    edges, review, _ = build(
        [([{"name": "PARENT LTD", "abn": "99000000009"}], ["Gumnut Care Pty Ltd"], {})]
    )
    assert edges == []
    (r,) = review
    assert r["reason"] == "ambiguous_matches_several_providers"
    assert r["candidate_provider_approval_numbers"] == "PR-00000004; PR-00000005"


def test_unique_name_without_provider_abn_goes_to_review():
    edges, review, _ = build(
        [([{"name": "PARENT LTD", "abn": "99000000009"}], ["Waratah Centres Pty Ltd"], {})]
    )
    assert edges == []
    assert review[0]["reason"] == "name_unique_provider_without_abn"


def test_fuzzy_suffix_match_goes_to_review():
    edges, review, _ = build(
        [([{"name": "PARENT LTD", "abn": "99000000009"}], ["Grevillea Kindergarten"], {})]
    )
    assert edges == []
    (r,) = review
    assert r["reason"] == "fuzzy_corporate_suffix_differs"
    assert r["candidate_provider_approval_numbers"] == "PR-00000009"


def test_individual_provider_never_appears():
    edges, review, stats = build(
        [([{"name": "PARENT LTD", "abn": "99000000009"}], ["Sample Person"], {})]
    )
    assert edges == [] and review == []
    assert stats["matches_to_excluded_providers"] == 1
    blob = repr(edges) + repr(review)
    assert "Sample Person" not in blob and "PR-00000008" not in blob


def test_review_withholds_msr_names_that_may_be_individuals():
    profiles = PROFILES + [
        {
            "provider_approval_number": "PR-00000010",
            "legal_name": "Jane Example",
            "entity_form": "company",
            "name_withheld": "false",
        },
    ]
    stmts = [
        {
            "statement_id": "2024-1",
            "page_id": "101",
            "statement_url": "https://modernslaveryregister.gov.au/statements/101/",
            "reporting_period": "p",
            "type": "Single",
            "captured_at": "t",
            "page_sha256": "s",
            "parsed": {
                "reporting": [{"name": "PARENT LTD", "abn": "99000000009"}],
                "included": [{"name": "Jane Example", "abn": None}],
            },
        }
    ]
    _, review, _ = msr.build_edges(stmts, profiles, ABN_ROWS)
    (r,) = review
    assert "Jane Example" not in repr(r)
    assert r["msr_entity_name"] == msr.WITHHELD


def test_included_entity_edge_by_abn():
    edges, review, _ = build(
        [
            (
                [{"name": "PARENT LTD", "abn": "99000000009"}],
                [("Renamed Wattle Co", "11000000002")],
                {},
            )
        ]
    )
    (e,) = edges
    assert e["provider_approval_number"] == "PR-00000002"
    assert e["edge_type"] == "included_entity"
    assert e["match_method"] == "included_entity_abn_equals_provider_abn"
    assert e["group_key"] == "99000000009"
    assert review == []


def test_included_abn_beats_included_name_in_same_statement():
    edges, _, _ = build(
        [
            (
                [{"name": "PARENT LTD", "abn": "99000000009"}],
                ["Wattle Kids Pty Ltd", ("Wattle Kids Pty Ltd", "11000000002")],
                {},
            )
        ]
    )
    (e,) = edges
    assert e["match_method"] == "included_entity_abn_equals_provider_abn"


def test_msr_abn_that_differs_from_provider_abn_goes_to_review():
    edges, review, _ = build(
        [
            (
                [{"name": "PARENT LTD", "abn": "99000000009"}],
                [("Wattle Kids Pty Ltd", "55000000005")],
                {},
            )
        ]
    )
    assert edges == []
    assert review[0]["reason"] == "msr_abn_differs_from_provider_abn"
    assert review[0]["msr_entity_abn"] == "55000000005"


def test_msr_abn_with_provider_abn_unresolved_goes_to_review():
    edges, review, _ = build(
        [([{"name": "Waratah Centres Pty Ltd", "abn": "66000000006"}], [], {})]
    )
    assert edges == []
    assert review[0]["reason"] == "name_match_provider_abn_not_resolved"


def test_unplaceable_organisation_names_are_shown_person_like_names_are_not():
    assert msr._shown_name("WOMBAT UNIVERSITY") == "WOMBAT UNIVERSITY"
    assert msr._shown_name("Jane Example") == msr.WITHHELD


def test_reporting_edge_wins_over_included_edge_in_same_statement():
    edges, _, _ = build(
        [
            (
                [{"name": "KOOKABURRA LEARNING GROUP LIMITED", "abn": "11000000001"}],
                ["Kookaburra Learning Group Limited"],
                {},
            )
        ]
    )
    (e,) = edges
    assert e["edge_type"] == "reporting_entity"


def test_joint_statement_group_key_is_statement():
    edges, _, _ = build(
        [
            (
                [
                    {"name": "KOOKABURRA LEARNING GROUP LIMITED", "abn": "11000000001"},
                    {"name": "WATTLE KIDS PTY LTD", "abn": "11000000002"},
                ],
                [],
                {"type": "Joint"},
            )
        ]
    )
    assert {e["group_key"] for e in edges} == {"MSR-101"}
    assert {e["group_name"] for e in edges} == {
        "KOOKABURRA LEARNING GROUP LIMITED; WATTLE KIDS PTY LTD"
    }
    assert len(edges) == 2


def test_reporting_entity_name_only_goes_to_review():
    edges, review, _ = build([([{"name": "Waratah Centres Pty Ltd", "abn": None}], [], {})])
    assert edges == []
    assert review[0]["reason"] == "reporting_entity_name_only"
    assert review[0]["msr_role"] == "reporting_entity"


def test_every_edge_has_statement_url_and_required_columns():
    edges, _, _ = build(
        [
            (
                [{"name": "KOOKABURRA LEARNING GROUP LIMITED", "abn": "11000000001"}],
                ["Wattle Kids Pty Ltd"],
                {},
            )
        ]
    )
    for e in edges:
        for col in msr.EDGE_COLUMNS:
            assert col in e
        assert e["statement_url"].startswith("https://modernslaveryregister.gov.au/statements/")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def test_summary_counts_priority_providers_and_services():
    edges, review, stats = build(
        [
            (
                [{"name": "KOOKABURRA LEARNING GROUP LIMITED", "abn": "11000000001"}],
                ["Wattle Kids Pty Ltd", "Gumnut Care Pty Ltd"],
                {},
            )
        ]
    )
    services = [
        {"provider_approval_number": "PR-00000001"},
        {"provider_approval_number": "PR-00000001"},
        {"provider_approval_number": "PR-00000002"},
        {"provider_approval_number": "PR-00000009"},
    ]
    s = msr.summarise(edges, review, stats, ABN_ROWS, services, candidates_count=1)
    c = s["counts"]
    assert c["edges_reporting_entity"] == 1
    assert c["edges_included_entity"] == 1
    assert c["distinct_providers_with_edge"] == 2
    assert c["priority_providers_gained_edge"] == 2
    assert c["priority_providers_total"] == len(ABN_ROWS)
    assert c["services_covered"] == 3
    assert c["services_covered_by_included_entity_providers"] == 1
    assert c["review_queue"] == 1
