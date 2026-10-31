"""Codex round 7: reparse_offline.py is single-writer; schemas accept fields the rules can null."""

import json
from pathlib import Path

import jsonschema
import pytest
from scrapers import common
from scrapers import profile_providers as pp
from scrapers import reparse_offline as ro

from tests.test_reparse_offline import make_parser

SCHEMA = json.loads(
    (
        Path(__file__).resolve().parent.parent / "data/schemas/enforcement-action.schema.json"
    ).read_text()
)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    d = tmp_path / "processed"
    d.mkdir()
    (d / "a.csv").write_text("old a\n", encoding="utf-8")
    (d / "enforcement-actions-all.csv").write_text("old join\n", encoding="utf-8")
    monkeypatch.setattr(ro, "PROCESSED_DIR", d)
    monkeypatch.setattr(ro, "acecqa_person_names", lambda: pp.PersonNames())
    monkeypatch.setattr(common, "REPARSE_MARKER", tmp_path / ".reparse-in-progress")
    monkeypatch.setattr(ro, "BACKUP_ROOT", tmp_path / ".reparse-backup")
    monkeypatch.setattr(ro, "LOCK_PATH", tmp_path / ".reparse.lock")

    def join_ok():
        (d / "enforcement-actions-all.csv").write_text("new join\n", encoding="utf-8")

    monkeypatch.setattr(ro, "run_join", join_ok)
    return tmp_path, d


def snapshot(root):
    return {
        str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()
    }


def test_a_second_run_while_the_lock_is_held_refuses_without_side_effects(
    setup, monkeypatch, capsys
):
    root, d = setup
    parser = make_parser(d, "a")
    monkeypatch.setattr(ro, "PARSERS", [parser])
    ro.LOCK_PATH.write_text("pid 99999 at 2026-10-31T00:00:00Z\n", encoding="utf-8")
    common.REPARSE_MARKER.write_text("backup: elsewhere\n", encoding="utf-8")
    (ro.BACKUP_ROOT / "2026-10-30T000000Z").mkdir(parents=True)
    (ro.BACKUP_ROOT / "2026-10-30T000000Z" / "a.csv").write_text("backup a\n", encoding="utf-8")
    before = snapshot(root)
    assert ro.main([]) != 0
    assert snapshot(root) == before  # outputs, marker, backups and the lock itself untouched
    assert parser.calls == 0
    out = capsys.readouterr()
    text = out.out + out.err
    assert str(ro.LOCK_PATH) in text and "only if no reparse is running" in text


def test_a_stale_lock_is_reported_not_removed(setup, monkeypatch, capsys):
    root, d = setup
    monkeypatch.setattr(ro, "PARSERS", [make_parser(d, "a")])
    ro.LOCK_PATH.write_text("pid 1 at 2020-01-01T00:00:00Z\n", encoding="utf-8")
    assert ro.main([]) != 0
    assert ro.LOCK_PATH.read_text(encoding="utf-8") == "pid 1 at 2020-01-01T00:00:00Z\n"
    assert "pid 1 at 2020-01-01T00:00:00Z" in capsys.readouterr().out


def test_the_lock_is_held_during_the_run_and_released_after_success(setup, monkeypatch):
    root, d = setup
    seen = {}

    def join_checks_lock():
        seen["lock"] = ro.LOCK_PATH.read_text(encoding="utf-8")
        (d / "enforcement-actions-all.csv").write_text("new join\n", encoding="utf-8")

    monkeypatch.setattr(ro, "PARSERS", [make_parser(d, "a")])
    monkeypatch.setattr(ro, "run_join", join_checks_lock)
    assert ro.main([]) == 0
    assert seen["lock"].startswith("pid ")
    assert not ro.LOCK_PATH.exists()


@pytest.mark.parametrize("where", ["capture", "real", "join", "restore"])
def test_the_lock_is_released_after_every_failure(setup, monkeypatch, where):
    root, d = setup
    kwargs = {"capture": {"fail_on_call": 1}, "real": {"fail_on_call": 2}}.get(where, {})
    monkeypatch.setattr(ro, "PARSERS", [make_parser(d, "a", **kwargs)])
    if where in ("join", "restore"):

        def join_fails():
            raise SystemExit(2)

        monkeypatch.setattr(ro, "run_join", join_fails)
    if where == "restore":

        def restore_fails(*args, **kwargs):
            raise OSError("restore failed")

        monkeypatch.setattr(ro, "_restore", restore_fails)
    assert ro.main([]) != 0
    assert not ro.LOCK_PATH.exists()


def test_the_lock_is_taken_with_exclusive_create(setup, monkeypatch):
    calls = []
    real_open = ro.os.open

    def spy(path, flags, *args):
        calls.append((Path(path), flags))
        return real_open(path, flags, *args)

    monkeypatch.setattr(ro.os, "open", spy)
    ro._acquire_lock()
    ro._release_lock()
    lock_calls = [f for p, f in calls if p == ro.LOCK_PATH]
    assert lock_calls and lock_calls[0] & ro.os.O_EXCL and lock_calls[0] & ro.os.O_CREAT


def test_a_row_with_a_nulled_snapshot_document_and_links_validates():
    row = {
        "record_id": "0123456789abcdef",
        "jurisdiction": "WA",
        "source_register": "https://www.wa.gov.au/register",
        "source_document": None,
        "linked_documents": None,
        "source_snapshot": None,
        "captured_at": "2026-10-29T07:00:00+00:00",
        "action_type": "compliance_notice",
        "action_type_raw": "Compliance Notice",
        "notes": "source snapshot path withheld: may name an individual",
    }
    jsonschema.validate(row, SCHEMA)


def test_the_recovery_text_says_to_remove_untracked_outputs(tmp_path, monkeypatch):
    marker = tmp_path / ".reparse-in-progress"
    marker.write_text("backup: nowhere\n", encoding="utf-8")
    monkeypatch.setattr(common, "REPARSE_MARKER", marker)
    assert "remove any untracked files under data/processed" in common.reparse_recovery_message()
    backup = tmp_path / "b"
    backup.mkdir()
    common.atomic_write_text(backup / common.BACKUP_MANIFEST, json.dumps({"files": []}))
    marker.write_text(f"backup: {backup}\n", encoding="utf-8")
    assert "remove any untracked files under data/processed" in common.reparse_recovery_message()
