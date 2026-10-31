"""PR #11: keyed joins. Names withheld by the shared fail-closed rule are kept only as keyed
hashes (HMAC-SHA256 under TICA_JOIN_KEY) in a private, gitignored sidecar, and the join matches
them on those keys with the old rules. No name or key reaches a published output. All names are
synthetic; the key is the fixed test key from conftest."""

import subprocess
from pathlib import Path

import pytest
from scrapers import common
from scrapers import join_enforcement as je
from scrapers import profile_providers as pp
from scrapers import reparse_offline as ro

from tests.conftest import TEST_JOIN_KEY
from tests.test_reparse_offline import make_parser

KEY = bytes.fromhex(TEST_JOIN_KEY)
ROOT = Path(__file__).resolve().parent.parent
# Withheld by the shared rule for lack of organisation evidence only (no person signal).
PROVIDER = "Example Kids Learning Collective"
SERVICE = "Sunny Meadow Early Learning"
NAMES = ("example kids", "sunny meadow")
QLD_KEYS = "qld-enforcement-actions"


def _spine(*, second_provider_named_alike=False):
    services = [
        {
            "ServiceApprovalNumber": "SE-00000101",
            "service_approval_number": "SE-00000101",
            "ServiceName": SERVICE,
            "State": "QLD",
            "Provider Approval Number": "PR-00000001",
        },
        {
            "ServiceApprovalNumber": "SE-00000102",
            "service_approval_number": "SE-00000102",
            "ServiceName": "Other Learning Centre",
            "State": "QLD",
            "Provider Approval Number": "PR-00000001",
        },
    ]
    profiles = [
        {
            "provider_approval_number": "PR-00000001",
            "legal_name": "",
            "entity_form": "trust_or_trustee",
            "name_withheld": "true",
            "service_count": "2",
        }
    ]
    providers = [
        {"Provider Approval Number": "PR-00000001", "Legal Name": PROVIDER, "State": "QLD"}
    ]
    if second_provider_named_alike:
        services.append(
            {
                "ServiceApprovalNumber": "SE-00000201",
                "service_approval_number": "SE-00000201",
                "ServiceName": "Another Service",
                "State": "QLD",
                "Provider Approval Number": "PR-00000002",
            }
        )
        profiles.append(
            {
                "provider_approval_number": "PR-00000002",
                "legal_name": "",
                "entity_form": "trust_or_trustee",
                "name_withheld": "true",
                "service_count": "1",
            }
        )
        providers.append(
            {"Provider Approval Number": "PR-00000002", "Legal Name": PROVIDER, "State": "QLD"}
        )
    return je.Spine(services, profiles, providers), providers


def _withheld_row(record_id="r1", jurisdiction="QLD"):
    return {
        "record_id": record_id,
        "jurisdiction": jurisdiction,
        "provider_name": None,
        "service_name": None,
        "notes": "provider name withheld: may identify an individual",
    }


def _keyed(spine, providers, record_id="r1", service=SERVICE):
    rows = {
        record_id: (common.provider_name_key(PROVIDER, KEY), common.service_name_key(service, KEY))
    }
    return je.KeyedNames(spine, KEY, rows, providers)


def test_the_name_key_is_deterministic_and_depends_on_the_key():
    a = common.provider_name_key(PROVIDER, KEY)
    assert a == common.provider_name_key(PROVIDER, KEY)
    assert a == common.provider_name_key("example kids learning-collective.", KEY)
    assert a != common.provider_name_key(PROVIDER, bytes.fromhex("a5" * 32))
    assert len(a) == 64 and PROVIDER.lower() not in a


def test_a_qld_row_is_matched_on_its_keyed_service_name_first():
    spine, providers = _spine()
    [out] = je.join_actions([_withheld_row()], spine, None, _keyed(spine, providers))
    assert out["join_key_kind"] == "name_match"
    assert out["acecqa_service_approval_number"] == "SE-00000101"
    assert out["acecqa_provider_approval_number"] == "PR-00000001"
    assert out["acecqa_service_name"] is None and out["acecqa_provider_legal_name"] is None


def test_a_recovered_join_gets_the_right_approval_numbers():
    spine, providers = _spine()
    row = _withheld_row(jurisdiction="CTH")
    [out] = je.join_actions([row], spine, None, _keyed(spine, providers))
    assert out["acecqa_provider_approval_number"] == "PR-00000001"
    assert out["acecqa_service_approval_number"] == "SE-00000101"
    assert out["join_key_kind"] == "provider_name_match"
    assert out["match_confidence"] == je.CONFIDENCE_PROVIDER_AND_SERVICE
    assert je.KEYED_NOTE in out["join_note"]
    assert out["acecqa_service_name"] is None and out["acecqa_provider_legal_name"] is None


def test_without_the_keyed_stage_the_row_stays_unmatched():
    spine, _ = _spine()
    [out] = je.join_actions([_withheld_row()], spine, None, None)
    assert out["match_confidence"] == je.CONFIDENCE_NONE


def test_an_ambiguous_key_stays_unmatched_with_the_existing_reason():
    spine, providers = _spine(second_provider_named_alike=True)
    [out] = je.join_actions([_withheld_row()], spine, None, _keyed(spine, providers, service=None))
    assert out["match_confidence"] == je.CONFIDENCE_NONE
    assert out["acecqa_provider_approval_number"] is None
    assert je.residual_reason(out) == "no_key_and_name_withheld"


def test_a_provider_that_reads_as_an_individual_is_never_matched():
    spine, providers = _spine()
    spine.profiles["PR-00000001"]["entity_form"] = "likely_individual"
    [out] = je.join_actions([_withheld_row()], spine, None, _keyed(spine, providers, service=None))
    assert out["match_confidence"] == je.CONFIDENCE_NONE


def _scan(paths, needles):
    hits = []
    for path in paths:
        text = path.read_text(encoding="utf-8").lower()
        hits.extend((path.name, n) for n in needles if n.lower() in text)
    return hits


def test_no_name_or_key_reaches_a_published_output(tmp_path, monkeypatch):
    processed = tmp_path / "processed"
    monkeypatch.setattr(common, "PROCESSED_DIR", processed)
    monkeypatch.setattr(common, "PROJECT_ROOT", tmp_path)
    parsed = {"record_id": "r1", "jurisdiction": "QLD", "provider_name": None, "notes": "x"}
    common.keep_withheld_names(parsed, provider=PROVIDER, service=SERVICE)
    assert all(n not in str(parsed).lower() for n in NAMES)  # the row holds only a token
    common.write_processed("qld-enforcement-actions", [parsed], list(parsed), raw_inputs=[])
    sidecar = tmp_path / "private" / "name-keys" / "qld-enforcement-actions.csv"
    assert sidecar.exists()
    keys = common.read_name_keys("qld-enforcement-actions", KEY)
    assert keys["r1"] == (
        common.provider_name_key(PROVIDER, KEY),
        common.service_name_key(SERVICE, KEY),
    )
    spine, providers = _spine()
    joined = je.join_actions(
        [_withheld_row()], spine, None, je.KeyedNames(spine, KEY, keys, providers)
    )
    common.write_processed("enforcement-actions-all", joined, je.ALL_COLUMNS, raw_inputs=[])
    published = sorted(processed.iterdir())
    needles = [*NAMES, TEST_JOIN_KEY, *keys["r1"], common.key_check(KEY)]
    assert published and not _scan(published, needles)
    assert not _scan([sidecar], NAMES)


def _sidecar(tmp_path, monkeypatch, rows, *, name=QLD_KEYS):
    monkeypatch.setattr(common, "PROCESSED_DIR", tmp_path / "processed")
    monkeypatch.setattr(common, "PROJECT_ROOT", tmp_path)
    common.write_processed(name, rows, ["record_id"], raw_inputs=[])
    return tmp_path / "private" / "name-keys" / f"{name}.csv"


def _withheld(record_id="r1"):
    row = {"record_id": record_id}
    common.keep_withheld_names(row, provider=PROVIDER, service=SERVICE)
    return row


def test_a_sidecar_written_with_another_key_is_refused(tmp_path, monkeypatch):
    _sidecar(tmp_path, monkeypatch, [_withheld()])
    with pytest.raises(common.JoinKeyMissing, match="another"):
        common.read_name_keys(QLD_KEYS, bytes.fromhex("a5" * 32))


def test_a_missing_sidecar_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "PROCESSED_DIR", tmp_path / "processed")
    with pytest.raises(common.JoinKeyMissing, match="missing"):
        common.read_name_keys(QLD_KEYS, KEY)
    spine, providers = _spine()
    with pytest.raises(SystemExit, match="missing"):
        je.keyed_names_for(spine, [tmp_path / "processed" / f"{QLD_KEYS}.csv"], providers)


def test_a_sidecar_without_its_check_row_is_refused(tmp_path, monkeypatch):
    path = _sidecar(tmp_path, monkeypatch, [_withheld()])
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    path.write_text(
        "".join(line for line in lines if not line.startswith(common.KEY_CHECK_ID)),
        encoding="utf-8",
    )
    with pytest.raises(common.JoinKeyMissing, match="no key-check row"):
        common.read_name_keys(QLD_KEYS, KEY)


def test_an_empty_eligible_set_writes_a_check_row_only_sidecar(tmp_path, monkeypatch):
    path = _sidecar(tmp_path, monkeypatch, [{"record_id": "r9"}])
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2  # header and check row
    assert common.read_name_keys(QLD_KEYS, KEY) == {}


def test_a_stale_sidecar_is_rewritten_or_deleted(tmp_path, monkeypatch):
    path = _sidecar(tmp_path, monkeypatch, [_withheld("r1")])
    assert set(common.read_name_keys(QLD_KEYS, KEY)) == {"r1"}
    _sidecar(tmp_path, monkeypatch, [{"record_id": "r2"}])
    assert common.read_name_keys(QLD_KEYS, KEY) == {}  # rewritten, r1 gone
    common.skip_name_keys()
    _sidecar(tmp_path, monkeypatch, [_withheld("r3")])
    assert not path.exists()  # --no-keyed-join deletes it


def test_a_keyed_source_without_the_key_stops_before_any_write(tmp_path, monkeypatch):
    monkeypatch.delenv(common.JOIN_KEY_VAR)
    with pytest.raises(SystemExit, match="TICA_JOIN_KEY is not set"):
        _sidecar(tmp_path, monkeypatch, [_withheld()])
    assert not (tmp_path / "processed" / f"{QLD_KEYS}.csv").exists()
    _sidecar(tmp_path, monkeypatch, [_withheld()], name="wa-enforcement-actions")  # not keyed


def test_a_person_named_trust_and_its_services_are_never_matched():
    spine, providers = _spine()
    providers[0]["Legal Name"] = "Example Kids Pty Ltd ATF Jane Example Family Trust"
    keyed = je.KeyedNames(
        spine,
        KEY,
        {
            "r1": (
                common.provider_name_key(providers[0]["Legal Name"], KEY),
                common.service_name_key(SERVICE, KEY),
            )
        },
        providers,
    )
    assert "PR-00000001" in keyed.excluded
    for row in (_withheld_row(), _withheld_row(jurisdiction="CTH")):
        [out] = je.join_actions([row], spine, None, keyed)
        assert out["match_confidence"] == je.CONFIDENCE_NONE


def test_the_keyed_service_path_excludes_an_individuals_service():
    spine, providers = _spine()
    spine.profiles["PR-00000001"]["entity_form"] = "likely_individual"
    keyed = _keyed(spine, providers)
    assert all(
        sv["ServiceApprovalNumber"] != "SE-00000101"
        for names in keyed.by_name.values()
        for services in names.values()
        for sv in services
    )
    [out] = je.join_actions([_withheld_row()], spine, None, keyed)
    assert out["match_confidence"] == je.CONFIDENCE_NONE


def test_the_pin_falls_back_to_a_printed_service_name_keyed_alike():
    spine, providers = _spine()
    row = _withheld_row(jurisdiction="CTH")
    row["service_name"] = SERVICE  # printed; the sidecar has no service key
    keyed = je.KeyedNames(
        spine, KEY, {"r1": (common.provider_name_key(PROVIDER, KEY), None)}, providers
    )
    [out] = je.join_actions([row], spine, None, keyed)
    assert out["acecqa_service_approval_number"] == "SE-00000101"
    assert out["match_confidence"] == je.CONFIDENCE_PROVIDER_AND_SERVICE


def test_a_keyed_row_keeps_its_service_name_only_when_the_shared_rule_clears_it():
    spine, providers = _spine()
    row = _withheld_row(jurisdiction="CTH")
    row["service_name"] = SERVICE
    keyed = je.KeyedNames(
        spine, KEY, {"r1": (common.provider_name_key(PROVIDER, KEY), None)}, providers
    )
    [out] = je.join_actions([row], spine, None, keyed)
    assert out["service_name"] is None
    assert je.KEYED_SERVICE_NOTE in out["notes"]


def test_the_sidecar_directory_is_ignored_by_git():
    done = subprocess.run(
        ["git", "check-ignore", "-q", "data/private/name-keys/qld-enforcement-actions.csv"],
        cwd=ROOT,
        check=False,
    )
    assert done.returncode == 0


def test_the_join_refuses_to_run_without_the_key(monkeypatch):
    monkeypatch.delenv(common.JOIN_KEY_VAR)
    spine, providers = _spine()
    with pytest.raises(SystemExit, match="TICA_JOIN_KEY is not set"):
        je.keyed_names_for(spine, [], providers)


@pytest.fixture
def processed(tmp_path, monkeypatch):
    d = tmp_path / "processed"
    d.mkdir()
    (d / "a.csv").write_text("old a\n", encoding="utf-8")
    monkeypatch.setattr(ro, "PROCESSED_DIR", d)
    monkeypatch.setattr(ro, "acecqa_person_names", lambda: pp.PersonNames())
    monkeypatch.setattr(common, "REPARSE_MARKER", tmp_path / ".reparse-in-progress")
    monkeypatch.setattr(ro, "BACKUP_ROOT", tmp_path / ".reparse-backup")
    monkeypatch.setattr(ro, "LOCK_PATH", tmp_path / ".reparse.lock")
    monkeypatch.setattr(ro, "PARSERS", [make_parser(d, "a")])
    return d


def test_the_reparse_refuses_to_start_without_the_key(processed, monkeypatch):
    monkeypatch.delenv(common.JOIN_KEY_VAR)
    joins = []
    monkeypatch.setattr(ro, "run_join", lambda: joins.append(1))
    assert ro.main([]) == 5
    assert (processed / "a.csv").read_text(encoding="utf-8") == "old a\n"
    assert not joins


def test_no_keyed_join_runs_without_the_key_and_passes_the_flag(processed, monkeypatch):
    monkeypatch.delenv(common.JOIN_KEY_VAR)
    seen = []
    monkeypatch.setattr(je, "main", lambda argv=None: seen.append(argv))
    assert ro.main(["--no-keyed-join"]) == 0
    assert seen == [["--no-keyed-join"]]
    assert (processed / "a.csv").read_text(encoding="utf-8") == "new 1\n"


def test_the_name_keys_are_backed_up_and_restored_with_the_outputs(processed, monkeypatch):
    keys_dir = processed.parent / "private" / "name-keys"
    keys_dir.mkdir(parents=True)
    (keys_dir / "a.csv").write_text("old keys\n", encoding="utf-8")

    def join_fails():
        (keys_dir / "a.csv").write_text("new keys\n", encoding="utf-8")
        raise SystemExit(2)

    monkeypatch.setattr(ro, "run_join", join_fails)
    assert ro.main([]) != 0
    assert (keys_dir / "a.csv").read_text(encoding="utf-8") == "old keys\n"
