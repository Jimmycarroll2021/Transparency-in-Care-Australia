from scrapers.common import normalise_pr, normalise_se, record_hash, utc_stamp


def test_normalise_se_variants():
    assert normalise_se("SE-00010955") == "SE-00010955"
    assert normalise_se("SE 00010955") == "SE-00010955"
    assert normalise_se("se-10955") == "SE-00010955"
    assert normalise_se("Service ID SE-00008497 (NSW)") == "SE-00008497"
    assert normalise_se("no key here") is None
    assert normalise_se(None) is None


def test_normalise_pr_variants():
    assert normalise_pr("PR-40001361") == "PR-40001361"
    assert normalise_pr("pr 6942") == "PR-00006942"
    assert normalise_pr("") is None


def test_record_hash_is_stable_and_case_insensitive():
    assert record_hash("NSW", "SE-1", "Compliance notice") == record_hash(
        "nsw", "se-1", " compliance notice "
    )
    assert record_hash("NSW", None) == record_hash("NSW", "")


def test_utc_stamp_shape():
    s = utc_stamp()
    assert len(s) == 16 and s.endswith("Z") and s[10] == "T"


# ---------------------------------------------------------------------------
# Codex round 1: withheld rows keep no free text; record_id never depends on a name.
# ---------------------------------------------------------------------------


from scrapers import common  # noqa: E402


def _withheld_row(**extra):
    row = {
        "record_id": "x",
        "jurisdiction": "QLD",
        "source_register": "https://example.gov.au/register",
        "source_document": "https://example.gov.au/register",
        "source_snapshot": "data/raw/x.html",
        "captured_at": "2026-10-29T00:00:00+00:00",
        "service_approval_number": "SE-00000001",
        "service_approval_number_raw": "SE-00000001",
        "provider_approval_number": "PR-00000001",
        "provider_approval_number_raw": "PR 00000001",
        "service_name": None,
        "provider_name": None,
        "address": "1 Example Street, Exampleton",
        "suburb": "Exampleton",
        "state": "QLD",
        "postcode": "4000",
        "action_type": "prosecution",
        "action_type_raw": "Jane Example fined",
        "reason": "Jane Example failed to supervise",
        "legal_references": ["NL s.165 offence by Jane Example"],
        "date_issued": "2026-02-01",
        "date_issued_raw": "1/2/2026",
        "period_label": "2026",
        "notes": "provider name withheld; reason mentions Jane Example; duplicate row in source",
        "linked_documents": "https://example.gov.au/jane-example.pdf",
    }
    row.update(extra)
    return row


def test_withhold_free_text_blanks_prose_and_keeps_structured_fields():
    row = common.withhold_free_text(_withheld_row())
    assert "jane" not in str(row).lower()
    assert row["action_type_raw"] == "(withheld)" and row["reason"] is None
    assert row["legal_references"] == [] and row["address"] is None
    assert row["linked_documents"] is None
    assert row["notes"] == f"{common.FREE_TEXT_WITHHELD_NOTE}; {common.DUPLICATE_NOTE}"
    for key in (
        "service_approval_number",
        "provider_approval_number",
        "service_approval_number_raw",
        "provider_approval_number_raw",
        "suburb",
        "state",
        "postcode",
        "action_type",
        "date_issued",
        "date_issued_raw",
        "source_document",
        "source_snapshot",
        "jurisdiction",
    ):
        assert row[key] == _withheld_row()[key], key


def test_withhold_free_text_keeps_a_joined_string_legal_references_column_a_string():
    row = common.withhold_free_text(_withheld_row(legal_references="NL s.165 by Jane Example"))
    assert row["legal_references"] == ""


def _printed(text, **extra):
    row = {
        "jurisdiction": "QLD",
        "source_document": "https://example.gov.au/register",
        "_fingerprint": common.printed_fingerprint(text),
    }
    row.update(extra)
    return row


def _ids(rows):
    common.assign_record_ids(rows)
    return {r["_fingerprint"]: r["record_id"] for r in rows}


def test_record_ids_survive_reordering_of_non_identical_rows():
    # Codex round 2, finding 3: no source-order ordinal, so moving rows moves no id.
    texts = ["Alpha Pty Ltd | 1/2/2026 | Compliance notice", "Beta Inc | 2/2/2026 | Cancellation"]
    forward = _ids([_printed(t) for t in texts])
    backward = _ids([_printed(t) for t in reversed(texts)])
    assert forward == backward and len(set(forward.values())) == 2


def test_record_id_is_unaffected_by_an_inserted_row():
    before = _ids([_printed("Alpha Pty Ltd | 1/2/2026"), _printed("Beta Inc | 2/2/2026")])
    after = _ids(
        [
            _printed("New Row Ltd | 3/2/2026"),
            _printed("Alpha Pty Ltd | 1/2/2026"),
            _printed("Beta Inc | 2/2/2026"),
        ]
    )
    for fp, rid in before.items():
        assert after[fp] == rid


def test_identical_printed_rows_get_distinct_ids_and_whitespace_does_not_matter():
    rows = [_printed("Same  row\ttext"), _printed("same row text")]
    common.assign_record_ids(rows)
    assert rows[0]["_fingerprint"] == rows[1]["_fingerprint"]
    assert rows[0]["record_id"] != rows[1]["record_id"]


def test_record_id_ignores_the_published_fields_and_the_withholding_decision():
    shown = _printed("Alpha Pty Ltd | 1/2/2026", provider_name="Alpha Pty Ltd", reason="x")
    withheld = common.withhold_free_text(
        _printed("Alpha Pty Ltd | 1/2/2026", provider_name=None, reason="x", notes=None)
    )
    common.assign_record_ids([shown])
    common.assign_record_ids([withheld])
    assert shown["record_id"] == withheld["record_id"]


def test_record_id_uses_the_given_source_id_over_the_row_document():
    a = _printed("Alpha", source_document="https://example.gov.au/a.pdf")
    b = _printed("Alpha", source_document="https://example.gov.au/register")
    common.assign_record_ids([a], source_id="https://example.gov.au/register")
    common.assign_record_ids([b], source_id="https://example.gov.au/register")
    assert a["record_id"] == b["record_id"]


# --- Codex round 2, finding 1: the prose rule nulls any field that may name a person --------

PROSE_NOTE = "free text withheld: may name an individual"


def _org_row(**over):
    row = {
        "service_name": "Sunny Meadow Early Learning",
        "provider_name": "Example Kids Pty Ltd",
        "suburb": "Exampleton",
        "action_type_raw": "Compliance notice issued under section 177",
        "reason": "Section 165 - inadequate supervision",
        "legal_references": ["Section 165"],
        "notes": "location as printed: 1 Example St; duplicate row in source",
        "address": "1 Example St",
    }
    row.update(over)
    return row


def test_prose_rule_leaves_clean_rows_untouched():
    row = _org_row()
    before = dict(row)
    assert common.withhold_prose_naming_people([row]) == {}
    assert row == before


def test_prose_rule_nulls_flagged_fields_and_adds_the_fixed_note_once():
    assert common.PROSE_WITHHELD_NOTE == PROSE_NOTE
    row = _org_row(
        action_type_raw="Notice issued to educator Jane Example",
        reason="Jane Example left children unsupervised",
        legal_references=["Section 165", "Offence by Jane Example"],
        notes="charge: Ms Jane Example; duplicate row in source",
    )
    counts = common.withhold_prose_naming_people([row])
    assert counts == {"action_type_raw": 1, "reason": 1, "legal_references": 1, "notes": 1}
    assert row["action_type_raw"] == common.ACTION_TYPE_RAW_WITHHELD
    assert row["reason"] is None
    assert row["legal_references"] == ["Section 165"]
    assert row["notes"] == f"duplicate row in source; {PROSE_NOTE}"
    assert "Jane" not in str(row)
    assert row["service_name"] == "Sunny Meadow Early Learning"
    assert row["address"] == "1 Example St"


def test_prose_rule_handles_string_legal_references_and_pipe_notes():
    a = _org_row(
        legal_references='["Section 165", "Offence by Jane Example"]',
        notes="x | Jane Example said",
    )
    b = _org_row(
        legal_references="Section 165; Offence by Jane Example", details="Jane Example agreed"
    )
    common.withhold_prose_naming_people([a, b])
    assert a["legal_references"] == '["Section 165"]'
    assert a["notes"] == f"x | {PROSE_NOTE}"
    assert b["legal_references"] == "Section 165"
    assert b["details"] is None and PROSE_NOTE in b["notes"]


def test_prose_rule_skips_rows_already_withheld_whole():
    row = _org_row(action_type_raw="(withheld)", reason=None, notes=common.FREE_TEXT_WITHHELD_NOTE)
    assert common.withhold_prose_naming_people([row]) == {}
