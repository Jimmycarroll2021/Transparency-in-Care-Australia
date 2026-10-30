"""Re-parse every enforcement register offline, sharing one in-memory set of personal names.

Codex round 3, finding 3. The prose rule also nulls any prose field that contains the name of a
person this project withholds or classes as an individual anywhere in the run: in the ACECQA
register or in any enforcement register. The set is built in two passes in one process:

1. Each parser runs on its newest local snapshots with its writers replaced by a capture, so
   nothing is written. The raw subject of every withheld row and any person-level field a
   parser drops are noted in memory (common.note_withheld_subject) and go into the set.
2. The set is handed to scrapers.common and every parser runs again for real.

The set exists only in memory. It is never written, logged or printed; only counts are logged.

Usage: python scrapers/reparse_offline.py   (no network; the same as each parser's --skip-fetch)
"""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scrapers import common  # noqa: E402
from scrapers import parse_cth_ccs_enforcement as cth  # noqa: E402
from scrapers import parse_nsw_enforcement as nsw  # noqa: E402
from scrapers import parse_qld_enforcement as qld  # noqa: E402
from scrapers import parse_sa_enforcement as sa  # noqa: E402
from scrapers import parse_tas_enforcement as tas  # noqa: E402
from scrapers import parse_vecra_enforcement as vecra  # noqa: E402
from scrapers import parse_wa_enforcement as wa  # noqa: E402
from scrapers.common import log  # noqa: E402
from scrapers.profile_providers import PersonNames, acecqa_person_names  # noqa: E402

PARSERS = [qld, vecra, sa, tas, cth, wa, nsw]
_WRITERS = ("write_processed", "write_counts")
ARGV = ["--skip-fetch"]


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
        module.main(list(ARGV))
    finally:
        for attr, fn in saved.items():
            setattr(module, attr, fn)
    return captured


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
    common.set_person_names(collect_person_names())
    failed = []
    for module in PARSERS:
        code = module.main(list(ARGV))
        if code:
            failed.append(module.__name__)
    if failed:
        log.error("parsers failed: %s", ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
