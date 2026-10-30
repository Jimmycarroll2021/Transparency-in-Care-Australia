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


def test_assign_record_ids_ignores_names_and_text_and_is_unique():
    a = _withheld_row(provider_name="Alpha Pty Ltd", reason="one")
    b = _withheld_row(provider_name="Beta Pty Ltd", reason="two")
    c = _withheld_row(provider_name=None, reason=None)
    rows = [a, b, c]
    common.assign_record_ids(rows)
    ids = [r["record_id"] for r in rows]
    assert len(set(ids)) == 3
    # Same position and facts, different names and text: the same id.
    d = _withheld_row(provider_name="Gamma Pty Ltd", reason="other text")
    common.assign_record_ids([d])
    assert d["record_id"] == ids[0]
