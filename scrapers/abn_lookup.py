"""ABN Lookup web services client, plus stage A: resolve the ABNs printed on Commonwealth rows.

Licence: ABN Lookup Web Services Agreement (research/2026-10-30-register-abn-lookup.md). A
non-exclusive licence to access and use the services; relevant extracts may be given to third
parties; details withdrawn to protect an individual's privacy must be deleted on notice.

Endpoints (JSON with a JSONP wrapper, documented at https://abr.business.gov.au/json/):
- AbnDetails.aspx?abn=<11 digits>&callback=cb&guid=<GUID>
- MatchingNames.aspx?name=<name>&maxResults=10&callback=cb&guid=<GUID>
MatchingNames has no documented state filter, so `matching_names(name, state)` narrows the
candidates on their `State` field after the call.

Credentials: the GUID comes from the ABN_LOOKUP_GUID environment variable, else from .env. It is
never printed, logged or written anywhere. Every URL that is logged or stored has the guid
parameter removed (redact_url), log records pass through a redacting filter, the httpx request
log is silenced, and any response text that echoed the GUID is redacted before it is cached.

Privacy (CLAUDE.md rule 2): an ABR result whose EntityTypeCode is IND, whose entity type name says
Individual or Sole Trader, or whose entity name reads as a person's name is excluded. Only the fact
of exclusion is recorded in processed outputs, never the name. Raw responses go to
data/raw/abr-lookup/ as a LOCAL cache (gitignored: candidate lists can hold individuals' names).
Processed outputs record endpoint, query, timestamp and the response sha256 instead.

Cache: a cached response younger than 30 days is reused and costs no API call.

Run:
  python3 scrapers/abn_lookup.py                     stage A: write data/processed/abn-details.csv
  python3 scrapers/abn_lookup.py --offline           stage A from the local cache only
  python3 scrapers/abn_lookup.py abn 12345678901     one ABN (organisations only are shown)
  python3 scrapers/abn_lookup.py name "Example Pty Ltd" --state NSW
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import hashlib
import json
import logging
import os
import re
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

try:
    from scrapers.common import (
        PROCESSED_DIR,
        PROJECT_ROOT,
        RAW_DIR,
        Fetched,
        RobotsDisallowed,
        fetch,
        log,
        utc_now,
        write_processed,
        write_snapshot,
    )
    from scrapers.join_enforcement import normalise_provider_name
    from scrapers.profile_providers import classify_entity_form, name_is_withheld
except ImportError:  # run as a plain script: python3 scrapers/abn_lookup.py
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from scrapers.common import (
        PROCESSED_DIR,
        PROJECT_ROOT,
        RAW_DIR,
        Fetched,
        RobotsDisallowed,
        fetch,
        log,
        utc_now,
        write_processed,
        write_snapshot,
    )
    from scrapers.join_enforcement import normalise_provider_name
    from scrapers.profile_providers import classify_entity_form, name_is_withheld

SOURCE = "abr-lookup"
BASE_URL = "https://abr.business.gov.au/json/"
ENDPOINT_ABN = "AbnDetails.aspx"
ENDPOINT_NAMES = "MatchingNames.aspx"
CALLBACK = "cb"
MAX_RESULTS = 10
CACHE_MAX_AGE_DAYS = 30
DEFAULT_MAX_CALLS = 1500
ENV_VAR = "ABN_LOOKUP_GUID"
ENV_FILE = PROJECT_ROOT / ".env"
REDACTED = "[redacted]"

ACTIONS_ALL_CSV = PROCESSED_DIR / "enforcement-actions-all.csv"
PROVIDERS_CSV = PROCESSED_DIR / "acecqa-providers-latest.csv"
PROFILE_CSV = PROCESSED_DIR / "provider-profile.csv"
ABN_DETAILS_NAME = "abn-details"

INDIVIDUAL_CODES = {"IND"}
_INDIVIDUAL_TYPE_WORDS = re.compile(r"individual|sole\s*trader", re.IGNORECASE)
# MatchingNames labels the name of an individual "Legal Name"; organisations carry "Entity Name",
# "Business Name" or "Trading Name". A "Legal Name" candidate is treated as an individual.
INDIVIDUAL_NAME_TYPES = {"legal name"}
BUSINESS_NAME_SEPARATOR = "; "

ABN_DETAILS_COLUMNS = [
    "abn",
    "lookup_status",
    "abn_status",
    "abn_status_effective_from",
    "acn",
    "entity_name",
    "entity_type_code",
    "entity_type_name",
    "business_names",
    "business_names_withheld",
    "name_withheld",
    "address_state",
    "address_postcode",
    "query_endpoint",
    "looked_up_at",
    "response_sha256",
    "note",
]


class AbnLookupError(RuntimeError):
    """A lookup failed. The message has already been redacted."""


class BudgetExhausted(RuntimeError):
    """The API call cap for this run has been reached; no further network calls are made."""


# ---------------------------------------------------------------------------
# Credentials and redaction
# ---------------------------------------------------------------------------


def load_guid(env_file: Path = ENV_FILE, environ: dict | None = None) -> str | None:
    """The GUID from the environment, else from .env. Never printed or logged."""
    environ = os.environ if environ is None else environ
    value = (environ.get(ENV_VAR) or "").strip()
    if value:
        return value
    if not env_file.exists():
        return None
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        if key.strip() == ENV_VAR:
            val = val.strip().strip("\"'").strip()
            return val or None
    return None


_GUID_PARAM = re.compile(r"(?i)([?&;])guid=[^&#\s\"'<>]*(&?)")
_GUID_SHAPE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)


def redact_url(url: str) -> str:
    """Remove the guid query parameter from a URL (any case), keeping the other parameters."""
    parts = urlsplit(url)
    if not parts.query:
        return url
    kept = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k.lower() != "guid"
    ]
    return urlunsplit(parts._replace(query=urlencode(kept)))


def redact_text(text: str, guid: str | None = None) -> str:
    """Strip guid=... parameters, the literal GUID and anything shaped like a GUID from text."""
    if not text:
        return text

    def _param(m: re.Match) -> str:
        return m.group(1) if m.group(2) else ("" if m.group(1) in "&;" else m.group(1))

    text = _GUID_PARAM.sub(_param, text)
    if guid:
        text = text.replace(guid, REDACTED)
    return _GUID_SHAPE.sub(REDACTED, text)


class RedactingFilter(logging.Filter):
    """Rewrites every log record so that no GUID can reach a log handler."""

    def __init__(self, guid: str | None = None):
        super().__init__()
        self.guid = guid

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover - malformed record
            message = str(record.msg)
        record.msg = redact_text(message, self.guid)
        record.args = ()
        return True


def install_log_redaction(guid: str | None) -> RedactingFilter:
    """Silence the httpx request log and add a redacting filter to every root handler."""
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
    flt = RedactingFilter(guid)
    root = logging.getLogger()
    for handler in root.handlers:
        handler.addFilter(flt)
    for name in ("scrapers", "httpx", "httpcore"):
        logging.getLogger(name).addFilter(flt)
    return flt


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

_JSONP = re.compile(r"^\s*[A-Za-z_$][\w$.]*\s*\((.*)\)\s*;?\s*$", re.DOTALL)


def parse_jsonp(text: str) -> dict:
    """`cb({...})` -> dict. Plain JSON is accepted too."""
    text = text.lstrip("﻿")
    m = _JSONP.match(text)
    body = m.group(1) if m else text
    data = json.loads(body)
    if not isinstance(data, dict):
        raise ValueError("ABN Lookup response is not a JSON object")
    return data


def is_individual_entity(data: dict) -> bool:
    """True for an ABR record that is, or may be, a natural person."""
    code = (data.get("EntityTypeCode") or "").strip().upper()
    type_name = data.get("EntityTypeName") or ""
    if code in INDIVIDUAL_CODES or _INDIVIDUAL_TYPE_WORDS.search(type_name):
        return True
    name = data.get("EntityName") or ""
    return bool(name) and classify_entity_form(name) == "likely_individual"


def is_individual_candidate(candidate: dict) -> bool:
    """True for a MatchingNames candidate that is, or may be, a natural person."""
    name_type = (candidate.get("NameType") or "").strip().lower()
    if name_type in INDIVIDUAL_NAME_TYPES:
        return True
    name = candidate.get("Name") or ""
    return bool(name) and classify_entity_form(name) == "likely_individual"


def name_is_safe(name: str | None, known_org_names: set[str] | None = None) -> bool:
    """True when a name may be stored: an ACECQA organisation name already shown, or a name the
    shared fail-closed rule (profile_providers.name_is_withheld) treats as an organisation."""
    if not name:
        return True
    return normalise_provider_name(name) in (known_org_names or set()) or not name_is_withheld(name)


def safe_business_names(
    names: list[str] | None, known_org_names: set[str] | None = None
) -> tuple[list[str], int]:
    """Business names safe to store, and the number withheld.

    A business name is withheld unless it is positively an organisation under the shared
    fail-closed rule, or its normalised form is already an ACECQA organisation name
    (known_org_names), which is public organisation data.
    """
    kept: list[str] = []
    withheld = 0
    for name in names or []:
        name = (name or "").strip()
        if not name:
            continue
        if not name_is_safe(name, known_org_names):
            withheld += 1
            continue
        if name not in kept:
            kept.append(name)
    return kept, withheld


def _yes(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"true", "y", "yes", "1"}


def _score(candidate: dict) -> float:
    try:
        return float(candidate.get("Score") or 0)
    except (TypeError, ValueError):
        return 0.0


def details_row(abn: str, data: dict | None, result: LookupResult | None, known=None) -> dict:
    """One processed row for an AbnDetails response. Individuals keep no name of any kind."""
    row = dict.fromkeys(ABN_DETAILS_COLUMNS)
    row["abn"] = abn
    row["query_endpoint"] = ENDPOINT_ABN
    if result is not None:
        row["looked_up_at"] = result.looked_up_at
        row["response_sha256"] = result.sha256
    if data is None:
        row["lookup_status"] = "error"
        row["note"] = "lookup failed; see the run log"
        return row
    if not re.sub(r"\D", "", data.get("Abn") or ""):
        row["lookup_status"] = "not_found"
        row["note"] = (data.get("Message") or "ABR returned no record").strip()
        return row
    row.update(
        abn_status=(data.get("AbnStatus") or None),
        abn_status_effective_from=(data.get("AbnStatusEffectiveFrom") or None),
        entity_type_code=(data.get("EntityTypeCode") or None),
        entity_type_name=(data.get("EntityTypeName") or None),
        address_state=(data.get("AddressState") or None),
        address_postcode=(data.get("AddressPostcode") or None),
    )
    if is_individual_entity(data):
        row["lookup_status"] = "excluded_individual"
        row["name_withheld"] = "true"
        row["note"] = "ABR record is or may be an individual; names not recorded (CLAUDE.md rule 2)"
        return row
    row["lookup_status"] = "ok"
    row["acn"] = re.sub(r"\D", "", data.get("Acn") or "") or None
    row["entity_name"] = (data.get("EntityName") or "").strip() or None
    row["business_names"] = BUSINESS_NAME_SEPARATOR.join(data.get("BusinessName") or []) or None
    row["business_names_withheld"] = 0
    return filter_details_names(row, known)


ENTITY_NAME_WITHHELD_NOTE = (
    "entity and business names withheld: entity name is not positively an organisation "
    "(CLAUDE.md rule 2)"
)


def filter_details_names(row: dict, known: set[str] | None = None) -> dict:
    """Apply the fail-closed name rule to an ok abn-details row, in place. The ABN, ACN and
    status stay. A withheld entity name nulls every name column; otherwise each business name
    is kept only when it is safe."""
    if row.get("lookup_status") != "ok":
        return row
    notes = [n for n in (row.get("note") or "").split("; ") if n]
    notes = [n for n in notes if "withheld" not in n]
    already = str(row.get("name_withheld") or "").lower() == "true"
    if already or not name_is_safe(row.get("entity_name"), known):
        row.update(entity_name=None, business_names=None, business_names_withheld=None)
        row["name_withheld"] = "true"
        notes.append(ENTITY_NAME_WITHHELD_NOTE)
    else:
        names = [n for n in (row.get("business_names") or "").split(BUSINESS_NAME_SEPARATOR) if n]
        kept, withheld = safe_business_names(names, known)
        withheld += int(row.get("business_names_withheld") or 0)
        row["business_names"] = BUSINESS_NAME_SEPARATOR.join(kept) or None
        row["business_names_withheld"] = withheld
        row["name_withheld"] = "false"
        if withheld:
            notes.append(f"{withheld} business name(s) withheld: not positively an organisation")
    row["note"] = "; ".join(notes) or None
    return row


def refilter_details_rows(rows: list[dict], known: set[str] | None = None) -> list[dict]:
    """Re-apply the name rule to committed abn-details rows without any ABN Lookup call."""
    out = []
    for r in rows:
        row = {k: (v if v != "" else None) for k, v in r.items()}
        if row.get("lookup_status") == "excluded_individual":
            row["name_withheld"] = "true"
        out.append(filter_details_names(row, known))
    return out


# ---------------------------------------------------------------------------
# Name-candidate assessment (stage B)
# ---------------------------------------------------------------------------


def assess_candidates(data: dict, legal_name: str, state: str | None = None) -> dict:
    """Decide whether a MatchingNames response names exactly one ABN for this legal name.

    Accept only when, among current candidates that are not individuals, exactly one distinct ABN
    carries a name whose normalised form equals the normalised legal name, and that candidate has
    the top score among all such current candidates. If several distinct ABNs carry the name, the
    provider's state may break the tie (exactly one of them in that state). Otherwise ambiguous or
    no_match, with the candidate count. Returns a dict with match_kind, abn, score, candidates,
    excluded_individual_candidates and note. Never returns a name.
    """
    names = data.get("Names") or []
    target = normalise_provider_name(legal_name)
    excluded = sum(1 for c in names if is_individual_candidate(c))
    usable = [c for c in names if not is_individual_candidate(c)]
    current = [c for c in usable if _yes(c.get("IsCurrent"))]
    # distinct ABN -> best candidate
    best: dict[str, dict] = {}
    for c in current:
        abn = re.sub(r"\D", "", c.get("Abn") or "")
        if not abn:
            continue
        if abn not in best or _score(c) > _score(best[abn]):
            best[abn] = c
    out = {
        "match_kind": "no_match",
        "abn": None,
        "score": None,
        "candidates": len(best),
        "excluded_individual_candidates": excluded,
        "note": None,
    }
    if not best:
        out["note"] = "no current non-individual candidate"
        return out
    top = max(_score(c) for c in best.values())
    equal: dict[str, dict] = {}
    for c in current:
        abn = re.sub(r"\D", "", c.get("Abn") or "")
        if abn and target and normalise_provider_name(c.get("Name")) == target:
            if abn not in equal or _score(c) > _score(equal[abn]):
                equal[abn] = c
    kind = "accepted_unique"
    if len(equal) > 1 and state:
        in_state = {a: c for a, c in equal.items() if (c.get("State") or "").upper() == state}
        if len(in_state) == 1:
            equal, kind = in_state, "accepted_unique_in_state"
    if not equal:
        out["note"] = (
            f"no candidate's normalised name equals the legal name ({len(best)} candidates)"
        )
        return out
    if len(equal) > 1:
        out["match_kind"] = "ambiguous"
        out["note"] = f"{len(equal)} distinct ABNs carry the normalised legal name"
        return out
    abn, cand = next(iter(equal.items()))
    if _score(cand) < top:
        out["match_kind"] = "ambiguous"
        out["note"] = "the name-equal candidate does not have the top score"
        out["score"] = _score(cand)
        return out
    out.update(match_kind=kind, abn=abn, score=_score(cand))
    out["note"] = "unique current name-equal candidate with the top score"
    if kind == "accepted_unique_in_state":
        out["note"] += f"; several ABNs carry the name, one in {state}"
    return out


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class LookupResult:
    endpoint: str
    query: dict
    data: dict
    sha256: str
    looked_up_at: str
    from_cache: bool
    path: Path | None = None


def query_key(endpoint: str, query: dict) -> str:
    return json.dumps({"endpoint": endpoint, **query}, sort_keys=True)


class AbnLookupClient:
    """Rate limited, cached, redacting client for the two JSON endpoints."""

    def __init__(
        self,
        guid: str | None = None,
        *,
        cache_dir: Path = RAW_DIR / SOURCE,
        max_calls: int | None = DEFAULT_MAX_CALLS,
        offline: bool = False,
        max_age_days: int = CACHE_MAX_AGE_DAYS,
        fetcher: Callable[..., Fetched] = fetch,
        now: Callable[[], datetime] = utc_now,
    ):
        self.guid = guid
        self.cache_dir = cache_dir
        self.max_calls = max_calls
        self.offline = offline
        self.max_age = timedelta(days=max_age_days)
        self.fetcher = fetcher
        self.now = now
        self.calls_made = 0
        self.cache_hits = 0
        self._index: dict[str, tuple[datetime, Path, dict]] | None = None
        if not offline and not guid:
            raise AbnLookupError(f"no {ENV_VAR} in the environment or .env")
        install_log_redaction(guid)

    # -- cache --------------------------------------------------------------

    def _build_index(self) -> dict[str, tuple[datetime, Path, dict]]:
        index: dict[str, tuple[datetime, Path, dict]] = {}
        if not self.cache_dir.exists():
            return index
        for meta_path in self.cache_dir.glob("*.meta.json"):
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                key = query_key(meta["endpoint"], meta["query"])
                when = datetime.fromisoformat(meta["fetched_at"])
            except (json.JSONDecodeError, KeyError, ValueError):
                continue
            data_path = meta_path.with_name(meta_path.name.removesuffix(".meta.json"))
            if not data_path.exists():
                continue
            if key not in index or when > index[key][0]:
                index[key] = (when, data_path, meta)
        return index

    def cached(self, endpoint: str, query: dict) -> LookupResult | None:
        if self._index is None:
            self._index = self._build_index()
        hit = self._index.get(query_key(endpoint, query))
        if hit is None:
            return None
        when, path, meta = hit
        if not self.offline and self.now() - when > self.max_age:
            return None
        content = path.read_bytes()
        return LookupResult(
            endpoint=endpoint,
            query=query,
            data=parse_jsonp(content.decode("utf-8", errors="replace")),
            sha256=hashlib.sha256(content).hexdigest(),
            looked_up_at=meta["fetched_at"],
            from_cache=True,
            path=path,
        )

    # -- network ------------------------------------------------------------

    def _redact(self, text: str) -> str:
        return redact_text(text, self.guid)

    def _get(self, endpoint: str, query: dict) -> LookupResult:
        hit = self.cached(endpoint, query)
        if hit is not None:
            self.cache_hits += 1
            return hit
        if self.offline:
            raise AbnLookupError(f"offline and no cached {endpoint} response for this query")
        if self.max_calls is not None and self.calls_made >= self.max_calls:
            raise BudgetExhausted(f"API call cap of {self.max_calls} reached")
        params = {**query, "callback": CALLBACK, "guid": self.guid}
        url = f"{BASE_URL}{endpoint}?{urlencode(params)}"
        self.calls_made += 1
        try:
            got = self.fetcher(url, redact=self._redact)
        except (httpx.HTTPError, RobotsDisallowed) as exc:
            raise AbnLookupError(self._redact(f"{type(exc).__name__}: {exc}")) from None
        text = got.content.decode("utf-8", errors="replace")
        clean = self._redact(text)
        content = clean.encode("utf-8") if clean != text else got.content
        safe = dataclasses.replace(
            got,
            url=redact_url(got.url),
            final_url=redact_url(got.final_url),
            content=content,
        )
        try:
            data = parse_jsonp(clean)
        except (json.JSONDecodeError, ValueError) as exc:
            raise AbnLookupError(f"unparseable {endpoint} response: {exc}") from None
        path = write_snapshot(
            self.cache_dir.name,
            safe,
            "jsonp",
            base_dir=self.cache_dir.parent,
            extra_meta={
                "endpoint": endpoint,
                "query": query,
                "guid_redacted": True,
                "note": "local cache only (gitignored); may hold individuals' names",
            },
        )
        when = datetime.fromisoformat(safe.fetched_at)
        if self._index is not None:
            meta = {"fetched_at": safe.fetched_at, "endpoint": endpoint, "query": query}
            self._index[query_key(endpoint, query)] = (when, path, meta)
        return LookupResult(
            endpoint=endpoint,
            query=query,
            data=data,
            sha256=safe.sha256,
            looked_up_at=safe.fetched_at,
            from_cache=False,
            path=path,
        )

    def abn_details(self, abn: str) -> LookupResult:
        digits = re.sub(r"\D", "", abn or "")
        if len(digits) != 11:
            raise AbnLookupError("an ABN has 11 digits")
        return self._get(ENDPOINT_ABN, {"abn": digits})

    def matching_names(
        self, name: str, state: str | None = None, max_results: int = MAX_RESULTS
    ) -> LookupResult:
        """Name search. The endpoint has no state filter, so `state` narrows candidates here."""
        result = self._get(ENDPOINT_NAMES, {"name": name.strip(), "maxResults": str(max_results)})
        if state:
            names = result.data.get("Names") or []
            narrowed = [c for c in names if (c.get("State") or "").upper() == state.upper()]
            result = dataclasses.replace(result, data={**result.data, "NamesInState": narrowed})
        return result


# ---------------------------------------------------------------------------
# Stage A: Commonwealth ABNs
# ---------------------------------------------------------------------------


def load_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def known_org_names() -> set[str]:
    """Normalised ACECQA Legal and Trading Names of providers not withheld as individuals."""
    if not PROFILE_CSV.exists():
        return set()
    names = set()
    for row in load_csv(PROFILE_CSV):
        if (row.get("name_withheld") or "").lower() == "true":
            continue
        for col in ("legal_name", "trading_name"):
            key = normalise_provider_name(row.get(col))
            if key:
                names.add(key)
    return names


def cth_abns(actions: list[dict]) -> list[str]:
    return sorted({(r.get("abn") or "").strip() for r in actions if (r.get("abn") or "").strip()})


def run_stage_a(client: AbnLookupClient) -> tuple[list[dict], dict]:
    abns = cth_abns(load_csv(ACTIONS_ALL_CSV))
    known = known_org_names()
    rows: list[dict] = []
    stats = {"distinct_abns": len(abns), "budget_stopped": False}
    for abn in abns:
        try:
            result = client.abn_details(abn)
        except BudgetExhausted:
            stats["budget_stopped"] = True
            break
        except AbnLookupError as exc:
            log.warning("ABN lookup failed: %s", exc)
            rows.append(details_row(abn, None, None))
            continue
        rows.append(details_row(abn, result.data, result, known))
    stats.update(
        resolved=sum(1 for r in rows if r["lookup_status"] == "ok"),
        excluded_individual=sum(1 for r in rows if r["lookup_status"] == "excluded_individual"),
        not_found=sum(1 for r in rows if r["lookup_status"] == "not_found"),
        errors=sum(1 for r in rows if r["lookup_status"] == "error"),
        api_calls=client.calls_made,
        cache_hits=client.cache_hits,
    )
    return rows, stats


def add_abr_provenance(name: str, extra: dict) -> None:
    path = PROCESSED_DIR / f"{name}.provenance.json"
    prov = json.loads(path.read_text(encoding="utf-8"))
    prov.update(extra)
    path.write_text(json.dumps(prov, indent=2) + "\n", encoding="utf-8")


ABR_PROVENANCE = {
    "abr_source": {
        "service": "ABN Lookup web services (JSON)",
        "endpoints": [BASE_URL + ENDPOINT_ABN, BASE_URL + ENDPOINT_NAMES],
        "licence": "ABN Lookup Web Services Agreement v9.9.7, "
        "https://abr.business.gov.au/Tools/WebServicesAgreement "
        "(see research/2026-10-30-register-abn-lookup.md)",
        "cache": "data/raw/abr-lookup/ is a local, gitignored cache; each row records the query "
        "endpoint, looked_up_at and the sha256 of the cached response instead",
        "credential": "the GUID is never stored; every recorded URL has the guid parameter removed",
    }
}


_PROVENANCE_CORE = {"output", "written_at", "rows", "schema", "raw_inputs", "notes"}


def rewrite_processed(name: str, rows: list[dict], columns: list[str], note: str) -> None:
    """Rewrite data/processed/<name>.csv after an offline re-filter, keeping its provenance
    (raw inputs, ABR source, run statistics) and adding the note once."""
    path = PROCESSED_DIR / f"{name}.provenance.json"
    old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    notes = old.get("notes") or ""
    if note not in notes:
        notes = f"{notes} {note}".strip()
    write_processed(
        name,
        rows,
        columns,
        raw_inputs=[PROJECT_ROOT / p for p in old.get("raw_inputs", [])],
        notes=notes,
    )
    extra = {k: v for k, v in old.items() if k not in _PROVENANCE_CORE}
    if extra:
        add_abr_provenance(name, extra)


REFILTER_NOTE = (
    "Name filter re-applied offline (no ABN Lookup calls) with the shared fail-closed rule "
    "(profile_providers.name_is_withheld); name_withheld marks rows whose names were nulled."
)


def main_refilter() -> None:
    path = PROCESSED_DIR / f"{ABN_DETAILS_NAME}.csv"
    if not path.exists():
        raise SystemExit(f"no {path.name}: run stage A first")
    rows = refilter_details_rows(load_csv(path), known_org_names())
    rewrite_processed(ABN_DETAILS_NAME, rows, ABN_DETAILS_COLUMNS, REFILTER_NOTE)
    log.info(
        "refilter: %d rows, %d with names withheld",
        len(rows),
        sum(1 for r in rows if r.get("name_withheld") == "true"),
    )


def main_stage_a(args: argparse.Namespace) -> None:
    guid = None if args.offline else load_guid()
    client = AbnLookupClient(guid, max_calls=args.max_calls, offline=args.offline)
    rows, stats = run_stage_a(client)
    write_processed(
        ABN_DETAILS_NAME,
        rows,
        ABN_DETAILS_COLUMNS,
        raw_inputs=[ACTIONS_ALL_CSV],
        notes=(
            "One row per distinct ABN printed on Commonwealth CCS enforcement rows "
            "(enforcement-actions-all.csv abn column), resolved with ABN Lookup AbnDetails. "
            "lookup_status ok, not_found, excluded_individual or error. Rows for individuals or "
            "sole traders keep no name of any kind (CLAUDE.md rule 2); business names that read as "
            "a person's name are withheld unless already an ACECQA organisation name. ABR data is "
            "as reported by the ABR and is not verified here; verify any ABN on ABN Lookup before "
            "it is shown publicly."
        ),
    )
    add_abr_provenance(ABN_DETAILS_NAME, {**ABR_PROVENANCE, "run": stats})
    log.info("stage A: %s", json.dumps(stats))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main_single(args: argparse.Namespace) -> None:
    client = AbnLookupClient(load_guid(), max_calls=5)
    if args.command == "abn":
        result = client.abn_details(args.value)
        row = details_row(args.value, result.data, result, known_org_names())
        print(json.dumps(row, indent=2))
    else:
        result = client.matching_names(args.value, state=args.state)
        decision = assess_candidates(result.data, args.value, args.state)
        decision.update(looked_up_at=result.looked_up_at, response_sha256=result.sha256)
        print(json.dumps(decision, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--max-calls", type=int, default=DEFAULT_MAX_CALLS)
    parser.add_argument("--offline", action="store_true", help="use the local cache only")
    sub = parser.add_subparsers(dest="command")
    p_abn = sub.add_parser("abn", help="look up one ABN")
    p_abn.add_argument("value")
    p_name = sub.add_parser("name", help="search one organisation name")
    p_name.add_argument("value")
    p_name.add_argument("--state")
    sub.add_parser(
        "refilter", help="re-apply the name filter to abn-details.csv offline (no API calls)"
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    try:
        if args.command in ("abn", "name"):
            main_single(args)
        elif args.command == "refilter":
            main_refilter()
        else:
            main_stage_a(args)
    except AbnLookupError as exc:
        raise SystemExit(f"ABN lookup error: {exc}") from None


if __name__ == "__main__":
    main()
