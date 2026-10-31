"""Tests for the Queensland enforcement register parser. No network."""

import json
import re
from pathlib import Path

from scrapers.parse_qld_enforcement import (
    INDEX_URL,
    INDIVIDUAL_NOTE,
    NO_APPROVAL_NOTE,
    map_action_type,
    parse_date,
    parse_register,
)

SCHEMA = json.loads(
    (
        Path(__file__).resolve().parent.parent / "data/schemas/enforcement-action.schema.json"
    ).read_text()
)

HEADER = (
    "<tr><th><p>Provider or individual name</p><p>Service name</p></th>"
    "<th>Date of action</th><th>Details</th><th>Breaches (if applicable)</th></tr>"
)

FIXTURE = f"""
<html><body>
<h2>2026</h2>
<table>{HEADER}
<tr><td>​​Inspired Kids Family Day Care Pty Ltd</td><td>​25/9/2026</td>
  <td><a href="/ececRegulation/Documents/cancellation-inspired-kids.pdf">Cancellation of provider approval</a></td>
  <td>N/A​</td></tr>
<tr><td><p>Janet Olive Sample</p><p>Kidspace Caloundra</p></td><td>22/09/2026</td>
  <td><p>Approved provider fined $8,000 for missing child</p>
   <p><a href="/ececRegulation/Documents/prosecution-janet-olive-sample.pdf">Prosecution</a><br/>
   <a href="/sector-news/approved-provider-fined">Further information</a></p></td>
  <td><p>NL s.165\u2014Offence relating to inadequately supervise children</p>
      <p>NR r.99\u2014Children leaving the education and care premises</p></td></tr>
<tr><td><p>East Coast Early Learning Pty Ltd</p><p>Natural Elements Early Learning Centre</p></td>
  <td>0​4/09/2026</td>
  <td><p>Approved provider fined $12,000 for missing child</p>
   <p><a href="/docs/prosecution-east-coast.docx">Prosecution</a><br/>
   <a href="/docs/prosecution-east-coast.pdf">Prosecution</a><br/>
   <a href="/news/east-coast-fined">Further information</a></p></td>
  <td><p>NL s.165\u2014Offence relating to inadequately supervise children</p></td></tr>
<tr><td>Rina Sampleton</td><td>07/09/2026</td>
  <td><a href="/docs/cancellation-rina-sampleton.pdf">Cancellation of provider approval</a></td><td>N/A</td></tr>
<tr><td>Nova Star Childcare Pty Ltd</td><td>17/04/2026</td>
  <td><a href="/docs/nova.pdf">Suspension of service approval\u2014lifted</a></td><td>N/A</td></tr>
</table>
<h2>2024</h2>
<table>{HEADER}
<tr><td>Oakhaul Pty Ltd</td><td>14/02/24</td><td><p>Approved provider was fined $23,000</p>
  <p><a href="/docs/oakhaul.pdf">Prosecution</a></p></td><td>8 breaches</td></tr>
<tr><td>G8 Education Limited</td><td>09/09/2024</td>
  <td><a href="/docs/g8.pdf">Enforceable undertaking\u2014discharged</a></td><td>N/A</td></tr>
</table>
<h2>2022</h2>
<table>{HEADER}
<tr><td>Frogtastic Educational Kindergarten and Childcare</td><td>02/06/2022</td>
  <td><a href="/docs/frog.docx">Cancellation of service approval</a></td><td>N/A</td></tr>
<tr><td>Educator\u2014centre-based service</td><td>23/12/2022</td>
  <td><a href="/docs/eu-educator.pdf">Enforceable undertaking</a></td>
  <td><p>NL s.166\u2014Offence to use inappropriate discipline</p></td></tr>
<tr><td><p>Farah Testerly</p><p>Testerly Family Day Care</p></td><td>04/11/2022</td>
  <td><a href="/docs/farah-testerly-cancellation.pdf">Cancellation of provider approval</a></td>
  <td>N/A</td></tr>
<tr><td>Dan and Kim Mockford</td><td>24/01/2022</td>
  <td><a href="/docs/mockford.pdf">Compliance notice</a></td><td>N/A</td></tr>
</table>
<table><tr><th>Unrelated</th></tr><tr><td>ignore me</td></tr></table>
</body></html>
"""


def rows():
    return parse_register(
        FIXTURE, page_url=INDEX_URL, captured_at="2026-10-29T07:00:00+00:00", source_snapshot="x"
    )


def by_date(raw):
    return next(r for r in rows() if r["date_issued_raw"] == raw)


def test_row_count_and_unrelated_table_ignored():
    assert len(rows()) == 11


def test_entity_row_with_zero_width_characters():
    r = by_date("25/9/2026")
    assert r["provider_name"] == "Inspired Kids Family Day Care Pty Ltd"
    assert r["service_name"] is None
    assert r["action_type"] == "approval_cancelled"
    assert r["date_issued"] == "2026-09-25"
    assert r["period_label"] == "2026"
    assert r["legal_references"] == []
    assert r["source_document"] == (
        "https://earlychildhood.qld.gov.au/ececRegulation/Documents/cancellation-inspired-kids.pdf"
    )


def test_approval_numbers_are_null_and_noted():
    for r in rows():
        assert r["service_approval_number"] is None
        assert r["provider_approval_number"] is None
        assert NO_APPROVAL_NOTE in r["notes"]


def test_zero_width_character_inside_date_is_removed():
    r = by_date("04/09/2026")
    assert r["date_issued"] == "2026-09-04"


def test_prosecution_and_legal_references_and_prefers_pdf():
    r = by_date("04/09/2026")
    assert r["action_type"] == "prosecution"
    assert r["action_type_raw"].startswith("Approved provider fined $12,000 for missing child")
    assert r["reason"] == "Approved provider fined $12,000 for missing child"
    assert r["source_document"].endswith("prosecution-east-coast.pdf")
    assert "prosecution-east-coast.docx" in r["linked_documents"]
    assert r["legal_references"] == [
        "NL s.165\u2014Offence relating to inadequately supervise children"
    ]


def test_named_individual_is_withheld_everywhere():
    r = by_date("22/09/2026")
    assert r["provider_name"] is None
    assert r["service_name"] == "Kidspace Caloundra"
    assert INDIVIDUAL_NOTE in r["notes"]
    assert r["source_document"] == INDEX_URL
    assert r["linked_documents"] is None
    assert r["action_type"] == "prosecution"
    # Codex round 1, finding 1: free text of a withheld row is withheld whole.
    assert r["legal_references"] == []
    blob = json.dumps(r).lower()
    assert "sample" not in blob and "janet" not in blob


def test_sole_trader_without_marker_is_individual():
    r = by_date("07/09/2026")
    assert r["provider_name"] is None
    assert INDIVIDUAL_NOTE in r["notes"]
    assert "sampleton" not in json.dumps(r).lower()


def test_service_name_repeating_the_individuals_name_is_withheld():
    r = by_date("04/11/2022")
    assert r["provider_name"] is None
    assert r["service_name"] is None
    assert "service name withheld" in r["notes"]
    assert "testerly" not in json.dumps(r).lower()


def test_two_named_individuals():
    r = by_date("24/01/2022")
    assert r["provider_name"] is None
    assert INDIVIDUAL_NOTE in r["notes"]
    assert "mockford" not in json.dumps(r).lower()
    assert r["action_type"] == "compliance_notice"


def test_generic_role_row_keeps_no_name_and_notes_it():
    r = by_date("23/12/2022")
    assert r["provider_name"] is None
    assert INDIVIDUAL_NOTE in r["notes"]
    assert "generic role" in r["notes"]
    assert r["action_type"] == "enforceable_undertaking"


def test_single_business_name_is_service_only():
    r = by_date("02/06/2022")
    assert r["provider_name"] is None
    assert r["service_name"] == "Frogtastic Educational Kindergarten and Childcare"
    assert INDIVIDUAL_NOTE not in r["notes"]


def test_ended_actions_are_not_mapped_to_new_actions():
    lifted = by_date("17/04/2026")
    assert lifted["action_type"] == "other"
    assert lifted["action_type_raw"] == "Suspension of service approval\u2014lifted"
    discharged = by_date("09/09/2024")
    assert discharged["action_type"] == "other"


def test_two_digit_year_and_free_text_breaches():
    r = by_date("14/02/24")
    assert r["date_issued"] == "2024-02-14"
    assert "two-digit year" in r["notes"]
    assert r["legal_references"] == []
    assert "8 breaches" in r["notes"]


def test_map_action_type_is_conservative():
    assert map_action_type("Fined $500", prosecution_label=False)[0] == "other"
    assert map_action_type("Infringement notice issued", prosecution_label=False)[0] == (
        "infringement_notice"
    )
    assert map_action_type("Anything", prosecution_label=True)[0] == "prosecution"
    assert map_action_type("Something new", prosecution_label=False)[0] == "other"


def test_parse_date():
    assert parse_date("25/9/2026")[0] == "2026-09-25"
    assert parse_date("31/02/2026")[0] is None
    assert parse_date("September 2026")[0] is None


def test_record_ids_are_stable_and_unique():
    a, b = rows(), rows()
    assert [r["record_id"] for r in a] == [r["record_id"] for r in b]
    assert len({r["record_id"] for r in a}) == len(a)


def test_rows_conform_to_schema():
    props = SCHEMA["properties"]
    for r in rows():
        for key in SCHEMA["required"]:
            assert r.get(key) not in (None, ""), key
        assert r["jurisdiction"] == "QLD"
        assert r["action_type"] in props["action_type"]["enum"]
        for key in ("source_register", "source_document", "date_issued"):
            pattern = props[key].get("pattern")
            if pattern and r[key] is not None:
                assert re.search(pattern, r[key]), (key, r[key])
        assert isinstance(r["legal_references"], list)


def test_location_columns_stay_null_because_the_register_prints_no_location():
    """The register's four columns carry no suburb, state or address (checked against the
    2026-10-29 snapshot). A trailing place name in a service name (for example 'Kidspace
    Caloundra') is part of the service name, not a printed location, so it is not split off."""
    rows = parse_register(FIXTURE)
    assert rows
    for row in rows:
        assert row["suburb"] is None
        assert row["state"] is None
        assert row["address"] is None
        assert row["postcode"] is None
    named = [r for r in rows if r["service_name"] and "Natural Elements" in r["service_name"]]
    assert named[0]["service_name"] == "Natural Elements Early Learning Centre"


def test_location_is_populated_only_when_the_register_prints_it():
    html = f"""<html><body><h2>2026</h2><table>{HEADER}
    <tr><td><p>Example Learning Pty Ltd</p><p>Example Learning Centre</p></td><td>01/02/2026</td>
    <td><a href="/docs/example.pdf">Suspension of service approval</a></td><td>N/A</td></tr>
    </table></body></html>"""
    (row,) = parse_register(html)
    assert (row["suburb"], row["state"], row["address"]) == (None, None, None)


# ---------------------------------------------------------------------------
# A withheld subject's name must not survive in any text column. Names are synthetic.
# ---------------------------------------------------------------------------

PRIVACY_FIXTURE = f"""
<html><body>
<h2>2026</h2>
<table>{HEADER}
<tr><td>Jane Example</td><td>01/02/2026</td>
  <td><p>Jane Example fined $5,000 for missing child</p>
   <p><a href="/docs/prosecution-jane-example.pdf">Prosecution</a><br/>
   <a href="/docs/jane-example-notice.pdf">Notice to Jane Example</a></p></td>
  <td><p>NL s.165 Offence by Jane Example</p></td></tr>
<tr><td>Jane Example</td><td>02/02/2026</td>
  <td><a href="/docs/x.pdf">Compliance notice issued to Jane Example</a></td>
  <td>Breach admitted by Jane Example</td></tr>
<tr><td><p>Jane Example ATF Example Family Trust</p><p>Sunny Days Early Learning</p></td>
  <td>03/02/2026</td>
  <td><a href="/docs/y.pdf">Compliance notice</a></td><td>N/A</td></tr>
<tr><td>Zoë Exämple</td><td>04/02/2026</td>
  <td><p>Zoë Exämple fined $2,000</p><p><a href="/docs/z.pdf">Prosecution</a></p></td>
  <td>N/A</td></tr>
<tr><td>Jane Example - executor of the estate of John Example</td><td>05/02/2026</td>
  <td><a href="/docs/w.pdf">Compliance notice</a></td><td>N/A</td></tr>
<tr><td><p>Example Holdings Pty Ltd ATF Sunrise Unit Trust</p><p>Sunny Days</p></td>
  <td>06/02/2026</td>
  <td><a href="/docs/v.pdf">Compliance notice</a></td><td>N/A</td></tr>
</table>
</body></html>
"""


def privacy_rows():
    return {
        r["date_issued_raw"]: r
        for r in parse_register(
            PRIVACY_FIXTURE,
            page_url=INDEX_URL,
            captured_at="2026-10-29T07:00:00+00:00",
            source_snapshot="x",
        )
    }


def _text_blob(row):
    return json.dumps(row, ensure_ascii=False).lower()


def test_withheld_name_is_scrubbed_from_every_text_column():
    for date_raw in ("01/02/2026", "02/02/2026"):
        r = privacy_rows()[date_raw]
        assert r["provider_name"] is None
        assert INDIVIDUAL_NOTE in r["notes"]
        blob = _text_blob(r)
        assert "jane" not in blob and "example" not in blob, date_raw
    r = privacy_rows()["01/02/2026"]
    assert r["action_type"] == "prosecution"
    assert r["legal_references"] == []  # withheld whole (Codex round 1, finding 1)


def test_individual_trustee_is_withheld():
    r = privacy_rows()["03/02/2026"]
    assert r["provider_name"] is None
    assert INDIVIDUAL_NOTE in r["notes"]
    assert "jane" not in _text_blob(r)


def test_accented_individual_name_is_withheld_and_scrubbed():
    r = privacy_rows()["04/02/2026"]
    assert r["provider_name"] is None
    blob = _text_blob(r)
    assert "zoë" not in blob and "exämple" not in blob


def test_estate_or_executor_subject_is_withheld():
    r = privacy_rows()["05/02/2026"]
    assert r["provider_name"] is None
    blob = _text_blob(r)
    assert "jane" not in blob and "john" not in blob


def test_organisation_trustee_is_still_shown():
    r = privacy_rows()["06/02/2026"]
    assert r["provider_name"] == "Example Holdings Pty Ltd ATF Sunrise Unit Trust"
    assert r["service_name"] == "Sunny Days"


def test_person_named_trust_with_company_trustee_is_withheld():
    # Shared fail-closed rule: a company trustee does not make a person-named trust shown.
    html = PRIVACY_FIXTURE.replace(
        "Example Holdings Pty Ltd ATF Sunrise Unit Trust",
        "Example Holdings Pty Ltd ATF Jane Example Unit Trust",
    )
    r = {
        x["date_issued_raw"]: x
        for x in parse_register(
            html, page_url=INDEX_URL, captured_at="2026-10-29T07:00:00+00:00", source_snapshot="x"
        )
    }["06/02/2026"]
    assert r["provider_name"] is None
    assert INDIVIDUAL_NOTE in r["notes"]
    assert "jane" not in _text_blob(r)


# --- Codex round 1: withheld rows keep no free text, keep keys, ids ignore names -------------

from scrapers.common import FREE_TEXT_WITHHELD_NOTE  # noqa: E402


def test_withheld_qld_row_keeps_no_free_text():
    r = privacy_rows()["01/02/2026"]
    assert r["provider_name"] is None
    assert r["reason"] is None and r["action_type_raw"] == "(withheld)"
    assert r["legal_references"] == [] and r["linked_documents"] is None
    assert FREE_TEXT_WITHHELD_NOTE in r["notes"]
    assert r["action_type"] == "prosecution" and r["date_issued"] == "2026-02-01"


def test_withheld_qld_row_keeps_structured_fields_and_keys_as_printed():
    # The QLD register prints no SE-/PR- numbers; withholding must not invent or drop any.
    r = privacy_rows()["06/02/2026"]
    assert r["service_approval_number"] is None and r["provider_approval_number"] is None
    assert r["period_label"] == "2026" and r["source_register"] == INDEX_URL


def test_qld_record_ids_survive_reordering_and_are_unique():
    kw = {"page_url": INDEX_URL, "captured_at": "2026-10-29T07:00:00+00:00", "source_snapshot": "x"}
    a = parse_register(FIXTURE, **kw)
    body = FIXTURE.split("<h2>2026</h2>")[1].split("</table>")[0]
    trs = re.findall(r"<tr><td>.*?</tr>", body, flags=re.S)
    swapped = FIXTURE.replace(trs[0], "@@0@@").replace(trs[1], trs[0]).replace("@@0@@", trs[1])
    b = parse_register(swapped, **kw)
    by_date = lambda rows: {r["date_issued_raw"]: r["record_id"] for r in rows}  # noqa: E731
    assert by_date(a) == by_date(b)
    assert len({r["record_id"] for r in a}) == len(a)


# --- Codex round 2, finding 4: a printed fine is kept as a structured column -----------------


def test_fine_amount_is_kept_as_a_structured_column():
    assert by_date("04/09/2026")["penalty_amount_aud"] == 12000


def test_fine_amount_survives_withholding():
    rows = privacy_rows()
    assert rows["01/02/2026"]["action_type_raw"] == "(withheld)"
    assert rows["01/02/2026"]["penalty_amount_aud"] == 5000
    assert rows["04/02/2026"]["penalty_amount_aud"] == 2000
    assert rows["02/02/2026"]["penalty_amount_aud"] is None


def test_fine_amount_is_null_when_not_one_printed_amount():
    from scrapers.parse_qld_enforcement import extract_fine_amount

    assert extract_fine_amount("Approved provider fined $14,500 for missing child") == 14500
    assert extract_fine_amount("Approved provider was fined $23,000") == 23000
    assert extract_fine_amount("Fined $8,000 and $2,000 in costs") is None
    assert extract_fine_amount("Compliance notice") is None
    assert extract_fine_amount(None) is None


def test_prose_naming_a_person_is_withheld_on_an_organisation_row():
    # Codex round 2, finding 1: the shared prose rule runs on every row, not only withheld ones.
    html = PRIVACY_FIXTURE.replace(
        '<a href="/docs/v.pdf">Compliance notice</a></td><td>N/A</td>',
        '<a href="/docs/v.pdf">Compliance notice</a></td><td>NL s.165 Offence by Jane Example</td>',
    )
    rows = {
        x["date_issued_raw"]: x
        for x in parse_register(
            html, page_url=INDEX_URL, captured_at="2026-10-29T07:00:00+00:00", source_snapshot="x"
        )
    }
    r = rows["06/02/2026"]
    assert r["provider_name"] is not None
    assert "free text withheld: may name an individual" in r["notes"]
    assert "jane" not in _text_blob(r)


# --- Codex round 5, finding 3: only an amount tied explicitly to the fine is recorded ---------


def test_costs_or_an_unclear_amount_is_not_recorded_as_the_fine():
    from scrapers.parse_qld_enforcement import FINE_NOT_RECORDED_NOTE, fine_amount_and_note

    for text in (
        "Approved provider fined and ordered to pay costs of $3,500",
        "Approved provider fined, plus $3,500 in costs",
        "Approved provider fined after a child left the service; $3,500 was ordered",
    ):
        assert fine_amount_and_note(text) == (None, FINE_NOT_RECORDED_NOTE), text


def test_an_amount_tied_explicitly_to_the_fine_is_recorded():
    from scrapers.parse_qld_enforcement import fine_amount_and_note

    assert fine_amount_and_note("Approved provider fined $12,000 for missing child") == (
        12000,
        None,
    )
    assert fine_amount_and_note("Approved provider was fined $23,000") == (23000, None)
    assert fine_amount_and_note("A fine of $5,000.50 was imposed") == (5000.5, None)
    assert fine_amount_and_note("Court imposes $7,500 penalty") == (7500, None)
    assert fine_amount_and_note("Compliance notice") == (None, None)
    assert fine_amount_and_note("Fined $8,000 and $2,000 in costs") == (
        None,
        "penalty amount not recorded: the printed amount is not tied explicitly and solely to the fine",
    )


def test_qld_row_with_costs_only_has_no_penalty_and_says_why():
    html = f"""<html><body><h2>2026</h2><table>{HEADER}
    <tr><td><p>Example Kids Pty Ltd</p><p>Sunny Meadow Early Learning</p></td><td>01/02/2026</td>
      <td><p>Approved provider fined and ordered to pay costs of $3,500</p>
       <p><a href="/docs/example-kids.pdf">Prosecution</a></p></td><td>N/A</td></tr>
    </table></body></html>"""
    row = parse_register(
        html, page_url=INDEX_URL, captured_at="2026-10-29T07:00:00+00:00", source_snapshot="x"
    )[0]
    assert row["penalty_amount_aud"] is None
    assert "penalty amount not recorded" in row["notes"]


# --- Codex round 5, finding 4: link targets are part of the QLD row's printed content --------


def _two_rows_same_text_different_links(first, second):
    row = (
        "<tr><td>Example Kids Pty Ltd</td><td>01/02/2026</td>"
        '<td><a href="{href}">Compliance notice</a></td><td>N/A</td></tr>'
    )
    html = (
        f"<html><body><h2>2026</h2><table>{HEADER}"
        + row.format(href=first)
        + row.format(href=second)
        + "</table></body></html>"
    )
    return parse_register(
        html, page_url=INDEX_URL, captured_at="2026-10-29T07:00:00+00:00", source_snapshot="x"
    )


def test_rows_with_identical_text_but_different_links_keep_stable_ids():
    a = _two_rows_same_text_different_links("/docs/notice-1.pdf", "/docs/notice-2.pdf")
    b = _two_rows_same_text_different_links("/docs/notice-2.pdf", "/docs/notice-1.pdf")
    ids_a = {r["source_document"]: r["record_id"] for r in a}
    ids_b = {r["source_document"]: r["record_id"] for r in b}
    assert len(set(ids_a.values())) == 2
    assert ids_a == ids_b  # each notice keeps its id when the order changes
    assert all("duplicate row" not in (r["notes"] or "") for r in a)
