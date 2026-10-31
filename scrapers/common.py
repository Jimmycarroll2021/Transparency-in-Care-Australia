"""Shared helpers for every collector in scrapers/.

Rules enforced here (see .claude/rules/data-pipeline.md):
- one named User-Agent with a contact address
- at least 1.5 seconds between requests to the same host (more if robots.txt asks)
- robots.txt is honoured for our own agent token and for "*"
- raw snapshots are new timestamped files under data/raw/<source>/, never overwritten
- every snapshot carries a sidecar .meta.json with url, headers of record and sha256
- approval numbers are normalised to SE-/PR- plus eight digits, original kept by the caller
"""

from __future__ import annotations

import csv
import hashlib
import json
import logging
import os
import re
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib import robotparser
from urllib.parse import unquote, urlsplit

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw"
EVIDENCE_DIR = PROJECT_ROOT / "data" / "evidence"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
# Codex round 5: set while scrapers/reparse_offline.py replaces data/processed; removed only after a
# fully successful run. Gitignored.
REPARSE_MARKER = PROJECT_ROOT / "data" / ".reparse-in-progress"

USER_AGENT = (
    "TransparencyInCareAustralia/0.1 "
    "(+https://github.com/Jimmycarroll2021/Transparency-in-Care-Australia; "
    "jimmisound@gmail.com)"
)
AGENT_TOKEN = "TransparencyInCareAustralia"
MIN_DELAY_SECONDS = 1.5
TIMEOUT_SECONDS = 60.0

log = logging.getLogger("scrapers")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

_last_request_at: dict[str, float] = {}
_robots: dict[str, robotparser.RobotFileParser | None] = {}
_crawl_delay: dict[str, float] = {}


class RobotsDisallowed(RuntimeError):
    """Raised when robots.txt disallows the URL for our agent."""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)  # noqa: UP017 (Python 3.10 support)


def utc_stamp(dt: datetime | None = None) -> str:
    """Snapshot stamp in the form 2026-10-29T0300Z (UTC, minute precision)."""
    return (dt or utc_now()).strftime("%Y-%m-%dT%H%MZ")


def _host(url: str) -> str:
    return urlsplit(url).netloc.lower()


def _load_robots(url: str, user_agent: str | None = None) -> robotparser.RobotFileParser | None:
    host = _host(url)
    if host in _robots:
        return _robots[host]
    parts = urlsplit(url)
    robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
    rp = robotparser.RobotFileParser()
    ua = user_agent or USER_AGENT
    try:
        resp = httpx.get(
            robots_url,
            headers={"User-Agent": ua},
            timeout=TIMEOUT_SECONDS,
            follow_redirects=True,
        )
        if resp.status_code == 200:
            rp.parse(resp.text.splitlines())
            delay = rp.crawl_delay(AGENT_TOKEN) or rp.crawl_delay("*")
            if delay:
                _crawl_delay[host] = float(delay)
            _robots[host] = rp
        else:
            # No robots.txt (404) or blocked (403): nothing to honour beyond our own delay.
            _robots[host] = None
    except httpx.HTTPError as exc:  # pragma: no cover - network dependent
        log.warning("robots.txt fetch failed for %s: %s", host, exc)
        _robots[host] = None
    return _robots[host]


def _respect_rate_limit(url: str) -> None:
    host = _host(url)
    delay = max(MIN_DELAY_SECONDS, _crawl_delay.get(host, 0.0))
    last = _last_request_at.get(host)
    if last is not None:
        wait = delay - (time.monotonic() - last)
        if wait > 0:
            time.sleep(wait)
    _last_request_at[host] = time.monotonic()


@dataclass
class Fetched:
    url: str
    final_url: str
    status: int
    content: bytes
    content_type: str | None
    last_modified: str | None
    etag: str | None
    fetched_at: str
    user_agent: str = USER_AGENT

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.content).hexdigest()


def fetch(
    url: str,
    *,
    retries: int = 2,
    allow_disallowed: bool = False,
    user_agent: str | None = None,
    redact: Callable[[str], str] | None = None,
) -> Fetched:
    """GET a URL politely. Raises RobotsDisallowed or httpx.HTTPStatusError.

    `redact` rewrites any text this function logs or raises itself (for example to strip an API
    key from a query string). The caller must still redact exceptions raised by httpx.
    """
    ua = user_agent or USER_AGENT
    shown = redact or (lambda text: text)
    rp = _load_robots(url, user_agent=ua)
    if rp is not None and not allow_disallowed:
        if not (rp.can_fetch(AGENT_TOKEN, url) and rp.can_fetch("*", url)):
            raise RobotsDisallowed(shown(f"robots.txt disallows {url} for {AGENT_TOKEN}"))

    attempt = 0
    while True:
        _respect_rate_limit(url)
        fetched_at = utc_now().isoformat()
        try:
            resp = httpx.get(
                url,
                headers={"User-Agent": ua, "Accept": "*/*"},
                timeout=TIMEOUT_SECONDS,
                follow_redirects=True,
            )
            resp.raise_for_status()
            return Fetched(
                url=url,
                final_url=str(resp.url),
                status=resp.status_code,
                content=resp.content,
                content_type=resp.headers.get("content-type"),
                last_modified=resp.headers.get("last-modified"),
                etag=resp.headers.get("etag"),
                fetched_at=fetched_at,
                user_agent=ua,
            )
        except httpx.HTTPError as exc:
            attempt += 1
            if attempt > retries:
                raise
            backoff = 2.0**attempt
            log.warning(
                "fetch failed (%s), retry %d in %.0fs: %s",
                shown(str(exc)),
                attempt,
                backoff,
                shown(url),
            )
            time.sleep(backoff)


def _unique_path(directory: Path, stem: str, ext: str) -> Path:
    """Never overwrite: if the minute stamp collides, add seconds, then a counter."""
    directory.mkdir(parents=True, exist_ok=True)
    candidate = directory / f"{stem}.{ext}"
    if not candidate.exists():
        return candidate
    seconds = utc_now().strftime("%S")
    candidate = directory / f"{stem}{seconds}.{ext}"
    n = 1
    while candidate.exists():
        candidate = directory / f"{stem}{seconds}-{n}.{ext}"
        n += 1
    return candidate


def write_snapshot(
    source: str,
    fetched: Fetched,
    ext: str,
    *,
    base_dir: Path = RAW_DIR,
    extra_meta: dict | None = None,
) -> Path:
    """Write data/raw/<source>/<stamp>.<ext> plus <stamp>.<ext>.meta.json. Returns the data path."""
    stamp = utc_stamp()
    path = _unique_path(base_dir / source, stamp, ext)
    path.write_bytes(fetched.content)
    meta = {
        "source": source,
        "url": fetched.url,
        "final_url": fetched.final_url,
        "status": fetched.status,
        "fetched_at": fetched.fetched_at,
        "content_type": fetched.content_type,
        "last_modified": fetched.last_modified,
        "etag": fetched.etag,
        "bytes": len(fetched.content),
        "sha256": fetched.sha256,
        "user_agent": fetched.user_agent,
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


def list_snapshots(source: str, *, base_dir: Path = RAW_DIR) -> list[Path]:
    """Data files for a source, oldest first (meta sidecars excluded)."""
    d = base_dir / source
    if not d.exists():
        return []
    return sorted(p for p in d.iterdir() if p.is_file() and not p.name.endswith(".meta.json"))


def known_hashes(source: str, *, base_dir: Path = RAW_DIR, key: str = "sha256") -> set[str]:
    """Hashes already archived for a source. `key` selects which sidecar field to read."""
    hashes: set[str] = set()
    d = base_dir / source
    if not d.exists():
        return hashes
    for meta in d.glob("*.meta.json"):
        try:
            hashes.add(json.loads(meta.read_text())[key])
        except (json.JSONDecodeError, KeyError):
            continue
    return hashes


_SE = re.compile(r"\bSE[\s_-]*0*(\d{1,8})\b", re.IGNORECASE)
_PR = re.compile(r"\bPR[\s_-]*0*(\d{1,8})\b", re.IGNORECASE)


def normalise_se(value: str | None) -> str | None:
    """'SE 00010955', 'se-10955', 'SE-00010955' -> 'SE-00010955'. None if absent."""
    if not value:
        return None
    m = _SE.search(value)
    return f"SE-{int(m.group(1)):08d}" if m else None


def normalise_pr(value: str | None) -> str | None:
    if not value:
        return None
    m = _PR.search(value)
    return f"PR-{int(m.group(1)):08d}" if m else None


def record_hash(*parts: str | None) -> str:
    """Stable id for a processed row, from the fields that identify the action."""
    joined = "\x1f".join("" if p is None else str(p).strip().lower() for p in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Withheld rows and record ids (CLAUDE.md rule 2)
# ---------------------------------------------------------------------------

DUPLICATE_NOTE = "duplicate row in source"
FREE_TEXT_WITHHELD_NOTE = "free text withheld: subject may be an individual"
# Columns that copy source prose. On a row whose subject or provider name is withheld they are
# blanked whole: redacting a name word by word leaks (initials, short names, spelling variants).
# action_type_raw is required and non-empty in the schema, so it becomes a fixed placeholder.
FREE_TEXT_COLUMNS = ("action_type_raw", "reason", "address", "linked_documents", "details")
ACTION_TYPE_RAW_WITHHELD = "(withheld)"


def withhold_free_text(row: dict, markers: tuple[str, ...] = ()) -> dict:
    """Blank every free-text column of a withheld row, in place, and set the fixed note.

    Structured columns stay: jurisdiction, dates, the normalised action type, SE-/PR- numbers
    (normalised and as printed), suburb, state, postcode, period label, and the source register,
    document and snapshot. legal_references becomes empty (a list stays a list, a JSON array
    string becomes "[]"). The notes become the parser's fixed markers (constant strings such as
    "provider name withheld", never source text), then the fixed FREE_TEXT_WITHHELD_NOTE, plus
    DUPLICATE_NOTE when the row had it, so duplicate counting still works.
    """
    had_duplicate = DUPLICATE_NOTE in (row.get("notes") or "")
    for col in FREE_TEXT_COLUMNS:
        if col in row:
            row[col] = ACTION_TYPE_RAW_WITHHELD if col == "action_type_raw" else None
    if "legal_references" in row:
        refs = row["legal_references"]
        if isinstance(refs, list):
            row["legal_references"] = []
        else:
            row["legal_references"] = "[]" if str(refs or "").startswith("[") else ""
    notes = [*markers, FREE_TEXT_WITHHELD_NOTE] + ([DUPLICATE_NOTE] if had_duplicate else [])
    row["notes"] = "; ".join(dict.fromkeys(notes))
    return row


PROSE_WITHHELD_NOTE = "free text withheld: may name an individual"
# Prose columns the shared rule checks on every row. The address is a printed premises
# locator, not prose: street and place names would trip the detector on most rows, and a
# withheld subject's address is already withheld whole by withhold_free_text.
PROSE_COLUMNS = ("action_type_raw", "reason", "details", "_details")


def _filter_refs(refs, flagged):
    """Drop legal reference items the detector flags; keep the column's type."""
    if isinstance(refs, list):
        kept = [r for r in refs if not flagged(r)]
        return kept, len(kept) != len(refs)
    text = str(refs or "")
    if not text:
        return refs, False
    if text.startswith("["):
        items = json.loads(text)
        kept = [r for r in items if not flagged(r)]
        return json.dumps(kept, ensure_ascii=False), len(kept) != len(items)
    items = text.split("; ")
    kept = [r for r in items if not flagged(r)]
    return "; ".join(kept), len(kept) != len(items)


# Codex round 3, finding 3: the run-wide set of personal names (profile_providers.PersonNames),
# in memory only. Set by reparse_offline across every register, or by ensure_person_names
# from the ACECQA register when one parser runs alone.
_PERSON_NAMES = None
# Raw subjects withheld so far in this process, as a PersonNames set (in memory only).
_RUN_NAMES = None


def note_withheld_subject(raw: str | None) -> None:
    """Remember, in memory only, the raw printed name of a subject a parser withheld or a
    person-level field it dropped, so the prose rule can find that name in other rows."""
    global _RUN_NAMES
    if not raw:
        return
    if _RUN_NAMES is None:
        from scrapers.profile_providers import PersonNames

        _RUN_NAMES = PersonNames()
    _RUN_NAMES.add_subject(raw)


def run_person_names():
    """The names noted so far in this process (in memory only), or None."""
    return _RUN_NAMES


def reset_run_names() -> None:
    global _RUN_NAMES
    _RUN_NAMES = None


def set_person_names(names) -> None:
    global _PERSON_NAMES
    _PERSON_NAMES = names


def ensure_person_names() -> None:
    """Load the ACECQA names when no run-wide set was given. Never written anywhere."""
    if _PERSON_NAMES is None:
        from scrapers.profile_providers import acecqa_person_names

        set_person_names(acecqa_person_names())


URL_WITHHELD_NOTE = "source URL withheld: may name an individual"
# Columns holding URLs (linked_documents holds several, separated by spaces). A URL is never
# altered: it is kept whole or nulled (Codex round 4, finding 1).
URL_COLUMNS = ("source_document", "linked_documents")
_URL_SEPARATORS = re.compile(r"[-_./+=&?~:;,\\\s]+")
# Codex round 6: snapshot and raw paths (their file names are slugs of document URLs).
SNAPSHOT_WITHHELD_NOTE = "source snapshot path withheld: may name an individual"
SNAPSHOT_TEXT_WITHHELD = "(source snapshot path withheld: may name an individual)"
SNAPSHOT_COLUMNS = ("source_snapshot",)
_SCHEME = re.compile(r"(?i)^https?://")
_URL_LIST_SPLIT = re.compile(r"\s+(?=https?://)", re.IGNORECASE)


def _url_words(url: str) -> str:
    """The decoded path and query of a URL as words: '/docs/Notice-to-Jane%20Example.pdf' ->
    'docs Notice to Jane Example pdf'. The host is left out (it names the regulator). A
    path without a scheme (a snapshot or raw path) is split the same way, whole: every
    segment and the file-name stem, on - _ . / \\ and spaces."""
    if not _SCHEME.match(url):
        return _URL_SEPARATORS.sub(" ", unquote(url)).strip()
    parts = urlsplit(url)
    return _URL_SEPARATORS.sub(" ", f"{unquote(parts.path)} {unquote(parts.query)}").strip()


URL_TEXT_WITHHELD = "(URL withheld: may name an individual)"
# A URL, or a path or file name of a document, inside free text (summaries, notes, log lines).
# Codex round 6: a URL or path whose file name holds spaces is matched (and checked) whole.
_EXT = r"\.(?:pdf|docx?|html?|json|csv|xlsx?|txt)\b"
_TOKEN = r"[^\s'\",;()\[\]<>]+"
# Follow-up to PR #6: a query string after a document name is part of the URL, and a path may
# hold folder names with spaces. _SEG is one path segment with no space.
# PR #7 round 1: a query may hold commas (ids=1,2); a comma or full stop that ends the
# sentence is trimmed off the match in redact_urls.
_QUERY = r"(?:[?#][^\s'\"();\[\]<>]*)?"
_EXT_Q = _EXT + _QUERY
_SEG = r"[^\s'\",;()\[\]<>:/\\?#]+"
_SPACED_SEG = _SEG + r"(?:[ ]" + _SEG + r"){0,4}"
_URL_IN_TEXT = re.compile(
    # A URL ending in a document name (and any query) with no space: matched first, so it
    # never runs on into the following words.
    r"https?://[^\s'\",;()\[\]<>?#]+?"
    + _EXT_Q
    # A URL whose folder or document names hold spaces.
    + r"|https?://"
    + _TOKEN
    + r"(?:[ ]"
    + _TOKEN
    + r"){1,8}?"
    + _EXT_Q
    + r"|https?://[^\s'\",;()\[\]<>?#]+"
    + _QUERY
    # A path whose folder or file names hold spaces: a first segment with no space, then two or
    # more segments, so that prose such as 'PDF/Word files ... robots.txt' (one slash) is not
    # taken for a path.
    + r"|"
    + _SEG
    + r"[/\\](?:"
    + _SPACED_SEG
    + r"[/\\])+"
    + _SEG
    + r"(?:[ ]"
    + _SEG
    + r"){0,8}?"
    + _EXT_Q
    # A path or file name with no spaces (PR #7 round 1: with any query after it).
    + r"|[^\s'\",;()\[\]<>:?#]+"
    + _EXT_Q,
    re.IGNORECASE,
)


def _run_wide_names():
    from scrapers.profile_providers import PersonNames

    names = PersonNames()
    for base in (_PERSON_NAMES, _RUN_NAMES):
        if base is not None:
            names.update(base)
    return names


def url_may_name_person(url: str | None, names=None) -> bool:
    """True when a URL's (or a path's) decoded path and file name may name an individual, by the
    person detector or the run-wide name set (Codex round 4 and 5)."""
    if not url:
        return False
    from scrapers.profile_providers import prose_may_name_person

    names = _run_wide_names() if names is None else names
    return any(prose_may_name_person(part, (), names) for part in _location_parts(url))


def _location_parts(value: str) -> list[str]:
    """The words to check for a URL or path (follow-up to PR #6): the whole value, every path
    segment and every query parameter value, each split the same way (on - _ . / backslash, +
    and spaces, after percent-decoding)."""
    parts = [_url_words(value)]
    if _SCHEME.match(value):
        split = urlsplit(value)
        path, query = split.path, split.query
    else:
        path, _, query = value.partition("?")
    for segment in re.split(r"[/\\]", unquote(path)):
        if segment:
            parts.append(_URL_SEPARATORS.sub(" ", segment).strip())
    for pair in query.split("&"):
        key, _, val = pair.partition("=")
        for item in (key, val):
            if item:
                parts.append(_URL_SEPARATORS.sub(" ", unquote(item.replace("+", " "))).strip())
    return [p for p in parts if p]


def redact_urls(text: str | None, names=None) -> str | None:
    """Replace, whole, every URL or document path in `text` that may name an individual with
    URL_TEXT_WITHHELD. Other text is unchanged. For summaries, provenance notes and logs."""
    if not text:
        return text
    names = _run_wide_names() if names is None else names

    def replace(m):
        # A comma or full stop that ends the sentence is not part of the URL (PR #7 round 1).
        found = m.group(0)
        value = found.rstrip(".,")
        tail = found[len(value) :]
        if not value or not url_may_name_person(value, names):
            return found
        return (URL_TEXT_WITHHELD if _SCHEME.match(value) else SNAPSHOT_TEXT_WITHHELD) + tail

    return _URL_IN_TEXT.sub(replace, text)


def redact_urls_in_obj(obj, names=None):
    """redact_urls applied to every string (dictionary keys included) in a JSON-like object."""
    names = _run_wide_names() if names is None else names
    if isinstance(obj, str):
        return redact_urls(obj, names)
    if isinstance(obj, dict):
        return {redact_urls_in_obj(k, names): redact_urls_in_obj(v, names) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [redact_urls_in_obj(v, names) for v in obj]
    return obj


class _UrlRuleLogFilter(logging.Filter):
    """Applies the URL rule to every log line of the scrapers logger."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True
        redacted = redact_urls(message)
        if redacted != message:
            record.msg, record.args = redacted, None
        return True


log.addFilter(_UrlRuleLogFilter())


def _add_note(row: dict, note: str) -> None:
    notes = row.get("notes") or ""
    sep = " | " if " | " in notes else "; "
    segments = [seg for seg in notes.split(sep) if seg] if notes else []
    row["notes"] = sep.join(dict.fromkeys([*segments, note]))


def _withhold_locations(row: dict, flagged, counts: dict[str, int]) -> None:
    """Keep each URL or snapshot path whole or null it (Codex rounds 4 and 6)."""
    url_hit = False
    for col in URL_COLUMNS:
        value = row.get(col)
        if not isinstance(value, str) or not value:
            continue
        urls = _URL_LIST_SPLIT.split(value.strip()) if col == "linked_documents" else [value]
        kept_urls = [u for u in urls if not any(flagged(p) for p in _location_parts(u))]
        if len(kept_urls) != len(urls):
            row[col] = " ".join(kept_urls) or None
            counts[col] = counts.get(col, 0) + 1
            url_hit = True
    if url_hit:
        _add_note(row, URL_WITHHELD_NOTE)
    for col in SNAPSHOT_COLUMNS:
        value = row.get(col)
        if isinstance(value, str) and value and any(flagged(p) for p in _location_parts(value)):
            row[col] = None
            counts[col] = counts.get(col, 0) + 1
            _add_note(row, SNAPSHOT_WITHHELD_NOTE)


def withhold_source_locations(rows: list[dict], person_names=None) -> dict[str, int]:
    """The URL and snapshot-path rule alone, for rows that have no prose (count tables)."""
    from scrapers.profile_providers import prose_may_name_person

    names = _run_wide_names()
    if person_names is not None:
        names.update(person_names)
    counts: dict[str, int] = {}
    for row in rows:
        _withhold_locations(
            row, lambda t: isinstance(t, str) and prose_may_name_person(t, (), names), counts
        )
    return counts


def withhold_prose_naming_people(rows: list[dict], person_names=None) -> dict[str, int]:
    """The shared prose rule, on every row, in place (Codex round 2, finding 1).

    For each prose field, if the shared person detector (profile_providers.
    prose_may_name_person) finds a possible personal name, the field is nulled
    (action_type_raw becomes the '(withheld)' placeholder, because the schema requires it), a
    flagged legal reference or notes segment is dropped, and the fixed PROSE_WITHHELD_NOTE is
    added once. Rows already withheld whole are skipped. Returns counts of fields nulled."""
    from scrapers.profile_providers import PersonNames, prose_may_name_person

    # The run-wide names plus the raw subjects withheld in these rows (in memory only).
    names = PersonNames()
    for base in (person_names, _PERSON_NAMES, _RUN_NAMES):
        if base is not None:
            names.update(base)
    for row in rows:
        names.add_subject(row.get("_subject_raw"))
        for extra in row.get("_person_raw") or ():
            names.add_subject(extra)

    counts: dict[str, int] = {}
    for row in rows:
        # PR #12 round 6: a structured value is exempt (stripped before the check) only when the
        # shared name rule would publish it; a service, provider or trading name it would
        # withhold stays in the text, so the detector sees it.
        known = tuple(
            v
            for v in (row.get("service_name"), row.get("provider_name"), row.get("trading_name"))
            if not name_may_name_person_in_row(v, row, names)
        ) + (row.get("suburb"),)

        def flagged(text, known=known):
            return isinstance(text, str) and prose_may_name_person(text, known, names)

        # URLs and snapshot paths, on every row (withheld rows too): kept whole or nulled.
        _withhold_locations(row, flagged, counts)

        notes = row.get("notes") or ""
        if FREE_TEXT_WITHHELD_NOTE in notes:
            continue

        hit = False
        for col in PROSE_COLUMNS:
            value = row.get(col)
            if value == ACTION_TYPE_RAW_WITHHELD or not flagged(value):
                continue
            row[col] = ACTION_TYPE_RAW_WITHHELD if col == "action_type_raw" else None
            name = col.lstrip("_")
            counts[name] = counts.get(name, 0) + 1
            hit = True
        if "legal_references" in row:
            refs, dropped = _filter_refs(row["legal_references"], flagged)
            if dropped:
                row["legal_references"] = refs
                counts["legal_references"] = counts.get("legal_references", 0) + 1
                hit = True
        sep = " | " if " | " in notes else "; "
        segments = [seg for seg in notes.split(sep) if seg] if notes else []
        kept = [seg for seg in segments if not flagged(seg)]
        if len(kept) != len(segments):
            counts["notes"] = counts.get("notes", 0) + 1
            hit = True
        if hit:
            row["notes"] = sep.join(dict.fromkeys([*kept, PROSE_WITHHELD_NOTE]))
    return counts


# ---------------------------------------------------------------------------
# Name rule (PR #12): trading names and service names in every processed output.
# ---------------------------------------------------------------------------

TRADING_NAME_WITHHELD_NOTE = "trading name withheld: may name an individual"
SERVICE_NAME_WITHHELD_NOTE = "service name withheld: may name an individual"
BUSINESS_NAME_WITHHELD_NOTE = "business name withheld: may name an individual"
# Output columns holding a trading name or a service name, and the fixed note for each.
# spine-unlisted.csv 'name' is a service name only on rows of kind 'service' (a provider stub's
# name already follows the provider-name rule); stub_name_variants holds the other printed names
# of the same key, separated by NAME_VARIANT_SEPARATOR. business_names (provider-abn.csv,
# abn-details.csv) holds ABR business names, which are trading names, separated by '; '
# (PR #12 round 2).
NAME_COLUMN_NOTES = {
    "trading_name": TRADING_NAME_WITHHELD_NOTE,
    "service_name": SERVICE_NAME_WITHHELD_NOTE,
    "acecqa_service_name": SERVICE_NAME_WITHHELD_NOTE,
    "name": SERVICE_NAME_WITHHELD_NOTE,
    "stub_name_variants": SERVICE_NAME_WITHHELD_NOTE,
    "business_names": BUSINESS_NAME_WITHHELD_NOTE,
}
NAME_VARIANT_SEPARATOR = " | "
# Columns holding a list of names, and the separator of each. An entry that fires is dropped.
NAME_LIST_SEPARATORS = {"stub_name_variants": NAME_VARIANT_SEPARATOR, "business_names": "; "}


class _InMemory(dict):
    """A dict of printed names that must never be serialised."""

    def __reduce__(self):
        raise TypeError("in memory only and cannot be serialised")


# In memory only: the ACECQA name context (profile_providers.AcecqaNameContext), the casefolded
# names withheld so far in this process (one name withheld in one output is withheld in every
# output), and the values withheld from each written output by (output name, row index), so that
# a later step in the same run (the join) can match on them without ever publishing them.
_NAME_CONTEXT = None
_WITHHELD_NAME_STRINGS: set[str] = set()
_WITHHELD_NAME_VALUES: _InMemory = _InMemory()


def set_name_context(ctx) -> None:
    global _NAME_CONTEXT
    _NAME_CONTEXT = ctx


def reset_withheld_names() -> None:
    """Forget the name context and every withheld name held in memory."""
    global _NAME_CONTEXT
    _NAME_CONTEXT = None
    _WITHHELD_NAME_STRINGS.clear()
    _WITHHELD_NAME_VALUES.clear()


# The context last loaded from disk, with the size and mtime of the files it came from, so that a
# reset (reset_withheld_names) does not re-read unchanged ACECQA tables. In memory only.
_LOADED_CONTEXT: tuple | None = None


def _context_source_key() -> tuple:
    from scrapers.profile_providers import PROVIDER_ABN_CSV, PROVIDERS_CSV, SERVICES_CSV

    key = []
    for path in (PROVIDERS_CSV, SERVICES_CSV, PROVIDER_ABN_CSV):
        try:
            st = path.stat()
            key.append((str(path), st.st_size, st.st_mtime_ns))
        except OSError:
            key.append((str(path), None, None))
    return tuple(key)


def ensure_name_context():
    """Load the ACECQA name context when none was set. Never written anywhere."""
    global _LOADED_CONTEXT
    if _NAME_CONTEXT is None:
        from scrapers.profile_providers import acecqa_name_context

        source = _context_source_key()
        if _LOADED_CONTEXT is None or _LOADED_CONTEXT[0] != source:
            _LOADED_CONTEXT = (source, acecqa_name_context())
        set_name_context(_LOADED_CONTEXT[1])
    return _NAME_CONTEXT


def _name_key(value: str) -> str:
    return " ".join(value.casefold().split())


def note_withheld_name(value: str | None) -> None:
    """Remember, in memory only, a trading or service name withheld outside the output rule
    (an ABR business name dropped by abn_lookup.safe_business_names), so that every output
    written later in this process withholds the same name."""
    if isinstance(value, str) and value.strip():
        _WITHHELD_NAME_STRINGS.add(_name_key(value))


def name_may_name_person_in_row(value: str | None, row: dict | None = None, names=None) -> bool:
    """The shared person check (profile_providers.name_may_name_person) for one trading or
    service name, with the run-wide names, the ACECQA context and the row's own withheld provider
    or subject (in memory only). A name already withheld in this process is withheld again."""
    if not isinstance(value, str) or not value.strip():
        return False
    key = _name_key(value)
    if key in _WITHHELD_NAME_STRINGS:
        return True
    from scrapers.profile_providers import PersonNames, name_may_name_person

    ctx = ensure_name_context()
    if key in ctx.flagged:
        return True
    names = _run_wide_names() if names is None else names
    row = row or {}
    own = ctx.own_names(
        row.get("provider_approval_number"), row.get("acecqa_provider_approval_number")
    )
    subjects = PersonNames()
    subjects.add_subject(row.get("_subject_raw"))
    for extra in row.get("_person_raw") or ():
        subjects.add_subject(extra)
    own.update(subjects)
    return name_may_name_person(value, names, own, ctx.ordinary)


def _name_note_column(col: str, fieldnames: list[str]) -> str:
    for candidate in (f"{col}_note", "notes", "note"):
        if candidate in fieldnames:
            return candidate
    return f"{col}_note"


def _append_note(row: dict, column: str, note: str) -> None:
    value = row.get(column) or ""
    sep = " | " if " | " in value else "; "
    segments = [seg for seg in value.split(sep) if seg] if value else []
    row[column] = sep.join(dict.fromkeys([*segments, note]))


def withhold_person_named_names(
    output: str, rows: list[dict], fieldnames: list[str], names=None
) -> tuple[list[dict], list[str], dict[str, int]]:
    """Apply the name rule to every trading-name and service-name column of an output.

    Returns (rows, fieldnames, counts). A row with a withheld name is copied: the caller's rows
    are not changed. The value becomes null, the fixed note goes to the column's own *_note
    column, else the row's notes or note column (a *_note column is added to fieldnames when the
    output has none). A stub_name_variants entry that fires is dropped. Approval numbers stay.
    The withheld values are kept in memory only (by output and row index) for the join."""
    cols = [c for c in NAME_COLUMN_NOTES if c in fieldnames]
    counts: dict[str, int] = {}
    if not has_name_rule_columns(fieldnames):
        return rows, fieldnames, counts
    names = _run_wide_names() if names is None else names
    fieldnames = list(fieldnames)

    def decide(row: dict) -> tuple[dict[str, object], dict[str, str]]:
        changed: dict[str, object] = {}
        withheld: dict[str, str] = {}
        is_service_stub = row.get("kind") == "service"
        for col in cols:
            value = row.get(col)
            if not isinstance(value, str) or not value.strip():
                continue
            if col in ("name", "stub_name_variants") and not is_service_stub:
                continue
            if col in NAME_LIST_SEPARATORS:
                sep = NAME_LIST_SEPARATORS[col]
                parts = [p for p in value.split(sep) if p]
                kept = [p for p in parts if not name_may_name_person_in_row(p, row, names)]
                if len(kept) == len(parts):
                    continue
                for p in parts:
                    if p not in kept:
                        _WITHHELD_NAME_STRINGS.add(_name_key(p))
                changed[col] = sep.join(kept) or None
            elif name_may_name_person_in_row(value, row, names):
                _WITHHELD_NAME_STRINGS.add(_name_key(value))
                changed[col] = None
            else:
                continue
            withheld[col] = value
        return changed, withheld

    # Fixed point (PR #12 round 1): every row and every column is decided again until no new
    # withheld name appears, so a name withheld on a later row is withheld on an earlier row too.
    while True:
        before = len(_WITHHELD_NAME_STRINGS)
        decisions = [decide(row) for row in rows]
        if len(_WITHHELD_NAME_STRINGS) == before:
            break
    out: list[dict] = []
    for index, (row, (changed, withheld)) in enumerate(zip(rows, decisions, strict=True)):
        if not changed:
            out.append(row)
            continue
        new = dict(row)
        new.update(changed)
        for col in withheld:
            counts[col] = counts.get(col, 0) + 1
            column = _name_note_column(col, fieldnames)
            if column not in fieldnames:
                fieldnames.append(column)
            _append_note(new, column, NAME_COLUMN_NOTES[col])
        if "name" in withheld and "name_withheld" in new:
            new["name_withheld"] = "true"
        for col, sep in NAME_LIST_SEPARATORS.items():
            count_col = f"{col}_withheld"
            if col in withheld and count_col in new:
                dropped = len([p for p in withheld[col].split(sep) if p]) - len(
                    [p for p in (new.get(col) or "").split(sep) if p]
                )
                try:
                    new[count_col] = int(new.get(count_col) or 0) + dropped
                except ValueError:
                    new[count_col] = dropped
        previous = _WITHHELD_NAME_VALUES.get((output, index))
        if previous is not None and previous[0] == row.get("record_id"):
            withheld = {**withheld, **previous[1]}  # a later pass keeps the first values
        _WITHHELD_NAME_VALUES[(output, index)] = (row.get("record_id"), _InMemory(withheld))
        out.append(new)
    out = _withhold_prose_repeating_withheld_names(out, fieldnames, counts)
    return out, fieldnames, counts


# PR #12 round 6: free-text columns scanned for any withheld trading, service or business name.
PROSE_SCAN_COLUMNS = (
    "action_type_raw",
    "reason",
    "details",
    "description",
    "address",
    "legal_references",
    "notes",
)
_HYPHENS = re.compile("[-\u2010\u2011\u2012\u2013\u2014]")  # hyphen and dash characters


def _prose_norm(text: str) -> str:
    return " ".join(_HYPHENS.sub(" ", text.casefold()).split())


def has_name_rule_columns(fieldnames) -> bool:
    return any(c in fieldnames for c in NAME_COLUMN_NOTES) or any(
        c in fieldnames for c in PROSE_SCAN_COLUMNS if c != "notes"
    )


def _withheld_name_matcher():
    """A whole-word, case-insensitive matcher (spacing and hyphens normalised) for every name
    withheld so far in this process, or None when there is none. In memory only."""
    keys = sorted({_prose_norm(k) for k in _WITHHELD_NAME_STRINGS if len(k.strip()) >= 4})
    keys = [k for k in keys if k]
    if not keys:
        return None
    keys.sort(key=len, reverse=True)
    pattern = re.compile(r"(?<!\w)(?:" + "|".join(re.escape(k) for k in keys) + r")(?!\w)")
    return lambda text: isinstance(text, str) and bool(pattern.search(_prose_norm(text)))


def _withhold_prose_repeating_withheld_names(
    rows: list[dict], fieldnames: list[str], counts: dict[str, int]
) -> list[dict]:
    """Null any free-text cell that repeats a withheld name (whole word), with the fixed
    PROSE_WITHHELD_NOTE. action_type_raw becomes the placeholder; a flagged legal reference or
    notes segment is dropped. Changed rows are copied."""
    cols = [c for c in PROSE_SCAN_COLUMNS if c in fieldnames]
    flagged = _withheld_name_matcher() if cols else None
    if flagged is None:
        return rows
    note_col = "notes" if "notes" in fieldnames else ("note" if "note" in fieldnames else None)
    out: list[dict] = []
    for row in rows:
        new = None
        for col in cols:
            value = row.get(col)
            if not value or value == ACTION_TYPE_RAW_WITHHELD:
                continue
            if col == "legal_references":
                refs, dropped = _filter_refs(value, flagged)
                if not dropped:
                    continue
                replacement = refs
            elif col == "notes":
                sep = " | " if " | " in value else "; "
                segments = [seg for seg in value.split(sep) if seg]
                kept = [seg for seg in segments if not flagged(seg)]
                if len(kept) == len(segments):
                    continue
                replacement = sep.join(kept) or None
            elif flagged(value):
                replacement = ACTION_TYPE_RAW_WITHHELD if col == "action_type_raw" else None
            else:
                continue
            new = new or dict(row)
            new[col] = replacement
            counts[col] = counts.get(col, 0) + 1
        if new is None:
            out.append(row)
            continue
        if note_col is None:
            note_col = "notes"
            fieldnames.append(note_col)
        _append_note(new, note_col, PROSE_WITHHELD_NOTE)
        out.append(new)
    return out


def restore_withheld_names(output: str, rows: list[dict]) -> int:
    """For a later step in the same run: put back, in memory only, the names withheld from the
    rows of `output` as written, so that a name match still works. The restored rows keep the
    fixed note, and every value restored is withheld again when written (it is remembered as
    withheld). Returns the number of rows restored. A row whose record_id does not agree is
    left as read."""
    restored = 0
    for index, row in enumerate(rows):
        entry = _WITHHELD_NAME_VALUES.get((output, index))
        if not entry:
            continue
        record_id, held = entry
        if (row.get("record_id") or None) != (record_id or None):
            continue
        for col, value in held.items():
            if col in row and not row.get(col):
                row[col] = value
        restored += 1
    return restored


def unrestored_withheld_names(rows: list[dict], column: str = "service_name") -> int:
    """Rows whose `column` was withheld by the name rule and is still null (no value in memory,
    as when the join runs on its own): their name match is not possible."""
    note = NAME_COLUMN_NOTES[column]
    return sum(1 for r in rows if not r.get(column) and note in (r.get("notes") or ""))


_INVISIBLE_CHARS = re.compile("[​‌‍⁠﻿]")


def printed_fingerprint(*texts: str | None) -> str:
    """Hash of a row's full printed source text: every printed field, whitespace collapsed,
    zero-width characters removed, case folded. The text is already public in data/raw; only
    the hash is kept, in memory, and it is never written as text."""
    parts = [re.sub(r"\s+", " ", _INVISIBLE_CHARS.sub("", t or "")).strip() for t in texts]
    return record_hash(*parts)


def assign_record_ids(rows: list[dict], source_id: str | None = None) -> None:
    """Give each row a record_id, in place: hash(jurisdiction, source document, printed-text
    hash), then hash(that, occurrence).

    The printed-text hash is each row's _fingerprint (printed_fingerprint of every printed
    field). There is no source-order ordinal: reordering rows, or inserting a row, never moves
    an id. Only rows whose printed text is fully identical share a base; they get an occurrence
    counter 1, 2, ... and, being identical, are interchangeable. The id never depends on what is
    published (a name shown or withheld). source_id is the document parsed (defaults to each
    row's source_document).
    """
    seen: dict[str, int] = {}
    for row in rows:
        base = record_hash(
            row.get("jurisdiction"), source_id or row.get("source_document"), row["_fingerprint"]
        )
        seen[base] = seen.get(base, 0) + 1
        row["record_id"] = record_hash(base, str(seen[base]))


@contextmanager
def atomic_open(path: Path, newline: str | None = None) -> Iterator:
    """Open a temporary file next to `path` for writing; on a clean exit flush, fsync and
    os.replace it over `path`. On any error the temporary file is removed and `path` is left
    exactly as it was, so no output is ever half-written (Codex round 5)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline=newline) as fh:
            yield fh
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def atomic_write_text(path: Path, text: str, newline: str | None = None) -> None:
    with atomic_open(path, newline=newline) as fh:
        fh.write(text)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path = Path(path)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


BACKUP_MANIFEST = "MANIFEST.json"


class BackupInvalid(RuntimeError):
    """A reparse backup that does not match its manifest. Nothing may be restored from it."""


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_backup(backup: Path) -> list[str]:
    """Problems found when checking a reparse backup against its manifest (relative path, size
    and sha256 of every file). An empty list means the backup is complete and intact."""
    backup = Path(backup)
    manifest_path = backup / BACKUP_MANIFEST
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        entries = manifest["files"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return [f"manifest missing or unreadable ({type(exc).__name__})"]
    problems: list[str] = []
    for entry in entries:
        path = backup / entry["path"]
        if not path.is_file():
            problems.append(f"{entry['path']}: missing")
        elif path.stat().st_size != entry["size"]:
            problems.append(f"{entry['path']}: size differs")
        elif file_sha256(path) != entry["sha256"]:
            problems.append(f"{entry['path']}: sha256 differs")
    return problems


def _marker_backup() -> Path | None:
    try:
        for line in REPARSE_MARKER.read_text(encoding="utf-8").splitlines():
            if line.startswith("backup: "):
                return Path(line[len("backup: ") :].strip())
    except OSError:
        return None
    return None


def reparse_recovery_message() -> str | None:
    """Recovery instructions when an interrupted reparse_offline run left its marker, else None.
    The backup is offered only after it verifies against its manifest (Codex round 6)."""
    if not REPARSE_MARKER.exists():
        return None
    backup = _marker_backup()
    problems = verify_backup(backup) if backup is not None else ["no backup named in the marker"]
    head = (
        f"An earlier scrapers/reparse_offline.py run did not finish (marker {REPARSE_MARKER}). "
        "data/processed may be partly replaced. "
    )
    if problems:
        return head + (
            f"The backup {backup} failed verification against its manifest "
            f"({'; '.join(problems[:3])}). Do not copy anything from it. Run "
            "`git checkout -- data/processed`, then remove any untracked files under "
            "data/processed (git status shows them), delete the marker and run again."
        )
    return head + (
        f"The backup {backup} is verified against its manifest {backup / BACKUP_MANIFEST}. "
        "Recover first: either copy the files listed in the manifest from that backup into "
        "data/processed, or run `git checkout -- data/processed`. Then remove any untracked "
        "files under data/processed (git status shows them), delete the marker and run again."
    )


def refuse_if_reparse_incomplete() -> bool:
    """True (and print why) when an interrupted reparse left data/processed in doubt."""
    message = reparse_recovery_message()
    if message is None:
        return False
    log.error("refusing to run: %s", message)
    print(message)
    return True


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    with atomic_open(path, newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: ("" if row.get(k) is None else row.get(k)) for k in fieldnames})


def refilter_processed_names(names: list[str] | None = None) -> dict[str, dict[str, int]]:
    """Make the name rule order independent across outputs (PR #12 round 1).

    After every output of a run is written, the name rule is applied again to each processed CSV
    named in `names` (default: every CSV in data/processed) that has a trading-name or
    service-name column, now with every name withheld anywhere in this process. A file that
    changes is rewritten atomically, with the same writer, and the counts in its provenance file
    are raised; the other provenance fields stay. Passes repeat until no file changes (a fixed
    point). Returns the cells newly withheld per output and column. Counts only are logged."""
    ensure_person_names()
    targets = names if names is not None else sorted(p.stem for p in PROCESSED_DIR.glob("*.csv"))
    added: dict[str, dict[str, int]] = {}
    while True:
        changed = False
        for name in targets:
            path = PROCESSED_DIR / f"{name}.csv"
            if not path.exists():
                continue
            with path.open(newline="", encoding="utf-8") as fh:
                reader = csv.DictReader(fh)
                fieldnames = list(reader.fieldnames or [])
                rows = list(reader)
            if not has_name_rule_columns(fieldnames):
                continue
            rows, fieldnames, counts = withhold_person_named_names(name, rows, fieldnames)
            if not counts:
                continue
            changed = True
            _write_csv(path, rows, fieldnames)
            sidecar = PROCESSED_DIR / f"{name}.provenance.json"
            if sidecar.exists():
                prov = json.loads(sidecar.read_text(encoding="utf-8"))
                block = prov.setdefault(
                    "names_withheld",
                    {
                        "rule": "trading, service and business names withheld when they may name "
                        "an individual, and free text repeating a withheld name "
                        "(scrapers.common.withhold_person_named_names)",
                        "counts": {},
                    },
                )
                for col, n in counts.items():
                    block["counts"][col] = block["counts"].get(col, 0) + n
                block["counts"] = dict(sorted(block["counts"].items()))
                atomic_write_text(sidecar, json.dumps(prov, indent=2) + "\n")
            for col, n in counts.items():
                added.setdefault(name, {})
                added[name][col] = added[name].get(col, 0) + n
            log.info("%s: names withheld by the cross-output pass %s", name, counts)
        if not changed:
            return added


def write_processed(
    name: str,
    rows: list[dict],
    fieldnames: list[str],
    *,
    raw_inputs: list[Path],
    schema: str | None = None,
    notes: str | None = None,
) -> Path:
    """Write data/processed/<name>.csv and <name>.provenance.json listing the raw inputs used.

    Every trading-name and service-name column passes the shared name rule first (PR #12,
    withhold_person_named_names); the caller's rows are not changed."""
    names_withheld: dict[str, int] | None = None
    if has_name_rule_columns(fieldnames):
        ensure_person_names()
        rows, fieldnames, names_withheld = withhold_person_named_names(name, rows, fieldnames)
        if names_withheld:
            log.info("%s: names withheld by the name rule %s", name, names_withheld)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    out = PROCESSED_DIR / f"{name}.csv"
    _write_csv(out, rows, fieldnames)
    provenance = {
        "output": out.relative_to(PROJECT_ROOT).as_posix(),
        "written_at": utc_now().isoformat(),
        "rows": len(rows),
        "schema": schema,
        "raw_inputs": [
            SNAPSHOT_TEXT_WITHHELD if url_may_name_person(rel) else rel
            for rel in (p.relative_to(PROJECT_ROOT).as_posix() for p in raw_inputs)
        ],
        "notes": notes,
    }
    if names_withheld is not None:
        # Counts only, never a name.
        provenance["names_withheld"] = {
            "rule": "trading, service and business names withheld when they may name an individual, "
            "and free text repeating a withheld name "
            "(scrapers.common.withhold_person_named_names)",
            "counts": dict(sorted(names_withheld.items())),
        }
    # Codex round 5: no URL or path that may name an individual reaches a provenance file.
    provenance = redact_urls_in_obj(provenance)
    atomic_write_text(
        PROCESSED_DIR / f"{name}.provenance.json", json.dumps(provenance, indent=2) + "\n"
    )
    log.info("processed %s (%d rows)", out.relative_to(PROJECT_ROOT), len(rows))
    return out
