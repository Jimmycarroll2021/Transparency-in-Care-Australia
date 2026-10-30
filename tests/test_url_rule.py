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
