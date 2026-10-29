from __future__ import annotations

from datetime import date

import pytest
from scrapers import join_enforcement as je

TYPES = ["compliance_notice", "prosecution", "approval_cancelled", "other"]
END = date(2026, 10, 28)
WINDOW = je.window_bounds(END)


def svc(se, pr, name, state="QLD", suburb="Mt Gravatt", **extra):
    row = {
        "service_approval_number": se,
        "provider_approval_number": pr,
        "ServiceName": name,
        "State": state,
        "Suburb": suburb,
        "Postcode": "4000",
        "ServiceType": "Centre-Based Care",
        "OverallRating": "Meeting NQS",
        "RatingsIssued": "Dec 2022",
        "snapshot_last_modified": "Wed, 28 Oct 2026 19:28:15 GMT",
    }
    row.update(extra)
    return row


def prof(pr, legal, count, withheld="false", form="company", states="QLD"):
    return {
        "provider_approval_number": pr,
        "legal_name": legal,
        "trading_name": "",
        "name_withheld": withheld,
        "entity_form": form,
        "provider_state": "QLD",
        "service_count": str(count),
        "states_operated_in": states,
    }


def act(
    rid="r1",
    jur="NSW",
    se="",
    pr="",
    name="",
    suburb="",
    state="",
    atype="compliance_notice",
    when="2026-01-01",
    notes="",
):
    return {
        "record_id": rid,
        "jurisdiction": jur,
        "service_approval_number": se,
        "provider_approval_number": pr,
        "service_name": name,
        "suburb": suburb,
        "state": state,
        "action_type": atype,
        "action_type_raw": atype,
        "date_issued": when,
        "notes": notes,
    }


@pytest.fixture
def spine():
    services = [
        svc("SE-00000001", "PR-00000001", "Little Gems Early Learning", suburb="Mt Gravatt"),
        svc("SE-00000002", "PR-00000001", "Sunny Days Pty Ltd", suburb="Carina"),
        svc("SE-00000003", "PR-00000002", "Sunny Days", suburb="Carina"),
        svc("SE-00000004", "PR-00000002", "Sunny Days", suburb="Indooroopilly"),
        svc("SE-00000005", "PR-00000002", "Unique Kids", suburb="Toowong"),
        svc("SE-00000006", "PR-00000003", "Unique Kids", state="NSW", suburb="Toowong"),
        svc("SE-00000007", "PR-00000003", "Quiet Place", state="SA", suburb="Adelaide"),
    ]
    profiles = [
        prof("PR-00000001", "Gems Pty Ltd", 2),
        prof("PR-00000002", "Days Pty Ltd", 3),
        prof("PR-00000003", None, 2, withheld="true", form="likely_individual"),
    ]
    return je.Spine(services, profiles)


def test_service_key_join(spine):
    (row,) = je.join_actions([act(se="SE-00000001", pr="PR-00000001")], spine)
    assert row["join_key_kind"] == "service"
    assert row["match_confidence"] == "exact_key"
    assert row["acecqa_service_name"] == "Little Gems Early Learning"
    assert row["acecqa_provider_approval_number"] == "PR-00000001"
    assert row["acecqa_provider_legal_name"] == "Gems Pty Ltd"
    assert row["provider_service_count"] == "2"
    assert row["acecqa_overall_rating"] == "Meeting NQS"
    assert row["acecqa_rating_issued"] == "Dec 2022"


def test_service_key_missing_from_spine_is_unmatched(spine):
    (row,) = je.join_actions([act(se="SE-09999999")], spine)
    assert row["join_key_kind"] == "none"
    assert row["match_confidence"] == "unmatched"
    assert "not in the spine" in row["join_note"]


def test_provider_level_join(spine):
    rows = je.join_actions(
        [act(pr="PR-00000001", atype="approval_cancelled"), act(rid="r2", pr="PR-09999999")], spine
    )
    assert rows[0]["join_key_kind"] == "provider"
    assert rows[0]["acecqa_service_approval_number"] is None
    assert rows[0]["acecqa_provider_legal_name"] == "Gems Pty Ltd"
    assert rows[1]["match_confidence"] == "unmatched"


def test_withheld_provider_name_stays_null_on_key_join(spine):
    (row,) = je.join_actions([act(pr="PR-00000003")], spine)
    assert row["join_key_kind"] == "provider"
    assert row["acecqa_provider_legal_name"] is None
    assert row["provider_entity_form"] == "likely_individual"


def test_normalise_service_name():
    assert je.normalise_service_name("St Peter's  Outside-School Hours Care Pty. Ltd.") == (
        "ST PETERS OUTSIDE SCHOOL HOURS CARE"
    )
    assert je.normalise_service_name("The Kids & Co Inc") == "KIDS AND CO"
    assert je.normalise_service_name(None) == ""


def test_qld_name_unique_match(spine):
    (row,) = je.join_actions(
        [act(jur="QLD", name="  LITTLE GEMS early learning ", atype="prosecution")], spine
    )
    assert row["join_key_kind"] == "name_match"
    assert row["match_confidence"] == "name_only"
    assert row["acecqa_service_approval_number"] == "SE-00000001"


def test_qld_name_restricted_to_qld(spine):
    # "Unique Kids" exists once in QLD and once in NSW: the QLD restriction makes it unique
    (row,) = je.join_actions([act(jur="QLD", name="Unique Kids")], spine)
    assert row["acecqa_service_approval_number"] == "SE-00000005"
    # a QLD-register name that only exists outside QLD must not match
    (row,) = je.join_actions([act(jur="QLD", name="Quiet Place")], spine)
    assert row["match_confidence"] == "unmatched"


def test_qld_suburb_disambiguates(spine):
    (row,) = je.join_actions([act(jur="QLD", name="Sunny Days", suburb="Carina")], spine)
    # two Carina candidates ("Sunny Days Pty Ltd" and "Sunny Days" normalise alike) -> ambiguous
    assert row["match_confidence"] == "unmatched"
    assert "ambiguous: 2 candidates share name and suburb" in row["join_note"]
    (row,) = je.join_actions([act(jur="QLD", name="Sunny Days", suburb="Indooroopilly")], spine)
    assert row["match_confidence"] == "name_and_suburb"
    assert row["acecqa_service_approval_number"] == "SE-00000004"


def test_qld_ambiguous_left_unmatched_with_count(spine):
    (row,) = je.join_actions([act(jur="QLD", name="Sunny Days")], spine)
    assert row["join_key_kind"] == "none"
    assert row["match_confidence"] == "unmatched"
    assert row["join_note"] == "ambiguous: 3 candidates share the name"
    assert row["acecqa_service_approval_number"] is None


def test_qld_withheld_individual_never_name_matched(spine):
    (row,) = je.join_actions(
        [
            act(
                jur="QLD",
                name="Little Gems Early Learning",
                notes="subject is an individual; name withheld",
            )
        ],
        spine,
    )
    assert row["match_confidence"] == "unmatched"
    assert "name match not attempted" in row["join_note"]


def test_non_qld_rows_without_keys_are_not_name_matched(spine):
    (row,) = je.join_actions([act(jur="NSW", name="Little Gems Early Learning")], spine)
    assert row["match_confidence"] == "unmatched"


def test_occurrence_numbering_and_duplicate_flag(spine):
    rows = je.join_actions(
        [
            act(rid="same", se="SE-00000001"),
            act(rid="other", se="SE-00000001"),
            act(rid="same", se="SE-00000001", notes="duplicate row in source"),
            act(rid="same", se="SE-00000001", notes="duplicate row in source"),
        ],
        spine,
    )
    assert [r["occurrence"] for r in rows] == [1, 1, 2, 3]
    assert [r["counted_in_totals"] for r in rows] == [True, True, False, False]


@pytest.mark.parametrize(
    ("end", "start"),
    [
        (date(2026, 10, 28), date(2024, 10, 29)),
        (date(2028, 2, 29), date(2026, 3, 1)),  # 29 Feb clamps to 28 Feb two years earlier
        (date(2026, 1, 31), date(2024, 2, 1)),
    ],
)
def test_window_start(end, start):
    assert je.window_bounds(end) == (start, end)


def test_snapshot_date_parses_http_date(spine):
    assert je.snapshot_date(list(spine.services.values())) == date(2026, 10, 28)


def test_window_boundaries_in_counts(spine):
    actions = [
        act(rid="a", se="SE-00000001", when="2024-10-28"),  # one day before the window
        act(rid="b", se="SE-00000001", when="2024-10-29"),  # first day
        act(rid="c", se="SE-00000001", when="2026-10-28"),  # last day
        act(rid="d", se="SE-00000001", when="2026-10-29"),  # after the window
        act(rid="e", se="SE-00000001", when=None, atype="prosecution"),  # undated
    ]
    joined = je.join_actions(actions, spine)
    service_rows, provider_rows = je.aggregate(joined, spine, TYPES, WINDOW, cth_present=False)
    s1 = next(r for r in service_rows if r["service_approval_number"] == "SE-00000001")
    assert s1["actions_total"] == 5
    assert s1["actions_last_24_months"] == 2
    assert s1["count_prosecution"] == 1
    assert s1["last24m_prosecution"] == 0
    assert s1["first_action_date"] == "2024-10-28"
    assert s1["last_action_date"] == "2026-10-29"
    p1 = next(r for r in provider_rows if r["provider_approval_number"] == "PR-00000001")
    assert p1["actions_last_24_months"] == 2
    assert p1["actions_last_24_months_per_service"] == 1.0
    assert p1["service_count"] == 2


def test_zero_count_rows_for_services_without_actions(spine):
    joined = je.join_actions([act(se="SE-00000001")], spine)
    service_rows, provider_rows = je.aggregate(joined, spine, TYPES, WINDOW, cth_present=False)
    assert len(service_rows) == len(spine.services)
    s2 = next(r for r in service_rows if r["service_approval_number"] == "SE-00000002")
    assert s2["actions_total"] == 0
    assert s2["actions_last_24_months"] == 0
    assert all(s2[f"count_{t}"] == 0 and s2[f"last24m_{t}"] == 0 for t in TYPES)
    assert s2["first_action_date"] is None
    assert "not evidence of safety" in s2["coverage_note"]
    sa = next(r for r in service_rows if r["service_approval_number"] == "SE-00000007")
    assert sa["jurisdictions_publishing"] == "SA register: not yet collected"
    assert len(provider_rows) == len(spine.profiles)


def test_provider_rollup_keeps_types_apart_and_counts_levels(spine):
    actions = [
        act(rid="a", se="SE-00000001", atype="compliance_notice"),
        act(rid="b", se="SE-00000002", atype="compliance_notice"),
        act(rid="c", se="SE-00000002", atype="compliance_notice", when="2026-02-02"),
        act(rid="d", pr="PR-00000001", atype="approval_cancelled"),
        act(rid="e", jur="QLD", name="Little Gems Early Learning", atype="prosecution"),
        act(rid="f", se="SE-00000001", notes="duplicate row in source"),
    ]
    joined = je.join_actions(actions, spine)
    service_rows, provider_rows = je.aggregate(joined, spine, TYPES, WINDOW, cth_present=False)
    p1 = next(r for r in provider_rows if r["provider_approval_number"] == "PR-00000001")
    assert p1["service_level_actions"] == 4
    assert p1["provider_level_actions"] == 1
    assert p1["actions_total"] == 5
    assert p1["count_compliance_notice"] == 3
    assert p1["count_prosecution"] == 1
    assert p1["count_approval_cancelled"] == 1
    assert p1["services_with_any_action"] == 2
    s1 = next(r for r in service_rows if r["service_approval_number"] == "SE-00000001")
    assert s1["actions_matched_by_name"] == 1
    assert s1["actions_total"] == 2  # duplicate row not counted
    p3 = next(r for r in provider_rows if r["provider_approval_number"] == "PR-00000003")
    assert p3["legal_name"] is None
    assert p3["name_withheld"] == "true"


def test_report_counts_and_excludes_withheld_from_top(spine):
    actions = [
        act(rid="a", se="SE-00000001"),
        act(rid="b", se="SE-00000006"),  # provider PR-00000003 is name-withheld
        act(rid="c", se="SE-00000006", when="2026-03-03"),
        act(rid="d", jur="QLD", name="Nope"),
        act(rid="e", se="SE-09999999"),
    ]
    joined = je.join_actions(actions, spine)
    service_rows, provider_rows = je.aggregate(joined, spine, TYPES, WINDOW, cth_present=False)
    report = je.build_report(joined, service_rows, provider_rows, TYPES, WINDOW, [], [])
    nsw = report["per_jurisdiction"]["NSW"]
    assert (nsw["rows_in"], nsw["joined_exact_key"], nsw["unmatched"]) == (4, 3, 1)
    assert nsw["unmatched_examples"] == [{"record_id": "e", "action_type": "compliance_notice"}]
    assert report["per_jurisdiction"]["QLD"]["unmatched"] == 1
    assert report["overall"]["match_rate"] == 0.6
    top = report["top_20_providers_by_actions_last_24_months"]
    assert [t["provider_approval_number"] for t in top] == ["PR-00000001"]
    assert top[0]["service_count"] == 2
    assert report["providers_with_action_last_24_months"]["count"] == 2
    assert report["providers_with_action_last_24_months"]["of_which_name_not_withheld"] == 1


def test_transitive_inputs_follow_provenance(tmp_path, monkeypatch):
    monkeypatch.setattr(je, "PROJECT_ROOT", tmp_path)
    (tmp_path / "a.csv").write_text("x\n")
    (tmp_path / "a.provenance.json").write_text('{"raw_inputs": ["b.csv", "raw/one.gz"]}')
    (tmp_path / "b.csv").write_text("x\n")
    (tmp_path / "b.provenance.json").write_text('{"raw_inputs": ["raw/two.gz", "raw/one.gz"]}')
    got = je.transitive_inputs([tmp_path / "a.csv"])
    assert [p.name for p in got] == ["a.csv", "b.csv", "one.gz", "two.gz"]
