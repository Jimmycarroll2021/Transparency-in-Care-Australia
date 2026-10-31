"""PR #9, Codex round 1: the total form is read from the headline alone; guards and the amount
count run over all of the row's text. All names and wording are synthetic."""

import pytest
from scrapers.parse_qld_enforcement import (
    FINE_NOT_SINGLE_TOTAL_NOTE,
    INDEX_URL,
    fine_amount_and_note,
    parse_register,
)

HEADER = (
    "<tr><th><p>Provider or individual name</p><p>Service name</p></th>"
    "<th>Date of action</th><th>Details</th><th>Breaches (if applicable)</th></tr>"
)


def _row(subject: str, details: str) -> dict:
    html = f"""<html><body><h2>2026</h2><table>{HEADER}
    <tr><td><p>{subject}</p></td><td>01/02/2026</td><td>{details}</td><td>N/A</td></tr>
    </table></body></html>"""
    return parse_register(
        html, page_url=INDEX_URL, captured_at="2026-10-31T00:00:00+00:00", source_snapshot="x"
    )[0]


@pytest.mark.parametrize(
    "text",
    [
        # a clause end at , ; or : is not the end of the form; rates
        "Provider fined $4,000, a day",
        "Provider fined $4,000; a day",
        "Provider fined $4,000: per day",
        "Provider fined $4,000 daily for the breach",
        "Provider fined $4,000 an hour for the breach",
        # prospective and negated
        "Provider could be fined $4,000",
        "Provider faces being fined $4,000",
        "Provider may be fined $4,000",
        "Provider was not fined $4,000",
        # superseded, maximum, payment terms
        "Provider originally fined $4,000, reduced to 2000",
        "Provider fined $4,000, the maximum",
        "Provider fined $4,000 for the breach, with 2000 to be paid",
        "Provider fined $4,000 for the breach after an appeal",
        # another subject, a second amount in words
        "Provider warned; director fined $4,000",
        "Provider fined $4,000; director fined 2000 dollars",
        # multipliers
        "Provider fined $4,000 multiplied by three",
        "Provider fined $4,000 twice",
        "Provider fined $4,000 for both offences at that amount",
        # unsupported formats: never a silent null
        "Provider fined AUD 4,000 for the breach",
        "Provider fined A$4,000 for the breach",
        "Provider fined 4,000 dollars for the breach",
        "Provider fined \uff044,000 for the breach",
    ],
)
def test_codex_round_1_wordings_give_null_with_a_note(text):
    value, note = fine_amount_and_note(text)
    assert value is None, text
    assert note, text


@pytest.mark.parametrize(
    "text",
    [
        "Provider fined $4,000 on each of three counts",
        "Provider fined $4,000 in respect of each offence",
        "Provider fined $4,000 for each failure to supervise",
        "Provider fined $4,000 for each of the three separate offences",
        "Provider fined $4,000 a time for three breaches",
        "Provider fined $4,000 x 3",
        "Provider fined $12,000 including costs",
        "Provider fined $12,000 plus costs",
        "Provider fined $12,000, wholly suspended",
    ],
)
def test_the_pr8_round_wordings_stay_null(text):
    value, note = fine_amount_and_note(text)
    assert value is None and note, text


@pytest.mark.parametrize(
    ("text", "amount"),
    [
        ("Provider fined $23,000 after multiple breaches", 23000),
        (
            "Provider fined $34,500 for multiple incidents including a child being left on the bus",
            34500,
        ),
        ("Provider was fined $8,000.", 8000),
        ("Provider fined a total of $12,000", 12000),
        ("Provider fined $9,000 after breaches identified between May 2020 and May 2022", 9000),
        ("Provider fined\u00a0$\u00a04,000 for the breach", 4000),
    ],
)
def test_a_recognised_single_total_is_recorded(text, amount):
    assert fine_amount_and_note(text) == (amount, None)


def test_a_fine_ending_the_headline_with_a_prosecution_label_is_recorded():
    row = _row(
        "Example Kids Pty Ltd",
        '<p>Provider fined $2,000</p><p><a href="/docs/k.pdf">Prosecution</a></p>',
    )
    assert row["penalty_amount_aud"] == 2000


def test_a_later_unlinked_paragraph_is_checked():
    row = _row(
        "Example Kids Pty Ltd",
        "<p>Provider fined $2,000 for missing child</p><p>The amount applies for each offence.</p>"
        '<p><a href="/docs/k.pdf">Prosecution</a></p>',
    )
    assert row["penalty_amount_aud"] is None
    assert "penalty amount not recorded" in row["notes"]


def test_a_second_amount_in_a_later_paragraph_gives_null():
    row = _row(
        "Example Kids Pty Ltd",
        "<p>Provider fined $2,000 for missing child</p><p>Costs were set at $500.</p>",
    )
    assert row["penalty_amount_aud"] is None


def test_a_role_word_in_a_provider_row_gives_null():
    row = _row(
        "Example Kids Pty Ltd",
        '<p>Provider warned; director fined $4,000</p><p><a href="/docs/k.pdf">Prosecution</a></p>',
    )
    assert row["penalty_amount_aud"] is None
    assert FINE_NOT_SINGLE_TOTAL_NOTE in row["notes"]


def test_a_role_word_naming_the_subject_of_an_individual_row_is_kept():
    row = _row(
        "Jane Example",
        "<p>Educator fined $2,000 for continuing to work while prohibited</p>"
        '<p><a href="/docs/j.pdf">Prosecution</a></p>',
    )
    assert row["penalty_amount_aud"] == 2000


def test_every_other_guard_still_applies_on_an_individual_row():
    row = _row(
        "Jane Example",
        '<p>Educator could be fined $2,000</p><p><a href="/docs/j.pdf">Prosecution</a></p>',
    )
    assert row["penalty_amount_aud"] is None
    assert fine_amount_and_note("Educator could be fined $2,000", subject_is_person=True) == (
        None,
        FINE_NOT_SINGLE_TOTAL_NOTE,
    )
