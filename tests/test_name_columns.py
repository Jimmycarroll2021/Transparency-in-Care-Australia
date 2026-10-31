"""PR #12: the shared person check on trading names and service names. Synthetic names only."""

import csv
import json
import pickle

import pytest
from scrapers import common
from scrapers import join_enforcement as je
from scrapers.profile_providers import (
    AcecqaNameContext,
    PersonNames,
    name_has_person_signal,
    name_may_name_person,
)


def _names(*subjects):
    names = PersonNames()
    for s in subjects:
        names.add_subject(s)
    return names


@pytest.fixture
def ctx():
    """An empty ACECQA context and an empty run-wide set, so no local file is read."""
    context = AcecqaNameContext()
    common.set_name_context(context)
    common.set_person_names(PersonNames())
    return context


# ---------------------------------------------------------------------------
# The check
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "Jane Example",
        "Mrs Example's Childcare",
        "Jane Example ATF The Example Family Trust",
        "Estate of Jane Example",
    ],
)
def test_person_named_trading_name_has_a_person_signal(name):
    assert name_has_person_signal(name)
    assert name_may_name_person(name)


@pytest.mark.parametrize(
    "name", ["Little Acorns Early Learning", "Sunny Kids Club", "Riverbend Holdings Pty Ltd"]
)
def test_ordinary_trading_name_is_kept(name):
    assert not name_has_person_signal(name)
    assert not name_may_name_person(name, _names("Jane Example", "John Sample"))


def test_family_day_care_named_after_a_person_in_the_run_wide_set():
    names = _names("Jane Example")
    assert name_may_name_person("Jane Example Family Day Care", names)
    assert not name_may_name_person("Riverside Family Day Care", names)


def test_service_repeating_its_own_withheld_provider_surname():
    own = _names("Jane Sample")
    assert name_may_name_person("Sample Family Day Care", None, own)
    assert not name_may_name_person("Sample Family Day Care", None, _names("John Other"))


def test_ordinary_word_surname_is_not_used_alone_but_full_names_are():
    names = _names("Rose Cottage")
    assert name_may_name_person("Cottage Kids Club", names)
    assert not name_may_name_person("Cottage Kids Club", names, ordinary={"cottage"})
    assert name_may_name_person("Rose Cottage Kids Club", names, ordinary={"cottage"})


def test_name_context_is_in_memory_only():
    with pytest.raises(TypeError):
        pickle.dumps(AcecqaNameContext())


# ---------------------------------------------------------------------------
# The output rule
# ---------------------------------------------------------------------------


def test_trading_name_withheld_with_note_and_ordinary_name_kept(ctx):
    rows = [
        {
            "provider_approval_number": "PR-00000001",
            "legal_name": "Example Holdings Pty Ltd",
            "trading_name": "Jane Example",
            "name_withheld": "false",
        },
        {
            "provider_approval_number": "PR-00000002",
            "legal_name": "Acorn Group Pty Ltd",
            "trading_name": "Little Acorns Early Learning",
            "name_withheld": "false",
        },
    ]
    fields = ["provider_approval_number", "legal_name", "trading_name", "name_withheld"]
    out, fieldnames, counts = common.withhold_person_named_names("provider-profile", rows, fields)
    assert counts == {"trading_name": 1}
    assert "trading_name_note" in fieldnames
    assert out[0]["trading_name"] is None
    assert out[0]["trading_name_note"] == common.TRADING_NAME_WITHHELD_NOTE
    assert out[0]["provider_approval_number"] == "PR-00000001"
    assert out[0]["legal_name"] == "Example Holdings Pty Ltd"
    assert out[1]["trading_name"] == "Little Acorns Early Learning"
    assert not out[1].get("trading_name_note")
    # the caller's rows are not changed
    assert rows[0]["trading_name"] == "Jane Example"


def test_family_day_care_service_withheld_and_approval_numbers_kept(ctx):
    ctx.withheld["PR-00000009"] = "Jane Sample"
    rows = [
        {
            "record_id": "r1",
            "service_approval_number": "SE-00000001",
            "provider_approval_number": "PR-00000009",
            "service_name": "Sample Family Day Care",
            "service_type": "Family Day Care",
            "notes": "duplicate row in source",
        },
        {
            "record_id": "r2",
            "service_approval_number": "SE-00000002",
            "provider_approval_number": "PR-00000010",
            "service_name": "Riverside Family Day Care",
            "service_type": "Family Day Care",
            "notes": None,
        },
    ]
    fields = list(rows[0])
    out, fieldnames, counts = common.withhold_person_named_names(
        "x-enforcement-actions", rows, fields
    )
    assert counts == {"service_name": 1}
    assert fieldnames == fields  # the existing notes column holds the note
    assert out[0]["service_name"] is None
    assert out[0]["service_approval_number"] == "SE-00000001"
    assert out[0]["provider_approval_number"] == "PR-00000009"
    assert out[0]["notes"] == "duplicate row in source; " + common.SERVICE_NAME_WITHHELD_NOTE
    assert out[1]["service_name"] == "Riverside Family Day Care"


def test_service_name_withheld_through_the_subject_of_a_withheld_row(ctx):
    rows = [{"record_id": "r1", "service_name": "Jane Sample's Little Learners", "notes": None}]
    rows[0]["_subject_raw"] = "Jane Sample"
    out, _, counts = common.withhold_person_named_names("y", rows, ["record_id", "service_name"])
    assert counts == {"service_name": 1} and out[0]["service_name"] is None


def test_a_name_withheld_once_is_withheld_in_every_later_output(ctx):
    ctx.withheld["PR-00000009"] = "Jane Sample"
    first = [{"provider_approval_number": "PR-00000009", "service_name": "Sample Kids Club"}]
    common.withhold_person_named_names("a", first, ["provider_approval_number", "service_name"])
    later = [{"acecqa_service_name": "Sample Kids Club", "notes": None}]
    out, _, counts = common.withhold_person_named_names(
        "b", later, ["acecqa_service_name", "notes"]
    )
    assert counts == {"acecqa_service_name": 1} and out[0]["acecqa_service_name"] is None


def test_service_stub_name_and_variants_withheld_provider_stub_untouched(ctx):
    names = _names("Jane Example")
    common.set_person_names(names)
    rows = [
        {
            "key": "SE-00000003",
            "kind": "service",
            "name": "Jane Example Family Day Care",
            "name_withheld": "false",
            "stub_name_variants": "Riverside Kids Club | Jane Example FDC",
            "note": "unlisted",
        },
        {
            "key": "PR-00000003",
            "kind": "provider",
            "name": "Riverside Holdings Pty Ltd",
            "name_withheld": "false",
            "stub_name_variants": None,
            "note": "unlisted",
        },
    ]
    out, fieldnames, counts = common.withhold_person_named_names(
        "spine-unlisted", rows, list(rows[0])
    )
    assert counts == {"name": 1, "stub_name_variants": 1}
    assert "name_note" not in fieldnames
    assert out[0]["name"] is None and out[0]["name_withheld"] == "true"
    assert out[0]["stub_name_variants"] == "Riverside Kids Club"
    assert out[0]["note"] == "unlisted; " + common.SERVICE_NAME_WITHHELD_NOTE
    assert out[1] is rows[1]


def test_write_processed_applies_the_rule_and_counts_in_provenance(ctx, tmp_path, monkeypatch):
    monkeypatch.setattr(common, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(common, "PROCESSED_DIR", tmp_path / "data" / "processed")
    rows = [
        {"service_approval_number": "SE-00000001", "service_name": "Mrs Example's Kindy"},
        {"service_approval_number": "SE-00000002", "service_name": "Little Acorns Early Learning"},
    ]
    common.write_processed(
        "by-service", rows, ["service_approval_number", "service_name"], raw_inputs=[]
    )
    with (tmp_path / "data" / "processed" / "by-service.csv").open(encoding="utf-8") as fh:
        written = list(csv.DictReader(fh))
    assert written[0]["service_approval_number"] == "SE-00000001"
    assert written[0]["service_name"] == ""
    assert written[0]["service_name_note"] == common.SERVICE_NAME_WITHHELD_NOTE
    assert written[1]["service_name"] == "Little Acorns Early Learning"
    prov = json.loads(
        (tmp_path / "data" / "processed" / "by-service.provenance.json").read_text("utf-8")
    )
    assert prov["names_withheld"]["counts"] == {"service_name": 1}
    assert "Example" not in json.dumps(prov)


# ---------------------------------------------------------------------------
# The join
# ---------------------------------------------------------------------------


def test_join_restores_withheld_service_names_in_memory_only(ctx):
    common.set_person_names(_names("Jane Example"))
    rows = [
        {"record_id": "a", "service_name": "Jane Example Family Day Care", "notes": None},
        {"record_id": "b", "service_name": "Riverside Kids Club", "notes": None},
    ]
    out, _, _ = common.withhold_person_named_names(
        "qld-enforcement-actions", rows, ["record_id", "service_name", "notes"]
    )
    # as read back from the CSV: the name is null and the note is set
    read = [{k: ("" if v is None else v) for k, v in r.items()} for r in out]
    assert common.unrestored_withheld_names(read) == 1
    assert common.restore_withheld_names("qld-enforcement-actions", read) == 1
    assert read[0]["service_name"] == "Jane Example Family Day Care"
    assert common.SERVICE_NAME_WITHHELD_NOTE in read[0]["notes"]
    # written again, the restored name is withheld again
    again, _, counts = common.withhold_person_named_names(
        "enforcement-actions-all", read, ["record_id", "service_name", "notes"]
    )
    assert counts == {"service_name": 1} and again[0]["service_name"] is None


def test_restore_skips_a_row_whose_record_id_differs(ctx):
    common.set_person_names(_names("Jane Example"))
    rows = [{"record_id": "a", "service_name": "Jane Example Kindy", "notes": None}]
    common.withhold_person_named_names("z", rows, ["record_id", "service_name", "notes"])
    read = [{"record_id": "other", "service_name": "", "notes": ""}]
    assert common.restore_withheld_names("z", read) == 0
    assert read[0]["service_name"] == ""


def test_name_rule_notes_do_not_mark_the_subject_withheld():
    for note in (common.SERVICE_NAME_WITHHELD_NOTE, common.TRADING_NAME_WITHHELD_NOTE):
        assert not je.name_withheld_row({"notes": note})
    assert je.name_withheld_row({"notes": "provider name withheld"})


# ---------------------------------------------------------------------------
# Codex round 1
# ---------------------------------------------------------------------------


def test_fixed_point_rechecks_every_column_of_a_row_already_changed(ctx):
    # Row 0's service_name fires at once; its acecqa_service_name is withheld only because row 1
    # (later) withholds the same name through its own withheld provider.
    ctx.withheld["PR-00000009"] = "Jane Sample"
    rows = [
        {
            "record_id": "r0",
            "provider_approval_number": "PR-00000001",
            "service_name": "Mrs Example's Kindy",
            "acecqa_service_name": "Sample Kids Club",
            "notes": None,
        },
        {
            "record_id": "r1",
            "provider_approval_number": "PR-00000009",
            "service_name": "Sample Kids Club",
            "acecqa_service_name": None,
            "notes": None,
        },
    ]
    out, _, counts = common.withhold_person_named_names("all", rows, list(rows[0]))
    assert out[0]["service_name"] is None
    assert out[0]["acecqa_service_name"] is None
    assert out[1]["service_name"] is None
    assert counts == {"service_name": 2, "acecqa_service_name": 1}


@pytest.mark.parametrize(
    "subject, text",
    [
        ("Ann-Marie Example", "Ann Marie Example Family Day Care"),
        ("Ann Marie Example", "Ann-Marie Example Family Day Care"),
        ("Jane Example-Sample", "Jane Example Sample Kindy"),
        ("Jane Example Sample", "Jane Example-Sample Kindy"),
        ("Jane Example-Sample", "Example Sample Kids Club"),
    ],
)
def test_hyphen_and_space_variants_match_alike(subject, text):
    assert _names(subject).found_in(text)


def _write_two(tmp_path, monkeypatch, order):
    root = tmp_path / order
    monkeypatch.setattr(common, "PROJECT_ROOT", root)
    monkeypatch.setattr(common, "PROCESSED_DIR", root / "data" / "processed")
    common.reset_withheld_names()
    context = AcecqaNameContext()
    context.withheld["PR-00000009"] = "Jane Sample"
    common.set_name_context(context)
    common.set_person_names(PersonNames())
    outputs = {
        # No context on this row: kept unless the name is withheld somewhere else.
        "first": (
            [{"record_id": "a", "service_name": "Sample Kids Club", "notes": None}],
            ["record_id", "service_name", "notes"],
        ),
        # The same name with its own withheld provider: withheld.
        "second": (
            [
                {
                    "service_approval_number": "SE-00000001",
                    "provider_approval_number": "PR-00000009",
                    "service_name": "Sample Kids Club",
                }
            ],
            ["service_approval_number", "provider_approval_number", "service_name"],
        ),
    }
    names = ["first", "second"] if order == "ab" else ["second", "first"]
    for name in names:
        rows, fields = outputs[name]
        common.write_processed(name, rows, fields, raw_inputs=[])
    common.refilter_processed_names()
    d = root / "data" / "processed"
    result = {}
    for name in ("first", "second"):
        prov = json.loads((d / f"{name}.provenance.json").read_text("utf-8"))
        result[name] = ((d / f"{name}.csv").read_text("utf-8"), prov["names_withheld"]["counts"])
    return result


def test_two_outputs_in_either_order_give_identical_results(tmp_path, monkeypatch):
    ab = _write_two(tmp_path, monkeypatch, "ab")
    ba = _write_two(tmp_path, monkeypatch, "ba")
    assert ab == ba
    for csv_text, counts in ab.values():
        assert "Sample Kids Club" not in csv_text
        assert counts == {"service_name": 1}


def test_hyphenated_business_words_are_not_taken_for_a_name():
    names = _names("Little Pre-School", "Jane Example")
    assert not names.found_in("Riverside Pre School")
    assert not names.found_in("Riverside Pre-School")
    assert names.found_in("Jane Example Pre-School")


# ---------------------------------------------------------------------------
# Codex round 2
# ---------------------------------------------------------------------------


def _csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


@pytest.fixture
def join_dir(tmp_path, monkeypatch, ctx):
    d = tmp_path / "data" / "processed"
    for mod in (common, je):
        monkeypatch.setattr(mod, "PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(mod, "PROCESSED_DIR", d)
    monkeypatch.setattr(je, "SERVICES_CSV", d / "acecqa-services-latest.csv")
    monkeypatch.setattr(je, "PROVIDERS_CSV", d / "acecqa-providers-latest.csv")
    monkeypatch.setattr(je, "PROFILE_CSV", d / "provider-profile.csv")
    monkeypatch.setattr(je, "ABN_DETAILS_CSV", d / "abn-details.csv")
    monkeypatch.setattr(je, "REPORT_JSON", d / "enforcement-join-report.json")
    _csv(
        d / "acecqa-services-latest.csv",
        [
            {
                "ServiceApprovalNumber": "SE-00000001",
                "service_approval_number": "SE-00000001",
                "ServiceName": "Riverside Kids Club",
                "State": "QLD",
                "Suburb": "Exampleton",
                "provider_approval_number": "PR-00000001",
                "ServiceType": "Centre-Based Care",
                "snapshot_last_modified": "Fri, 30 Oct 2026 00:00:00 GMT",
            }
        ],
    )
    _csv(
        d / "acecqa-providers-latest.csv",
        [{"provider_approval_number": "PR-00000001", "Legal Name": "Riverside Pty Ltd"}],
    )
    _csv(
        d / "provider-profile.csv",
        [
            {
                "provider_approval_number": "PR-00000001",
                "legal_name": "Riverside Pty Ltd",
                "trading_name": "",
                "name_withheld": "false",
                "entity_form": "company",
                "service_count": "1",
            }
        ],
    )
    _csv(
        d / "qld-enforcement-actions.csv",
        [
            {
                "record_id": "q1",
                "jurisdiction": "QLD",
                "source_register": "x",
                "captured_at": "2026-10-29",
                "service_name": "",
                "state": "QLD",
                "action_type": "compliance_notice",
                "action_type_raw": "Compliance notice",
                "date_issued": "2026-01-01",
                "notes": common.SERVICE_NAME_WITHHELD_NOTE,
            }
        ],
    )
    monkeypatch.setattr(je, "discover_action_files", lambda: [d / "qld-enforcement-actions.csv"])
    monkeypatch.setattr(je, "load_abn_details", lambda: None)
    return d


def test_standalone_join_refuses_when_withheld_names_cannot_be_restored(join_dir, capsys):
    with pytest.raises(SystemExit) as exc:
        je.main([])
    assert exc.value.code == je.UNRESTORED_EXIT
    assert "reparse_offline.py" in capsys.readouterr().out
    assert not (join_dir / "enforcement-actions-all.csv").exists()
    assert not (join_dir / "enforcement-join-report.json").exists()


def test_allow_unrestored_writes_and_records_the_count(join_dir):
    je.main(["--allow-unrestored"])
    report = json.loads((join_dir / "enforcement-join-report.json").read_text("utf-8"))
    assert report["unrestored_withheld_service_names"] == 1
    assert (join_dir / "enforcement-actions-all.csv").exists()


def test_business_name_equal_to_a_later_withheld_service_name_in_either_order(
    tmp_path, monkeypatch
):
    def run(order):
        root = tmp_path / order
        monkeypatch.setattr(common, "PROJECT_ROOT", root)
        monkeypatch.setattr(common, "PROCESSED_DIR", root / "data" / "processed")
        common.reset_withheld_names()
        context = AcecqaNameContext()
        context.withheld["PR-00000009"] = "Jane Sample"
        common.set_name_context(context)
        common.set_person_names(PersonNames())
        outputs = {
            "provider-abn": (
                [
                    {
                        "provider_approval_number": "PR-00000002",
                        "business_names": "Sample Kids Club; Riverside Kids",
                        "note": None,
                    }
                ],
                ["provider_approval_number", "business_names", "note"],
            ),
            "by-service": (
                [{"provider_approval_number": "PR-00000009", "service_name": "Sample Kids Club"}],
                ["provider_approval_number", "service_name"],
            ),
        }
        names = list(outputs) if order == "ab" else list(reversed(outputs))
        for name in names:
            common.write_processed(name, *outputs[name], raw_inputs=[])
        common.refilter_processed_names()
        d = root / "data" / "processed"
        return {n: (d / f"{n}.csv").read_text("utf-8") for n in outputs}

    ab, ba = run("ab"), run("ba")
    assert ab == ba
    rows = list(csv.DictReader(ab["provider-abn"].splitlines()))
    assert rows[0]["business_names"] == "Riverside Kids"
    assert rows[0]["note"] == common.BUSINESS_NAME_WITHHELD_NOTE


def test_a_name_withheld_from_abr_propagates_to_trading_name(ctx):
    from scrapers import abn_lookup as al

    common.set_person_names(_names("Jane Example"))
    kept, withheld = al.safe_business_names(["Jane Example Kindy", "Sunny Kids Club"], set())
    assert withheld >= 1 and "Jane Example Kindy" not in kept
    # A later output in the same process, with no names that would fire by themselves.
    common.set_person_names(PersonNames())
    rows = [{"provider_approval_number": "PR-00000003", "trading_name": "Jane Example Kindy"}]
    out, _, counts = common.withhold_person_named_names(
        "provider-profile", rows, ["provider_approval_number", "trading_name"]
    )
    assert counts == {"trading_name": 1} and out[0]["trading_name"] is None


def test_business_names_withheld_count_column_is_raised(ctx):
    common.set_person_names(_names("Jane Example"))
    rows = [{"business_names": "Jane Example Kindy; Sunny Kids Club", "business_names_withheld": 1}]
    out, _, _ = common.withhold_person_named_names(
        "abn-details", rows, ["business_names", "business_names_withheld", "note"]
    )
    assert out[0]["business_names"] == "Sunny Kids Club"
    assert out[0]["business_names_withheld"] == 2


def test_known_name_window_covers_hyphen_splits_longer_than_five_words():
    names = _names("Ann-Marie Jo-Anne Example-Sample")
    assert names.found_in("Ann Marie Jo Anne Example Sample Family Day Care")


# ---------------------------------------------------------------------------
# Codex round 3: ABN entity stage on the full business-name list
# ---------------------------------------------------------------------------

ABN = "12345678901"
_REAL_LOAD_ABN = je.load_abn_details


def _abn_spine():
    providers = [
        {
            "provider_approval_number": "PR-00000101",
            "Legal Name": "Alpha Holdings Pty Ltd",
            "Trading Name": "",
            "State": "NSW",
        },
        {
            "provider_approval_number": "PR-00000202",
            "Legal Name": "Bravo Group Pty Ltd",
            "Trading Name": "Bravo Kids Club",
            "State": "NSW",
        },
    ]
    profiles = [
        {"provider_approval_number": p["provider_approval_number"], "name_withheld": "false"}
        for p in providers
    ]
    return je.Spine([], profiles, providers)


def _write_cache(cache_dir, business_names):
    import hashlib

    cache_dir.mkdir(parents=True, exist_ok=True)
    body = json.dumps(
        {"Abn": ABN, "EntityName": "Alpha Holdings Pty Ltd", "BusinessName": business_names}
    )
    data = f"callback({body})".encode()
    (cache_dir / "2026-10-30T0000Z-details.json").write_bytes(data)
    (cache_dir / "2026-10-30T0000Z-details.json.meta.json").write_text(
        json.dumps(
            {
                "endpoint": "AbnDetails.aspx",
                "query": {"abn": ABN},
                "fetched_at": "2026-10-30T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    return hashlib.sha256(data).hexdigest()


def _details(sha=None):
    return {
        ABN: {
            "abn": ABN,
            "lookup_status": "ok",
            "entity_name": "Alpha Holdings Pty Ltd",
            "business_names": "",
            "business_names_withheld": "1",
            "response_sha256": sha or "0" * 64,
        }
    }


def test_withheld_business_name_matching_a_second_provider_stays_ambiguous(tmp_path):
    sha = _write_cache(tmp_path / "abr-lookup", ["Bravo Kids Club"])
    details = _details(sha)
    assert je.restore_business_names(details, tmp_path / "abr-lookup") == 0
    pr, note = je.match_by_abn_entity(ABN, details, _abn_spine())
    assert pr is None and "ambiguous" in note
    # the restored list is in memory only, never in a published column
    assert details[ABN]["business_names"] == ""


def test_unique_match_is_still_accepted_with_the_full_list_restored(tmp_path):
    sha = _write_cache(tmp_path / "abr-lookup", ["Unrelated Learning Centre"])
    details = _details(sha)
    assert je.restore_business_names(details, tmp_path / "abr-lookup") == 0
    pr, _ = je.match_by_abn_entity(ABN, details, _abn_spine())
    assert pr == "PR-00000101"


def test_no_cache_fails_closed(tmp_path):
    details = _details()
    assert je.restore_business_names(details, tmp_path / "missing") == 1
    pr, note = je.match_by_abn_entity(ABN, details, _abn_spine())
    assert pr is None and note == je.ABN_NOT_RESTORABLE_NOTE


def test_a_cached_response_that_is_not_the_rows_response_fails_closed(tmp_path):
    _write_cache(tmp_path / "abr-lookup", ["Unrelated Learning Centre"])
    details = _details("f" * 64)
    assert je.restore_business_names(details, tmp_path / "abr-lookup") == 1
    assert je.match_by_abn_entity(ABN, details, _abn_spine())[0] is None


def test_row_with_nothing_withheld_needs_no_cache(tmp_path):
    details = _details()
    details[ABN]["business_names_withheld"] = "0"
    assert je.restore_business_names(details, tmp_path / "missing") == 0
    assert je.match_by_abn_entity(ABN, details, _abn_spine())[0] == "PR-00000101"


def test_abn_stage_is_idempotent_across_runs(tmp_path):
    sha = _write_cache(tmp_path / "abr-lookup", ["Bravo Kids Club", "Unrelated"])
    results = []
    for _ in range(2):
        details = _details(sha)
        je.restore_business_names(details, tmp_path / "abr-lookup")
        results.append(je.match_by_abn_entity(ABN, details, _abn_spine()))
    assert results[0] == results[1]


def test_standalone_join_refuses_when_abn_business_names_cannot_be_restored(
    join_dir, monkeypatch, capsys
):
    # Only the ABN guard: the QLD row's service name is not withheld here.
    qld = join_dir / "qld-enforcement-actions.csv"
    _csv(
        qld,
        [
            {
                "record_id": "c1",
                "jurisdiction": "CTH",
                "source_register": "x",
                "captured_at": "2026-10-29",
                "service_name": "",
                "state": "",
                "action_type": "ccs_sanction",
                "action_type_raw": "Sanction",
                "date_issued": "2026-01-01",
                "notes": f"ccs_identifier: ABN {ABN}",
            }
        ],
    )
    _csv(join_dir / "abn-details.csv", [_details()[ABN]])
    monkeypatch.setattr(
        je, "load_abn_details", lambda: _REAL_LOAD_ABN(join_dir / "abn-details.csv")
    )
    with pytest.raises(SystemExit) as exc:
        je.main([])
    assert exc.value.code == je.UNRESTORED_EXIT
    assert "abr-lookup" in capsys.readouterr().out
    assert not (join_dir / "enforcement-join-report.json").exists()
    je.main(["--allow-unrestored"])
    report = json.loads((join_dir / "enforcement-join-report.json").read_text("utf-8"))
    assert report["abn_entity_rows_not_matched_business_names_not_restorable"] == 1


# ---------------------------------------------------------------------------
# Codex rounds 4 and 5: a row whose ABN entity stage failed closed is never rescued
# ---------------------------------------------------------------------------


def _cth_row(name="Alpha Holdings Pty Ltd"):
    return {
        "record_id": "c1",
        "jurisdiction": "CTH",
        "source_register": "x",
        "captured_at": "2026-10-29",
        "provider_name": name,
        "action_type": "ccs_sanction",
        "action_type_raw": "Sanction",
        "date_issued": "2026-01-01",
        "notes": f"ccs_identifier: ABN {ABN}",
    }


def _unrestorable(tmp_path):
    details = _details()
    je.restore_business_names(details, tmp_path / "missing")
    return details


@pytest.mark.parametrize("name", ["Alpha Holdings Pty Ltd", "Bravo Group Pty Ltd"])
def test_a_flagged_row_stays_unmatched_even_when_a_name_matches(tmp_path, name):
    # Each printed provider name matches exactly one ACECQA provider by name.
    (row,) = je.join_actions([_cth_row(name)], _abn_spine(), _unrestorable(tmp_path))
    assert row["match_confidence"] == je.CONFIDENCE_NONE
    assert row.get("acecqa_provider_approval_number") is None
    assert row["_abn_unrestorable"]
    assert je.ABN_NOT_RESTORABLE_NOTE in row["join_note"]
    assert "ambiguous" not in je.ABN_NOT_RESTORABLE_NOTE
    assert je.residual_reason(row) == "abn_business_names_not_restorable"


def test_without_the_abn_failure_the_name_stage_still_joins(tmp_path):
    details = _details()
    details[ABN]["lookup_status"] = "not_found"  # the ABN stage does not apply
    (row,) = je.join_actions([_cth_row("Bravo Group Pty Ltd")], _abn_spine(), details)
    assert row["acecqa_provider_approval_number"] == "PR-00000202"
    assert not row.get("_abn_unrestorable")


def test_cache_restore_needs_the_rows_response_hash(tmp_path):
    from scrapers import abn_lookup as al

    _write_cache(tmp_path / "abr-lookup", ["Unrelated"])
    assert al.cached_business_names(ABN, None, tmp_path / "abr-lookup") is None
    assert al.cached_business_names(ABN, "", tmp_path / "abr-lookup") is None


# ---------------------------------------------------------------------------
# Codex round 6: free text may not repeat a withheld name
# ---------------------------------------------------------------------------

QLD_FIELDS = ["record_id", "service_name", "reason", "notes"]


def _write_qld_and_service(tmp_path, monkeypatch, order):
    root = tmp_path / order
    monkeypatch.setattr(common, "PROJECT_ROOT", root)
    monkeypatch.setattr(common, "PROCESSED_DIR", root / "data" / "processed")
    common.reset_withheld_names()
    context = AcecqaNameContext()
    context.withheld["PR-00000009"] = "Jane Sample"
    common.set_name_context(context)
    common.set_person_names(PersonNames())
    outputs = {
        "qld-enforcement-actions": (
            [
                {
                    "record_id": "q1",
                    "service_name": "Sample Kids Club",
                    "reason": "Compliance notice issued to Sample Kids Club after a visit.",
                    "notes": "duplicate row in source",
                },
                {
                    "record_id": "q2",
                    "service_name": "Riverside Kids Club",
                    "reason": "Compliance notice issued to Riverside Kids Club after a visit.",
                    "notes": None,
                },
            ],
            QLD_FIELDS,
        ),
        "by-service": (
            [{"provider_approval_number": "PR-00000009", "service_name": "Sample Kids Club"}],
            ["provider_approval_number", "service_name"],
        ),
    }
    names = list(outputs) if order == "ab" else list(reversed(outputs))
    for name in names:
        common.write_processed(name, *outputs[name], raw_inputs=[])
    common.refilter_processed_names()
    d = root / "data" / "processed"
    return {n: (d / f"{n}.csv").read_text("utf-8") for n in outputs}


def test_prose_repeating_a_withheld_service_name_is_withheld_in_either_order(tmp_path, monkeypatch):
    ab = _write_qld_and_service(tmp_path, monkeypatch, "ab")
    ba = _write_qld_and_service(tmp_path, monkeypatch, "ba")
    assert ab == ba
    rows = list(csv.DictReader(ab["qld-enforcement-actions"].splitlines()))
    assert rows[0]["service_name"] == "" and rows[0]["reason"] == ""
    assert common.PROSE_WITHHELD_NOTE in rows[0]["notes"]
    assert "duplicate row in source" in rows[0]["notes"]
    # prose repeating an ordinary, kept service name is kept
    assert rows[1]["service_name"] == "Riverside Kids Club"
    assert rows[1]["reason"].startswith("Compliance notice issued to Riverside Kids Club")
    assert "Sample Kids Club" not in ab["qld-enforcement-actions"]


def test_the_prose_rule_does_not_exempt_a_service_name_the_name_rule_withholds(ctx):
    common.set_person_names(_names("Jane Example"))
    rows = [
        {
            "service_name": "Jane Example Family Day Care",
            "provider_name": None,
            "suburb": "Exampleton",
            "reason": "Breach found at Jane Example Family Day Care.",
            "notes": None,
        },
        {
            "service_name": "Riverside Family Day Care",
            "provider_name": None,
            "suburb": "Exampleton",
            "reason": "Breach found at Riverside Family Day Care.",
            "notes": None,
        },
    ]
    counts = common.withhold_prose_naming_people(rows)
    assert counts.get("reason") == 1
    assert rows[0]["reason"] is None
    assert rows[1]["reason"] == "Breach found at Riverside Family Day Care."


def test_a_withheld_trading_name_in_free_text_is_withheld(ctx):
    rows = [
        {
            "provider_approval_number": "PR-00000001",
            "trading_name": "Jane Example",
            "reason": "Operates as Jane Example in two suburbs.",
            "notes": None,
        }
    ]
    out, _, counts = common.withhold_person_named_names("x", rows, list(rows[0]))
    assert out[0]["trading_name"] is None and out[0]["reason"] is None
    assert counts == {"trading_name": 1, "reason": 1}
    assert common.PROSE_WITHHELD_NOTE in out[0]["notes"]


def test_whole_word_and_hyphen_spacing_in_the_free_text_scan(ctx):
    common.note_withheld_name("Ann-Marie Sample Kindy")
    rows = [
        {"reason": "Visit to Ann Marie Sample Kindy.", "notes": None},
        {"reason": "Visit to Ann-Marie Sample Kindygarten.", "notes": None},
    ]
    out, _, counts = common.withhold_person_named_names("y", rows, ["reason", "notes"])
    assert out[0]["reason"] is None
    assert out[1]["reason"] == "Visit to Ann-Marie Sample Kindygarten."
    assert counts == {"reason": 1}
