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
import hmac
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


# Name normalisation for the enforcement join (moved here from join_enforcement so that the
# parsers' name keys use exactly the join's normalisation; join_enforcement re-exports them).
_NAME_STOPWORDS = {"PTY", "LTD", "LIMITED", "INC", "THE"}


def normalise_service_name(name: str | None) -> str:
    """Upper case, drop apostrophes, other punctuation to space, drop corporate words, collapse."""
    if not name:
        return ""
    text = name.upper().replace("&", " AND ")
    text = re.sub(r"['’`]", "", text)
    text = re.sub(r"[^A-Z0-9 ]+", " ", text)
    words = [w for w in text.split() if w not in _NAME_STOPWORDS]
    return " ".join(words)


def normalise_provider_name(name: str | None) -> str:
    """Upper case; strip punctuation; collapse spaces; drop a trailing ABN; canonicalise suffixes.

    PTY LTD / PTY LIMITED / PROPRIETARY LIMITED -> PTY LTD, LIMITED -> LTD, INCORPORATED -> INC,
    leading THE dropped. ATF and trust names are kept intact.
    """
    if not name:
        return ""
    text = name.upper().replace("&", " AND ")
    text = re.sub(r"['’`]", "", text)
    text = re.sub(r"[^A-Z0-9 ]+", " ", text)
    text = " ".join(text.split())
    text = re.sub(r"\s*\bABN\b.*$", "", text)
    text = re.sub(r"\b(?:PTY LIMITED|PROPRIETARY LIMITED|PTY LTD)\b", "PTY LTD", text)
    text = re.sub(r"\bLIMITED\b", "LTD", text)
    text = re.sub(r"\bINCORPORATED\b", "INC", text)
    text = re.sub(r"^THE\s+", "", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Keyed names for the join (PR #11): a withheld name is kept internally only as a keyed hash
# ---------------------------------------------------------------------------

JOIN_KEY_VAR = "TICA_JOIN_KEY"
ENV_FILE = PROJECT_ROOT / ".env"
NAME_KEY_COLUMNS = ["record_id", "provider_key", "service_key"]
# The first data row of every sidecar: a keyed constant, so a sidecar written with another key is
# detected. It reveals nothing about the key or any name.
KEY_CHECK_ID = "__key_check__"
_KEY_CHECK_TEXT = "tica-join-key-check"


class JoinKeyMissing(RuntimeError):
    pass


def name_keys_dir() -> Path:
    """data/private/name-keys, beside data/processed (gitignored). Holds (record_id, keyed
    provider name, keyed service name) for rows whose names a parser withheld. Never a name in
    plain text; never published."""
    return PROCESSED_DIR.parent / "private" / "name-keys"


def load_join_key(env_file: Path | None = None, environ=None) -> bytes | None:
    """TICA_JOIN_KEY from the environment, else from .env, as bytes. Never printed or logged."""
    environ = os.environ if environ is None else environ
    value = (environ.get(JOIN_KEY_VAR) or "").strip()
    env_file = ENV_FILE if env_file is None else env_file
    if not value and env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("export "):
                line = line[len("export ") :].strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, _, val = line.partition("=")
            if name.strip() == JOIN_KEY_VAR:
                value = val.strip().strip("\"'").strip()
                break
    if not value:
        return None
    try:
        key = bytes.fromhex(value)
    except ValueError:
        raise JoinKeyMissing(f"{JOIN_KEY_VAR} is not hex") from None
    if len(key) < 32:
        raise JoinKeyMissing(f"{JOIN_KEY_VAR} is shorter than 32 bytes")
    return key


def name_key(normalised: str | None, key: bytes) -> str | None:
    """HMAC-SHA256 of an already normalised name under the join key, or None when empty."""
    if not normalised:
        return None
    return hmac.new(key, normalised.encode("utf-8"), hashlib.sha256).hexdigest()


def provider_name_key(name: str | None, key: bytes) -> str | None:
    return name_key(normalise_provider_name(name), key)


def service_name_key(name: str | None, key: bytes) -> str | None:
    return name_key(normalise_service_name(name), key)


def key_check(key: bytes) -> str:
    return name_key(_KEY_CHECK_TEXT, key)


# In memory only: token -> (raw provider name, raw service name) of rows a parser withheld. A row
# carries only the opaque token (_withheld_ref), never the names (PR #11).
_WITHHELD_NAMES: dict[int, tuple[str | None, str | None]] = {}


def remember_withheld_names(provider: str | None = None, service: str | None = None) -> int | None:
    """Keep, in memory only, the raw names a parser withholds, so that write_processed can store
    their keyed hashes in the private sidecar. Returns an opaque token, or None."""
    if not (provider or service):
        return None
    token = len(_WITHHELD_NAMES) + 1
    _WITHHELD_NAMES[token] = (provider or None, service or None)
    return token


def keep_withheld_names(row: dict, provider: str | None = None, service: str | None = None) -> None:
    """Attach the token of remember_withheld_names to a row (never the names themselves)."""
    token = remember_withheld_names(provider, service)
    if token is not None:
        row["_withheld_ref"] = token


def _write_name_keys(name: str, rows: list[dict]) -> None:
    """Write data/private/name-keys/<name>.csv for rows carrying _withheld_ref. Without
    TICA_JOIN_KEY nothing is written (an older sidecar stays: a record_id always stands for the
    same printed row, so its entries stay right)."""
    kept = [r for r in rows if r.get("_withheld_ref") in _WITHHELD_NAMES and r.get("record_id")]
    if not kept:
        return
    key = load_join_key()
    if key is None:
        log.warning("name keys for %s not written: %s is not set", name, JOIN_KEY_VAR)
        return
    path = name_keys_dir() / f"{name}.csv"
    seen: dict[str, tuple] = {}
    for row in kept:
        provider, service = _WITHHELD_NAMES[row["_withheld_ref"]]
        seen.setdefault(
            row["record_id"], (provider_name_key(provider, key), service_name_key(service, key))
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    with atomic_open(path, newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(NAME_KEY_COLUMNS)
        writer.writerow([KEY_CHECK_ID, key_check(key), ""])
        for rid, (pk, sk) in sorted(seen.items()):
            writer.writerow([rid, pk or "", sk or ""])
    log.info("name keys for %s: %d rows (private, gitignored)", name, len(seen))


def read_name_keys(name: str, key: bytes) -> dict[str, tuple[str | None, str | None]]:
    """record_id -> (provider key, service key) from data/private/name-keys/<name>.csv; {} when
    absent. Raises JoinKeyMissing when the sidecar was written with another key."""
    path = name_keys_dir() / f"{name}.csv"
    if not path.exists():
        return {}
    out: dict[str, tuple[str | None, str | None]] = {}
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row["record_id"] == KEY_CHECK_ID:
                if row["provider_key"] != key_check(key):
                    raise JoinKeyMissing(
                        f"name-keys/{path.name} was written with another {JOIN_KEY_VAR}; run "
                        "python scrapers/reparse_offline.py again"
                    )
                continue
            out[row["record_id"]] = (row["provider_key"] or None, row["service_key"] or None)
    return out


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
        known = tuple(row.get(k) for k in ("service_name", "provider_name", "suburb"))

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


def write_processed(
    name: str,
    rows: list[dict],
    fieldnames: list[str],
    *,
    raw_inputs: list[Path],
    schema: str | None = None,
    notes: str | None = None,
) -> Path:
    """Write data/processed/<name>.csv and <name>.provenance.json listing the raw inputs used."""
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    out = PROCESSED_DIR / f"{name}.csv"
    with atomic_open(out, newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: ("" if row.get(k) is None else row.get(k)) for k in fieldnames})
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
    # Codex round 5: no URL or path that may name an individual reaches a provenance file.
    provenance = redact_urls_in_obj(provenance)
    atomic_write_text(
        PROCESSED_DIR / f"{name}.provenance.json", json.dumps(provenance, indent=2) + "\n"
    )
    log.info("processed %s (%d rows)", out.relative_to(PROJECT_ROOT), len(rows))
    _write_name_keys(name, rows)  # PR #11: keyed names of withheld rows, private sidecar
    return out
