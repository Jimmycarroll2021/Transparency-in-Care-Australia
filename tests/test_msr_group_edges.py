"""Tests for scrapers/build_msr_group_edges.py. Inline synthetic fixtures, no network.

Every entity name below is invented. No real individual is named. Synthetic ABNs are built to pass
the ABN checksum.
"""

from __future__ import annotations

import csv
import io
import json

import pytest
from scrapers import build_msr_group_edges as msr

# ---------------------------------------------------------------------------
# Synthetic ABNs and fixtures
# ---------------------------------------------------------------------------

_WEIGHTS = [10, 1, 3, 5, 7, 9, 11, 13, 15, 17, 19]


def make_abn(n: int) -> str:
    """A checksum-valid ABN ending in the nine digits of n."""
    for prefix in range(10, 100):
        cand = f"{prefix}{n:09d}"
        digits = [int(c) for c in cand]
        digits[0] -= 1
        if sum(d * w for d, w in zip(digits, _WEIGHTS, strict=True)) % 89 == 0:
            return cand
    raise AssertionError(n)


def spaced(abn: str) -> str:
    return f"{abn[:2]} {abn[2:5]} {abn[5:8]} {abn[8:]}"


KOOK_ABN = make_abn(1)
WATTLE_ABN = make_abn(2)
BANKSIA_ABN = make_abn(3)
LILLY_ABN = make_abn(6)
PARENT_ABN = make_abn(9)
OTHER_ABN = make_abn(77)
KOOK_REP_TEXT = f"KOOKABURRA LEARNING GROUP LIMITED ({spaced(KOOK_ABN)})"
BAD_ABN = WATTLE_ABN[:-1] + str((int(WATTLE_ABN[-1]) + 1) % 10)  # fails the checksum

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
    # "\n" so that a text-mode write on Windows does not leave blank records behind.
    writer = csv.DictWriter(buf, fieldnames=header, lineterminator="\n")
    writer.writeheader()
    for r in rows:
        writer.writerow({k: r.get(k, "") for k in header})
    return buf.getvalue()


def entity_div(name, abn=None, acn=None):
    """One entity block in the register's markup: name link, optional ABN or ACN, empty p."""
    ident = ""
    if abn:
        ident = f'<p>ABN: <a href="/statements/?abn={abn}" target="_blank">{spaced(abn)}</a></p>'
    elif acn:
        ident = f'<p>ACN: <a href="/statements/?acn={acn}" target="_blank">{acn}</a></p>'
    return f"""
      <div class="statement-entity">
        <div class="statement-entity__name">
          <a class="statement-entity__name-link" href="/statements/?company_name={name}&"
             target="_blank">{name} </a>
        </div>
        {ident}
        <p>
        </p>
      </div>"""


def statement_page(reporting, included=()):
    """reporting: [(name, abn)]; included: names or (name, abn) tuples."""
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
<div class="related"><p>Reporting entity:</p><p>EXAMPLE OTHER LIMITED</p></div>
</body></html>"""


def prof(pr, legal, form="company", withheld="false"):
    return {
        "provider_approval_number": pr,
        "legal_name": legal,
        "entity_form": form,
        "name_withheld": withheld,
    }


def abn_row(pr, legal, abn, code="PRV", kind="accepted_unique", abr_name=None):
    return {
        "provider_approval_number": pr,
        "legal_name": legal,
        "abn": abn,
        "abr_entity_name": abr_name if abr_name is not None else legal.upper(),
        "entity_type_code": code,
        "match_kind": kind,
    }


PROFILES = [
    prof("PR-00000001", "Kookaburra Learning Group Ltd"),
    prof("PR-00000002", "Wattle Kids Pty Ltd"),
    prof("PR-00000003", "Banksia Early Years Pty Ltd"),
    prof("PR-00000004", "Gumnut Care Pty Ltd"),
    prof("PR-00000005", "Gumnut Care Pty Ltd"),
    prof("PR-00000006", "Lilly Pilly Childcare Pty Ltd"),
    prof("PR-00000007", "Waratah Centres Pty Ltd"),
    prof("PR-00000008", "", form="likely_individual", withheld="true"),
    prof("PR-00000009", "Grevillea Kindergarten Pty Ltd"),
]
ABN_ROWS = [
    abn_row("PR-00000001", "Kookaburra Learning Group Ltd", KOOK_ABN, code="PUB"),
    abn_row("PR-00000002", "Wattle Kids Pty Ltd", WATTLE_ABN),
    abn_row("PR-00000003", "Banksia Early Years Pty Ltd", BANKSIA_ABN),
    abn_row("PR-00000006", "Lilly Pilly Childcare Pty Ltd", LILLY_ABN),
    abn_row("PR-00000008", "", "", code="", kind="excluded_individual_or_unknown"),
    abn_row("PR-00000007", "Waratah Centres Pty Ltd", "", code="", kind="no_match"),
]

KOOK = {"name": "KOOKABURRA LEARNING GROUP LIMITED", "abn": KOOK_ABN}
PARENT = {"name": "PARENT LTD", "abn": PARENT_ABN}


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


def layer(*statements, profiles=PROFILES, abn_rows=ABN_ROWS, details=()):
    return msr.build_layer(
        list(statements), profiles, abn_rows, msr.abr_types_from(abn_rows, list(details))
    )


# ---------------------------------------------------------------------------
# Download, privacy filter, CSV, candidates
# ---------------------------------------------------------------------------


def test_find_all_statements_link_picks_the_all_years_file():
    assert msr.find_all_statements_link(RESOURCES_HTML) == (
        "https://modernslaveryregister.gov.au/resources/all-statement-information_2026-10-31.csv"
    )


def test_find_all_statements_link_none_when_absent():
    assert msr.find_all_statements_link("<html><a href='/x.csv'>x</a></html>") is None


def test_privacy_filter_keeps_entity_columns_and_drops_person_columns():
    header = CSV_HEADER + ["SignatoryName", "ApproverFullName", "ContactEmail"]
    row = csv_row("2024-1", "100", "KOOKABURRA LEARNING GROUP LIMITED", KOOK_ABN)
    row.update(SignatoryName="A Person", ApproverFullName="B Person", ContactEmail="x@example.org")
    out, kept, dropped = msr.privacy_filter_csv(csv_text([row], header))
    assert dropped == ["SignatoryName", "ApproverFullName", "ContactEmail"]
    assert kept == CSV_HEADER
    assert "A Person" not in out and "B Person" not in out and "example.org" not in out


def test_column_filter_is_an_allowlist_of_the_15_known_columns():
    # Codex round 8: any column not on the allowlist is dropped, whatever its name.
    assert list(msr.ALLOWED_CSV_COLUMNS) == CSV_HEADER
    header = CSV_HEADER + ["Comments", "Notes"]
    row = csv_row("2024-1", "100", "X LTD", KOOK_ABN)
    row.update(Comments="UNKNOWN COLUMN SENTINEL", Notes="ANOTHER SENTINEL")
    out, kept, dropped = msr.privacy_filter_csv(csv_text([row], header))
    assert kept == CSV_HEADER and dropped == ["Comments", "Notes"]
    assert "SENTINEL" not in out and "Comments" not in out
    assert not hasattr(msr, "_PERSON_COLUMN")


def test_privacy_filter_is_identity_when_nothing_to_drop():
    text = csv_text([csv_row("2024-1", "100", "X LTD", KOOK_ABN)])
    out, kept, dropped = msr.privacy_filter_csv(text)
    assert (out, kept, dropped) == (text, CSV_HEADER, [])


def _raw_csv(header, rows):
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return buf.getvalue()


def _row_values(header):
    row = csv_row("2024-1", "100", "X LTD", KOOK_ABN)
    return [row.get(h, "x") for h in header]


@pytest.mark.parametrize("extra", [[], ["SignatoryName"]])
@pytest.mark.parametrize("shape", ["short", "long"])
def test_privacy_filter_rejects_rows_that_do_not_match_the_header(extra, shape):
    # Codex round 6: row length is checked before any filtering, and nothing is padded.
    header = CSV_HEADER + extra
    good = _row_values(header)
    bad = good[:-1] if shape == "short" else good + ["surplus"]
    with pytest.raises(msr.CsvSchemaError):
        msr.privacy_filter_csv(_raw_csv(header, [good, bad]))


@pytest.mark.parametrize("shape", ["short", "long"])
def test_parse_statements_rejects_a_row_of_the_wrong_length(shape):
    # A short row lacks the trailing non-required RelatedStatements field.
    good = _row_values(CSV_HEADER)
    bad = good[:-1] if shape == "short" else good + ["surplus"]
    with pytest.raises(msr.CsvSchemaError):
        msr.parse_statements_csv(_raw_csv(CSV_HEADER, [good, bad]))


@pytest.mark.parametrize("duplicate", ["ABN", " abn ", "Abn"])
def test_duplicate_header_names_are_rejected_before_filtering_and_parsing(duplicate):
    # Codex round 7: dict(zip(...)) would keep the last ABN column; a duplicate header is refused,
    # compared after stripping spaces and folding case.
    header = CSV_HEADER + [duplicate]
    values = _row_values(CSV_HEADER) + [WATTLE_ABN]
    text = _raw_csv(header, [values])
    with pytest.raises(msr.CsvSchemaError, match="duplicate"):
        msr.privacy_filter_csv(text)
    with pytest.raises(msr.CsvSchemaError, match="duplicate"):
        msr.parse_statements_csv(text)


def test_parse_statements_reads_abns_page_id_and_included_abn_count():
    included = f"WATTLE KIDS PTY LTD ({spaced(WATTLE_ABN)}), Numbat College, Suburb"
    text = csv_text(
        [csv_row("2024-7", "200", "A LTD, B PTY LTD", f"{KOOK_ABN}, {WATTLE_ABN}", included)]
    )
    (s,) = msr.parse_statements_csv(text)
    assert s["statement_id"] == "2024-7" and s["page_id"] == "200"
    assert s["abns"] == [KOOK_ABN, WATTLE_ABN]
    assert s["reporting_period"] == "2024-01-01 to 2024-12-31"
    assert s["csv_lists_included"] is True
    assert s["csv_included_abn_count"] == 1


def test_parse_statements_handles_bom_and_blank_abn():
    (s,) = msr.parse_statements_csv("﻿" + csv_text([csv_row("2024-8", "201", "NO ABN", "")]))
    assert s["abns"] == [] and s["csv_included_abn_count"] == 0


def test_select_candidates_by_abn_and_by_childcare_term():
    rows = [
        csv_row("2024-1", "1", "KOOKABURRA LEARNING GROUP LIMITED", KOOK_ABN),
        csv_row("2024-2", "2", "BOTTLEBRUSH EARLY LEARNING PTY LTD", OTHER_ABN),
        csv_row("2024-3", "3", "IRONBARK MINING LIMITED", make_abn(33)),
        csv_row("2024-4", "4", "Coolabah Child Care Ltd", ""),
    ]
    cands = msr.select_candidates(msr.parse_statements_csv(csv_text(rows)), {KOOK_ABN})
    by_id = {c["statement_id"]: c["candidate_reason"] for c in cands}
    assert by_id == {"2024-1": "abn_match", "2024-2": "childcare_term", "2024-4": "childcare_term"}


def test_candidate_row_without_page_id_is_kept_for_the_completeness_check():
    rows = [csv_row("2024-9", "not-a-number", "KOOKABURRA LEARNING GROUP LIMITED", KOOK_ABN)]
    (c,) = msr.select_candidates(msr.parse_statements_csv(csv_text(rows)), {KOOK_ABN})
    assert c["page_id"] is None and c["candidate_reason"] == "abn_match"


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
# ABN checksum
# ---------------------------------------------------------------------------


def test_abn_checksum():
    assert msr.valid_abn("95123828553")  # a published public company ABN
    assert not msr.valid_abn("95123828554")
    assert not msr.valid_abn("9512382855")
    assert not msr.valid_abn("9512382855a")
    assert msr.valid_abn(WATTLE_ABN) and not msr.valid_abn(BAD_ABN)


# ---------------------------------------------------------------------------
# Strict page schema
# ---------------------------------------------------------------------------


def test_parse_statement_page_reporting_and_included():
    page = statement_page(
        [("KOOKABURRA LEARNING GROUP LIMITED", KOOK_ABN)],
        [
            "Wattle Kids Pty Ltd",
            "Wattle Kids Pty Ltd",
            ("Banksia Early Years Pty Ltd", BANKSIA_ABN),
        ],
    )
    parsed = msr.parse_statement_page(page)
    assert parsed["reporting"] == [{"name": "KOOKABURRA LEARNING GROUP LIMITED", "abn": KOOK_ABN}]
    assert parsed["included"] == [
        {"name": "Wattle Kids Pty Ltd", "abn": None},
        {"name": "Banksia Early Years Pty Ltd", "abn": BANKSIA_ABN},
    ]
    assert parsed["included_abn_count"] == 1


def test_parse_accepts_acn_paragraph_and_no_included_section():
    assert msr.parse_statement_page(statement_page([("A LTD", KOOK_ABN)]))["included"] == []
    acn_block = entity_div("Wattle Kids Pty Ltd", acn="123456789")
    page = statement_page([("A LTD", KOOK_ABN)], ["X"]).replace(
        entity_div("X").strip(), acn_block.strip()
    )
    assert msr.parse_statement_page(page)["included"][0]["abn"] is None


def test_parse_accepts_non_profit_flag_and_former_name():
    page = statement_page([("A LTD", KOOK_ABN)], ["Wattle Kids Pty Ltd"])
    page = page.replace(
        "<p>\n        </p>", "<p>\n          Non-profit organisation<br/>\n</p>", 1
    ).replace("A LTD </a>", "A LTD <small>( Old Name Ltd )</small> </a>", 1)
    parsed = msr.parse_statement_page(page)
    assert parsed["reporting"][0]["abn"] == KOOK_ABN


@pytest.mark.parametrize(
    "old,new",
    [
        # an unrecognised sibling element in the section
        (
            '<div id="statement-included-entities" class="accordion__content collapse hide">',
            '<div id="statement-included-entities" class="accordion__content collapse hide">'
            '<div class="statement-entity-v2"><span>Banksia</span></div>',
        ),
        # stray text in the section
        (
            '<div id="statement-included-entities" class="accordion__content collapse hide">',
            '<div id="statement-included-entities" class="accordion__content collapse hide">Banksia',
        ),
        # nested unrecognised content inside an entity block
        (
            '<div class="statement-entity__name">',
            '<span class="extra">Banksia Early Years</span><div class="statement-entity__name">',
        ),
        # nested unrecognised content inside the name block
        (
            'target="_blank">Wattle Kids Pty Ltd </a>',
            'target="_blank">Wattle Kids Pty Ltd </a><em>x</em>',
        ),
        # a paragraph with an unknown label
        ("<p>\n        </p>", "<p>Owner: <a href='/x'>1</a></p>"),
        # a comment inside the section
        (
            '<div id="statement-included-entities" class="accordion__content collapse hide">',
            '<div id="statement-included-entities" class="accordion__content collapse hide">'
            "<!-- hidden -->",
        ),
        # name link missing
        ('class="statement-entity__name-link"', 'class="something-else"'),
    ],
)
def test_parse_rejects_any_unrecognised_structure(old, new):
    # Codex round 4 item 4: anything outside the known structure, at any depth, is an error.
    page = statement_page([("A LTD", KOOK_ABN)], ["Wattle Kids Pty Ltd"])
    idx = page.index("statement-included-entities")
    head, tail = page[:idx], page[idx:]
    assert old in tail or old in page
    page = head + tail.replace(old, new, 1) if old in tail else page.replace(old, new, 1)
    with pytest.raises(msr.PageParseError):
        msr.parse_statement_page(page)


def test_parse_rejects_included_section_without_entities():
    page = statement_page([("A LTD", KOOK_ABN)], ["Wattle Kids Pty Ltd"])
    start = page.index('<div class="statement-entity">', page.index("statement-included-entities"))
    end = page.index("</div>\n</div>", start)
    with pytest.raises(msr.PageParseError):
        msr.parse_statement_page(page[:start] + page[end:])


def test_parse_rejects_missing_reporting_section():
    with pytest.raises(msr.PageParseError):
        msr.parse_statement_page("<html><body>maintenance page</body></html>")


@pytest.mark.parametrize("abn_text", ["95 123 828 554", "95 123 828", "95 123 828 55x"])
def test_parse_rejects_an_unusable_abn_text(abn_text):
    # Codex round 4 item 1: an ABN link whose text is not a valid ABN makes the page unparseable.
    page = statement_page([("A LTD", KOOK_ABN)], [("Wattle Kids Pty Ltd", WATTLE_ABN)])
    page = page.replace(spaced(WATTLE_ABN), abn_text)
    with pytest.raises(msr.PageParseError):
        msr.parse_statement_page(page)


def test_parse_reads_the_registers_00_placeholder_as_no_abn_and_lists_it():
    # The register shows one ARBN-only entity as "ABN: 00 649 711 026", which fails the ABN
    # checksum. Only such a failing 00-prefixed value is a placeholder.
    page = statement_page([("A LTD", KOOK_ABN)], [("Wattle Kids Pty Ltd", WATTLE_ABN)])
    page = page.replace(f"?abn={KOOK_ABN}", "?abn=00649711026").replace(
        spaced(KOOK_ABN), "00 649 711 026"
    )
    parsed = msr.parse_statement_page(page)
    assert parsed["reporting"][0]["abn"] is None
    assert parsed["abn_placeholders"] == [{"msr_role": "reporting_entity", "value": "00649711026"}]
    assert parsed["included"][0]["abn"] == WATTLE_ABN


def test_checksum_valid_00_value_is_a_real_abn_not_a_placeholder():
    # Codex round 5 item 3: 00000000019 passes the checksum, so it is an ABN.
    assert msr.valid_abn("00000000019")
    page = statement_page([("A LTD", KOOK_ABN)])
    page = page.replace(f"?abn={KOOK_ABN}", "?abn=00000000019").replace(
        spaced(KOOK_ABN), "00 000 000 019"
    )
    parsed = msr.parse_statement_page(page)
    assert parsed["reporting"][0]["abn"] == "00000000019"
    assert parsed["abn_placeholders"] == []


@pytest.mark.parametrize(
    "text,href", [("01 649 711 026", "01649711026"), ("00 649 711", "00649711")]
)
def test_parse_rejects_near_placeholders(text, href):
    page = statement_page([("A LTD", KOOK_ABN)])
    page = page.replace(f"?abn={KOOK_ABN}", f"?abn={href}").replace(spaced(KOOK_ABN), text)
    with pytest.raises(msr.PageParseError):
        msr.parse_statement_page(page)


def test_parse_rejects_abn_href_and_text_that_disagree():
    page = statement_page([("A LTD", KOOK_ABN)], [("Wattle Kids Pty Ltd", WATTLE_ABN)])
    page = page.replace(f"?abn={WATTLE_ABN}", f"?abn={BANKSIA_ABN}")
    with pytest.raises(msr.PageParseError):
        msr.parse_statement_page(page)


RECONCILE_ENTITIES = [
    {"name": "Wattle Kids Pty Ltd", "abn": WATTLE_ABN},
    {"name": "Gumnut Care Pty Ltd", "abn": None},
]


def test_reconcile_exact_match_passes_after_case_and_whitespace_normalisation():
    text = f"WATTLE KIDS  PTY LTD ({spaced(WATTLE_ABN)}), gumnut care pty ltd"
    assert msr.reconcile_entities(text, RECONCILE_ENTITIES) == {}


def test_reconcile_empty_field_and_no_entities_passes():
    assert msr.reconcile_entities("", []) == {}


@pytest.mark.parametrize(
    "text,abn_differs",
    [
        # a different ABN on the page than in the CSV, with equal counts
        (f"Wattle Kids Pty Ltd ({spaced(BANKSIA_ABN)}), Gumnut Care Pty Ltd", True),
        # the CSV lists a name-only entity the page omits
        (f"Wattle Kids Pty Ltd ({spaced(WATTLE_ABN)}), Gumnut Care Pty Ltd, Waratah Ltd", False),
        # the page lists a name-only entity the CSV lacks
        (f"Wattle Kids Pty Ltd ({spaced(WATTLE_ABN)})", False),
        # a page name that is only part of a longer CSV name
        (f"Wattle Kids Pty Ltd ({spaced(WATTLE_ABN)}), Gumnut Care Pty Ltd Holdings", False),
        # an ABN in the CSV that the page does not give
        (
            f"Wattle Kids Pty Ltd ({spaced(WATTLE_ABN)}), Gumnut Care Pty Ltd "
            f"({spaced(LILLY_ABN)})",
            True,
        ),
    ],
)
def test_reconcile_reports_each_difference(text, abn_differs):
    out = msr.reconcile_entities(text, RECONCILE_ENTITIES)
    assert out.get("no_grouping_matches_page") == 1
    assert ("abn_multiset_differs" in out) is abn_differs


def test_reconcile_swapped_name_abn_pairs_fail():
    # Codex round 6: the ABN set and the name set both agree, but the pairs do not.
    entities = [
        {"name": "Wattle Kids Pty Ltd", "abn": WATTLE_ABN},
        {"name": "Banksia Early Years Pty Ltd", "abn": BANKSIA_ABN},
    ]
    text = (
        f"Wattle Kids Pty Ltd ({spaced(BANKSIA_ABN)}), "
        f"Banksia Early Years Pty Ltd ({spaced(WATTLE_ABN)})"
    )
    assert msr.reconcile_entities(text, entities) == {"no_grouping_matches_page": 1}


def test_reconcile_counts_duplicates_and_does_not_deduplicate():
    entities = [{"name": "Gumnut Care Pty Ltd", "abn": None}]
    twice = "Gumnut Care Pty Ltd, Gumnut Care Pty Ltd"
    assert msr.reconcile_entities(twice, entities) == {"no_grouping_matches_page": 1}
    assert msr.reconcile_entities(twice, entities * 2) == {}


def test_reconcile_name_with_a_comma_passes_when_exactly_one_grouping_fits():
    entities = [
        {"name": "Numbat College, Suburb", "abn": None},
        {"name": "Wattle Kids Pty Ltd", "abn": WATTLE_ABN},
    ]
    text = f"Numbat College, Suburb, Wattle Kids Pty Ltd ({spaced(WATTLE_ABN)})"
    assert msr.reconcile_entities(text, entities) == {}


def test_reconcile_two_valid_groupings_fail():
    # "Acacia, Acacia, Acacia" fits the page's two entities as (2 + 1) or (1 + 2) pieces.
    entities = [{"name": "Acacia, Acacia", "abn": None}, {"name": "Acacia", "abn": None}]
    out = msr.reconcile_entities("Acacia, Acacia, Acacia", entities)
    assert out == {"several_groupings_match_page": 2}


def test_reconcile_comma_after_a_bracketed_abn_always_separates():
    # Joining across "(ABN)," would make one entry that equals this page name; it is not allowed.
    entities = [{"name": f"Wattle Kids Pty Ltd ({spaced(WATTLE_ABN)}), Gumnut", "abn": None}]
    text = f"Wattle Kids Pty Ltd ({spaced(WATTLE_ABN)}), Gumnut"
    assert msr.reconcile_entities(text, entities).get("no_grouping_matches_page") == 1


def test_reconcile_search_is_bounded_and_fails_closed(monkeypatch):
    monkeypatch.setattr(msr, "MAX_GROUPING_STEPS", 5)
    entities = [{"name": "Acacia", "abn": None}] * 20
    out = msr.reconcile_entities(", ".join(["Acacia"] * 20), entities)
    assert out == {"grouping_search_limit_exceeded": 5}


def test_reconcile_fails_closed_on_a_field_too_long_to_search():
    entities = [{"name": "Acacia", "abn": None}] * 3000
    out = msr.reconcile_entities(", ".join(["Acacia"] * 3000), entities)
    assert out == {"grouping_search_limit_exceeded": msr.MAX_GROUPING_STEPS}


def test_grouping_limit_is_set():
    assert msr.MAX_GROUPING_STEPS == 100_000


def test_reconcile_counts_hold_no_names():
    out = msr.reconcile_entities("Waratah Ltd", RECONCILE_ENTITIES)
    assert all(isinstance(v, int) for v in out.values())
    assert "Waratah" not in repr(out) and "Gumnut" not in repr(out)


# ---------------------------------------------------------------------------
# CSV header (Codex round 5 item 2)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("column", msr.REQUIRED_CSV_COLUMNS)
def test_parse_statements_rejects_a_missing_column(column):
    header = [h for h in CSV_HEADER if h != column]
    with pytest.raises(msr.CsvSchemaError, match=column):
        msr.parse_statements_csv(csv_text([csv_row("2024-1", "1", "X LTD", KOOK_ABN)], header))


def test_parse_statements_rejects_a_renamed_column():
    header = ["URL" if h == "Link" else h for h in CSV_HEADER]
    row = csv_row("2024-1", "1", "X LTD", KOOK_ABN)
    row["URL"] = row.pop("Link")
    with pytest.raises(msr.CsvSchemaError, match="Link"):
        msr.parse_statements_csv(csv_text([row], header))


def test_parse_statements_rejects_a_short_row_instead_of_defaulting_to_empty():
    text = csv_text([csv_row("2024-1", "1", "X LTD", KOOK_ABN)]) + "2024-2,2024-01-01\n"
    with pytest.raises(msr.CsvSchemaError):
        msr.parse_statements_csv(text)


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


@pytest.mark.parametrize(
    "a,b",
    [
        ("Wattle Kids Pty Ltd", "Wattle Kids Ltd"),
        ("Story House Early Learning No 1 Pty Ltd", "Story House Early Learning No 21 Pty Ltd"),
        (
            "Ramsay Bourne Acquisitions (No. 2) Pty Limited",
            "Ramsay Bourne Acquisitions (No.1) Pty Limited",
        ),
    ],
)
def test_normalise_keeps_different_entities_apart(a, b):
    assert msr.normalise(a) != msr.normalise(b)


# ---------------------------------------------------------------------------
# Screening (Codex round 4 item 3)
# ---------------------------------------------------------------------------


def screened(profiles=PROFILES, abn_rows=ABN_ROWS, details=()):
    return msr.screen_providers(profiles, abn_rows, msr.abr_types_from(abn_rows, list(details)))


def test_screening_passes_positively_classified_organisations_only():
    ok, stats = screened()
    assert set(ok) == {
        "PR-00000001",
        "PR-00000002",
        "PR-00000003",
        "PR-00000004",
        "PR-00000005",
        "PR-00000006",
        "PR-00000007",
        "PR-00000009",
    }
    assert stats["excluded_not_positively_organisation"] == 1  # PR-00000008


@pytest.mark.parametrize(
    "profiles,abn_rows,details,reason",
    [
        (
            PROFILES + [prof("PR-00000002", "Wattle Kids Pty Ltd")],
            ABN_ROWS,
            (),
            "excluded_duplicate_profile_rows",
        ),
        (
            [p for p in PROFILES if p["provider_approval_number"] != "PR-00000002"],
            ABN_ROWS,
            (),
            "excluded_missing_profile",
        ),
        (
            [
                p if p["provider_approval_number"] != "PR-00000002" else prof("PR-00000002", "  ")
                for p in PROFILES
            ],
            ABN_ROWS,
            (),
            "excluded_blank_legal_name",
        ),
        (
            [
                p
                if p["provider_approval_number"] != "PR-00000002"
                else prof("PR-00000002", "Wattle Kids Pty Ltd", withheld="true")
                for p in PROFILES
            ],
            ABN_ROWS,
            (),
            "excluded_name_withheld",
        ),
        (
            [
                p
                if p["provider_approval_number"] != "PR-00000002"
                else prof("PR-00000002", "Wattle Kids Pty Ltd", form="unknown")
                for p in PROFILES
            ],
            ABN_ROWS,
            (),
            "excluded_not_positively_organisation",
        ),
        (
            PROFILES,
            ABN_ROWS + [abn_row("PR-00000002", "Wattle Kids Pty Ltd", WATTLE_ABN)],
            (),
            "excluded_duplicate_provider_abn_rows",
        ),
        (
            PROFILES,
            [
                r
                if r["provider_approval_number"] != "PR-00000002"
                else abn_row("PR-00000002", "", "", code="", kind="excluded_individual_abr")
                for r in ABN_ROWS
            ],
            (),
            "excluded_abr_individual",
        ),
        (
            PROFILES,
            ABN_ROWS,
            [
                {
                    "abn": WATTLE_ABN,
                    "lookup_status": "ok",
                    "entity_type_code": "IND",
                    "entity_name": "",
                }
            ],
            "excluded_abr_individual",
        ),
        (
            PROFILES,
            ABN_ROWS,
            [
                {
                    "abn": WATTLE_ABN,
                    "lookup_status": "ok",
                    "entity_type_code": "PUB",
                    "entity_name": "X",
                }
            ],
            "excluded_abr_type_conflict",
        ),
    ],
)
def test_screening_excludes_and_counts_each_case(profiles, abn_rows, details, reason):
    ok, stats = screened(profiles, abn_rows, details)
    assert "PR-00000002" not in ok
    assert stats[reason] >= 1


def test_screened_provider_with_individual_abr_never_appears_in_any_output():
    details = [
        {"abn": WATTLE_ABN, "lookup_status": "ok", "entity_type_code": "IND", "entity_name": ""}
    ]
    out = layer(stmt([PARENT], [("Wattle Kids Pty Ltd", WATTLE_ABN)]), details=details)
    assert "PR-00000002" not in repr(out) and "Wattle" not in repr(out)


PERSON_TRUST = "The Trustee for the Jane Example Family Trust"
PERSON_COMPANY = "Dr Jane Example Pty Ltd"


@pytest.mark.parametrize(
    "legal,form", [(PERSON_TRUST, "trust_or_trustee"), (PERSON_COMPANY, "company")]
)
def test_screening_applies_the_shared_name_classifier(legal, form):
    # Rebuilt on main: even when the profile row says the name is shown, the shared classifier
    # (profile_providers.name_is_withheld) is applied again and a person signal excludes it.
    person_abn = make_abn(55)
    profiles = PROFILES + [prof("PR-00000055", legal, form=form)]
    rows = ABN_ROWS + [abn_row("PR-00000055", legal, person_abn)]
    ok, stats = screened(profiles, rows)
    assert "PR-00000055" not in ok
    assert stats["excluded_classifier_withholds_name"] == 1


def test_person_named_provider_matched_by_abn_never_appears_in_any_output():
    person_abn = make_abn(56)
    profiles = PROFILES + [prof("PR-00000056", PERSON_TRUST, form="trust_or_trustee")]
    rows = ABN_ROWS + [abn_row("PR-00000056", PERSON_TRUST, person_abn)]
    out = layer(stmt([PARENT], [("x", person_abn)]), profiles=profiles, abn_rows=rows)
    assert out["edges"] == [] and out["review"] == []
    assert "Jane" not in repr(out) and "PR-00000056" not in repr(out)


def test_statement_urls_naming_a_person_are_withheld_whole():
    rows = [
        {
            "statement_url": "https://example.org/docs/Jane%20Example.pdf",
            "statement_urls": "https://modernslaveryregister.gov.au/statements/12/; "
            "https://example.org/docs/Jane%20Example.pdf",
        },
        {
            "statement_url": "https://modernslaveryregister.gov.au/statements/12/",
            "statement_urls": "https://modernslaveryregister.gov.au/statements/12/",
        },
    ]
    counts = msr.withhold_statement_urls(rows)
    assert rows[0]["statement_url"] is None
    assert rows[0]["statement_urls"] == "https://modernslaveryregister.gov.au/statements/12/"
    assert rows[1]["statement_url"] == "https://modernslaveryregister.gov.au/statements/12/"
    assert counts == {"statement_url": 1, "statement_urls": 1}
    assert "Jane" not in repr(rows)


def test_summary_paths_and_urls_naming_a_person_are_withheld(tmp_path, monkeypatch):
    monkeypatch.setattr(msr, "SUMMARY_JSON", tmp_path / "summary.json")
    msr.write_summary(
        {
            "inputs": ["data/raw/msr/Jane Example/x.html", "data/processed/provider-abn.csv"],
            "source": {"csv_url": "https://example.org/docs/Jane%20Example.pdf"},
        }
    )
    text = (tmp_path / "summary.json").read_text(encoding="utf-8")
    assert "Jane" not in text
    assert "data/processed/provider-abn.csv" in text


def test_abn_index_holds_screened_providers_only():
    # A duplicate profile row excludes PR-00000002; its ABN must not match anything.
    out = layer(
        stmt([PARENT], [("Wattle Kids Pty Ltd", WATTLE_ABN)]),
        profiles=PROFILES + [prof("PR-00000002", "Wattle Kids Pty Ltd")],
    )
    assert out["edges"] == [] and "PR-00000002" not in repr(out)


def test_provider_name_comes_from_the_screened_profile_only():
    # Codex round 4: no name from provider-abn.csv rows. A provider without a profile row is
    # excluded even though its ABN row carries a name.
    rows = ABN_ROWS + [abn_row("PR-00000099", "Orphan Provider Pty Ltd", OTHER_ABN)]
    out = layer(stmt([PARENT], [("x", OTHER_ABN)]), abn_rows=rows)
    assert out["edges"] == [] and "Orphan" not in repr(out)


def test_duplicate_input_rows_are_detected():
    assert msr.duplicate_keys(PROFILES + [prof("PR-00000001", "x")]) == ["PR-00000001"]
    assert msr.duplicate_keys(PROFILES) == []


# ---------------------------------------------------------------------------
# Matching: ABN only (Codex round 4 item 1)
# ---------------------------------------------------------------------------


def test_included_entity_by_abn_is_an_edge():
    (e,) = layer(stmt([PARENT], [("Renamed Wattle Co", WATTLE_ABN)]))["edges"]
    assert e["provider_approval_number"] == "PR-00000002"
    assert e["provider_legal_name"] == "Wattle Kids Pty Ltd"
    assert e["match_method"] == "included_entity_abn_equals_provider_abn"
    assert e["group_key"] == PARENT_ABN and e["group_abn"] == PARENT_ABN
    assert e["msr_entity_abn"] == WATTLE_ABN
    assert "Renamed" not in repr(e)


def test_exact_name_without_abn_goes_to_review_never_an_edge():
    out = layer(stmt([PARENT], ["Wattle Kids Pty. Ltd."]))
    assert out["edges"] == []
    (r,) = out["review"]
    assert r["reason"] == "name_match_without_msr_abn"
    assert r["candidate_provider_approval_numbers"] == "PR-00000002"


def test_ambiguous_name_goes_to_review_never_edges():
    out = layer(stmt([PARENT], ["Gumnut Care Pty Ltd"]))
    assert out["edges"] == []
    (r,) = out["review"]
    assert r["reason"] == "ambiguous_matches_several_providers"
    assert r["candidate_provider_approval_numbers"] == "PR-00000004; PR-00000005"


def test_fuzzy_suffix_match_goes_to_review():
    out = layer(stmt([PARENT], ["Grevillea Kindergarten"]))
    assert out["edges"] == []
    (r,) = out["review"]
    assert r["reason"] == "fuzzy_corporate_suffix_differs"


def test_msr_abn_that_differs_from_provider_abn_goes_to_review():
    out = layer(stmt([PARENT], [("Wattle Kids Pty Ltd", OTHER_ABN)]))
    assert out["edges"] == []
    assert out["review"][0]["reason"] == "msr_abn_differs_from_provider_abn"
    assert out["review"][0]["msr_entity_abn"] == OTHER_ABN


def test_msr_abn_with_provider_abn_unresolved_goes_to_review():
    out = layer(stmt([{"name": "Waratah Centres Pty Ltd", "abn": OTHER_ABN}]))
    assert out["edges"] == []
    assert out["review"][0]["reason"] == "name_match_provider_abn_not_resolved"


def test_reporting_entity_name_only_goes_to_review():
    out = layer(stmt([{"name": "Waratah Centres Pty Ltd", "abn": None}]))
    assert out["edges"] == [] and out["heads"] == []
    assert out["review"][0]["reason"] == "name_match_without_msr_abn"
    assert out["review"][0]["msr_role"] == "reporting_entity"


def test_individual_provider_never_appears():
    out = layer(stmt([PARENT], ["Sample Person"]))
    assert out["edges"] == [] and out["review"] == [] and out["relations"] == []
    assert "Sample Person" not in repr(out) and "PR-00000008" not in repr(out)


def test_review_rows_hold_no_names():
    out = layer(stmt([PARENT], ["Gumnut Care Pty Ltd", "Grevillea Kindergarten"]))
    assert out["review"]
    for r in out["review"]:
        assert not [k for k in r if "name" in k]
        assert "Gumnut" not in repr(r) and "Grevillea" not in repr(r)


# ---------------------------------------------------------------------------
# Classification and collapse
# ---------------------------------------------------------------------------


def test_self_relation_is_a_group_head_not_an_edge():
    out = layer(stmt([KOOK], [("Wattle Kids Pty Ltd", WATTLE_ABN), ("Kook dup", KOOK_ABN)]))
    assert [e["provider_approval_number"] for e in out["edges"]] == ["PR-00000002"]
    (h,) = out["heads"]
    assert h["provider_approval_number"] == "PR-00000001"
    assert h["relation"] == msr.HEAD
    assert h["group_key"] == KOOK_ABN
    assert h["controlled_providers_linked"] == 1


def test_reporting_entity_without_included_entities_is_written_nowhere():
    out = layer(stmt([KOOK]))
    assert out["edges"] == [] and out["heads"] == [] and out["coreported"] == []
    (rel,) = out["relations"]
    assert rel["relation"] == msr.SELF_ONLY


def test_joint_statement_rows_never_reach_edges_or_heads():
    joint = stmt(
        [KOOK, {"name": "WATTLE KIDS PTY LTD", "abn": WATTLE_ABN}],
        [("Banksia Early Years Pty Ltd", BANKSIA_ABN)],
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


def test_single_group_joint_statement_is_not_promoted_but_listed():
    out = layer(stmt([PARENT], [("x", WATTLE_ABN)], type_="Joint", page=150))
    assert out["edges"] == []
    (cand,) = msr.joint_manual_candidates(out["coreported"])
    assert cand["statement_url"].endswith("/statements/150/")
    assert cand["included_providers"] == ["PR-00000002"]


def test_duplicate_statements_across_years_collapse_to_one_edge():
    out = layer(
        stmt([PARENT], [("x", WATTLE_ABN)], year=2022, page=201),
        stmt([PARENT], [("x", WATTLE_ABN)], year=2024, page=203),
        stmt([PARENT], [("x", WATTLE_ABN)], year=2023, page=202),
    )
    (e,) = out["edges"]
    assert e["statement_count"] == 3
    assert e["statement_url"].endswith("/statements/203/")
    assert e["reporting_period"] == "2024-01-01 to 2024-12-31"
    assert e["statement_ids"] == "2023-201; 2024-202; 2025-203"


def test_group_key_without_abn_is_the_statement_page():
    out = layer(stmt([{"name": "Parent Limited", "abn": None}], [("x", WATTLE_ABN)], page=777))
    (e,) = out["edges"]
    assert e["group_key"] == "MSR-777"
    assert e["group_key_source"] == "statement_page_no_abn"
    assert e["group_abn"] is None


def test_group_key_is_never_borrowed_from_another_statement():
    out = layer(
        stmt([PARENT], [("x", WATTLE_ABN)], year=2023, page=301),
        stmt([{"name": "PARENT LTD", "abn": None}], [("x", WATTLE_ABN)], year=2024, page=302),
    )
    assert {e["group_key"] for e in out["edges"]} == {PARENT_ABN, "MSR-302"}


def test_other_statement_types_are_unclassified():
    rel = {
        "statement_type": "Voluntary",
        "reporting_entity_count": 1,
        "msr_role": "included_entity",
        "included_entities_listed": 1,
    }
    assert msr.classify_relation(rel) == msr.UNCLASSIFIED


# ---------------------------------------------------------------------------
# Output columns: only ACECQA provider names (Codex round 4 item 2)
# ---------------------------------------------------------------------------


def test_only_name_column_in_any_output_is_the_acecqa_provider_name():
    for cols in (msr.EDGE_COLUMNS, msr.HEAD_COLUMNS, msr.COREPORTED_COLUMNS):
        assert {c for c in cols if "name" in c} == {"provider_legal_name"}
    assert not [c for c in msr.REVIEW_COLUMNS if "name" in c]


def test_group_name_and_trust_wording_code_are_gone():
    for attr in (
        "group_name_fields",
        "ALLOWED_GROUP_ABR_TYPES",
        "_PERSON_WORDING",
        "_shown_name",
        "is_organisation_name",
        "csv_included_lower_bound",
    ):
        assert not hasattr(msr, attr)


def test_every_edge_has_required_columns():
    (e,) = layer(stmt([KOOK], [("x", WATTLE_ABN)]))["edges"]
    for col in msr.EDGE_COLUMNS:
        assert col in e
    assert e["edge_type"] == e["relation"] == msr.CONTROLLED


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def test_summary_counts_each_class_separately():
    out = layer(
        stmt([KOOK], [("x", WATTLE_ABN), "Gumnut Care Pty Ltd"], year=2024, page=401),
        stmt([KOOK], [("x", WATTLE_ABN)], year=2023, page=400),
        stmt([PARENT], [("x", BANKSIA_ABN)], type_="Joint", page=402),
    )
    services = [
        {"provider_approval_number": p}
        for p in ("PR-00000001", "PR-00000001", "PR-00000002", "PR-00000003")
    ]
    s = msr.summarise(out, ABN_ROWS, services, candidates_count=3)
    c = s["counts"]
    ce = c["controlled_entity_of"]
    assert (ce["edges"], ce["distinct_providers"], ce["groups"]) == (1, 1, 1)
    assert ce["services_of_those_providers"] == 1
    assert c["group_parent_self_not_ownership_edges"]["rows"] == 1
    joint = c["co_reported_joint_not_ownership"]
    assert joint["rows"] == 1 and joint["providers_with_only_joint_relations"] == 1
    assert c["relations_by_class"] == {msr.JOINT: 1, msr.CONTROLLED: 2, msr.HEAD: 2}
    assert c["review_queue"] == 1
    (g,) = s["groups"]
    assert g == {
        "group_key": KOOK_ABN,
        "group_abn": KOOK_ABN,
        "controlled_providers": 1,
        "services_of_controlled_providers": 1,
        "head_provider": "PR-00000001",
    }
    assert "screening" in c


def test_only_joint_label_excludes_self_only_providers():
    out = layer(stmt([KOOK], year=2024, page=410), stmt([PARENT, KOOK], type_="Joint", page=411))
    joint = msr.summarise(out, ABN_ROWS, [], candidates_count=2)["counts"][
        "co_reported_joint_not_ownership"
    ]
    assert joint["distinct_providers"] == 1
    assert joint["providers_with_only_joint_relations"] == 0


# ---------------------------------------------------------------------------
# Main: exit codes, outputs on disk, services, refresh
# ---------------------------------------------------------------------------

SENTINEL = "SENTINEL FULL STATEMENT TEXT THAT MUST NEVER BE COPIED"
PERSON_BUSINESS = "Jane Example Care Services Pty Ltd"


def _write_csv(path, rows, fields):
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})


PROFILE_FIELDS = ["provider_approval_number", "legal_name", "entity_form", "name_withheld"]
ABN_FIELDS = [
    "provider_approval_number",
    "legal_name",
    "abn",
    "abr_entity_name",
    "entity_type_code",
    "match_kind",
]
DETAIL_FIELDS = ["abn", "lookup_status", "entity_type_code", "entity_name"]


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A tmp raw dir with one CSV snapshot and two statement pages, and tmp processed inputs."""
    from scrapers import common

    raw = tmp_path / "raw"
    rows = [
        csv_row(
            "2024-501",
            "501",
            KOOK_REP_TEXT,
            KOOK_ABN,
            included=f"WATTLE KIDS PTY LTD ({spaced(WATTLE_ABN)}), Gumnut Care Pty Ltd, "
            "Grevillea Kindergarten",
        ),
        csv_row(
            "2024-502",
            "502",
            f"PARENT LTD ({spaced(PARENT_ABN)}), "
            f"BANKSIA EARLY YEARS PTY LTD ({spaced(BANKSIA_ABN)})",
            f"{PARENT_ABN}, {BANKSIA_ABN}",
            included="Lilly Pilly Childcare Pty Ltd",
            type_="Joint",
        ),
    ]
    (raw / "msr" / "all-statements").mkdir(parents=True)
    (raw / "msr" / "all-statements" / "2026-01-01T0000Z.csv").write_text(
        csv_text(rows), encoding="utf-8"
    )
    pages = {
        "501": statement_page(
            [("KOOKABURRA LEARNING GROUP LIMITED", KOOK_ABN)],
            [("Wattle Kids Pty Ltd", WATTLE_ABN), "Gumnut Care Pty Ltd", "Grevillea Kindergarten"],
        ),
        "502": statement_page(
            [("PARENT LTD", PARENT_ABN), ("BANKSIA EARLY YEARS PTY LTD", BANKSIA_ABN)],
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
    _write_csv(proc / "provider-profile.csv", PROFILES, PROFILE_FIELDS)
    _write_csv(proc / "provider-abn.csv", ABN_ROWS, ABN_FIELDS)
    _write_csv(
        proc / "acecqa-services-latest.csv",
        [{"provider_approval_number": "PR-00000002"}],
        ["provider_approval_number"],
    )
    _write_csv(
        proc / "abn-details.csv",
        [{"abn": OTHER_ABN, "lookup_status": "excluded_individual", "entity_type_code": "IND"}],
        DETAIL_FIELDS,
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
    monkeypatch.setattr(msr, "ABN_DETAILS_CSV", proc / "abn-details.csv")
    monkeypatch.setattr(msr, "SERVICES_CSV", proc / "acecqa-services-latest.csv")
    monkeypatch.setattr(msr, "SUMMARY_JSON", proc / "summary.json")
    return {"raw": raw, "proc": proc, "written": written}


def _summary(env):
    return json.loads((env["proc"] / "summary.json").read_text(encoding="utf-8"))


def everything_written(env):
    summary = env["proc"] / "summary.json"
    return repr(env["written"]) + (summary.read_text(encoding="utf-8") if summary.exists() else "")


def add_statement(
    env, idx, page_id, reporting, abns, page_html, *, included_text="", type_="Single"
):
    snap = env["raw"] / "msr" / "all-statements" / "2026-01-01T0000Z.csv"
    rows = list(csv.DictReader(io.StringIO(snap.read_text(encoding="utf-8"))))
    rows.append(csv_row(idx, page_id, reporting, abns, included=included_text, type_=type_))
    snap.write_text(csv_text(rows), encoding="utf-8")
    d = env["raw"] / "msr" / "statements" / page_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "2026-01-01T0000Z.html").write_text(page_html, encoding="utf-8")


def test_main_exit_0_when_complete(env):
    assert msr.main(["--no-fetch"]) == 0
    assert set(env["written"]) == {
        msr.EDGES_NAME,
        msr.HEADS_NAME,
        msr.COREPORTED_NAME,
        msr.REVIEW_NAME,
    }
    assert (env["proc"] / "summary.json").exists()


def test_main_edges_file_holds_only_abn_matched_controlled_entities(env):
    assert msr.main(["--no-fetch"]) == 0
    edges = env["written"][msr.EDGES_NAME]["rows"]
    assert [e["provider_approval_number"] for e in edges] == ["PR-00000002"]
    assert {e["relation"] for e in edges} == {msr.CONTROLLED}
    joint = env["written"][msr.COREPORTED_NAME]["rows"]
    assert {r["provider_approval_number"] for r in joint} == {"PR-00000003"}
    reasons = {r["reason"] for r in env["written"][msr.REVIEW_NAME]["rows"]}
    assert {"ambiguous_matches_several_providers", "fuzzy_corporate_suffix_differs"} <= reasons


def test_main_written_columns_follow_the_name_policy(env):
    assert msr.main(["--no-fetch"]) == 0
    w = env["written"]
    assert w[msr.EDGES_NAME]["fieldnames"] == msr.EDGE_COLUMNS
    assert w[msr.HEADS_NAME]["fieldnames"] == msr.HEAD_COLUMNS
    assert w[msr.COREPORTED_NAME]["fieldnames"] == msr.COREPORTED_COLUMNS
    assert w[msr.REVIEW_NAME]["fieldnames"] == msr.REVIEW_COLUMNS
    for row in w[msr.COREPORTED_NAME]["rows"]:
        shown = {k: row.get(k) for k in msr.COREPORTED_COLUMNS}
        assert "PARENT" not in repr(shown) and "Lilly" not in repr(shown)
    s = _summary(env)
    for key in ("candidate_statements", "joint_statements_for_manual_confirmation", "groups"):
        for item in s[key]:
            assert not [k for k in item if "name" in k]
    assert "PARENT LTD" not in everything_written(env)


def test_main_outputs_contain_no_raw_statement_text(env):
    assert msr.main(["--no-fetch"]) == 0
    blob = everything_written(env)
    assert SENTINEL not in blob
    assert "<div" not in blob and "statement-entity" not in blob


def test_person_plus_business_word_name_never_appears_in_any_output(env):
    add_statement(
        env,
        "2024-503",
        "503",
        PERSON_BUSINESS,
        WATTLE_ABN,
        statement_page([(PERSON_BUSINESS, None)], [("x", WATTLE_ABN)]),
        included_text=f"x ({spaced(WATTLE_ABN)})",
    )
    add_statement(
        env,
        "2024-504",
        "504",
        f"{PERSON_BUSINESS} ({spaced(OTHER_ABN)})",
        f"{OTHER_ABN}, {WATTLE_ABN}",
        statement_page([(PERSON_BUSINESS, OTHER_ABN)], [("x", WATTLE_ABN)]),
        included_text=f"x ({spaced(WATTLE_ABN)})",
    )
    assert msr.main(["--no-fetch"]) == 0
    blob = everything_written(env)
    assert "Jane" not in blob and "JANE" not in blob
    keys = {e["group_key"] for e in env["written"][msr.EDGES_NAME]["rows"]}
    assert {"MSR-503", OTHER_ABN} <= keys


def test_main_exit_2_and_no_writes_when_a_page_is_missing(env):
    for f in (env["raw"] / "msr" / "statements" / "502").iterdir():
        f.unlink()
    assert msr.main(["--no-fetch"]) == 2
    assert env["written"] == {} and not (env["proc"] / "summary.json").exists()


def test_main_exit_2_when_a_page_is_unparseable(env):
    (env["raw"] / "msr" / "statements" / "502" / "2026-01-01T0000Z.html").write_text(
        "<html><body>maintenance page</body></html>", encoding="utf-8"
    )
    assert msr.main(["--no-fetch"]) == 2
    assert env["written"] == {}


def test_main_exit_2_on_nested_unrecognised_markup(env):
    page = env["raw"] / "msr" / "statements" / "501" / "2026-01-01T0000Z.html"
    html = page.read_text(encoding="utf-8").replace(
        '<div class="statement-entity__name">',
        '<div class="statement-entity__name"><span>extra</span>',
        2,
    )
    page.write_text(html, encoding="utf-8")
    assert msr.main(["--no-fetch"]) == 2
    assert env["written"] == {}


def test_main_exit_2_on_an_unusable_abn_text(env):
    page = env["raw"] / "msr" / "statements" / "501" / "2026-01-01T0000Z.html"
    html = page.read_text(encoding="utf-8").replace(spaced(WATTLE_ABN), "not an abn")
    page.write_text(html, encoding="utf-8")
    assert msr.main(["--no-fetch"]) == 2
    assert env["written"] == {}


def test_main_builds_with_a_placeholder_abn_and_lists_it(env):
    page = statement_page([("PLACEHOLDER EDUCATION CO", PARENT_ABN)], [("x", WATTLE_ABN)])
    page = page.replace(f"?abn={PARENT_ABN}", "?abn=00649711026").replace(
        spaced(PARENT_ABN), "00 649 711 026"
    )
    add_statement(
        env,
        "2024-511",
        "511",
        "PLACEHOLDER EDUCATION CO (00 649 711 026)",
        f"00649711026, {WATTLE_ABN}",
        page,
        included_text=f"x ({spaced(WATTLE_ABN)})",
    )
    assert msr.main(["--no-fetch"]) == 0
    s = _summary(env)
    assert s["counts"]["abn_placeholders_read_as_no_abn"] == 1
    (ph,) = s["abn_placeholders_read_as_no_abn"]
    assert ph["statement_id"] == "2024-511" and ph["value"] == "00649711026"
    keys = {e["group_key"] for e in env["written"][msr.EDGES_NAME]["rows"]}
    assert "MSR-511" in keys and "00649711026" not in keys


def test_main_exit_2_when_csv_lists_included_entities_but_page_has_none(env):
    add_statement(
        env,
        "2024-506",
        "506",
        KOOK_REP_TEXT,
        KOOK_ABN,
        statement_page([("KOOKABURRA LEARNING GROUP LIMITED", KOOK_ABN)]),
        included_text="Wattle Kids Pty Ltd",
    )
    assert msr.main(["--no-fetch"]) == 2
    assert env["written"] == {}


def test_main_exit_2_when_csv_and_page_disagree_on_included_abns(env):
    # The reliable count signal: ABNs in brackets in the CSV IncludedEntities field must equal
    # the included entity blocks that carry an ABN link on the page.
    add_statement(
        env,
        "2024-508",
        "508",
        KOOK_REP_TEXT,
        KOOK_ABN,
        statement_page([("KOOKABURRA LEARNING GROUP LIMITED", KOOK_ABN)], [("x", WATTLE_ABN)]),
        included_text=f"x ({spaced(WATTLE_ABN)}), y ({spaced(BANKSIA_ABN)})",
    )
    assert msr.main(["--no-fetch"]) == 2
    assert env["written"] == {}


def test_main_complete_when_csv_and_page_agree(env):
    add_statement(
        env,
        "2024-509",
        "509",
        KOOK_REP_TEXT,
        KOOK_ABN,
        statement_page([("KOOKABURRA LEARNING GROUP LIMITED", KOOK_ABN)]),
    )
    assert msr.main(["--no-fetch"]) == 0


def test_main_exit_2_when_page_abn_differs_from_the_csv(env):
    # Equal counts, different identity: the round 4 count check passed this page.
    add_statement(
        env,
        "2024-512",
        "512",
        KOOK_REP_TEXT,
        KOOK_ABN,
        statement_page([("KOOKABURRA LEARNING GROUP LIMITED", KOOK_ABN)], [("x", WATTLE_ABN)]),
        included_text=f"x ({spaced(BANKSIA_ABN)})",
    )
    assert msr.main(["--no-fetch"]) == 2
    assert env["written"] == {}


def test_main_exit_2_when_page_omits_a_name_only_entity_the_csv_lists(env):
    add_statement(
        env,
        "2024-513",
        "513",
        KOOK_REP_TEXT,
        KOOK_ABN,
        statement_page([("KOOKABURRA LEARNING GROUP LIMITED", KOOK_ABN)], [("x", WATTLE_ABN)]),
        included_text=f"x ({spaced(WATTLE_ABN)}), Gumnut Care Pty Ltd",
    )
    assert msr.main(["--no-fetch"]) == 2
    assert env["written"] == {}


def test_main_exit_2_when_page_reporting_abn_differs_from_the_csv(env):
    add_statement(
        env,
        "2024-514",
        "514",
        f"KOOKABURRA LEARNING GROUP LIMITED ({spaced(OTHER_ABN)})",
        KOOK_ABN,
        statement_page([("KOOKABURRA LEARNING GROUP LIMITED", KOOK_ABN)]),
    )
    assert msr.main(["--no-fetch"]) == 2
    assert env["written"] == {}


def test_main_complete_when_page_matches_the_csv_exactly(env):
    add_statement(
        env,
        "2024-515",
        "515",
        KOOK_REP_TEXT,
        KOOK_ABN,
        statement_page(
            [("KOOKABURRA LEARNING GROUP LIMITED", KOOK_ABN)],
            [("Wattle Kids Pty Ltd", WATTLE_ABN), "Numbat College, Suburb"],
        ),
        included_text=f"WATTLE KIDS PTY LTD ({spaced(WATTLE_ABN)}), numbat college,  suburb",
    )
    assert msr.main(["--no-fetch"]) == 0


@pytest.mark.parametrize("change", ["missing", "renamed"])
def test_main_exit_2_on_a_bad_csv_header(env, change):
    snap = env["raw"] / "msr" / "all-statements" / "2026-01-01T0000Z.csv"
    rows = list(csv.DictReader(io.StringIO(snap.read_text(encoding="utf-8"))))
    if change == "missing":
        header = [h for h in CSV_HEADER if h != "IncludedEntities"]
    else:
        header = ["Entities" if h == "IncludedEntities" else h for h in CSV_HEADER]
        for r in rows:
            r["Entities"] = r.pop("IncludedEntities")
    snap.write_text(csv_text(rows, header), encoding="utf-8")
    assert msr.main(["--no-fetch"]) == 2
    assert env["written"] == {}


def test_main_exit_2_when_page_swaps_name_abn_pairs(env):
    add_statement(
        env,
        "2024-516",
        "516",
        KOOK_REP_TEXT,
        KOOK_ABN,
        statement_page(
            [("KOOKABURRA LEARNING GROUP LIMITED", KOOK_ABN)],
            [("Wattle Kids Pty Ltd", WATTLE_ABN), ("Banksia Early Years Pty Ltd", BANKSIA_ABN)],
        ),
        included_text=f"Wattle Kids Pty Ltd ({spaced(BANKSIA_ABN)}), "
        f"Banksia Early Years Pty Ltd ({spaced(WATTLE_ABN)})",
    )
    assert msr.main(["--no-fetch"]) == 2
    assert env["written"] == {}


def test_main_exit_2_when_page_omits_a_duplicated_name_only_entity(env):
    add_statement(
        env,
        "2024-517",
        "517",
        KOOK_REP_TEXT,
        KOOK_ABN,
        statement_page(
            [("KOOKABURRA LEARNING GROUP LIMITED", KOOK_ABN)],
            [("x", WATTLE_ABN), "Gumnut Care Pty Ltd"],
        ),
        included_text=f"x ({spaced(WATTLE_ABN)}), Gumnut Care Pty Ltd, Gumnut Care Pty Ltd",
    )
    assert msr.main(["--no-fetch"]) == 2
    assert env["written"] == {}


def _former_name_page():
    page = statement_page(
        [("KOOKABURRA LEARNING GROUP LIMITED", KOOK_ABN)], [("Wattle Kids Pty Ltd", WATTLE_ABN)]
    )
    return page.replace(
        'target="_blank">Wattle Kids Pty Ltd </a>',
        'target="_blank">Wattle Kids Pty Ltd (<small>Old Wattle Pty Ltd</small>)</a>',
    )


def test_main_former_name_page_reconciles_on_the_current_name(env):
    page = _former_name_page()
    assert "<small>Old Wattle Pty Ltd</small>" in page
    add_statement(
        env,
        "2024-518",
        "518",
        KOOK_REP_TEXT,
        KOOK_ABN,
        page,
        included_text=f"Wattle Kids Pty Ltd ({spaced(WATTLE_ABN)})",
    )
    assert msr.main(["--no-fetch"]) == 0


def test_main_exit_2_when_csv_lists_the_former_name_as_an_entry(env):
    add_statement(
        env,
        "2024-519",
        "519",
        KOOK_REP_TEXT,
        KOOK_ABN,
        _former_name_page(),
        included_text=f"Wattle Kids Pty Ltd ({spaced(WATTLE_ABN)}), Old Wattle Pty Ltd",
    )
    assert msr.main(["--no-fetch"]) == 2
    assert env["written"] == {}


def test_main_exit_2_when_a_snapshot_row_is_short(env):
    snap = env["raw"] / "msr" / "all-statements" / "2026-01-01T0000Z.csv"
    lines = snap.read_text(encoding="utf-8").splitlines()
    lines[-1] = lines[-1].rsplit(",", 1)[0]  # drop the trailing RelatedStatements field
    snap.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert msr.main(["--no-fetch"]) == 2
    assert env["written"] == {}


def test_main_exit_2_when_a_fetched_csv_row_is_short_and_nothing_is_stored(env, monkeypatch):
    from scrapers.common import Fetched

    good = _row_values(CSV_HEADER)
    body = _raw_csv(CSV_HEADER, [good, good[:-1]]).encode("utf-8")

    def fake_fetch(url, **kwargs):
        content = RESOURCES_HTML.encode("utf-8") if url == msr.RESOURCES_URL else body
        return Fetched(
            url=url,
            final_url=url,
            status=200,
            content=content,
            content_type="text/html",
            last_modified=None,
            etag=None,
            fetched_at="2026-10-31T01:00:00+00:00",
        )

    monkeypatch.setattr(msr, "fetch", fake_fetch)
    before = sorted((env["raw"] / "msr" / "all-statements").iterdir())
    assert msr.main([]) == 2
    assert sorted((env["raw"] / "msr" / "all-statements").iterdir()) == before
    assert env["written"] == {}


def test_main_exit_2_when_a_snapshot_has_a_duplicate_abn_column(env):
    snap = env["raw"] / "msr" / "all-statements" / "2026-01-01T0000Z.csv"
    rows = list(csv.reader(io.StringIO(snap.read_text(encoding="utf-8"))))
    rows = [rows[0] + ["ABN"]] + [r + [OTHER_ABN] for r in rows[1:]]
    snap.write_text(_raw_csv(rows[0], rows[1:]), encoding="utf-8")
    assert msr.main(["--no-fetch"]) == 2
    assert env["written"] == {} and not (env["proc"] / "summary.json").exists()


def test_main_exit_2_when_a_fetched_csv_has_a_duplicate_abn_column_and_nothing_is_stored(
    env, monkeypatch
):
    from scrapers.common import Fetched

    header = CSV_HEADER + ["ABN"]
    body = _raw_csv(header, [_row_values(CSV_HEADER) + [OTHER_ABN]]).encode("utf-8")

    def fake_fetch(url, **kwargs):
        content = RESOURCES_HTML.encode("utf-8") if url == msr.RESOURCES_URL else body
        return Fetched(
            url=url,
            final_url=url,
            status=200,
            content=content,
            content_type="text/csv",
            last_modified=None,
            etag=None,
            fetched_at="2026-10-31T01:00:00+00:00",
        )

    monkeypatch.setattr(msr, "fetch", fake_fetch)
    before = sorted((env["raw"] / "msr" / "all-statements").iterdir())
    assert msr.main([]) == 2
    assert sorted((env["raw"] / "msr" / "all-statements").iterdir()) == before
    assert env["written"] == {} and not (env["proc"] / "summary.json").exists()


def _serve(monkeypatch, resources_html, csv_body=b""):
    from scrapers.common import Fetched

    def fake_fetch(url, **kwargs):
        content = resources_html.encode("utf-8") if url == msr.RESOURCES_URL else csv_body
        return Fetched(
            url=url,
            final_url=url,
            status=200,
            content=content,
            content_type="text/csv",
            last_modified=None,
            etag=None,
            fetched_at="2026-10-31T01:00:00+00:00",
        )

    monkeypatch.setattr(msr, "fetch", fake_fetch)


def test_main_exit_2_without_fallback_when_resources_page_has_no_csv_link(env, monkeypatch):
    # Codex round 8: an online run never falls back to an older snapshot.
    _serve(monkeypatch, "<html><a href='/resources/other.pdf'>x</a></html>")
    before = sorted((env["raw"] / "msr" / "all-statements").iterdir())
    assert msr.main([]) == 2
    assert sorted((env["raw"] / "msr" / "all-statements").iterdir()) == before
    assert env["written"] == {} and not (env["proc"] / "summary.json").exists()


def test_main_exit_2_without_fallback_when_the_resources_fetch_fails(env, monkeypatch):
    def failing(url, **kwargs):
        raise RuntimeError("simulated network failure")

    monkeypatch.setattr(msr, "fetch", failing)
    before = sorted((env["raw"] / "msr" / "all-statements").iterdir())
    assert msr.main([]) == 2
    assert sorted((env["raw"] / "msr" / "all-statements").iterdir()) == before
    assert env["written"] == {} and not (env["proc"] / "summary.json").exists()


def test_main_exit_2_without_fallback_when_the_csv_fetch_fails(env, monkeypatch, caplog):
    # The resources page succeeds and links a CSV; only the CSV fetch fails, so this reaches the
    # CSV-fetch handler in acquire_csv.
    from scrapers.common import Fetched

    calls: list = []

    def fake_fetch(url, **kwargs):
        calls.append(url)
        if url == msr.RESOURCES_URL:
            return Fetched(
                url=url,
                final_url=url,
                status=200,
                content=RESOURCES_HTML.encode("utf-8"),
                content_type="text/html",
                last_modified=None,
                etag=None,
                fetched_at="2026-10-31T01:00:00+00:00",
            )
        raise RuntimeError("simulated CSV download failure")

    monkeypatch.setattr(msr, "fetch", fake_fetch)
    before = sorted((env["raw"] / "msr" / "all-statements").iterdir())
    assert msr.main([]) == 2
    assert calls == [
        msr.RESOURCES_URL,
        "https://modernslaveryregister.gov.au/resources/all-statement-information_2026-10-31.csv",
    ]
    assert "all-statements CSV not fetched" in caplog.text
    assert sorted((env["raw"] / "msr" / "all-statements").iterdir()) == before
    assert env["written"] == {} and not (env["proc"] / "summary.json").exists()


def test_main_online_stores_only_allowlisted_columns_and_counts_the_dropped(env, monkeypatch):
    snap = env["raw"] / "msr" / "all-statements" / "2026-01-01T0000Z.csv"
    rows = list(csv.reader(io.StringIO(snap.read_text(encoding="utf-8"))))
    rows = [rows[0] + ["Comments"]] + [r + ["UNKNOWN COLUMN SENTINEL"] for r in rows[1:]]
    _serve(monkeypatch, RESOURCES_HTML, _raw_csv(rows[0], rows[1:]).encode("utf-8"))
    assert msr.main([]) == 0
    stored = [
        p
        for p in (env["raw"] / "msr" / "all-statements").iterdir()
        if p.suffix == ".csv" and p != snap
    ]
    assert len(stored) == 1
    text = stored[0].read_text(encoding="utf-8")
    assert "SENTINEL" not in text and "Comments" not in text
    assert text.splitlines()[0].split(",") == CSV_HEADER
    s = _summary(env)
    assert s["counts"]["csv_columns_dropped"] == 1
    assert s["source"]["columns_dropped_for_privacy"] == ["Comments"]


@pytest.mark.parametrize("problem", ["missing_link", "narrow_header", "duplicate_header"])
def test_main_never_stores_a_fetched_csv_that_fails_validation(env, monkeypatch, problem):
    # Codex round 8: required columns, header width and duplicates are checked before storing.
    if problem == "missing_link":
        header = [h for h in CSV_HEADER if h != "Link"]
        body = _raw_csv(
            header,
            [[v for h, v in zip(CSV_HEADER, _row_values(CSV_HEADER), strict=True) if h != "Link"]],
        )
    elif problem == "narrow_header":
        body = _raw_csv(CSV_HEADER[:-1], [_row_values(CSV_HEADER)])
    else:
        body = _raw_csv(CSV_HEADER + ["Link"], [_row_values(CSV_HEADER) + ["x"]])
    _serve(monkeypatch, RESOURCES_HTML, body.encode("utf-8"))
    before = sorted((env["raw"] / "msr" / "all-statements").iterdir())
    assert msr.main([]) == 2
    assert sorted((env["raw"] / "msr" / "all-statements").iterdir()) == before
    assert env["written"] == {}


def test_main_exit_2_when_a_candidate_row_has_no_page_id(env):
    snap = env["raw"] / "msr" / "all-statements" / "2026-01-01T0000Z.csv"
    rows = list(csv.DictReader(io.StringIO(snap.read_text(encoding="utf-8"))))
    rows.append(csv_row("2024-510", "x510", "KOOKABURRA LEARNING GROUP LIMITED", KOOK_ABN))
    snap.write_text(csv_text(rows), encoding="utf-8")
    assert msr.main(["--no-fetch"]) == 2
    assert env["written"] == {}


@pytest.mark.parametrize("which", ["provider-profile.csv", "provider-abn.csv"])
def test_main_exit_2_on_duplicate_provider_rows(env, which):
    path = env["proc"] / which
    rows = list(csv.DictReader(io.StringIO(path.read_text(encoding="utf-8"))))
    fields = list(rows[0].keys())
    _write_csv(path, rows + [rows[1]], fields)
    assert msr.main(["--no-fetch"]) == 2
    assert env["written"] == {}


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
    assert "acecqa-services-latest.csv" in c["services_note"]
    assert all(g["services_of_controlled_providers"] is None for g in s["groups"])


def test_main_services_present_are_counted(env):
    assert msr.main(["--no-fetch"]) == 0
    c = _summary(env)["counts"]
    assert c["services_total"] == 1
    assert c["controlled_entity_of"]["services_of_those_providers"] == 1
    assert c["services_note"] is None


def test_provenance_lists_abr_details_and_services_inputs(env):
    assert msr.main(["--no-fetch"]) == 0
    for name in (msr.EDGES_NAME, msr.HEADS_NAME, msr.COREPORTED_NAME, msr.REVIEW_NAME):
        inputs = {p.name for p in env["written"][name]["raw_inputs"]}
        assert {"abn-details.csv", "acecqa-services-latest.csv", "provider-abn.csv"} <= inputs


def _fake_fetch(calls):
    from scrapers.common import Fetched

    def fake(url, **kwargs):
        calls.append(url)
        page = statement_page([("KOOKABURRA LEARNING GROUP LIMITED", KOOK_ABN)])
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
    assert len(snaps) == 2 and old in snaps and old.read_bytes() == old_bytes
    assert path != old and path in snaps


def test_without_refresh_an_existing_snapshot_is_reused(env, monkeypatch):
    calls: list = []
    monkeypatch.setattr(msr, "fetch", _fake_fetch(calls))
    s = {"page_id": "501", "statement_url": "https://modernslaveryregister.gov.au/statements/501/"}
    path, _ = msr.acquire_page(s, False, [0.0])
    assert calls == [] and path.name == "2026-01-01T0000Z.html"


def test_failed_refresh_exits_2_and_writes_nothing(env, monkeypatch):
    snap = env["raw"] / "msr" / "all-statements" / "2026-01-01T0000Z.csv"
    monkeypatch.setattr(msr, "acquire_csv", lambda no_fetch: (snap, {}))
    monkeypatch.setattr(msr, "PAGE_DELAY_SECONDS", 0.0)

    def failing_fetch(url, **kwargs):
        raise RuntimeError("simulated network failure")

    monkeypatch.setattr(msr, "fetch", failing_fetch)
    assert msr.main(["--refresh"]) == 2
    assert env["written"] == {} and not (env["proc"] / "summary.json").exists()


def test_failed_refresh_of_one_page_returns_no_snapshot(env, monkeypatch):
    def failing_fetch(url, **kwargs):
        raise RuntimeError("simulated network failure")

    monkeypatch.setattr(msr, "fetch", failing_fetch)
    monkeypatch.setattr(msr, "PAGE_DELAY_SECONDS", 0.0)
    s = {"page_id": "501", "statement_url": "https://modernslaveryregister.gov.au/statements/501/"}
    assert msr.acquire_page(s, False, [0.0], refresh=True) == (None, {})


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
