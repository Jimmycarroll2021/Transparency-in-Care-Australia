"""PR #9, Codex round 2: prospective or withdrawn fines, and a fine that may name someone other
than the row's subject, fail closed. All names and wording are synthetic."""

import pytest
from scrapers.parse_qld_enforcement import FINE_NOT_SINGLE_TOTAL_NOTE, fine_amount_and_note

from tests.test_pr9_round1 import _row

LINK = '<p><a href="/docs/k.pdf">Prosecution</a></p>'


def test_another_educator_on_an_individual_row_gives_null():
    row = _row(
        "Jane Example", f"<p>Educator warned; another educator fined $4,000 for a breach</p>{LINK}"
    )
    assert row["penalty_amount_aud"] is None
    assert FINE_NOT_SINGLE_TOTAL_NOTE in row["notes"]


@pytest.mark.parametrize(
    "text",
    [
        "Provider warned; another organisation was fined $4,000 for a breach",
        "Provider will be fined $4,000 for the breach",
        "Provider may yet be fined $4,000 for the breach",
        "Provider is liable to be fined $4,000 for the breach",
        "Provider fined $4,000 for the breach. The fine was withdrawn.",
        "Provider fined $4,000 for the breach; the fine was later quashed",
        # the same causes, other wording
        "Provider warned; operator fined $4,000 for a breach",
        "Provider warned. Company fined $4,000 for a breach",
        "Provider fined $4,000 for the breach and fined again on review",
        "Provider fined $4,000 for the breach; the penalty was waived",
        "Provider fined $4,000 for the breach, pending review",
        "A separate provider fined $4,000 for the breach",
    ],
)
def test_round_2_blocking_wordings_give_null(text):
    assert fine_amount_and_note(text) == (None, FINE_NOT_SINGLE_TOTAL_NOTE)


@pytest.mark.parametrize(
    "text",
    [
        "Provider fined $4,000 fortnightly for the breach",
        "Provider fined $4,000 for the breach, tripled from the first notice",
        "Provider fined $4,000 for the breach, a three-fold rise",
        "Provider fined $4,000 for the breach, a twofold rise",
        "Provider fined $4,000 including fees",
        "Provider fined $4,000 including the levy",
    ],
)
def test_round_2_low_wordings_give_null(text):
    value, note = fine_amount_and_note(text)
    assert value is None and note, text


def test_a_role_word_after_a_clause_break_on_an_individual_row_gives_null():
    row = _row("Jane Example", f"<p>Warned for a breach; educator fined $4,000</p>{LINK}")
    assert row["penalty_amount_aud"] is None


def test_a_role_word_on_an_organisation_row_gives_null():
    row = _row("Example Kids Pty Ltd", f"<p>Educator fined $4,000 for a breach</p>{LINK}")
    assert row["penalty_amount_aud"] is None


@pytest.mark.parametrize(
    ("subject", "headline", "amount"),
    [
        (
            "Jane Example",
            "Family day care educator was fined $2,500 for leaving children unattended in a public library",
            2500,
        ),
        (
            "Jane Example",
            "Jane Example fined $6,000 for providing and advertising a service without a service approval",
            6000,
        ),
        (
            "Example Kids Pty Ltd",
            "Approved provider was fined $23,000 after multiple breaches identified between May 2020 and June 2022",
            23000,
        ),
        (
            "Example Kids Pty Ltd",
            "Approved provider fined $34,500 for multiple incidents including a child being left on the bus",
            34500,
        ),
    ],
)
def test_the_committed_shapes_still_record_the_amount(subject, headline, amount):
    row = _row(subject, f"<p>{headline}</p>{LINK}")
    assert row["penalty_amount_aud"] == amount
