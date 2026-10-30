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
    pname="",
    address="",
    postcode="",
):
    return {
        "record_id": rid,
        "jurisdiction": jur,
        "service_approval_number": se,
        "provider_approval_number": pr,
        "service_name": name,
        "provider_name": pname,
        "address": address,
        "postcode": postcode,
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
        svc("SE-00000007", "PR-00000003", "Quiet Place", state="NT", suburb="Darwin"),
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
    nt = next(r for r in service_rows if r["service_approval_number"] == "SE-00000007")
    assert nt["jurisdictions_publishing"] == "NT register: not yet collected"
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


# ---------------------------------------------------------------------------
# Provider-name stage
# ---------------------------------------------------------------------------


def provider(pr, legal, trading="", state="NSW"):
    return {
        "provider_approval_number": pr,
        "Legal Name": legal,
        "Trading Name": trading,
        "State": state,
    }


@pytest.fixture
def pspine():
    services = [
        svc("SE-00000101", "PR-00000101", "Bright Start Kindy", state="NSW", suburb="Manly"),
        svc("SE-00000102", "PR-00000101", "Bright Start Annex", state="NSW", suburb="Dee Why"),
        svc("SE-00000103", "PR-00000101", "Bright Start Annex", state="NSW", suburb="Collaroy"),
        svc("SE-00000104", "PR-00000101", "Bright Start Kindy", state="VIC", suburb="Carlton"),
        svc("SE-00000201", "PR-00000201", "Twin Care", state="NSW"),
        svc("SE-00000301", "PR-00000301", "Twin Care", state="NSW"),
        svc("SE-00000401", "PR-00000401", "Southern Cross Kids", state="VIC"),
        svc("SE-00000501", "PR-00000501", "Sole Trader Care", state="NSW"),
        svc("SE-00000601", "PR-00000601", "Cross Border Care", state="QLD"),
    ]
    profiles = [
        prof("PR-00000101", "Bright Start Pty Ltd", 4, states="NSW, VIC"),
        prof("PR-00000201", "Twin Holdings Pty Ltd", 1, states="NSW"),
        prof("PR-00000301", "Twin Holdings Proprietary Limited", 1, states="NSW"),
        prof("PR-00000401", "Southern Cross Kids Inc", 1, states="VIC"),
        prof("PR-00000501", None, 1, withheld="true", form="likely_individual", states="NSW"),
        prof("PR-00000601", "Cross Border Pty Ltd", 1, states="QLD"),
    ]
    providers = [
        provider("PR-00000101", "THE BRIGHT START PTY. LIMITED", "Bright Start Kindy", "NSW"),
        provider("PR-00000201", "Twin Holdings Pty Ltd", "", "NSW"),
        provider("PR-00000301", "TWIN HOLDINGS PROPRIETARY LIMITED", "", "NSW"),
        provider("PR-00000401", "Southern Cross Kids Incorporated", "", "VIC"),
        provider("PR-00000501", "Placeholder Person Name", "", "NSW"),
        provider("PR-00000601", "Cross Border Pty Ltd", "", "QLD"),
    ]
    return je.Spine(services, profiles, providers)


def pact(name, *, rid="p1", jur="CTH", state="", service="", notes="", **kw):
    row = act(rid=rid, jur=jur, state=state, notes=notes, name=service, **kw)
    row["provider_name"] = name
    return row


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("The Bright Start Pty. Limited", "BRIGHT START PTY LTD"),
        ("Bright Start Proprietary Limited ABN 12 345 678 901", "BRIGHT START PTY LTD"),
        ("Bright Start Pty Ltd", "BRIGHT START PTY LTD"),
        ("Kids Club Incorporated", "KIDS CLUB INC"),
        ("Acme Services Limited", "ACME SERVICES LTD"),
        ("Corp Pty Ltd ATF Smith Family Trust", "CORP PTY LTD ATF SMITH FAMILY TRUST"),
        ("Kids & Co's  Care", "KIDS AND COS CARE"),
        (None, ""),
    ],
)
def test_normalise_provider_name(raw, expected):
    assert je.normalise_provider_name(raw) == expected


def test_provider_name_unique_match(pspine):
    (row,) = je.join_actions([pact("Bright Start Pty Ltd", state="NSW")], pspine)
    assert row["join_key_kind"] == "provider_name_match"
    assert row["match_confidence"] == "provider_name_unique"
    assert row["acecqa_provider_approval_number"] == "PR-00000101"
    assert row["acecqa_provider_legal_name"] == "Bright Start Pty Ltd"
    assert row["acecqa_service_approval_number"] is None
    # the source row's own key columns stay empty
    assert row["service_approval_number"] is None
    assert row["provider_approval_number"] is None


def test_provider_name_match_on_trading_name(pspine):
    (row,) = je.join_actions([pact("BRIGHT START KINDY", state="NSW")], pspine)
    assert row["acecqa_provider_approval_number"] == "PR-00000101"


def test_provider_name_ambiguous_left_unmatched_with_count(pspine):
    # PR-00000201 and PR-00000301 normalise to the same name
    (row,) = je.join_actions([pact("Twin Holdings Pty Ltd")], pspine)
    assert row["join_key_kind"] == "none"
    assert row["match_confidence"] == "unmatched"
    assert row["acecqa_provider_approval_number"] is None
    assert "ambiguous provider name: 2 candidate providers" in row["join_note"]
    rows = je.join_actions([pact("Twin Holdings Pty Ltd")], pspine)
    report = je.build_report(rows, [], [], TYPES, WINDOW, [], [])
    assert report["per_jurisdiction"]["CTH"]["unmatched_ambiguous_provider_name"] == 1


def test_provider_name_withheld_provider_never_matched(pspine):
    # A name equal to a withheld (likely individual) provider's legal name is never matched.
    (row,) = je.join_actions([pact("Placeholder Person Name", state="NSW")], pspine)
    assert row["match_confidence"] == "unmatched"
    assert row["acecqa_provider_approval_number"] is None


def test_withheld_row_and_null_provider_name_not_attempted(pspine):
    rows = je.join_actions(
        [
            pact(
                "Bright Start Pty Ltd",
                rid="a",
                notes="provider name withheld; subject is an individual",
            ),
            pact(None, rid="b"),
        ],
        pspine,
    )
    assert [r["match_confidence"] for r in rows] == ["unmatched", "unmatched"]
    assert all("provider name:" not in r["join_note"] for r in rows)


def test_provider_name_state_restriction(pspine):
    # Southern Cross Kids Inc only operates in VIC
    (vic,) = je.join_actions([pact("Southern Cross Kids Incorporated", state="VIC")], pspine)
    assert vic["acecqa_provider_approval_number"] == "PR-00000401"
    (nsw,) = je.join_actions([pact("Southern Cross Kids Inc", state="NSW")], pspine)
    assert nsw["match_confidence"] == "unmatched"
    assert "no provider in NSW" in nsw["join_note"]
    # no state: unrestricted
    (none,) = je.join_actions([pact("Southern Cross Kids Inc")], pspine)
    assert none["acecqa_provider_approval_number"] == "PR-00000401"
    # a QLD-register row takes QLD from its jurisdiction when state is blank
    (qld,) = je.join_actions([pact("Southern Cross Kids Inc", jur="QLD")], pspine)
    assert qld["match_confidence"] == "unmatched"
    # a provider registered in one state counts as present where its services are
    (cross,) = je.join_actions([pact("Bright Start Pty Ltd", state="VIC")], pspine)
    assert cross["acecqa_provider_approval_number"] == "PR-00000101"


def test_provider_and_service_pin(pspine):
    (row,) = je.join_actions(
        [pact("Bright Start Pty Ltd", state="NSW", service="Bright Start Kindy Pty Ltd")], pspine
    )
    assert row["match_confidence"] == "provider_and_service_name"
    assert row["join_key_kind"] == "provider_name_match"
    assert row["acecqa_service_approval_number"] == "SE-00000101"
    assert row["acecqa_provider_approval_number"] == "PR-00000101"
    assert row["service_approval_number"] is None  # never set on the source columns


def test_service_pin_needs_unique_name_within_state(pspine):
    # two NSW services share the name: provider match kept, service not pinned
    (row,) = je.join_actions(
        [pact("Bright Start Pty Ltd", state="NSW", service="Bright Start Annex")], pspine
    )
    assert row["match_confidence"] == "provider_name_unique"
    assert row["acecqa_service_approval_number"] is None
    assert "not pinned: 2" in row["join_note"]
    # no state: the same name is also shared by the unrelated-state service, so still unpinned
    (row,) = je.join_actions([pact("Bright Start Pty Ltd", service="Bright Start Kindy")], pspine)
    assert row["match_confidence"] == "provider_name_unique"
    assert row["acecqa_service_approval_number"] is None
    # a service the provider does not run is not pinned
    (row,) = je.join_actions([pact("Bright Start Pty Ltd", service="Twin Care")], pspine)
    assert row["match_confidence"] == "provider_name_unique"
    assert row["acecqa_service_approval_number"] is None


def test_key_matched_and_service_matched_rows_skip_provider_stage(pspine):
    keyed = pact("Bright Start Pty Ltd", se="SE-09999999", state="NSW")
    (row,) = je.join_actions([keyed], pspine)
    assert row["match_confidence"] == "unmatched"  # key absent from spine: not name matched
    assert row["join_note"] == "service key SE-09999999 not in the spine"
    (row,) = je.join_actions([pact("Whoever", se="SE-00000101")], pspine)
    assert row["match_confidence"] == "exact_key"


def test_qld_provider_stage_runs_after_service_name_stage(pspine):
    # service name unknown, provider known: provider-name match; a service-name hit wins first
    (a,) = je.join_actions(
        [pact("Cross Border Pty Ltd", jur="QLD", service="Not A Real Service")], pspine
    )
    assert a["join_key_kind"] == "provider_name_match"
    assert a["match_confidence"] == "provider_name_unique"
    assert a["acecqa_provider_approval_number"] == "PR-00000601"
    (b,) = je.join_actions(
        [pact("Some Other Name", jur="QLD", service="Cross Border Care")], pspine
    )
    assert b["join_key_kind"] == "name_match"
    assert b["match_confidence"] == "name_only"


def test_abn_carried_through_and_withheld_rows_have_none(pspine):
    with_abn = pact(
        "Bright Start Pty Ltd",
        rid="a",
        notes="service_type: X; ccs_identifier: ABN 12345678901; end_date: 1 May 2027",
    )
    spaced = pact("Other Pty Ltd", rid="b", notes="ccs_identifier: ABN 12 345 678 901")
    withheld = pact(
        None,
        rid="c",
        notes="provider name withheld; subject is an individual; ccs_identifier: ABN 12345678901",
    )
    short = pact("Short Pty Ltd", rid="d", notes="ccs_identifier: ABN 1234567")
    plain = pact("Plain Pty Ltd", rid="e", notes="end_date: 1 May 2027")
    rows = je.join_actions([with_abn, spaced, withheld, short, plain], pspine)
    assert [r["abn"] for r in rows] == ["12345678901", "12345678901", None, None, None]
    assert "abn" in je.ALL_COLUMNS


def test_provider_name_match_is_provider_level_and_pin_is_service_level(pspine):
    actions = [
        pact("Bright Start Pty Ltd", rid="a", state="NSW", when="2026-05-05"),
        pact(
            "Bright Start Pty Ltd",
            rid="b",
            state="NSW",
            service="Bright Start Kindy",
            when="2026-05-06",
        ),
        pact("Bright Start Pty Ltd", rid="c", state="NSW", notes="duplicate row in source"),
    ]
    joined = je.join_actions(actions, pspine)
    service_rows, provider_rows = je.aggregate(joined, pspine, TYPES, WINDOW, cth_present=True)
    p = next(r for r in provider_rows if r["provider_approval_number"] == "PR-00000101")
    assert p["provider_level_actions"] == 1
    assert p["service_level_actions"] == 1
    assert p["actions_total"] == 2  # duplicate not counted
    assert p["actions_matched_by_name"] == 2
    assert p["services_with_any_action_last_24_months"] == 1
    s = next(r for r in service_rows if r["service_approval_number"] == "SE-00000101")
    assert s["actions_total"] == 1 and s["actions_matched_by_name"] == 1
    report = je.build_report(joined, service_rows, provider_rows, TYPES, WINDOW, [], [])
    cth = report["per_jurisdiction"]["CTH"]
    assert cth["joined_by_provider_name"] == 3
    assert cth["joined_by_provider_and_service_name"] == 1
    assert cth["joined_by_provider_name_unpinned"] == 2
    assert cth["match_rate"] == 1.0


# ---------------------------------------------------------------------------
# Unlisted spine stage
# ---------------------------------------------------------------------------

SNAPSHOT = date(2026, 10, 28)


def stage(actions, spine):
    joined = je.join_actions(actions, spine)
    stubs = je.add_unlisted_stage(joined, spine, SNAPSHOT)
    return joined, stubs


def stub_for(stubs, key):
    return next(s for s in stubs if s["key"] == key)


def test_stub_from_service_key_uses_only_printed_values(spine):
    joined, stubs = stage(
        [
            act(
                se="SE-09999999",
                pr="PR-09999999",
                name="Old Bluegum Kids",
                pname="Bluegum Holdings Pty Ltd",
                address="1 High St",
                suburb="Ashgrove",
                state="QLD",
                postcode="4060",
                atype="approval_cancelled",
                when="2025-05-05",
            )
        ],
        spine,
    )
    (row,) = joined
    assert row["join_key_kind"] == "service_key_unlisted"
    assert row["match_confidence"] == "exact_key_unlisted"
    assert row["spine_status"] == "not_in_current_register"
    assert row["acecqa_service_approval_number"] is None
    assert row["acecqa_overall_rating"] is None
    service = stub_for(stubs, "SE-09999999")
    assert service["kind"] == "service"
    assert service["name"] == "Old Bluegum Kids"
    assert (service["address"], service["suburb"]) == ("1 High St", "Ashgrove")
    assert (service["state"], service["postcode"]) == ("QLD", "4060")
    assert service["provider_approval_number"] == "PR-09999999"
    assert service["jurisdictions_seen"] == "NSW"
    assert service["first_seen"] == service["last_seen"] == "2025-05-05"
    assert service["row_count"] == 1
    assert service["spine_status"] == "not_in_current_register"
    assert service["note"] == (
        "identity taken from the enforcement register; the approval is absent from the ACECQA "
        "export of 2026-10-28, usually because it has ceased"
    )
    # the printed provider key is also absent, so the provider gets its own stub
    assert stub_for(stubs, "PR-09999999")["name"] == "Bluegum Holdings Pty Ltd"


def test_stub_from_provider_key(spine):
    joined, stubs = stage(
        [act(pr="PR-09999998", pname="Gone Pty Ltd", atype="approval_cancelled", state="NSW")],
        spine,
    )
    assert joined[0]["join_key_kind"] == "provider_key_unlisted"
    assert joined[0]["match_confidence"] == "exact_key_unlisted"
    (provider,) = stubs
    assert provider["kind"] == "provider"
    assert provider["key"] == "PR-09999998"
    assert provider["name"] == "Gone Pty Ltd"
    assert provider["state"] == "NSW"
    assert provider["provider_approval_number"] is None


def test_name_variants_keep_most_recent_and_list_others(spine):
    _, stubs = stage(
        [
            act(rid="a", se="SE-09999999", name="Sunrise Early Learning", when="2025-01-01"),
            act(
                rid="b", se="SE-09999999", name="SUNRISE EARLY LEARNING PTY LTD", when="2025-02-01"
            ),
            act(rid="c", se="SE-09999999", name="Sunrise Kids", when="2026-03-01"),
            act(rid="d", se="SE-09999999", name="Sunrise Childcare", when="2024-06-01"),
        ],
        spine,
    )
    stub = stub_for(stubs, "SE-09999999")
    assert stub["name"] == "Sunrise Kids"
    # newest first; a second spelling that normalises to the same name is listed once
    assert stub["stub_name_variants"] == "SUNRISE EARLY LEARNING PTY LTD | Sunrise Childcare"
    assert stub["row_count"] == 4
    assert (stub["first_seen"], stub["last_seen"]) == ("2024-06-01", "2026-03-01")


def test_withheld_names_stay_null_in_stubs(spine):
    withheld = "provider name withheld: may be an individual"
    _, stubs = stage(
        [
            act(rid="a", pr="PR-09999997", pname="", notes=withheld, address="9 Home St"),
            act(rid="b", pr="PR-09999997", pname="Maybe Named Pty Ltd", when="2025-01-01"),
            act(rid="c", pr="PR-09999996", pname="Jo Citizen", when="2025-01-01"),
            act(rid="d", pr="PR-09999995", pname="Jo Citizen, director of Acme Care Pty Ltd"),
        ],
        spine,
    )
    for key in ("PR-09999997", "PR-09999996", "PR-09999995"):
        stub = stub_for(stubs, key)
        assert stub["name"] is None
        assert stub["stub_name_variants"] is None
        assert stub["name_withheld"] == "true"
    assert stub_for(stubs, "PR-09999997")["address"] is None
    assert "Citizen" not in repr(stubs)


def test_person_role_name_is_dropped_from_joined_output(spine):
    (row,) = je.join_actions([act(pr="PR-00000001", pname="Jo Citizen, director of Acme")], spine)
    assert row["provider_name"] is None
    assert "withheld" in row["notes"]


def test_withheld_service_stub_keeps_no_address(spine):
    _, stubs = stage(
        [
            act(
                se="SE-09999999",
                name="Family Day Care Co",
                suburb="Carina",
                address="5 Private Rd",
                notes="subject is an individual; name withheld",
            )
        ],
        spine,
    )
    stub = stub_for(stubs, "SE-09999999")
    assert stub["address"] is None
    assert stub["suburb"] == "Carina"


def test_stage_leaves_earlier_stage_joins_alone(spine):
    joined, stubs = stage(
        [
            act(rid="a", se="SE-00000001"),
            act(rid="b", se="SE-09999999", pr="PR-00000001"),  # joined on the provider key
            act(rid="c", jur="QLD", name="Little Gems Early Learning"),
            act(rid="d", jur="QLD", name="Not Anywhere"),
        ],
        spine,
    )
    assert [r["match_confidence"] for r in joined] == [
        "exact_key",
        "exact_key",
        "name_only",
        "unmatched",
    ]
    assert [r["spine_status"] for r in joined] == ["current", "current", "current", None]
    assert stubs == []


def test_live_denominators_unchanged_and_stubs_reported_separately(spine):
    actions = [
        act(rid="a", se="SE-00000001"),
        act(rid="b", se="SE-09999999", pr="PR-09999999", pname="Gone Pty Ltd", name="Gone Kids"),
        act(rid="c", se="SE-09999998", pr="PR-09999999", pname="Gone Pty Ltd", name="Gone Two"),
        act(rid="d", pr="PR-09999999", atype="approval_cancelled"),
        act(rid="e", se="SE-09999998", pr="PR-09999999", notes="duplicate row in source"),
    ]
    joined, stubs = stage(actions, spine)
    service_rows, provider_rows = je.aggregate(joined, spine, TYPES, WINDOW, cth_present=False)
    assert len(service_rows) == len(spine.services)
    assert len(provider_rows) == len(spine.profiles)
    assert {r["spine_status"] for r in service_rows + provider_rows} == {"current"}
    live_total = sum(r["actions_total"] for r in service_rows)
    assert live_total == 1  # only the live row; stub rows never leak in
    stub_services, stub_providers = je.aggregate_unlisted(
        joined, stubs, TYPES, WINDOW, False, SNAPSHOT
    )
    assert [r["service_approval_number"] for r in stub_services] == ["SE-09999998", "SE-09999999"]
    two = stub_services[0]
    assert two["actions_total"] == 1  # duplicate not counted
    assert two["acecqa_overall_rating"] is None
    assert two["spine_status"] == "not_in_current_register"
    assert "Not in the current ACECQA register" in two["coverage_note"]
    assert "not evidence of safety" in two["coverage_note"]
    (prov,) = stub_providers
    assert prov["provider_approval_number"] == "PR-09999999"
    assert prov["legal_name"] == "Gone Pty Ltd"
    assert prov["service_count"] == 2  # distinct stub services seen
    assert prov["service_count_basis"] == "distinct_unlisted_services_seen_in_actions"
    assert prov["service_level_actions"] == 2
    assert prov["provider_level_actions"] == 1
    assert prov["actions_total"] == 3
    assert prov["actions_last_24_months_per_service"] == 1.5
    assert {r["service_count_basis"] for r in provider_rows} == {"acecqa_current_register"}


def test_report_residual_breakdown_sums_to_unmatched(spine):
    actions = [
        act(rid="a", se="SE-00000001"),
        act(rid="b", se="SE-09999999"),
        act(rid="c", pr="PR-09999998", pname="Gone Pty Ltd"),
        act(rid="d", jur="NSW", name="No Key Here"),
        act(rid="e", jur="QLD", name="Nowhere Kids"),
        act(rid="f", jur="QLD", notes="subject is an individual; name withheld"),
        act(rid="g", jur="QLD", name="Sunny Days", state="QLD"),  # ambiguous: 3 share the name
        act(rid="h", jur="NSW", name="x", notes="register prints something odd"),
    ]
    actions[-1]["service_approval_number_raw"] = "garbled"
    joined, stubs = stage(actions, spine)
    service_rows, provider_rows = je.aggregate(joined, spine, TYPES, WINDOW, cth_present=False)
    stub_services, stub_providers = je.aggregate_unlisted(
        joined, stubs, TYPES, WINDOW, False, SNAPSHOT
    )
    report = je.build_report(
        joined,
        service_rows,
        provider_rows,
        TYPES,
        WINDOW,
        [],
        [],
        stubs=stubs,
        stub_service_rows=stub_services,
        stub_provider_rows=stub_providers,
        snapshot=SNAPSHOT,
    )
    overall = report["overall"]
    assert overall["rows_in"] == 8
    assert overall["joined_live_spine"] == 1
    assert overall["joined_by_unlisted_key"] == 2
    assert overall["unlisted_service_keys"] == 1
    assert overall["unlisted_provider_keys"] == 1
    assert overall["unmatched"] == 5
    assert overall["unmatched_residual"] == {
        "no_key_and_name_withheld": 1,
        "no_key_no_name_match": 2,
        "ambiguous_name": 1,
        "other": 1,
    }
    assert sum(overall["unmatched_residual"].values()) == overall["unmatched"]
    per_total = 0
    for jur in report["per_jurisdiction"].values():
        assert set(jur["unmatched_residual"]) == set(je.RESIDUAL_REASONS)
        assert sum(jur["unmatched_residual"].values()) == jur["unmatched"]
        per_total += jur["unmatched"]
    assert per_total == overall["unmatched"]
    nsw = report["per_jurisdiction"]["NSW"]
    assert nsw["joined_by_unlisted_key"] == 2
    assert overall["match_rate"] == 0.375
    assert overall["match_rate_live_spine_only"] == 0.125
    assert report["services_with_action_last_24_months"]["denominator_services"] == 7
    assert report["providers_with_action_last_24_months"]["denominator_providers"] == 3
    assert report["unlisted_spine"]["service_keys"] == 1


def test_top_lists_flag_stub_providers_and_skip_nameless_ones(spine):
    actions = [
        act(rid=f"n{i}", se=f"SE-0999990{i}", pr="PR-09999990", pname="Gone Pty Ltd")
        for i in range(5)
    ] + [
        act(rid="w", pr="PR-09999991", pname="", notes="provider name withheld: individual"),
        act(rid="x", se="SE-00000001", pr="PR-00000001"),
    ]
    joined, stubs = stage(actions, spine)
    service_rows, provider_rows = je.aggregate(joined, spine, TYPES, WINDOW, cth_present=False)
    stub_services, stub_providers = je.aggregate_unlisted(
        joined, stubs, TYPES, WINDOW, False, SNAPSHOT
    )
    report = je.build_report(
        joined,
        service_rows,
        provider_rows,
        TYPES,
        WINDOW,
        [],
        [],
        stubs=stubs,
        stub_service_rows=stub_services,
        stub_provider_rows=stub_providers,
        snapshot=SNAPSHOT,
    )
    top = report["top_20_providers_by_actions_last_24_months"]
    assert [t["provider_approval_number"] for t in top] == ["PR-09999990", "PR-00000001"]
    assert [t["spine_status"] for t in top] == ["not_in_current_register", "current"]
    assert "actions-derived" in top[0]["service_count_note"]
    assert "service_count_note" not in top[1]
    assert top[0]["service_count"] == 5
    rate = report["top_20_providers_by_rate_per_service_min_5_services"]
    assert [t["provider_approval_number"] for t in rate] == ["PR-09999990"]
    assert rate[0]["actions_last_24_months_per_service"] == 1.0
    assert "PR-09999991" not in {t["provider_approval_number"] for t in top}
    assert any("100 per cent" in c for c in report["caveats"])


# ---------------------------------------------------------------------------
# ABN entity stage
# ---------------------------------------------------------------------------

ABN = "12345678901"


def abr(entity, business="", status="ok", abn=ABN):
    return {
        "abn": abn,
        "lookup_status": status,
        "entity_name": entity,
        "business_names": business,
        "abn_status": "Active",
    }


def abn_act(name="Unrelated Printed Name Pty Ltd", *, abn=ABN, **kw):
    return pact(name, notes=f"ccs_identifier: ABN {abn}", **kw)


def test_abn_entity_unique_match_on_entity_name(pspine):
    details = {ABN: abr("The Bright Start Pty Limited")}
    (row,) = je.join_actions([abn_act(state="NSW")], pspine, details)
    assert row["join_key_kind"] == "abn_entity_match"
    assert row["match_confidence"] == "abn_unique_entity"
    assert row["acecqa_provider_approval_number"] == "PR-00000101"
    assert "entity name" in row["join_note"]
    assert row["provider_approval_number"] is None  # never set on the source columns


def test_abn_entity_match_on_business_name_across_states(pspine):
    details = {ABN: abr("Holdco Pty Ltd", business="Some Brand; Southern Cross Kids Inc")}
    (row,) = je.join_actions([abn_act(state="NSW")], pspine, details)
    assert row["acecqa_provider_approval_number"] == "PR-00000401"
    assert "business name" in row["join_note"]


def test_abn_entity_ambiguous_falls_through_to_provider_name(pspine):
    details = {ABN: abr("Twin Holdings Pty Ltd")}
    (row,) = je.join_actions([abn_act("Cross Border Pty Ltd")], pspine, details)
    assert row["join_key_kind"] == "provider_name_match"
    assert row["acecqa_provider_approval_number"] == "PR-00000601"
    (row,) = je.join_actions([abn_act("Nobody Pty Ltd")], pspine, details)
    assert row["match_confidence"] == "unmatched"
    assert "ambiguous ABN entity match: 2 candidate providers" in row["join_note"]
    assert je.residual_reason(row) == "ambiguous_name"


def test_abn_entity_union_of_names_must_be_unique(pspine):
    # entity name points at one provider, a business name at another: not accepted
    details = {ABN: abr("Bright Start Pty Ltd", business="Cross Border Pty Ltd")}
    (row,) = je.join_actions([abn_act("Nobody Pty Ltd")], pspine, details)
    assert row["match_confidence"] == "unmatched"
    assert "ambiguous ABN entity match" in row["join_note"]


def test_abn_entity_never_matches_individuals(pspine):
    excluded = {ABN: abr(None, status="excluded_individual")}
    (row,) = je.join_actions([abn_act("Nobody Pty Ltd")], pspine, excluded)
    assert row["match_confidence"] == "unmatched"
    assert "ABR lookup status excluded_individual" in row["join_note"]
    # an entity name equal to a withheld provider's legal name is never matched
    withheld = {ABN: abr("Placeholder Person Name")}
    (row,) = je.join_actions([abn_act("Nobody Pty Ltd")], pspine, withheld)
    assert row["acecqa_provider_approval_number"] is None


def test_abn_entity_stage_runs_before_provider_name_stage(pspine):
    details = {ABN: abr("Southern Cross Kids Incorporated")}
    (row,) = je.join_actions([abn_act("Bright Start Pty Ltd", state="NSW")], pspine, details)
    assert row["join_key_kind"] == "abn_entity_match"
    assert row["acecqa_provider_approval_number"] == "PR-00000401"


def test_abn_entity_stage_skipped_without_table_abn_or_with_key(pspine):
    details = {ABN: abr("Bright Start Pty Ltd")}
    # no table: provider-name stage only
    (row,) = je.join_actions([abn_act("Cross Border Pty Ltd")], pspine)
    assert row["join_key_kind"] == "provider_name_match"
    # no ABN on the row
    (row,) = je.join_actions([pact("Cross Border Pty Ltd")], pspine, details)
    assert row["join_key_kind"] == "provider_name_match"
    # ABN not in the table
    (row,) = je.join_actions([abn_act("Nobody Pty Ltd", abn="99999999999")], pspine, details)
    assert "ABN not in the ABR lookup table" in row["join_note"]
    # a printed key absent from the spine is never matched by ABN either
    keyed = abn_act("Nobody Pty Ltd", se="SE-09999999")
    (row,) = je.join_actions([keyed], pspine, details)
    assert row["match_confidence"] == "unmatched"
    assert row["join_note"] == "service key SE-09999999 not in the spine"


def test_abn_entity_pin_counts_and_report(pspine):
    details = {ABN: abr("Bright Start Pty Ltd")}
    actions = [
        abn_act(rid="a", state="NSW", when="2026-05-05"),
        abn_act(rid="b", state="NSW", service="Bright Start Kindy", when="2026-05-06"),
    ]
    joined = je.join_actions(actions, pspine, details)
    assert [r["match_confidence"] for r in joined] == ["abn_unique_entity", "abn_unique_entity"]
    assert joined[1]["acecqa_service_approval_number"] == "SE-00000101"
    assert "service pinned" in joined[1]["join_note"]
    service_rows, provider_rows = je.aggregate(joined, pspine, TYPES, WINDOW, cth_present=True)
    p = next(r for r in provider_rows if r["provider_approval_number"] == "PR-00000101")
    assert p["provider_level_actions"] == 1
    assert p["service_level_actions"] == 1
    assert p["actions_matched_by_name"] == 2
    report = je.build_report(joined, service_rows, provider_rows, TYPES, WINDOW, [], [])
    cth = report["per_jurisdiction"]["CTH"]
    assert cth["joined_by_abn_entity"] == 2
    assert cth["joined_by_abn_entity_pinned"] == 1
    assert cth["joined_by_provider_name"] == 0
    assert cth["match_rate"] == 1.0


def test_load_abn_details(tmp_path):
    assert je.load_abn_details(tmp_path / "missing.csv") is None
    path = tmp_path / "abn-details.csv"
    path.write_text(
        "abn,lookup_status,entity_name,business_names\n"
        "12 345 678 901,ok,Bright Start Pty Ltd,\n"
        ",ok,No Abn Pty Ltd,\n",
        encoding="utf-8",
    )
    loaded = je.load_abn_details(path)
    assert list(loaded) == [ABN]
    assert loaded[ABN]["entity_name"] == "Bright Start Pty Ltd"
