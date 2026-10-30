"""Tests for Western Australia (WA ECRU) enforcement actions parser."""

from __future__ import annotations

from scrapers.common import record_hash
from scrapers.parse_wa_enforcement import (
    INDIVIDUAL_NOTE,
    extract_provider_info,
    extract_service_details,
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
    <td>Provider (provider number): Mara Sample (PR-00008204)</td>
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
    <td>Provider (provider number): Rae-Lee EXAMPLE (CS-00051586)</td>
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
    name, pr, cs, notes = extract_provider_info("Mara Sample (PR-00008204)")
    assert name is None  # Withheld
    assert pr == "PR-00008204"
    assert cs is None
    assert INDIVIDUAL_NOTE in notes


def test_extract_provider_info_certified_supervisor_withheld():
    name, pr, cs, notes = extract_provider_info("Rae-Lee EXAMPLE (CS-00051586)")
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


# --- name fields carrying address text or key fragments -------------------------

ZWSP = chr(0x200B)  # zero-width space, printed in some register cells


def test_provider_key_printed_without_brackets_is_removed_from_the_name():
    name, pr, _, notes = extract_provider_info("City of Kwinana PR-00014080")
    assert name == "City of Kwinana"
    assert pr == "PR-00014080"
    name, pr, _, _ = extract_provider_info("Extend (Australia) Pty Ltd PR- 00002530")
    assert name == "Extend (Australia) Pty Ltd"
    assert pr == "PR-00002530"
    name, _, _, _ = extract_provider_info("LA Anchor Pty Ltd PR-40016908.")
    assert name == "LA Anchor Pty Ltd"


def test_provider_key_printed_first_leaves_the_name_after_it():
    name, pr, _, _ = extract_provider_info("PR-40011786 EXAMPLE LADIES' COLLEGE LIMITED")
    assert name == "EXAMPLE LADIES' COLLEGE LIMITED"
    assert pr == "PR-40011786"
    # Codex round 1, finding 4: an institutional word alone is not organisation evidence, so the
    # name is withheld, but the key printed first is still read.
    name, pr, _, notes = extract_provider_info("PR-40011786 METHODIST LADIES' COLLEGE")
    assert name is None and pr == "PR-40011786"


def test_text_after_the_provider_key_is_removed_and_noted_without_repeating_it():
    name, pr, _, notes = extract_provider_info(
        "G8 Education Limited PR-00000898 PO Box 515 VARSITY LAKES QLD 4227"
    )
    assert name == "G8 Education Limited"
    assert pr == "PR-00000898"
    joined = "; ".join(notes)
    assert "removed from the provider name" in joined
    assert "PO Box" not in joined  # removed text is never copied into notes


def test_zero_width_characters_are_removed_from_names():
    name, pr, _, _ = extract_provider_info(
        f"{ZWSP}{ZWSP}BUTTERCUPS CHILDCARE PTY LTD{ZWSP} PR-40005790{ZWSP}"
    )
    assert name == "BUTTERCUPS CHILDCARE PTY LTD"
    assert pr == "PR-40005790"


def test_person_named_with_an_educator_role_is_withheld():
    # Rule 2. The role in brackets contains business words ('Family Day Care'), which made the
    # entity heuristic read the whole cell as an organisation.
    for cell in (
        "Mara Sample (Family Day Care Educator)",
        "Mara SAMPLE (FDC Educator)",
        "Mara Sample (Former Family Day Care Educator)",
    ):
        name, _, _, notes = extract_provider_info(cell)
        assert name is None, cell
        assert INDIVIDUAL_NOTE in notes


def test_person_with_an_unbracketed_key_is_still_withheld():
    name, pr, _, notes = extract_provider_info("Mara Sample PR-00008204")
    assert name is None
    assert pr == "PR-00008204"
    assert INDIVIDUAL_NOTE in notes


def test_service_key_and_address_are_split_out_of_the_service_name():
    d = extract_service_details(
        "Goodstart Early Learning Stratton SE-00012647 165 Talbot Road STRATTON WA 6056"
    )
    assert d["service_name"] == "Goodstart Early Learning Stratton"
    assert d["service_approval_number"] == "SE-00012647"
    assert d["address"] == "165 Talbot Road STRATTON WA 6056"
    assert d["suburb"] is None  # not derived from text moved out of the name
    assert any("separated from the service name" in n for n in d["notes"])


def test_street_address_without_a_key_is_split_out_of_the_service_name():
    d = extract_service_details("Meela Child Care Centre 116 West Parade, MT LAWLEY WA 6050")
    assert d["service_name"] == "Meela Child Care Centre"
    assert d["address"] == "116 West Parade, MT LAWLEY WA 6050"
    assert d["suburb"] == "MT LAWLEY WA"  # unchanged from the existing comma rule
    d = extract_service_details(
        "Camp Australia Cloverdale Primary School OSHC 180 Fisher Street Cloverdale"
    )
    assert d["service_name"] == "Camp Australia Cloverdale Primary School OSHC"
    assert d["address"] == "180 Fisher Street Cloverdale"
    d = extract_service_details("Little Nest Centre at 51 Example Drive")
    assert d["service_name"] == "Little Nest Centre"
    assert d["address"] == "51 Example Drive"


def test_unlabelled_number_in_brackets_is_removed_and_not_used_as_a_key():
    d = extract_service_details("Zebra Family Day Care (00014407)")
    assert d["service_name"] == "Zebra Family Day Care"
    assert d["service_approval_number"] is None  # SE or PR is not printed: never guessed
    assert any("00014407" in n and "not used as a key" in n for n in d["notes"])


def test_clean_service_names_are_unchanged():
    d = extract_service_details("Melville Day Care Centre, 39 Rome Road, Melville WA 6158")
    assert d["service_name"] == "Melville Day Care Centre"
    assert d["address"] == "39 Rome Road, Melville WA 6158"
    assert d["notes"] == []
    d = extract_service_details("Better Future Family Day Care WA")
    assert d["service_name"] == "Better Future Family Day Care WA"
    assert d["address"] is None


def test_record_id_is_stable_when_the_service_name_is_cleaned():
    contaminated = SAMPLE_TABLE_HTML.replace(
        "Melville Day Care Centre, 39 Rome Road, Melville WA 6158",
        "Melville Day Care Centre 39 Rome Road Melville",
    )
    after = parse_wa_html_table(contaminated, "s.html", "2026-10-29T08:00:00Z")[0]
    assert after["service_name"] == "Melville Day Care Centre"
    assert after["address"] == "39 Rome Road Melville"
    # record_id still hashes the name text as printed before the first comma, so ids already
    # used downstream do not change when the cleaned name does.
    assert after["record_id"] == record_hash(
        "WA",
        "Melville Day Care Centre 39 Rome Road Melville",
        "PR-00007392",
        "compliance_notice",
        "2013-09-16",
    )


def test_service_number_printed_in_the_provider_cell_is_removed_from_the_name():
    name, pr, _, notes = extract_provider_info("SPARROW GROUP WA PTY LTD SE-40013266")
    assert name == "SPARROW GROUP WA PTY LTD"
    assert pr is None  # an SE number is not a provider key and is never used as one
    assert any("service number printed in the provider cell" in n for n in notes)


def test_record_id_ignores_cleaning_of_zero_width_characters():
    d = extract_service_details(f"{ZWSP}Tall Tree Early Learning{ZWSP} SE-40017749 1 Example Way")
    assert d["service_name"] == "Tall Tree Early Learning"
    assert d["legacy_name"] == f"{ZWSP}Tall Tree Early Learning{ZWSP} SE-40017749 1 Example Way"


def test_person_named_trust_provider_is_withheld_by_shared_rule():
    # Shared fail-closed rule: a company trustee does not make a person-named trust shown.
    name, pr, _, notes = extract_provider_info(
        "Example Holdings Pty Ltd ATF Jane Example Unit Trust (PR-00008204)"
    )
    assert name is None
    assert pr == "PR-00008204"
    assert "Jane" not in " ".join(notes)
    kept, _, _, _ = extract_provider_info(
        "Example Holdings Pty Ltd ATF Smith Family Trust (PR-00008205)"
    )
    assert kept == "Example Holdings Pty Ltd ATF Smith Family Trust"
