"""Codex round 3, finding 1: the consolidated output keeps every structured parser column."""

import csv
from pathlib import Path

from scrapers import join_enforcement as je
from scrapers import parse_cth_ccs_enforcement as cth
from scrapers import parse_nsw_enforcement as nsw
from scrapers import parse_qld_enforcement as qld
from scrapers import parse_sa_enforcement as sa
from scrapers import parse_tas_enforcement as tas
from scrapers import parse_vecra_enforcement as vecra
from scrapers import parse_wa_enforcement as wa

PROCESSED = Path(__file__).resolve().parent.parent / "data" / "processed"
# Prose or link columns: not structured facts.
PROSE = {"action_type_raw", "reason", "address", "notes", "linked_documents", "details"}
# Name columns the join may null on its own (a person paired with a role); compared separately.
JOIN_MAY_NULL = {"provider_name", "service_name"}
PARSERS = {
    "cth-ccs": cth.FIELDNAMES,
    "nsw": nsw.FIELDNAMES,
    "qld": qld.FIELDNAMES,
    "sa": sa.FIELDNAMES,
    "tas": getattr(tas, "FIELDNAMES", None) or tas.COLUMNS,
    "vecra": vecra.FIELDNAMES,
    "wa": getattr(wa, "FIELDNAMES", None) or wa.COLUMNS,
}


def structured(columns):
    return [c for c in columns if c not in PROSE]


def test_action_columns_carry_every_structured_parser_column():
    for name, columns in PARSERS.items():
        missing = [c for c in structured(columns) if c not in je.ACTION_COLUMNS]
        assert not missing, (name, missing)
        assert all(c in je.ALL_COLUMNS for c in structured(columns))


def _read(path):
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def test_consolidated_output_keeps_every_structured_value():
    all_path = PROCESSED / "enforcement-actions-all.csv"
    if not all_path.exists():
        return
    joined = {r["record_id"]: r for r in _read(all_path)}
    for name, columns in PARSERS.items():
        path = PROCESSED / f"{name}-enforcement-actions.csv"
        if not path.exists():
            continue
        for row in _read(path):
            out = joined[row["record_id"]]
            for col in structured(columns):
                if col in JOIN_MAY_NULL and not out[col]:
                    continue
                assert out.get(col) == row[col], (name, row["record_id"], col)


def test_example_cth_conviction_keeps_its_dates_and_plea():
    all_path = PROCESSED / "enforcement-actions-all.csv"
    if not all_path.exists():
        return
    row = next(r for r in _read(all_path) if r["record_id"] == "d0694e7da63916d2")
    assert row["date_charged"] == "2025-09-24"
    assert row["date_of_sentence"] == "2026-03-24"
    assert row["plea"] == "Guilty"
    assert row["service_type"] == "Family Day Care"
