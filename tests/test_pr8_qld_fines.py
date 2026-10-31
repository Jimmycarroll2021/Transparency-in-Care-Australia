"""PR #8: QLD fines fail closed. Per-offence wording tied to the amount through up to three
intervening words, '$N apiece', and counted amount occurrences."""

import pytest
from scrapers.parse_qld_enforcement import (
    FINE_NOT_RECORDED_NOTE,
    FINE_NOT_SINGLE_TOTAL_NOTE,
    FINE_PER_OFFENCE_NOTE,
    fine_amount_and_note,
)


@pytest.mark.parametrize(
    "text",
    [
        "Provider fined $4,000 for each of 3 offences",
        "Provider fined $4,000 for each of the three offences",
        "Provider fined $4,000 for each of 12 breaches",
        "Provider fined $4,000 per each offence",
        "Provider fined $4,000 apiece",
        "Provider fined $4,000 for every one of the charges",
    ],
)
def test_per_offence_wording_tied_through_intervening_words_gives_null(text):
    assert fine_amount_and_note(text) == (None, FINE_PER_OFFENCE_NOTE)


def test_a_fine_on_counts_is_not_a_recognised_single_total():
    # PR #9: "fined $N on ..." is not one of the recognised single-total forms.
    text = "Provider fined $12,000 on three counts of failing to supervise"
    assert fine_amount_and_note(text) == (None, FINE_NOT_SINGLE_TOTAL_NOTE)


def test_two_identical_fines_give_null():
    text = "Provider fined $5,000 for one breach and fined $5,000 for one breach"
    assert fine_amount_and_note(text) == (None, FINE_NOT_RECORDED_NOTE)


@pytest.mark.parametrize(
    "text",
    [
        "Provider fined a total of $12,000",
        "Provider was fined $12,000 after multiple breaches identified between 2020 and 2022",
        "Provider fined $12,000 for multiple incidents including multiple children leaving the service",
    ],
)
def test_a_single_tied_total_is_recorded(text):
    assert fine_amount_and_note(text) == (12000, None)
