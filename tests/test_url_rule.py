"""Codex round 4, finding 1: URLs whose path or file name may name a person are withheld whole.

A URL is never altered: it is kept whole or nulled. Traceability stays through record_id and the
committed raw snapshot path. All names are synthetic.
"""

import json
from pathlib import Path

from scrapers import common
from scrapers import join_enforcement as je
from scrapers import profile_providers as pp
from scrapers.parse_qld_enforcement import INDEX_URL, parse_register

URL_NOTE = "source URL withheld: may name an individual"
SCHEMA = json.loads(
    (
        Path(__file__).resolve().parent.parent / "data/schemas/enforcement-action.schema.json"
    ).read_text()
)
HEADER = (
    "<tr><th><p>Provider or individual name</p><p>Service name</p></th>"
    "<th>Date of action</th><th>Details</th><th>Breaches (if applicable)</th></tr>"
)


def _row(**over):
    row = {
        "service_name": "Sunny Meadow Early Learning",
        "provider_name": "Example Kids Pty Ltd",
        "source_document": "https://example.gov.au/docs/cancellation-sunny-meadow.pdf",
        "linked_documents": "https://example.gov.au/news/sunny-meadow-fined",
        "action_type_raw": "Cancellation of provider approval",
        "reason": None,
        "notes": None,
    }
    row.update(over)
    return row


def test_clean_urls_are_kept_whole():
    row = _row()
    before = dict(row)
    assert common.withhold_prose_naming_people([row]) == {}
    assert row == before


def test_a_capitalised_name_in_a_pdf_file_name_withholds_that_url_only():
    row = _row(
        source_document="https://example.gov.au/docs/Prosecution-Jane-Example.pdf",
        linked_documents=(
            "https://example.gov.au/news/sunny-meadow-fined "
            "https://example.gov.au/docs/Notice_to_Jane%20Example.docx"
        ),
    )
    counts = common.withhold_prose_naming_people([row])
    assert counts == {"source_document": 1, "linked_documents": 1}
    assert row["source_document"] is None
    assert row["linked_documents"] == "https://example.gov.au/news/sunny-meadow-fined"
    assert row["notes"] == URL_NOTE
    assert "jane" not in json.dumps(row).lower()


def test_a_lowercase_known_name_in_a_url_is_withheld():
    names = pp.PersonNames()
    names.add_subject("Jane Example")
    row = _row(linked_documents="https://example.gov.au/docs/prosecution-jane-example.pdf")
    common.withhold_prose_naming_people([row], person_names=names)
    assert row["linked_documents"] is None
    assert URL_NOTE in row["notes"]


def test_urls_on_rows_already_withheld_whole_are_checked_too():
    row = _row(
        source_document="https://example.gov.au/docs/Jane-Example-cancellation.pdf",
        action_type_raw="(withheld)",
        notes=common.FREE_TEXT_WITHHELD_NOTE,
    )
    common.withhold_prose_naming_people([row])
    assert row["source_document"] is None
    assert row["notes"] == f"{common.FREE_TEXT_WITHHELD_NOTE}; {URL_NOTE}"


def test_qld_pdf_file_name_with_a_name_is_withheld_and_row_stays_traceable():
    html = f"""<html><body><h2>2026</h2><table>{HEADER}
    <tr><td><p>Example Kids Pty Ltd</p><p>Sunny Meadow Early Learning</p></td><td>01/02/2026</td>
      <td><p>Approved provider fined $5,000 for missing child</p>
       <p><a href="/docs/Prosecution-Jane-Example.pdf">Prosecution</a><br/>
       <a href="/news/example-kids-fined">Further information</a></p></td>
      <td>N/A</td></tr></table></body></html>"""
    row = parse_register(
        html, page_url=INDEX_URL, captured_at="2026-10-29T07:00:00+00:00", source_snapshot="x.html"
    )[0]
    assert row["provider_name"] == "Example Kids Pty Ltd"
    assert row["source_document"] is None
    assert row["linked_documents"].endswith("/news/example-kids-fined")
    assert URL_NOTE in row["notes"]
    assert row["record_id"] and row["source_snapshot"] == "x.html"
    assert "jane" not in json.dumps(row).lower()


def test_schema_allows_a_withheld_source_document():
    prop = SCHEMA["properties"]["source_document"]
    assert "null" in prop["type"] and "source_document" not in SCHEMA["required"]
    assert "linked_documents" in SCHEMA["properties"]


def test_url_note_does_not_mark_the_provider_name_as_withheld():
    assert je.URL_WITHHELD_NOTE == common.URL_WITHHELD_NOTE == URL_NOTE
    assert not je.name_withheld_row({"notes": URL_NOTE})


def test_linked_documents_are_carried_into_the_consolidated_output():
    assert "linked_documents" in je.ACTION_COLUMNS


def test_consolidated_linked_documents_match_the_qld_output():
    import csv

    processed = Path(__file__).resolve().parent.parent / "data" / "processed"
    qld_path, all_path = (
        processed / "qld-enforcement-actions.csv",
        processed / "enforcement-actions-all.csv",
    )
    if not (qld_path.exists() and all_path.exists()):
        return
    with all_path.open(newline="", encoding="utf-8") as fh:
        joined = {r["record_id"]: r for r in csv.DictReader(fh)}
    with qld_path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            assert joined[row["record_id"]].get("linked_documents") == row["linked_documents"]


def test_register_file_names_with_plural_action_words_are_kept():
    url = (
        "https://education.nsw.gov.au/content/dam/main-education/register-of-published-"
        "enforcement-actions/Q2_Involuntary_Suspensions_2025_2026.pdf"
    )
    row = _row(source_document=url)
    common.withhold_prose_naming_people([row])
    assert row["source_document"] == url
    assert not pp.prose_may_name_person("Cancellations Providers Conditions Notices")


def test_record_id_does_not_depend_on_the_url_rule():
    import copy

    from scrapers import parse_sa_enforcement as sa

    from tests.test_sa_enforcement import CURRENT_FIXTURE

    named = "https://www.esb.sa.gov.au/Notice-Jane-Example"
    rows = sa.parse_actions(
        CURRENT_FIXTURE,
        source_document=named,
        captured_at="2026-10-29T03:00:00+00:00",
        period_label="Current compliance action",
        source_snapshot="data/raw/sa-enforcement/x.html",
    )
    assert all(r["source_document"] is None for r in rows)
    expected = copy.deepcopy(rows)
    for r in expected:
        r["source_document"] = named
    common.assign_record_ids(expected)
    assert [r["record_id"] for r in rows] == [r["record_id"] for r in expected]


# --- Codex round 5, finding 2: the URL rule in summaries, provenance notes and logs ---------


def test_nsw_fallback_summary_and_provenance_withhold_a_named_url(tmp_path, monkeypatch, caplog):
    import logging

    from scrapers import parse_nsw_enforcement as nsw

    from tests.test_nsw_enforcement import SOURCE, _fake_reader, _write_pdf_snapshot

    names = pp.PersonNames()
    names.add_subject("Jane Example")
    monkeypatch.setattr(common, "_PERSON_NAMES", names)
    src = tmp_path / SOURCE
    src.mkdir()
    url = "https://education.nsw.gov.au/x/Notice_to_Jane_Example.pdf"
    old = "2026-10-29T0718Z-notice-to-jane-example.pdf"
    new = "2026-11-02T0718Z-notice-to-jane-example.pdf"
    _write_pdf_snapshot(src, old, url)
    _write_pdf_snapshot(src, new, url)
    monkeypatch.setattr(nsw, "read_pdf_records", _fake_reader({new}))
    with caplog.at_level(logging.INFO, logger="scrapers"):
        rows, parsed, summary = nsw.parse_all(base_dir=tmp_path, root=tmp_path)
    assert summary["fallbacks"] and len(rows) == 1
    published = json.dumps(summary) + nsw.provenance_notes(summary)
    assert "jane" not in published.lower()
    assert common.URL_TEXT_WITHHELD in published
    assert "jane" not in caplog.text.lower()


def test_write_processed_provenance_applies_the_url_rule(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "PROCESSED_DIR", tmp_path)
    monkeypatch.setattr(common, "PROJECT_ROOT", tmp_path)
    raw = tmp_path / "raw" / "Notice-Jane-Example.pdf"
    common.write_processed(
        "x",
        [{"a": "1"}],
        ["a"],
        raw_inputs=[raw, tmp_path / "raw" / "register.html"],
        notes="Parsed from https://example.gov.au/docs/Jane-Example-notice.pdf and register.html.",
    )
    prov = (tmp_path / "x.provenance.json").read_text(encoding="utf-8")
    assert "jane" not in prov.lower()
    assert "raw/register.html" in prov and "register.html." in prov


def test_log_lines_apply_the_url_rule(caplog):
    import logging

    with caplog.at_level(logging.INFO, logger="scrapers"):
        common.log.warning("could not fetch %s: %s", "https://x.gov.au/Jane-Example.pdf", "404")
        common.log.info("parsed %s", "https://x.gov.au/register.pdf")
    assert "jane" not in caplog.text.lower()
    assert "https://x.gov.au/register.pdf" in caplog.text
