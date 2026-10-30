"""Tests for the Commonwealth CCS enforcement register parser. No network.

The fixture mirrors the markup of the real pages saved on 2026-10-29 (div.views-row, an h2 per
entry, dt/dd label and value pairs). All names in it are invented.
"""

import json
import re
from pathlib import Path

import httpx
from scrapers import parse_cth_ccs_enforcement as cth
from scrapers.common import record_hash
from scrapers.parse_cth_ccs_enforcement import (
    CURRENT_URL,
    PAST_URL,
    extract_legal_references,
    is_individual,
    map_action_type,
    parse_cth_date,
    parse_location,
    parse_page,
    split_abn,
)

SCHEMA = json.loads(
    (
        Path(__file__).resolve().parent.parent / "data/schemas/enforcement-action.schema.json"
    ).read_text()
)


def entry(service, provider, location, service_type, sanction, grounds, date, end=None):
    end_html = (
        f'<div class="views-field"><div class="field-content"><div class="foot-meta">'
        f"<dt>End date:</dt><dd><time>{end}</time></dd></div></div></div>"
        if end
        else ""
    )
    return f"""
<div class="views-row">
 <div class="views-field views-field-title"><h2 class="field-content">{service}</h2></div>
 <div class="views-field views-field-nothing"><span class="field-content"><dl>
  <div class="head-meta">
   <dt>Provider:</dt><dd>{provider}</dd>
   <dt>Location:</dt><dd>{location}</dd>
   <dt>Service type:</dt><dd>{service_type}</dd>
   <dt>Type of sanction:</dt><dd>{sanction}</dd>
  </div></dl></span></div>
 <div class="views-field views-field-body"><div class="field-content">
  <dt>Conditions of approval or grounds for sanction:</dt>
  <dd><p>{grounds}</p><p>Second paragraph.</p></dd></div></div>
 <div class="views-field views-field-field-eccc-date-of-effect"><div class="field-content">
  <div class="foot-meta"><dt>Date of effect:</dt><dd><time datetime="x">{date}</time></dd>
  </div></div></div>
 {end_html}
</div>"""


COMPANY = entry(
    "Riverbend Early Learning Centre",
    "Riverbend Kids Pty Ltd Atf The Riverbend Unit Trust – ABN: 11222333444",
    "Gayndah, queensland",
    "Centre Based Day Care",
    "Sanction under section 197H - Cancellation of Provider Approval",
    "Failed to meet Section 195H requirements.",
    "22 April 2025",
)
INDIVIDUAL = entry(
    "Zanzibar Family Day Care",
    "Ms Quinn Sampleby and Ms Olive Sampleby – ABN: 55666777888",
    "Meadow Heights, victoria",
    "Family Day Care",
    "Sanction under section 197L – Cancellation of Provider Approval",
    "Sampleby breached s 194C and section 195A. Cancelled under 197L.",
    "19 December 2024",
)
REPEAT = entry(
    "Harbour Street OSHC",
    "Harbour Street Services Inc",
    "Western Australia, WA",
    "Outside School Hours Care",
    "Conditions on approval under section 195F",
    "Must report monthly.",
    "1 July 2026",
    end="1 January 2027",
)

TOC = '<h2>On this page:</h2><ul><li><a href="#a">Riverbend</a></li></ul>'


def page(*entries):
    return (
        "<html><body><header><h2>Site menu</h2></header><main><h1>Enforcement action register</h1>"
        f"{TOC}{''.join(entries)}</main></body></html>"
    )


PAGE = page(COMPANY, INDIVIDUAL, REPEAT, REPEAT)


def rows(html=PAGE, role="current"):
    return parse_page(
        html,
        role=role,
        page_url=CURRENT_URL if role == "current" else PAST_URL,
        captured_at="2026-10-29T07:00:00+00:00",
        source_snapshot="x",
    )


def test_entries_split_and_toc_and_site_menu_ignored():
    r = rows()
    assert len(r) == 4
    assert [x["service_name"] for x in r] == [
        "Riverbend Early Learning Centre",
        "Zanzibar Family Day Care",
        "Harbour Street OSHC",
        "Harbour Street OSHC",
    ]


def test_company_row_abn_and_mapping():
    r = rows()[0]
    assert r["jurisdiction"] == "CTH"
    assert r["provider_name"] == "Riverbend Kids Pty Ltd Atf The Riverbend Unit Trust"
    assert r["notes"].startswith("ccs_identifier: ABN 11222333444")
    assert "service_type: Centre Based Day Care" in r["notes"]
    assert r["suburb"] == "Gayndah" and r["state"] == "QLD"
    assert r["action_type"] == "ccs_sanction"
    assert r["action_type_raw"] == "Sanction under section 197H - Cancellation of Provider Approval"
    assert r["reason"] == "Failed to meet Section 195H requirements. Second paragraph."
    assert r["legal_references"] == ["section 197H", "section 195H"]
    assert r["date_issued"] == "2025-04-22"
    assert r["date_issued_raw"] == "22 April 2025"
    assert r["period_label"] == "current"
    assert r["source_document"] == CURRENT_URL
    assert r["service_approval_number"] is None and r["provider_approval_number"] is None


def test_individual_provider_is_withheld_everywhere():
    r = rows()[1]
    assert r["provider_name"] is None
    assert "provider name withheld; subject is an individual" in r["notes"]
    assert "ccs_identifier" not in r["notes"] and "55666777888" not in json.dumps(r)
    assert "sampleby" not in json.dumps(r).lower()
    assert "quinn" not in json.dumps(r).lower()
    assert r["state"] == "VIC" and r["suburb"] == "Meadow Heights"
    # Codex round 1, finding 1: free text of a withheld row is withheld whole, not redacted.
    assert r["legal_references"] == []
    assert r["service_name"] == "Zanzibar Family Day Care"
    assert r["reason"] is None


def test_service_name_withheld_when_it_is_the_individuals_name():
    html = page(
        entry(
            "Sampleby Family Day Care",
            "Ms Quinn Sampleby",
            "Perth, WA",
            "Family Day Care",
            "Sanction under section 197L - Cancellation of Provider Approval",
            "Grounds.",
            "1 May 2025",
        )
    )
    r = rows(html)[0]
    assert r["service_name"] is None
    assert "service name withheld" in r["notes"]
    assert "sampleby" not in json.dumps(r).lower()


def test_repeated_service_kept_and_second_marked_duplicate():
    r = rows()
    assert r[2]["service_name"] == r[3]["service_name"] == "Harbour Street OSHC"
    # Codex round 1, finding 3: ids come from position and keys, so a repeat gets its own id;
    # the repeat is still found by its printed content and marked.
    assert r[2]["record_id"] != r[3]["record_id"]
    assert "duplicate row in source" not in r[2]["notes"]
    assert r[3]["notes"].endswith("; duplicate row in source")
    assert r[2]["state"] == "WA" and r[2]["suburb"] is None
    assert r[2]["action_type"] == "ccs_sanction"
    assert "end_date: 1 January 2027" in r[2]["notes"]
    assert r[2]["legal_references"] == ["section 195F"]


def test_record_id_no_longer_uses_a_withheld_placeholder():
    # Codex round 1, finding 3: the old id hashed "withheld" in place of the name, so different
    # individuals with the same action collided. The id now uses non-name facts only.
    r = rows()[1]
    old = record_hash(
        "CTH",
        "Zanzibar Family Day Care",
        "withheld",
        "Sanction under section 197L – Cancellation of Provider Approval",
        "19 December 2024",
    )
    assert r["record_id"] != old


def test_label_variants_strong_and_plain_text():
    html = """<html><body><main><h1>x</h1><h2>On this page:</h2>
    <h2>Strong Svc</h2>
    <p><strong>Provider:</strong> Alpha Pty Ltd – ABN: 12 345 678 901</p>
    <p><b>Location:</b> Hobart, Tas</p>
    <p>Type of sanction: Conditions on approval under section 195F</p>
    <p>Date of effect: 5 March 2026</p>
    </main></body></html>"""
    r = rows(html)
    assert len(r) == 1
    assert r[0]["provider_name"] == "Alpha Pty Ltd"
    assert "ccs_identifier: ABN 12345678901" in r[0]["notes"]
    assert r[0]["state"] == "TAS" and r[0]["suburb"] == "Hobart"
    assert r[0]["date_issued"] == "2026-03-05"


def test_split_abn_variants():
    assert split_abn("Acme Pty Ltd – ABN: 11222333444")[:2] == ("Acme Pty Ltd", "11222333444")
    assert split_abn("Acme Pty Ltd - ABN: ABN: 11222333444")[:2] == ("Acme Pty Ltd", "11222333444")
    assert split_abn("Acme Pty Ltd - ABN:11222333444")[:2] == ("Acme Pty Ltd", "11222333444")
    assert split_abn("Acme Pty Ltd") == ("Acme Pty Ltd", None, None)
    assert split_abn("Acme Pty Ltd - ABN: 123")[1] is None


def test_is_individual():
    assert is_individual("Ms Yara Example and Ms Nina Example")
    assert is_individual("Partnership Of Ann Example and Bob Example")
    assert is_individual("Pat Example")
    assert is_individual("L.V Example & N Sample")
    assert is_individual("Pat Example, Sunny Family Day Care")
    assert is_individual("Pat Example, Sunny FDC")
    assert not is_individual("Sunny Family Day Care Pty Ltd")
    assert not is_individual("Grans & Co Pty Ltd")
    assert not is_individual("Lockhart Shire Council")
    assert not is_individual("Department for Education")
    assert not is_individual("Kaleen Cubbyhouse Association Incorporated")


def test_state_normalisation_and_locations():
    assert parse_location("Gayndah, queensland")["state"] == "QLD"
    assert parse_location("Cairns, New South Wales")["state"] == "NSW"
    assert parse_location("Hobart, Tas")["state"] == "TAS"
    assert parse_location("Victoria, VIC") == {
        "address": None,
        "suburb": None,
        "state": "VIC",
        "postcode": None,
    }
    assert parse_location("Australian Capital Territory, ACT")["suburb"] is None
    assert parse_location("Not specified , WA")["suburb"] is None
    assert parse_location("Victoria")["state"] == "VIC"
    odd = parse_location("Carlingford")
    assert odd["suburb"] == "Carlingford" and odd["state"] is None
    assert parse_location("Somewhere, Nowhere")["address"] == "Somewhere, Nowhere"


def test_date_parsing():
    assert parse_cth_date("22 April 2025") == "2025-04-22"
    assert parse_cth_date("5 October 2026") == "2026-10-05"
    assert parse_cth_date("October 2026") is None
    assert parse_cth_date("") is None


def test_section_extraction():
    text = "Section 195H, s 194C and sections 195A; also 197L - of the Act. Act of 1999."
    assert extract_legal_references(text) == [
        "section 195H",
        "section 194C",
        "section 195A",
        "section 197L",
    ]
    assert extract_legal_references(None, "") == []


def test_action_type_mapping():
    m = lambda s: map_action_type(s)[0]  # noqa: E731
    assert m("Sanction under section 197H - Cancellation of Provider Approval") == "ccs_sanction"
    assert m("Sanction under section 197AB - Suspension of Service Approval") == "ccs_sanction"
    assert m("Sanction under section 197L - Variation to Provider Approval") == "ccs_sanction"
    assert m("Conditions on approval under section 195F") == "ccs_sanction"
    assert m("Civil penalty order") == "ccs_sanction"
    assert m("Infringement notice") == "infringement_notice"
    assert m("Conviction (Criminal Code)") == "prosecution"
    assert m("Without Conviction") == "prosecution"
    assert map_action_type("Without Conviction")[1] is not None
    assert m("Suspension lifted") == "other"
    assert m("Something else entirely") == "other"


def test_conviction_row_keeps_case_facts_and_null_date():
    html = """<html><body><main><h2>On this page:</h2><h2>Example FDC</h2>
    <div class="views-row"><dl><dt>Provider:</dt><dd>Pat Example</dd>
    <dt>Location:</dt><dd>Victoria, VIC</dd><dt>Service type:</dt><dd>Family Day Care</dd>
    <dt>Type of sanction:</dt><dd>Conviction (Criminal Code)</dd>
    <dt>Charge:</dt><dd>Criminal Code - 135.1(3)</dd><dt>Plea:</dt><dd>Guilty</dd>
    <dt>Date charged:</dt><dd>4 September 2023</dd>
    <dt>Date of sentence:</dt><dd>3 March 2025</dd></dl></div></main></body></html>"""
    r = rows(html)[0]
    assert r["action_type"] == "prosecution"
    assert r["date_issued"] is None and r["date_issued_raw"] is None
    assert r["provider_name"] is None
    # Codex round 1, finding 1: the subject is withheld, so case text (charge, plea, sentence
    # date) is withheld whole with the rest of the free text.
    assert r["notes"].endswith("free text withheld: subject may be an individual")
    assert "charge" not in r["notes"] and "Criminal Code" not in r["notes"]
    # Codex round 2, finding 4: the printed dates survive as structured, source-faithful columns.
    assert r["date_of_sentence"] == "2025-03-03"
    assert r["date_charged"] == "2023-09-04"
    assert r["end_date"] is None
    assert r["plea"] == "Guilty"
    assert r["service_type"] == "Family Day Care"


def test_past_role_label():
    r = rows(PAGE, role="past")
    assert {x["period_label"] for x in r} == {"past"}
    assert r[0]["source_document"] == PAST_URL


def test_no_entries_means_no_rows():
    assert rows("<html><body><main><h1>x</h1><h2>On this page:</h2></main></body></html>") == []


def test_rows_conform_to_schema():
    props = SCHEMA["properties"]
    r = rows()
    for row in r:
        for key in SCHEMA["required"]:
            assert row.get(key) not in (None, ""), key
        assert row["jurisdiction"] == "CTH"
        assert row["action_type"] in props["action_type"]["enum"]
        assert isinstance(row["legal_references"], list)
        for key in ("service_approval_number", "provider_approval_number"):
            if row[key] is not None:
                assert re.search(props[key]["pattern"], row[key])
        if row["date_issued"] is not None:
            assert re.search(props["date_issued"]["pattern"], row["date_issued"])


def test_main_returns_2_when_site_unreachable(monkeypatch):
    def boom(url, **kwargs):
        raise httpx.ConnectError("unreachable")

    monkeypatch.setattr(cth, "fetch", boom)
    assert cth.main([]) == 2


def test_is_individual_applies_the_shared_fail_closed_rule():
    assert is_individual("Example Holdings Pty Ltd ATF Jane Example Unit Trust")
    assert is_individual("Jane Example ATF Example Unit Trust")
    assert not is_individual("Example Holdings Pty Ltd ATF Sunrise Unit Trust")
    # Codex round 2, finding 2: a family trust names a family, so it is withheld.
    assert is_individual("Example Holdings Pty Ltd ATF Smith Family Trust")


# --- Codex round 1: withheld rows keep no free text, keep keys, ids ignore names -------------

from scrapers.common import FREE_TEXT_WITHHELD_NOTE  # noqa: E402


def test_withheld_cth_row_keeps_no_free_text():
    r = rows()[1]
    assert r["provider_name"] is None
    assert r["reason"] is None and r["action_type_raw"] == "(withheld)"
    assert r["legal_references"] == []
    assert FREE_TEXT_WITHHELD_NOTE in r["notes"]
    assert "sampleby" not in json.dumps(r).lower() and "quinn" not in json.dumps(r).lower()
    assert r["state"] == "VIC" and r["suburb"] == "Meadow Heights"


def test_withheld_cth_row_keeps_printed_keys():
    html = page(
        entry(
            "Example Family Day Care SE-40001234",
            "Ms Jane Example PR-40005678 - ABN: 55666777888",
            "Perth, WA",
            "Family Day Care",
            "Sanction under section 197L - Cancellation of Provider Approval",
            "Jane Example breached s 194C.",
            "1 May 2025",
        )
    )
    r = rows(html)[0]
    assert r["provider_name"] is None
    assert r["service_approval_number"] == "SE-40001234"
    assert r["provider_approval_number"] == "PR-40005678"


def test_cth_record_ids_survive_reordering_and_are_unique():
    a = rows(page(COMPANY, INDIVIDUAL, REPEAT, REPEAT))
    b = rows(page(INDIVIDUAL, REPEAT, COMPANY, REPEAT))
    key = lambda r: (r["service_name"], r["date_issued_raw"])  # noqa: E731
    assert sorted(map(key, a)) == sorted(map(key, b))
    assert {r["record_id"] for r in a} == {r["record_id"] for r in b}
    assert {key(r): r["record_id"] for r in a if key(r)[0] != "Harbour Street OSHC"} == {
        key(r): r["record_id"] for r in b if key(r)[0] != "Harbour Street OSHC"
    }
    assert len({r["record_id"] for r in a}) == len(a)


def test_two_withheld_individuals_with_the_same_action_are_not_duplicates():
    one = entry(
        "Alpha Family Day Care",
        "Ms Jane Example",
        "Perth, WA",
        "Family Day Care",
        "Sanction under section 197L - Cancellation of Provider Approval",
        "Grounds.",
        "1 May 2025",
    )
    two = one.replace("Ms Jane Example", "Ms Mary Sample")
    r = rows(page(one, two))
    assert len({x["record_id"] for x in r}) == 2
    assert all("duplicate row in source" not in (x["notes"] or "") for x in r)


# Codex round 2, finding 4: structured facts printed in labelled fields are kept as columns,
# never inferred, and survive the free-text withholding.


def test_structured_dates_on_organisation_row():
    r = rows(page(REPEAT))[0]
    assert r["end_date"] == "2027-01-01"
    assert r["date_charged"] is None and r["date_of_sentence"] is None
    assert r["plea"] is None
    assert r["service_type"] == "Outside School Hours Care"


def test_structured_dates_null_when_not_printed():
    r = rows(page(COMPANY))[0]
    for key in ("end_date", "date_charged", "date_of_sentence", "plea"):
        assert r[key] is None, key
    assert r["service_type"] == "Centre Based Day Care"


def test_structured_date_unparsable_is_null_not_inferred():
    r = rows(
        page(
            entry(
                "A OSHC",
                "A Services Inc",
                "Perth, WA",
                "Outside School Hours Care",
                "Conditions on approval under section 195F",
                "x",
                "1 July 2026",
                end="early 2027",
            )
        )
    )[0]
    assert r["end_date"] is None
    assert "end date printed but not parsable" in r["notes"]


def test_service_type_and_plea_outside_vocabulary_are_null():
    html = """<html><body><main><h2>On this page:</h2><h2>Example FDC</h2>
    <div class="views-row"><dl><dt>Provider:</dt><dd>Jane Example</dd>
    <dt>Location:</dt><dd>Victoria, VIC</dd><dt>Service type:</dt><dd>Run by Jane Example</dd>
    <dt>Type of sanction:</dt><dd>Conviction (Criminal Code)</dd>
    <dt>Plea:</dt><dd>Entered by Jane Example</dd></dl></div></main></body></html>"""
    r = rows(html)[0]
    assert r["service_type"] is None and r["plea"] is None
    assert "Jane" not in json.dumps(r)


def test_structured_columns_in_fieldnames_and_schema():
    props = SCHEMA["properties"]
    for key in ("service_type", "end_date", "date_charged", "date_of_sentence", "plea"):
        assert key in cth.FIELDNAMES
        assert key in props
    for key in ("end_date", "date_charged", "date_of_sentence"):
        assert props[key]["pattern"] == props["date_issued"]["pattern"]
