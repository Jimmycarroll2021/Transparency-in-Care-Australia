"""Fetch and parse the Commonwealth Child Care Subsidy (CCS) enforcement action register.

STATUS: UNTESTED AGAINST LIVE HTML. On 2026-10-29 education.gov.au closed every connection
from this project (HTTP/2 INTERNAL_ERROR with curl, "Server disconnected" with httpx, also for
/robots.txt), and returned HTTP 503 to the register-auditor the day before. No real page has
been captured, so the table structure below is a best guess from the register-auditor's search
snippet (columns: provider name, location, service type, type of sanction, conditions of
approval or grounds for sanction, date of effect, sometimes an end date). The parser therefore
maps columns by header text, not by position, and ignores tables it cannot recognise. Treat
every output row as unverified until a real snapshot has been parsed and checked by hand.
Licence for this host is also unconfirmed (research note section 4); do not republish.

Source: Department of Education (Cth), enforcement action register under section 199B of the
A New Tax System (Family Assistance) (Administration) Act 1999, rolling 12 months, plus the
"past registers" page. Links from the past-registers page to older registers are not followed
in this version.

Mapping: CCS approval suspensions, cancellations and conditions -> ccs_sanction; criminal
convictions -> prosecution; everything else (for example civil penalty orders) -> other, with
the printed text kept in action_type_raw. ABN and CCS identifiers found are written to notes as
"ccs_identifier: ..." because the schema has no column for them yet. Approval numbers are only
filled when a cell literally contains SE- or PR- plus eight digits.

Privacy: an individual's name is never stored. A provider cell with no legal-entity or business
word is treated as an individual: provider_name and identifiers are withheld and the note
"subject is an individual; name withheld" is added.

Run: python3 scrapers/parse_cth_ccs_enforcement.py [--skip-fetch]
Exit code 2 means the pages were unreachable and nothing was written.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

if __package__ in (None, ""):  # allow `python3 scrapers/parse_cth_ccs_enforcement.py`
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scrapers import common
from scrapers.common import (
    PROJECT_ROOT,
    RAW_DIR,
    fetch,
    list_snapshots,
    log,
    record_hash,
    write_processed,
)
from scrapers.parse_qld_enforcement import (
    INDIVIDUAL_NOTE,
    classify_subject,
    clean,
    contains_token,
    name_tokens,
)

SOURCE = "cth-ccs-enforcement"
JURISDICTION = "CTH"
CURRENT_URL = (
    "https://www.education.gov.au/early-childhood/providers/compliance-and-enforcement/"
    "enforcement-action-register"
)
PAST_URL = (
    "https://www.education.gov.au/early-childhood/providers/compliance-and-enforcement/"
    "enforcement-action-register/past-registers"
)
PAGES = {"current": CURRENT_URL, "past": PAST_URL}
SCHEMA_PATH = "data/schemas/enforcement-action.schema.json"
OUTPUT_NAME = "cth-ccs-enforcement-actions"

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

STATES = r"NSW|VIC|QLD|SA|WA|TAS|NT|ACT"

# Header text -> role. Order matters: first match wins.
_ROLES: list[tuple[str, re.Pattern]] = [
    (
        "id",
        re.compile(r"approval (id|number)|(provider|service|ccs).*\b(id|number)\b|\bid\b", re.I),
    ),
    ("abn", re.compile(r"\babn\b", re.I)),
    ("end_date", re.compile(r"end date|\bends?\b|expiry|expires|date (of )?(end|expiry)", re.I)),
    ("service_type", re.compile(r"service type|type of service|care type", re.I)),
    ("service", re.compile(r"service name|approved service|^service$|child care service", re.I)),
    ("grounds", re.compile(r"ground|condition|reason|detail|description|basis", re.I)),
    ("sanction", re.compile(r"sanction|action|enforcement|outcome|type of", re.I)),
    ("date", re.compile(r"date|effective|commence|start", re.I)),
    ("location", re.compile(r"location|state|suburb|postcode|address", re.I)),
    ("provider", re.compile(r"provider|entity|organisation|approved person|name", re.I)),
]

_ABN = re.compile(r"\bABN\b[:\s#.]*((?:\d[ ]?){11})", re.I)
_SE = re.compile(r"\bSE-\d{8}\b")
_PR = re.compile(r"\bPR-\d{8}\b")
_DATE_FORMATS = ("%d/%m/%Y", "%d/%m/%y", "%d %B %Y", "%d %b %Y", "%d-%m-%Y", "%Y-%m-%d")


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def header_role(text: str) -> str | None:
    for role, pattern in _ROLES:
        if pattern.search(text):
            return role
    return None


def parse_cth_date(raw: str) -> str | None:
    """Parse a printed day-precision date. Month-only or free text returns None."""
    text = clean(raw)
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def map_action_type(raw: str) -> tuple[str, str | None]:
    """Conservative mapping of the printed sanction text. Returns (action_type, note)."""
    low = raw.lower()
    if re.search(r"\b(lifted|withdrawn|ended|expired)\b", low):
        return "other", "printed text records the end of an earlier action; kept as other"
    if re.search(r"civil penalt", low):
        return "other", None
    if re.search(r"criminal|convict", low):
        return "prosecution", None
    if re.search(r"\b(suspen|cancel|condition)", low):
        return "ccs_sanction", None
    return "other", None


def parse_location(text: str) -> dict[str, str | None]:
    """Fill suburb, state, postcode only when the pattern is unambiguous."""
    out: dict[str, str | None] = {"address": None, "suburb": None, "state": None, "postcode": None}
    text = clean(text)
    if not text:
        return out
    if re.fullmatch(STATES, text):
        out["state"] = text
        return out
    m = re.fullmatch(rf"(?P<suburb>.+?),?\s+(?P<state>{STATES})(?:\s+(?P<pc>\d{{4}}))?", text)
    if m:
        out["suburb"], out["state"], out["postcode"] = m["suburb"], m["state"], m["pc"]
        return out
    out["address"] = text
    return out


def _table_header(table):
    """Return (roles, header texts, header row). The header is the first row with a th."""
    header_row = next((tr for tr in table.find_all("tr") if tr.find("th")), None)
    if header_row is None:
        return [], [], None
    texts = [clean(c.get_text(" ")) for c in header_row.find_all(["th", "td"])]
    return [header_role(t) for t in texts], texts, header_row


def _heading(table) -> str | None:
    node = table.find_previous(["h1", "h2", "h3", "h4", "caption"])
    text = clean(node.get_text(" ")) if node else ""
    return text or None


def parse_page(
    html: str,
    *,
    role: str,
    page_url: str,
    captured_at: str = "",
    source_snapshot: str = "",
) -> list[dict]:
    """Parse every recognisable register table on one page. role is 'current' or 'past'."""
    soup = BeautifulSoup(html, "lxml")
    rows: list[dict] = []
    for table in soup.find_all("table"):
        roles, header_texts, header_row = _table_header(table)
        if "provider" not in roles or not ({"sanction", "grounds"} & set(roles)):
            continue  # not a register table we recognise
        heading = _heading(table)
        period = f"{role} register" + (f", {heading}" if heading else "")
        for tr in table.find_all("tr"):
            if tr is header_row:
                continue
            cells = [clean(c.get_text(" ")) for c in tr.find_all(["td", "th"])]
            if not any(cells):
                continue
            row = _build_row(roles, header_texts, cells, period, page_url)
            if row is None:
                continue
            row["captured_at"] = captured_at
            row["source_snapshot"] = source_snapshot
            rows.append(row)
    seen: dict[str, int] = {}
    for row in rows:
        seen[row["record_id"]] = seen.get(row["record_id"], 0) + 1
        if seen[row["record_id"]] > 1:
            row["notes"] += "; duplicate record_id: another row has the same key fields"
    return rows


def _build_row(
    roles: list[str | None],
    header_texts: list[str],
    cells: list[str],
    period: str,
    page_url: str,
) -> dict | None:
    by_role: dict[str, str] = {}
    extras: list[tuple[str, str]] = []  # (header, value) for unmapped or repeated columns
    for i, value in enumerate(cells):
        role = roles[i] if i < len(roles) else None
        header = header_texts[i] if i < len(header_texts) else f"column {i + 1}"
        if role and role not in by_role:
            by_role[role] = value
        elif value:
            extras.append((header, value))

    provider_raw = by_role.get("provider", "")
    sanction_raw = by_role.get("sanction", "") or by_role.get("grounds", "")
    if not provider_raw and not sanction_raw:
        return None

    notes: list[str] = []
    identifiers: list[str] = []
    candidates = [m.group(1) for m in _ABN.finditer(" ".join(cells))]
    abn_cell = by_role.get("abn", "").strip()
    if re.fullmatch(r"(?:\d ?){11}", abn_cell):
        candidates.append(abn_cell)
    for candidate in candidates:
        ident = "ABN " + re.sub(r"\s", "", candidate)
        if ident not in identifiers:
            identifiers.append(ident)
    if by_role.get("id"):
        identifiers.append(f"{header_texts[roles.index('id')]} {by_role['id']}")

    # Approval numbers only when printed in full in the SE-/PR- form.
    blob = " ".join(cells)
    se_raw = (_SE.search(blob) or [None])[0]
    pr_raw = (_PR.search(blob) or [None])[0]

    # Subject.
    provider_name: str | None = None
    if provider_raw:
        kind = classify_subject(provider_raw, has_service_line=True)
        if kind in {"entity", "service_only"}:
            provider_name = provider_raw
        else:
            notes.append(INDIVIDUAL_NOTE)
            if identifiers:
                notes.append("identifiers withheld because the subject is an individual")
                identifiers = []
            se_raw = pr_raw = None
            tokens = name_tokens(provider_raw) if kind == "individual" else set()
            for key in ("service", "grounds"):
                if tokens and by_role.get(key) and contains_token(by_role[key], tokens):
                    by_role[key] = ""
                    notes.append(
                        f"{key} text withheld: it repeated a word from the individual's name"
                    )
    else:
        notes.append("provider name not printed")

    for ident in identifiers:
        notes.append(f"ccs_identifier: {ident}")

    action_type, type_note = map_action_type(sanction_raw)
    if type_note:
        notes.append(type_note)

    date_raw = by_role.get("date", "")
    date_issued = parse_cth_date(date_raw) if date_raw else None
    if date_raw and not date_issued:
        notes.append(f"date not parsable: {date_raw!r}")
    if by_role.get("end_date"):
        notes.append(f"end_date: {by_role['end_date']}")
    if by_role.get("service_type"):
        notes.append(f"service_type: {by_role['service_type']}")
    if not (se_raw or pr_raw):
        notes.append("register prints no SE-/PR- number in this row")

    loc = parse_location(by_role.get("location", ""))
    if loc["address"]:
        notes.append(f"location as printed: {loc['address']}")
        loc["address"] = None
    if INDIVIDUAL_NOTE not in notes:
        for header, value in extras:
            notes.append(f"{header}: {value}")

    reason = by_role.get("grounds") or None
    service_name = by_role.get("service") or None

    return {
        "record_id": record_hash(
            JURISDICTION, provider_name, service_name, sanction_raw, date_raw, reason
        ),
        "jurisdiction": JURISDICTION,
        "source_register": CURRENT_URL,
        "source_document": page_url,
        "service_approval_number": se_raw,
        "service_approval_number_raw": se_raw,
        "provider_approval_number": pr_raw,
        "provider_approval_number_raw": pr_raw,
        "service_name": service_name,
        "provider_name": provider_name,
        "address": loc["address"],
        "suburb": loc["suburb"],
        "state": loc["state"],
        "postcode": loc["postcode"],
        "action_type": action_type,
        "action_type_raw": sanction_raw or "(not printed)",
        "reason": reason,
        "legal_references": [],
        "date_issued": date_issued,
        "date_issued_raw": date_raw or None,
        "period_label": period,
        "notes": "; ".join(notes) or None,
    }


# ---------------------------------------------------------------------------
# Snapshot and run
# ---------------------------------------------------------------------------


def write_page_snapshot(fetched: common.Fetched, stamp: str, role: str) -> Path:
    """Write <stamp>-<role>.html plus sidecar. Never overwrites."""
    path = common._unique_path(RAW_DIR / SOURCE, f"{stamp}-{role}", "html")
    path.write_bytes(fetched.content)
    meta = {
        "source": SOURCE,
        "role": role,
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
    }
    Path(f"{path}.meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    log.info("snapshot %s (%d bytes)", path.relative_to(PROJECT_ROOT), len(fetched.content))
    return path


def _latest_by_role() -> dict[str, Path]:
    latest: dict[str, Path] = {}
    for p in list_snapshots(SOURCE):
        if p.suffix != ".html":
            continue
        for role in PAGES:
            if p.stem.endswith(f"-{role}") or f"-{role}" in p.stem:
                latest[role] = p  # list is oldest first, so the newest wins
    return latest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--skip-fetch", action="store_true", help="parse the newest local snapshots")
    args = ap.parse_args(argv)

    paths: dict[str, Path] = {}
    if args.skip_fetch:
        paths = _latest_by_role()
    else:
        stamp = common.utc_stamp()
        for role, url in PAGES.items():
            try:
                fetched = fetch(url, retries=1)
            except (httpx.HTTPError, common.RobotsDisallowed) as exc:
                log.error("%s page unreachable: %r", role, exc)
                continue
            paths[role] = write_page_snapshot(fetched, stamp, role)

    if not paths:
        log.error("no Commonwealth pages available; nothing written")
        return 2

    rows: list[dict] = []
    for role, path in paths.items():
        meta_path = Path(f"{path}.meta.json")
        meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        rows.extend(
            parse_page(
                path.read_text(encoding="utf-8", errors="replace"),
                role=role,
                page_url=PAGES[role],
                captured_at=meta.get("fetched_at", ""),
                source_snapshot=str(path.relative_to(PROJECT_ROOT)),
            )
        )
    missing = [r for r in PAGES if r not in paths]
    if missing:
        log.warning("pages not captured: %s", ", ".join(missing))
    if not rows:
        log.error("pages captured but no register table recognised; check the layout")
        return 1

    out_rows = [{**r, "legal_references": json.dumps(r["legal_references"])} for r in rows]
    write_processed(
        OUTPUT_NAME,
        out_rows,
        FIELDNAMES,
        raw_inputs=list(paths.values()),
        schema=SCHEMA_PATH,
        notes=(
            "Parser written against a best-guess table structure; verify against the snapshot. "
            "ABN and CCS identifiers are in notes as 'ccs_identifier: ...'."
            + (f" Pages not captured: {', '.join(missing)}." if missing else "")
        ),
    )
    log.info("%d rows parsed from %s", len(rows), ", ".join(paths))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
