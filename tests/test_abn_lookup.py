"""Tests for scrapers/abn_lookup.py and the stage B and C logic. Inline fixtures, no network."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from scrapers import abn_lookup as al
from scrapers import build_provider_groups as bpg
from scrapers import common
from scrapers.common import Fetched

GUID = "0a1b2c3d-4e5f-6789-abcd-ef0123456789"
ABN = "11603236353"

DETAILS_COMPANY = {
    "Abn": ABN,
    "AbnStatus": "Active",
    "AbnStatusEffectiveFrom": "2015-01-01",
    "Acn": "603236353",
    "AddressPostcode": "2000",
    "AddressState": "NSW",
    "BusinessName": ["Bright Start Kindy", "Jane Example"],
    "EntityName": "BRIGHT START PTY LTD",
    "EntityTypeCode": "PRV",
    "EntityTypeName": "Australian Private Company",
    "Gst": None,
    "Message": "",
}
DETAILS_PERSON = {
    **DETAILS_COMPANY,
    "Acn": "",
    "EntityName": "EXAMPLE, JANE",
    "EntityTypeCode": "IND",
    "EntityTypeName": "Individual/Sole Trader",
    "BusinessName": ["Jane's Family Day Care"],
}


@pytest.fixture(autouse=True)
def _project_root_in_tmp(tmp_path, monkeypatch):
    # write_snapshot logs paths relative to the project root; keep test caches under tmp_path.
    monkeypatch.setattr(common, "PROJECT_ROOT", tmp_path)


def jsonp(data: dict, callback: str = "cb") -> str:
    return f"{callback}({json.dumps(data)})"


def cand(abn, name, score=99, current=True, name_type="Entity Name", state="NSW"):
    return {
        "Abn": abn,
        "AbnStatus": "0000000001",
        "IsCurrent": current,
        "Name": name,
        "NameType": name_type,
        "Postcode": "2000",
        "Score": score,
        "State": state,
    }


# ---------------------------------------------------------------------------
# JSONP
# ---------------------------------------------------------------------------


def test_parse_jsonp_strips_wrapper():
    assert al.parse_jsonp(jsonp({"Abn": ABN}))["Abn"] == ABN
    assert al.parse_jsonp('﻿callback({"Names": []});\n') == {"Names": []}
    assert al.parse_jsonp('{"Abn": "1"}') == {"Abn": "1"}
    # a ')' inside a string value does not confuse the unwrapping
    assert al.parse_jsonp('cb({"Message": "bad (input)"})')["Message"] == "bad (input)"


def test_parse_jsonp_rejects_non_object():
    with pytest.raises(ValueError):
        al.parse_jsonp("cb([1, 2])")


# ---------------------------------------------------------------------------
# GUID handling and redaction
# ---------------------------------------------------------------------------


def test_load_guid_prefers_environment_then_env_file(tmp_path):
    env = tmp_path / ".env"
    env.write_text(f"# comment\nOTHER=1\nexport ABN_LOOKUP_GUID='{GUID}'\n", encoding="utf-8")
    assert al.load_guid(env, environ={}) == GUID
    assert al.load_guid(env, environ={"ABN_LOOKUP_GUID": "from-env"}) == "from-env"
    assert al.load_guid(tmp_path / "missing", environ={}) is None


def test_redact_url_removes_guid_parameter():
    url = f"https://abr.business.gov.au/json/AbnDetails.aspx?abn={ABN}&callback=cb&guid={GUID}"
    clean = al.redact_url(url)
    assert GUID not in clean and "guid" not in clean.lower()
    assert f"abn={ABN}" in clean and "callback=cb" in clean
    first = f"https://abr.business.gov.au/json/MatchingNames.aspx?GUID={GUID}&name=A+B"
    assert al.redact_url(first) == "https://abr.business.gov.au/json/MatchingNames.aspx?name=A+B"
    assert al.redact_url("https://abr.business.gov.au/json/") == "https://abr.business.gov.au/json/"


def test_redact_text_covers_messages_and_bare_guids():
    msg = (
        "Client error '404' for url 'https://abr.business.gov.au/json/AbnDetails.aspx?"
        f"abn={ABN}&guid={GUID}&callback=cb'"
    )
    clean = al.redact_text(msg, GUID)
    assert GUID not in clean and "guid=" not in clean.lower()
    assert "callback=cb" in clean
    assert GUID not in al.redact_text(f"key is {GUID}")  # GUID-shaped text, no known guid
    assert GUID.upper() not in al.redact_text(f"key {GUID.upper()}")


def test_redacting_filter_cleans_log_records(caplog):
    logger = logging.getLogger("test_abn_redaction")
    logger.addFilter(al.RedactingFilter(GUID))
    with caplog.at_level(logging.INFO, logger="test_abn_redaction"):
        logger.info("GET %s", f"https://x/json/AbnDetails.aspx?abn=1&guid={GUID}")
    assert caplog.records
    assert all(GUID not in r.getMessage() for r in caplog.records)
    assert GUID not in caplog.text


def fake_fetcher(payloads: dict, calls: list, *, echo_guid: bool = False):
    """Returns a fetch stand-in keyed on the endpoint name."""

    def _fetch(url, redact=None):
        calls.append(url)
        endpoint = url.split("/json/")[1].split("?")[0]
        body = jsonp(payloads[endpoint])
        if echo_guid:
            body = body.replace('"Message": ""', f'"Message": "guid {GUID}"')
        return Fetched(
            url=url,
            final_url=url,
            status=200,
            content=body.encode("utf-8"),
            content_type="text/javascript",
            last_modified=None,
            etag=None,
            fetched_at=datetime.now(timezone.utc).isoformat(),  # noqa: UP017
        )

    return _fetch


def client_for(tmp_path, payloads, calls, **kw):
    return al.AbnLookupClient(
        GUID,
        cache_dir=tmp_path / "raw" / "abr-lookup",
        fetcher=fake_fetcher(payloads, calls, echo_guid=kw.pop("echo_guid", False)),
        **kw,
    )


def test_guid_sent_but_never_stored(tmp_path):
    calls: list = []
    client = client_for(tmp_path, {al.ENDPOINT_ABN: DETAILS_COMPANY}, calls, echo_guid=True)
    result = client.abn_details(ABN)
    assert f"guid={GUID}" in calls[0]  # the request itself carries the GUID
    stored = list((tmp_path / "raw" / "abr-lookup").iterdir())
    assert len(stored) == 2  # response plus sidecar
    for path in stored:
        text = path.read_text(encoding="utf-8")
        assert GUID not in text
        assert "guid=" not in text.lower()
    meta = json.loads(next(p for p in stored if p.name.endswith(".meta.json")).read_text())
    assert meta["query"] == {"abn": ABN}
    assert meta["guid_redacted"] is True
    assert GUID not in json.dumps(result.query)


def test_http_error_message_is_redacted(tmp_path):
    def failing(url, redact=None):
        request = httpx.Request("GET", url)
        response = httpx.Response(500, request=request)
        raise httpx.HTTPStatusError(
            f"Server error for url '{url}'", request=request, response=response
        )

    client = al.AbnLookupClient(GUID, cache_dir=tmp_path / "abr-lookup", fetcher=failing)
    with pytest.raises(al.AbnLookupError) as info:
        client.abn_details(ABN)
    assert GUID not in str(info.value)
    assert info.value.__suppress_context__


def test_cache_reuse_age_and_budget(tmp_path):
    calls: list = []
    payloads = {al.ENDPOINT_ABN: DETAILS_COMPANY, al.ENDPOINT_NAMES: {"Names": []}}
    client = client_for(tmp_path, payloads, calls, max_calls=2)
    first = client.abn_details(ABN)
    again = client.abn_details(ABN)
    assert len(calls) == 1 and again.from_cache and again.sha256 == first.sha256
    # a fresh client finds the cache on disk
    fresh = client_for(tmp_path, payloads, calls, max_calls=2)
    assert fresh.abn_details(ABN).from_cache and fresh.calls_made == 0
    # older than 30 days: fetched again
    later = client_for(
        tmp_path,
        payloads,
        calls,
        max_calls=2,
        now=lambda: datetime.now(timezone.utc) + timedelta(days=31),  # noqa: UP017
    )
    assert not later.abn_details(ABN).from_cache
    # the cap stops new calls but not cache hits
    client.matching_names("Bright Start Pty Ltd")
    with pytest.raises(al.BudgetExhausted):
        client.matching_names("Another Name Pty Ltd")
    assert client.calls_made == 2
    # offline uses the cache only
    offline = al.AbnLookupClient(None, cache_dir=tmp_path / "raw" / "abr-lookup", offline=True)
    assert offline.abn_details(ABN).from_cache
    with pytest.raises(al.AbnLookupError):
        offline.abn_details("99999999999")


def test_client_needs_guid_unless_offline(tmp_path):
    with pytest.raises(al.AbnLookupError):
        al.AbnLookupClient(None, cache_dir=tmp_path)


# ---------------------------------------------------------------------------
# Individual exclusion
# ---------------------------------------------------------------------------


def test_individual_abr_record_keeps_no_name():
    row = al.details_row(ABN, DETAILS_PERSON, None)
    assert row["lookup_status"] == "excluded_individual"
    assert row["entity_name"] is None and row["business_names"] is None
    assert "JANE" not in json.dumps(row).upper()


@pytest.mark.parametrize(
    "data",
    [
        {"EntityTypeCode": "IND", "EntityTypeName": "x", "EntityName": "Acme Pty Ltd"},
        {"EntityTypeCode": "", "EntityTypeName": "Individual/Sole Trader", "EntityName": "A"},
        {"EntityTypeCode": "PTR", "EntityTypeName": "Sole Trader", "EntityName": "A"},
        {
            "EntityTypeCode": "FPT",
            "EntityTypeName": "Family Partnership",
            "EntityName": "Jane Example & John Example",
        },
    ],
)
def test_is_individual_entity(data):
    assert al.is_individual_entity(data)


def test_company_is_not_individual_and_person_like_business_names_withheld():
    assert not al.is_individual_entity(DETAILS_COMPANY)
    row = al.details_row(ABN, DETAILS_COMPANY, None, known={"BRIGHT START KINDY"})
    assert row["lookup_status"] == "ok"
    assert row["entity_name"] == "BRIGHT START PTY LTD"
    assert row["acn"] == "603236353"
    assert row["business_names"] == "Bright Start Kindy"
    assert row["business_names_withheld"] == 1
    # a person-like business name that is already an ACECQA organisation name is kept
    kept, withheld = al.safe_business_names(["Jane Example"], {"JANE EXAMPLE"})
    assert kept == ["Jane Example"] and withheld == 0


def test_not_found_record():
    row = al.details_row(ABN, {"Abn": "", "Message": "Search text is not a valid ABN or ACN"}, None)
    assert row["lookup_status"] == "not_found"
    assert "not a valid ABN" in row["note"]


# ---------------------------------------------------------------------------
# Name-candidate assessment
# ---------------------------------------------------------------------------


def test_unique_match_accepted_with_score():
    data = {
        "Names": [
            cand("11111111111", "Bright Start Pty. Limited", score=99),
            cand("22222222222", "Bright Start Early Learning Pty Ltd", score=90),
            cand("11111111111", "Bright Start Kindy", score=95, name_type="Business Name"),
        ]
    }
    out = al.assess_candidates(data, "The Bright Start Pty Ltd", "NSW")
    assert out["match_kind"] == "accepted_unique"
    assert out["abn"] == "11111111111"
    assert out["score"] == 99
    assert out["candidates"] == 2  # distinct ABNs


def test_ambiguous_when_several_abns_carry_the_name():
    data = {
        "Names": [
            cand("11111111111", "Little Learners Pty Ltd", state="QLD"),
            cand("22222222222", "Little Learners Pty Ltd", state="QLD"),
        ]
    }
    out = al.assess_candidates(data, "Little Learners Pty Ltd", "QLD")
    assert out["match_kind"] == "ambiguous" and out["abn"] is None
    assert out["candidates"] == 2


def test_state_breaks_a_tie_only():
    data = {
        "Names": [
            cand("11111111111", "Little Learners Pty Ltd", state="QLD"),
            cand("22222222222", "Little Learners Pty Ltd", state="VIC"),
        ]
    }
    out = al.assess_candidates(data, "Little Learners Pty Ltd", "VIC")
    assert out["match_kind"] == "accepted_unique_in_state"
    assert out["abn"] == "22222222222"
    # a single name-equal candidate in another state is still accepted
    single = {"Names": [cand("33333333333", "Solo Care Pty Ltd", state="WA")]}
    assert al.assess_candidates(single, "Solo Care Pty Ltd", "NSW")["abn"] == "33333333333"


def test_not_top_score_is_ambiguous():
    data = {
        "Names": [
            cand("11111111111", "Acme Care Pty Ltd", score=90),
            cand("22222222222", "Acme Care Services Pty Ltd", score=99),
        ]
    }
    out = al.assess_candidates(data, "Acme Care Pty Ltd")
    assert out["match_kind"] == "ambiguous"
    assert "top score" in out["note"]


def test_non_current_and_individual_candidates_ignored():
    data = {
        "Names": [
            cand("11111111111", "Acme Care Pty Ltd", current=False),
            cand("22222222222", "Acme Care Pty Ltd", name_type="Legal Name"),
            cand("44444444444", "Jane Example", score=100, name_type="Business Name"),
        ]
    }
    out = al.assess_candidates(data, "Acme Care Pty Ltd")
    assert out["match_kind"] == "no_match"
    assert out["excluded_individual_candidates"] == 2
    assert out["candidates"] == 0
    assert "Jane" not in json.dumps(out)


def test_no_name_equal_candidate_is_no_match():
    data = {"Names": [cand("11111111111", "Acme Care Services Pty Ltd")]}
    out = al.assess_candidates(data, "Acme Care Pty Ltd")
    assert out["match_kind"] == "no_match" and out["candidates"] == 1
    assert al.assess_candidates({"Names": None, "Message": "x"}, "Acme")["candidates"] == 0


# ---------------------------------------------------------------------------
# Stage B and C
# ---------------------------------------------------------------------------


def profile(pr, legal, *, form="company", services=1, states=1, withheld="false"):
    return {
        "provider_approval_number": pr,
        "legal_name": legal,
        "trading_name": "",
        "name_withheld": withheld,
        "entity_form": form,
        "provider_state": "NSW",
        "service_count": str(services),
        "state_count": str(states),
    }


def test_subset_priority_and_exclusion():
    profiles = [
        profile("PR-00000001", "Big Pty Ltd", services=9),
        profile("PR-00000002", "Joined Pty Ltd"),
        profile("PR-00000003", "Two States Pty Ltd", states=2),
        profile("PR-00000004", "Small Pty Ltd"),
        profile("PR-00000005", None, form="likely_individual", services=6, withheld="true"),
    ]
    subset = bpg.select_subset(profiles, {"PR-00000002"})
    prs = [p["provider_approval_number"] for p, _ in subset]
    assert prs == ["PR-00000002", "PR-00000001", "PR-00000005", "PR-00000003"]
    assert bpg.excluded_profile(profiles[4])
    assert bpg.excluded_profile(profile("PR-00000006", "Odd Name", form="unknown"))


def test_excluded_provider_is_never_queried(tmp_path):
    calls: list = []
    client = client_for(tmp_path, {}, calls)
    row = bpg.resolve_provider(
        client, profile("PR-00000005", "Jane Example", form="likely_individual"), ["x"], set()
    )
    assert calls == []
    assert row["match_kind"] == bpg.KIND_EXCLUDED and row["legal_name"] is None


def test_resolve_provider_accepts_and_confirms(tmp_path):
    calls: list = []
    payloads = {
        al.ENDPOINT_NAMES: {"Names": [cand(ABN, "Bright Start Pty Ltd")]},
        al.ENDPOINT_ABN: DETAILS_COMPANY,
    }
    client = client_for(tmp_path, payloads, calls)
    row = bpg.resolve_provider(client, profile("PR-00000001", "Bright Start Pty Ltd"), ["x"], set())
    assert row["match_kind"] == "accepted_unique"
    assert row["abn"] == ABN and row["acn"] == "603236353"
    assert row["entity_type_code"] == "PRV" and row["abn_status"] == "Active"
    assert row["response_sha256"] and row["details_response_sha256"]
    assert len(calls) == 2


def test_resolve_provider_drops_abr_individual(tmp_path):
    calls: list = []
    payloads = {
        al.ENDPOINT_NAMES: {"Names": [cand(ABN, "Bright Start Pty Ltd")]},
        al.ENDPOINT_ABN: DETAILS_PERSON,
    }
    client = client_for(tmp_path, payloads, calls)
    row = bpg.resolve_provider(client, profile("PR-00000001", "Bright Start Pty Ltd"), ["x"], set())
    assert row["match_kind"] == bpg.KIND_EXCLUDED_ABR
    assert row["abn"] is None and row["legal_name"] is None and row["business_names"] is None
    assert "JANE" not in json.dumps(row).upper()


def abn_row(pr, abn, acn=None, business="", entity="Entity Pty Ltd"):
    return {
        "provider_approval_number": pr,
        "legal_name": f"Legal {pr}",
        "abn": abn,
        "acn": acn,
        "business_names": business,
        "match_kind": "accepted_unique",
        "abr_entity_name": entity,
    }


def test_groups_by_shared_abn_acn_and_business_name_overlap():
    rows = [
        abn_row("PR-00000001", "11111111111", "111111111"),
        abn_row("PR-00000002", "11111111111", "111111111"),
        abn_row("PR-00000003", "33333333333", "333333333"),
        abn_row("PR-00000004", "44444444444", "333333333"),  # same ACN, other ABN
        abn_row("PR-00000005", "55555555555", business="Brand Kids"),
        abn_row("PR-00000006", "66666666666"),
        {**abn_row("PR-00000007", "11111111111"), "match_kind": "ambiguous"},
    ]
    names = {"BRAND KIDS": {"PR-00000009"}, "LEGAL PR 00000001": {"PR-00000001"}}
    groups = bpg.build_groups(rows, names, {"PR-00000009": "Brand Kids Pty Ltd"})
    by_group: dict = {}
    for g in groups:
        by_group.setdefault(g["group_id"], []).append(g)
    assert {g["provider_approval_number"] for g in by_group["G-11111111111"]} == {
        "PR-00000001",
        "PR-00000002",
    }  # the ambiguous row is never grouped
    assert {g["link_reason"] for g in by_group["G-11111111111"]} == {"shared_abn_and_acn"}
    acn_group = by_group["G-33333333333"]
    assert {g["link_reason"] for g in acn_group} == {"shared_acn"}
    overlap = by_group["BN-PR-00000005"]
    assert [g["link_reason"] for g in overlap] == [
        "business_name_overlap_holder",
        "business_name_overlap_named",
    ]
    assert overlap[1]["provider_approval_number"] == "PR-00000009"
    assert "G-66666666666" not in by_group  # singletons are not groups

    summary = bpg.summarise(
        groups,
        rows,
        [
            {
                "provider_approval_number": "PR-00000001",
                "service_count": "4",
                "actions_last_24_months": "2",
                "window_start": "2024-10-29",
                "window_end": "2026-10-28",
            },
            {
                "provider_approval_number": "PR-00000002",
                "service_count": "3",
                "actions_last_24_months": "1",
            },
        ],
        None,
    )
    assert summary["entity_groups"] == 2
    assert summary["business_name_overlap_flags"] == 1
    top = summary["largest_10_entity_groups"][0]
    assert top["group_id"] == "G-11111111111"
    assert top["total_services"] == 7 and top["actions_last_24_months"] == 2 + 1
    assert summary["window"]["end"] == "2026-10-28"
    assert any("NOT derivable" in c for c in summary["caveats"])


# ---------------------------------------------------------------------------
# Fail-closed name filter on ABN outputs (CLAUDE.md rule 2). Synthetic names only.
# ---------------------------------------------------------------------------

DETAILS_PERSON_TRUST = {
    **DETAILS_COMPANY,
    "EntityName": "Example Holdings Pty Ltd ATF the Jane Example Family Trust",
    "EntityTypeCode": "DTT",
    "EntityTypeName": "Discretionary Trading Trust",
    "BusinessName": ["Sunny Days Childcare Centre"],
}


def test_details_row_withholds_a_person_named_trust_but_keeps_the_abn():
    row = al.details_row(ABN, DETAILS_PERSON_TRUST, None, known=set())
    assert row["abn"] == ABN and row["acn"] == "603236353"
    assert row["entity_name"] is None and row["business_names"] is None
    assert row["name_withheld"] == "true"
    assert "JANE" not in json.dumps(row).upper()


def test_details_row_keeps_a_company_name():
    row = al.details_row(ABN, DETAILS_COMPANY, None, known=set())
    assert row["entity_name"] == "BRIGHT START PTY LTD"
    assert row["name_withheld"] == "false"


def test_refilter_details_rows_applies_the_rule_to_committed_rows():
    rows = [
        {
            "abn": ABN,
            "lookup_status": "ok",
            "entity_name": "Example Holdings Pty Ltd ATF the Jane Example Family Trust",
            "business_names": "Sunny Days Childcare Centre",
            "business_names_withheld": "0",
            "note": "",
        },
        {
            "abn": "22222222222",
            "lookup_status": "ok",
            "entity_name": "BRIGHT START PTY LTD",
            "business_names": "Bright Start Kindy; Jane Example",
            "business_names_withheld": "0",
            "note": "",
        },
    ]
    out = al.refilter_details_rows(rows, known={"BRIGHT START KINDY"})
    assert out[0]["abn"] == ABN
    assert out[0]["entity_name"] is None and out[0]["business_names"] is None
    assert out[0]["name_withheld"] == "true"
    assert out[1]["entity_name"] == "BRIGHT START PTY LTD"
    assert out[1]["business_names"] == "Bright Start Kindy"
    assert out[1]["business_names_withheld"] == 1
    assert out[1]["name_withheld"] == "false"
    assert "JANE" not in json.dumps(out).upper()


def test_provider_abn_filter_nulls_names_of_withheld_providers():
    rows = [
        {
            **abn_row("PR-00000011", "11111111111", business="Sunny Days Childcare Centre"),
            "legal_name": "Jane Example ATF Example Family Trust",
            "abr_entity_name": "Jane Example ATF Example Family Trust",
        },
        {
            **abn_row("PR-00000012", "22222222222"),
            "legal_name": "Example Holdings Pty Ltd ATF Jane Example Family Trust",
        },
        {**abn_row("PR-00000013", "33333333333"), "legal_name": "Sunny Days Pty Ltd"},
    ]
    profiles = {
        "PR-00000011": profile("PR-00000011", None, form="likely_individual", withheld="true"),
        "PR-00000012": profile(
            "PR-00000012", "Example Holdings Pty Ltd ATF Jane Example Family Trust"
        ),
        "PR-00000013": profile("PR-00000013", "Sunny Days Pty Ltd"),
    }
    changed = bpg.apply_name_filter(rows, profiles, known=set())
    assert changed == 2
    for r in rows[:2]:
        assert r["abn"] and r["provider_approval_number"]
        assert r["legal_name"] is None and r["abr_entity_name"] is None
        assert r["business_names"] is None
        assert r["name_withheld"] == "true"
    assert rows[2]["legal_name"] == "Sunny Days Pty Ltd" and rows[2]["name_withheld"] == "false"
    assert "JANE" not in json.dumps(rows).upper()
    assert "name_withheld" in bpg.PROVIDER_ABN_COLUMNS


def test_groups_mark_withheld_names():
    rows = [
        {**abn_row("PR-00000021", "11111111111"), "legal_name": None, "name_withheld": "true"},
        abn_row("PR-00000022", "11111111111"),
    ]
    groups = bpg.build_groups(rows, {}, {})
    by_pr = {g["provider_approval_number"]: g for g in groups}
    assert by_pr["PR-00000021"]["legal_name"] is None
    assert by_pr["PR-00000021"]["name_withheld"] == "true"
    assert by_pr["PR-00000022"]["name_withheld"] == "false"
    assert "name_withheld" in bpg.GROUP_COLUMNS


def test_refilter_is_idempotent_and_keeps_the_withheld_flag_and_note():
    rows = [
        {
            "abn": ABN,
            "lookup_status": "ok",
            "entity_name": "Example Holdings Pty Ltd ATF the Jane Example Family Trust",
            "business_names": "Sunny Days Childcare Centre",
            "business_names_withheld": "0",
            "note": "",
        }
    ]
    once = al.refilter_details_rows(rows, known=set())
    as_csv = [{k: ("" if v is None else str(v)) for k, v in r.items()} for r in once]
    twice = al.refilter_details_rows(as_csv, known=set())
    assert twice[0]["name_withheld"] == "true"
    assert twice[0]["entity_name"] is None and twice[0]["business_names"] is None
    assert al.ENTITY_NAME_WITHHELD_NOTE in (twice[0]["note"] or "")
    assert twice == once


def test_provider_abn_filter_is_idempotent():
    rows = [
        {
            **abn_row("PR-00000031", "11111111111"),
            "legal_name": "Example Holdings Pty Ltd ATF Jane Example Family Trust",
        }
    ]
    profiles = {"PR-00000031": profile("PR-00000031", "Example Holdings Pty Ltd")}
    bpg.apply_name_filter(rows, profiles, known=set())
    first = [dict(r) for r in rows]
    as_csv = [{k: ("" if v is None else str(v)) for k, v in r.items()} for r in rows]
    bpg.apply_name_filter(as_csv, profiles, known=set())
    assert as_csv[0]["name_withheld"] == "true"
    assert as_csv[0]["legal_name"] is None
    assert bpg.NAME_WITHHELD_NOTE in (as_csv[0]["note"] or "")
    assert as_csv == first
