"""Follow-up to PR #6: whole-value path redaction in text, QLD fine amounts, lock initialisation.

All names are synthetic.
"""

import pytest
from scrapers import common
from scrapers import profile_providers as pp
from scrapers import reparse_offline as ro


def _names(*subjects):
    names = pp.PersonNames()
    for s in subjects:
        names.add_subject(s)
    return names


# --- Fix 1: every path segment and query value, and the whole value ----------------------------


@pytest.mark.parametrize(
    "value",
    [
        "data/raw/x/Jane Example/file.html",
        "data/raw/qld-enforcement/Jane Example notices/2026-10-29T0718Z-page.html",
        "https://example.gov.au/docs/Jane Example/notice.pdf",
        "https://example.gov.au/docs/notice.pdf?subject=Jane%20Example",
        "https://example.gov.au/docs/notice.pdf?subject=Jane+Example&page=2",
        "https://example.gov.au/register?id=7&who=Jane-Example",
    ],
)
def test_a_name_in_a_folder_or_query_value_withholds_the_whole_value(value):
    text = f"parsed from {value} today"
    redacted = common.redact_urls(text)
    assert "Jane" not in redacted and "Example" not in redacted, redacted
    assert redacted.startswith("parsed from ") and redacted.endswith(" today"), redacted


def test_a_lowercase_known_name_in_a_folder_or_query_is_withheld():
    names = _names("Jane Example")
    for value in (
        "data/raw/x/jane-example/file.html",
        "https://example.gov.au/docs/notice.pdf?subject=jane-example",
    ):
        assert "jane" not in common.redact_urls(f"see {value}", names)


def test_row_values_check_every_segment_and_query_value():
    for col, value in (
        ("source_snapshot", "data/raw/x/Jane Example/file.html"),
        ("source_document", "https://example.gov.au/docs/notice.pdf?subject=Jane%20Example"),
    ):
        row = {col: value}
        common.withhold_prose_naming_people([row])
        assert row[col] is None, value


@pytest.mark.parametrize(
    "text",
    [
        "Historical years 2020 to 2025 are PDF/Word files disallowed by robots.txt and are not included.",
        "Rows whose SE-/PR- key is absent from the ACECQA export are joined to stub entries "
        "listed in spine-unlisted.csv (spine_status not_in_current_register).",
        "Snapshot data/raw/nsw-enforcement/2026-10-29T0718Z-q1-cancellations-providers-2025-2026.pdf parsed.",
        "Register https://www.education.gov.au/early-childhood/providers/compliance-and-enforcement/enforcement-action-register?page=2 read.",
    ],
)
def test_prose_and_clean_locations_are_left_alone(text):
    assert common.redact_urls(text) == text


# --- Fix 2: QLD fines ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Approved provider fined $1.5 million for failing to supervise",
        "Approved provider fined $1.5m after child left on bus",
        "Approved provider fined $15k for missing child",
        "Approved provider fined $20 thousand for breaches",
        "Approved provider fined $2,000 per offence for missing children",
        "Approved provider fined $2,000 for each of three offences",
        "Approved provider fined $12,000 and $3,000",
    ],
)
def test_an_unclear_or_per_offence_fine_is_null_with_a_note(text):
    from scrapers.parse_qld_enforcement import fine_amount_and_note

    value, note = fine_amount_and_note(text)
    assert value is None, text
    assert note and note.startswith("penalty amount not recorded"), text


def test_one_unambiguous_total_fine_is_recorded():
    from scrapers.parse_qld_enforcement import FINE_NOT_SINGLE_TOTAL_NOTE, fine_amount_and_note

    assert fine_amount_and_note("Approved provider fined $12,000 for missing child") == (
        12000,
        None,
    )
    # PR #9: "a fine of $N" is not one of the recognised single-total forms.
    assert fine_amount_and_note("A fine of $5,000.50 was imposed") == (
        None,
        FINE_NOT_SINGLE_TOTAL_NOTE,
    )
    assert fine_amount_and_note("Approved provider fined $35,000 for leaving child on bus") == (
        35000,
        None,
    )


# --- Fix 3: a lock whose body cannot be written is removed ----------------------------------


def test_a_lock_that_fails_to_initialise_is_removed(tmp_path, monkeypatch):
    monkeypatch.setattr(ro, "LOCK_PATH", tmp_path / ".reparse.lock")

    def boom(fd):
        raise OSError("fsync failed")

    monkeypatch.setattr(ro.os, "fsync", boom)
    with pytest.raises(OSError):
        ro._acquire_lock()
    assert not ro.LOCK_PATH.exists()


def test_a_lock_taken_by_another_process_is_never_removed(tmp_path, monkeypatch):
    monkeypatch.setattr(ro, "LOCK_PATH", tmp_path / ".reparse.lock")
    ro.LOCK_PATH.write_text("pid 12345 at 2026-10-31T00:00:00Z\n", encoding="utf-8")

    def boom(fd):
        raise OSError("fsync failed")

    monkeypatch.setattr(ro.os, "fsync", boom)
    with pytest.raises(ro.LockHeld):
        ro._acquire_lock()
    assert ro.LOCK_PATH.read_text(encoding="utf-8") == "pid 12345 at 2026-10-31T00:00:00Z\n"
