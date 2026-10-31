"""PR #7, Codex round 1: per-offence wording tied to an amount, queries in free text, counted
fine occurrences, and a lock token. All names are synthetic."""

import logging

import pytest
from scrapers import common
from scrapers import reparse_offline as ro
from scrapers.parse_qld_enforcement import (
    FINE_NOT_RECORDED_NOTE,
    FINE_PER_OFFENCE_NOTE,
    fine_amount_and_note,
)

# --- Finding 1: per-offence wording counts only when it is tied to the amount -----------------


@pytest.mark.parametrize(
    "text",
    [
        "Provider fined $12,000 for two offences each involving a child",
        "Each child was found safe; provider fined $12,000",
        "Provider fined $12,000 after children were left alone for every hour of the trip",
    ],
)
def test_each_elsewhere_in_the_sentence_does_not_null_a_single_tied_total(text):
    assert fine_amount_and_note(text) == (12000, None)


@pytest.mark.parametrize(
    "text",
    [
        "Provider fined $4,000 each",
        "Provider fined $4,000 per offence",
        "Provider fined; each offence attracted $4,000",
        "Provider fined $4,000 for each of three offences",
        "Provider fined, for every child left behind, $4,000",
    ],
)
def test_per_offence_wording_tied_to_the_amount_stays_null(text):
    assert fine_amount_and_note(text) == (None, FINE_PER_OFFENCE_NOTE)


# --- Finding 4: separate equal fines are counted, a repeated phrase is not ----------------------


def test_two_separate_equal_tied_fines_give_null():
    text = "Provider fined $5,000 for one breach and fined $5,000 for another"
    assert fine_amount_and_note(text) == (None, FINE_NOT_RECORDED_NOTE)


def test_the_same_phrase_printed_twice_counts_once():
    text = "Approved provider fined $12,000 for missing child Approved provider fined $12,000 for missing child"
    assert fine_amount_and_note(text) == (12000, None)


# --- Findings 2 and 3: queries after a local path or after a comma are checked -------------------


def test_a_query_after_a_local_document_path_is_checked():
    for text in (
        "parsed data/raw/x/notice.pdf?subject=Jane%20Example today",
        "parsed notice.pdf?who=Jane%20Example today",
    ):
        redacted = common.redact_urls(text)
        assert "Jane" not in redacted, redacted
        assert redacted.startswith("parsed ") and redacted.endswith(" today"), redacted


def test_a_query_value_after_a_comma_is_checked():
    text = "see https://example.gov.au/register?ids=1,2&who=Jane%20Example, then stop."
    redacted = common.redact_urls(text)
    assert "Jane" not in redacted, redacted
    assert redacted.startswith("see ") and redacted.endswith(", then stop."), redacted


@pytest.mark.parametrize(
    "text",
    [
        "see https://x.gov.au/y.pdf, and then",
        "see https://x.gov.au/register?page=2, and then.",
        "read https://x.gov.au/register.",
    ],
)
def test_trailing_sentence_punctuation_is_not_part_of_the_url(text):
    assert common.redact_urls(text) == text


# --- Finding 5: the lock is removed only when it still holds this run's token -------------------


def test_release_leaves_a_lock_that_holds_another_token(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(ro, "LOCK_PATH", tmp_path / ".reparse.lock")
    ro._acquire_lock()
    ro.LOCK_PATH.write_text("pid 1 nonce other at 2026-10-31T00:00:00Z\n", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="scrapers"):
        ro._release_lock()
    assert ro.LOCK_PATH.exists()
    assert "not removed" in caplog.text


def test_release_removes_this_runs_own_lock(tmp_path, monkeypatch):
    monkeypatch.setattr(ro, "LOCK_PATH", tmp_path / ".reparse.lock")
    ro._acquire_lock()
    body = ro.LOCK_PATH.read_text(encoding="utf-8")
    assert body.startswith("pid ") and " nonce " in body
    ro._release_lock()
    assert not ro.LOCK_PATH.exists()


def test_a_failed_initialisation_removes_only_a_lock_with_this_runs_token(tmp_path, monkeypatch):
    monkeypatch.setattr(ro, "LOCK_PATH", tmp_path / ".reparse.lock")

    def fail(fd):
        raise OSError("fsync failed")

    monkeypatch.setattr(ro.os, "fsync", fail)
    # The file no longer holds this run's token (another process replaced it, or it is unreadable).
    monkeypatch.setattr(ro, "_read_lock_text", lambda: "pid 2 nonce theirs at x")
    with pytest.raises(OSError):
        ro._acquire_lock()
    assert ro.LOCK_PATH.exists()


def test_a_failed_initialisation_removes_this_runs_lock(tmp_path, monkeypatch):
    monkeypatch.setattr(ro, "LOCK_PATH", tmp_path / ".reparse.lock")

    def fail(fd):
        raise OSError("fsync failed")

    monkeypatch.setattr(ro.os, "fsync", fail)
    with pytest.raises(OSError):
        ro._acquire_lock()
    assert not ro.LOCK_PATH.exists()
