"""Unit tests for the NSW enforcement register parser. Inline fixtures only, no network."""

import json

from scrapers.parse_nsw_enforcement import (
    DUPLICATE_NOTE,
    INDEX_URL,
    SOURCE,
    RawRecord,
    build_row,
    clean_text,
    date_in_period,
    discover_pdf_urls,
    extract_legal_references,
    map_action_type,
    mark_duplicates,
    parse_date,
    pdf_snapshots,
    period_label_from_slug,
    provider_name_if_entity,
    slug_from_url,
    snapshot_rel_path,
    split_address,
)

META = {
    "final_url": "https://education.nsw.gov.au/x/q4.pdf",
    "fetched_at": "2026-10-29T07:18:00+00:00",
}


def make_raw(**fields: str) -> RawRecord:
    raw = RawRecord(page=1)
    raw.fields.update(fields)
    return raw


def make_row(raw: RawRecord, label: str | None = "2024-25 Q4") -> dict:
    return build_row(
        raw, meta=META, snapshot_rel="data/raw/nsw-enforcement/x.pdf", period_label=label
    )


# --- dates ------------------------------------------------------------------


def test_parse_date_slash_format():
    assert parse_date("01/04/2025") == "2025-04-01"
    assert parse_date("4/07/2025") == "2025-07-04"
    assert parse_date(" 31/12/2025 ") == "2025-12-31"


def test_parse_date_day_month_name_format_seen_in_q3_2024_25():
    assert parse_date("15-Jan-25") == "2025-01-15"
    assert parse_date("28-Mar-2025") == "2025-03-28"


def test_parse_date_unparsable_is_none():
    assert parse_date("31/02/2025") is None  # impossible date
    assert parse_date("2025-04-01") is None  # not a printed NSW format; do not guess
    assert parse_date("April 2025") is None
    assert parse_date("") is None
    assert parse_date(None) is None


def test_unparsable_date_keeps_raw_and_adds_note():
    row = make_row(make_raw(id="SE-00008497", date="31/02/2025", nature="Compliance notice issued"))
    assert row["date_issued"] is None
    assert row["date_issued_raw"] == "31/02/2025"
    assert "could not be parsed" in row["notes"]


def test_date_in_period():
    assert date_in_period("2025-04-01", "2024-25 Q4")
    assert date_in_period("2025-07-04", "2025-26 Q1")
    assert date_in_period("2026-03-31", "2025-26 Q3")
    assert not date_in_period("2025-12-05", "2024-25 Q4")
    assert not date_in_period("2025-04-17", "2025-26 Q2")


def test_date_outside_period_is_noted_not_changed():
    row = make_row(
        make_raw(id="SE-00008118", date="5/12/2025", nature="Service Approval cancelled")
    )
    assert row["date_issued"] == "2025-12-05"
    assert "outside the register period" in row["notes"]


# --- action type ------------------------------------------------------------


def test_map_action_type_from_printed_nature():
    assert map_action_type("Compliance notice issued") == "compliance_notice"
    assert map_action_type("Emergency action notice issued") == "emergency_action_notice"
    assert map_action_type("Service Approval cancelled") == "approval_cancelled"
    assert map_action_type("Provider approval cancelled") == "approval_cancelled"
    assert map_action_type("Involuntary suspension") == "approval_suspended"
    assert (
        map_action_type("Enforceable undertaking issued to provider") == "enforceable_undertaking"
    )


def test_map_action_type_falls_back_to_details_when_no_nature():
    assert (
        map_action_type(None, "Issue of compliance notice under Section 177") == "compliance_notice"
    )
    assert (
        map_action_type(
            None, "Enter into an Enforceable undertaking with a person under Section 179A"
        )
        == "enforceable_undertaking"
    )
    assert (
        map_action_type(
            None, "Cancellation of provider approval in accordance with Section 33(1)(a)(i)"
        )
        == "approval_cancelled"
    )


def test_map_action_type_other_when_phrase_unknown():
    assert map_action_type("Letter of caution") == "other"
    assert map_action_type("Direction") == "other"  # bare 'direction' is not a schema category
    assert map_action_type(None, None) == "other"
    assert map_action_type("") == "other"


def test_map_action_type_covers_remaining_schema_phrases():
    assert map_action_type("Prosecution commenced") == "prosecution"
    assert map_action_type("Show cause notice") == "show_cause_notice"
    assert map_action_type("Prohibition notice") == "prohibition_notice"
    assert map_action_type("Amendment of service approval") == "approval_amended"
    assert map_action_type("Condition imposed on approval") == "condition_imposed"


def test_reason_text_is_never_used_to_choose_the_action_type():
    # Cancellation grounds mention "breach of a condition"; the printed action is the cancellation.
    row = make_row(
        make_raw(
            id="PR-00004108",
            name="Angel's Paradise Pty Ltd",
            date="8/09/2025",
            reason="the approved provider has breached a condition of the provider approval",
            details="Cancellation of provider approval in accordance with Section 31",
        )
    )
    assert row["action_type"] == "approval_cancelled"


# --- legal references -------------------------------------------------------


def test_extract_legal_references_from_reason_and_details():
    reason = (
        "Due to non-compliance with the National Law and/or National Regulations: "
        "Regulation 103 Premises, furniture and equipment to be safe, clean and in good repair "
        "Regulation 92 Medication record Law 167 Offence relating to protection of children from "
        "harm and hazards Regulation 84C Risk assessment for purposes of sleep and rest policies"
    )
    refs = extract_legal_references(reason, "Issue of compliance notice under section 177")
    assert refs == ["Regulation 103", "Regulation 92", "Law 167", "Regulation 84C", "section 177"]


def test_extract_legal_references_keeps_subsections_and_normalises_prefixes():
    refs = extract_legal_references(
        "Reg 102D Authorisation for service to transport children; Law 174(2)(c) Offence; "
        "Section 31 (f) of the National Law; S31(a); Regulation 97(3)",
        "Section 33 (1)(a)(i) of the National Law",
    )
    assert refs == [
        "Regulation 102D",
        "Law 174(2)(c)",
        "section 31(f)",
        "section 31(a)",
        "Regulation 97(3)",
        "section 33(1)(a)(i)",
    ]


def test_extract_legal_references_deduplicates_and_handles_empty():
    assert extract_legal_references("Law 167 and again Law 167") == ["Law 167"]
    assert extract_legal_references(None, "") == []
    assert extract_legal_references("National Regulations and the National Law") == []


# --- identifiers and names --------------------------------------------------


def test_well_formed_ids_are_normalised_and_kept_raw():
    row = make_row(make_raw(id="SE-00008497", name="Munchkin Manor", date="01/04/2025"))
    assert row["service_approval_number"] == "SE-00008497"
    assert row["service_approval_number_raw"] == "SE-00008497"
    assert row["provider_approval_number"] is None


def test_malformed_ids_are_not_padded_or_trimmed():
    short = make_row(make_raw(id="SE-4006774", date="20/03/2025"))
    assert short["service_approval_number"] is None
    assert short["service_approval_number_raw"] == "SE-4006774"
    assert "not SE-/PR- plus 8 digits" in short["notes"]
    suffixed = make_row(
        make_raw(id="PR-00007724R", name="Gundaroo P and C Association", date="4/05/2026")
    )
    assert suffixed["provider_approval_number"] is None
    assert suffixed["provider_approval_number_raw"] == "PR-00007724R"


def test_missing_id_is_null_and_logged():
    row = make_row(make_raw(name="Unnamed", date="01/04/2025"))
    assert row["service_approval_number"] is None
    assert "approval number missing in source" in row["notes"]


def test_provider_row_fills_provider_fields_and_leaves_service_fields_null():
    row = make_row(
        make_raw(
            id="PR-00004108",
            name="Angel's Paradise Pty Ltd",
            date="8/09/2025",
            details="Cancellation of provider approval in accordance with Section 31",
        ),
        label="2025-26 Q1",
    )
    assert row["provider_approval_number"] == "PR-00004108"
    assert row["provider_name"] == "Angel's Paradise Pty Ltd"
    assert row["service_approval_number"] is None
    assert row["service_name"] is None and row["address"] is None


def test_individual_provider_names_are_withheld():
    assert provider_name_if_entity("Kids' Kinder Childcare Pty Limited") == (
        "Kids' Kinder Childcare Pty Limited",
        None,
    )
    name, note = provider_name_if_entity("Jane Q Citizen")
    assert name is None and "withheld" in note
    name, note = provider_name_if_entity("Jane Citizen t/a Little Kids Care")
    assert name is None and note
    row = make_row(
        make_raw(id="PR-40006858", name="Jane Q Citizen", date="4/07/2025"), label="2025-26 Q1"
    )
    assert row["provider_name"] is None
    assert "Citizen" not in str(row)


# --- addresses, labels, links -----------------------------------------------


def test_split_address_uses_only_printed_parts():
    assert split_address("60 Elizabeth Street ASHFIELD") == ("ASHFIELD", None, None)
    assert split_address("120 Gurney Road CHESTER HILL, NSW 2162") == (
        "CHESTER HILL",
        "NSW",
        "2162",
    )
    assert split_address("27-29 Bentley Road, COLYTON 2760") == ("COLYTON", None, "2760")
    assert split_address("43a - 45 Lancelot St FIVE DOCK") == ("FIVE DOCK", None, None)
    assert split_address("12 Florence Street Hillston") == (None, None, None)
    assert split_address(None) == (None, None, None)


def test_period_label_from_filename_slug():
    assert (
        period_label_from_slug("q4-service-enforcement-action-information-2024-2025")
        == "2024-25 Q4"
    )
    assert period_label_from_slug("q1-cancellations-providers-2025-2026") == "2025-26 Q1"
    assert period_label_from_slug("something-else") is None


def test_discover_pdf_urls_makes_absolute_and_deduplicates():
    page = """
    <a href="/content/dam/a/Q4_Cancellations_Services_2025_2026.pdf">Services</a>
    <a href='/content/dam/a/Q4_Cancellations_Services_2025_2026.pdf?x=1'>Services again</a>
    <a href="https://education.nsw.gov.au/content/dam/b/Q3_Involuntary_Suspensions_2025_2026.pdf">Susp</a>
    <a href="/other-page">not a pdf</a>
    """
    urls = discover_pdf_urls(page, INDEX_URL)
    assert urls == [
        "https://education.nsw.gov.au/content/dam/a/Q4_Cancellations_Services_2025_2026.pdf",
        "https://education.nsw.gov.au/content/dam/b/Q3_Involuntary_Suspensions_2025_2026.pdf",
    ]
    assert slug_from_url(urls[0]) == "q4-cancellations-services-2025-2026"


def test_clean_text_joins_hyphen_wraps_and_collapses_whitespace():
    assert clean_text("Colonial Pre-\nSchool and\nChild Care\nCentre -\nLakemba") == (
        "Colonial Pre-School and Child Care Centre - Lakemba"
    )
    assert clean_text(None) == ""


# --- duplicates -------------------------------------------------------------


def test_duplicate_rows_are_kept_and_second_is_noted():
    fields = dict(
        id="SE-00008203",
        name="Little Elves Childcare Centre",
        address="35 Elvy St BARGO",
        nature="Compliance notice issued",
        reason="Due to non-compliance with the National Law and/or National Regulations: Law 167",
        date="01/04/2025",
        details="Issue of compliance notice under section 177",
    )
    first, second = make_row(make_raw(**fields)), make_row(make_raw(**fields))
    other = make_row(make_raw(**{**fields, "date": "02/04/2025"}))
    rows = [first, second, other]
    assert mark_duplicates(rows) == 1
    assert len(rows) == 3
    assert not first["notes"]
    assert second["notes"] == DUPLICATE_NOTE
    assert not other["notes"]


def test_same_row_in_different_snapshots_is_not_a_duplicate():
    fields = dict(id="SE-00008203", name="X", date="01/04/2025", nature="Compliance notice issued")
    a, b = make_row(make_raw(**fields)), make_row(make_raw(**fields))
    b["source_snapshot"] = "data/raw/nsw-enforcement/other.pdf"
    assert mark_duplicates([a, b]) == 0


def test_duplicate_note_is_appended_to_existing_notes():
    fields = dict(id="SE-4006774", name="X", date="01/04/2025", nature="Compliance notice issued")
    rows = [make_row(make_raw(**fields)), make_row(make_raw(**fields))]
    mark_duplicates(rows)
    assert rows[1]["notes"].endswith(DUPLICATE_NOTE)
    assert "not SE-/PR- plus 8 digits" in rows[1]["notes"]


# --- latest snapshot per URL --------------------------------------------------


def _write_pdf_snapshot(directory, name: str, url: str | None) -> None:
    (directory / name).write_bytes(b"%PDF-1.4 test")
    if url is not None:
        meta = {"url": url, "final_url": url}
        (directory / f"{name}.meta.json").write_text(json.dumps(meta))


def test_only_the_newest_snapshot_of_each_url_is_parsed(tmp_path):
    # A re-issued quarterly PDF is fetched again from the same URL; both copies sit in data/raw.
    # Parsing both would double count every action in that quarter.
    src = tmp_path / SOURCE
    src.mkdir()
    q4 = "https://education.nsw.gov.au/x/Q4_Cancellations_Services_2025_2026.pdf"
    q3 = "https://education.nsw.gov.au/x/Q3_Cancellations_Services_2025_2026.pdf"
    _write_pdf_snapshot(src, "2026-10-29T0718Z-q4-cancellations-services-2025-2026.pdf", q4)
    _write_pdf_snapshot(src, "2026-10-29T0718Z-q3-cancellations-services-2025-2026.pdf", q3)
    _write_pdf_snapshot(src, "2026-12-01T0700Z-q4-cancellations-services-2025-2026.pdf", q4)
    (src / "2026-10-29T0717Z.html").write_text("<html></html>")  # index page, not a PDF

    kept, superseded = pdf_snapshots(base_dir=tmp_path)

    assert [p.name for p in kept] == [
        "2026-10-29T0718Z-q3-cancellations-services-2025-2026.pdf",
        "2026-12-01T0700Z-q4-cancellations-services-2025-2026.pdf",
    ]
    assert [p.name for p in superseded] == [
        "2026-10-29T0718Z-q4-cancellations-services-2025-2026.pdf"
    ]


def test_snapshot_without_meta_falls_back_to_its_file_slug(tmp_path):
    src = tmp_path / SOURCE
    src.mkdir()
    _write_pdf_snapshot(src, "2026-10-29T0718Z-q1-cancellations-providers-2025-2026.pdf", None)
    _write_pdf_snapshot(src, "2026-11-02T0718Z-q1-cancellations-providers-2025-2026.pdf", None)
    _write_pdf_snapshot(src, "2026-11-02T0718Z-q2-cancellations-providers-2025-2026.pdf", None)

    kept, superseded = pdf_snapshots(base_dir=tmp_path)

    assert [p.name for p in kept] == [
        "2026-11-02T0718Z-q1-cancellations-providers-2025-2026.pdf",
        "2026-11-02T0718Z-q2-cancellations-providers-2025-2026.pdf",
    ]
    assert [p.name for p in superseded] == [
        "2026-10-29T0718Z-q1-cancellations-providers-2025-2026.pdf"
    ]


# --- paths in outputs ---------------------------------------------------------


def test_processed_outputs_record_posix_paths_on_every_platform(tmp_path, monkeypatch):
    # The committed outputs use forward slashes. A run on Windows must not rewrite every
    # source_snapshot and provenance path with backslashes.
    from scrapers import common

    monkeypatch.setattr(common, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(common, "PROCESSED_DIR", tmp_path / "data" / "processed")
    raw = tmp_path / "data" / "raw" / SOURCE / "2026-10-29T0718Z-q1-x.pdf"
    common.write_processed("x", [], ["record_id"], raw_inputs=[raw])
    provenance = json.loads((tmp_path / "data" / "processed" / "x.provenance.json").read_text())
    assert provenance["output"] == "data/processed/x.csv"
    assert provenance["raw_inputs"] == [f"data/raw/{SOURCE}/2026-10-29T0718Z-q1-x.pdf"]
    assert snapshot_rel_path(raw, root=tmp_path) == provenance["raw_inputs"][0]
