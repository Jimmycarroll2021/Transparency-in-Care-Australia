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

The join needs TICA_JOIN_KEY (environment or .env) for its keyed-name stage (PR #11): the run
refuses to start without it unless --no-keyed-join is passed. The private name-key sidecars
(data/private/name-keys, gitignored) are backed up and restored with data/processed.

Usage: python scrapers/reparse_offline.py [--no-keyed-join]
       (no network; the same as each parser's --skip-fetch)
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
    common,  # noqa: E402
    join_enforcement,  # noqa: E402
)
from scrapers import parse_cth_ccs_enforcement as cth  # noqa: E402
from scrapers import parse_nsw_enforcement as nsw  # noqa: E402
from scrapers import parse_qld_enforcement as qld  # noqa: E402
from scrapers import parse_sa_enforcement as sa  # noqa: E402
from scrapers import parse_tas_enforcement as tas  # noqa: E402
from scrapers import parse_vecra_enforcement as vecra  # noqa: E402
from scrapers import parse_wa_enforcement as wa  # noqa: E402
from scrapers.common import PROCESSED_DIR, PROJECT_ROOT, log  # noqa: E402
from scrapers.profile_providers import PersonNames, acecqa_person_names  # noqa: E402

PARSERS = [qld, vecra, sa, tas, cth, wa, nsw]
# Persistent backups of data/processed, one directory per run (gitignored).
BACKUP_ROOT = PROJECT_ROOT / "data" / ".reparse-backup"
# Single-writer lock (Codex round 7, gitignored). Taken with an exclusive create.
LOCK_PATH = PROJECT_ROOT / "data" / ".reparse.lock"
_WRITERS = ("write_processed", "write_counts")
ARGV = ["--skip-fetch"]


class ParserFailed(RuntimeError):
    pass


def _run_parser(module) -> None:
    name = module.__name__.rsplit(".", 1)[-1]
    try:
        code = module.main(list(ARGV))
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


# PR #11: the join's keyed-name stage. Set from --no-keyed-join in main().
KEYED_JOIN = True


def run_join() -> None:
    join_enforcement.main([] if KEYED_JOIN else ["--no-keyed-join"])


def _name_keys_dir() -> Path:
    """The private name-key sidecars beside data/processed (gitignored, PR #11)."""
    return PROCESSED_DIR.parent / "private" / "name-keys"


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
    global KEYED_JOIN
    ap = argparse.ArgumentParser(description="Re-parse every enforcement register offline.")
    ap.add_argument(
        "--no-keyed-join",
        action="store_true",
        help="run the join without the keyed-name stage (no TICA_JOIN_KEY needed; fewer joins)",
    )
    KEYED_JOIN = not ap.parse_args(argv).no_keyed_join
    common.skip_name_keys(not KEYED_JOIN)  # parsers write, or delete, their sidecars to match
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
    if KEYED_JOIN:
        # PR #11: without the key the join would lose the keyed joins; stop before any work.
        try:
            key = common.load_join_key()
        except common.JoinKeyMissing as exc:
            key, problem = None, str(exc)
        else:
            problem = f"{common.JOIN_KEY_VAR} is not set (environment or .env)"
        if key is None:
            message = (
                f"Refusing to run: {problem}. Nothing was read or changed. Set it, or pass "
                "--no-keyed-join to run with fewer joins."
            )
            log.error(message)
            print(message)
            return 5
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
    # PR #11: the private name-key sidecars are written with the outputs, so they are backed up
    # and restored with them.
    keys_dir = _name_keys_dir()
    keys_backup = None
    keys_dir_existed = keys_dir.is_dir()
    if keys_dir_existed:
        try:
            keys_backup = _build_backup(keys_dir)
        except BaseException as exc:
            shutil.rmtree(backup)
            log.error("name-key backup failed (%r); no marker written, nothing changed", exc)
            return 1
    common.atomic_write_text(
        common.REPARSE_MARKER,
        f"backup: {backup}\nmanifest: {backup / common.BACKUP_MANIFEST}\n"
        + (f"name keys backup: {keys_backup}\n" if keys_backup is not None else ""),
    )
    try:
        for fn, args, kwargs in held:
            fn(*args, **kwargs)
        run_join()
    except BaseException as exc:  # includes SystemExit from the join
        log.error("writing or join failed (%r)", exc)
        if keys_backup is not None:
            try:
                _restore(keys_dir, keys_backup)
                shutil.rmtree(keys_backup)
            except BaseException as keys_exc:
                log.error("name keys not restored (%r); backup kept at %s", keys_exc, keys_backup)
        elif not keys_dir_existed and keys_dir.is_dir():
            shutil.rmtree(keys_dir)  # created by this failed run
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
    if keys_backup is not None:
        shutil.rmtree(keys_backup)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
