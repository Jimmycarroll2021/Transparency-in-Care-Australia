"""Codex round 3, finding 3: a data-driven layer for the prose rule, plus the month rule.

The layer is an in-memory set of the personal names this run withholds or classifies as an
individual. It is never written. All names here are synthetic.
"""

import csv

import pytest
from scrapers import common
from scrapers import profile_providers as pp

PROSE_NOTE = "free text withheld: may name an individual"


# --- month rule --------------------------------------------------------------------------------


def test_month_used_as_a_given_name_is_flagged():
    assert pp.prose_may_name_person("The educator April Example left the room.")
    assert pp.prose_may_name_person("Notice issued to June Sample")


@pytest.mark.parametrize(
    "text",
    [
        "Compliance notice issued in April 2025",
        "From 1 May 2025 the conditions apply.",
        "In May the Regulatory Authority issued a notice.",
        "Between March and April, no action.",
    ],
)
def test_plain_dates_are_not_flagged(text):
    assert not pp.prose_may_name_person(text)


# --- the name set ------------------------------------------------------------------------------


def _names(*subjects):
    names = pp.PersonNames()
    for s in subjects:
        names.add_subject(s)
    return names


def test_name_set_matches_full_names_case_insensitively():
    names = _names("Ms Jane Example and Mr John Sample")
    assert names.found_in("the educator jane example left a child alone")
    assert names.found_in("JOHN SAMPLE was told")
    assert not names.found_in("the example given in the notice")


def test_name_set_matches_a_known_surname_only_when_capitalised_and_four_letters():
    names = _names("Jane Q Example", "Al Ng")
    assert names.found_in("Example was told to supervise")
    assert not names.found_in("for example, the gate")
    assert not names.found_in("Ng left")  # surname under four letters is not used alone
    assert names.found_in("al ng left")  # the full name still is


def test_name_set_takes_the_surname_of_a_family_trust_and_ignores_organisations():
    names = _names("Example Family Trust", "Sunny Meadow Early Learning Pty Ltd")
    assert names.found_in("Example breached section 165")
    assert not names.found_in("Sunny Meadow Early Learning breached section 165")


def test_prose_rule_uses_the_name_set_for_lowercase_names():
    names = _names("Jane Example")
    assert not pp.prose_may_name_person("notice given to jane example on site")
    assert pp.prose_may_name_person("notice given to jane example on site", person_names=names)


def test_withhold_prose_uses_names_withheld_elsewhere_in_the_same_call():
    withheld = {"notes": common.FREE_TEXT_WITHHELD_NOTE, "_subject_raw": "Jane Example"}
    org = {
        "service_name": "Sunny Meadow Early Learning",
        "provider_name": "Example Kids Pty Ltd",
        "action_type_raw": "Compliance notice",
        "reason": "the educator jane example left children unsupervised",
        "notes": None,
    }
    counts = common.withhold_prose_naming_people([withheld, org])
    assert counts == {"reason": 1}
    assert org["reason"] is None and org["notes"] == PROSE_NOTE


def test_withhold_prose_uses_the_run_wide_name_set(monkeypatch):
    monkeypatch.setattr(common, "_PERSON_NAMES", _names("Jane Example"))
    row = {"action_type_raw": "Notice", "reason": "given to jane example", "notes": None}
    common.withhold_prose_naming_people([row])
    assert row["reason"] is None


def test_acecqa_names_come_only_from_withheld_legal_names(tmp_path):
    path = tmp_path / "providers.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["provider_approval_number", "Legal Name"])
        w.writeheader()
        w.writerow({"provider_approval_number": "PR-1", "Legal Name": "Jane Example"})
        w.writerow({"provider_approval_number": "PR-2", "Legal Name": "Sunny Meadow Pty Ltd"})
    names = pp.acecqa_person_names(path, abr_types={})
    assert names.found_in("jane example")
    assert not names.found_in("Sunny Meadow")


def test_name_set_is_never_written(tmp_path, monkeypatch):
    # The set lives in memory only; the class has no writer and pickling is refused.
    import pickle

    with pytest.raises(TypeError):
        pickle.dumps(_names("Jane Example"))


# --- every parser notes the raw subject of a withheld row, in memory only ---------------------


def test_parsers_note_the_withheld_subject_in_memory_and_not_in_rows():
    from scrapers.parse_tas_enforcement import INDEX_URL, parse_page
    from scrapers.parse_wa_enforcement import parse_wa_html_table

    from tests.test_cth_ccs_enforcement import INDIVIDUAL, page
    from tests.test_cth_ccs_enforcement import rows as cth_rows
    from tests.test_nsw_enforcement import _withheld_nsw
    from tests.test_qld_enforcement import privacy_rows
    from tests.test_sa_enforcement import CURRENT_FIXTURE, rows_for
    from tests.test_tas_enforcement import TAS_HTML
    from tests.test_vecra_enforcement import rows as vecra_rows
    from tests.test_wa_enforcement import SAMPLE_TABLE_HTML

    tas_html = TAS_HTML.replace(
        "Lady Gowrie Tasmania Inc, PR-00005936", "Tessa Sample, PR-00005936"
    )
    cases = [
        (lambda: cth_rows(page(INDIVIDUAL)), "Olive Sampleby"),
        (lambda: [_withheld_nsw()], "Jane Q Citizen"),
        (lambda: list(privacy_rows().values()), "Jane Example"),
        (lambda: rows_for(CURRENT_FIXTURE), "Jane Citizen"),
        (lambda: parse_page(tas_html, page_url=INDEX_URL, captured_at="x"), "Tessa Sample"),
        (lambda: vecra_rows(), "Jane Citizen"),
        (lambda: parse_wa_html_table(SAMPLE_TABLE_HTML, "s.html", "x"), "Mara Sample"),
    ]
    for build, name in cases:
        common.reset_run_names()
        rows = build()
        names = common.run_person_names()
        assert names is not None and names.found_in(name.lower()), name
        assert all(name not in str(r) for r in rows), name
    common.reset_run_names()


def test_reparse_collects_names_without_writing(monkeypatch):
    from scrapers import reparse_offline as ro

    class Fake:
        writes = 0

        @staticmethod
        def write_processed(name, rows, *args, **kwargs):
            Fake.writes += 1

        @staticmethod
        def main(argv):
            Fake.write_processed("x", [{"_subject_raw": "Jane Example"}, {"_subject_raw": None}])
            return 0

    monkeypatch.setattr(ro, "PARSERS", [Fake])
    monkeypatch.setattr(ro, "acecqa_person_names", lambda: pp.PersonNames())
    names = ro.collect_person_names()
    assert names.found_in("jane example")
    assert Fake.writes == 0
    assert Fake.write_processed is not None


# --- Codex round 4, finding 3: a month as a given name enters the name set -----------------


def test_month_named_person_enters_the_name_set():
    names = _names("April Example")
    assert names.found_in("notice given to april example on site")
    assert pp.prose_may_name_person("notice given to april example on site", person_names=names)
    assert not names.found_in("compliance notice issued in april 2025")
    assert not pp.prose_may_name_person("issued in april 2025", person_names=names)


def test_withheld_month_named_subject_nulls_lowercase_prose():
    withheld = {"notes": common.FREE_TEXT_WITHHELD_NOTE, "_subject_raw": "April Example"}
    org = {
        "provider_name": "Example Kids Pty Ltd",
        "action_type_raw": "Compliance notice",
        "reason": "the educator april example left children unsupervised in april 2025",
        "notes": None,
    }
    common.withhold_prose_naming_people([withheld, org])
    assert org["reason"] is None
    dated = {"action_type_raw": "Notice", "reason": "issued in april 2025", "notes": None}
    common.withhold_prose_naming_people([withheld, dated])
    assert dated["reason"] == "issued in april 2025"


def test_month_alone_or_month_with_stopword_is_not_a_name():
    names = _names("April", "May Regulation")
    assert len(names) == 0
