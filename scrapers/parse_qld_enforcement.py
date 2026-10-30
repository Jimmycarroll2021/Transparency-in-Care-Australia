"""Fetch and parse the Queensland register of published enforcement actions.

Source: Queensland Department of Education, Early Childhood Education and Care regulatory
authority. Licence: CC BY 4.0 by default on qed.qld.gov.au (see
research/2026-10-29-register-enforcement-nsw-vic-qld-cth.md section 3; confirmation that the
statement covers earlychildhood.qld.gov.au is still open).
Attribution: State of Queensland (Department of Education) 2026.

The register is one HTML page with a table per year. Columns: "Provider or individual name /
Service name", "Date of action", "Details", "Breaches (if applicable)". It prints NO service
or provider approval numbers, so those columns are always null here and the join to ACECQA
must be made by name and location.

Privacy: the first column can name natural persons (fined educators, sole-trader providers).
Individual names are never stored. For such rows provider_name is null, the linked document
URLs (whose file names usually embed the person's name) are withheld, and a service name is
kept only when it shares no word with the withheld name. Every other text column of a withheld
row (action text, reason, legal references, notes) has each word of the name redacted. Because
the page gives no explicit flag, a printed name with no legal-entity or business word in it is
treated as an individual, and so is any name profile_providers.classify_entity_form classes as
likely_individual (an individual trustee, a deceased estate or executor, an accented personal
name) even when it carries a word such as 'trust'. That errs towards withholding; it can wrongly
withhold an entity with an unusual name.

Linked documents are NOT downloaded in this version.

Run: python3 scrapers/parse_qld_enforcement.py [--skip-fetch] [--force]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

if __package__ in (None, ""):  # allow `python3 scrapers/parse_qld_enforcement.py`
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scrapers.common import (
    PROJECT_ROOT,
    RAW_DIR,
    assign_record_ids,
    fetch,
    list_snapshots,
    log,
    normalise_pr,
    normalise_se,
    printed_fingerprint,
    withhold_free_text,
    withhold_prose_naming_people,
    write_processed,
    write_snapshot,
)
from scrapers.profile_providers import classify_entity_form, name_is_withheld

SOURCE = "qld-enforcement"
JURISDICTION = "QLD"
INDEX_URL = (
    "https://earlychildhood.qld.gov.au/regulation/compliance-and-enforcement/"
    "register-published-enforcement-actions"
)
SCHEMA_PATH = "data/schemas/enforcement-action.schema.json"
OUTPUT_NAME = "qld-enforcement-actions"

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
    # Extra column, not in the schema: every other URL linked from the Details cell.
    "linked_documents",
    # Structured fact taken from the printed headline before any free text is withheld.
    "penalty_amount_aud",
]

NO_APPROVAL_NOTE = "register prints no approval number; join by name and address"
INDIVIDUAL_NOTE = "subject is an individual; name withheld"

_INVISIBLE = re.compile(r"[​‌‍⁠﻿]")
_DOC_EXT = (".pdf", ".docx", ".doc")
_STOPWORDS = {"and", "the", "of", "for", "pty", "ltd"}

# Words that mark a legal entity.
_LEGAL = re.compile(
    r"\b(pty|ltd|limited|proprietary|inc|incorporated|association|trust|trustee|trustees|"
    r"corporation|council|company|co-operative|cooperative|foundation|society|college|"
    r"school|university|atf|holdings|p&c)\b|\(qld\)",
    re.IGNORECASE,
)
# Words that mark a business or service name rather than a person.
_BUSINESS = re.compile(
    r"\b(kindergarten|childcare|child care|care|learning|education|educational|centre|centres|"
    r"center|early|kids|kindy|preschool|school hours|day care|services|group|church|network)\b",
    re.IGNORECASE,
)
# Generic role descriptors the register prints instead of a name.
_ROLE_PREFIX = re.compile(
    r"^(individual|educator|nominated supervisor|certified supervisor|supervisor|"
    r"family day care educator)\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------


def clean(text: str | None) -> str:
    """Strip zero-width characters, normalise spaces. Keeps printed punctuation."""
    if not text:
        return ""
    text = _INVISIBLE.sub("", text.replace("\xa0", " "))
    return re.sub(r"\s+", " ", text).strip()


def pieces(cell) -> list[str]:
    """Visible text fragments of a cell, in order, cleaned, blanks dropped."""
    return [c for c in (clean(s) for s in cell.stripped_strings) if c]


_FINED = re.compile(r"(?i)(?<![a-z])fined(?![a-z])")
_DOLLARS = re.compile(r"[$][ ]?([0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:[.]([0-9]{2}))?(?![0-9])")


def extract_fine_amount(text: str | None) -> int | float | None:
    """The fine in a printed headline such as 'Approved provider fined $12,000 ...', in dollars.

    Source-faithful: only when the text says 'fined' and prints exactly one distinct dollar
    amount. Anything else (no amount, several amounts) is None, never a guess."""
    if not text or not _FINED.search(text):
        return None
    amounts = set()
    for m in _DOLLARS.finditer(text):
        whole = int(m.group(1).replace(",", ""))
        amounts.add(whole + int(m.group(2)) / 100 if m.group(2) else whole)
    return amounts.pop() if len(amounts) == 1 else None


def parse_date(raw: str) -> tuple[str | None, str | None]:
    """d/m/y (Queensland style) -> (ISO date, warning). Two-digit years are read as 20yy."""
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})", raw.strip())
    if not m:
        return None, f"date not parsable: {raw!r}"
    day, month, year = int(m.group(1)), int(m.group(2)), m.group(3)
    warning = None
    if len(year) == 2:
        year_i = 2000 + int(year)
        warning = f"two-digit year {raw!r} read as {year_i}"
    else:
        year_i = int(year)
    try:
        return date(year_i, month, day).isoformat(), warning
    except ValueError:
        return None, f"date not valid: {raw!r}"


# ---------------------------------------------------------------------------
# Subject classification (entity or individual)
# ---------------------------------------------------------------------------


def classify_subject(first: str, *, has_service_line: bool) -> str:
    """Return 'role', 'individual', 'entity' or 'service_only' for the first printed name.

    role          generic descriptor such as 'Educator - centre-based service' (no name printed)
    individual    printed name with no legal or business marker (treated as a natural person)
    entity        legal-entity name, or a business-like name in the provider position
    service_only  single business-like name with no legal marker (probably a service name)
    """
    if _ROLE_PREFIX.match(first):
        return "role"
    # Person signals beat legal and business words: '<person> ATF <trust>', a deceased estate
    # or its executors, and accented personal names are individuals.
    if classify_entity_form(first) == "likely_individual":
        return "individual"
    if _LEGAL.search(first) or (_BUSINESS.search(first) and has_service_line):
        # A provider name is kept only when the shared fail-closed rule accepts it.
        return "individual" if name_is_withheld(first) else "entity"
    if _BUSINESS.search(first):
        return "service_only"
    return "individual"


# A word of any letters, accented ones included ('Zoë' must not split into 'Zo' and 'e').
_WORD = re.compile(r"[^\W\d_](?:[^\W\d_]|['’\-])+")


def name_tokens(name: str) -> set[str]:
    words = _WORD.findall(name.lower())
    return {w.strip("'’-") for w in words if len(w) >= 3 and w not in _STOPWORDS}


def contains_token(text: str, tokens: set[str]) -> bool:
    found = {w.strip("'’-") for w in _WORD.findall(text.lower())}
    return bool(found & tokens)


# ---------------------------------------------------------------------------
# Action type mapping (conservative)
# ---------------------------------------------------------------------------


def map_action_type(raw: str, *, prosecution_label: bool) -> tuple[str, str | None]:
    """Map the printed Details text to the schema enum. Returns (action_type, note)."""
    low = raw.lower()
    # Events that undo or close an earlier action are not new actions of that kind.
    if re.search(r"\b(lifted|discharged|revoked|withdrawn|ended|expired)\b", low):
        return "other", "printed text records the end of an earlier action; kept as other"
    if prosecution_label:
        return "prosecution", None
    if "infringement notice" in low:
        return "infringement_notice", None
    if re.search(r"\bcancellation\b|\bcancelled\b", low):
        return "approval_cancelled", None
    if re.search(r"\bsuspension\b|\bsuspended\b", low):
        return "approval_suspended", None
    if "emergency action notice" in low:
        return "emergency_action_notice", None
    if "compliance notice" in low:
        return "compliance_notice", None
    if "compliance direction" in low:
        return "compliance_direction", None
    if "enforceable undertaking" in low:
        return "enforceable_undertaking", None
    if "show cause" in low:
        return "show_cause_notice", None
    if "prohibition notice" in low:
        return "prohibition_notice", None
    if "direction to exclude" in low:
        return "direction_to_exclude", None
    if re.search(r"\bconditions?\b", low):
        return "condition_imposed", None
    if re.search(r"\b(fine|fined|penalty)\b", low):
        return "other", "fine printed without a Prosecution or infringement notice label"
    return "other", None


# ---------------------------------------------------------------------------
# Table parsing
# ---------------------------------------------------------------------------


def _is_register_table(table) -> bool:
    first = table.find("tr")
    return bool(first and "date of action" in clean(first.get_text(" ")).lower())


def _period_label(table) -> str | None:
    heading = table.find_previous(["h1", "h2", "h3", "h4", "h5"])
    text = clean(heading.get_text(" ")) if heading else ""
    return text if re.fullmatch(r"(19|20)\d{2}", text) else None


def parse_row(tr, *, period: str | None, page_url: str) -> dict | None:
    cells = tr.find_all(["td", "th"])
    if len(cells) < 4:
        log.warning("row with %d cells skipped", len(cells))
        return None
    name_parts = pieces(cells[0])
    date_raw = clean(cells[1].get_text(" "))
    details = cells[2]
    breach_parts = pieces(cells[3])
    if not name_parts and not date_raw:
        return None

    # Details: headline is the first paragraph, or the cell text when there are no paragraphs.
    link_labels = [clean(a.get_text(" ")) for a in details.find_all("a")]
    link_labels = [t for t in link_labels if t]
    paras = [clean(p.get_text(" ")) for p in details.find_all("p")]
    paras = [p for p in paras if p]
    prosecution_label = any(t.lower() == "prosecution" for t in link_labels)
    labels = [t for t in link_labels if t.lower() != "further information"]
    if paras and paras[0].lower() not in {"prosecution", "further information"}:
        headline = paras[0]
        extra_labels = [t for t in labels if t != headline]
    else:
        headline = labels[0] if labels else clean(details.get_text(" "))
        extra_labels = labels[1:]
    action_type_raw = " ".join([headline, *extra_labels]).strip()
    action_type, type_note = map_action_type(action_type_raw, prosecution_label=prosecution_label)
    reason = headline if extra_labels else None

    # Linked documents (PDF preferred as the primary source document).
    hrefs: list[str] = []
    for a in details.find_all("a", href=True):
        url = urljoin(page_url, a["href"].strip().replace(" ", "%20"))
        if url.startswith("https://") and url not in hrefs:
            hrefs.append(url)
    docs = [u for u in hrefs if urlsplit(u).path.lower().endswith(_DOC_EXT)]
    pdfs = [u for u in docs if urlsplit(u).path.lower().endswith(".pdf")]
    primary = (pdfs or docs or hrefs or [page_url])[0]

    notes = [NO_APPROVAL_NOTE]
    if type_note:
        notes.append(type_note)

    # Subject.
    first = name_parts[0] if name_parts else ""
    service_parts = name_parts[1:]
    kind = classify_subject(first, has_service_line=bool(service_parts))
    provider_name: str | None = None
    service_name: str | None = None
    tokens: set[str] = set()
    withheld_markers: list[str] = []  # constant phrases only, never source text

    if kind == "entity":
        provider_name = first
        service_name = "; ".join(service_parts) if service_parts else None
        if len(service_parts) > 1:
            notes.append("several service lines printed; joined with '; ' in printed order")
    elif kind == "service_only":
        service_name = first
        notes.append(
            "one name printed with no legal-entity marker; treated as a service name and "
            "provider not stated"
        )
    else:  # role or individual: never store the name
        if kind == "individual":
            tokens = name_tokens(first)
            detail = (
                "printed name is not positively an organisation"
                if _LEGAL.search(first) or _BUSINESS.search(first)
                else "no legal-entity or business word in the printed name"
            )
            withheld_markers.append(f"{INDIVIDUAL_NOTE} ({detail})")
        else:
            withheld_markers.append(f"{INDIVIDUAL_NOTE} (register prints a generic role, no name)")
        if service_parts:
            candidate = "; ".join(service_parts)
            if tokens and contains_token(candidate, tokens):
                withheld_markers.append(
                    "service name withheld: it repeats a word from the individual's name"
                )
            else:
                service_name = candidate
        # File names of linked documents usually embed the person's name.
        if hrefs:
            withheld_markers.append(
                "linked document URLs withheld because file names can embed the name"
            )
        primary = page_url
        hrefs = []

    # Dates.
    date_issued, date_warning = parse_date(date_raw)
    if date_warning:
        notes.append(date_warning)
    if date_issued and period and date_issued[:4] != period:
        notes.append(f"date year {date_issued[:4]} differs from table heading {period}")

    # Breaches column -> legal references. 'N/A' means none printed.
    legal_references = [p for p in breach_parts if p.lower() not in {"n/a", "na", "-"}]
    if legal_references and not any(re.match(r"(NL|NR)\b", p) for p in legal_references):
        notes.append(f"breaches column printed: {'; '.join(legal_references)}")
        legal_references = []

    se_raw = pr_raw = None
    row = {
        "record_id": None,  # set by parse_register from non-name facts (assign_record_ids)
        "jurisdiction": JURISDICTION,
        "source_register": INDEX_URL,
        "source_document": primary,
        "service_approval_number": normalise_se(se_raw),
        "service_approval_number_raw": se_raw,
        "provider_approval_number": normalise_pr(pr_raw),
        "provider_approval_number_raw": pr_raw,
        "service_name": service_name,
        "provider_name": provider_name,
        "address": None,
        "suburb": None,
        "state": None,
        "postcode": None,
        "action_type": action_type,
        "action_type_raw": action_type_raw,
        "reason": reason,
        "legal_references": legal_references,
        "date_issued": date_issued,
        "date_issued_raw": date_raw or None,
        "period_label": period,
        "notes": "; ".join(notes),
        "linked_documents": " ".join(u for u in hrefs if u != primary) or None,
        "penalty_amount_aud": extract_fine_amount(action_type_raw),
        # In-memory only (not written): the printed content, names included, to spot a row the
        # register prints twice. Never published and never used as the record_id.
        "_fingerprint": printed_fingerprint(*(clean(c.get_text(" ")) for c in cells)),
    }
    if kind in ("individual", "role"):
        # Rule 2: free text can repeat the name in forms no redaction catches, so it is withheld
        # whole. Structured fields stay.
        withhold_free_text(row, (NO_APPROVAL_NOTE, *withheld_markers))
    return row


def parse_register(
    html: str,
    *,
    page_url: str = INDEX_URL,
    captured_at: str = "",
    source_snapshot: str = "",
) -> list[dict]:
    """Parse every register table in the page into schema rows."""
    soup = BeautifulSoup(html, "lxml")
    rows: list[dict] = []
    seen: dict[str, int] = {}  # printed-content fingerprint -> count
    for table in soup.find_all("table"):
        if not _is_register_table(table):
            continue
        period = _period_label(table)
        for tr in table.find_all("tr")[1:]:
            row = parse_row(tr, period=period, page_url=page_url)
            if row is None:
                continue
            row["captured_at"] = captured_at
            row["source_snapshot"] = source_snapshot
            seen[row["_fingerprint"]] = seen.get(row["_fingerprint"], 0) + 1
            if seen[row["_fingerprint"]] > 1:
                row["notes"] += "; duplicate row: another row prints the same text"
            rows.append(row)
    withhold_prose_naming_people(rows)  # shared prose rule, every row
    assign_record_ids(rows, source_id=page_url)
    return rows


# ---------------------------------------------------------------------------
# Snapshot and run
# ---------------------------------------------------------------------------


def _snapshot_meta(path: Path) -> dict:
    meta_path = Path(f"{path}.meta.json")
    return json.loads(meta_path.read_text()) if meta_path.exists() else {}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--skip-fetch", action="store_true", help="parse the newest local snapshot")
    ap.add_argument("--force", action="store_true", help="archive even if the page is unchanged")
    args = ap.parse_args(argv)

    if args.skip_fetch:
        snaps = [p for p in list_snapshots(SOURCE) if p.suffix == ".html"]
        if not snaps:
            log.error("no local snapshot under data/raw/%s", SOURCE)
            return 1
        path = snaps[-1]
        captured_at = _snapshot_meta(path).get("fetched_at", "")
    else:
        fetched = fetch(INDEX_URL)
        path = None
        if not args.force:
            for meta in sorted((RAW_DIR / SOURCE).glob("*.html.meta.json")):
                if json.loads(meta.read_text()).get("sha256") == fetched.sha256:
                    path = Path(str(meta)[: -len(".meta.json")])
            if path:
                log.info("page unchanged since %s; reusing that snapshot", path.name)
        if path is None:
            path = write_snapshot(SOURCE, fetched, "html")
        captured_at = fetched.fetched_at

    rel = str(path.relative_to(PROJECT_ROOT))
    rows = parse_register(
        path.read_text(encoding="utf-8", errors="replace"),
        page_url=INDEX_URL,
        captured_at=captured_at,
        source_snapshot=rel,
    )
    if not rows:
        log.error("no rows parsed; the page layout may have changed")
        return 1

    out_rows = [
        {**r, "legal_references": json.dumps(r["legal_references"], ensure_ascii=False)}
        for r in rows
    ]
    write_processed(
        OUTPUT_NAME,
        out_rows,
        FIELDNAMES,
        raw_inputs=[path],
        schema=SCHEMA_PATH,
        notes=(
            "Queensland register prints no SE-/PR- numbers. Individual names are withheld "
            "(provider_name null). legal_references is a JSON array. linked_documents is an "
            "extra column. Linked documents were not downloaded."
        ),
    )
    withheld = sum(1 for r in rows if INDIVIDUAL_NOTE in (r["notes"] or ""))
    log.info("%d rows parsed, %d with an individual subject (name withheld)", len(rows), withheld)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
