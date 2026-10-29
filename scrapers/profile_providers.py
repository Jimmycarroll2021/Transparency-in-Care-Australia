"""Profile ACECQA approved providers: entity form, service counts, states operated in.

Reads the processed ACECQA registers (data/processed/acecqa-providers-latest.csv and
acecqa-services-latest.csv, rebuilt from the raw snapshot by snapshot_acecqa_registers.py) and writes:

- data/processed/provider-profile.csv           one row per provider
- data/processed/provider-profile-summary.json  aggregate counts and top providers by service count

Privacy (CLAUDE.md rule 2, applied at ingest): providers classed as likely_individual keep a row
in the CSV, but Legal Name and Trading Name are null and name_withheld is true. Their names never
appear in the summary, in log lines or in any printed list. Street addresses are not carried over.

ACECQA content is not openly licensed: outputs are for internal use only.

Run: python3 scrapers/profile_providers.py
"""

from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

try:
    from scrapers.common import PROCESSED_DIR, PROJECT_ROOT, log, utc_now, write_processed
except ImportError:  # run as a plain script: python3 scrapers/profile_providers.py
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from scrapers.common import PROCESSED_DIR, PROJECT_ROOT, log, utc_now, write_processed

PROVIDERS_CSV = PROCESSED_DIR / "acecqa-providers-latest.csv"
SERVICES_CSV = PROCESSED_DIR / "acecqa-services-latest.csv"
SUMMARY_JSON = PROCESSED_DIR / "provider-profile-summary.json"

ENTITY_FORMS = (
    "company",
    "incorporated_association",
    "cooperative",
    "government",
    "trust_or_trustee",
    "church_or_religious",
    "likely_individual",
    "unknown",
)

# ---------------------------------------------------------------------------
# Name normalisation (also the basis for the planned ABR name match)
# ---------------------------------------------------------------------------

_ACN_TAG = re.compile(r"\(?\bA\.?C\.?N\.?\s*\d[\d\s]{7,}\d\)?")
_PTY_LTD_TAIL = re.compile(r"\b(?:PTY|PROPRIETARY)(?: LTD| LIMITED)$|\bP L$")
_LTD_TAIL = re.compile(r"\b(?:LTD|LIMITED)$")
_INC_TAIL = re.compile(r"\b(?:INC|INCORPORATED)$")


def normalise_name(name: str | None) -> str | None:
    """Upper case, strip punctuation, collapse whitespace, canonicalise the corporate tail.

    Tails become one of PTY LTD, LTD or INC. Returns None for blank input.
    """
    if not name:
        return None
    s = _ACN_TAG.sub(" ", name.upper())
    s = s.replace("&", " AND ")
    s = re.sub(r"[‘’'`]", "", s)  # O'BRIEN -> OBRIEN, not O BRIEN
    s = re.sub(r"[^A-Z0-9]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return None
    s = re.sub(r"\bPTY LTD$|\bPTY LIMITED$|\bPROPRIETARY LIMITED$|\bP L$", "PTY LTD", s)
    s = _LTD_TAIL.sub("LTD", s) if not s.endswith("PTY LTD") else s
    s = _INC_TAIL.sub("INC", s)
    return s


def strip_corporate_suffix(name: str | None) -> str | None:
    """Normalised name without its trailing PTY LTD, LTD or INC. Used for looser matching."""
    norm = normalise_name(name)
    if norm is None:
        return None
    for tail in (" PTY LTD", " LTD", " INC"):
        if norm.endswith(tail):
            return norm[: -len(tail)].strip() or None
    return norm


# ---------------------------------------------------------------------------
# Entity form classifier
# ---------------------------------------------------------------------------

_I = re.IGNORECASE
_TRUSTEE = re.compile(r"\b(?:as\s+trustee|trustee\s+for|trustee\s+of|a\.?t\.?f\.?)\b", _I)
_TRUST_WORD = re.compile(r"\b(?:trust|trustee|trustees)\b", _I)
_GOV_STRONG = re.compile(
    r"\b(?:minister|department|dept|state\s+of|crown|commonwealth\s+of|city\s+of|shire\s+of|"
    r"shire\s+council|city\s+council|regional\s+council|municipal\w*)\b",
    _I,
)
# Applies only when there is no company, Inc or Association marker (a school's parents and
# citizens association is an association, not the government).
_GOV_WEAK = re.compile(
    r"\b(?:council|shire|government\s+school\w*|public\s+school|state\s+school|"
    r"local\s+health\s+district|tafe|technical\s+and\s+further\s+education)\b",
    _I,
)
_CHURCH = re.compile(
    r"\b(?:parish|diocese|diocesan|uniting|anglican|catholic|baptist|lutheran|"
    r"salvation\s+army|presbyterian)\b",
    _I,
)
_COOP = re.compile(r"\b(?:co-?operative|co-?op|coop)\b", _I)
_COMPANY = re.compile(
    r"(?:\bpty\.?\s*(?:ltd|limited)?\b|\bproprietary\s+limited\b|\bltd\b\.?|\blimited\b|\bp/l\b)",
    _I,
)
_INC = re.compile(r"\b(?:inc|incorporated)\b\.?", _I)
_ASSOC = re.compile(r"\b(?:association|assoc|assn)\b", _I)

# Words that mark a business, school, charity or place rather than a person.
_BUSINESS_WORDS = frozenset(
    """
    child children childcare care kids kid kindergarten kinder preschool pre school schools learning
    education educational centre center centres services service group holdings australia
    australian foundation club society community college academy montessori nursery playgroup
    daycare ymca ymcas council shire department ministry health hospital university
    institute association trust network enterprises investments management
    partners partnership operations solutions
    """.split()
)
_PERSON_PARTICLES = frozenset(
    {"de", "del", "della", "van", "von", "der", "den", "bin", "al", "el", "le", "la", "di"}
)
_PERSON_TOKEN = re.compile(r"^[A-Za-z][A-Za-z.'\u2019\-]*$")
_TRADING_AS = re.compile(r"\s+(?:t/as?|trading\s+as)\s+", _I)
_PARTNER_SPLIT = re.compile(r"\s*(?:&|\+|;|\band\b)\s*", _I)


def _person_segment(tokens: list[str]) -> bool:
    """One to five name-like words: capitalised (particles excepted), no business word."""
    if not 1 <= len(tokens) <= 5:
        return False
    if not all(_PERSON_TOKEN.match(t) for t in tokens):
        return False
    if {t.lower().strip(".") for t in tokens} & _BUSINESS_WORDS:
        return False
    if all(t.islower() for t in tokens):  # carelessly typed all-lowercase names
        return True
    return all(t.lower() in _PERSON_PARTICLES or t[0].isupper() for t in tokens)


def _looks_like_person(name: str) -> bool:
    """A person's name, or a partnership of people, with no corporate marker or business word.

    Covers 'Given Surname', 'Given M Surname', 'A Surname & B Surname' and the same followed by
    'T/A <business name>' (the business name is dropped before the test). The spec asks for two
    or three words; up to five are allowed per person here because under-withholding a person's
    name is the costlier error. Over-withholding only nulls a name in the CSV.
    """
    left = _TRADING_AS.split(name.strip(), maxsplit=1)[0].replace(",", " ").strip()
    parts = [p.split() for p in _PARTNER_SPLIT.split(left)]
    if any(not p for p in parts):
        return False
    if len(parts) == 1:
        return len(parts[0]) >= 2 and _person_segment(parts[0])
    return all(_person_segment(p) for p in parts) and any(len(p) >= 2 for p in parts)


def classify_entity_form(legal_name: str | None) -> str:
    """Conservative classification of a provider legal name. Order of the checks matters."""
    if not legal_name or not legal_name.strip():
        return "unknown"
    name = legal_name.strip()
    has_company = bool(_COMPANY.search(name))
    has_inc = bool(_INC.search(name))
    has_assoc = bool(_ASSOC.search(name))

    if _TRUSTEE.search(name):
        return "trust_or_trustee"
    if _CHURCH.search(name):
        return "church_or_religious"
    if _GOV_STRONG.search(name):
        return "government"
    if _GOV_WEAK.search(name) and not (has_company or has_inc or has_assoc):
        return "government"
    if _COOP.search(name):
        return "cooperative"
    if has_inc:
        return "incorporated_association"
    if has_company:
        return "company"
    if has_assoc:
        return "incorporated_association"
    if _TRUST_WORD.search(name):
        return "trust_or_trustee"
    if _looks_like_person(name):
        return "likely_individual"
    return "unknown"


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _raw_inputs_of(processed: Path) -> list[Path]:
    prov = processed.with_suffix(".provenance.json")
    if not prov.exists():
        return [processed]
    listed = json.loads(prov.read_text()).get("raw_inputs", [])
    paths = [PROJECT_ROOT / p for p in listed]
    return [processed, *paths]


def _to_int(value: str | None) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _band(n: int) -> str:
    if n == 0:
        return "0"
    if n == 1:
        return "1"
    if n <= 4:
        return "2-4"
    if n <= 9:
        return "5-9"
    if n <= 24:
        return "10-24"
    return "25+"


def build_profile() -> dict:
    providers = _read(PROVIDERS_CSV)
    services = _read(SERVICES_CSV)

    by_provider: dict[str, list[dict[str, str]]] = defaultdict(list)
    unlinked_services = 0
    for svc in services:
        pr = svc.get("provider_approval_number") or ""
        if pr:
            by_provider[pr].append(svc)
        else:
            unlinked_services += 1

    mgmt_cols = [
        c
        for c in (services[0].keys() if services else [])
        if "management" in c.lower() or "provider type" in c.lower()
    ]

    rows: list[dict] = []
    seen: set[str] = set()
    null_log: Counter[str] = Counter()
    for p in providers:
        pr = p.get("provider_approval_number") or ""
        if not pr:
            null_log["provider_approval_number_missing"] += 1
            continue
        if pr in seen:
            null_log["duplicate_provider_row_skipped"] += 1
            continue
        seen.add(pr)
        form = classify_entity_form(p.get("Legal Name"))
        withheld = form == "likely_individual"
        svcs = by_provider.get(pr, [])
        states = sorted({s["State"] for s in svcs if s.get("State")})
        places = [_to_int(s.get("NumberOfApprovedPlaces")) for s in svcs]
        known_places = [x for x in places if x is not None]
        row = {
            "provider_approval_number": pr,
            "legal_name": None if withheld else (p.get("Legal Name") or None),
            "trading_name": None if withheld else (p.get("Trading Name") or None),
            "name_withheld": "true" if withheld else "false",
            "entity_form": form,
            "provider_state": p.get("State") or None,
            "date_approval_granted": p.get("Date Approval Granted") or None,
            "service_count": len(svcs),
            "states_operated_in": "|".join(states) or None,
            "state_count": len(states),
            "family_day_care_services": sum(
                1 for s in svcs if s.get("ServiceType") == "Family Day Care"
            ),
            "total_approved_places": sum(known_places) if known_places else None,
            "services_without_places_value": len(places) - len(known_places),
        }
        if mgmt_cols:
            row["management_type"] = (
                "|".join(sorted({s[mgmt_cols[0]] for s in svcs if s.get(mgmt_cols[0])})) or None
            )
        rows.append(row)
        if not svcs:
            null_log["provider_with_no_services_in_services_table"] += 1

    fieldnames = [
        "provider_approval_number",
        "legal_name",
        "trading_name",
        "name_withheld",
        "entity_form",
        "provider_state",
        "date_approval_granted",
        "service_count",
        "states_operated_in",
        "state_count",
        "family_day_care_services",
        "total_approved_places",
        "services_without_places_value",
    ]
    if mgmt_cols:
        fieldnames.append("management_type")

    raw_inputs = _raw_inputs_of(PROVIDERS_CSV) + _raw_inputs_of(SERVICES_CSV)
    write_processed(
        "provider-profile",
        rows,
        fieldnames,
        raw_inputs=raw_inputs,
        notes=(
            "One row per provider (provider_approval_number). entity_form is a conservative "
            "classification of Legal Name by suffix and keyword; it is a heuristic, not a legal "
            "determination. likely_individual rows have legal_name and trading_name null and "
            "name_withheld true (CLAUDE.md rule 2). Addresses are not carried over. "
            "service_count joins on provider_approval_number in the services table; providers "
            "with no services in that table have service_count 0, which is not evidence that "
            "they operate none. ACECQA content is not openly licensed: internal use only."
        ),
    )

    # ---- summary (never includes names of likely_individual providers) ----
    form_counts = Counter(r["entity_form"] for r in rows)
    form_services: Counter[str] = Counter()
    for r in rows:
        form_services[r["entity_form"]] += r["service_count"]
    total_providers = len(rows)
    total_services_linked = sum(r["service_count"] for r in rows)

    non_individual = [r for r in rows if r["name_withheld"] == "false"]
    top = sorted(
        non_individual, key=lambda r: (-r["service_count"], r["provider_approval_number"])
    )[:30]
    top_out = [
        {
            "provider_approval_number": r["provider_approval_number"],
            "legal_name": r["legal_name"],
            "trading_name": r["trading_name"],
            "entity_form": r["entity_form"],
            "service_count": r["service_count"],
            "states_operated_in": r["states_operated_in"],
        }
        for r in top
    ]

    summary = {
        "generated_at": utc_now().isoformat(),
        "inputs": {
            "providers_file": str(PROVIDERS_CSV.relative_to(PROJECT_ROOT)),
            "services_file": str(SERVICES_CSV.relative_to(PROJECT_ROOT)),
            "provider_rows": len(providers),
            "service_rows": len(services),
            "snapshot_last_modified_providers": (
                providers[0].get("snapshot_last_modified") if providers else None
            ),
            "snapshot_last_modified_services": (
                services[0].get("snapshot_last_modified") if services else None
            ),
            "raw_inputs": [str(p.relative_to(PROJECT_ROOT)) for p in raw_inputs],
        },
        "window_note": (
            "Point-in-time counts from the ACECQA register snapshot named above, not a time series. "
            "Denominator for every share: providers in the providers file, or services in the "
            "services file."
        ),
        "providers_total": total_providers,
        "services_total": len(services),
        "services_linked_to_a_provider_row": total_services_linked,
        "services_with_no_provider_approval_number": unlinked_services,
        "entity_form_counts": {f: form_counts.get(f, 0) for f in ENTITY_FORMS},
        "entity_form_share_of_providers": {
            f: round(form_counts.get(f, 0) / total_providers, 4) if total_providers else None
            for f in ENTITY_FORMS
        },
        "entity_form_service_counts": {f: form_services.get(f, 0) for f in ENTITY_FORMS},
        "entity_form_share_of_services": {
            f: round(form_services.get(f, 0) / total_services_linked, 4)
            if total_services_linked
            else None
            for f in ENTITY_FORMS
        },
        "likely_individual_providers_names_withheld": form_counts.get("likely_individual", 0),
        "providers_with_no_services_in_services_table": null_log[
            "provider_with_no_services_in_services_table"
        ],
        "providers_by_service_count_band": dict(
            sorted(Counter(_band(r["service_count"]) for r in rows).items(), key=lambda kv: kv[0])
        ),
        "providers_operating_in_more_than_one_state": sum(1 for r in rows if r["state_count"] > 1),
        "service_type_distribution": dict(
            Counter(s.get("ServiceType") or "null" for s in services)
        ),
        "management_type": (
            {
                "column": mgmt_cols[0],
                "distribution": dict(Counter(s.get(mgmt_cols[0]) or "null" for s in services)),
            }
            if mgmt_cols
            else {
                "available": False,
                "reason": (
                    "Neither ACECQA export has a management type or provider type column "
                    "(headers checked). service_type_distribution is service type "
                    "(Centre-Based Care or Family Day Care), not management type. entity_form "
                    "is the only proxy, and it is inferred from the legal name."
                ),
            }
        ),
        "top_30_providers_by_service_count": top_out,
        "top_30_note": (
            "likely_individual providers are excluded from this list by design. Service count is "
            "approved services on the register on the snapshot date, out of the services_total above. "
            "A large count does not by itself indicate any compliance concern."
        ),
        "row_level_logs": dict(null_log),
        "caveat": "entity_form is heuristic. Absence of a flag is not evidence of safety.",
    }
    SUMMARY_JSON.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    log.info("summary %s", SUMMARY_JSON.relative_to(PROJECT_ROOT))
    log.info("entity_form counts: %s", summary["entity_form_counts"])
    return summary


def main() -> None:
    for path in (PROVIDERS_CSV, SERVICES_CSV):
        if not path.exists():
            raise SystemExit(
                f"missing {path.relative_to(PROJECT_ROOT)}; run "
                "python3 scrapers/snapshot_acecqa_registers.py --no-fetch"
            )
    build_profile()


if __name__ == "__main__":
    main()
