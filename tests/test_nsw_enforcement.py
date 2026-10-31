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
    is_id_cell,
    map_action_type,
    mark_duplicates,
    parse_all,
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


def test_cosmetic_variants_of_a_valid_key_are_normalised_deterministically():
    # Case, spacing and the dash character carry no meaning; the eight digits are all printed.
    for printed in (
        "se-00008497",
        "SE - 00008497",
        "SE\u201300008497",
        "SE 00008497",
        " SE-00008497 ",
    ):
        row = make_row(make_raw(id=printed, name="Munchkin Manor", date="01/04/2025"))
        assert row["service_approval_number"] == "SE-00008497", printed
        assert row["service_approval_number_raw"] == printed  # kept as printed
        assert not row["notes"] or "plus 8 digits" not in row["notes"]
    provider = make_row(
        make_raw(id="pr-00004108", name="Angel's Paradise Pty Ltd", date="8/09/2025")
    )
    assert provider["provider_approval_number"] == "PR-00004108"
    assert provider["service_approval_number"] is None


def test_the_two_malformed_register_keys_say_why_they_were_not_corrected():
    # Q1 2025-26 service enforcement file, row 268 of the output: seven digits. The missing digit
    # could be anywhere, so the key is not padded.
    short = make_row(make_raw(id="SE-4006774", date="20/03/2025"))
    assert short["service_approval_number"] is None
    assert "has 7 digits" in short["notes"]
    assert "normalised value left null" in short["notes"]
    # Q4 2025-26 provider cancellations file, row 1213: eight digits then a stray 'R'. What the
    # suffix means is not printed, so the key is not trimmed.
    suffixed = make_row(make_raw(id="PR-00007724R", name="X Association", date="4/05/2026"))
    assert suffixed["provider_approval_number"] is None
    assert "trailing 'R'" in suffixed["notes"]
    assert "normalised value left null" in suffixed["notes"]


def test_id_cells_are_recognised_in_cosmetic_variants_only():
    assert is_id_cell("SE-00008497")
    assert is_id_cell("se - 00008497")
    assert is_id_cell("PR-00007724R")  # a malformed key still starts a new record
    assert is_id_cell("SE-4006774")
    assert not is_id_cell("Service ID")
    assert not is_id_cell("Seven Hills 2147")
    assert not is_id_cell(None)


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


def test_snapshots_without_meta_are_not_identified_from_their_file_names(tmp_path):
    # The file name is not an identity: without a sidecar URL a snapshot is neither kept nor
    # superseded, and parse_all reports it as unidentified.
    src = tmp_path / SOURCE
    src.mkdir()
    names = [
        "2026-10-29T0718Z-q1-cancellations-providers-2025-2026.pdf",
        "2026-11-02T0718Z-q1-cancellations-providers-2025-2026.pdf",
        "2026-11-02T0718Z-q2-cancellations-providers-2025-2026.pdf",
    ]
    for name in names:
        _write_pdf_snapshot(src, name, None)

    kept, superseded = pdf_snapshots(base_dir=tmp_path)
    rows, parsed, summary = parse_all(base_dir=tmp_path, root=tmp_path)

    assert kept == []
    assert superseded == []
    assert parsed == []
    assert summary["unidentified_snapshots"] == names
    assert summary["complete"] is False


def test_a_newer_copy_without_a_sidecar_is_not_counted_as_a_second_document(tmp_path):
    # The same quarterly PDF, once with a sidecar and once without, must not be counted as two
    # documents: the copy with the sidecar is the document, the other is reported unidentified.
    src = tmp_path / SOURCE
    src.mkdir()
    q1 = "https://education.nsw.gov.au/x/Q1_Cancellations_Providers_2025_2026.pdf"
    old = "2026-10-29T0718Z-q1-cancellations-providers-2025-2026.pdf"
    new = "2026-11-02T0718Z-q1-cancellations-providers-2025-2026.pdf"
    _write_pdf_snapshot(src, old, q1)
    _write_pdf_snapshot(src, new, None)

    kept, superseded = pdf_snapshots(base_dir=tmp_path)

    assert [p.name for p in kept] == [old]
    assert superseded == []
    rows, parsed, summary = parse_all(base_dir=tmp_path, root=tmp_path)
    assert summary["unidentified_snapshots"] == [new]
    assert new not in summary["by_file"]


def test_an_older_copy_without_a_sidecar_is_not_counted_as_a_second_document(tmp_path):
    src = tmp_path / SOURCE
    src.mkdir()
    q1 = "https://education.nsw.gov.au/x/Q1_Cancellations_Providers_2025_2026.pdf"
    _write_pdf_snapshot(src, "2026-10-29T0718Z-q1-cancellations-providers-2025-2026.pdf", None)
    _write_pdf_snapshot(src, "2026-11-02T0718Z-q1-cancellations-providers-2025-2026.pdf", q1)

    kept, superseded = pdf_snapshots(base_dir=tmp_path)

    assert [p.name for p in kept] == ["2026-11-02T0718Z-q1-cancellations-providers-2025-2026.pdf"]
    assert superseded == []  # the older copy has no sidecar: unidentified, not superseded


def _fake_reader(bad: set[str]):
    """Stand-in for read_pdf_records: raises for names in `bad`, else returns one service row."""
    from scrapers.parse_nsw_enforcement import RawRecord

    def read(path):
        if path.name in bad:
            raise ValueError("No /Root object! - Is this really a PDF?")
        raw = RawRecord(page=1)
        raw.fields.update(
            {
                "id": "SE-00012345",
                "name": "Example Early Learning Centre",
                "nature": "Cancellation of service approval",
                "date": "1/7/2025",
            }
        )
        return [raw], {"pages": 1}

    return read


def test_a_corrupt_newer_snapshot_falls_back_to_the_older_copy(tmp_path, monkeypatch):
    from scrapers import parse_nsw_enforcement as nsw

    src = tmp_path / SOURCE
    src.mkdir()
    q1 = "https://education.nsw.gov.au/x/Q1_Cancellations_Services_2025_2026.pdf"
    old = "2026-10-29T0718Z-q1-cancellations-services-2025-2026.pdf"
    new = "2026-11-02T0718Z-q1-cancellations-services-2025-2026.pdf"
    _write_pdf_snapshot(src, old, q1)
    _write_pdf_snapshot(src, new, q1)
    monkeypatch.setattr(nsw, "read_pdf_records", _fake_reader({new}))

    rows, parsed, summary = parse_all(base_dir=tmp_path, root=tmp_path)

    assert [p.name for p in parsed] == [old]
    assert len(rows) == 1
    assert rows[0]["source_snapshot"] == f"{SOURCE}/{old}"
    assert summary["pdfs_parsed"] == 1
    assert "error" in summary["by_file"][new]
    assert summary["fallbacks"] == [{"document": q1, "used": old, "failed": [new]}]
    assert summary["failed_documents"] == []
    assert summary["complete"] is True


def test_a_document_whose_snapshots_all_fail_is_reported_not_silently_dropped(
    tmp_path, monkeypatch
):
    from scrapers import parse_nsw_enforcement as nsw

    src = tmp_path / SOURCE
    src.mkdir()
    q1 = "https://education.nsw.gov.au/x/Q1_Cancellations_Services_2025_2026.pdf"
    q2 = "https://education.nsw.gov.au/x/Q2_Cancellations_Services_2025_2026.pdf"
    old = "2026-10-29T0718Z-q1-cancellations-services-2025-2026.pdf"
    new = "2026-11-02T0718Z-q1-cancellations-services-2025-2026.pdf"
    ok = "2026-10-29T0718Z-q2-cancellations-services-2025-2026.pdf"
    _write_pdf_snapshot(src, old, q1)
    _write_pdf_snapshot(src, new, q1)
    _write_pdf_snapshot(src, ok, q2)
    monkeypatch.setattr(nsw, "read_pdf_records", _fake_reader({old, new}))

    rows, parsed, summary = parse_all(base_dir=tmp_path, root=tmp_path)

    assert [p.name for p in parsed] == [ok]
    assert summary["failed_documents"] == [{"document": q1, "snapshots": [new, old]}]
    assert summary["complete"] is False


def test_a_snapshot_with_no_rows_counts_as_a_failed_parse(tmp_path, monkeypatch):
    # A register PDF that opens but yields no rows is not a valid copy of the document.
    from scrapers import parse_nsw_enforcement as nsw

    src = tmp_path / SOURCE
    src.mkdir()
    q1 = "https://education.nsw.gov.au/x/Q1_Cancellations_Services_2025_2026.pdf"
    old = "2026-10-29T0718Z-q1-cancellations-services-2025-2026.pdf"
    new = "2026-11-02T0718Z-q1-cancellations-services-2025-2026.pdf"
    _write_pdf_snapshot(src, old, q1)
    _write_pdf_snapshot(src, new, q1)
    good = _fake_reader(set())
    monkeypatch.setattr(
        nsw, "read_pdf_records", lambda p: ([], {"pages": 1}) if p.name == new else good(p)
    )

    rows, parsed, summary = parse_all(base_dir=tmp_path, root=tmp_path)

    assert [p.name for p in parsed] == [old]
    assert summary["fallbacks"][0]["failed"] == [new]


# --- document identity is the exact source URL ---------------------------------


def test_two_urls_with_the_same_basename_are_two_documents(tmp_path, monkeypatch):
    # Different folders on the site can publish files with the same name. Both are register
    # documents; treating them as one would silently drop one document's actions.
    from scrapers import parse_nsw_enforcement as nsw

    src = tmp_path / SOURCE
    src.mkdir()
    a = "https://education.nsw.gov.au/a/Q1_Cancellations_Services_2025_2026.pdf"
    b = "https://education.nsw.gov.au/b/Q1_Cancellations_Services_2025_2026.pdf"
    first = "2026-10-29T0718Z-q1-cancellations-services-2025-2026.pdf"
    second = "2026-10-29T0718Z-q1-cancellations-services-2025-202630.pdf"  # same-minute collision
    _write_pdf_snapshot(src, first, a)
    _write_pdf_snapshot(src, second, b)
    monkeypatch.setattr(nsw, "read_pdf_records", _fake_reader(set()))

    rows, parsed, summary = parse_all(base_dir=tmp_path, root=tmp_path)

    assert [p.name for p in parsed] == [first, second]
    assert len(rows) == 2
    assert summary["superseded_snapshots"] == []
    assert summary["complete"] is True


def test_a_snapshot_without_a_usable_sidecar_is_reported_not_parsed(tmp_path, monkeypatch):
    # No sidecar, a sidecar with no URL, or an unreadable sidecar: the document cannot be
    # identified, so the snapshot is listed and not parsed, and the run is marked incomplete.
    from scrapers import parse_nsw_enforcement as nsw

    src = tmp_path / SOURCE
    src.mkdir()
    q2 = "https://education.nsw.gov.au/x/Q2_Cancellations_Services_2025_2026.pdf"
    ok = "2026-10-29T0718Z-q2-cancellations-services-2025-2026.pdf"
    no_meta = "2026-11-02T0718Z-q1-cancellations-services-2025-2026.pdf"
    no_url = "2026-11-02T0718Z-q3-cancellations-services-2025-2026.pdf"
    bad_json = "2026-11-02T0718Z-q4-cancellations-services-2025-2026.pdf"
    _write_pdf_snapshot(src, ok, q2)
    _write_pdf_snapshot(src, no_meta, None)
    _write_pdf_snapshot(src, no_url, None)
    (src / f"{no_url}.meta.json").write_text(json.dumps({"url": "  ", "final_url": None}))
    _write_pdf_snapshot(src, bad_json, None)
    (src / f"{bad_json}.meta.json").write_text("{not json")
    monkeypatch.setattr(nsw, "read_pdf_records", _fake_reader(set()))

    rows, parsed, summary = parse_all(base_dir=tmp_path, root=tmp_path)

    assert [p.name for p in parsed] == [ok]
    assert len(rows) == 1
    assert summary["unidentified_snapshots"] == [no_meta, no_url, bad_json]
    assert set(summary["by_file"]) == {ok}
    assert summary["complete"] is False
    kept, superseded = pdf_snapshots(base_dir=tmp_path)
    assert [p.name for p in kept] == [ok]
    assert superseded == []
    notes = nsw.provenance_notes(summary)
    for name in (no_meta, no_url, bad_json):
        assert name in notes


def test_a_collision_suffixed_copy_of_the_same_url_is_the_same_document(tmp_path, monkeypatch):
    # A same-minute re-fetch is written as '<stamp>-<slug><seconds>.pdf'. With a sidecar for the
    # same URL it is the newer copy of the same document: it wins, the older copy is the fallback.
    from scrapers import parse_nsw_enforcement as nsw

    src = tmp_path / SOURCE
    src.mkdir()
    q1 = "https://education.nsw.gov.au/x/Q1_Cancellations_Services_2025_2026.pdf"
    old = "2026-10-29T0718Z-q1-cancellations-services-2025-2026.pdf"
    new = "2026-10-29T0718Z-q1-cancellations-services-2025-202630.pdf"
    _write_pdf_snapshot(src, old, q1)
    _write_pdf_snapshot(src, new, q1)
    monkeypatch.setattr(nsw, "read_pdf_records", _fake_reader(set()))

    rows, parsed, summary = parse_all(base_dir=tmp_path, root=tmp_path)

    assert [p.name for p in parsed] == [new]
    assert len(rows) == 1
    assert rows[0]["period_label"] == "2025-26 Q1"
    assert summary["superseded_snapshots"] == [old]

    monkeypatch.setattr(nsw, "read_pdf_records", _fake_reader({new}))
    rows, parsed, summary = parse_all(base_dir=tmp_path, root=tmp_path)

    assert [p.name for p in parsed] == [old]
    assert summary["fallbacks"] == [{"document": q1, "used": old, "failed": [new]}]
    assert summary["complete"] is True


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


# --- incomplete runs and malformed sidecars -----------------------------------


def _patch_main_paths(tmp_path, monkeypatch):
    """Point main() at snapshots and processed outputs under tmp_path; no fetch, no data/raw."""
    from scrapers import common
    from scrapers import parse_nsw_enforcement as nsw

    monkeypatch.setattr(common, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(common, "PROCESSED_DIR", tmp_path / "data" / "processed")
    real_parse_all = nsw.parse_all
    monkeypatch.setattr(
        nsw, "parse_all", lambda: real_parse_all(base_dir=tmp_path / "raw", root=tmp_path)
    )
    monkeypatch.setattr(nsw, "read_pdf_records", _fake_reader(set()))
    src = tmp_path / "raw" / SOURCE
    src.mkdir(parents=True)
    return nsw, src, tmp_path / "data" / "processed"


def test_an_incomplete_run_leaves_the_previous_outputs_and_exits_non_zero(tmp_path, monkeypatch):
    # A run that could not identify or parse every document must not replace the last good
    # outputs with a partial set; the join would silently lose that document's actions.
    nsw, src, processed = _patch_main_paths(tmp_path, monkeypatch)
    _write_pdf_snapshot(
        src,
        "2026-10-29T0718Z-q2-cancellations-services-2025-2026.pdf",
        "https://education.nsw.gov.au/x/Q2_Cancellations_Services_2025_2026.pdf",
    )
    _write_pdf_snapshot(src, "2026-11-02T0718Z-q1-cancellations-services-2025-2026.pdf", None)
    processed.mkdir(parents=True)
    csv_path = processed / f"{nsw.OUTPUT_NAME}.csv"
    prov_path = processed / f"{nsw.OUTPUT_NAME}.provenance.json"
    csv_path.write_text("previous good csv\n")
    prov_path.write_text('{"previous": "good provenance"}\n')

    code = nsw.main(["--skip-fetch"])

    assert code != 0
    assert csv_path.read_text() == "previous good csv\n"
    assert prov_path.read_text() == '{"previous": "good provenance"}\n'
    assert sorted(p.name for p in processed.iterdir()) == sorted([csv_path.name, prov_path.name])


def test_a_complete_run_writes_the_outputs_and_exits_zero(tmp_path, monkeypatch):
    nsw, src, processed = _patch_main_paths(tmp_path, monkeypatch)
    name = "2026-10-29T0718Z-q2-cancellations-services-2025-2026.pdf"
    _write_pdf_snapshot(
        src, name, "https://education.nsw.gov.au/x/Q2_Cancellations_Services_2025_2026.pdf"
    )
    processed.mkdir(parents=True)
    csv_path = processed / f"{nsw.OUTPUT_NAME}.csv"
    csv_path.write_text("previous good csv\n")

    code = nsw.main(["--skip-fetch"])

    assert code == 0
    lines = csv_path.read_text(encoding="utf-8").splitlines()
    assert lines[0].split(",") == nsw.FIELDNAMES
    assert len(lines) == 2
    provenance = json.loads((processed / f"{nsw.OUTPUT_NAME}.provenance.json").read_text())
    assert provenance["rows"] == 1
    assert provenance["raw_inputs"] == [f"raw/{SOURCE}/{name}"]


def test_a_sidecar_that_is_not_a_json_object_is_reported_as_unidentified(tmp_path, monkeypatch):
    # A sidecar holding a JSON list (or string, or number) has no URL field. It must be reported
    # like any other unusable sidecar, not abort the run with an AttributeError.
    from scrapers import parse_nsw_enforcement as nsw

    src = tmp_path / SOURCE
    src.mkdir()
    q2 = "https://education.nsw.gov.au/x/Q2_Cancellations_Services_2025_2026.pdf"
    ok = "2026-10-29T0718Z-q2-cancellations-services-2025-2026.pdf"
    as_list = "2026-11-02T0718Z-q1-cancellations-services-2025-2026.pdf"
    as_string = "2026-11-02T0718Z-q3-cancellations-services-2025-2026.pdf"
    _write_pdf_snapshot(src, ok, q2)
    _write_pdf_snapshot(src, as_list, None)
    (src / f"{as_list}.meta.json").write_text(json.dumps([{"url": q2}]))
    _write_pdf_snapshot(src, as_string, None)
    (src / f"{as_string}.meta.json").write_text(json.dumps(q2))
    monkeypatch.setattr(nsw, "read_pdf_records", _fake_reader(set()))

    rows, parsed, summary = parse_all(base_dir=tmp_path, root=tmp_path)

    assert [p.name for p in parsed] == [ok]
    assert summary["unidentified_snapshots"] == [as_list, as_string]
    assert summary["complete"] is False


def test_individual_trustee_and_estate_names_are_withheld():
    # Synthetic names. A trust or company word must not let a person's name through.
    for printed in (
        "Jane Example ATF Jane Example Unit Trust",
        "Jane Example & John Example as trustees for the Example Family Trust",
        "Jane Example - executor of the estate of John Example",
        "Example Holdings Pty Ltd ATF the Jane Example Family Trust",
    ):
        name, note = provider_name_if_entity(printed)
        assert name is None, printed
        assert note and "withheld" in note
    row = make_row(
        make_raw(
            id="PR-40006858", name="Jane Example ATF Jane Example Unit Trust", date="4/07/2025"
        ),
        label="2025-26 Q1",
    )
    assert row["provider_name"] is None
    assert "Jane" not in str(row)


def test_organisation_trustee_name_is_kept():
    name, note = provider_name_if_entity("Example Holdings Pty Ltd ATF Sunrise Unit Trust")
    assert name == "Example Holdings Pty Ltd ATF Sunrise Unit Trust" and note is None


# --- Codex round 1: withheld rows keep no free text, keep keys, ids ignore names -------------

from scrapers.common import FREE_TEXT_WITHHELD_NOTE, assign_record_ids  # noqa: E402


def _withheld_nsw(name="Jane Q Citizen"):
    return make_row(
        make_raw(
            id="PR-40006858",
            name=name,
            date="4/07/2025",
            nature="Compliance notice",
            details=f"Notice issued to {name}",
            reason=f"{name} failed to supervise children. Regulation 168",
        ),
        label="2025-26 Q1",
    )


def test_withheld_row_keeps_no_free_text():
    row = _withheld_nsw()
    assert row["provider_name"] is None
    assert row["reason"] is None and row["action_type_raw"] == "(withheld)"
    assert row["legal_references"] == "" and row.get("_details") is None
    assert FREE_TEXT_WITHHELD_NOTE in row["notes"]
    assert "citizen" not in str({k: v for k, v in row.items() if k != "_fingerprint"}).lower()
    assert row["action_type"] == "compliance_notice" and row["date_issued"] == "2025-07-04"


def test_withheld_row_keeps_its_approval_number():
    row = _withheld_nsw()
    assert row["provider_approval_number"] == "PR-40006858"
    assert row["provider_approval_number_raw"] == "PR-40006858"


def test_record_id_ignores_the_withholding_decision():
    # Codex round 2, finding 3: the id hashes the printed row, not what is published.
    a = [_withheld_nsw("Jane Q Citizen")]
    b = [_withheld_nsw("Jane Q Citizen")]
    b[0]["provider_name"] = "Shown Anyway Pty Ltd"
    assign_record_ids(a)
    assign_record_ids(b)
    assert a[0]["record_id"] == b[0]["record_id"]
    c = [_withheld_nsw("Mary Sample")]
    assign_record_ids(c)
    assert c[0]["record_id"] != a[0]["record_id"]  # a different printed row


# --- Codex round 2, finding 4: a printed suspension period is kept as structured columns ----

SUSPENSION = (
    "Service approval suspended under section 72 of the National Law. "
    "The period of suspension is from 17/12/2025 until 16/03/2026"
)


def test_suspension_period_is_kept_as_structured_columns():
    row = make_row(
        make_raw(
            id="SE-40000001", name="Example Kids Pty Ltd", date="17/12/2025", nature=SUSPENSION
        ),
        label="2025-26 Q2",
    )
    assert row["start_date"] == "2025-12-17" and row["end_date"] == "2026-03-16"


def test_suspension_period_with_to_and_survives_withholding():
    row = make_row(
        make_raw(
            id="PR-40006858",
            name="Jane Q Citizen",
            date="24/10/2025",
            nature=SUSPENSION.replace(
                "from 17/12/2025 until 16/03/2026", "from 24/10/2025 to 28/01/2026"
            ),
        ),
        label="2025-26 Q2",
    )
    assert row["action_type_raw"] == "(withheld)"
    assert row["start_date"] == "2025-10-24" and row["end_date"] == "2026-01-28"


def test_no_printed_period_means_null_dates():
    row = _withheld_nsw()
    assert row["start_date"] is None and row["end_date"] is None


def test_prose_naming_a_person_is_withheld_on_an_organisation_row():
    # Codex round 2, finding 1: the shared prose rule runs on every row, not only withheld ones.
    from scrapers.common import withhold_prose_naming_people

    row = make_row(
        make_raw(
            id="PR-40000001",
            name="Example Kids Pty Ltd",
            date="4/07/2025",
            nature="Compliance notice",
            details="Notice issued after educator Jane Example left a child alone",
            reason="Educator Jane Example failed to supervise children. Regulation 168",
        ),
        label="2025-26 Q1",
    )
    withhold_prose_naming_people([row])
    assert row["provider_name"] == "Example Kids Pty Ltd"
    assert row["reason"] is None and row["_details"] is None
    assert "free text withheld: may name an individual" in row["notes"]
    assert "jane" not in str({k: v for k, v in row.items() if k != "_fingerprint"}).lower()


def test_snapshot_parsing_applies_the_prose_rule():
    import inspect

    from scrapers import parse_nsw_enforcement as nsw_mod

    assert "withhold_prose_naming_people(file_rows)" in inspect.getsource(nsw_mod._parse_snapshot)
