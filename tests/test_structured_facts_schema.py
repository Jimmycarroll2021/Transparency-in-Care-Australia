"""Codex round 2, finding 4: structured facts kept apart from prose are declared columns."""

import json
from pathlib import Path

from scrapers import parse_nsw_enforcement as nsw
from scrapers import parse_qld_enforcement as qld
from scrapers import parse_sa_enforcement as sa

SCHEMA = json.loads(
    (
        Path(__file__).resolve().parent.parent / "data/schemas/enforcement-action.schema.json"
    ).read_text()
)


def test_structured_fact_columns_are_written_and_declared():
    props = SCHEMA["properties"]
    expected = {
        qld: ("penalty_amount_aud",),
        nsw: ("start_date", "end_date"),
        sa: ("end_date",),
    }
    for module, columns in expected.items():
        for column in columns:
            assert column in module.FIELDNAMES, (module.__name__, column)
            assert column in props, column
    for column in ("start_date", "end_date"):
        assert props[column]["pattern"] == props["date_issued"]["pattern"]
