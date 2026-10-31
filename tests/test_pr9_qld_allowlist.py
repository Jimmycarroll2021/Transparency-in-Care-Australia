"""PR #9: QLD fines are recorded only from a closed set of single-total forms, with no
qualifier anywhere in the text. All wording is synthetic."""

import pytest
from scrapers.parse_qld_enforcement import (
    FINE_NOT_RECORDED_NOTE,
    FINE_NOT_SINGLE_TOTAL_NOTE,
    FINE_PER_OFFENCE_NOTE,
    fine_amount_and_note,
)


@pytest.mark.parametrize(
    ("text", "note"),
    [
        ("Provider fined $4,000 on each of three counts", FINE_PER_OFFENCE_NOTE),
        ("Provider fined $4,000 in respect of each offence", FINE_PER_OFFENCE_NOTE),
        ("Provider fined $4,000 for each failure to supervise", FINE_PER_OFFENCE_NOTE),
        ("Provider fined $4,000 for each of the three separate offences", FINE_PER_OFFENCE_NOTE),
        ("Provider fined $4,000 a time for three breaches", FINE_PER_OFFENCE_NOTE),
        ("Provider fined $4,000 x 3", FINE_PER_OFFENCE_NOTE),
        ("Provider fined $4,000 x3 for breaches", FINE_PER_OFFENCE_NOTE),
        ("Provider fined $4,000 three times", FINE_PER_OFFENCE_NOTE),
        ("Two providers fined $4,000 and $6,000 respectively", FINE_PER_OFFENCE_NOTE),
        ("Provider fined $12,000 including costs", FINE_NOT_RECORDED_NOTE),
        ("Provider fined $12,000 plus costs", FINE_NOT_RECORDED_NOTE),
        ("Provider fined $12,000 and ordered to pay costs", FINE_NOT_RECORDED_NOTE),
        ("Provider fined $12,000, wholly suspended", FINE_NOT_SINGLE_TOTAL_NOTE),
        ("Provider fined $12,000, part-suspended", FINE_NOT_SINGLE_TOTAL_NOTE),
        ("Provider fined $12,000, partially paid", FINE_NOT_SINGLE_TOTAL_NOTE),
        ("Provider fined $12,000 on conviction", FINE_NOT_SINGLE_TOTAL_NOTE),
        ("Provider ordered to pay $12,000 as a penalty", FINE_NOT_SINGLE_TOTAL_NOTE),
    ],
)
def test_wording_outside_the_single_total_forms_gives_null(text, note):
    assert fine_amount_and_note(text) == (None, note)


@pytest.mark.parametrize(
    ("text", "amount"),
    [
        ("Provider fined $23,000 after multiple breaches", 23000),
        (
            "Provider fined $34,500 for multiple incidents including a child being left on the bus",
            34500,
        ),
        ("Provider fined a total of $12,000", 12000),
        ("Provider was fined $8,000.", 8000),
        ("Provider has been fined $8,000", 8000),
        ("Total fine of $9,000 for missing child", 9000),
        ("Provider fined $7,000 following an incident", 7000),
        ("Provider fined $7,000 in relation to supervision", 7000),
        ("Provider fined $7,000 over a missing child", 7000),
    ],
)
def test_a_recognised_single_total_is_recorded(text, amount):
    assert fine_amount_and_note(text) == (amount, None)


def test_a_grouped_amount_is_never_cut_at_its_comma():
    # The form must not take "$2" from "$2,000" and the comma for the end of the clause.
    assert fine_amount_and_note("Provider fined $2,000 Prosecution") == (
        None,
        FINE_NOT_SINGLE_TOTAL_NOTE,
    )
