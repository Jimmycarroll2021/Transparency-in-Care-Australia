"""Re-parse every enforcement register offline, sharing one in-memory set of personal names.

Codex round 3, finding 3. The prose rule also nulls any prose field that contains the name of a
person this project withholds or classes as an individual anywhere in the run: in the ACECQA
register or in any enforcement register. The set is built in two passes in one process:

1. Each parser runs on its newest local snapshots with its writers replaced by a capture, so
   nothing is written. The raw subject of every withheld row and any person-level field a
   parser drops are noted in memory (common.note_withheld_subject) and go into the set.
2. The set is handed to scrapers.common and every parser runs again for real.

All or nothing (Codex round 4, finding 2). A parser that exits non-zero or raises in the capture
pass stops the run before anything is written. In the real pass every parser's writes are held
back in memory until all parsers have succeeded. Then the current processed outputs are copied to
a persistent backup (data/.reparse-backup/<timestamp>) with a manifest of sizes and sha256, which is
verified before the marker (data/.reparse-in-progress) is set; the held writes are then made
atomically and the join runs. If anything fails, data/processed is restored from the backup once
it verifies against its manifest (files the run created are removed; a backup that fails
verification restores nothing), the exit code is non-zero, and the
backup and the marker are kept: until the marker is removed every later run refuses to start and
prints recovery instructions. Only a fully successful run removes the marker and the backup.

The set exists only in memory. It is never written, logged or printed; only counts are logged.

Usage: python scrapers/reparse_offline.py [--allow-unrestored]   (no network; the same as each
parser's --skip-fetch)
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import sys
import tempfile
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scrapers import (
    abn_lookup,  # noqa: E402
    common,  # noqa: E402
    join_enforcement,  # noqa: E402
)
from scrapers import build_provider_groups as groups  # noqa: E402
from scrapers import parse_cth_ccs_enforcement as cth  # noqa: E402
from scrapers import parse_nsw_enforcement as nsw  # noqa: E402
from scrapers import parse_qld_enforcement as qld  # noqa: E402
from scrapers import parse_sa_enforcement as sa  # noqa: E402
from scrapers import parse_tas_enforcement as tas  # noqa: E402
from scrapers import parse_vecra_enforcement as vecra  # noqa: E402
from scrapers import parse_wa_enforcement as wa  # noqa: E402
from scrapers import profile_providers as profile  # noqa: E402
from scrapers.common import PROCESSED_DIR, PROJECT_ROOT, log  # noqa: E402
from scrapers.profile_providers import PersonNames, acecqa_person_names  # noqa: E402

PARSERS = [qld, vecra, sa, tas, cth, wa, nsw]
# PR #12: builders run last, after the join and inside the same backup and marker, so that the
# name rule on provider-profile.csv trading names uses the run-wide names and every name withheld
# by an earlier output in this run (a name withheld once is withheld everywhere).
# Round 2: the ABR tables (business names) and the provider groups are rebuilt too, offline: the
# re-filter of abn-details.csv and stage C of the groups from provider-abn.csv (no ABN Lookup call).
BUILDERS = [(profile, []), (abn_lookup, ["refilter"]), (groups, ["--skip-lookup"])]
# Round 3: the ABR re-filter also runs before the join, so that the join reads the same
# abn-details.csv as the end of the run; the join is repeated until its inputs no longer change,
# so that a second run uses the same candidate set and writes the same outputs.
# Round 4: the provider profile is rebuilt before the first join too (the join reads it), and
# the loop runs until every join input the builders write is stable.
PRE_JOIN_BUILDERS = [(profile, []), (abn_lookup, ["refilter"]), (groups, ["--skip-lookup"])]
# Round 5: provider-abn.csv is no longer read by the join (it feeds the profile, which is here).
JOIN_INPUTS = [
    PROCESSED_DIR / "abn-details.csv",
    PROCESSED_DIR / "provider-profile.csv",
]
# Round 5: the join, the passes and the builders are repeated at most this many times; a run
# that has not converged by then fails closed (data/processed restored from the backup).
MAX_JOIN_ITERATIONS = 10


class NotConverged(RuntimeError):
    pass


# Persistent backups of data/processed, one directory per run (gitignored).
BACKUP_ROOT = PROJECT_ROOT / "data" / ".reparse-backup"
# Single-writer lock (Codex round 7, gitignored). Taken with an exclusive create.
LOCK_PATH = PROJECT_ROOT / "data" / ".reparse.lock"
_WRITERS = ("write_processed", "write_counts")
ARGV = ["--skip-fetch"]


class ParserFailed(RuntimeError):
    pass


def _run_parser(module, argv: list[str] | None = None) -> None:
    name = module.__name__.rsplit(".", 1)[-1]
    try:
        code = module.main(list(ARGV) if argv is None else list(argv))
    except SystemExit as exc:  # argparse or an explicit exit
        code = exc.code
    except Exception as exc:
        raise ParserFailed(f"{name} raised {type(exc).__name__}") from exc
    if code:
        raise ParserFailed(f"{name} exited {code}")


def _capture(module) -> list[dict]:
    """Run one parser with its writers replaced by a capture. Nothing is written."""
    captured: list[dict] = []

    def capture_processed(name, rows, *args, **kwargs):
        captured.extend(rows)

    def ignore(*args, **kwargs):
        return None

    saved = {}
    for attr in _WRITERS:
        if hasattr(module, attr):
            saved[attr] = getattr(module, attr)
            setattr(module, attr, capture_processed if attr == "write_processed" else ignore)
    try:
        _run_parser(module)
    finally:
        for attr, fn in saved.items():
            setattr(module, attr, fn)
    return captured


def _held_writes(module) -> list:
    """Run one parser with its writes held back in memory. Returns the held calls."""
    held: list = []
    saved = {}
    for attr in _WRITERS:
        if hasattr(module, attr):
            original = getattr(module, attr)
            saved[attr] = original

            def hold(*args, _fn=original, **kwargs):
                held.append((_fn, args, kwargs))

            setattr(module, attr, hold)
    try:
        _run_parser(module)
    finally:
        for attr, fn in saved.items():
            setattr(module, attr, fn)
    return held


# PR #12 round 3: passed to the join by --allow-unrestored (fewer joins, recorded in the report).
ALLOW_UNRESTORED = False


def run_join() -> None:
    join_enforcement.main(["--allow-unrestored"] if ALLOW_UNRESTORED else [])


def _sha_or_none(path: Path) -> str | None:
    return common.file_sha256(path) if path.exists() else None


def _fsync_file(path: Path) -> None:
    with path.open("rb+") as fh:
        os.fsync(fh.fileno())


def _build_backup(directory: Path) -> Path:
    """Copy every file in `directory` into a temporary directory under BACKUP_ROOT, fsync each,
    write and fsync a manifest (relative path, size, sha256), verify every file against it, and
    only then rename the directory to BACKUP_ROOT/<timestamp>. On any failure the temporary
    directory is removed and the error is raised (Codex round 6)."""
    BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
    building = Path(tempfile.mkdtemp(prefix=".building-", dir=BACKUP_ROOT))
    try:
        entries = []
        for path in sorted(p for p in directory.iterdir() if p.is_file()):
            sha256 = common.file_sha256(path)
            size = path.stat().st_size
            shutil.copy2(path, building / path.name)
            _fsync_file(building / path.name)
            entries.append({"path": path.name, "size": size, "sha256": sha256})
        common.atomic_write_text(
            building / common.BACKUP_MANIFEST, json.dumps({"files": entries}, indent=2) + "\n"
        )
        problems = common.verify_backup(building)
        if problems:
            raise common.BackupInvalid("; ".join(problems))
        final = BACKUP_ROOT / common.utc_now().strftime("%Y-%m-%dT%H%M%S%fZ")
        os.replace(building, final)
        return final
    except BaseException:
        shutil.rmtree(building, ignore_errors=True)
        raise


def _restore(directory: Path, backup: Path) -> None:
    """Restore `directory` from a backup, but only after the backup verifies against its
    manifest; otherwise raise BackupInvalid and touch nothing."""
    problems = common.verify_backup(backup)
    if problems:
        raise common.BackupInvalid("; ".join(problems))
    manifest = json.loads((backup / common.BACKUP_MANIFEST).read_text(encoding="utf-8"))
    names = {entry["path"] for entry in manifest["files"]}
    for path in directory.iterdir():
        if path.is_file() and path.name not in names:
            path.unlink()
    for name in sorted(names):
        common.atomic_write_bytes(directory / name, (backup / name).read_bytes())


def collect_person_names() -> PersonNames:
    common.reset_run_names()
    names = PersonNames()
    names.update(acecqa_person_names())
    log.info("person names from the ACECQA register: %d entries (in memory)", len(names))
    for module in PARSERS:
        before = len(names)
        for row in _capture(module):
            names.add_subject(row.get("_subject_raw"))
        run = common.run_person_names()  # subjects the parser withheld, noted in memory
        if run is not None:
            names.update(run)
        log.info(
            "person names from %s: %d entries added (in memory)",
            module.__name__.rsplit(".", 1)[-1],
            len(names) - before,
        )
    return names


class LockHeld(RuntimeError):
    pass


# PR #7 round 1: the body this run wrote into the lock (pid and a random nonce). The lock is
# removed only while it still holds this token, never by path alone.
_LOCK_TOKEN: str | None = None


def _read_lock_text() -> str | None:
    """The lock file's text, stripped, or None when it cannot be read."""
    try:
        return LOCK_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def _remove_own_lock() -> None:
    """Unlink the lock only when it still holds this run's token; otherwise leave it and log."""
    global _LOCK_TOKEN
    token, _LOCK_TOKEN = _LOCK_TOKEN, None
    if token is None:
        return
    if _read_lock_text() == token.strip():
        LOCK_PATH.unlink(missing_ok=True)
        return
    log.warning("lock %s not removed: it does not hold this run's token", LOCK_PATH)


def _acquire_lock() -> None:
    """Take the single-writer lock with an exclusive create; raise LockHeld if it exists."""
    global _LOCK_TOKEN
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise LockHeld(str(LOCK_PATH)) from exc
    # Follow-up to PR #6: this process created the lock, so if its body cannot be written the
    # lock is removed here, but only while it still holds this run's token (PR #7 round 1).
    # A lock that already existed never reaches this point.
    _LOCK_TOKEN = (
        f"pid {os.getpid()} nonce {secrets.token_hex(8)} at {common.utc_now().isoformat()}\n"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(_LOCK_TOKEN)
            fh.flush()
            os.fsync(fh.fileno())
    except BaseException:
        _remove_own_lock()
        raise


def _release_lock() -> None:
    _remove_own_lock()


def main(argv: list[str] | None = None) -> int:
    """Single writer (Codex round 7): the lock is taken before anything is read or written and
    released on every exit path. A held or stale lock is reported, never removed."""
    global ALLOW_UNRESTORED
    ap = argparse.ArgumentParser(description=__doc__.split(chr(10) * 2)[0])
    ap.add_argument(
        "--allow-unrestored",
        action="store_true",
        help="let the join write even when withheld names cannot be restored in memory (fewer "
        "joins; the counts are recorded in the join report)",
    )
    ALLOW_UNRESTORED = ap.parse_args(argv).allow_unrestored
    try:
        _acquire_lock()
    except LockHeld:
        try:
            holder = LOCK_PATH.read_text(encoding="utf-8").strip()
        except OSError:
            holder = "(unreadable)"
        message = (
            f"Refusing to run: another reparse holds the lock {LOCK_PATH} ({holder}). Nothing "
            "was read or changed. Delete the lock file by hand only if no reparse is running."
        )
        log.error(message)
        print(message)
        return 4
    try:
        return _run()
    finally:
        _release_lock()


def _run() -> int:
    if common.refuse_if_reparse_incomplete():
        return 3
    try:
        names = collect_person_names()
    except ParserFailed as exc:
        log.error("capture pass failed (%s); nothing written", exc)
        return 2
    common.set_person_names(names)
    held: list = []
    try:
        for module in PARSERS:
            held.extend(_held_writes(module))
    except ParserFailed as exc:
        log.error("real pass failed (%s); nothing written", exc)
        return 1
    # Codex rounds 5 and 6: a verified, persistent backup first; only then the marker. The marker
    # is removed and the backup deleted only after a fully successful run.
    try:
        backup = _build_backup(PROCESSED_DIR)
    except BaseException as exc:
        log.error("backup failed (%r); no marker written, data/processed untouched", exc)
        return 1
    common.atomic_write_text(
        common.REPARSE_MARKER,
        f"backup: {backup}\nmanifest: {backup / common.BACKUP_MANIFEST}\n",
    )
    try:
        for fn, args, kwargs in held:
            fn(*args, **kwargs)
        for module, argv in PRE_JOIN_BUILDERS:
            _run_parser(module, argv)
        for iteration in range(1, MAX_JOIN_ITERATIONS + 1):
            inputs_before = [_sha_or_none(path) for path in JOIN_INPUTS]
            run_join()
            # PR #12 round 1: the cross-output pass, then the builders (which see every withheld
            # name), then the pass again, so that every output agrees whatever the write order.
            common.refilter_processed_names()
            # Round 2: builders, then the cross-output pass, until the pass changes nothing (the
            # set of withheld names only grows, so this ends).
            for _ in range(MAX_JOIN_ITERATIONS):
                for module, argv in BUILDERS:
                    _run_parser(module, argv)
                if not common.refilter_processed_names():
                    break
            else:
                raise NotConverged(
                    f"the builders and the cross-output pass did not converge after "
                    f"{MAX_JOIN_ITERATIONS} passes; nothing kept"
                )
            # Rounds 3 and 4: if the passes changed a join input, join again.
            if [_sha_or_none(path) for path in JOIN_INPUTS] == inputs_before:
                log.info("join inputs stable after %d join(s)", iteration)
                break
        else:
            raise NotConverged(
                f"the join inputs did not converge after {MAX_JOIN_ITERATIONS} joins; nothing kept"
            )
    except BaseException as exc:  # includes SystemExit from the join
        log.error("writing or join failed (%r)", exc)
        try:
            _restore(PROCESSED_DIR, backup)
        except common.BackupInvalid as invalid:
            message = (
                f"Nothing was restored: the backup {backup} failed verification against its "
                f"manifest ({invalid}). Do not copy anything from it. Run "
                "`git checkout -- data/processed`, then remove any untracked files under "
                f"data/processed (git status shows them) and delete {common.REPARSE_MARKER}."
            )
            log.error(message)
            print(message)
            return 1
        except BaseException as restore_exc:
            message = (
                f"Restore FAILED ({restore_exc!r}). The backup is kept at {backup}. Copy its files "
                "back into data/processed, or run `git checkout -- data/processed`, then remove "
                "any untracked files under data/processed (git status shows them) and delete "
                f"{common.REPARSE_MARKER}."
            )
            log.error(message)
            print(message)
            return 1
        message = (
            f"data/processed was restored from the backup at {backup}. The backup and the marker "
            f"{common.REPARSE_MARKER} are kept: check `git status`, then delete both (or run "
            "`git checkout -- data/processed`) before running again."
        )
        log.error(message)
        print(message)
        return 1
    common.REPARSE_MARKER.unlink()
    shutil.rmtree(backup)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
