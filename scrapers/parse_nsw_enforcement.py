"""Fetch and parse the NSW register of published enforcement actions (quarterly PDFs).

Source: NSW Department of Education, CC BY 4.0 (see research/2026-10-29-register-enforcement-nsw-vic-qld-cth.md).
Attribution: (c) State of New South Wales (Department of Education).

Run: python3 scrapers/parse_nsw_enforcement.py [--force] [--skip-fetch]

Exit status: 0 when every document was identified and parsed and the outputs were written; 1 when
no snapshot was parsed; 2 when the run was incomplete (an unidentified snapshot or a document
with no parsable copy). On 1 or 2 data/processed/nsw-enforcement-actions.* are left unchanged and the
run summary is printed to stdout only.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from datetime import date
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit

if __package__ in (None, ""):  # allow `python3 scrapers/parse_nsw_enforcement.py`
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scrapers import common
from scrapers.common import (
    PROJECT_ROOT,
    RAW_DIR,
    assign_record_ids,
    ensure_person_names,
    fetch,
    known_hashes,
    list_snapshots,
    log,
    normalise_pr,
    normalise_se,
    note_withheld_subject,
    printed_fingerprint,
    withhold_free_text,
    withhold_prose_naming_people,
    write_processed,
    write_snapshot,
)
from scrapers.profile_providers import name_is_withheld

SOURCE = "nsw-enforcement"
JURISDICTION = "NSW"
INDEX_URL = (
    "https://education.nsw.gov.au/early-childhood-education/regulation-and-compliance/"
    "compliance-and-enforcement-actions/register-of-published-enforcement-actions"
)
SCHEMA_PATH = "data/schemas/enforcement-action.schema.json"
OUTPUT_NAME = "nsw-enforcement-actions"

FIELDNAMES = [
    "record_id",
    "jurisdiction",
    "source_register",
    "source_document",
    "source_snapshot",
    "captured_at",
    "service_approval_number",
    "service_approval_number_raw",
    "provider_approval_number",
    "provider_approval_number_raw",
    "service_name",
    "provider_name",
    "address",
    "suburb",
    "state",
    "postcode",
    "action_type",
    "action_type_raw",
    "reason",
    "legal_references",
    "date_issued",
    "date_issued_raw",
    "period_label",
    "notes",
    # Structured facts from a printed suspension period, kept before free text is withheld.
    "start_date",
    "end_date",
]


# ---------------------------------------------------------------------------
# Discovery and snapshotting
# ---------------------------------------------------------------------------

_HREF = re.compile(r"""href\s*=\s*["']([^"']+?\.pdf)(?:[?#][^"']*)?["']""", re.IGNORECASE)


def discover_pdf_urls(index_html: str, base_url: str = INDEX_URL) -> list[str]:
    """Absolute, de-duplicated PDF URLs linked from the index page, in page order."""
    seen: dict[str, None] = {}
    for match in _HREF.finditer(index_html):
        url = urljoin(base_url, html.unescape(match.group(1)).strip())
        seen.setdefault(url, None)
    return list(seen)


def slug_from_url(url: str) -> str:
    stem = Path(unquote(urlsplit(url).path)).stem
    return re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-") or "document"


def write_pdf_snapshot(fetched: common.Fetched, slug: str) -> Path:
    """Like common.write_snapshot, but the file name is <stamp>-<slug>.pdf. Never overwrites."""
    stamp = common.utc_stamp()
    path = common._unique_path(RAW_DIR / SOURCE, f"{stamp}-{slug}", "pdf")
    path.write_bytes(fetched.content)
    meta = {
        "source": SOURCE,
        "url": fetched.url,
        "final_url": fetched.final_url,
        "status": fetched.status,
        "fetched_at": fetched.fetched_at,
        "content_type": fetched.content_type,
        "last_modified": fetched.last_modified,
        "etag": fetched.etag,
        "bytes": len(fetched.content),
        "sha256": fetched.sha256,
        "user_agent": common.USER_AGENT,
        "role": "pdf",
        "slug": slug,
    }
    Path(f"{path}.meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    log.info("snapshot %s (%d bytes)", path.relative_to(PROJECT_ROOT), len(fetched.content))
    return path


def fetch_all(force: bool = False) -> dict:
    """Snapshot the index page and every linked PDF not already held. Returns a summary."""
    summary = {"pdfs_found": 0, "pdfs_fetched": 0, "pdfs_skipped": 0, "errors": []}
    index = fetch(INDEX_URL)
    hashes = known_hashes(SOURCE)
    if index.sha256 in hashes and not force:
        log.info("index page unchanged (sha256 %s), not re-snapshotted", index.sha256[:12])
    else:
        write_snapshot(SOURCE, index, "html", extra_meta={"role": "index"})
        hashes.add(index.sha256)
    urls = discover_pdf_urls(index.text, index.final_url)
    summary["pdfs_found"] = len(urls)
    log.info("found %d linked PDFs", len(urls))
    for url in urls:
        try:
            doc = fetch(url)
        except Exception as exc:  # network and HTTP errors must not stop the run
            log.warning("could not fetch %s: %s", url, exc)
            summary["errors"].append(f"{url}: {exc}")
            continue
        if not doc.content.startswith(b"%PDF"):
            log.warning("not a PDF, skipped: %s", url)
            summary["errors"].append(f"{url}: response was not a PDF")
            continue
        if doc.sha256 in hashes and not force:
            summary["pdfs_skipped"] += 1
            log.info("already held (sha256 %s): %s", doc.sha256[:12], url)
            continue
        write_pdf_snapshot(doc, slug_from_url(url))
        hashes.add(doc.sha256)
        summary["pdfs_fetched"] += 1
    return summary


# ---------------------------------------------------------------------------
# Field helpers (pure functions, unit tested)
# ---------------------------------------------------------------------------

_MONTHS = {
    m: i
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1
    )
}
_DATE_SLASH = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")
_DATE_DMONY = re.compile(r"^(\d{1,2})-([A-Za-z]{3})-(\d{2}|\d{4})$")


def clean_text(value: str | None) -> str:
    """Flatten a PDF cell to one line. Joins hyphen wraps (Pre-\\nSchool) without a space."""
    if not value:
        return ""
    text = re.sub(r"(?<=[A-Za-z])-\n(?=[A-Za-z])", "-", value)
    return re.sub(r"\s+", " ", text).strip()


_SUSPENSION_PERIOD = re.compile(
    r"(?i)period of suspension is from[ ]+([0-9]{1,2}/[0-9]{1,2}/[0-9]{2,4})"
    r"[ ]+(?:until|to)[ ]+([0-9]{1,2}/[0-9]{1,2}/[0-9]{2,4})"
)


def extract_suspension_period(*texts: str | None) -> tuple[str | None, str | None]:
    """(start, end) ISO dates from 'The period of suspension is from D until D' as printed.
    (None, None) when no such sentence is printed or a date does not parse; never inferred."""
    for text in texts:
        m = _SUSPENSION_PERIOD.search(" ".join((text or "").split()))
        if m:
            start, end = parse_date(m.group(1)), parse_date(m.group(2))
            if start and end:
                return start, end
    return None, None


def parse_date(raw: str | None) -> str | None:
    """DD/MM/YYYY (or D-Mon-YY, seen in the Q3 2024-25 file) to ISO. None if unparsable or invalid."""
    if not raw:
        return None
    text = raw.strip()
    try:
        if m := _DATE_SLASH.match(text):
            d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        elif m := _DATE_DMONY.match(text):
            mo = _MONTHS.get(m.group(2).lower())
            if mo is None:
                return None
            d, y = int(m.group(1)), int(m.group(3))
            if y < 100:
                y += 2000
        else:
            return None
        return date(y, mo, d).isoformat()
    except ValueError:
        return None


# Order matters: the first phrase found wins. Searched in the "nature" text, then the
# "details of action taken" text. The grounds/reason text is never searched, because
# cancellation grounds mention conditions, suspensions and notices that were not the action.
ACTION_PHRASES: list[tuple[str, str]] = [
    ("prosecution", "prosecution"),
    ("enforceable undertaking", "enforceable_undertaking"),
    ("emergency action notice", "emergency_action_notice"),
    ("prohibition notice", "prohibition_notice"),
    ("show cause", "show_cause_notice"),
    ("compliance direction", "compliance_direction"),
    ("direction to exclude", "direction_to_exclude"),
    ("compliance notice", "compliance_notice"),
    ("cancel", "approval_cancelled"),
    ("suspen", "approval_suspended"),
    ("amend", "approval_amended"),
    ("condition", "condition_imposed"),
]


def map_action_type(*printed: str | None) -> str:
    """Map printed phrases to the schema enum. Anything not in the dictionary is 'other'."""
    for text in printed:
        if not text:
            continue
        low = clean_text(text).lower()
        for phrase, action in ACTION_PHRASES:
            if phrase in low:
                return action
    return "other"


_LEGAL_REF = re.compile(
    r"(?<![A-Za-z0-9])(Regulations?|Reg|Law|Section|S)\.?\s?(\d+[A-Z]?(?:\s?\([0-9A-Za-z]{1,4}\))*)(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_REF_PREFIX = {"regulation": "Regulation", "regulations": "Regulation", "reg": "Regulation"}


def extract_legal_references(*texts: str | None) -> list[str]:
    """Regulation, Law and section citations, in order of first appearance, de-duplicated.

    'Reg 102D' becomes 'Regulation 102D'; 'Section 177', 'S31(a)' and 's 33 (1)' become
    'section 177', 'section 31(a)', 'section 33(1)'. 'Law 167' stays 'Law 167'.
    """
    found: dict[str, None] = {}
    for text in texts:
        if not text:
            continue
        for m in _LEGAL_REF.finditer(clean_text(text)):
            word = m.group(1).lower()
            number = re.sub(r"\s+", "", m.group(2))
            if word in ("section", "s"):
                prefix = "section"
            elif word == "law":
                prefix = "Law"
            else:
                prefix = _REF_PREFIX[word]
            found.setdefault(f"{prefix} {number}", None)
    return list(found)


def date_in_period(iso_date: str, period_label: str) -> bool:
    """True if an ISO date falls in the financial-year quarter named by '2024-25 Q4'."""
    m = re.fullmatch(r"(\d{4})-\d{2} Q([1-4])", period_label)
    if not m:
        return True
    start_year, quarter = int(m.group(1)), int(m.group(2))
    year, month = int(iso_date[:4]), int(iso_date[5:7])
    first_month = {1: 7, 2: 10, 3: 1, 4: 4}[quarter]
    expected_year = start_year if quarter <= 2 else start_year + 1
    return year == expected_year and first_month <= month < first_month + 3


_PERIOD = re.compile(r"(?:^|-)q([1-4])-.*?(\d{4})-(\d{4})")


def period_label_from_slug(slug: str) -> str | None:
    """'q4-service-enforcement-action-information-2024-2025' -> '2024-25 Q4'."""
    m = _PERIOD.search(slug)
    if not m:
        return None
    return f"{m.group(2)}-{m.group(3)[2:]} Q{m.group(1)}"


_ENTITY_WORDS = re.compile(
    r"\b(pty|ltd|limited|inc|incorporated|association|council|trust|co-?operative|foundation|"
    r"church|society|club|university|school|college|company|corporation|holdings|group|"
    r"management|enterprises|services?|centres?|centers?|care|childcare|learning|education|"
    r"educational|kids|children|kindergartens?|preschools?|montessori|academy|nursery|early|"
    r"parish|diocese|network|institute|australia|nsw|department|authority|ministry|p/l|"
    r"partnership|ministries|community)\b",
    re.IGNORECASE,
)
_TRADING_AS = re.compile(r"\b(t/a|trading as|trading)\b", re.IGNORECASE)


def provider_name_if_entity(name: str | None) -> tuple[str | None, str | None]:
    """Return (name, note). The register lists sole-trader providers by personal name, and a
    personal name must never be stored, so a name is kept only when it reads as an organisation.
    The shared fail-closed rule (profile_providers.name_is_withheld) also applies, so an entity
    word such as 'trust' cannot carry an individual trustee, an estate or an executor through."""
    text = clean_text(name)
    if not text:
        return None, None
    if _ENTITY_WORDS.search(text) and not _TRADING_AS.search(text) and not name_is_withheld(text):
        return text, None
    return (
        None,
        "provider name withheld: does not read as an organisation and may identify an individual",
    )


_STATE_POSTCODE = re.compile(r",?\s*\b(NSW)\b\s*(\d{4})?\s*$")
_STREET_TOKENS = {
    "ST", "RD", "AVE", "STREET", "ROAD", "AVENUE", "DRIVE", "DR", "LANE", "LN", "HWY",
    "HIGHWAY", "PDE", "PARADE", "CRES", "CLOSE", "PL", "PLACE", "CT", "COURT", "BLVD",
}  # fmt: skip
_UPPER_TOKEN = re.compile(r"^[A-Z][A-Z'\-]+,?$")


def split_address(address: str | None) -> tuple[str | None, str | None, str | None]:
    """(suburb, state, postcode) taken only from what is printed: a trailing 'NSW 2138' and a
    trailing run of capitalised words. Anything doubtful gives None for that part."""
    text = clean_text(address)
    if not text:
        return None, None, None
    state = postcode = None
    if m := _STATE_POSTCODE.search(text):
        state, postcode = m.group(1), m.group(2)
        text = text[: m.start()].strip()
    elif m := re.search(r"\b([A-Z][A-Z'\-]+),?\s+(\d{4})$", text):
        postcode = m.group(2)  # e.g. 'COLYTON 2760': a printed postcode with no state
        text = text[: m.start(2)].strip()
    tokens = text.replace(",", " ,").split()
    run: list[str] = []
    for tok in reversed(tokens):
        bare = tok.strip(",")
        if bare and _UPPER_TOKEN.match(tok) and bare not in _STREET_TOKENS and len(run) < 4:
            run.insert(0, bare)
        elif tok == ",":
            continue
        else:
            break
    suburb = " ".join(run) if run and len(run) < len(tokens) else None
    return suburb, state, postcode


# ---------------------------------------------------------------------------
# PDF table parsing
# ---------------------------------------------------------------------------

_KEY_SEP = r"\s*[-\u2013\u2014:]?\s*"  # hyphen, the two long dash characters or colon; any spacing
_ID_CELL = re.compile(rf"^\s*(SE|PR){_KEY_SEP}\d+\w*\s*$", re.IGNORECASE)


def is_id_cell(text: str | None) -> bool:
    """True if a cell holds a printed SE-/PR- key (well formed or not), which starts a record."""
    return bool(text) and _ID_CELL.match(text) is not None


_HEADER_WORDS = re.compile(
    r"^(service|provider|date|issued|details|of|action|taken|enforcement|nature|reason|grounds|"
    r"for|decision|to|cancel|involuntary|suspension|address|name|id|\(provision|under|which|"
    r"compliance|is|taken\))(\s+(service|provider|date|issued|details|of|action|taken|enforcement|"
    r"nature|reason|grounds|for|decision|to|cancel|involuntary|suspension|address|name|id|"
    r"\(provision|under|which|compliance|is|taken\)))*$",
    re.IGNORECASE,
)
_ROLE_TESTS = [
    ("id", re.compile(r"\b(service|provider)\s*id\b", re.I)),
    ("address", re.compile(r"address", re.I)),
    ("supervisor", re.compile(r"supervisor", re.I)),
    ("nature", re.compile(r"nature", re.I)),
    ("details", re.compile(r"details", re.I)),
    ("date", re.compile(r"date", re.I)),
    ("reason", re.compile(r"reason|grounds", re.I)),
    ("name", re.compile(r"name", re.I)),
]


def header_role(text: str | None) -> str | None:
    flat = clean_text(text)
    for role, test in _ROLE_TESTS:
        if test.search(flat):
            return role
    return None


def is_header_row(row: list) -> bool:
    return any(c and re.fullmatch(r"(service|provider)\s*id", clean_text(c), re.I) for c in row)


def is_header_fragment(row: list) -> bool:
    cells = [clean_text(c) for c in row if clean_text(c)]
    return all(_HEADER_WORDS.match(c) for c in cells)


class RawRecord:
    """One register row as read from the PDF, before mapping to the schema."""

    def __init__(self, page: int) -> None:
        self.page = page
        self.fields: dict[str, str] = {}
        self.continued = False
        self.warnings: list[str] = []

    def add(self, role: str, text: str, *, append: bool) -> None:
        text = clean_text(text)
        if not text:
            return
        if append and self.fields.get(role):
            self.fields[role] = f"{self.fields[role]} {text}"
        else:
            self.fields[role] = text


def read_pdf_records(path: Path) -> tuple[list[RawRecord], dict]:
    """Read every data row of one register PDF.

    The layouts differ by quarter (2024-25 files have spacer columns and the printed values do not
    sit under their header cell; 2025-26 files have six clean columns), so roles are assigned by
    reading the non-empty header cells in order, then learning which raw column index each role
    lands in from rows that are complete. Rows with no ID are continuations of a cell that wrapped
    across a page and are appended to the previous record, column by column.
    """
    import pdfplumber

    stats = {"pages": 0, "stray_single_column_rows": 0, "continuations": 0, "supervisor_columns": 0}
    tables: list[tuple[int, list[list]]] = []
    with pdfplumber.open(path) as pdf:
        stats["pages"] = len(pdf.pages)
        for page_no, page in enumerate(pdf.pages, 1):
            for table in page.extract_tables():
                tables.append((page_no, table))

    # Pass 1: learn raw-index -> role maps from complete rows.
    roles_by_width: dict[int, list[str | None]] = {}
    maps: dict[tuple, dict[int, str | None]] = {}
    for _, table in tables:
        for row in table:
            width = len(row)
            if width < 2:
                continue
            if is_header_row(row):
                roles_by_width[width] = [header_role(c) for c in row if clean_text(c)]
                continue
            roles = roles_by_width.get(width)
            idx = [i for i, c in enumerate(row) if clean_text(c)]
            if roles and len(idx) == len(roles) and any(is_id_cell(row[i]) for i in idx):
                maps.setdefault((width, tuple(map(str, roles))), dict(zip(idx, roles, strict=True)))

    # Pass 2: assign.
    records: list[RawRecord] = []
    current: RawRecord | None = None
    last_roles: list[str | None] | None = None
    roles_by_width = {}
    for page_no, table in tables:
        for row in table:
            width = len(row)
            if width < 2:
                if any(clean_text(c) for c in row) and not is_header_fragment(row):
                    stats["stray_single_column_rows"] += 1
                continue
            if is_header_row(row):
                roles_by_width[width] = [header_role(c) for c in row if clean_text(c)]
                last_roles = roles_by_width[width]
                if "supervisor" in roles_by_width[width]:
                    stats["supervisor_columns"] += 1
                continue
            if all(not clean_text(c) for c in row) or is_header_fragment(row):
                continue
            roles = roles_by_width.get(width)
            populated = [i for i, c in enumerate(row) if clean_text(c)]
            if roles is None:
                # Some pages come out with a different column count and no header row in the
                # same table (e.g. 7 columns without spacers). Use the last header seen if the
                # populated cells line up with it one to one.
                if last_roles is not None and len(populated) == len(last_roles):
                    roles = last_roles
                else:
                    if current is not None:
                        current.warnings.append(f"row of width {width} could not be mapped")
                    continue
            raw_map = maps.get((width, tuple(map(str, roles))))
            has_id = any(is_id_cell(row[i]) for i in populated)
            if raw_map is None:  # no complete row to learn from: fall back to reading order
                raw_map = dict(zip(populated, roles, strict=False))
            if has_id:
                current = RawRecord(page_no)
                records.append(current)
                append = False
            else:
                if current is None:
                    continue
                current.continued = True
                stats["continuations"] += 1
                append = True
            for i in populated:
                role = raw_map.get(i)
                if role is None:
                    current.warnings.append(f"unmapped cell at column {i} on page {page_no}")
                elif role == "supervisor":
                    current.warnings.append("supervisor/person column dropped")
                else:
                    current.add(role, row[i], append=append)
    return records, stats


# ---------------------------------------------------------------------------
# Mapping to the enforcement action schema
# ---------------------------------------------------------------------------


_KEY_PARTS = re.compile(rf"^(SE|PR){_KEY_SEP}(\d+)(.*)$", re.IGNORECASE)


def printed_key(id_raw: str | None) -> tuple[str | None, str | None]:
    """(key, note) for a printed approval number. key is 'SE-' or 'PR-' plus 8 digits, or None.

    Only differences that carry no meaning are corrected: letter case, spacing and the dash
    character between prefix and digits. A number with too few or too many digits, or with
    characters after the digits, is never padded, trimmed or guessed; the key is null and the
    note says why, so the join's fallbacks decide what happens to the row.
    """
    text = clean_text(id_raw)
    if not text:
        return None, None
    m = _KEY_PARTS.match(text)
    if m and len(m.group(2)) == 8 and not m.group(3).strip():
        return f"{m.group(1).upper()}-{m.group(2)}", None
    if m is None:
        reason = "it does not start with SE- or PR- and digits"
    elif m.group(3).strip():
        reason = (
            f"it has {len(m.group(2))} digits then trailing '{m.group(3).strip()}', "
            "whose meaning is not printed"
        )
    else:
        reason = f"it has {len(m.group(2))} digits and the digit at fault cannot be located"
    return None, (
        f"approval number '{text}' is not SE-/PR- plus 8 digits ({reason}); "
        "normalised value left null"
    )


def build_row(
    raw: RawRecord,
    *,
    meta: dict,
    snapshot_rel: str,
    period_label: str | None,
) -> dict:
    """Turn one raw register row into a schema row. Never invents values."""
    f = raw.fields
    notes: list[str] = list(dict.fromkeys(raw.warnings))
    id_raw = f.get("id")
    is_provider_row = bool(id_raw) and id_raw.upper().startswith("PR")
    key, key_note = printed_key(id_raw)
    se = normalise_se(key) if key and key.startswith("SE") else None
    pr = normalise_pr(key) if key and key.startswith("PR") else None
    if key_note:
        notes.append(key_note)
    if not id_raw:
        notes.append("approval number missing in source")

    provider_name = service_name = address = suburb = state = postcode = None
    withheld_note = None
    if is_provider_row:
        provider_name, withheld_note = provider_name_if_entity(f.get("name"))
    else:
        service_name = f.get("name") or None
        address = f.get("address") or None
        suburb, state, postcode = split_address(address)

    nature = f.get("nature") or None
    details = f.get("details") or None
    reason = f.get("reason") or None
    action_type_raw = nature or details or ""
    action_type = map_action_type(nature, details)
    if not action_type_raw:
        notes.append("no action type printed")

    date_raw = f.get("date") or None
    date_iso = parse_date(date_raw)
    if date_raw and date_iso is None:
        notes.append(f"date '{date_raw}' could not be parsed")
    if not date_raw:
        notes.append("date missing in source")
    if date_iso and period_label and not date_in_period(date_iso, period_label):
        notes.append(f"date {date_iso} is outside the register period {period_label} as printed")
    if raw.continued:
        notes.append("row wrapped across a page break and was rejoined")

    suspension = extract_suspension_period(nature, details)
    row = {
        "record_id": None,  # set by parse_file from non-name facts (assign_record_ids)
        "jurisdiction": JURISDICTION,
        "source_register": INDEX_URL,
        "source_document": meta.get("final_url") or meta.get("url") or INDEX_URL,
        "source_snapshot": snapshot_rel,
        "captured_at": meta.get("fetched_at"),
        "service_approval_number": se,
        "service_approval_number_raw": id_raw if not is_provider_row else None,
        "provider_approval_number": pr,
        "provider_approval_number_raw": id_raw if is_provider_row else None,
        "service_name": service_name,
        "provider_name": provider_name,
        "address": address,
        "suburb": suburb,
        "state": state,
        "postcode": postcode,
        "action_type": action_type,
        "action_type_raw": action_type_raw,
        "reason": reason,
        "legal_references": "; ".join(extract_legal_references(reason, details)),
        "date_issued": date_iso,
        "date_issued_raw": date_raw,
        "period_label": period_label,
        "notes": "; ".join(notes) if notes else None,
        "_details": details,
        "start_date": suspension[0],
        "end_date": suspension[1],
        # In-memory only, never written: the printed row, names included, so a repeated row is
        # spotted without the record_id ever depending on a name.
        "_fingerprint": printed_fingerprint(*(f"{k}: {v}" for k, v in sorted(f.items()))),
    }
    if withheld_note:
        # Rule 2: the reason and details can repeat the name in forms no redaction catches, so
        # every free-text field is withheld whole. Keys, dates and the action type stay.
        # The key note quotes only the printed approval number, which is kept anyway.
        withhold_free_text(row, tuple(n for n in (key_note, withheld_note) if n))
        note_withheld_subject(f.get("name"))  # in-memory name set, never written
        row["_details"] = None
    return row


DUPLICATE_NOTE = "duplicate row in source"


def mark_duplicates(rows: list[dict]) -> int:
    """Keep every row; add a note to the second and later copies of an identical row.

    Two rows are identical when every printed field matches within the same source snapshot
    (the register says some services receive several actions on one day for separate incidents).
    """
    seen: set[tuple] = set()
    count = 0
    for row in rows:
        key = (row["source_snapshot"], row["_fingerprint"])
        if key in seen:
            row["notes"] = (
                f"{row['notes']}; {DUPLICATE_NOTE}" if row.get("notes") else DUPLICATE_NOTE
            )
            count += 1
        else:
            seen.add(key)
    return count


def document_key(path: Path) -> str | None:
    """The exact source URL of a snapshot, from its meta sidecar ('url', then 'final_url').

    The URL string is compared exactly (surrounding whitespace stripped, nothing else): two
    documents whose URLs share a file name stay two documents, and a same-minute copy whose file
    name carries a collision suffix is still the same document. None when there is no readable
    sidecar or it holds no URL; such a snapshot cannot be identified and is not parsed.
    """
    meta = read_meta(path)
    for field in ("url", "final_url"):
        value = meta.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def pdf_documents(base_dir: Path = RAW_DIR) -> tuple[dict[str, list[Path]], list[Path]]:
    """(documents, unidentified). Documents maps document_key to its snapshots, newest first.

    Unidentified snapshots (no usable sidecar URL) are returned separately, oldest first.
    """
    pdfs = [p for p in list_snapshots(SOURCE, base_dir=base_dir) if p.suffix.lower() == ".pdf"]
    docs: dict[str, list[Path]] = {}
    unidentified: list[Path] = []
    for path in pdfs:  # listed oldest first
        key = document_key(path)
        if key is None:
            unidentified.append(path)
        else:
            docs.setdefault(key, []).insert(0, path)
    return docs, unidentified


def pdf_snapshots(base_dir: Path = RAW_DIR) -> tuple[list[Path], list[Path]]:
    """(kept, superseded) PDF snapshots. Only the newest snapshot of each document is kept.

    A re-issued quarterly PDF is fetched again from the same URL and archived next to the old
    copy; parsing both would count every action in that quarter twice. Documents are identified
    by document_key. parse_all falls back to an older copy if the newest cannot be parsed.
    Unidentified snapshots are in neither list.
    """
    pdfs = [p for p in list_snapshots(SOURCE, base_dir=base_dir) if p.suffix.lower() == ".pdf"]
    docs, unidentified = pdf_documents(base_dir)
    keep = {versions[0] for versions in docs.values()}
    superseded = {p for versions in docs.values() for p in versions[1:]}
    return [p for p in pdfs if p in keep], [p for p in pdfs if p in superseded]


def snapshot_rel_path(path: Path, root: Path = PROJECT_ROOT) -> str:
    """Project-relative path with forward slashes, so outputs are the same on every platform."""
    return path.relative_to(root).as_posix()


def read_meta(path: Path) -> dict:
    """The snapshot's meta sidecar, or {} when it is missing, unreadable or not a JSON object."""
    meta_path = Path(f"{path}.meta.json")
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text())
        except json.JSONDecodeError:
            return {}
        if isinstance(meta, dict):
            return meta
        log.warning("meta sidecar of %s is not a JSON object; ignored", path.name)
    return {}


def slug_of_snapshot(path: Path) -> str:
    """'2026-10-29T0718Z-q4-cancellations-services-2025-2026.pdf' -> 'q4-cancellations-services-2025-2026'."""
    return re.sub(r"^\d{4}-\d{2}-\d{2}T\d{4,6}Z(?:-\d+)?-?", "", path.stem)


def _parse_snapshot(path: Path, root: Path, summary: dict) -> list[dict] | None:
    """Rows of one snapshot, or None if it raised or yielded no rows. Records it in by_file."""
    meta = read_meta(path)
    slug = slug_of_snapshot(path)
    label = period_label_from_slug(slug)
    if label is None:
        log.warning("no period label derivable from %s", path.name)
    try:
        raws, stats = read_pdf_records(path)
    except Exception as exc:  # a corrupt PDF must not stop the other files
        log.error("could not parse %s: %s", path.name, exc)
        summary["by_file"][path.name] = {"error": str(exc)}
        return None
    if not raws:
        log.error("no rows read from %s", path.name)
        summary["by_file"][path.name] = {"error": "no rows read", **stats}
        return None
    rel = snapshot_rel_path(path, root=root)
    file_rows = [build_row(r, meta=meta, snapshot_rel=rel, period_label=label) for r in raws]
    summary["duplicates"] += mark_duplicates(file_rows)
    assign_record_ids(file_rows)
    # After the ids: the id never depends on what the prose or URL rule withholds.
    withhold_prose_naming_people(file_rows)  # shared prose rule, every row
    summary["by_file"][path.name] = {"rows": len(file_rows), **stats}
    log.info("parsed %s: %d rows %s", path.name, len(file_rows), stats)
    return file_rows


def parse_all(
    base_dir: Path = RAW_DIR, root: Path = PROJECT_ROOT
) -> tuple[list[dict], list[Path], dict]:
    """Parse the newest usable snapshot of every document.

    Each document's snapshots are tried newest first. A snapshot that raises, or that yields no
    rows, is a failed parse; the next older copy is then tried and the fallback is recorded in
    summary["fallbacks"]. A document with no parsable copy is listed in
    summary["failed_documents"] and summary["complete"] is False; the other documents are still
    parsed, as before. A snapshot with no usable sidecar URL is not parsed and not guessed: it is
    listed in summary["unidentified_snapshots"] and summary["complete"] is False.
    """
    rows: list[dict] = []
    parsed: list[Path] = []
    summary = {
        "pdfs_parsed": 0,
        "rows": 0,
        "null_service_approval_number": 0,
        "null_provider_approval_number_on_provider_rows": 0,
        "duplicates": 0,
        "withheld_provider_names": 0,
        "superseded_snapshots": [],
        "fallbacks": [],
        "failed_documents": [],
        "unidentified_snapshots": [],
        "complete": True,
        "by_file": {},
    }
    used: dict[Path, list[dict]] = {}
    superseded: list[Path] = []
    docs, unidentified = pdf_documents(base_dir)
    for path in unidentified:
        log.error("no source URL in the meta sidecar of %s; not parsed", path.name)
        summary["unidentified_snapshots"].append(path.name)
        summary["complete"] = False
    for doc, versions in docs.items():
        failed: list[str] = []
        for i, path in enumerate(versions):
            file_rows = _parse_snapshot(path, root, summary)
            if file_rows is None:
                failed.append(path.name)
                continue
            used[path] = file_rows
            superseded.extend(versions[i + 1 :])
            if failed:
                log.warning("%s: newer snapshot(s) %s failed, used %s", doc, failed, path.name)
                summary["fallbacks"].append({"document": doc, "used": path.name, "failed": failed})
            break
        else:
            log.error("%s: no snapshot could be parsed (%s)", doc, ", ".join(failed))
            summary["failed_documents"].append({"document": doc, "snapshots": failed})
            summary["complete"] = False
    for path in sorted(superseded):
        log.info("superseded by a newer snapshot of the same document, not parsed: %s", path.name)
        summary["superseded_snapshots"].append(path.name)
    for path in sorted(used):  # oldest first, the order outputs were always written in
        rows.extend(used[path])
        parsed.append(path)
        summary["pdfs_parsed"] += 1
    for r in rows:
        if r["service_approval_number"] is None and r["provider_approval_number_raw"] is None:
            summary["null_service_approval_number"] += 1
        if r["provider_approval_number_raw"] is not None and r["provider_approval_number"] is None:
            summary["null_provider_approval_number_on_provider_rows"] += 1
        if r["notes"] and "provider name withheld" in r["notes"]:
            summary["withheld_provider_names"] += 1
    summary["rows"] = len(rows)
    return rows, parsed, summary


def provenance_notes(summary: dict) -> str:
    """Provenance notes for the processed output, including any document not fully parsed."""
    notes = (
        "NSW Department of Education register of published enforcement actions, CC BY 4.0, "
        "(c) State of New South Wales (Department of Education). legal_references joined with '; '. "
        "Personal provider names withheld; nominated supervisor data not stored."
    )
    for fb in summary["fallbacks"]:
        notes += f" Fallback: {fb['document']} parsed from {fb['used']}; failed: {', '.join(fb['failed'])}."
    for fd in summary["failed_documents"]:
        notes += f" Not parsed: {fd['document']}; no snapshot could be read ({', '.join(fd['snapshots'])})."
    for name in summary["unidentified_snapshots"]:
        notes += f" Not parsed: {name}; no source URL in its meta sidecar, document not identified."
    return notes


def main(argv: list[str] | None = None) -> int:
    ensure_person_names()  # in-memory names for the prose rule (Codex round 3)
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--force", action="store_true", help="re-snapshot PDFs already held")
    ap.add_argument("--skip-fetch", action="store_true", help="parse existing snapshots only")
    args = ap.parse_args(argv)

    fetch_summary: dict = {}
    if not args.skip_fetch:
        try:
            fetch_summary = fetch_all(force=args.force)
        except Exception as exc:
            log.error("index page fetch failed (%s); parsing snapshots already held", exc)
            fetch_summary = {"index_error": str(exc)}
    rows, parsed, summary = parse_all()
    if not parsed:
        log.error("no PDF snapshots to parse")
        print(json.dumps({"fetch": fetch_summary, "parse": summary}, indent=2))
        return 1
    if not summary["complete"]:
        # A partial run must not replace the last good outputs: the join would silently lose the
        # missing documents' actions. The summary is printed to stdout instead; no file is written.
        log.error(
            "run incomplete; %s left unchanged. Unidentified snapshots: %s. Failed documents: %s",
            f"data/processed/{OUTPUT_NAME}.*",
            ", ".join(summary["unidentified_snapshots"]) or "none",
            "; ".join(
                f"{fd['document']} ({', '.join(fd['snapshots'])})"
                for fd in summary["failed_documents"]
            )
            or "none",
        )
        print(json.dumps({"fetch": fetch_summary, "parse": summary}, indent=2))
        return 2
    for row in rows:
        row.pop("_details", None)
    notes = provenance_notes(summary)
    write_processed(
        OUTPUT_NAME,
        rows,
        FIELDNAMES,
        raw_inputs=parsed,
        schema=SCHEMA_PATH,
        notes=notes,
    )
    print(json.dumps({"fetch": fetch_summary, "parse": summary}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
