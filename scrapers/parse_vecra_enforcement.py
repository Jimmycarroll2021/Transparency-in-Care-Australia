"""Fetch and parse VECRA (Victoria) monthly enforcement action pages under the National Law.

Source: Victorian Early Childhood Regulation Authority, https://www.vecra.vic.gov.au/enforcement-action
Licence: CC BY 4.0, attribution "(c) Copyright State Government of Victoria"
(see research/2026-10-29-register-enforcement-nsw-vic-qld-cth.md, section 2).

Only HTML pages are fetched. robots.txt disallows the archived PDF and Word files, so the
historical years (2020 to 2025) are not collected here; their URLs are logged for the hub.

Outputs:
- data/raw/vecra-enforcement/<stamp>-index.html and <stamp>-<month>-<year>.html (+ .meta.json)
- data/processed/vecra-enforcement-actions.csv (one row per published action per service)
- data/processed/vecra-enforcement-monthly-counts.csv (summary table counts, the denominator)

Run: python3 scrapers/parse_vecra_enforcement.py [--force] [--skip-fetch]
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup, Tag

if __package__ in (None, ""):  # allow `python3 scrapers/parse_vecra_enforcement.py`
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scrapers import common
from scrapers.common import (
    PROCESSED_DIR,
    PROJECT_ROOT,
    RAW_DIR,
    USER_AGENT,
    Fetched,
    fetch,
    known_hashes,
    log,
    normalise_pr,
    normalise_se,
    record_hash,
    utc_stamp,
    write_processed,
)
from scrapers.profile_providers import name_is_withheld

SOURCE = "vecra-enforcement"
JURISDICTION = "VIC"
INDEX_URL = "https://www.vecra.vic.gov.au/enforcement-action"
SCHEMA_PATH = "data/schemas/enforcement-action.schema.json"
ACTIONS_NAME = "vecra-enforcement-actions"
COUNTS_NAME = "vecra-enforcement-monthly-counts"

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
]

COUNT_FIELDNAMES = [
    "period_label",
    "action_type_raw",
    "count",
    "source_document",
    "captured_at",
    "count_raw",
    "section",
    "page_period_label",
    "source_snapshot",
]

MONTHS = "january|february|march|april|may|june|july|august|september|october|november|december"
# Monthly pages, including multi-month pages such as april-may-2026 or january-march-2026.
PAGE_PATH = re.compile(
    rf"^/enforcement-actions-(?P<slug>(?:{MONTHS})(?:-(?:{MONTHS}))?-\d{{4}})/?$", re.IGNORECASE
)
SUMMARY_SLUG = "summary-table"
SUMMARY_PATH = "/enforcement-action-summary-table"
SUMMARY_URL = f"https://www.vecra.vic.gov.au{SUMMARY_PATH}"
ARCHIVE_FILE = re.compile(r"\.(pdf|docx?|xlsx?|csv)$", re.IGNORECASE)

_DASHES = "".join(chr(c) for c in (0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2015, 0x2212))

# ---------------------------------------------------------------------------
# Small text helpers
# ---------------------------------------------------------------------------


def clean(text: str | None) -> str:
    """Collapse whitespace (including non-breaking spaces) and trim."""
    if text is None:
        return ""
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def fold_apostrophes(text: str) -> str:
    return text.replace("\u2019", "'").replace("\u2018", "'")


def fold_dashes(text: str) -> str:
    """Replace Unicode dash variants with a plain hyphen so matching is simple."""
    return re.sub(f"[{_DASHES}]", "-", text)


def slug_to_label(slug: str) -> str:
    """'april-may-2026' -> 'April to May 2026'; 'august-2026' -> 'August 2026'."""
    parts = slug.split("-")
    year = parts[-1]
    months = [p.capitalize() for p in parts[:-1]]
    return f"{' to '.join(months)} {year}"


def parse_date(raw: str | None) -> str | None:
    """'3 August 2026' -> '2026-08-03'. None if it cannot be parsed."""
    text = clean(raw)
    if not text:
        return None
    for fmt in ("%d %B %Y", "%d %b %Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# Index discovery
# ---------------------------------------------------------------------------


def discover_pages(index_html: str, base_url: str = INDEX_URL) -> dict[str, str]:
    """Return {slug: absolute URL} for each monthly HTML page, plus the summary table page."""
    soup = BeautifulSoup(index_html, "lxml")
    found: dict[str, str] = {}
    for a in soup.find_all("a", href=True):
        url = urljoin(base_url, str(a["href"]).split("#")[0])
        parts = urlsplit(url)
        if parts.netloc.lower() not in {"www.vecra.vic.gov.au", "vecra.vic.gov.au"}:
            continue
        m = PAGE_PATH.match(parts.path)
        if m:
            slug = m.group("slug").lower()
            found.setdefault(slug, f"https://www.vecra.vic.gov.au/enforcement-actions-{slug}")
        elif parts.path.rstrip("/") == SUMMARY_PATH:
            found.setdefault(SUMMARY_SLUG, SUMMARY_URL)
    return found


def discover_archive_links(index_html: str, base_url: str = INDEX_URL) -> list[str]:
    """Archived PDF/Word/other files linked from the index. Logged, never fetched."""
    soup = BeautifulSoup(index_html, "lxml")
    links: list[str] = []
    for a in soup.find_all("a", href=True):
        url = urljoin(base_url, str(a["href"]).split("#")[0])
        if ARCHIVE_FILE.search(urlsplit(url).path) and url not in links:
            links.append(url)
    return links


# ---------------------------------------------------------------------------
# Snapshots (named <stamp>-<label>.html, never overwritten)
# ---------------------------------------------------------------------------


def _snapshot_path(directory: Path, stamp: str, label: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    candidate = directory / f"{stamp}-{label}.html"
    if not candidate.exists():
        return candidate
    seconds = common.utc_now().strftime("%S")
    candidate = directory / f"{stamp}{seconds}-{label}.html"
    n = 1
    while candidate.exists():
        candidate = directory / f"{stamp}{seconds}-{n}-{label}.html"
        n += 1
    return candidate


def write_named_snapshot(label: str, fetched: Fetched, *, extra_meta: dict | None = None) -> Path:
    """Like common.write_snapshot but keeps the page label in the file name."""
    path = _snapshot_path(RAW_DIR / SOURCE, utc_stamp(), label)
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
        "user_agent": USER_AGENT,
        "page_slug": label,
    }
    if extra_meta:
        meta.update(extra_meta)
    Path(f"{path}.meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    log.info(
        "snapshot %s (%d bytes, sha256 %s)",
        path.relative_to(PROJECT_ROOT),
        len(fetched.content),
        fetched.sha256[:12],
    )
    return path


def latest_snapshots() -> dict[str, tuple[Path, dict]]:
    """{page_slug: (html path, meta)} using the newest snapshot of each page."""
    out: dict[str, tuple[Path, dict]] = {}
    directory = RAW_DIR / SOURCE
    if not directory.exists():
        return out
    for meta_path in sorted(directory.glob("*.html.meta.json")):
        try:
            meta = json.loads(meta_path.read_text())
        except json.JSONDecodeError:
            continue
        slug = meta.get("page_slug")
        html_path = meta_path.with_name(meta_path.name.removesuffix(".meta.json"))
        if slug and html_path.exists():
            prior = out.get(slug)
            if prior is None or meta.get("fetched_at", "") >= prior[1].get("fetched_at", ""):
                out[slug] = (html_path, meta)
    return out


def collect(*, force: bool) -> list[str]:
    """Fetch the index and every monthly page, snapshotting new content. Returns archive URLs."""
    index = fetch(INDEX_URL)
    hashes = known_hashes(SOURCE)
    if force or index.sha256 not in hashes:
        write_named_snapshot("index", index)
    else:
        log.info("index unchanged (sha256 %s), no new snapshot", index.sha256[:12])
    pages = discover_pages(index.text, index.final_url)
    archives = discover_archive_links(index.text, index.final_url)
    log.info("found %d monthly pages and %d archive files", len(pages), len(archives))
    for slug, url in pages.items():
        page = fetch(url)
        hashes = known_hashes(SOURCE)
        if force or page.sha256 not in hashes:
            write_named_snapshot(slug, page)
        else:
            log.info("%s unchanged (sha256 %s), no new snapshot", slug, page.sha256[:12])
    return archives


# ---------------------------------------------------------------------------
# Detail table parsing
# ---------------------------------------------------------------------------

LABELS = {
    "service": "service",
    "service approval number": "se",
    "approved provider name": "provider",
    "approved provider number": "pr",
}
LABEL_LINE = re.compile(r"^(?P<label>[A-Za-z][A-Za-z ,/()'-]{1,60}?)\s*:\s*(?P<value>.*)$")
ADDRESS_TAIL = re.compile(
    r"^(?P<rest>.*),\s*(?P<state>VIC|NSW|QLD|SA|WA|TAS|NT|ACT)\s*,?\s*(?P<postcode>\d{4})\s*$",
    re.IGNORECASE,
)
ENTITY_MARKER = re.compile(
    r"\b(pty|ltd|limited|inc|incorporated|council|association|co-?operative|trust|foundation|"
    r"school|college|church|university|institute|department|corporation|company|society|"
    r"kindergarten|centre|center|care|learning|education|services|group|australia|"
    r"limited partnership|ymca|ywca|shire|city of|trustee)\b",
    re.IGNORECASE,
)
HONORIFIC_NAME = re.compile(
    r"\b(?:Mr|Mrs|Ms|Miss|Mx|Dr|Prof)\.?\s+[A-Z][A-Za-z'’-]+(?:\s+[A-Z][A-Za-z'’-]+){0,2}"
)
PERSON_LABELS = re.compile(
    r"nominated supervisor|educator name|person|individual|staff member|volunteer|"
    r"responsible person|certified supervisor|name of",
    re.IGNORECASE,
)
LEGAL_REF = re.compile(
    r"\b(?:Sections?|Regulations?)(?:\s+on)?\s+\d+[A-Z]*(?:\([A-Za-z0-9]+\))*",
    re.IGNORECASE,
)


def cell_lines(cell: Tag) -> list[str]:
    """Text of a cell as lines, splitting on <br> and block elements."""
    clone = BeautifulSoup(str(cell), "lxml")
    for br in clone.find_all("br"):
        br.replace_with("\n")
    for block in clone.find_all(["p", "li", "div", "ul", "ol"]):
        block.insert_before("\n")
        block.insert_after("\n")
    text = clone.get_text()
    return [clean(line) for line in text.split("\n") if clean(line)]


def split_address(address: str | None) -> tuple[str | None, str | None, str | None]:
    """(suburb, state, postcode) from '28 Laurel Cres, Campbellfield, Vic, 3061'; else nulls."""
    if not address:
        return None, None, None
    m = ADDRESS_TAIL.match(address)
    if not m:
        return None, None, None
    rest_parts = [p.strip() for p in m.group("rest").split(",") if p.strip()]
    suburb = rest_parts[-1] if len(rest_parts) >= 2 else None
    return suburb, m.group("state").upper(), m.group("postcode")


def parse_details_cell(cell: Tag) -> dict:
    """Split the packed first cell into service, address and approval numbers."""
    lines = cell_lines(cell)
    fields: dict[str, str] = {}
    address_lines: list[str] = []
    dropped_person_fields = 0
    current: str | None = None
    for line in lines:
        m = LABEL_LINE.match(fold_dashes(line))
        label = clean(m.group("label")).lower() if m else None
        if m and label in LABELS:
            current = LABELS[label]
            fields[current] = clean(line.split(":", 1)[1])
            continue
        if m and PERSON_LABELS.search(label or ""):
            # Person-level field: dropped at ingest, counted only.
            dropped_person_fields += 1
            current = "_person"
            continue
        if current == "service":
            address_lines.append(line)
        elif current == "_person":
            continue
        elif current in {"se", "pr", "provider"} and not fields.get(current):
            fields[current] = line
        elif current is None:
            address_lines.append(line)
    address = clean(", ".join(address_lines)) or None
    suburb, state, postcode = split_address(address)
    se_raw = fields.get("se") or None
    pr_raw = fields.get("pr") or None
    return {
        "service_name": fields.get("service") or None,
        "address": address,
        "suburb": suburb,
        "state": state,
        "postcode": postcode,
        "service_approval_number_raw": se_raw,
        "service_approval_number": normalise_se(se_raw),
        "provider_approval_number_raw": pr_raw,
        "provider_approval_number": normalise_pr(pr_raw),
        "provider_name": fields.get("provider") or None,
        "dropped_person_fields": dropped_person_fields,
    }


def extract_legal_references(text: str | None) -> list[str]:
    """Section and regulation citations as printed, de-duplicated in order of appearance."""
    refs: list[str] = []
    for m in LEGAL_REF.finditer(text or ""):
        ref = clean(re.sub(r"\s+on\s+", " ", m.group(0), flags=re.IGNORECASE))
        if ref not in refs:
            refs.append(ref)
    return refs


def strip_personal_names(text: str | None) -> tuple[str | None, int]:
    """Replace titled personal names (for example 'Ms Jane Citizen') and count removals."""
    if not text:
        return text, 0
    cleaned, n = HONORIFIC_NAME.subn("[name removed]", text)
    return cleaned, n


def reason_text(cell: Tag) -> str | None:
    """Reason cell as one line: intro sentence, then list items separated by '; '."""
    lines = cell_lines(cell)
    if not lines:
        return None
    items = [ln.lstrip("• ").strip() for ln in lines]
    head = items[0]
    rest = [i for i in items[1:] if i]
    if not rest:
        return head
    return f"{head} " + "; ".join(rest)


def map_action_type(raw: str) -> str:
    """Conservative mapping to the schema enum. Ambiguous or unknown text maps to 'other'."""
    text = fold_dashes(raw).lower()
    hits: set[str] = set()
    if "direction to suspend" in text:
        hits.add("direction_to_exclude")
    elif "suspension" in text or "suspend" in text:
        hits.add("approval_suspended")
    if "compliance notice" in text:
        hits.add("compliance_notice")
    if "compliance direction" in text:
        hits.add("compliance_direction")
    if "emergency action" in text:
        hits.add("emergency_action_notice")
    if "enforceable undertaking" in text:
        hits.add("enforceable_undertaking")
    if "prohibition" in text:
        hits.add("prohibition_notice")
    if "show cause" in text:
        hits.add("show_cause_notice")
    if "prosecution" in text:
        hits.add("prosecution")
    if "infringement" in text:
        hits.add("infringement_notice")
    if "cancel" in text:
        hits.add("approval_cancelled")
    if "amend" in text:
        hits.add("approval_amended")
    if "condition" in text:
        hits.add("condition_imposed")
    return hits.pop() if len(hits) == 1 else "other"


def header_texts(table: Tag) -> list[str]:
    first = table.find("tr")
    if first is None:
        return []
    return [clean(c.get_text(" ")) for c in first.find_all(["th", "td"])]


def find_tables(soup: BeautifulSoup) -> tuple[Tag | None, Tag | None]:
    """(summary table, detail table) identified by header text."""
    summary = detail = None
    for table in soup.find_all("table"):
        heads = " ".join(header_texts(table)).lower()
        if "compliance action type" in heads and summary is None:
            summary = table
        elif "reason for enforcement action" in heads and detail is None:
            detail = table
    return summary, detail


def parse_actions(
    html: str,
    *,
    source_document: str,
    captured_at: str,
    period_label: str,
    source_snapshot: str | None = None,
) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    _, detail = find_tables(soup)
    if detail is None:
        log.warning("no detail table in %s", source_document)
        return []
    rows: list[dict] = []
    for tr in detail.find_all("tr"):
        cells = tr.find_all("td")
        if len(cells) < 4:
            continue
        info = parse_details_cell(cells[0])
        action_raw = clean(cells[1].get_text(" "))
        reason = reason_text(cells[2])
        reason, names_in_reason = strip_personal_names(reason)
        date_raw = clean(cells[3].get_text(" ")) or None
        date_iso = parse_date(date_raw)
        refs = extract_legal_references(reason)

        notes: list[str] = []
        stripped = info.pop("dropped_person_fields") + names_in_reason
        if stripped:
            notes.append(f"{stripped} personal name or person field(s) removed at ingest")
        if info["service_approval_number"] is None:
            notes.append("service approval number missing or unparsable; set to null")
        if info["provider_approval_number"] is None:
            notes.append("provider approval number missing or unparsable; set to null")
        if date_raw and date_iso is None:
            notes.append(f"date not parsable: {date_raw!r}")
        if not date_raw:
            notes.append("date missing")
        if info["provider_name"] and (
            not ENTITY_MARKER.search(info["provider_name"])
            or name_is_withheld(info["provider_name"])
        ):
            # Likely a sole trader approved in their own name, or a name the shared fail-closed
            # rule does not accept as an organisation. Rule 2: never name individuals.
            info["provider_name"] = None
            notes.append(
                "provider name withheld: no company or organisation marker, may be an individual"
            )
        if "children's services act" in fold_apostrophes(reason or "").lower():
            notes.append("action cites the Children's Services Act; references are to that Act")
        if info["address"] and info["state"] is None:
            notes.append("address not separable into suburb, state and postcode")
        if not refs:
            notes.append("no legal reference found in reason")

        key = info["service_approval_number"] or info["provider_approval_number"]
        rows.append(
            {
                "record_id": record_hash("VIC", key, action_raw, date_raw, reason),
                "jurisdiction": JURISDICTION,
                "source_register": INDEX_URL,
                "source_document": source_document,
                "source_snapshot": source_snapshot,
                "captured_at": captured_at,
                **info,
                "action_type": map_action_type(action_raw),
                "action_type_raw": action_raw,
                "reason": reason,
                "legal_references": json.dumps(refs, ensure_ascii=False),
                "date_issued": date_iso,
                "date_issued_raw": date_raw,
                "period_label": period_label,
                "notes": " | ".join(notes) if notes else None,
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Summary count table
# ---------------------------------------------------------------------------


def parse_count(raw: str) -> int | None:
    """'318' -> 318; '-' (a dash printed for nil) -> 0; blank or other text -> None."""
    text = fold_dashes(clean(raw))
    if re.fullmatch(r"\d[\d,]*", text):
        return int(text.replace(",", ""))
    if text == "-":
        return 0
    return None


def parse_counts(
    html: str,
    *,
    source_document: str,
    captured_at: str,
    page_period_label: str,
    source_snapshot: str | None = None,
) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    summary, _ = find_tables(soup)
    if summary is None:
        log.warning("no summary table in %s", source_document)
        return []
    heads = header_texts(summary)
    period_labels = [h or page_period_label for h in heads[1:]] or [page_period_label]
    out: list[dict] = []
    section: str | None = None
    for tr in summary.find_all("tr")[1:]:
        cells = tr.find_all(["td", "th"])
        if not cells:
            continue
        label = clean(cells[0].get_text(" "))
        values = [clean(c.get_text(" ")) for c in cells[1:]]
        if not label:
            continue
        is_bold = cells[0].find(["strong", "b"]) is not None
        if is_bold and all(v == "" for v in values):
            section = label
            continue
        for i, period in enumerate(period_labels):
            raw = values[i] if i < len(values) else ""
            out.append(
                {
                    "period_label": period,
                    "action_type_raw": label,
                    "count": parse_count(raw),
                    "source_document": source_document,
                    "captured_at": captured_at,
                    "count_raw": raw,
                    "section": None if label.lower() == "grand total" else section,
                    "page_period_label": page_period_label,
                    "source_snapshot": source_snapshot,
                }
            )
    return out


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def mark_duplicates(rows: list[dict]) -> int:
    seen: dict[str, int] = {}
    dupes = 0
    for row in rows:
        rid = row["record_id"]
        seen[rid] = seen.get(rid, 0) + 1
        if seen[rid] > 1:
            dupes += 1
            extra = "duplicate record_id within the register; row kept"
            row["notes"] = f"{row['notes']} | {extra}" if row["notes"] else extra
    return dupes


def write_counts(rows: list[dict], raw_inputs: list[Path]) -> Path:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    out = PROCESSED_DIR / f"{COUNTS_NAME}.csv"
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COUNT_FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {k: ("" if row.get(k) is None else row.get(k)) for k in COUNT_FIELDNAMES}
            )
    provenance = {
        "output": out.relative_to(PROJECT_ROOT).as_posix(),
        "written_at": common.utc_now().isoformat(),
        "rows": len(rows),
        "schema": None,
        "raw_inputs": [p.relative_to(PROJECT_ROOT).as_posix() for p in raw_inputs],
        "notes": (
            "Summary table counts of all compliance actions by type per period, as printed. "
            "count_raw keeps the printed cell; a printed dash is read as 0 [Verify This]. "
            "Administrative actions (caution and compliance report letters) are counted here "
            "but their details are not published, so counts exceed published rows."
        ),
    }
    (PROCESSED_DIR / f"{COUNTS_NAME}.provenance.json").write_text(
        json.dumps(provenance, indent=2) + "\n"
    )
    log.info("processed %s (%d rows)", out.relative_to(PROJECT_ROOT), len(rows))
    return out


def parse_all() -> tuple[list[dict], list[dict], list[Path]]:
    snaps = latest_snapshots()
    action_rows: list[dict] = []
    count_rows: list[dict] = []
    inputs: list[Path] = []
    month_snaps = {slug: v for slug, v in snaps.items() if slug not in {"index", SUMMARY_SLUG}}
    # Chronological order: by year then by first month named in the slug.
    order = {m: i for i, m in enumerate(MONTHS.split("|"))}

    def sort_key(slug: str) -> tuple[int, int]:
        parts = slug.split("-")
        return int(parts[-1]), order.get(parts[0], 99)

    for slug in sorted(month_snaps, key=sort_key):
        path, meta = month_snaps[slug]
        html = path.read_text(encoding="utf-8", errors="replace")
        rel = path.relative_to(PROJECT_ROOT).as_posix()
        label = slug_to_label(slug)
        kwargs = {
            "source_document": meta["url"],
            "captured_at": meta["fetched_at"],
            "source_snapshot": rel,
        }
        rows = parse_actions(html, period_label=label, **kwargs)
        counts = parse_counts(html, page_period_label=label, **kwargs)
        log.info("%s: %d detailed rows, %d count rows", slug, len(rows), len(counts))
        action_rows.extend(rows)
        count_rows.extend(counts)
        inputs.append(path)
    if SUMMARY_SLUG in snaps:
        path, meta = snaps[SUMMARY_SLUG]
        counts = parse_counts(
            path.read_text(encoding="utf-8", errors="replace"),
            source_document=meta["url"],
            captured_at=meta["fetched_at"],
            page_period_label="Summary table comparison",
            source_snapshot=path.relative_to(PROJECT_ROOT).as_posix(),
        )
        log.info("%s: %d count rows", SUMMARY_SLUG, len(counts))
        count_rows.extend(counts)
        inputs.append(path)
    if "index" in snaps:
        inputs.append(snaps["index"][0])
    return action_rows, count_rows, inputs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--force", action="store_true", help="write new snapshots even if unchanged")
    ap.add_argument("--skip-fetch", action="store_true", help="parse existing snapshots only")
    args = ap.parse_args(argv)

    archives: list[str] = []
    if not args.skip_fetch:
        archives = collect(force=args.force)
    else:
        snaps = latest_snapshots()
        if "index" in snaps:
            archives = discover_archive_links(
                snaps["index"][0].read_text(encoding="utf-8", errors="replace")
            )
    for url in archives:
        log.info("archive file NOT fetched (robots.txt disallows): %s", url)

    action_rows, count_rows, inputs = parse_all()
    if not action_rows and not count_rows:
        log.error("no monthly snapshots to parse")
        return 1
    dupes = mark_duplicates(action_rows)
    null_se = sum(1 for r in action_rows if r["service_approval_number"] is None)
    for r in action_rows:
        if r["service_approval_number"] is None:
            log.warning("null SE key: %s %s %s", r["period_label"], r["service_name"], r["notes"])
    write_processed(
        ACTIONS_NAME,
        action_rows,
        FIELDNAMES,
        raw_inputs=inputs,
        schema=SCHEMA_PATH,
        notes=(
            "VECRA published enforcement actions under the National Law, parsed from monthly "
            "HTML pages. Latest snapshot of each page. CC BY 4.0, (c) State Government of "
            "Victoria. Historical years 2020 to 2025 are PDF/Word files disallowed by "
            "robots.txt and are not included. legal_references is a JSON array."
        ),
    )
    write_counts(count_rows, inputs)
    log.info(
        "pages parsed: %d; rows: %d; null SE-: %d; duplicate ids: %d; archive files unfetched: %d",
        len(
            {r["source_document"] for r in action_rows} | {r["source_document"] for r in count_rows}
        ),
        len(action_rows),
        null_se,
        dupes,
        len(archives),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
