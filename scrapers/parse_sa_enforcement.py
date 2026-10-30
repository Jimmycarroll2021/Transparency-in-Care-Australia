"""Fetch and parse the South Australian (ESB) compliance action register under the National Law.

Source: Education Standards Board SA, "Current compliance action" and the "Historical compliance
action" year pages, https://www.esb.sa.gov.au/early-childhood/compliance-and-enforcement
Licence: "All rights reserved" (ESB copyright and disclaimer page). The project owner states that
consent has been obtained (CLAUDE.md, Current phase); the licence text is recorded in every
snapshot sidecar as `licence_note`. See research/2026-10-29-register-enforcement-sa-wa-tas-nt-act.md.

Only HTML pages are fetched. Older PDF tables, if any, are logged and not parsed in this version.
Pages are discovered from the historical index page (https://www.esb.sa.gov.au/historical-compliance-action).

Outputs:
- data/raw/sa-enforcement/<stamp>-<slug>.html (+ .meta.json) for the current page, the historical
  index, each year page and the copyright page
- data/processed/sa-enforcement-actions.csv (one row per published action per service or provider)
- data/processed/sa-enforcement-yearly-counts.csv (summary table by financial year, the denominator)

Run: python3 scrapers/parse_sa_enforcement.py [--force] [--skip-fetch]
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

import httpx
from bs4 import BeautifulSoup, Tag

if __package__ in (None, ""):  # allow `python3 scrapers/parse_sa_enforcement.py`
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scrapers import common
from scrapers.common import (
    PROCESSED_DIR,
    PROJECT_ROOT,
    RAW_DIR,
    USER_AGENT,
    Fetched,
    RobotsDisallowed,
    assign_record_ids,
    fetch,
    known_hashes,
    log,
    normalise_pr,
    normalise_se,
    printed_fingerprint,
    record_hash,
    utc_stamp,
    withhold_free_text,
    withhold_prose_naming_people,
    write_processed,
)
from scrapers.profile_providers import name_is_withheld

SOURCE = "sa-enforcement"
JURISDICTION = "SA"
HOST = "www.esb.sa.gov.au"
INDEX_URL = "https://www.esb.sa.gov.au/early-childhood/compliance-and-enforcement"
CURRENT_URL = (
    "https://www.esb.sa.gov.au/early-childhood/compliance-and-enforcement/current-compliance-action"
)
HISTORICAL_INDEX_URL = "https://www.esb.sa.gov.au/historical-compliance-action"
COPYRIGHT_URL = "https://www.esb.sa.gov.au/copyright-disclaimer"
SITEMAP_URL = "https://www.esb.sa.gov.au/sitemap.xml"
CURRENT_SLUG = "current-compliance-action"
HISTORICAL_INDEX_SLUG = "historical-index"
COPYRIGHT_SLUG = "copyright-disclaimer"
NON_DATA_SLUGS = {HISTORICAL_INDEX_SLUG, COPYRIGHT_SLUG}
SCHEMA_PATH = "data/schemas/enforcement-action.schema.json"
ACTIONS_NAME = "sa-enforcement-actions"
COUNTS_NAME = "sa-enforcement-yearly-counts"
DEFAULT_LICENCE_NOTE = (
    "ESB copyright and disclaimer page (https://www.esb.sa.gov.au/copyright-disclaimer): "
    "(c) Government of South Australia. All rights reserved. Not openly licensed. Used under the "
    "project owner's statement of 2026-10-29 that consent was obtained from the data owner "
    "(CLAUDE.md, Current phase)."
)

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
    # Structured fact: the end of a printed date range, kept before free text is withheld.
    "end_date",
]

COUNT_FIELDNAMES = [
    "period_label",
    "action_type_raw",
    "count",
    "count_raw",
    "source_document",
    "captured_at",
    "source_snapshot",
]

_DASHES = "".join(chr(c) for c in (0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2015, 0x2212))

# ---------------------------------------------------------------------------
# Small text helpers
# ---------------------------------------------------------------------------


def clean(text: str | None) -> str:
    """Collapse whitespace (including non-breaking and zero-width spaces) and trim."""
    if text is None:
        return ""
    text = text.replace("\xa0", " ").replace("​", "")
    return re.sub(r"\s+", " ", text).strip()


def fold_dashes(text: str) -> str:
    return re.sub(f"[{_DASHES}]", "-", text)


MONTH_NAMES = {
    name: i + 1
    for i, name in enumerate(
        [
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        ]
    )
}
MONTH_NAMES.update(
    {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9}
)
MONTH_NAMES.update({"oct": 10, "nov": 11, "dec": 12})
MONTH_PATTERN = "|".join(sorted(MONTH_NAMES, key=len, reverse=True))
WORD_DATE = re.compile(
    rf"(?:(?:Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day,?\s+)?"
    rf"(?<!\d)(?P<d>\d{{1,2}})(?:st|nd|rd|th)?\s+(?P<m>{MONTH_PATTERN})\.?,?\s+(?P<y>\d{{4}})",
    re.IGNORECASE,
)
PARTIAL_DATE = re.compile(
    rf"(?<!\d)(?P<d>\d{{1,2}})(?:st|nd|rd|th)?\s+(?P<m>{MONTH_PATTERN})\b(?!\.?,?\s*\d)",
    re.IGNORECASE,
)
NUM_DATE = re.compile(r"(?<![\d/])(?P<d>\d{1,2})/(?P<m>\d{1,2})/(?P<y>\d{4}|\d{2})(?![\d/])")


def find_date(text: str | None) -> tuple[str | None, str | None]:
    """First printed date in `text` as (ISO date, raw fragment). (None, None) if none parses."""
    text = clean(text)
    if not text:
        return None, None
    candidates: list[tuple[int, str | None, str]] = []
    m = WORD_DATE.search(text)
    if m:
        try:
            iso = datetime(int(m["y"]), MONTH_NAMES[m["m"].lower()], int(m["d"])).date().isoformat()
        except ValueError:
            iso = None
        candidates.append((m.start(), iso, clean(m.group(0))))
    n = NUM_DATE.search(text)
    if n:
        year = int(n["y"])
        if len(n["y"]) == 2:
            year += 2000  # the register starts in 2012; two-digit years are 20xx
        try:
            iso = datetime(year, int(n["m"]), int(n["d"])).date().isoformat()
        except ValueError:
            iso = None
        candidates.append((n.start(), iso, clean(n.group(0))))
    if not candidates:
        return None, None
    _, iso, raw = min(candidates, key=lambda c: c[0])
    return iso, raw


def find_partial_date(text: str | None) -> str | None:
    """A day and month printed without a year (for example '24 October'), kept as raw only."""
    m = PARTIAL_DATE.search(clean(text))
    return clean(m.group(0)) if m else None


def parse_date(raw: str | None) -> str | None:
    return find_date(raw)[0]


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def discover_historical(index_html: str, sitemap_xml: str | None = None) -> list[str]:
    """Absolute URLs of the historical year pages.

    The index page links to its year pages by /node/NNN, and most of those node ids now point to
    unrelated PDF file pages. So the year is read from the link text and turned into the named
    URL, and the public sitemap.xml is used as a second source. Duplicates are dropped.
    """
    urls: list[str] = []

    def add(url: str) -> None:
        if url.rstrip("/") != HISTORICAL_INDEX_URL and url not in urls:
            urls.append(url)

    soup = BeautifulSoup(index_html, "lxml")
    body = largest_body(soup) or soup
    for a in body.find_all("a", href=True):
        m = re.search(
            r"historical compliance action:?\s*(\d{4}(?:-\d{2})?)\s*$", a.get_text(" "), re.I
        )
        if m:
            add(f"https://{HOST}/historical-compliance-action-{m.group(1)}")
    for loc in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", sitemap_xml or ""):
        parts = urlsplit(loc)
        if parts.netloc.lower() == HOST and parts.path.startswith("/historical-compliance-action"):
            add(f"https://{HOST}{parts.path}")
    return urls


def discover_pdf_links(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    out: list[str] = []
    for a in soup.find_all("a", href=True):
        url = urljoin(base_url, str(a["href"]).split("#")[0])
        if urlsplit(url).path.lower().endswith(".pdf") and url not in out:
            out.append(url)
    return out


def slug_for(final_url: str) -> str:
    path = urlsplit(final_url).path.strip("/")
    return path.rsplit("/", 1)[-1] or "page"


def canonical_slug(html: str) -> str | None:
    """Slug from the page's canonical link (node/NNN URLs do not redirect to the named page)."""
    soup = BeautifulSoup(html, "lxml")
    link = soup.find("link", rel="canonical")
    if link is None or not link.get("href"):
        return None
    slug = slug_for(str(link["href"]))
    return slug if slug.startswith("historical-compliance-action") else None


def period_label_for(slug: str) -> str:
    if slug == CURRENT_SLUG:
        return "Current compliance action"
    m = re.fullmatch(r"historical-compliance-action-(.+)", slug)
    if m:
        return f"Historical compliance action {m.group(1)}"
    return slug


# ---------------------------------------------------------------------------
# Snapshots (named <stamp>-<slug>.html, never overwritten)
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
    """Like common.write_snapshot but keeps the page slug in the file name."""
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
        if slug and slug.isdigit() and html_path.exists():
            # Snapshot taken before slugs came from the canonical link: fix the slug on read.
            slug = canonical_slug(html_path.read_text(encoding="utf-8", errors="replace")) or slug
        if slug and html_path.exists():
            prior = out.get(slug)
            if prior is None or meta.get("fetched_at", "") >= prior[1].get("fetched_at", ""):
                out[slug] = (html_path, meta)
    return out


def licence_note_from(copyright_html: str | None) -> str:
    """Confirm the 'All rights reserved' wording on the live copyright page; else the default."""
    if copyright_html:
        text = clean(BeautifulSoup(copyright_html, "lxml").get_text(" "))
        m = re.search(r"[^.]*All rights reserved\.?", text)
        if m:
            return (
                f"ESB copyright and disclaimer page ({COPYRIGHT_URL}) states: "
                f"{clean(m.group(0))!r}. Not openly licensed. Used under the project owner's "
                "statement of 2026-10-29 that consent was obtained from the data owner "
                "(CLAUDE.md, Current phase)."
            )
    return DEFAULT_LICENCE_NOTE


def table_last_updated(html: str) -> str | None:
    m = re.search(r"Table last updated:\s*([^<]{3,40})", html)
    return clean(m.group(1)) if m else None


def collect(*, force: bool) -> tuple[list[str], list[str]]:
    """Fetch the current page, the historical index and every year page.

    Returns (PDF URLs found, page URLs that could not be fetched).
    """
    copyright_page = fetch(COPYRIGHT_URL)
    licence = licence_note_from(copyright_page.text)
    pdfs: list[str] = []

    def store(slug: str, page: Fetched, **extra: object) -> None:
        hashes = known_hashes(SOURCE)
        if force or page.sha256 not in hashes:
            write_named_snapshot(slug, page, extra_meta={"licence_note": licence, **extra})
        else:
            log.info("%s unchanged (sha256 %s), no new snapshot", slug, page.sha256[:12])

    store(COPYRIGHT_SLUG, copyright_page)
    current = fetch(CURRENT_URL)
    store(CURRENT_SLUG, current, table_last_updated=table_last_updated(current.text))
    pdfs.extend(discover_pdf_links(current.text, current.final_url))

    index = fetch(HISTORICAL_INDEX_URL)
    store(HISTORICAL_INDEX_SLUG, index)
    try:
        sitemap_xml = fetch(SITEMAP_URL, retries=0).text
    except (httpx.HTTPError, RobotsDisallowed) as exc:
        log.warning("sitemap.xml not available (%s); using index link text only", exc)
        sitemap_xml = None
    urls = discover_historical(index.text, sitemap_xml)
    log.info("found %d historical page links", len(urls))
    seen_slugs: set[str] = set()
    failed: list[str] = []
    for url in urls:
        try:
            page = fetch(url, retries=0)
        except (httpx.HTTPError, RobotsDisallowed) as exc:
            log.warning("could not fetch %s: %s", url, str(exc).splitlines()[0])
            failed.append(url)
            continue
        slug = canonical_slug(page.text) or slug_for(page.final_url)
        if not slug.startswith("historical-compliance-action"):
            log.warning("%s is not a historical compliance action page (%s); skipped", url, slug)
            failed.append(url)
            continue
        if slug in seen_slugs:
            log.info("%s is the same page as an already fetched one (%s)", url, slug)
            continue
        seen_slugs.add(slug)
        store(slug, page, discovered_from=url)
        pdfs.extend(u for u in discover_pdf_links(page.text, page.final_url) if u not in pdfs)
    return pdfs, failed


# ---------------------------------------------------------------------------
# Section parsing
# ---------------------------------------------------------------------------

# Label text (lower case, no colon) -> field name. Longest labels are tried first.
LABELS = {
    "approved provider address": "provider_address",
    "approved provider name": "provider",
    "approved provider": "provider",
    "service address": "address",
    "address": "address",
    "details of enforceable undertaking": "details_eu",
    "reason for enforceable undertaking": "reason_eu",
    "details of action": "details",
    "details": "details",
    "action taken": "action",
    "steps taken": "steps",
    "type of action": "type",
    "type of a action": "type",  # typo printed on the 2015 page
    "compliance type": "type",
    "date of agreed undertaking": "date",
    "date of action": "date",
    "outcome": "outcome",
}
_LABEL_ALT = "|".join(sorted((re.escape(k) for k in LABELS), key=len, reverse=True))
LABEL_LINE = re.compile(rf"^(?P<label>{_LABEL_ALT})\s*(?::\s*(?P<value>.*)|\s*)$", re.IGNORECASE)

SE_TOKEN = re.compile(r"\(?\bSE[\s_-]*\d+\b\)?", re.IGNORECASE)
PR_TOKEN = re.compile(r"\(?\bPR[\s_-]*\d+\b\)?", re.IGNORECASE)

ENTITY_MARKER = re.compile(
    r"\b(pty|ltd|limited|inc|incorporated|council|association|co-?operative|trust|foundation|"
    r"school|college|church|university|institute|department|corporation|company|society|"
    r"kindergarten|centre|center|care|learning|education|services|group|australia|"
    r"limited partnership|ymca|ywca|shire|city of|trustee|committee|governing|board|"
    r"partnership|nominees|holdings|enterprises|atf|oshc)\b",
    re.IGNORECASE,
)
LEGAL_REF = re.compile(
    r"\b(?:Sections?|Regulations?|Reg|ss?\.?)\s*\d+[A-Z]*(?:\s*\([A-Za-z0-9]+\))*",
    re.IGNORECASE,
)
ADDRESS_TAIL_STATE = re.compile(
    r"^(?P<rest>.*?)[,\s]+(?P<state>NSW|VIC|QLD|SA|WA|TAS|NT|ACT)\b[,\s]*(?P<postcode>\d{4})?\s*$"
)
ADDRESS_TAIL_POSTCODE = re.compile(r"^(?P<rest>.*?),\s*(?P<postcode>\d{4})\s*$")


def lines_of(fragment_html: str) -> list[str]:
    """Text of an HTML fragment as lines, splitting on <br> and block elements."""
    soup = BeautifulSoup(f"<div>{fragment_html}</div>", "lxml")
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for block in soup.find_all(["p", "li", "div", "ul", "ol", "tr"]):
        block.insert_before("\n")
        block.insert_after("\n")
    return [clean(line) for line in soup.get_text().split("\n") if clean(line)]


def largest_body(soup: BeautifulSoup) -> Tag | None:
    bodies = soup.select("div.field--name-body")
    return max(bodies, key=lambda d: len(d.get_text()), default=None)


def split_sections(body: Tag) -> list[tuple[str, str]]:
    """[(heading text, html of everything up to the next h2)] in page order."""
    sections: list[tuple[str, list[str]]] = []
    for child in body.children:
        if isinstance(child, Tag) and child.name == "h2":
            sections.append((clean(child.get_text(" ")), []))
        elif sections:
            sections[-1][1].append(str(child))
    return [(h, "".join(parts)) for h, parts in sections]


def split_fields(lines: list[str]) -> dict[str, list[str]]:
    """Group lines under their label. Only the first occurrence of each field counts as a label."""
    fields: dict[str, list[str]] = {}
    labels_seen: dict[str, str] = {}  # field -> printed label
    current: str | None = None
    for line in lines:
        m = LABEL_LINE.match(fold_dashes(line))
        if m:
            name = LABELS[m["label"].lower()]
            if name not in fields:
                current = name
                fields[name] = []
                labels_seen[name] = clean(m["label"])
                value = clean(m["value"]) if m["value"] else ""
                if value:
                    fields[name].append(value)
                continue
        if current is not None:
            fields[current].append(line)
    fields["_labels"] = list(labels_seen.values())
    return fields


def split_address(address: str | None) -> tuple[str | None, str | None, str | None]:
    """(suburb, state, postcode) as printed; nulls where the address does not separate."""
    if not address:
        return None, None, None
    m = ADDRESS_TAIL_STATE.match(address)
    if m:
        rest, state, postcode = m["rest"], m["state"], m["postcode"]
    else:
        p = ADDRESS_TAIL_POSTCODE.match(address)
        if p:
            rest, state, postcode = p["rest"], None, p["postcode"]
        else:
            rest, state, postcode = address, None, None
    parts = [x.strip() for x in rest.split(",") if x.strip()]
    suburb = None
    if len(parts) >= 2 and not re.search(r"\d", parts[-1]):
        suburb = parts[-1]
    elif len(parts) == 1 and (state or postcode):
        # No comma before the suburb: accept a trailing run of capitalised words only.
        caps = re.search(r"(?:\s|^)((?:[A-Z][A-Z'-]{2,}\s?){1,3})$", parts[0])
        if caps and caps.start() > 0:
            suburb = caps.group(1).strip()
    return suburb, state, postcode


def extract_legal_references(*texts: str | None) -> list[str]:
    """Section and regulation citations as printed, de-duplicated in order of appearance."""
    refs: list[str] = []
    for text in texts:
        for m in LEGAL_REF.finditer(text or ""):
            ref = clean(m.group(0))
            ref = re.sub(r"\s+\(", "(", ref)
            ref = re.sub(r"^(?:s|ss)\.?\s*(?=\d)", "s ", ref, flags=re.IGNORECASE)
            ref = re.sub(
                r"^(sections?|regulations?|reg)\b",
                lambda mm: mm.group(1).capitalize(),
                ref,
                flags=re.IGNORECASE,
            )
            if ref.casefold() not in {r.casefold() for r in refs}:
                refs.append(ref)
    return refs


def map_action_type(raw: str) -> str:
    """Conservative mapping to the schema enum. Ambiguous or unknown text maps to 'other'."""
    text = fold_dashes(raw).lower().replace("without show cause", "")
    hits: set[str] = set()
    if "direction to suspend" in text or "direction to exclude" in text:
        hits.add("direction_to_exclude")
    elif "inappropriate person" in text and "exclu" in text:
        hits.add("direction_to_exclude")
    elif "suspend" in text or "suspension" in text:
        hits.add("approval_suspended")
    if "compliance notice" in text:
        hits.add("compliance_notice")
    if "compliance direction" in text:
        hits.add("compliance_direction")
    if "emergency action" in text:
        hits.add("emergency_action_notice")
    if "enforceable undertaking" in text or "undertaking" in text:
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
    if re.search(r"\bconditions?\b", text):
        hits.add("condition_imposed")
    if hits == {"approval_amended", "condition_imposed"}:
        # An amendment of the approval under s 55 that imposes conditions.
        hits = {"condition_imposed"}
    return hits.pop() if len(hits) == 1 else "other"


def action_head(lines: list[str]) -> str:
    """The lead clause of the action text, as printed, cut before the list of requirements."""
    if not lines:
        return ""
    lead = lines[0]
    cut = re.search(r"\s*,?\s*requiring\b|:\s*$|:\s", lead)
    if cut and cut.start() > 0:
        lead = lead[: cut.start()]
    lead = lead.rstrip(" ,;:")
    if len(lead) > 300:
        lead = lead[:300].rsplit(" ", 1)[0] + " ..."
    return lead


def is_organisation(name: str) -> bool:
    return bool(ENTITY_MARKER.search(name))


def first_token(text: str, regex: re.Pattern) -> str | None:
    """First approval-number token as printed (dash variants matched, original text returned)."""
    m = regex.search(fold_dashes(text))
    return clean(text[m.start() : m.end()].strip("()")) if m else None


def strip_tokens(text: str, regex: re.Pattern) -> str:
    """`text` without approval-number tokens, keeping every other character as printed."""
    out: list[str] = []
    last = 0
    for m in regex.finditer(fold_dashes(text)):
        out.append(text[last : m.start()])
        out.append(" ")
        last = m.end()
    out.append(text[last:])
    return "".join(out)


def clean_provider(joined: str) -> tuple[str | None, str | None, bool]:
    """(provider name, raw PR token, trust text dropped) from the provider field text."""
    text = clean(joined)
    pr_raw = first_token(text, PR_TOKEN)
    name = strip_tokens(text, PR_TOKEN)
    name = re.sub(r"\bis the approved provider\b", " ", name, flags=re.IGNORECASE)
    name = clean(re.sub(r"\(\s*\)", " ", name)).strip(" ,;-")
    trust_dropped = False
    t = re.search(r"\s+trustee for\b.*$", name, flags=re.IGNORECASE)
    if t and t.start() > 0:
        name = name[: t.start()].strip(" ,;-")
        trust_dropped = True
    return (name or None), pr_raw, trust_dropped


def parse_section(heading: str, html: str, *, page_is_current_format: bool = True) -> dict:
    """One section to a row dict (without provenance columns). Person-level text is dropped."""
    lines = lines_of(html)
    f = split_fields(lines)
    notes: list[str] = []

    heading_clean = clean(heading)
    se_raw = first_token(heading_clean, SE_TOKEN)
    service_name = clean(strip_tokens(strip_tokens(heading_clean, PR_TOKEN), SE_TOKEN))
    service_name = clean(re.sub(r"\(\s*\)", " ", service_name)).strip(" ,;-" + _DASHES) or None

    provider_text = " ".join(f.get("provider", []))
    provider_name, pr_raw, trust_dropped = clean_provider(provider_text)
    if pr_raw is None:
        pr_raw = first_token(heading_clean, PR_TOKEN)
    provider_raw_for_hash = provider_name
    if trust_dropped:
        notes.append("trust text after 'trustee for' removed from provider name")

    # Address: service address, else the provider's address (enforceable undertakings).
    address = clean(", ".join(f.get("address", []))) or None
    if address is None and f.get("provider_address"):
        address = clean(", ".join(f["provider_address"])) or None
        notes.append("address is the approved provider's address (no service address printed)")
    suburb, state, postcode = split_address(address)
    if address and state and state != "SA":
        notes.append(f"address printed with state {state}, outside South Australia")
    if address and postcode is None:
        notes.append("postcode not printed or not four digits")

    # Action type, text and date.
    action_lines = f.get("action", [])
    type_text = clean(" ".join(f.get("type", [])))
    labels = f.get("_labels", [])
    inferred = False
    if type_text:
        action_raw = type_text
    elif action_lines:
        action_raw = action_head(action_lines)
    elif any("undertaking" in lab.lower() for lab in labels):
        action_raw = next(
            (lab for lab in labels if "enforceable undertaking" in lab.lower()),
            next(lab for lab in labels if "undertaking" in lab.lower()),
        )
        inferred = True
    elif f.get("details") and map_action_type(f["details"][0]) != "other":
        # Older pages sometimes print the action in the first line of the details.
        action_raw = f["details"][0]
        f["details"] = f["details"][1:]
        notes.append("action type taken from the first line of the details (no type label printed)")
    else:
        action_raw = ""
    if inferred:
        notes.append("action type inferred from the printed section label, no action text printed")
    date_iso, date_raw = find_date(" ".join(f.get("date", [])))
    end_date = None
    date_range = re.split(r"(?<=[0-9])[ ]+to[ ]+(?=[0-9])", " ".join(f.get("date", [])), maxsplit=1)
    if len(date_range) == 2:
        notes.append("date range printed; the start date is used as date_issued")
        end_date = find_date(date_range[1])[0]
    if not date_raw:
        date_iso, date_raw = find_date(action_lines[0] if action_lines else "")
        if (
            date_raw
            and not f.get("date")
            and map_action_type(action_raw) not in {"compliance_notice", "emergency_action_notice"}
        ):
            notes.append(
                "date taken from the first date in the action text (may be an effective date)"
            )
    if not date_raw:
        partial = find_partial_date(
            " ".join(f.get("date", [])) or (action_lines[0] if action_lines else "")
        )
        if partial:
            date_raw = partial
            notes.append(f"date printed without a year ({partial!r}); date_issued set to null")
        else:
            notes.append("date missing or unparsable in the section")
    if len(re.findall(r"\bIssue of\b", " ".join(action_lines), flags=re.IGNORECASE)) > 1:
        notes.append("action text names more than one issue; first action only used for type/date")

    # Reason text: contraventions (details) or the stated reason for an undertaking.
    reason_lines = f.get("details", []) or f.get("reason_eu", [])
    outcome_lines = list(f.get("outcome", []))
    kept: list[str] = []
    for ln in reason_lines:
        if re.search(r"\b(?:has|have)\s+(?:not\s+)?provided evidence\b", ln, re.IGNORECASE):
            outcome_lines.append(ln)
        else:
            kept.append(ln)
    reason = None
    if kept:
        head, rest = kept[0], [x.lstrip("• ").strip() for x in kept[1:] if x.strip()]
        reason = f"{head} " + "; ".join(rest) if rest else head
    # Names in the reason or outcome are handled by the shared prose rule in parse_actions.
    outcome = " ".join(outcome_lines) or None
    if outcome:
        short = outcome if len(outcome) <= 240 else outcome[:240].rsplit(" ", 1)[0] + " ..."
        notes.append(f"outcome printed: {short}")
    if reason is None:
        notes.append("no reason or contravention text printed")

    refs = extract_legal_references(reason, action_raw, action_lines[0] if action_lines else "")
    if re.search(
        r"\b(revoked|revoke|lifted|withdrawn|rescinded)\b", f"{action_raw} {outcome or ''}", re.I
    ):
        notes.append("text mentions the action being revoked, lifted or withdrawn: check source")

    # Provider-level sections have a heading that is only the provider's name.
    if (
        (pr_raw or "undertaking" in action_raw.lower())
        and not se_raw
        and service_name
        and provider_name
        and provider_name.casefold().startswith(service_name.casefold())
    ):
        notes.append("provider-level action: heading is the provider name, no service named")
        service_name_hash = service_name
        service_name = None
    else:
        service_name_hash = service_name

    # Withhold provider names that may be individuals (rule 2).
    withheld_markers: list[str] = []  # constant phrases only, never source text
    if provider_name:
        family_trust = re.search(r"\bfamily trust\b|^\s*trustee for\b", provider_name, re.I)
        if (
            family_trust
            or not is_organisation(provider_name)
            or name_is_withheld(provider_name)  # shared fail-closed rule
        ):
            withheld_markers.append(
                "provider name withheld: no company or organisation marker or a family trust, "
                "may identify an individual"
            )
            if (
                service_name
                and provider_name.casefold().startswith(service_name.casefold())
                or service_name
                and service_name.casefold() == provider_name.casefold()
            ):
                service_name = None
                withheld_markers.append(
                    "service name withheld: identical to the withheld provider name"
                )
            if address:
                withheld_markers.append("street address withheld: provider may be an individual")
                address = None
            provider_name = None

    se = normalise_se(fold_dashes(se_raw)) if se_raw else None
    pr = normalise_pr(fold_dashes(pr_raw)) if pr_raw else None
    for label, raw, norm in (("service", se_raw, se), ("provider", pr_raw, pr)):
        if raw is None:
            notes.append(f"{label} approval number not printed; set to null")
        elif norm is None:
            notes.append(f"{label} approval number unparsable ({raw!r}); set to null")
        elif len(re.sub(r"\D", "", raw)) != 8:
            notes.append(
                f"{label} approval number printed with {len(re.sub(r'[^0-9]', '', raw))} digits; zero-padded"
            )
    if se_raw and not re.search(r"SE-", fold_dashes(se_raw)):
        notes.append("service approval number printed without the hyphen")
    elif se_raw and fold_dashes(se_raw) != se_raw:
        notes.append("service approval number printed with a dash other than a hyphen")
    if not action_raw:
        notes.append("no action type printed")

    return {
        "service_approval_number": se,
        "service_approval_number_raw": se_raw,
        "provider_approval_number": pr,
        "provider_approval_number_raw": pr_raw,
        "service_name": service_name,
        "provider_name": provider_name,
        "address": address,
        "suburb": suburb,
        "state": state,
        "postcode": postcode,
        "action_type": map_action_type(action_raw),
        "action_type_raw": action_raw,
        "reason": reason,
        "legal_references": json.dumps(refs, ensure_ascii=False),
        "date_issued": date_iso,
        "date_issued_raw": date_raw,
        "end_date": end_date,
        "notes": notes,
        "_hash_fallback": provider_raw_for_hash or service_name_hash,
        "_hash_service": service_name_hash,
        "_withheld_markers": withheld_markers,
    }


def is_action_section(heading: str, html: str) -> bool:
    """A section is an action entry when it carries an approved provider label."""
    if re.search(r"statutory compliance actions|breadcrumb|sections in this page", heading, re.I):
        return False
    return bool(re.search(r"approved provider|approved provider name", html, re.IGNORECASE))


def parse_actions(
    html: str,
    *,
    source_document: str,
    captured_at: str,
    period_label: str,
    source_snapshot: str | None = None,
) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    body = largest_body(soup)
    if body is None:
        log.warning("no body container in %s", source_document)
        return []
    rows: list[dict] = []
    for heading, section_html in split_sections(body):
        if not is_action_section(heading, section_html):
            continue
        info = parse_section(heading, section_html)
        notes = info.pop("notes")
        # The record_id hashes the whole printed section (assign_record_ids). Duplicates are found
        # on the printed action facts instead, because the same action reprinted on another page
        # can carry an extra outcome sentence.
        fallback = info.pop("_hash_fallback")
        fallback_service = info.pop("_hash_service")
        withheld_markers = info.pop("_withheld_markers")
        page_year = re.search(r"\b(20\d{2})$", period_label)
        if (
            page_year
            and info["date_issued"]
            and not info["date_issued"].startswith(page_year.group(1))
        ):
            notes.append(
                f"date year differs from the {page_year.group(1)} page it is printed on: check source"
            )
        row = {
            "record_id": None,  # set below from non-name facts (assign_record_ids)
            # In-memory only, never written: the printed action, names included, to find
            # the same action printed twice (on one page or on two pages).
            "_fingerprint": printed_fingerprint(
                heading, BeautifulSoup(section_html, "lxml").get_text(" ")
            ),
            # In-memory only, never written: the printed action facts (key, action text, date
            # as printed, reason), names included, so the same action on two pages is found.
            "_action_key": record_hash(
                "SA",
                info["service_approval_number"] or info["provider_approval_number"] or fallback,
                info["action_type_raw"],
                info["date_issued_raw"],
                info["reason"],
                None if info["service_approval_number"] else fallback_service,
            ),
            "jurisdiction": JURISDICTION,
            "source_register": INDEX_URL,
            "source_document": source_document,
            "source_snapshot": source_snapshot,
            "captured_at": captured_at,
            **info,
            "period_label": period_label,
            "notes": " | ".join(notes) if notes else None,
        }
        if withheld_markers:
            withhold_free_text(row, tuple(withheld_markers))
        rows.append(row)
    withhold_prose_naming_people(rows)  # shared prose rule, every row
    assign_record_ids(rows)
    return rows


# ---------------------------------------------------------------------------
# Summary count table
# ---------------------------------------------------------------------------


def parse_count(raw: str) -> int | None:
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
    source_snapshot: str | None = None,
) -> list[dict]:
    """Rows of the 'Statutory compliance actions issued by type and year' table."""
    soup = BeautifulSoup(html, "lxml")
    out: list[dict] = []
    for table in soup.find_all("table"):
        first = table.find("tr")
        if first is None:
            continue
        heads = [clean(c.get_text(" ")) for c in first.find_all(["th", "td"])]
        if not heads or heads[0].lower() != "type" or len(heads) < 2:
            continue
        for tr in table.find_all("tr")[1:]:
            cells = tr.find_all(["td", "th"])
            if not cells:
                continue
            label = clean(cells[0].get_text(" "))
            if not label:
                continue
            values = [clean(c.get_text(" ")) for c in cells[1:]]
            for i, period in enumerate(heads[1:]):
                raw = values[i] if i < len(values) else ""
                out.append(
                    {
                        "period_label": period,
                        "action_type_raw": label,
                        "count": parse_count(raw),
                        "count_raw": raw,
                        "source_document": source_document,
                        "captured_at": captured_at,
                        "source_snapshot": source_snapshot,
                    }
                )
    return out


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def mark_duplicates(rows: list[dict]) -> int:
    """Flag rows that print the same action again (twice on a page, or on two pages). Rows are
    compared by their printed action facts (_action_key), never by record_id, which is unique per
    printed row."""
    seen: dict[str, str] = {}
    dupes = 0
    for row in rows:
        rid = row["_action_key"]
        if rid in seen:
            dupes += 1
            extra = (
                f"duplicate row: same action also printed on '{seen[rid]}'; row kept, "
                "count once when aggregating"
            )
            row["notes"] = f"{row['notes']} | {extra}" if row["notes"] else extra
        else:
            seen[rid] = row["period_label"]
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
            "Summary table of statutory compliance actions issued by type and financial year, as "
            "printed on the ESB current compliance action page. count_raw keeps the printed cell. "
            "Counts are far larger than the number of per-service entries published on the pages, "
            "so most actions counted here have no published detail. Use as a denominator only "
            "with that caveat. Absence of an entry is not evidence of safety."
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

    def order(slug: str) -> tuple[int, str]:
        return (0 if slug == CURRENT_SLUG else 1, slug)

    def is_register_page(slug: str) -> bool:
        return slug == CURRENT_SLUG or slug.startswith("historical-compliance-action-")

    for slug in sorted((s for s in snaps if is_register_page(s)), key=order):
        path, meta = snaps[slug]
        html = path.read_text(encoding="utf-8", errors="replace")
        kwargs = {
            "source_document": meta.get("final_url") or meta["url"],
            "captured_at": meta["fetched_at"],
            "source_snapshot": path.relative_to(PROJECT_ROOT).as_posix(),
        }
        rows = parse_actions(html, period_label=period_label_for(slug), **kwargs)
        counts = parse_counts(html, **kwargs)
        log.info("%s: %d action rows, %d count rows", slug, len(rows), len(counts))
        action_rows.extend(rows)
        count_rows.extend(counts)
        inputs.append(path)
    for slug in sorted(NON_DATA_SLUGS & set(snaps)):
        inputs.append(snaps[slug][0])
    return action_rows, count_rows, inputs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--force", action="store_true", help="write new snapshots even if unchanged")
    ap.add_argument("--skip-fetch", action="store_true", help="parse existing snapshots only")
    args = ap.parse_args(argv)

    pdfs: list[str] = []
    failed: list[str] = []
    if not args.skip_fetch:
        pdfs, failed = collect(force=args.force)
    for url in failed:
        log.warning("linked page NOT fetched (error): %s", url)
    for url in pdfs:
        log.info("PDF NOT fetched or parsed in this version: %s", url)

    action_rows, count_rows, inputs = parse_all()
    if not action_rows and not count_rows:
        log.error("no snapshots to parse")
        return 1
    dupes = mark_duplicates(action_rows)
    null_se = sum(1 for r in action_rows if r["service_approval_number"] is None)
    withheld = sum(1 for r in action_rows if r["notes"] and "provider name withheld" in r["notes"])
    write_processed(
        ACTIONS_NAME,
        action_rows,
        FIELDNAMES,
        raw_inputs=inputs,
        schema=SCHEMA_PATH,
        notes=(
            "South Australia ESB compliance actions under the National Law, parsed from the HTML "
            "current and historical pages (latest snapshot of each). ESB content is All rights "
            "reserved; used under the project owner's statement of consent. Pages before 2022 "
            "print no SE-/PR- numbers, so those rows cannot be joined on a key. "
            "legal_references is a JSON array. Provider names that may be individuals are "
            "withheld. Absence of an entry is not evidence of safety."
        ),
    )
    write_counts(count_rows, inputs)
    log.info(
        "rows: %d; null SE-: %d; provider names withheld: %d; duplicate ids: %d; PDFs unfetched: %d",
        len(action_rows),
        null_se,
        withheld,
        dupes,
        len(pdfs),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
