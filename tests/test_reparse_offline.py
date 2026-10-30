"""Codex round 4, finding 2: reparse_offline.py is all-or-nothing."""

import pytest
from scrapers import common
from scrapers import profile_providers as pp
from scrapers import reparse_offline as ro


def make_parser(directory, name, *, fail_on_call=None, raise_on_call=None):
    """A fake parser module. Its write_processed writes <name>.csv into `directory`."""

    class Fake:
        calls = 0

        @staticmethod
        def write_processed(out_name, rows, *args, **kwargs):
            (directory / f"{out_name}.csv").write_text(f"new {len(rows)}\n", encoding="utf-8")

        @staticmethod
        def main(argv):
            Fake.calls += 1
            if raise_on_call == Fake.calls:
                raise RuntimeError("parser crashed")
            if fail_on_call == Fake.calls:
                return 2
            Fake.write_processed(name, [{"x": 1}])
            return 0

    Fake.__name__ = name
    return Fake


@pytest.fixture
def processed(tmp_path, monkeypatch):
    d = tmp_path / "processed"
    d.mkdir()
    (d / "a.csv").write_text("old a\n", encoding="utf-8")
    (d / "b.csv").write_text("old b\n", encoding="utf-8")
    (d / "enforcement-actions-all.csv").write_text("old join\n", encoding="utf-8")
    monkeypatch.setattr(ro, "PROCESSED_DIR", d)
    monkeypatch.setattr(ro, "acecqa_person_names", lambda: pp.PersonNames())
    # Codex round 5: the marker and the persistent backup live outside data/processed.
    monkeypatch.setattr(common, "REPARSE_MARKER", tmp_path / ".reparse-in-progress")
    monkeypatch.setattr(ro, "BACKUP_ROOT", tmp_path / ".reparse-backup")

    def join_ok():
        (d / "enforcement-actions-all.csv").write_text("new join\n", encoding="utf-8")

    monkeypatch.setattr(ro, "run_join", join_ok)
    return d


def contents(d):
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(d.iterdir())}


def test_all_succeed_replaces_every_output(processed, monkeypatch):
    monkeypatch.setattr(ro, "PARSERS", [make_parser(processed, "a"), make_parser(processed, "b")])
    assert ro.main([]) == 0
    assert contents(processed) == {
        "a.csv": "new 1\n",
        "b.csv": "new 1\n",
        "enforcement-actions-all.csv": "new join\n",
    }
    assert not common.REPARSE_MARKER.exists()
    assert not any(ro.BACKUP_ROOT.glob("*"))  # the backup is deleted after a full success


@pytest.mark.parametrize("how", ["exit", "raise"])
def test_a_failing_capture_parser_writes_nothing(processed, monkeypatch, how):
    bad = make_parser(
        processed, "b", **({"fail_on_call": 1} if how == "exit" else {"raise_on_call": 1})
    )
    good = make_parser(processed, "a")
    monkeypatch.setattr(ro, "PARSERS", [good, bad])
    before = contents(processed)
    assert ro.main([]) != 0
    assert contents(processed) == before
    assert good.calls == 1  # the real pass never started


@pytest.mark.parametrize("how", ["exit", "raise"])
def test_a_failing_real_pass_parser_leaves_every_output_unchanged(processed, monkeypatch, how):
    good = make_parser(processed, "a")
    bad = make_parser(
        processed, "b", **({"fail_on_call": 2} if how == "exit" else {"raise_on_call": 2})
    )
    monkeypatch.setattr(ro, "PARSERS", [good, bad])
    before = contents(processed)
    assert ro.main([]) != 0
    assert contents(processed) == before


def test_a_failing_join_restores_every_output(processed, monkeypatch):
    monkeypatch.setattr(ro, "PARSERS", [make_parser(processed, "a"), make_parser(processed, "b")])

    def join_fails():
        (processed / "enforcement-actions-all.csv").write_text("half written\n", encoding="utf-8")
        (processed / "new-file.csv").write_text("x\n", encoding="utf-8")
        raise SystemExit(2)

    monkeypatch.setattr(ro, "run_join", join_fails)
    before = contents(processed)
    assert ro.main([]) != 0
    assert contents(processed) == before


# --- Codex round 5, finding 1: atomic writes, persistent backup, interrupted-run marker ---------


def test_a_crash_mid_apply_leaves_the_marker_and_the_next_run_is_refused(
    processed, monkeypatch, capsys
):
    good = make_parser(processed, "a")
    bad = make_parser(processed, "b")

    def crash_on_apply(*args, **kwargs):
        raise RuntimeError("disk full")

    # Hold mode records the call; the crash happens when the held write is applied.
    monkeypatch.setattr(bad, "write_processed", staticmethod(crash_on_apply))
    monkeypatch.setattr(ro, "PARSERS", [good, bad])
    before = contents(processed)
    assert ro.main([]) != 0
    assert contents(processed) == before  # restored from the backup
    assert common.REPARSE_MARKER.exists()
    backups = list(ro.BACKUP_ROOT.iterdir())
    assert len(backups) == 1 and (backups[0] / "a.csv").read_text(encoding="utf-8") == "old a\n"
    capsys.readouterr()

    good_calls = good.calls
    assert ro.main([]) != 0  # refused
    assert good.calls == good_calls
    out = capsys.readouterr()
    text = out.out + out.err
    assert "git checkout -- data/processed" in text and str(backups[0]) in text


def test_a_parser_main_refuses_while_the_marker_is_set(tmp_path, monkeypatch, capsys):
    from scrapers import parse_tas_enforcement as tas

    marker = tmp_path / ".reparse-in-progress"
    marker.write_text("backup: somewhere\n", encoding="utf-8")
    monkeypatch.setattr(common, "REPARSE_MARKER", marker)
    monkeypatch.setattr(tas, "write_processed", lambda *a, **k: pytest.fail("wrote output"))
    assert tas.main(["--skip-fetch"]) != 0
    assert "git checkout -- data/processed" in capsys.readouterr().out


def test_a_failed_restore_keeps_the_backup_and_says_where(processed, monkeypatch, capsys):
    monkeypatch.setattr(ro, "PARSERS", [make_parser(processed, "a"), make_parser(processed, "b")])

    def join_fails():
        raise SystemExit(2)

    def restore_fails(*args, **kwargs):
        raise OSError("restore failed")

    monkeypatch.setattr(ro, "run_join", join_fails)
    monkeypatch.setattr(ro, "_restore", restore_fails)
    assert ro.main([]) != 0
    backups = list(ro.BACKUP_ROOT.iterdir())
    assert len(backups) == 1 and (backups[0] / "b.csv").read_text(encoding="utf-8") == "old b\n"
    assert common.REPARSE_MARKER.exists()
    out = capsys.readouterr()
    assert str(backups[0]) in out.out + out.err


def test_no_file_is_ever_half_written(tmp_path, monkeypatch):
    target = tmp_path / "out.csv"
    target.write_text("old\n", encoding="utf-8")

    def boom(src, dst):
        raise OSError("crash before replace")

    monkeypatch.setattr(common.os, "replace", boom)
    with pytest.raises(OSError):
        common.atomic_write_text(target, "new\n" * 1000)
    assert target.read_text(encoding="utf-8") == "old\n"
    assert [p.name for p in tmp_path.iterdir()] == ["out.csv"]  # no temp file left behind


def test_write_processed_is_atomic(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "PROCESSED_DIR", tmp_path)
    monkeypatch.setattr(common, "PROJECT_ROOT", tmp_path)
    common.write_processed("x", [{"a": "1"}], ["a"], raw_inputs=[])
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}

    def boom(src, dst):
        raise OSError("crash before replace")

    monkeypatch.setattr(common.os, "replace", boom)
    with pytest.raises(OSError):
        common.write_processed("x", [{"a": "2"}], ["a"], raw_inputs=[])
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before


# --- Codex round 6, finding 2: a verified backup before the marker; restore verifies first ------


def test_a_backup_copy_failing_part_way_leaves_no_marker_and_no_partial_backup(
    processed, monkeypatch
):
    monkeypatch.setattr(ro, "PARSERS", [make_parser(processed, "a"), make_parser(processed, "b")])
    real_copy = ro.shutil.copy2
    calls = {"n": 0}

    def copy_then_fail(src, dst, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("disk full")
        return real_copy(src, dst, *args, **kwargs)

    monkeypatch.setattr(ro.shutil, "copy2", copy_then_fail)
    before = contents(processed)
    assert ro.main([]) != 0
    assert contents(processed) == before
    assert not common.REPARSE_MARKER.exists()
    assert not ro.BACKUP_ROOT.exists() or not any(ro.BACKUP_ROOT.iterdir())


def test_a_backup_that_fails_verification_writes_no_marker(processed, monkeypatch):
    monkeypatch.setattr(ro, "PARSERS", [make_parser(processed, "a"), make_parser(processed, "b")])
    monkeypatch.setattr(common, "verify_backup", lambda d: ["a.csv: sha256 differs"])
    before = contents(processed)
    assert ro.main([]) != 0
    assert contents(processed) == before
    assert not common.REPARSE_MARKER.exists()
    assert not ro.BACKUP_ROOT.exists() or not any(ro.BACKUP_ROOT.iterdir())


def test_the_marker_names_a_verified_backup_and_its_manifest(processed, monkeypatch):
    seen = {}

    def join_reads_marker():
        seen["marker"] = common.REPARSE_MARKER.read_text(encoding="utf-8")
        raise SystemExit(2)

    monkeypatch.setattr(ro, "PARSERS", [make_parser(processed, "a"), make_parser(processed, "b")])
    monkeypatch.setattr(ro, "run_join", join_reads_marker)
    assert ro.main([]) != 0
    (backup,) = list(ro.BACKUP_ROOT.iterdir())
    assert f"backup: {backup}" in seen["marker"]
    assert f"manifest: {backup / common.BACKUP_MANIFEST}" in seen["marker"]
    assert common.verify_backup(backup) == []


def test_restore_refuses_a_truncated_backup_and_overwrites_nothing(processed):
    backup = ro._build_backup(processed)
    (backup / "a.csv").write_text("ol", encoding="utf-8")  # truncated
    (processed / "a.csv").write_text("partly applied\n", encoding="utf-8")
    after_crash = contents(processed)
    with pytest.raises(common.BackupInvalid):
        ro._restore(processed, backup)
    assert contents(processed) == after_crash


def test_restore_refuses_a_backup_with_a_missing_file_or_manifest(processed):
    backup = ro._build_backup(processed)
    (backup / "b.csv").unlink()
    with pytest.raises(common.BackupInvalid):
        ro._restore(processed, backup)
    (backup / common.BACKUP_MANIFEST).unlink()
    assert common.verify_backup(backup)
    with pytest.raises(common.BackupInvalid):
        ro._restore(processed, backup)


def test_a_crash_with_a_corrupted_backup_restores_nothing_and_says_use_git(
    processed, monkeypatch, capsys
):
    good = make_parser(processed, "a")
    bad = make_parser(processed, "b")

    def corrupt_then_crash(*args, **kwargs):
        (backup,) = list(ro.BACKUP_ROOT.iterdir())
        (backup / "b.csv").write_text("corrupt\n", encoding="utf-8")
        (processed / "b.csv").write_text("partly applied\n", encoding="utf-8")
        raise RuntimeError("disk full")

    monkeypatch.setattr(bad, "write_processed", staticmethod(corrupt_then_crash))
    monkeypatch.setattr(ro, "PARSERS", [good, bad])
    assert ro.main([]) != 0
    assert (processed / "b.csv").read_text(encoding="utf-8") == "partly applied\n"
    assert common.REPARSE_MARKER.exists()
    out = capsys.readouterr()
    text = out.out + out.err
    assert "git checkout -- data/processed" in text and "failed verification" in text
    message = common.reparse_recovery_message()
    assert "failed verification" in message and "git checkout -- data/processed" in message
    assert "copy the files back" not in message


def test_recovery_message_offers_the_backup_only_when_it_verifies(processed, monkeypatch):
    backup = ro._build_backup(processed)
    common.REPARSE_MARKER.write_text(
        f"backup: {backup}\nmanifest: {backup / common.BACKUP_MANIFEST}\n", encoding="utf-8"
    )
    message = common.reparse_recovery_message()
    assert "verified against its manifest" in message and str(backup) in message
    (backup / "a.csv").write_text("x", encoding="utf-8")
    message = common.reparse_recovery_message()
    assert "failed verification" in message and "git checkout -- data/processed" in message
