"""Fetch and parse the Commonwealth Child Care Subsidy (CCS) enforcement action register.

Source: Department of Education (Cth), enforcement action register under section 199B of the
A New Tax System (Family Assistance) (Administration) Act 1999: the current register (rolling
12 months) and the "past registers" page. Links from the past-registers page to older registers
are not followed in this version. Licence for this host is unconfirmed (research note
2026-10-29-register-enforcement-nsw-vic-qld-cth.md, section 4); do not republish.

Fetching: education.gov.au closes connections from non-browser clients. Save each page from a
browser and pass it with --current-file / --past-file; the script copies it into
data/raw/cth-ccs-enforcement/ as a timestamped snapshot with a sidecar. --skip-fetch re-parses
the newest local snapshots.

Page layout (checked against the 2026-10-29T0749Z snapshots): no tables. Inside <main>, an
<h1>, an "On this page:" <h2> with anchor links, then one <h2> per entry holding the service
name. Each entry carries <dt>label:</dt><dd>value</dd> pairs (Provider, Location, Service type,
Type of sanction, Conditions of approval or grounds for sanction, Date of effect, End date, and
for criminal outcomes Charge, Plea, Date charged, Date of sentence). The parser walks <main> in
document order, so it also copes with <strong>/<b> labels and plain "Label: value" text.

Mapping (action_type values follow the hub decision; action_type_raw keeps the printed text):
- cancellation, suspension, variation and conditions on approval, and civil penalty orders ->
  ccs_sanction
- conviction (including "Without Conviction", which is still a criminal outcome) -> prosecution
- infringement_notice only when the printed text says infringement notice
- anything else, and the end of an earlier action (lifted, withdrawn) -> other
- ABN goes to notes as "ccs_identifier: ABN <11 digits>"; service type to notes as
  "service_type: ...", because the schema has no column for either. SE-/PR- numbers are only
  filled when printed in full; this register does not print them.
- legal_references: every "section 19xX" token in the sanction and grounds text (a bare "197L"
  also counts), written as "section 197L".

Privacy (CLAUDE.md rule 2): if the Provider value has no organisation marker, or reads like a
person with a title, a joined pair of people, or "Name, trading name", provider_name is null, the
ABN is not kept (sole-trader ABNs identify the person), and notes say "provider name withheld;
subject is an individual". Over-withholding is the chosen failure direction. The service name is
also withheld if it repeats a word from the individual's name, and such words are redacted in the
grounds text. Names are never logged; only counts are.

Run: python3 scrapers/parse_cth_ccs_enforcement.py [--skip-fetch] [--current-file F]
     [--past-file F]
Exit code 2 means the pages were unreachable and nothing was written; 1 means pages were read
but no register entries were recognised.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

import httpx
from bs4 import BeautifulSoup, Tag

if __package__ in (None, ""):  # allow `python3 scrapers/parse_cth_ccs_enforcement.py`
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scrapers import common
from scrapers.common import (
    PROJECT_ROOT,
    RAW_DIR,
    assign_record_ids,
    fetch,
    list_snapshots,
    log,
    printed_fingerprint,
    withhold_free_text,
    withhold_prose_naming_people,
    write_processed,
)
from scrapers.parse_qld_enforcement import clean
from scrapers.profile_providers import name_is_withheld

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

WITHHELD_NOTE = "provider name withheld; subject is an individual"
DUPLICATE_NOTE = "duplicate row in source"

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
    # Structured facts from labelled fields, kept apart from the prose so that withholding
    # free text never deletes them. Source-faithful: null when not printed or not parsable.
    "service_type",
    "end_date",
    "date_charged",
    "date_of_sentence",
    "plea",
]

STATE_CODES = {"NSW", "VIC", "QLD", "SA", "WA", "TAS", "NT", "ACT"}
STATE_NAMES = {
    "new south wales": "NSW",
    "victoria": "VIC",
    "queensland": "QLD",
    "south australia": "SA",
    "western australia": "WA",
    "tasmania": "TAS",
    "northern territory": "NT",
    "australian capital territory": "ACT",
}

# Printed label (lower case, no colon) -> field key. Unknown labels are kept in notes.
LABELS = {
    "provider": "provider",
    "location": "location",
    "service type": "service_type",
    "type of sanction": "sanction",
    "conditions of approval or grounds for sanction": "grounds",
    "grounds for sanction": "grounds",
    "conditions of approval": "grounds",
    "date of effect": "date",
    "end date": "end_date",
    "charge": "charge",
    "plea": "plea",
    "date charged": "date_charged",
    "date of sentence": "date_sentence",
}
# Extra fields written to notes, in this order, as "<label>: <value>".
NOTE_FIELDS = [
    ("service_type", "service_type"),
    ("end_date", "end_date"),
    ("charge", "charge"),
    ("plea", "plea"),
    ("date_charged", "date_charged"),
    ("date_sentence", "date_of_sentence"),
]

# Labelled date fields kept as structured ISO columns: field key -> (column, printed label).
STRUCTURED_DATES = [
    ("end_date", "end_date", "end date"),
    ("date_charged", "date_charged", "date charged"),
    ("date_sentence", "date_of_sentence", "date of sentence"),
]
# Controlled vocabularies: a printed value outside them is not copied into a column.
SERVICE_TYPES = {
    "family day care": "Family Day Care",
    "centre based day care": "Centre Based Day Care",
    "outside school hours care": "Outside School Hours Care",
    "in home care": "In Home Care",
}
PLEAS = {"guilty": "Guilty", "not guilty": "Not guilty"}

_ABN = re.compile(r"\bABN\b\s*:?\s*(?:ABN\s*:?\s*)?((?:\d\s?){11})(?!\d)", re.I)
_ABN_TAIL = re.compile(r"\s*[–—-]?\s*(?:ABN\s*:?\s*)+[\d\s]*$", re.I)
_SE = re.compile(r"\bSE-\d{8}\b")
_PR = re.compile(r"\bPR-\d{8}\b")
_SECTION_PREFIXED = re.compile(r"\b(?:sections?|ss?)\.?\s*(19\d[A-Z]{0,2})\b", re.I)
_SECTION_BARE = re.compile(r"\b(19\d[A-Z]{1,2})\b", re.I)
_DATE_FORMATS = ("%d %B %Y", "%d %b %Y", "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d")

# Subject classification. Strong markers identify a legal entity. Weak markers suggest a
# business but also occur in "Name, trading name" strings, so they only count when nothing
# joins several names together.
_TITLE = re.compile(r"\b(mr|mrs|ms|miss|dr)\b\.?", re.I)
_PARTNERSHIP_OF = re.compile(r"^\s*partnership\s+of\b", re.I)
_STRONG_WORDS = (
    "pty|ltd|limited|proprietary|inc|incorporated|association|trust|trustee|trustees|atf|"
    "co-operative|cooperative|council|church|foundation|corporation|corp|company|society|"
    "college|university|department|holdings|p&c"
)
_WEAK_WORDS = (
    "centre|centres|center|care|childcare|school|kindergarten|kindy|preschool|pre-school|"
    "services|service|group|australia|australian|education|educational|learning|"
    "day care|daycare"
)
_STRONG = re.compile(rf"(?<![\w-])({_STRONG_WORDS})(?![\w-])", re.I)
_WEAK = re.compile(rf"(?<![\w-])({_WEAK_WORDS})(?![\w-])", re.I)
_PERSON_JOIN = re.compile(r"[,;&]|\band\b|\baka\b|\bt/a\b", re.I)
_NOT_NAME_WORDS = (
    set(_STRONG_WORDS.split("|"))
    | set(_WEAK_WORDS.split("|"))
    | {"and", "the", "of", "for", "aka", "family", "day", "fdc", "mr", "mrs", "ms", "miss", "dr"}
)


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def parse_cth_date(raw: str) -> str | None:
    """Parse a printed day-precision date. Month-only or free text returns None."""
    text = clean(raw)
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def normalise_state(text: str) -> str | None:
    """'queensland', 'Tas', 'VIC' -> 'QLD', 'TAS', 'VIC'. Anything else -> None."""
    t = clean(text).strip(" .").lower()
    if t.upper() in STATE_CODES:
        return t.upper()
    return STATE_NAMES.get(t)


def parse_location(text: str) -> dict[str, str | None]:
    """'Gayndah, queensland' -> suburb Gayndah, state QLD. Never infers a missing state."""
    out: dict[str, str | None] = {"address": None, "suburb": None, "state": None, "postcode": None}
    text = clean(text)
    if not text:
        return out
    if "," in text:
        left, _, right = text.rpartition(",")
        state = normalise_state(right)
        if state is None:
            out["address"] = text
            return out
        left = clean(left)
        out["state"] = state
        if left and left.lower() != "not specified" and normalise_state(left) is None:
            out["suburb"] = left
        return out
    state = normalise_state(text)
    if state:
        out["state"] = state
    else:
        out["suburb"] = text
    return out


def map_action_type(raw: str) -> tuple[str, str | None]:
    """Conservative mapping of the printed sanction text. Returns (action_type, note)."""
    low = raw.lower()
    if re.search(r"\b(lifted|withdrawn|ended|expired|revoked)\b", low):
        return "other", "printed text records the end of an earlier action; kept as other"
    if re.search(r"conviction|criminal", low):
        note = "printed outcome is 'Without Conviction'" if "without conviction" in low else None
        return "prosecution", note
    if "infringement notice" in low:
        return "infringement_notice", None
    if re.search(
        r"civil penalt|cancel|suspen|condition|variation|varied|sanction under section", low
    ):
        return "ccs_sanction", None
    return "other", None


def extract_legal_references(*texts: str | None) -> list[str]:
    """Every 'section 19xX' / 's 19xX' token (and bare '197L'), as 'section 197L', in order."""
    found: list[tuple[int, str]] = []
    for text in texts:
        if not text:
            continue
        base = len(found) * 100000
        hits = [(m.start(), m.group(1)) for m in _SECTION_PREFIXED.finditer(text)]
        hits += [(m.start(), m.group(1)) for m in _SECTION_BARE.finditer(text)]
        found.extend((base + pos, num.upper()) for pos, num in sorted(hits))
    refs: list[str] = []
    for _, num in sorted(found):
        ref = f"section {num}"
        if ref not in refs:
            refs.append(ref)
    return refs


def split_abn(provider_raw: str) -> tuple[str, str | None, str | None]:
    """Return (provider text without the ABN part, 11-digit ABN or None, problem or None)."""
    m = _ABN.search(provider_raw)
    abn = re.sub(r"\s", "", m.group(1)) if m else None
    stripped = clean(_ABN_TAIL.sub("", provider_raw))
    problem = None
    if re.search(r"\bABN\b", provider_raw, re.I) and not abn:
        problem = (
            f"ABN printed but not 11 digits: {provider_raw[provider_raw.upper().find('ABN') :]!r}"
        )
        stripped = clean(re.sub(r"\s*[–—-]?\s*ABN\b.*$", "", provider_raw, flags=re.I))
    return stripped, abn, problem


def is_individual(provider: str) -> bool:
    """True when the Provider value looks like a natural person (over-withholds on purpose).

    The shared fail-closed rule (profile_providers.name_is_withheld) applies first, so a
    company or trust word cannot carry an individual trustee or a person-named trust through.
    """
    if name_is_withheld(provider):
        return True
    if _TITLE.search(provider) or _PARTNERSHIP_OF.match(provider):
        return True
    if _STRONG.search(provider):
        return False
    if not _WEAK.search(provider):
        return True
    return bool(_PERSON_JOIN.search(provider))


def person_tokens(provider: str) -> set[str]:
    """Words of the person part of a provider string (before any comma or semicolon)."""
    person_part = re.split(r"[,;]", provider, maxsplit=1)[0]
    person_part = _PARTNERSHIP_OF.sub("", person_part)
    words = re.findall(r"[A-Za-z][A-Za-z\-]*", person_part.lower())
    return {w for w in words if len(w) >= 3 and w not in _NOT_NAME_WORDS}


def _words(text: str) -> set[str]:
    return {w.lower() for w in re.findall(r"[A-Za-z][A-Za-z\-]*", text)}


# ---------------------------------------------------------------------------
# Walking the page
# ---------------------------------------------------------------------------


def _text(node) -> str:
    return clean(node.get_text(" "))


def _label_key(label: str) -> str:
    return clean(label).rstrip(":").strip().lower()


def _is_label_tag(el: Tag) -> bool:
    return el.name in {"strong", "b"} and _text(el).endswith(":")


def _inside(el: Tag, names: list[str]) -> bool:
    return el.find_parent(names) is not None


def _dt_value(dt: Tag) -> str:
    for sib in dt.next_siblings:
        if isinstance(sib, Tag):
            if sib.name == "dd":
                return _text(sib)
            if sib.name == "dt":
                break
    return ""


def _strong_value(label: Tag) -> str:
    parts: list[str] = []
    for sib in label.next_siblings:
        if isinstance(sib, Tag):
            if sib.name == "br" or _is_label_tag(sib):
                break
            parts.append(_text(sib))
        else:
            parts.append(str(sib))
    value = clean(" ".join(parts))
    if not value and label.parent is not None:
        # <p><strong>Label:</strong></p><p>value</p>
        parent_text = _text(label.parent)
        nxt = label.parent.find_next_sibling()
        if parent_text == _text(label) and nxt is not None and nxt.name in {"p", "div", "dd", "ul"}:
            if not nxt.find(_is_label_tag):
                value = _text(nxt)
    return value


def _entries(main: Tag) -> list[dict]:
    """Split <main> into entries: {'service': h2 text, 'pairs': [(label, value), ...]}."""
    has_toc = any(_text(h).lower().startswith("on this page") for h in main.find_all("h2"))
    started = not has_toc
    entries: list[dict] = []
    for el in main.descendants:
        if not isinstance(el, Tag):
            continue
        if el.name == "h2":
            text = _text(el)
            if text.lower().startswith("on this page"):
                started = True
                continue
            if started:
                entries.append({"service": text, "pairs": []})
            continue
        if not entries or _inside(el, ["h2"]):
            continue
        pair: tuple[str, str] | None = None
        if el.name == "dt":
            pair = (_label_key(_text(el)), _dt_value(el))
        elif _is_label_tag(el) and not _inside(el, ["dt", "dd"]):
            pair = (_label_key(_text(el)), _strong_value(el))
        elif (
            el.name in {"p", "li"} and not _inside(el, ["dt", "dd"]) and not el.find(_is_label_tag)
        ):
            m = re.match(r"([^:]{3,80}):\s*(.*)", _text(el))
            if m and _label_key(m.group(1)) in LABELS:
                pair = (_label_key(m.group(1)), clean(m.group(2)))
        if pair and pair[0]:
            entries[-1]["pairs"].append(pair)
    return entries


# ---------------------------------------------------------------------------
# Row building
# ---------------------------------------------------------------------------


def _build_row(entry: dict, *, role: str, page_url: str) -> dict | None:
    fields: dict[str, str] = {}
    notes_extra: list[str] = []
    for label, value in entry["pairs"]:
        key = LABELS.get(label)
        if key is None:
            notes_extra.append(f"{label}: {value}")
        elif key in fields:
            notes_extra.append(f"{label} (repeated): {value}")
        else:
            fields[key] = value

    provider_raw = fields.get("provider", "")
    sanction_raw = fields.get("sanction", "")
    grounds = fields.get("grounds", "") or None
    if not provider_raw and not sanction_raw and not grounds:
        return None

    notes: list[str] = []
    service_name = clean(entry["service"]) or None

    # Provider, ABN and the individual check.
    provider_name: str | None = None
    abn: str | None = None
    redact: set[str] = set()
    withheld = False
    withheld_markers: list[str] = []  # constant phrases only, never source text
    if provider_raw:
        stripped, abn, abn_problem = split_abn(provider_raw)
        if abn_problem and not is_individual(stripped):
            notes.append(abn_problem)
        if is_individual(stripped):
            withheld = True
            redact = person_tokens(stripped)
            withheld_markers.append(WITHHELD_NOTE)
            if abn:
                withheld_markers.append("ABN not kept because the subject is an individual")
                abn = None
        else:
            provider_name = stripped or None
    else:
        notes.append("provider not printed")

    if withheld and service_name and redact & _words(service_name):
        service_name = None
        withheld_markers.append(
            "service name withheld: it repeats a word from the individual's name"
        )

    if abn:
        notes.insert(0, f"ccs_identifier: ABN {abn}")
    for key, label in NOTE_FIELDS:
        if fields.get(key):
            notes.append(f"{label}: {fields[key]}")
    notes.extend(notes_extra)

    action_type, type_note = map_action_type(sanction_raw)
    if type_note:
        notes.append(type_note)
    if not sanction_raw:
        notes.append("type of sanction not printed")
    if not fields.get("service_type"):
        notes.append("service type not printed")

    date_raw = fields.get("date", "")
    date_issued = parse_cth_date(date_raw) if date_raw else None
    if not date_raw:
        notes.append("date of effect not printed")
    elif not date_issued:
        notes.append(f"date not parsable: {date_raw!r}")

    loc = parse_location(fields.get("location", ""))
    if loc["address"]:
        notes.append(f"location as printed: {loc['address']}")
        loc["address"] = None
    if fields.get("location") and not loc["state"] and not loc["address"]:
        notes.append("state not printed in location")
    if not fields.get("location"):
        notes.append("location not printed")

    # Approval numbers are public keys of the service and provider approvals, never a name:
    # withholding a name never drops them.
    blob = " ".join([entry["service"] or "", *(v for _, v in entry["pairs"])])
    se_raw = (_SE.search(blob) or [None])[0]
    pr_raw = (_PR.search(blob) or [None])[0]
    if not (se_raw or pr_raw):
        notes.append("register prints no SE-/PR- number in this row")

    row = {
        "record_id": None,  # set by parse_page from non-name facts (assign_record_ids)
        "jurisdiction": JURISDICTION,
        "source_register": CURRENT_URL,
        "source_document": page_url,
        "source_snapshot": "",
        "captured_at": "",
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
        "reason": grounds,
        "legal_references": extract_legal_references(sanction_raw, grounds),
        "date_issued": date_issued,
        "date_issued_raw": date_raw or None,
        "period_label": role,
        "notes": "; ".join(notes) or None,
        # In-memory only, never written: the printed entry, names included, so a repeated row
        # is spotted without ever using a name or a placeholder in the record_id.
        "_fingerprint": printed_fingerprint(
            entry["service"], *(f"{k}: {v}" for k, v in entry["pairs"])
        ),
    }
    # Structured facts, taken before any free text is withheld.
    row["service_type"] = SERVICE_TYPES.get(clean(fields.get("service_type", "")).lower())
    row["plea"] = PLEAS.get(clean(fields.get("plea", "")).lower())
    for key, column, label in STRUCTURED_DATES:
        printed = fields.get(key, "")
        row[column] = parse_cth_date(printed) if printed else None
        if printed and row[column] is None:
            notes.append(f"{label} printed but not parsable")
            withheld_markers.append(f"{label} printed but not parsable")
    row["notes"] = "; ".join(notes) or None
    if withheld:
        withhold_free_text(row, tuple(withheld_markers))
    return row


def mark_duplicates(rows: list[dict]) -> None:
    """Append '; duplicate row in source' to later rows that print the same entry. Keeps every
    row. Rows are compared by their printed content, not by record_id."""
    seen: set[str] = set()
    for row in rows:
        if row["_fingerprint"] in seen:
            if DUPLICATE_NOTE not in (row["notes"] or ""):
                row["notes"] = (
                    f"{row['notes']}; {DUPLICATE_NOTE}" if row["notes"] else DUPLICATE_NOTE
                )
        seen.add(row["_fingerprint"])


def parse_page(
    html: str,
    *,
    role: str,
    page_url: str,
    captured_at: str = "",
    source_snapshot: str = "",
) -> list[dict]:
    """Parse every register entry on one page. role is 'current' or 'past'."""
    soup = BeautifulSoup(html, "lxml")
    main = soup.find("main") or soup.body or soup
    rows: list[dict] = []
    for entry in _entries(main):
        row = _build_row(entry, role=role, page_url=page_url)
        if row is None:
            continue
        row["captured_at"] = captured_at
        row["source_snapshot"] = source_snapshot
        rows.append(row)
    mark_duplicates(rows)
    withhold_prose_naming_people(rows)  # shared prose rule, every row
    assign_record_ids(rows, source_id=page_url)
    return rows


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


def _fetched_from_file(file: Path, url: str) -> common.Fetched:
    """Wrap a browser-saved HTML file as if fetched, so the snapshot sidecar is complete."""
    content = file.read_bytes()
    return common.Fetched(
        url=url,
        final_url=url,
        status=0,
        content=content,
        content_type="text/html; charset=utf-8 (saved from browser)",
        last_modified=None,
        etag=None,
        fetched_at=common.utc_now().isoformat(),
    )


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
    ap.add_argument(
        "--current-file",
        type=Path,
        help="HTML of the current register saved from a browser (education.gov.au drops non-browser clients)",
    )
    ap.add_argument(
        "--past-file", type=Path, help="HTML of the past registers page saved from a browser"
    )
    args = ap.parse_args(argv)

    paths: dict[str, Path] = {}
    if args.skip_fetch:
        paths = _latest_by_role()
    elif args.current_file or args.past_file:
        stamp = common.utc_stamp()
        for role, file in (("current", args.current_file), ("past", args.past_file)):
            if file is None:
                continue
            if not file.exists():
                log.error("%s file not found: %s", role, file)
                return 2
            paths[role] = write_page_snapshot(_fetched_from_file(file, PAGES[role]), stamp, role)
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
    per_page: dict[str, int] = {}
    for role, path in paths.items():
        meta_path = Path(f"{path}.meta.json")
        meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        page_rows = parse_page(
            path.read_text(encoding="utf-8", errors="replace"),
            role=role,
            page_url=PAGES[role],
            captured_at=meta.get("fetched_at", ""),
            source_snapshot=path.relative_to(PROJECT_ROOT).as_posix(),
        )
        per_page[role] = len(page_rows)
        rows.extend(page_rows)
    mark_duplicates(rows)
    missing = [r for r in PAGES if r not in paths]
    if missing:
        log.warning("pages not captured: %s", ", ".join(missing))
    if not rows:
        log.error("pages captured but no register entries recognised; check the layout")
        return 1

    out_rows = [{**r, "legal_references": json.dumps(r["legal_references"])} for r in rows]
    write_processed(
        OUTPUT_NAME,
        out_rows,
        FIELDNAMES,
        raw_inputs=list(paths.values()),
        schema=SCHEMA_PATH,
        notes=(
            "Parsed from browser-saved pages (dt/dd entry layout). ABN is in notes as "
            "'ccs_identifier: ABN ...'; individuals' names, and their ABNs, are withheld."
            + (f" Pages not captured: {', '.join(missing)}." if missing else "")
        ),
    )
    withheld = sum(1 for r in rows if WITHHELD_NOTE in (r["notes"] or ""))
    with_abn = sum(1 for r in rows if "ccs_identifier: ABN" in (r["notes"] or ""))
    dupes = sum(1 for r in rows if DUPLICATE_NOTE in (r["notes"] or ""))
    log.info("rows per page: %s", per_page)
    log.info(
        "%d rows: %d withheld as individuals, %d with an ABN kept, %d duplicate rows",
        len(rows),
        withheld,
        with_abn,
        dupes,
    )
    log.info("action_type: %s", dict(Counter(r["action_type"] for r in rows)))
    log.info("%d rows parsed from %s", len(rows), ", ".join(paths))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
