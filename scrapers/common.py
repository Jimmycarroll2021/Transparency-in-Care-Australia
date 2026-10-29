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
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib import robotparser
from urllib.parse import urlsplit

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw"
EVIDENCE_DIR = PROJECT_ROOT / "data" / "evidence"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"

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
) -> Fetched:
    """GET a URL politely. Raises RobotsDisallowed or httpx.HTTPStatusError."""
    ua = user_agent or USER_AGENT
    rp = _load_robots(url, user_agent=ua)
    if rp is not None and not allow_disallowed:
        if not (rp.can_fetch(AGENT_TOKEN, url) and rp.can_fetch("*", url)):
            raise RobotsDisallowed(f"robots.txt disallows {url} for {AGENT_TOKEN}")

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
            log.warning("fetch failed (%s), retry %d in %.0fs: %s", exc, attempt, backoff, url)
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
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: ("" if row.get(k) is None else row.get(k)) for k in fieldnames})
    provenance = {
        "output": str(out.relative_to(PROJECT_ROOT)),
        "written_at": utc_now().isoformat(),
        "rows": len(rows),
        "schema": schema,
        "raw_inputs": [str(p.relative_to(PROJECT_ROOT)) for p in raw_inputs],
        "notes": notes,
    }
    (PROCESSED_DIR / f"{name}.provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    log.info("processed %s (%d rows)", out.relative_to(PROJECT_ROOT), len(rows))
    return out
