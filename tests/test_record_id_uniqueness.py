"""Codex round 1, finding 3: no record_id repeats in any committed enforcement output."""

import csv
from pathlib import Path

PROCESSED = Path(__file__).resolve().parent.parent / "data" / "processed"


def test_no_duplicate_record_id_in_any_committed_output():
    files = sorted(PROCESSED.glob("*-enforcement-actions.csv")) + [
        PROCESSED / "enforcement-actions-all.csv"
    ]
    for path in files:
        if not path.exists():
            continue
        with path.open(newline="", encoding="utf-8") as fh:
            ids = [r["record_id"] for r in csv.DictReader(fh)]
        assert len(ids) == len(set(ids)), f"{path.name}: {len(ids) - len(set(ids))} duplicates"
