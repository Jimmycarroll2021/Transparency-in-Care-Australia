"""PR #9, Codex round 3: another party named before 'fined' after a conjunction, annulled or
reversed fines, and fees included in the amount. All names and wording are synthetic."""

import pytest
from scrapers.parse_qld_enforcement import fine_amount_and_note

from tests.test_pr9_round1 import _row


def test_another_party_after_a_conjunction_on_a_role_row_gives_null():
    row = _row(
        "Educator",
        '<p>Educator warned and operator was <a href="/x.pdf">fined $4,000</a> for a breach</p>',
    )
    assert row["penalty_amount_aud"] is None


def test_an_annulled_total_fine_gives_null():
    row = _row(
        "Example Kids Pty Ltd",
        '<p>A total fine of <a href="/x.pdf">$4,000</a> for the breach. The fine was later annulled.</p>',
    )
    assert row["penalty_amount_aud"] is None


@pytest.mark.parametrize(
    "text",
    [
        "Provider fined $4,000 for the breach. The penalty was nullified.",
        "Provider fined $4,000 for the breach. The judgment was reversed.",
        "Provider fined $4,000 for the breach. The order was vacated.",
        "Provider fined $4,000 for the breach. The decision was set-aside.",
        "Provider fined $4,000 for the breach. The amount includes legal fees.",
        "Provider fined $4,000 for the breach, inclusive of the levy",
        "Provider fined $4,000 for the breach, with fees included",
        "Provider warned and director fined $4,000 for the breach",
        "Provider warned while service fined $4,000 for the breach",
        "Provider fined $4,000. for a breach",
    ],
)
def test_round_3_wordings_give_null(text):
    value, note = fine_amount_and_note(text)
    assert value is None and note, text


def test_a_personal_name_leading_an_organisation_row_headline_gives_null():
    row = _row("Example Kids Pty Ltd", "<p>Jane Example fined $4,000 for a breach</p>")
    assert row["penalty_amount_aud"] is None


@pytest.mark.parametrize(
    ("subject", "details", "amount"),
    [
        (
            "Example Kids Pty Ltd",
            '<p>Provider fined <a href="/x.pdf">$4,000</a> for a breach</p>',
            4000,
        ),
        ("Example Kids Pty Ltd", "<p>Fined $4,000 for a breach</p>", 4000),
        ("Example Kids Pty Ltd", "<p>Example Kids Pty Ltd fined $4,000 for a breach</p>", 4000),
        ("Example Kids Pty Ltd", "<p>A total fine of $4,000 for the breach.</p>", 4000),
        ("Educator", "<p>Educator fined $4,000 for a breach</p>", 4000),
    ],
)
def test_the_rows_own_subject_still_records(subject, details, amount):
    assert _row(subject, details)["penalty_amount_aud"] == amount
