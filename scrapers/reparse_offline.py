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
a persistent backup (data/.reparse-backup/<timestamp>), a marker (data/.reparse-in-progress) is
set, the held writes are made atomically and the join runs. If anything fails, data/processed is
restored from the backup (files the run created are removed), the exit code is non-zero, and the
backup and the marker are kept: until the marker is removed every later run refuses to start and
prints recovery instructions. Only a fully successful run removes the marker and the backup.

The set exists only in memory. It is never written, logged or printed; only counts are logged.

Usage: python scrapers/reparse_offline.py   (no network; the same as each parser's --skip-fetch)
"""

from __future__ import annotations

import shutil
import sys
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


def run_join() -> None:
    join_enforcement.main()


def _backup(directory: Path, to: Path) -> list[str]:
    names = []
    for path in directory.iterdir():
        if path.is_file():
            shutil.copy2(path, to / path.name)
            names.append(path.name)
    return names


def _restore(directory: Path, backup: Path, names: list[str]) -> None:
    for path in directory.iterdir():
        if path.is_file() and path.name not in names:
            path.unlink()
    for name in names:
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


def main(argv: list[str] | None = None) -> int:
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
    # Codex round 5: a persistent backup and a marker. The marker is removed and the backup
    # deleted only after a fully successful run; otherwise both stay for recovery.
    backup = BACKUP_ROOT / common.utc_now().strftime("%Y-%m-%dT%H%M%S%fZ")
    backup.mkdir(parents=True)
    common.atomic_write_text(common.REPARSE_MARKER, f"backup: {backup}\n")
    names_before = _backup(PROCESSED_DIR, backup)
    try:
        for fn, args, kwargs in held:
            fn(*args, **kwargs)
        run_join()
    except BaseException as exc:  # includes SystemExit from the join
        log.error("writing or join failed (%r)", exc)
        try:
            _restore(PROCESSED_DIR, backup, names_before)
        except BaseException as restore_exc:
            message = (
                f"Restore FAILED ({restore_exc!r}). The backup is kept at {backup}. Copy its files "
                "back into data/processed, or run `git checkout -- data/processed`, then delete "
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
