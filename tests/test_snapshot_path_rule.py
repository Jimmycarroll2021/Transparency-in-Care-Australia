"""Codex round 6, finding 1: a snapshot or raw path that may name an individual is withheld whole.

Snapshot file names are slugs of the document URL, so a name withheld from source_document must
not survive in source_snapshot, provenance raw_inputs, summaries or logs. All names are synthetic.
"""

import copy
import json
import logging

from scrapers import common
from scrapers import join_enforcement as je
from scrapers import profile_providers as pp

SNAPSHOT_NOTE = "source snapshot path withheld: may name an individual"


def _names(*subjects):
    names = pp.PersonNames()
    for s in subjects:
        names.add_subject(s)
    return names


def test_a_named_source_snapshot_is_nulled_whole_with_the_fixed_note():
    row = {
        "source_document": "https://example.gov.au/register",
        "source_snapshot": "data/raw/x/2026-10-29T0718Z-Notice-to-Jane-Example.pdf",
        "action_type_raw": "Compliance notice",
        "notes": None,
    }
    counts = common.withhold_prose_naming_people([row])
    assert counts == {"source_snapshot": 1}
    assert row["source_snapshot"] is None
    assert row["notes"] == SNAPSHOT_NOTE
    assert row["source_document"] == "https://example.gov.au/register"


def test_a_lowercase_slug_of_a_known_name_is_withheld():
    row = {"source_snapshot": "data/raw/nsw/2026-10-29T0718Z-notice-to-jane-example.pdf"}
    common.withhold_prose_naming_people([row], person_names=_names("Jane Example"))
    assert row["source_snapshot"] is None


def test_a_clean_snapshot_path_is_kept_whole():
    path = "data/raw/nsw-enforcement/2026-10-29T0718Z-q1-cancellations-providers-2025-2026.pdf"
    row = {"source_snapshot": path}
    assert common.withhold_prose_naming_people([row]) == {}
    assert row["source_snapshot"] == path


def test_paths_and_urls_with_spaces_are_checked_whole():
    for value in (
        "data/raw/x/Notice to Jane Example.pdf",
        "https://example.gov.au/docs/Notice to Jane Example.pdf",
    ):
        text = f"parsed from {value} today"
        redacted = common.redact_urls(text)
        assert "Jane" not in redacted and "Example" not in redacted, redacted
        assert redacted.startswith("parsed from ") and redacted.endswith(" today")
    row = {"source_snapshot": "data/raw/x/Notice to Jane Example.pdf"}
    common.withhold_prose_naming_people([row])
    assert row["source_snapshot"] is None


def test_windows_style_paths_are_split_on_backslashes():
    row = {"source_snapshot": "data\\raw\\tas\\2026-10-29T0718Z-Jane-Example.html"}
    common.withhold_prose_naming_people([row])
    assert row["source_snapshot"] is None


def test_provenance_raw_inputs_withhold_a_named_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "PROCESSED_DIR", tmp_path)
    monkeypatch.setattr(common, "PROJECT_ROOT", tmp_path)
    common.write_processed(
        "x",
        [{"a": "1"}],
        ["a"],
        raw_inputs=[
            tmp_path / "data" / "raw" / "2026-10-29T0718Z-notice to Jane Example.pdf",
            tmp_path / "data" / "raw" / "register.html",
        ],
    )
    prov = json.loads((tmp_path / "x.provenance.json").read_text(encoding="utf-8"))
    assert prov["raw_inputs"][0] == common.SNAPSHOT_TEXT_WITHHELD
    assert prov["raw_inputs"][1] == "data/raw/register.html"
    assert "jane" not in json.dumps(prov).lower()


def test_snapshot_note_does_not_mark_the_provider_name_as_withheld():
    assert je.SNAPSHOT_WITHHELD_NOTE == common.SNAPSHOT_WITHHELD_NOTE == SNAPSHOT_NOTE
    assert not je.name_withheld_row({"notes": SNAPSHOT_NOTE})


def test_nsw_named_snapshot_is_withheld_and_the_record_id_is_unchanged(
    tmp_path, monkeypatch, caplog
):
    from scrapers import parse_nsw_enforcement as nsw

    from tests.test_nsw_enforcement import SOURCE, _fake_reader, _write_pdf_snapshot

    monkeypatch.setattr(common, "_PERSON_NAMES", _names("Jane Example"))
    src = tmp_path / SOURCE
    src.mkdir()
    url = "https://education.nsw.gov.au/x/Q1_Cancellations_Services_2025_2026.pdf"
    name = "2026-10-29T0718Z-q1-cancellations-services-jane-example.pdf"
    _write_pdf_snapshot(src, name, url)
    monkeypatch.setattr(nsw, "read_pdf_records", _fake_reader(set()))
    with caplog.at_level(logging.INFO, logger="scrapers"):
        rows, parsed, summary = nsw.parse_all(base_dir=tmp_path, root=tmp_path)
    assert len(rows) == 1
    row = rows[0]
    assert row["source_snapshot"] is None and SNAPSHOT_NOTE in row["notes"]
    expected = copy.deepcopy(rows)
    expected[0]["source_snapshot"] = f"{SOURCE}/{name}"
    common.assign_record_ids(expected)
    assert row["record_id"] == expected[0]["record_id"]
    assert "jane" not in (json.dumps(summary) + nsw.provenance_notes(summary)).lower()
    assert "jane" not in caplog.text.lower()


def test_cth_named_snapshot_is_withheld_and_the_record_id_is_unchanged():
    from scrapers.parse_cth_ccs_enforcement import CURRENT_URL, parse_page

    from tests.test_cth_ccs_enforcement import COMPANY, page

    def parse(snapshot):
        return parse_page(
            page(COMPANY),
            role="current",
            page_url=CURRENT_URL,
            captured_at="2026-10-29T07:00:00+00:00",
            source_snapshot=snapshot,
        )

    named = parse("data/raw/cth-ccs-enforcement/2026-10-29T0718Z-Jane-Example-current.html")[0]
    clean = parse("data/raw/cth-ccs-enforcement/2026-10-29T0718Z-current.html")[0]
    assert named["source_snapshot"] is None and SNAPSHOT_NOTE in named["notes"]
    assert clean["source_snapshot"].endswith("2026-10-29T0718Z-current.html")
    assert named["record_id"] == clean["record_id"]


def test_count_rows_apply_the_url_and_snapshot_rule():
    rows = [
        {
            "source_document": "https://example.gov.au/Jane-Example-counts",
            "source_snapshot": "data/raw/sa/2026-10-29T0718Z-Jane-Example.html",
            "count": "3",
        }
    ]
    common.withhold_source_locations(rows)
    assert rows[0]["source_document"] is None and rows[0]["source_snapshot"] is None
    assert rows[0]["count"] == "3"
