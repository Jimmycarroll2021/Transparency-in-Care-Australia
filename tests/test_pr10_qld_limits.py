"""PR #10: Codex round 4 known limitations on QLD fines, failing closed. All names and wording
are synthetic."""

import pytest
from scrapers.parse_qld_enforcement import fine_amount_and_note

from tests.test_pr9_round1 import _row


@pytest.mark.parametrize(
    "headline",
    [
        "Provider; Jane Example was fined $8,125",
        "Provider warned; Other Kids Pty Ltd was fined $4,000",
        "Provider warned. Other Kids Pty Ltd was fined $4,000 for a breach",
        "Provider: Jane Example fined $4,000 for a breach",
    ],
)
def test_a_clause_break_before_fined_on_a_provider_row_gives_null(headline):
    assert _row("Example Kids Pty Ltd", f"<p>{headline}</p>")["penalty_amount_aud"] is None


@pytest.mark.parametrize(
    "text",
    [
        "Provider fined $4,000 for a breach. The sum includes court expenses.",
        "Provider fined $4,000 for a breach. The amount includes the levy.",
        "Provider fined $4,000 for a breach, including disbursements",
        "Provider fined $4,000 for a breach. The fine was stayed.",
        "Provider fined $4,000 for a breach, subject to a stay of execution",
        "Provider fined $4,000 for a breach. The figure was discharged.",
        "Provider fined $4,000 for a breach. Payment was deferred.",
        "Provider fined $4,000 for a breach. Payment was postponed.",
        "Provider fined $4,000 for a breach. The fine was imposed jointly.",
        "Provider fined $4,000 for a breach under a joint order",
        "Provider fined $4,000 for a breach with two related parties and others",
        "Provider fined $4,000 for a breach, shared with a related party",
        "Provider fined $4,000 for a breach, apportioned between parties",
    ],
)
def test_round_4_limitations_give_null(text):
    value, note = fine_amount_and_note(text)
    assert value is None and note, text


@pytest.mark.parametrize(
    ("subject", "headline", "amount"),
    [
        ("Example Kids Pty Ltd", "Approved provider fined $12,000 for missing child", 12000),
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
        (
            "Jane Example",
            "Family day care educator was fined $2,500 for leaving children unattended in a public library",
            2500,
        ),
        ("Jane Example", "Educator fined $2,000 for continuing to work while prohibited", 2000),
        (
            "Example Kids Pty Ltd",
            "Approved provider fined $2,500 for providing false and misleading information "
            "and documents in relation to the number of educators engaged with the service",
            2500,
        ),
    ],
)
def test_the_committed_shapes_still_record(subject, headline, amount):
    row = _row(subject, f'<p>{headline}</p><p><a href="/d.pdf">Prosecution</a></p>')
    assert row["penalty_amount_aud"] == amount
