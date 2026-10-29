"""Join every jurisdiction's enforcement actions onto the ACECQA register spine.

Reads (all under data/processed/, none fetched here):
- acecqa-services-latest.csv     the spine: one row per approved service
- provider-profile.csv           one row per approved provider (entity form, service count);
                                 names of providers withheld as likely individuals are already null
- *-enforcement-actions.csv      every jurisdiction's parsed actions, found by glob so a new
                                 jurisdiction joins automatically

Writes (via scrapers.common.write_processed, with transitive raw_inputs provenance):
- enforcement-actions-all.csv    stacked actions plus join columns
- enforcement-by-service.csv     one row per ACECQA service, zero-filled
- enforcement-by-provider.csv    one row per provider, rolled up
and data/processed/enforcement-join-report.json.

Join rules
- Service-level rows (SE- present) join on service_approval_number.
- Provider-level rows (PR- only) join on provider_approval_number.
- Queensland prints no keys: service_name is matched to ACECQA ServiceName after normalisation,
  restricted to State == QLD. A suburb-equal match is preferred (name_and_suburb), otherwise a
  unique name-only match is accepted (name_only). Several candidates: left unmatched, with the
  candidate count in join_note. Rows whose subject was withheld as an individual are never name
  matched; they join by key only.
- Provider-name stage (third, last): a row still unmatched, with no printed SE-/PR- key and a
  non-null provider_name, is matched to ACECQA providers by normalised Legal Name or Trading Name,
  restricted to the row's state when it has one (a provider is "in" a state if its registered
  State or any of its services is there). Accepted only when exactly one provider matches
  (provider_name_unique); several matches leave the row unmatched with the count in join_note.
  Rows with a printed key are never name matched (a key absent from the spine means a ceased or
  unlisted approval, and a name match could attach a different provider). Providers and rows
  withheld as likely individuals are never matched. A row that also has a service_name is then
  pinned to one of that provider's services when the normalised ServiceName is unique
  (provider_and_service_name); the key is set on the joined output only, never on the source row.
- abn: the 11 digits of a printed "ccs_identifier: ABN ..." note, carried for the Phase 4 ABR
  stage. ACECQA has no ABN, so it cannot be matched here. Null where the subject is withheld.
- join_key_kind is the kind of join that succeeded (service, provider, name_match,
  provider_name_match) or none.

Counting rules (CLAUDE.md rules 5, 6, 7)
- Every count carries its window. "Last 24 months" ends on the ACECQA snapshot's
  snapshot_last_modified date; the start is the same day 24 calendar months earlier plus one day.
- action_type categories are kept in separate columns. actions_total and actions_last_24_months
  are counts of all published enforcement actions of any type; they are not a count of breaches
  and do not turn prosecutions into breaches.
- A row the parser flagged "duplicate row in source" stays in enforcement-actions-all.csv
  (counted_in_totals false) but is not counted, so a register printing a line twice is not
  counted twice.
- Counts are only as complete as the register behind them: see coverage_note. Absence of an
  action is not evidence of safety.

ACECQA content is not openly licensed: outputs are for internal use only.

Run: python3 scrapers/join_enforcement.py
"""

from __future__ import annotations

import calendar
import csv
import json
import re
from collections import Counter, defaultdict
from datetime import date, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path

try:
    from scrapers.common import (
        PROCESSED_DIR,
        PROJECT_ROOT,
        log,
        normalise_pr,
        normalise_se,
        utc_now,
        write_processed,
    )
except ImportError:  # run as a plain script: python3 scrapers/join_enforcement.py
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from scrapers.common import (
        PROCESSED_DIR,
        PROJECT_ROOT,
        log,
        normalise_pr,
        normalise_se,
        utc_now,
        write_processed,
    )

SERVICES_CSV = PROCESSED_DIR / "acecqa-services-latest.csv"
PROVIDERS_CSV = PROCESSED_DIR / "acecqa-providers-latest.csv"
PROFILE_CSV = PROCESSED_DIR / "provider-profile.csv"
REPORT_JSON = PROCESSED_DIR / "enforcement-join-report.json"
SCHEMA_PATH = PROJECT_ROOT / "data" / "schemas" / "enforcement-action.schema.json"
ACTION_GLOB = "*-enforcement-actions.csv"

WINDOW_MONTHS = 24
NAME_MATCH_JURISDICTIONS = {"QLD"}
STATES = {"NSW", "VIC", "QLD", "SA", "WA", "TAS", "NT", "ACT"}
DUPLICATE_NOTE = "duplicate row in source"
TOP_N = 20
UNMATCHED_EXAMPLES = 10

CONFIDENCE_EXACT = "exact_key"
CONFIDENCE_NAME_SUBURB = "name_and_suburb"
CONFIDENCE_NAME_ONLY = "name_only"
CONFIDENCE_PROVIDER_NAME = "provider_name_unique"
CONFIDENCE_PROVIDER_AND_SERVICE = "provider_and_service_name"
CONFIDENCE_NONE = "unmatched"

ACTION_COLUMNS = [
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
JOIN_COLUMNS = [
    "join_key_kind",
    "match_confidence",
    "join_note",
    "acecqa_service_approval_number",
    "acecqa_service_name",
    "acecqa_provider_approval_number",
    "acecqa_provider_legal_name",
    "acecqa_state",
    "acecqa_service_type",
    "acecqa_overall_rating",
    "acecqa_rating_issued",
    "provider_entity_form",
    "provider_service_count",
    "counted_in_totals",
]
ALL_COLUMNS = ["record_id", "occurrence"] + ACTION_COLUMNS[1:] + ["abn"] + JOIN_COLUMNS

# Coverage of each register as the audits in research/ found it (2026-10-29).
COVERAGE = {
    "NSW": "NSW register: Jan 2025 onward (quarterly PDFs)",
    "VIC": "VIC register: Jan 2026 onward (HTML only, archive not collected)",
    "QLD": "QLD register: 2017 onward (register, discretionary removal, no keys)",
    "CTH": "CTH register: rolling 12 months plus past registers",
}
NOT_COLLECTED = "{state} register: not yet collected"
SAFETY_SENTENCE = "Absence of an action is not evidence of safety."

_NAME_STOPWORDS = {"PTY", "LTD", "LIMITED", "INC", "THE"}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def load_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


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


_ABN_NOTE = re.compile(r"ccs_identifier:\s*ABN\s*((?:\d\s?){11})(?!\d)", re.IGNORECASE)


def extract_abn(notes: str | None) -> str | None:
    """Eleven digits from a 'ccs_identifier: ABN ...' note, or None. Never invented."""
    m = _ABN_NOTE.search(notes or "")
    return re.sub(r"\D", "", m.group(1)) if m else None


def normalise_suburb(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(re.sub(r"[^A-Z0-9 ]+", " ", value.upper()).split())


def add_months(d: date, months: int) -> date:
    """Calendar-month arithmetic, clamping the day (29 Feb minus 24 months is 28 Feb)."""
    index = d.year * 12 + (d.month - 1) + months
    year, month = divmod(index, 12)
    month += 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def window_bounds(end: date, months: int = WINDOW_MONTHS) -> tuple[date, date]:
    """Inclusive window: (end minus `months` calendar months) plus one day, up to and including end."""
    return add_months(end, -months) + timedelta(days=1), end


def parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def snapshot_date(services: list[dict]) -> date | None:
    """Latest snapshot_last_modified (HTTP date) across the spine, as a UTC date."""
    best = None
    for value in {r.get("snapshot_last_modified") for r in services}:
        if not value:
            continue
        try:
            d = parsedate_to_datetime(value).date()
        except (TypeError, ValueError):
            continue
        if best is None or d > best:
            best = d
    return best


def load_action_types() -> list[str]:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return list(schema["properties"]["action_type"]["enum"])


def coverage_label(state: str | None) -> str:
    state = (state or "").strip().upper()
    if not state:
        return "state unknown: no register coverage can be stated"
    return COVERAGE.get(state, NOT_COLLECTED.format(state=state))


def coverage_note(state: str | None, cth_present: bool) -> str:
    label = coverage_label(state)
    note = f"{label}. Zero or few actions here reflects only what that register publishes."
    if cth_present:
        note += f" {COVERAGE['CTH']} also applies to CCS approved providers in every state."
    return f"{note} {SAFETY_SENTENCE}"


def transitive_inputs(paths: list[Path]) -> list[Path]:
    """The given files plus, recursively, the raw_inputs of their provenance sidecars."""
    seen: dict[Path, None] = {}
    stack = list(paths)
    while stack:
        path = stack.pop(0)
        path = path if path.is_absolute() else PROJECT_ROOT / path
        if path in seen:
            continue
        seen[path] = None
        sidecar = path.with_name(path.name.removesuffix(".csv") + ".provenance.json")
        if path.suffix == ".csv" and sidecar.exists():
            try:
                inputs = json.loads(sidecar.read_text(encoding="utf-8")).get("raw_inputs", [])
            except json.JSONDecodeError:
                inputs = []
            stack.extend(PROJECT_ROOT / p for p in inputs)
    return list(seen)


# ---------------------------------------------------------------------------
# The spine
# ---------------------------------------------------------------------------


class Spine:
    """Lookups over the ACECQA services and the provider profile."""

    def __init__(
        self,
        services: list[dict],
        profiles: list[dict],
        providers: list[dict] | None = None,
    ):
        self.services: dict[str, dict] = {}
        for row in services:
            se = row.get("service_approval_number") or normalise_se(
                row.get("ServiceApprovalNumber")
            )
            if se and se not in self.services:
                self.services[se] = row
        self.profiles: dict[str, dict] = {}
        for row in profiles:
            pr = normalise_pr(row.get("provider_approval_number"))
            if pr and pr not in self.profiles:
                self.profiles[pr] = row
        # state -> normalised service name -> list of service rows
        self.by_name: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
        for row in self.services.values():
            key = normalise_service_name(row.get("ServiceName"))
            state = (row.get("State") or "").strip().upper()
            if key and state:
                self.by_name[state][key].append(row)
        # provider -> its services, and the states each provider is present in
        self.services_by_provider: dict[str, list[dict]] = defaultdict(list)
        self.provider_states: dict[str, set] = defaultdict(set)
        for row in self.services.values():
            pr = self.service_pr(row)
            if pr:
                self.services_by_provider[pr].append(row)
                state = (row.get("State") or "").strip().upper()
                if state:
                    self.provider_states[pr].add(state)
        # normalised provider name -> set of PR numbers. Providers withheld as likely individuals
        # are left out, so an individual's name can never be matched.
        withheld = {
            pr
            for pr, prof in self.profiles.items()
            if (prof.get("name_withheld") or "").strip().lower() == "true"
        }
        self.provider_names: dict[str, set] = defaultdict(set)
        if providers is not None:
            for row in providers:
                pr = normalise_pr(
                    row.get("provider_approval_number") or row.get("Provider Approval Number")
                )
                if not pr or pr in withheld:
                    continue
                for col in ("Legal Name", "Trading Name"):
                    key = normalise_provider_name(row.get(col))
                    if key:
                        self.provider_names[key].add(pr)
                state = (row.get("State") or "").strip().upper()
                if state:
                    self.provider_states[pr].add(state)
        else:
            for pr, prof in self.profiles.items():
                if pr in withheld:
                    continue
                for col in ("legal_name", "trading_name"):
                    key = normalise_provider_name(prof.get(col))
                    if key:
                        self.provider_names[key].add(pr)

    def service_pr(self, service: dict) -> str | None:
        return service.get("provider_approval_number") or normalise_pr(
            service.get("Provider Approval Number")
        )

    def profile_for(self, pr: str | None) -> dict | None:
        return self.profiles.get(pr) if pr else None


def name_withheld_row(row: dict) -> bool:
    """True where a parser withheld the subject's name as a possible individual."""
    notes = (row.get("notes") or "").lower()
    return "withheld" in notes or "individual" in notes


def match_by_name(row: dict, spine: Spine, state: str) -> tuple[dict | None, str, str]:
    """Return (service row or None, confidence, join_note). Never guesses between candidates."""
    key = normalise_service_name(row.get("service_name"))
    if not key:
        return None, CONFIDENCE_NONE, "no service name printed; no key; name match not possible"
    candidates = spine.by_name.get(state, {}).get(key, [])
    if not candidates:
        return None, CONFIDENCE_NONE, f"no {state} service with this normalised name"
    suburb = normalise_suburb(row.get("suburb"))
    if suburb:
        same = [c for c in candidates if normalise_suburb(c.get("Suburb")) == suburb]
        if len(same) == 1:
            return same[0], CONFIDENCE_NAME_SUBURB, "unique name and suburb match"
        if len(same) > 1:
            return None, CONFIDENCE_NONE, f"ambiguous: {len(same)} candidates share name and suburb"
    if len(candidates) == 1:
        note = "unique name-only match"
        if suburb:
            note += "; printed suburb differs from the ACECQA suburb"
        return candidates[0], CONFIDENCE_NAME_ONLY, note
    return None, CONFIDENCE_NONE, f"ambiguous: {len(candidates)} candidates share the name"


def match_by_provider_name(row: dict, spine: Spine, state: str | None) -> tuple[str | None, str]:
    """Return (provider PR or None, join_note). Accepts a match only when exactly one provider fits."""
    key = normalise_provider_name(row.get("provider_name"))
    if not key:
        return None, "provider name empty after normalisation"
    candidates = spine.provider_names.get(key, set())
    if state:
        candidates = {pr for pr in candidates if state in spine.provider_states.get(pr, set())}
    where = f" in {state}" if state else ""
    if not candidates:
        return None, f"no provider{where} with this normalised name"
    if len(candidates) > 1:
        return None, f"ambiguous provider name: {len(candidates)} candidate providers{where}"
    return next(iter(candidates)), f"unique provider name match{where}"


def pin_service(row: dict, spine: Spine, pr: str, state: str | None) -> tuple[dict | None, str]:
    """Pin a provider-matched row to one of the provider's services by unique normalised name."""
    key = normalise_service_name(row.get("service_name"))
    if not key:
        return None, ""
    services = spine.services_by_provider.get(pr, [])
    if state:
        services = [s for s in services if (s.get("State") or "").strip().upper() == state]
    same = [s for s in services if normalise_service_name(s.get("ServiceName")) == key]
    if len(same) == 1:
        return same[0], "; service pinned by unique name among the provider's services"
    if len(same) > 1:
        return None, f"; service not pinned: {len(same)} of the provider's services share the name"
    return None, "; service not pinned: no service of this provider has the printed name"


def attach_service(out: dict, service: dict, spine: Spine) -> None:
    pr = spine.service_pr(service)
    profile = spine.profile_for(pr)
    out.update(
        acecqa_service_approval_number=service.get("service_approval_number"),
        acecqa_service_name=blank_to_none(service.get("ServiceName")),
        acecqa_provider_approval_number=pr,
        acecqa_state=blank_to_none(service.get("State")),
        acecqa_service_type=blank_to_none(service.get("ServiceType")),
        acecqa_overall_rating=blank_to_none(service.get("OverallRating")),
        acecqa_rating_issued=blank_to_none(service.get("RatingsIssued")),
    )
    if profile:
        out["acecqa_provider_legal_name"] = blank_to_none(profile.get("legal_name"))
        out["provider_entity_form"] = blank_to_none(profile.get("entity_form"))
        out["provider_service_count"] = blank_to_none(profile.get("service_count"))


def attach_provider(out: dict, pr: str, profile: dict) -> None:
    out.update(
        acecqa_provider_approval_number=pr,
        acecqa_provider_legal_name=blank_to_none(profile.get("legal_name")),
        provider_entity_form=blank_to_none(profile.get("entity_form")),
        provider_service_count=blank_to_none(profile.get("service_count")),
    )


def join_actions(actions: list[dict], spine: Spine) -> list[dict]:
    """Stack-order join. Adds occurrence, join columns and spine columns to a copy of each row."""
    seen: Counter = Counter()
    joined: list[dict] = []
    for action in actions:
        out = {c: blank_to_none(action.get(c)) for c in ACTION_COLUMNS}
        out["service_approval_number"] = normalise_se(out["service_approval_number"])
        out["provider_approval_number"] = normalise_pr(out["provider_approval_number"])
        seen[out["record_id"]] += 1
        out["occurrence"] = seen[out["record_id"]]
        out["counted_in_totals"] = DUPLICATE_NOTE not in (out["notes"] or "")
        out["abn"] = None if name_withheld_row(out) else extract_abn(out["notes"])
        out.update({c: None for c in JOIN_COLUMNS if c not in out})
        out.update(
            join_key_kind="none",
            match_confidence=CONFIDENCE_NONE,
            join_note=None,
        )
        se, pr = out["service_approval_number"], out["provider_approval_number"]
        jurisdiction = (out["jurisdiction"] or "").upper()

        if se:
            service = spine.services.get(se)
            profile = spine.profile_for(pr)
            if service is not None:
                out.update(join_key_kind="service", match_confidence=CONFIDENCE_EXACT)
                attach_service(out, service, spine)
                spine_pr = out["acecqa_provider_approval_number"]
                if pr and spine_pr and pr != spine_pr:
                    out["join_note"] = (
                        f"printed provider key {pr} differs from the spine's {spine_pr}"
                    )
            elif profile is not None:
                out.update(join_key_kind="provider", match_confidence=CONFIDENCE_EXACT)
                attach_provider(out, pr, profile)
                out["join_note"] = f"service key {se} not in the spine; joined on provider key only"
            else:
                out["join_note"] = f"service key {se} not in the spine"
        elif pr:
            profile = spine.profile_for(pr)
            if profile is not None:
                out.update(join_key_kind="provider", match_confidence=CONFIDENCE_EXACT)
                attach_provider(out, pr, profile)
            else:
                out["join_note"] = f"provider key {pr} not in the spine"
        elif jurisdiction in NAME_MATCH_JURISDICTIONS:
            if name_withheld_row(out):
                out["join_note"] = (
                    "no key; subject withheld as an individual; name match not attempted"
                )
            else:
                state = (out["state"] or jurisdiction).upper()
                service, confidence, note = match_by_name(out, spine, state)
                out["join_note"] = note
                if service is not None:
                    out.update(join_key_kind="name_match", match_confidence=confidence)
                    attach_service(out, service, spine)
        else:
            out["join_note"] = "no service or provider key printed"

        # Third stage: provider name, for rows with no printed key that are still unmatched.
        if (
            out["match_confidence"] == CONFIDENCE_NONE
            and not se
            and not pr
            and out["provider_name"]
            and not name_withheld_row(out)
        ):
            state = (out["state"] or "").upper() or None
            if state is None and jurisdiction in STATES:
                state = jurisdiction
            if state not in STATES:
                state = None
            matched_pr, note = match_by_provider_name(out, spine, state)
            if matched_pr is None:
                out["join_note"] = f"{out['join_note']}; provider name: {note}"
            else:
                out.update(
                    join_key_kind="provider_name_match", match_confidence=CONFIDENCE_PROVIDER_NAME
                )
                out["join_note"] = note
                attach_provider(out, matched_pr, spine.profiles[matched_pr])
                service, pin_note = pin_service(out, spine, matched_pr, state)
                if service is not None:
                    out["match_confidence"] = CONFIDENCE_PROVIDER_AND_SERVICE
                    attach_service(out, service, spine)
                out["join_note"] += pin_note
        joined.append(out)
    return joined


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


class Tally:
    """Counts of actions by type, in total and inside the window, with first and last dates."""

    def __init__(self, action_types: list[str]):
        self.types = action_types
        self.total: Counter = Counter()
        self.window: Counter = Counter()
        self.dates: list[date] = []
        self.by_name = 0

    def add(self, action_type: str, when: date | None, window: tuple[date, date]) -> None:
        self.total[action_type] += 1
        if when is not None:
            self.dates.append(when)
            if window[0] <= when <= window[1]:
                self.window[action_type] += 1

    def columns(self) -> dict:
        out: dict = {"actions_total": sum(self.total.values())}
        for t in self.types:
            out[f"count_{t}"] = self.total[t]
        out["actions_last_24_months"] = sum(self.window.values())
        for t in self.types:
            out[f"last24m_{t}"] = self.window[t]
        out["first_action_date"] = min(self.dates).isoformat() if self.dates else None
        out["last_action_date"] = max(self.dates).isoformat() if self.dates else None
        return out


def tally_columns(types: list[str]) -> list[str]:
    return (
        ["actions_total"]
        + [f"count_{t}" for t in types]
        + ["actions_last_24_months"]
        + [f"last24m_{t}" for t in types]
        + ["first_action_date", "last_action_date"]
    )


def counted_type(row: dict, known: set[str]) -> str:
    return row["action_type"] if row["action_type"] in known else "other"


def aggregate(
    joined: list[dict],
    spine: Spine,
    types: list[str],
    window: tuple[date, date],
    cth_present: bool,
) -> tuple[list[dict], list[dict]]:
    """Return (by_service rows, by_provider rows)."""
    known = set(types)
    service_tally: dict[str, Tally] = {}
    provider_tally: dict[str, Tally] = {}
    provider_service_level: Counter = Counter()
    provider_provider_level: Counter = Counter()
    services_with_any: defaultdict[str, set] = defaultdict(set)
    services_with_recent: defaultdict[str, set] = defaultdict(set)
    name_matched: Counter = Counter()
    provider_name_matched: Counter = Counter()

    for row in joined:
        if not row["counted_in_totals"] or row["join_key_kind"] == "none":
            continue
        action_type = counted_type(row, known)
        when = parse_iso_date(row["date_issued"])
        recent = when is not None and window[0] <= when <= window[1]
        pr = row["acecqa_provider_approval_number"]
        by_name = row["match_confidence"] != CONFIDENCE_EXACT
        se = row["acecqa_service_approval_number"]
        if row["join_key_kind"] in ("service", "name_match") or (
            row["join_key_kind"] == "provider_name_match" and se
        ):
            service_tally.setdefault(se, Tally(types)).add(action_type, when, window)
            if by_name:
                name_matched[se] += 1
            if pr:
                provider_tally.setdefault(pr, Tally(types)).add(action_type, when, window)
                provider_service_level[pr] += 1
                services_with_any[pr].add(se)
                if recent:
                    services_with_recent[pr].add(se)
                if by_name:
                    provider_name_matched[pr] += 1
        elif pr:  # provider-level action
            provider_tally.setdefault(pr, Tally(types)).add(action_type, when, window)
            provider_provider_level[pr] += 1
            if by_name:
                provider_name_matched[pr] += 1

    window_cols = {"window_start": window[0].isoformat(), "window_end": window[1].isoformat()}
    blank = Tally(types).columns()

    service_rows = []
    for se in sorted(spine.services):
        svc = spine.services[se]
        state = blank_to_none(svc.get("State"))
        tally = service_tally.get(se)
        service_rows.append(
            {
                "service_approval_number": se,
                "provider_approval_number": spine.service_pr(svc),
                "service_name": blank_to_none(svc.get("ServiceName")),
                "suburb": blank_to_none(svc.get("Suburb")),
                "state": state,
                "postcode": blank_to_none(svc.get("Postcode")),
                "service_type": blank_to_none(svc.get("ServiceType")),
                "acecqa_overall_rating": blank_to_none(svc.get("OverallRating")),
                "acecqa_rating_issued": blank_to_none(svc.get("RatingsIssued")),
                **window_cols,
                **(tally.columns() if tally else blank),
                "actions_matched_by_name": name_matched[se],
                "jurisdictions_publishing": coverage_label(state),
                "coverage_note": coverage_note(state, cth_present),
            }
        )

    # services per provider as seen in the spine
    states_by_provider: dict[str, set] = defaultdict(set)
    for svc in spine.services.values():
        pr = spine.service_pr(svc)
        if pr and svc.get("State"):
            states_by_provider[pr].add(svc["State"].strip().upper())

    provider_rows = []
    for pr in sorted(spine.profiles):
        profile = spine.profiles[pr]
        withheld = (profile.get("name_withheld") or "").strip().lower() == "true"
        service_count = int(profile.get("service_count") or 0)
        tally = provider_tally.get(pr)
        cols = tally.columns() if tally else blank
        states = sorted(states_by_provider.get(pr, set()))
        labels = "; ".join(coverage_label(s) for s in states) or None
        notes = (
            " ".join(coverage_note(s, cth_present) for s in states[:1])
            if len(states) == 1
            else f"{SAFETY_SENTENCE} Coverage differs by state: see jurisdictions_publishing."
        )
        provider_rows.append(
            {
                "provider_approval_number": pr,
                "legal_name": None if withheld else blank_to_none(profile.get("legal_name")),
                "trading_name": None if withheld else blank_to_none(profile.get("trading_name")),
                "name_withheld": "true" if withheld else "false",
                "entity_form": blank_to_none(profile.get("entity_form")),
                "provider_state": blank_to_none(profile.get("provider_state")),
                "states_operated_in": blank_to_none(profile.get("states_operated_in")),
                "service_count": service_count,
                "services_with_any_action": len(services_with_any[pr]),
                "services_with_any_action_last_24_months": len(services_with_recent[pr]),
                "service_level_actions": provider_service_level[pr],
                "provider_level_actions": provider_provider_level[pr],
                "actions_matched_by_name": provider_name_matched[pr],
                **window_cols,
                **cols,
                "actions_last_24_months_per_service": (
                    round(cols["actions_last_24_months"] / service_count, 4)
                    if service_count
                    else None
                ),
                "jurisdictions_publishing": labels,
                "coverage_note": notes,
            }
        )
    return service_rows, provider_rows


def service_columns(types: list[str]) -> list[str]:
    return (
        [
            "service_approval_number",
            "provider_approval_number",
            "service_name",
            "suburb",
            "state",
            "postcode",
            "service_type",
            "acecqa_overall_rating",
            "acecqa_rating_issued",
            "window_start",
            "window_end",
        ]
        + tally_columns(types)
        + ["actions_matched_by_name", "jurisdictions_publishing", "coverage_note"]
    )


def provider_columns(types: list[str]) -> list[str]:
    return (
        [
            "provider_approval_number",
            "legal_name",
            "trading_name",
            "name_withheld",
            "entity_form",
            "provider_state",
            "states_operated_in",
            "service_count",
            "services_with_any_action",
            "services_with_any_action_last_24_months",
            "service_level_actions",
            "provider_level_actions",
            "actions_matched_by_name",
            "window_start",
            "window_end",
        ]
        + tally_columns(types)
        + [
            "actions_last_24_months_per_service",
            "jurisdictions_publishing",
            "coverage_note",
        ]
    )


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def top_providers(
    provider_rows: list[dict], types: list[str], *, by: str, min_services: int, n: int = TOP_N
) -> list[dict]:
    """Providers (name-withheld excluded) ranked by actions or by rate in the window."""
    eligible = [
        r
        for r in provider_rows
        if r["name_withheld"] != "true"
        and r["actions_last_24_months"] > 0
        and r["service_count"] >= min_services
    ]
    if by == "count":
        eligible.sort(
            key=lambda r: (
                -r["actions_last_24_months"],
                -(r["actions_last_24_months_per_service"] or 0),
                r["provider_approval_number"],
            )
        )
    else:
        eligible.sort(
            key=lambda r: (
                -(r["actions_last_24_months_per_service"] or 0),
                -r["actions_last_24_months"],
                r["provider_approval_number"],
            )
        )
    out = []
    for r in eligible[:n]:
        out.append(
            {
                "provider_approval_number": r["provider_approval_number"],
                "legal_name": r["legal_name"],
                "entity_form": r["entity_form"],
                "actions_last_24_months": r["actions_last_24_months"],
                "by_action_type_last_24_months": {
                    t: r[f"last24m_{t}"] for t in types if r[f"last24m_{t}"]
                },
                "service_count": r["service_count"],
                "actions_last_24_months_per_service": r["actions_last_24_months_per_service"],
                "services_with_any_action_last_24_months": r[
                    "services_with_any_action_last_24_months"
                ],
                "states_operated_in": r["states_operated_in"],
                "window": f"{r['window_start']} to {r['window_end']}",
            }
        )
    return out


def build_report(
    joined: list[dict],
    service_rows: list[dict],
    provider_rows: list[dict],
    types: list[str],
    window: tuple[date, date],
    raw_inputs: list[Path],
    action_files: list[Path],
) -> dict:
    per: dict[str, dict] = {}
    for row in joined:
        j = row["jurisdiction"]
        s = per.setdefault(
            j,
            {
                "rows_in": 0,
                "joined_exact_key": 0,
                "joined_exact_key_service": 0,
                "joined_exact_key_provider": 0,
                "joined_by_name": 0,
                "joined_by_name_and_suburb": 0,
                "joined_by_name_only": 0,
                "joined_by_provider_name": 0,
                "joined_by_provider_name_unpinned": 0,
                "joined_by_provider_and_service_name": 0,
                "unmatched": 0,
                "unmatched_ambiguous_name": 0,
                "unmatched_ambiguous_provider_name": 0,
                "duplicate_rows_not_counted": 0,
                "unmatched_reasons": {},
                "unmatched_examples": [],
            },
        )
        s["rows_in"] += 1
        if not row["counted_in_totals"]:
            s["duplicate_rows_not_counted"] += 1
        confidence = row["match_confidence"]
        if confidence == CONFIDENCE_EXACT:
            s["joined_exact_key"] += 1
            kind = "service" if row["join_key_kind"] == "service" else "provider"
            s[f"joined_exact_key_{kind}"] += 1
        elif confidence in (CONFIDENCE_NAME_SUBURB, CONFIDENCE_NAME_ONLY):
            s["joined_by_name"] += 1
            s[f"joined_by_{confidence}"] += 1
        elif confidence in (CONFIDENCE_PROVIDER_NAME, CONFIDENCE_PROVIDER_AND_SERVICE):
            s["joined_by_provider_name"] += 1
            if confidence == CONFIDENCE_PROVIDER_NAME:
                s["joined_by_provider_name_unpinned"] += 1
            else:
                s["joined_by_provider_and_service_name"] += 1
        else:
            s["unmatched"] += 1
            note = row["join_note"] or ""
            if note.startswith("ambiguous"):
                s["unmatched_ambiguous_name"] += 1
            if "ambiguous provider name" in note:
                s["unmatched_ambiguous_provider_name"] += 1
            reason = re.sub(
                r"\b(?:SE|PR)-\d{8}\b", "<key>", row["join_note"] or "no reason recorded"
            )
            reason = re.sub(r"\d+ candidate(?: provider)?s", "N candidates", reason)
            s["unmatched_reasons"][reason] = s["unmatched_reasons"].get(reason, 0) + 1
            if len(s["unmatched_examples"]) < UNMATCHED_EXAMPLES:
                s["unmatched_examples"].append(
                    {"record_id": row["record_id"], "action_type": row["action_type"]}
                )
    for s in per.values():
        joined_n = s["joined_exact_key"] + s["joined_by_name"] + s["joined_by_provider_name"]
        s["match_rate"] = round(joined_n / s["rows_in"], 4) if s["rows_in"] else None

    total = len(joined)
    matched = sum(1 for r in joined if r["match_confidence"] != CONFIDENCE_NONE)
    services_recent = sum(1 for r in service_rows if r["actions_last_24_months"] > 0)
    providers_recent = sum(1 for r in provider_rows if r["actions_last_24_months"] > 0)
    providers_recent_named = sum(
        1 for r in provider_rows if r["actions_last_24_months"] > 0 and r["name_withheld"] != "true"
    )
    return {
        "generated_at": utc_now().isoformat(),
        "window": {
            "months": WINDOW_MONTHS,
            "start": window[0].isoformat(),
            "end": window[1].isoformat(),
            "end_basis": "snapshot_last_modified of the ACECQA services snapshot",
        },
        "inputs": [str(p.relative_to(PROJECT_ROOT)) for p in action_files],
        "raw_inputs": [str(p.relative_to(PROJECT_ROOT)) for p in raw_inputs],
        "coverage": {**COVERAGE, "others": "SA, WA, TAS, NT, ACT not yet collected"},
        "overall": {
            "rows_in": total,
            "joined": matched,
            "unmatched": total - matched,
            "match_rate": round(matched / total, 4) if total else None,
        },
        "per_jurisdiction": dict(sorted(per.items())),
        "services_with_action_last_24_months": {
            "count": services_recent,
            "denominator_services": len(service_rows),
            "note": "counts actions of any type that were joined to the service; only states whose registers are collected can contribute",
        },
        "providers_with_action_last_24_months": {
            "count": providers_recent,
            "of_which_name_not_withheld": providers_recent_named,
            "denominator_providers": len(provider_rows),
        },
        "top_20_providers_by_actions_last_24_months": top_providers(
            provider_rows, types, by="count", min_services=0
        ),
        "top_20_providers_by_rate_per_service_min_5_services": top_providers(
            provider_rows, types, by="rate", min_services=5
        ),
        "caveats": [
            "Counts are of published enforcement actions of every type. Action types are kept in separate columns; prosecutions are not breaches.",
            "Rates divide actions in the window by the provider's current service_count, so they mix a historic numerator with a current denominator.",
            "Only NSW (from Jan 2025), VIC (from Jan 2026), QLD (from 2017, no keys) are collected; other states are not covered. "
            + SAFETY_SENTENCE,
            "Name-withheld providers are excluded from the top lists.",
            "Rows joined by provider name (provider_name_unique, provider_and_service_name) carry no printed key: they are accepted only when exactly one ACECQA provider has the normalised name, but a name match is weaker evidence than a key. actions_matched_by_name on each table shows how many of a row's counts rest on a name.",
            "Commonwealth CCS sanctions attach to the CCS approved provider, so a provider-name match is provider-level unless the service is pinned. ABNs are carried in enforcement-actions-all.csv for the Phase 4 ABR stage and are not matched here.",
        ],
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def discover_action_files() -> list[Path]:
    return sorted(PROCESSED_DIR.glob(ACTION_GLOB))


def main() -> None:
    action_files = discover_action_files()
    for needed in (SERVICES_CSV, PROFILE_CSV, PROVIDERS_CSV):
        if not needed.exists():
            raise SystemExit(
                f"missing {needed.relative_to(PROJECT_ROOT)}: "
                "run python3 scrapers/snapshot_acecqa_registers.py --no-fetch "
                "and python3 scrapers/profile_providers.py"
            )
    if not action_files:
        raise SystemExit("no *-enforcement-actions.csv files under data/processed/")

    services = load_csv(SERVICES_CSV)
    profiles = load_csv(PROFILE_CSV)
    providers = load_csv(PROVIDERS_CSV)
    spine = Spine(services, profiles, providers)
    end = snapshot_date(services)
    if end is None:
        raise SystemExit("no usable snapshot_last_modified in the services spine")
    window = window_bounds(end)
    types = load_action_types()

    actions: list[dict] = []
    for path in action_files:
        rows = load_csv(path)
        log.info("%s: %d rows", path.name, len(rows))
        actions.extend(rows)
    joined = join_actions(actions, spine)
    # Only claim CTH coverage in notes if CTH rows actually joined to a service or provider.
    cth_present = any(r["jurisdiction"] == "CTH" and r["join_key_kind"] != "none" for r in joined)
    service_rows, provider_rows = aggregate(joined, spine, types, window, cth_present)

    inputs = [SERVICES_CSV, PROVIDERS_CSV, PROFILE_CSV, *action_files]
    raw_inputs = transitive_inputs(inputs)

    base_note = (
        f"Built from {', '.join(p.name for p in inputs)}. Window: {WINDOW_MONTHS} calendar months "
        f"ending {window[1].isoformat()} (the ACECQA snapshot date), inclusive of {window[0].isoformat()}. "
        "Counts are of published enforcement actions of every type; action_type columns stay separate "
        "and prosecutions are not breaches. Rows flagged 'duplicate row in source' are kept but not "
        "counted. Coverage: NSW from Jan 2025, VIC from Jan 2026, QLD from 2017 (no keys), CTH rolling "
        f"12 months; SA, WA, TAS, NT, ACT not yet collected. {SAFETY_SENTENCE} "
        "Names of providers withheld as likely individuals stay null. "
        "ACECQA content is not openly licensed: internal use only."
    )
    write_processed(
        "enforcement-actions-all",
        joined,
        ALL_COLUMNS,
        raw_inputs=raw_inputs,
        schema="data/schemas/enforcement-action.schema.json",
        notes=base_note
        + " join_key_kind is the join that succeeded (none when unjoined); match_confidence "
        "unmatched means no join. occurrence numbers rows sharing a record_id. abn is carried from "
        "'ccs_identifier: ABN' notes for the Phase 4 ABR stage (null where the subject is withheld).",
    )
    write_processed(
        "enforcement-by-service",
        service_rows,
        service_columns(types),
        raw_inputs=raw_inputs,
        notes=base_note
        + " One row per ACECQA service; zero actions are zeros, not blanks. Provider-level actions "
        "are not attributed to individual services.",
    )
    write_processed(
        "enforcement-by-provider",
        provider_rows,
        provider_columns(types),
        raw_inputs=raw_inputs,
        notes=base_note
        + " One row per provider: its services' actions plus provider-level actions. "
        "actions_last_24_months_per_service divides by the provider's current service_count.",
    )

    report = build_report(
        joined, service_rows, provider_rows, types, window, raw_inputs, action_files
    )
    REPORT_JSON.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    log.info("wrote %s", REPORT_JSON.relative_to(PROJECT_ROOT))
    for j, s in report["per_jurisdiction"].items():
        log.info(
            "%s: %d rows, %d exact key, %d by service name, %d by provider name "
            "(%d pinned to a service), %d unmatched (match rate %s)",
            j,
            s["rows_in"],
            s["joined_exact_key"],
            s["joined_by_name"],
            s["joined_by_provider_name"],
            s["joined_by_provider_and_service_name"],
            s["unmatched"],
            s["match_rate"],
        )


if __name__ == "__main__":
    main()
