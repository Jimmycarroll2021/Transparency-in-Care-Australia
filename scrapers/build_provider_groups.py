"""Stage B and C of the ownership graph v0: ACECQA providers to ABN, then provider groups.

Stage B (provider to ABN), priority subset for this run:
- providers joined to at least one enforcement action in enforcement-actions-all.csv,
- providers with service_count of 5 or more,
- providers operating in more than one state,
in that order of priority. A provider is never queried when provider-profile.csv classes it
likely_individual or unknown, or has name_withheld true (CLAUDE.md rule 2); its row keeps no name.

For each remaining provider, ABN Lookup MatchingNames is called with the ACECQA Legal Name, and the
provider's registered state is used only to break a tie (the endpoint has no state filter). An ABN
is accepted only when exactly one distinct current, non-individual candidate carries a name whose
normalised form equals the normalised legal name and that candidate has the top score; otherwise
the row is ambiguous or no_match with the candidate count. Each accepted ABN is confirmed with
AbnDetails (ACN, entity type, status, business names). An ABR record that is, or may be, an
individual is excluded and keeps no name.

A cap on API calls (default 1,500) stops the run cleanly between providers; cached responses
younger than 30 days cost nothing, so a later run resumes where this one stopped.

Stage C (provider groups):
- entity groups: providers sharing an ABN or an ACN, i.e. one legal entity holding several
  provider approvals (link_reason shared_abn, shared_acn or shared_abn_and_acn);
- business-name overlap flags: a provider whose ABR business names, normalised, equal another
  ACECQA provider's Legal or Trading Name (link_reason business_name_overlap_holder for the holder,
  business_name_overlap_named for the other provider). A shared brand is not evidence of common
  ownership: franchises and unrelated users of one name exist.
Parent and subsidiary relationships are NOT derivable from free ABR data. They need paid ASIC
extracts and are out of scope.

Writes data/processed/provider-abn.csv, provider-groups.csv and provider-groups-summary.json.

Run:
  python3 scrapers/build_provider_groups.py                 stage B (capped) then stage C
  python3 scrapers/build_provider_groups.py --max-calls 300
  python3 scrapers/build_provider_groups.py --offline       stage B from the local cache only
  python3 scrapers/build_provider_groups.py --skip-lookup   stage C only, from provider-abn.csv
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

try:
    from scrapers import abn_lookup as al
    from scrapers.common import (
        PROCESSED_DIR,
        atomic_write_text,
        log,
        normalise_pr,
        utc_now,
        write_processed,
    )
    from scrapers.join_enforcement import normalise_provider_name
    from scrapers.profile_providers import name_is_withheld
except ImportError:  # run as a plain script
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from scrapers import abn_lookup as al
    from scrapers.common import (
        PROCESSED_DIR,
        atomic_write_text,
        log,
        normalise_pr,
        utc_now,
        write_processed,
    )
    from scrapers.join_enforcement import normalise_provider_name
    from scrapers.profile_providers import name_is_withheld

PROFILE_CSV = PROCESSED_DIR / "provider-profile.csv"
PROVIDERS_CSV = PROCESSED_DIR / "acecqa-providers-latest.csv"
ACTIONS_ALL_CSV = PROCESSED_DIR / "enforcement-actions-all.csv"
BY_PROVIDER_CSV = PROCESSED_DIR / "enforcement-by-provider.csv"
PROVIDER_ABN_NAME = "provider-abn"
GROUPS_NAME = "provider-groups"
SUMMARY_JSON = PROCESSED_DIR / "provider-groups-summary.json"

EXCLUDED_FORMS = {"likely_individual", "unknown"}
ACCEPTED_KINDS = {"accepted_unique", "accepted_unique_in_state"}
KIND_EXCLUDED = "excluded_individual_or_unknown"
KIND_EXCLUDED_ABR = "excluded_individual_abr"
KIND_ERROR = "lookup_error"
LARGEST_N = 10
CALLS_PER_PROVIDER = 2  # one name search, one confirmation

PROVIDER_ABN_COLUMNS = [
    "provider_approval_number",
    "legal_name",
    "abn",
    "acn",
    "entity_type_code",
    "entity_type_name",
    "abn_status",
    "business_names",
    "match_kind",
    "score",
    "candidates",
    "looked_up_at",
    "response_sha256",
    "abr_entity_name",
    "provider_state",
    "abr_state",
    "priority_reasons",
    "excluded_individual_candidates",
    "details_looked_up_at",
    "details_response_sha256",
    "note",
    "name_withheld",
]
GROUP_COLUMNS = [
    "group_id",
    "provider_approval_number",
    "legal_name",
    "abn",
    "acn",
    "link_reason",
    "name_withheld",
]
NAME_WITHHELD_NOTE = (
    "names withheld: provider name is not positively an organisation (CLAUDE.md rule 2)"
)

NOT_DERIVABLE = (
    "Parent and subsidiary relationships are NOT derivable from free ABR data: they need paid ASIC "
    "extracts and are out of scope. A group here is one legal entity (one ABN or ACN) holding "
    "several provider approvals, nothing more."
)


def load_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _int(value) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def excluded_profile(profile: dict) -> bool:
    return (profile.get("entity_form") or "").strip() in EXCLUDED_FORMS or (
        profile.get("name_withheld") or ""
    ).strip().lower() == "true"


def apply_name_filter(
    abn_rows: list[dict], profiles: dict[str, dict], known: set[str] | None = None
) -> int:
    """Apply the shared fail-closed name rule to provider-abn rows, in place, with no API call.

    A row whose provider is withheld in provider-profile.csv, or whose legal name is not
    positively an organisation, keeps its PR, ABN and ACN but loses every name column
    (legal_name, abr_entity_name, business_names) and gets name_withheld true. Otherwise each
    ABR business name and the ABR entity name must pass the same rule. Returns the number of
    rows whose names were nulled by this call.
    """
    changed = 0
    for row in abn_rows:
        for key, value in list(row.items()):
            if value == "":
                row[key] = None
        pr = row.get("provider_approval_number")
        profile = profiles.get(pr) or {}
        legal = row.get("legal_name")
        withhold = (excluded_profile(profile) if profile else False) or bool(
            legal and name_is_withheld(legal)
        )
        withhold = withhold or row.get("match_kind") in (KIND_EXCLUDED, KIND_EXCLUDED_ABR)
        # A row withheld by an earlier run stays withheld: the filter is idempotent.
        withhold = withhold or str(row.get("name_withheld") or "").lower() == "true"
        if withhold:
            had_name = any(row.get(c) for c in ("legal_name", "abr_entity_name", "business_names"))
            row.update(legal_name=None, abr_entity_name=None, business_names=None)
            row["name_withheld"] = "true"
            if had_name:
                changed += 1
                note = row.get("note") or ""
                if NAME_WITHHELD_NOTE not in note:
                    row["note"] = f"{note}; {NAME_WITHHELD_NOTE}" if note else NAME_WITHHELD_NOTE
            continue
        row["name_withheld"] = "false"
        if not al.name_is_safe(row.get("abr_entity_name"), known):
            row["abr_entity_name"] = None
        names = [
            n for n in (row.get("business_names") or "").split(al.BUSINESS_NAME_SEPARATOR) if n
        ]
        kept, _ = al.safe_business_names(names, known)
        row["business_names"] = al.BUSINESS_NAME_SEPARATOR.join(kept) or None
    return changed


# ---------------------------------------------------------------------------
# Stage B
# ---------------------------------------------------------------------------


def select_subset(profiles: list[dict], joined_prs: set[str]) -> list[tuple[dict, list[str]]]:
    """Priority subset, in priority order: joined, then 5+ services, then several states."""
    picked: dict[str, tuple[int, int, str, dict, list[str]]] = {}
    for prof in profiles:
        pr = normalise_pr(prof.get("provider_approval_number"))
        if not pr:
            continue
        reasons = []
        if pr in joined_prs:
            reasons.append("joined_to_enforcement")
        if _int(prof.get("service_count")) >= 5:
            reasons.append("service_count_5_plus")
        if _int(prof.get("state_count")) > 1:
            reasons.append("multi_state")
        if not reasons:
            continue
        tier = 0 if pr in joined_prs else (1 if _int(prof.get("service_count")) >= 5 else 2)
        picked[pr] = (tier, -_int(prof.get("service_count")), pr, prof, reasons)
    ordered = sorted(picked.values(), key=lambda t: (t[0], t[1], t[2]))
    return [(t[3], t[4]) for t in ordered]


def empty_row(pr: str, profile: dict, reasons: list[str]) -> dict:
    row = dict.fromkeys(PROVIDER_ABN_COLUMNS)
    row.update(
        provider_approval_number=pr,
        legal_name=(profile.get("legal_name") or "").strip() or None,
        provider_state=(profile.get("provider_state") or "").strip().upper() or None,
        priority_reasons="; ".join(reasons),
    )
    return row


def resolve_provider(
    client: al.AbnLookupClient, profile: dict, reasons: list[str], known: set[str]
) -> dict:
    """One provider-abn row. Raises BudgetExhausted only before any call for this provider."""
    pr = normalise_pr(profile.get("provider_approval_number"))
    row = empty_row(pr, profile, reasons)
    if excluded_profile(profile):
        row.update(
            legal_name=None,
            match_kind=KIND_EXCLUDED,
            note=f"not queried: entity_form {profile.get('entity_form') or 'blank'} "
            f"or name withheld (CLAUDE.md rule 2)",
        )
        return row
    legal = row["legal_name"]
    if not legal:
        row.update(match_kind="no_match", note="no legal name to search")
        return row
    try:
        search = client.matching_names(legal, state=row["provider_state"])
    except al.AbnLookupError as exc:
        log.warning("name search failed for %s: %s", pr, exc)
        row.update(match_kind=KIND_ERROR, note="name search failed; see the run log")
        return row
    decision = al.assess_candidates(search.data, legal, row["provider_state"])
    row.update(
        match_kind=decision["match_kind"],
        score=decision["score"],
        candidates=decision["candidates"],
        excluded_individual_candidates=decision["excluded_individual_candidates"],
        looked_up_at=search.looked_up_at,
        response_sha256=search.sha256,
        note=decision["note"],
    )
    if decision["match_kind"] not in ACCEPTED_KINDS:
        return row
    try:
        details = client.abn_details(decision["abn"])
    except al.BudgetExhausted:
        row.update(
            match_kind="accepted_unconfirmed",
            note=decision["note"] + "; AbnDetails not called: API call cap reached",
        )
        return row
    except al.AbnLookupError as exc:
        log.warning("ABN confirmation failed for %s: %s", pr, exc)
        row.update(match_kind=KIND_ERROR, note="AbnDetails failed; see the run log")
        return row
    drow = al.details_row(decision["abn"], details.data, details, known)
    row.update(
        details_looked_up_at=details.looked_up_at,
        details_response_sha256=details.sha256,
        entity_type_code=drow["entity_type_code"],
        entity_type_name=drow["entity_type_name"],
        abn_status=drow["abn_status"],
        abr_state=drow["address_state"],
    )
    if drow["lookup_status"] == "excluded_individual":
        row.update(
            legal_name=None,
            match_kind=KIND_EXCLUDED_ABR,
            score=None,
            note="ABR record is or may be an individual; no ABN or name recorded (CLAUDE.md rule 2)",
        )
        return row
    if drow["lookup_status"] != "ok":
        row.update(match_kind=KIND_ERROR, note=f"AbnDetails status {drow['lookup_status']}")
        return row
    row.update(
        abn=decision["abn"],
        acn=drow["acn"],
        business_names=drow["business_names"],
        abr_entity_name=drow["entity_name"],
    )
    if drow["note"]:
        row["note"] = f"{row['note']}; {drow['note']}"
    return row


def run_stage_b(client: al.AbnLookupClient) -> tuple[list[dict], dict]:
    profiles = load_csv(PROFILE_CSV)
    joined_prs = {
        r["acecqa_provider_approval_number"]
        for r in load_csv(ACTIONS_ALL_CSV)
        if r.get("acecqa_provider_approval_number")
    }
    subset = select_subset(profiles, joined_prs)
    known = al.known_org_names()
    rows: list[dict] = []
    stopped_at = None
    for i, (profile, reasons) in enumerate(subset):
        needs_call = not excluded_profile(profile) and (
            client.cached(
                al.ENDPOINT_NAMES,
                {
                    "name": (profile.get("legal_name") or "").strip(),
                    "maxResults": str(al.MAX_RESULTS),
                },
            )
            is None
        )
        remaining = None if client.max_calls is None else client.max_calls - client.calls_made
        if needs_call and remaining is not None and remaining < CALLS_PER_PROVIDER:
            stopped_at = i
            break
        try:
            rows.append(resolve_provider(client, profile, reasons, known))
        except al.BudgetExhausted:
            stopped_at = i
            break
        if (i + 1) % 100 == 0:
            log.info(
                "stage B: %d of %d providers, %d API calls", i + 1, len(subset), client.calls_made
            )
    remaining_providers = subset[stopped_at:] if stopped_at is not None else []
    kinds = Counter(r["match_kind"] for r in rows)
    excluded_forms = Counter(
        (p.get("entity_form") or "blank") for p, _ in subset if excluded_profile(p)
    )
    stats = {
        "subset_size": len(subset),
        "subset_rule": "joined to an enforcement action, or service_count >= 5, or state_count > 1",
        "providers_processed": len(rows),
        "providers_queried": sum(1 for r in rows if r["match_kind"] != KIND_EXCLUDED),
        "match_kinds": dict(sorted(kinds.items())),
        "accepted": sum(1 for r in rows if r["match_kind"] in ACCEPTED_KINDS and r["abn"]),
        "excluded_before_query_by_entity_form": dict(sorted(excluded_forms.items())),
        "excluded_as_individual_by_abr": kinds.get(KIND_EXCLUDED_ABR, 0),
        "excluded_individual_candidates_discarded": sum(
            _int(r["excluded_individual_candidates"]) for r in rows
        ),
        "api_calls": client.calls_made,
        "cache_hits": client.cache_hits,
        "max_calls": client.max_calls,
        "stopped_by_call_cap": stopped_at is not None,
        "providers_remaining": len(remaining_providers),
        "providers_remaining_excluding_individuals": sum(
            1 for p, _ in remaining_providers if not excluded_profile(p)
        ),
    }
    return rows, stats


# ---------------------------------------------------------------------------
# Stage C
# ---------------------------------------------------------------------------


class _UnionFind:
    def __init__(self):
        self.parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def build_groups(
    abn_rows: list[dict], provider_names: dict[str, set], legal_names: dict[str, str]
) -> list[dict]:
    """Entity groups (shared ABN or ACN) plus business-name overlap flags.

    provider_names: normalised ACECQA Legal or Trading Name -> PRs (individuals already removed).
    legal_names: PR -> ACECQA legal name, for providers whose name may be shown.
    """
    accepted = [r for r in abn_rows if r.get("abn") and r.get("match_kind") in ACCEPTED_KINDS]
    by_pr = {r["provider_approval_number"]: r for r in accepted}
    uf = _UnionFind()
    by_abn: dict[str, list[str]] = defaultdict(list)
    by_acn: dict[str, list[str]] = defaultdict(list)
    for r in accepted:
        pr = r["provider_approval_number"]
        uf.find(pr)
        by_abn[r["abn"]].append(pr)
        if r.get("acn"):
            by_acn[r["acn"]].append(pr)
    for members in list(by_abn.values()) + list(by_acn.values()):
        for other in members[1:]:
            uf.union(members[0], other)
    components: dict[str, list[str]] = defaultdict(list)
    for pr in by_pr:
        components[uf.find(pr)].append(pr)

    out: list[dict] = []
    group_of: dict[str, str] = {}
    for members in components.values():
        if len(members) < 2:
            continue
        group_id = "G-" + min(by_pr[m]["abn"] for m in members)
        for pr in sorted(members):
            r = by_pr[pr]
            shared_abn = len(by_abn[r["abn"]]) > 1
            shared_acn = bool(r.get("acn")) and len(by_acn[r["acn"]]) > 1
            reason = (
                "shared_abn_and_acn"
                if shared_abn and shared_acn
                else ("shared_abn" if shared_abn else "shared_acn")
            )
            group_of[pr] = group_id
            out.append(
                {
                    "group_id": group_id,
                    "provider_approval_number": pr,
                    "legal_name": r.get("legal_name"),
                    "abn": r["abn"],
                    "acn": r.get("acn"),
                    "link_reason": reason,
                    "name_withheld": "false" if r.get("legal_name") else "true",
                }
            )

    for pr in sorted(by_pr):
        r = by_pr[pr]
        named: set[str] = set()
        for name in (r.get("business_names") or "").split(al.BUSINESS_NAME_SEPARATOR):
            key = normalise_provider_name(name)
            if key:
                named |= provider_names.get(key, set())
        named.discard(pr)
        if pr in group_of:
            named = {o for o in named if group_of.get(o) != group_of[pr]}
        if not named:
            continue
        group_id = f"BN-{pr}"
        out.append(
            {
                "group_id": group_id,
                "provider_approval_number": pr,
                "legal_name": r.get("legal_name"),
                "abn": r["abn"],
                "acn": r.get("acn"),
                "link_reason": "business_name_overlap_holder",
                "name_withheld": "false" if r.get("legal_name") else "true",
            }
        )
        for other in sorted(named):
            o = by_pr.get(other, {})
            out.append(
                {
                    "group_id": group_id,
                    "provider_approval_number": other,
                    "legal_name": legal_names.get(other) or None,
                    "abn": o.get("abn"),
                    "acn": o.get("acn"),
                    "link_reason": "business_name_overlap_named",
                    "name_withheld": "false" if legal_names.get(other) else "true",
                }
            )
    return out


def summarise(
    groups: list[dict], abn_rows: list[dict], by_provider: list[dict], stats: dict | None
) -> dict:
    enforcement = {r["provider_approval_number"]: r for r in by_provider}
    window = next(
        ((r.get("window_start"), r.get("window_end")) for r in by_provider if r.get("window_end")),
        (None, None),
    )
    entity_name = {r["provider_approval_number"]: r.get("abr_entity_name") for r in abn_rows}
    entity_groups: dict[str, list[dict]] = defaultdict(list)
    overlap_groups: dict[str, list[dict]] = defaultdict(list)
    for g in groups:
        (entity_groups if g["group_id"].startswith("G-") else overlap_groups)[g["group_id"]].append(
            g
        )
    accepted = sum(1 for r in abn_rows if r.get("abn") and r.get("match_kind") in ACCEPTED_KINDS)

    def describe(gid: str, members: list[dict]) -> dict:
        prs = [m["provider_approval_number"] for m in members]
        names = Counter(entity_name.get(p) for p in prs if entity_name.get(p))
        return {
            "group_id": gid,
            "abr_entity_name": names.most_common(1)[0][0] if names else None,
            "abns": sorted({m["abn"] for m in members if m["abn"]}),
            "provider_approvals": len(prs),
            "total_services": sum(_int(enforcement.get(p, {}).get("service_count")) for p in prs),
            "actions_last_24_months": sum(
                _int(enforcement.get(p, {}).get("actions_last_24_months")) for p in prs
            ),
            "link_reasons": sorted({m["link_reason"] for m in members}),
        }

    described = [describe(gid, members) for gid, members in entity_groups.items()]
    described.sort(key=lambda d: (-d["provider_approvals"], -d["total_services"], d["group_id"]))
    return {
        "generated_at": utc_now().isoformat(),
        "denominators": {
            "providers_in_provider_abn": len(abn_rows),
            "providers_with_accepted_abn": accepted,
            "note": "Groups are formed only among providers with an accepted ABN in this run's "
            "priority subset; providers not yet looked up cannot appear in a group.",
        },
        "entity_groups": len(entity_groups),
        "providers_in_entity_groups": sum(len(v) for v in entity_groups.values()),
        "entity_group_size_distribution": dict(
            sorted(Counter(len(v) for v in entity_groups.values()).items())
        ),
        "business_name_overlap_flags": len(overlap_groups),
        "providers_named_by_overlap_flags": sum(
            1
            for v in overlap_groups.values()
            for m in v
            if m["link_reason"] == "business_name_overlap_named"
        ),
        "window": {"start": window[0], "end": window[1], "basis": "enforcement-by-provider.csv"},
        f"largest_{LARGEST_N}_entity_groups": described[:LARGEST_N],
        "stage_b_run": stats,
        "caveats": [
            NOT_DERIVABLE,
            "A business-name overlap flag is a lead, not a finding: a shared brand or trading name "
            "is not evidence of common ownership.",
            "total_services is the sum of current ACECQA service counts of the group's provider "
            "approvals. actions_last_24_months counts published enforcement actions of every type "
            "in the window (not breaches), only from registers collected so far. Absence of an "
            "action is not evidence of safety.",
            "ABNs come from a name match on ABN Lookup and are not verified by hand. Verify any "
            "ABN on ABN Lookup before it is shown publicly. ACECQA content is not openly licensed: "
            "internal use only.",
        ],
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def profiles_by_pr() -> dict[str, dict]:
    return {
        normalise_pr(p.get("provider_approval_number")): p
        for p in load_csv(PROFILE_CSV)
        if normalise_pr(p.get("provider_approval_number"))
    }


def acecqa_names() -> tuple[dict[str, set], dict[str, str]]:
    provider_names: dict[str, set] = defaultdict(set)
    legal: dict[str, str] = {}
    for prof in load_csv(PROFILE_CSV):
        pr = normalise_pr(prof.get("provider_approval_number"))
        if not pr or excluded_profile(prof):
            continue
        name = (prof.get("legal_name") or "").strip()
        if name and not name_is_withheld(name):
            legal[pr] = name
        for col in ("legal_name", "trading_name"):
            key = normalise_provider_name(prof.get(col))
            if key:
                provider_names[key].add(pr)
    return provider_names, legal


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--max-calls", type=int, default=al.DEFAULT_MAX_CALLS)
    parser.add_argument("--offline", action="store_true", help="use the local cache only")
    parser.add_argument("--skip-lookup", action="store_true", help="stage C only")
    args = parser.parse_args(argv)

    provider_abn_csv = PROCESSED_DIR / f"{PROVIDER_ABN_NAME}.csv"
    stats = None
    if args.skip_lookup:
        if not provider_abn_csv.exists():
            raise SystemExit("no provider-abn.csv: run without --skip-lookup first")
        abn_rows = load_csv(provider_abn_csv)
        prov = PROCESSED_DIR / f"{PROVIDER_ABN_NAME}.provenance.json"
        stats = json.loads(prov.read_text(encoding="utf-8")).get("run")
        # Deterministic post-processing of the committed table: no ABN Lookup call is made.
        changed = apply_name_filter(abn_rows, profiles_by_pr(), al.known_org_names())
        al.rewrite_processed(PROVIDER_ABN_NAME, abn_rows, PROVIDER_ABN_COLUMNS, al.REFILTER_NOTE)
        log.info("provider-abn: name filter re-applied offline, %d rows newly withheld", changed)
    else:
        guid = None if args.offline else al.load_guid()
        try:
            client = al.AbnLookupClient(guid, max_calls=args.max_calls, offline=args.offline)
        except al.AbnLookupError as exc:
            raise SystemExit(f"ABN lookup error: {exc}") from None
        abn_rows, stats = run_stage_b(client)
        apply_name_filter(abn_rows, profiles_by_pr(), al.known_org_names())
        write_processed(
            PROVIDER_ABN_NAME,
            abn_rows,
            PROVIDER_ABN_COLUMNS,
            raw_inputs=[PROFILE_CSV, ACTIONS_ALL_CSV],
            notes=(
                "One row per provider in the priority subset processed this run (joined to an "
                "enforcement action, or 5+ services, or several states). match_kind: "
                "accepted_unique, accepted_unique_in_state, ambiguous, no_match, "
                f"{KIND_EXCLUDED} (never queried; no name kept), {KIND_EXCLUDED_ABR} (ABR says "
                "individual; no ABN or name kept), accepted_unconfirmed, lookup_error. score is the "
                "MatchingNames score of the accepted candidate; candidates is the number of "
                "distinct current non-individual ABNs returned (maxResults 10). looked_up_at and "
                "response_sha256 are for the name search; details_* for the AbnDetails "
                "confirmation. ABR business names that read as a person's name are withheld unless "
                "already an ACECQA organisation name. " + NOT_DERIVABLE
            ),
        )
        al.add_abr_provenance(PROVIDER_ABN_NAME, {**al.ABR_PROVENANCE, "run": stats})
        log.info("stage B: %s", json.dumps(stats))

    provider_names, legal = acecqa_names()
    groups = build_groups(abn_rows, provider_names, legal)
    write_processed(
        GROUPS_NAME,
        groups,
        GROUP_COLUMNS,
        raw_inputs=[provider_abn_csv, PROFILE_CSV],
        notes=(
            "group_id G-<lowest ABN> is an entity group: providers sharing an ABN or ACN "
            "(link_reason shared_abn, shared_acn, shared_abn_and_acn). group_id BN-<PR> is a "
            "business-name overlap flag: the holder's ABR business name equals the named "
            "provider's ACECQA Legal or Trading Name after normalisation; a shared brand is not "
            "evidence of common ownership. " + NOT_DERIVABLE
        ),
    )
    by_provider = load_csv(BY_PROVIDER_CSV) if BY_PROVIDER_CSV.exists() else []
    summary = summarise(groups, abn_rows, by_provider, stats)
    summary["inputs"] = [
        f"data/processed/{PROVIDER_ABN_NAME}.csv",
        f"data/processed/{GROUPS_NAME}.csv",
        "data/processed/enforcement-by-provider.csv",
    ]
    atomic_write_text(SUMMARY_JSON, json.dumps(summary, indent=2) + "\n")
    log.info(
        "stage C: %d entity groups (%d providers), %d business-name overlap flags",
        summary["entity_groups"],
        summary["providers_in_entity_groups"],
        summary["business_name_overlap_flags"],
    )


if __name__ == "__main__":
    main()
