"""Ownership layer 1: provider-to-group edges from the Modern Slavery Statements Register (MSR).

Every provider named in a candidate statement is a relation, classified into exactly one of:
- controlled_entity_of: an included entity in a Single statement (one reporting entity). Under
  the Modern Slavery Act 2018 such a statement covers the entities the reporting entity owns or
  controls, so this reads "included in the group's statement as owned or controlled". This is the
  only ownership edge.
- group_parent_self: the provider is the reporting entity of a Single statement that lists
  included entities. It marks a group head; it is not an edge to another provider.
- co_reported_joint: any relation from a Joint statement. Joint statements can combine unrelated
  bodies, so these are never edges, even when one corporate group filed them.
Two residual classes are counted but written nowhere: a reporting entity of a Single statement
with no included entities (self_report_no_included_entities), and any other statement type
(unclassified_statement). The MSR covers only entities with consolidated revenue of at least
AUD 100 million, plus voluntary reporters.

Steps:
1. Read the MSR resources page, find the all-statements CSV, download it. Columns that could hold
   an individual's name (signatories, approvers, contacts) are dropped before anything is stored.
2. Candidate statements: any ABN listed on the statement (the CSV ABN column holds reporting and
   included entities' ABNs) equals a provider ABN in provider-abn.csv, or the reporting entities'
   text contains a childcare term.
3. Fetch each candidate's statement page (at least 2 s apart, robots.txt honoured) and parse the
   reporting entities and included entities (name, and ABN where the statement gives one).
4. Matching, strongest first, one relation per provider and statement: an entity's ABN equals a
   provider ABN; or an included entity listed without an ABN whose normalised name equals exactly
   one ACECQA provider legal name AND that provider's ABR entity name. Everything else that looks
   like a match goes to the review queue, never to a relation.
5. Edges and group heads are collapsed to one row per provider and group from the latest
   statement, listing every statement id and URL. The group key is the reporting entity's ABN,
   taken from the statement, else from another candidate statement naming the same entity with
   one ABN, else NAME:<normalised name>.

Licence: the MSR shows "Copyright Attorney-General's Department" and no open licence. Raw MSR files
and their sidecars stay in data/raw/msr/, which is gitignored. Only derived facts are written to
data/processed/. Providers that are, or may be, individuals never appear in any output.

Writes data/processed/provider-group-edges-msr.csv (controlled_entity_of only),
provider-group-heads-msr.csv, provider-coreported-msr.csv and provider-group-review-msr.csv, each
with a provenance JSON, plus provider-group-edges-msr-summary.json.

Run:
  python3 scrapers/build_msr_group_edges.py              fetch the CSV and candidate pages
  python3 scrapers/build_msr_group_edges.py --no-fetch   rebuild from the newest local snapshots
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import time
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup

try:
    from scrapers.common import (
        PROCESSED_DIR,
        PROJECT_ROOT,
        RAW_DIR,
        Fetched,
        fetch,
        list_snapshots,
        log,
        normalise_pr,
        utc_now,
        write_processed,
        write_snapshot,
    )
    from scrapers.join_enforcement import normalise_provider_name
    from scrapers.profile_providers import classify_entity_form
except ImportError:  # run as a plain script
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from scrapers.common import (
        PROCESSED_DIR,
        PROJECT_ROOT,
        RAW_DIR,
        Fetched,
        fetch,
        list_snapshots,
        log,
        normalise_pr,
        utc_now,
        write_processed,
        write_snapshot,
    )
    from scrapers.join_enforcement import normalise_provider_name
    from scrapers.profile_providers import classify_entity_form

BASE_URL = "https://modernslaveryregister.gov.au"
RESOURCES_URL = f"{BASE_URL}/resources/"
SOURCE_RESOURCES = "msr/resources"
SOURCE_CSV = "msr/all-statements"
SOURCE_PAGES = "msr/statements"
PAGE_DELAY_SECONDS = 2.0

PROFILE_CSV = PROCESSED_DIR / "provider-profile.csv"
PROVIDER_ABN_CSV = PROCESSED_DIR / "provider-abn.csv"
SERVICES_CSV = PROCESSED_DIR / "acecqa-services-latest.csv"
EDGES_NAME = "provider-group-edges-msr"
REVIEW_NAME = "provider-group-review-msr"
HEADS_NAME = "provider-group-heads-msr"
COREPORTED_NAME = "provider-coreported-msr"
SUMMARY_JSON = PROCESSED_DIR / f"{EDGES_NAME}-summary.json"

CHILDCARE_TERMS = re.compile(r"early\s+learning|child\s*care|kindergarten|education", re.IGNORECASE)
_ALL_STATEMENTS_LINK = re.compile(r"all-statement-information_[\d-]+\.csv$")
# Column names that could carry an individual's name or contact details. Dropped at ingest.
_PERSON_COLUMN = re.compile(
    r"sign|approv|contact|director|officer|person|individual|e-?mail|phone|"
    r"first.?name|last.?name|surname|full.?name|author|submitter|prepared",
    re.IGNORECASE,
)
_PAGE_ID = re.compile(r"/statements/(\d+)/?$")
_SUFFIX_TAIL = re.compile(r"\s+(?:PTY LTD|LTD|INC)$")
EXCLUDED_FORMS = {"likely_individual", "unknown"}
ACCEPTED_KINDS = {"accepted_unique", "accepted_unique_in_state"}
WITHHELD = "[withheld: may name an individual]"
# One edge per provider and statement: the strongest method wins.
_RANK = {
    "reporting_entity_abn_equals_provider_abn": 0,
    "included_entity_abn_equals_provider_abn": 1,
    "included_name_equals_acecqa_and_abr_name": 2,
}

CONTROLLED = "controlled_entity_of"
HEAD = "group_parent_self"
JOINT = "co_reported_joint"
SELF_ONLY = "self_report_no_included_entities"
UNCLASSIFIED = "unclassified_statement"
JOINT_CAVEAT = "joint statement: co-reporting, not evidence of ownership"

_COLLAPSED = [
    "provider_approval_number",
    "provider_legal_name",
    "provider_abn",
    "relation",
    "group_key",
    "group_key_source",
    "group_name",
    "statement_id",
    "statement_url",
    "reporting_period",
    "statement_count",
    "statement_ids",
    "statement_urls",
]
EDGE_COLUMNS = [
    *_COLLAPSED[:3],
    "edge_type",
    *_COLLAPSED[3:],
    "match_method",
    "match_methods",
    "msr_entity_name",
    "captured_at",
    "page_sha256",
]
HEAD_COLUMNS = [
    *_COLLAPSED,
    "included_entities_listed",
    "controlled_providers_linked",
    "captured_at",
    "page_sha256",
]
COREPORTED_COLUMNS = [
    "provider_approval_number",
    "provider_legal_name",
    "provider_abn",
    "relation",
    "caveat",
    "msr_role",
    "match_method",
    "msr_entity_name",
    "statement_key",
    "statement_id",
    "statement_url",
    "reporting_period",
    "reporting_entity_count",
    "first_listed_reporting_entity",
    "included_entities_listed",
    "captured_at",
    "page_sha256",
]
REVIEW_COLUMNS = [
    "statement_id",
    "statement_page_id",
    "statement_url",
    "statement_type",
    "reporting_period",
    "reporting_entity_count",
    "first_listed_reporting_entity",
    "msr_role",
    "msr_entity_name",
    "msr_entity_abn",
    "reason",
    "candidate_provider_approval_numbers",
    "candidate_provider_legal_names",
    "captured_at",
]

EDGE_DEFINITION = (
    "controlled_entity_of: the provider is listed as an included entity in a Single modern "
    "slavery statement on the Modern Slavery Statements Register, that is, included in the "
    "group's statement as owned or controlled by the one reporting entity (group_key). Matched "
    "by the included entity's ABN, or by exact normalised name agreeing with both the ACECQA legal "
    "name and the ABR entity name. It is not a verified ownership chain, shareholding or date of "
    "acquisition. This is the only ownership edge in this layer."
)
HEAD_DEFINITION = (
    "group_parent_self: the provider is itself the one reporting entity of a Single statement "
    "that lists included entities. It marks the provider as a group head; it is not an edge to "
    "another provider."
)
JOINT_DEFINITION = (
    "co_reported_joint: the provider is named (as a reporting or included entity) in a Joint "
    "statement. Joint statements can combine unrelated bodies, so these rows are never edges."
)


# ---------------------------------------------------------------------------
# Download and privacy filter
# ---------------------------------------------------------------------------


def find_all_statements_link(resources_html: str) -> str | None:
    """Absolute URL of the all-statements CSV on the resources page, or None."""
    soup = BeautifulSoup(resources_html, "html.parser")
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if _ALL_STATEMENTS_LINK.search(href):
            return urljoin(RESOURCES_URL, href)
    return None


def privacy_filter_csv(text: str) -> tuple[str, list[str], list[str]]:
    """Drop columns that could hold an individual's name. Returns (text, kept, dropped).

    The text is returned unchanged when nothing is dropped, so its hash equals the source's.
    """
    reader = csv.reader(io.StringIO(text))
    header = next(reader, [])
    clean = [h.lstrip("﻿") for h in header]
    dropped = [h for h in clean if _PERSON_COLUMN.search(h)]
    kept = [h for h in clean if h not in dropped]
    if not dropped:
        return text, kept, dropped
    keep_idx = [i for i, h in enumerate(clean) if h in kept]
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(kept)
    for row in reader:
        writer.writerow([row[i] if i < len(row) else "" for i in keep_idx])
    return buf.getvalue(), kept, dropped


# ---------------------------------------------------------------------------
# CSV parsing and candidates
# ---------------------------------------------------------------------------


def _abns(value: str | None) -> list[str]:
    out = []
    for part in (value or "").split(","):
        digits = re.sub(r"\D", "", part)
        if len(digits) == 11:
            out.append(digits)
    return out


def parse_statements_csv(text: str) -> list[dict]:
    """One dict per statement row. page_id comes from the statement URL (IDX is not unique)."""
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    out = []
    for row in reader:
        link = (row.get("Link") or "").strip()
        m = _PAGE_ID.search(link)
        start, end = (row.get("PeriodStart") or "").strip(), (row.get("PeriodEnd") or "").strip()
        out.append(
            {
                "statement_id": (row.get("IDX") or "").strip(),
                "page_id": m.group(1) if m else None,
                "statement_url": link or None,
                "type": (row.get("Type") or "").strip(),
                "period_start": start or None,
                "period_end": end or None,
                "reporting_period": f"{start} to {end}" if start and end else None,
                "reporting_entities_text": (row.get("ReportingEntities") or "").strip(),
                "abns": _abns(row.get("ABN")),
            }
        )
    return out


def select_candidates(statements: list[dict], provider_abns: set[str]) -> list[dict]:
    """Statements naming a provider ABN as a reporting entity, or with a childcare term."""
    out = []
    for s in statements:
        if not s["page_id"]:
            continue
        if set(s["abns"]) & provider_abns:
            reason = "abn_match"
        elif CHILDCARE_TERMS.search(s["reporting_entities_text"]):
            reason = "childcare_term"
        else:
            continue
        out.append({**s, "candidate_reason": reason})
    return out


# ---------------------------------------------------------------------------
# Statement pages
# ---------------------------------------------------------------------------


def _entities(section) -> list[dict]:
    out = []
    if section is None:
        return out
    for div in section.find_all("div", class_="statement-entity"):
        link = div.find("a", class_="statement-entity__name-link")
        name = " ".join(link.get_text(" ").split()) if link else ""
        abn = None
        abn_link = div.find("a", href=re.compile(r"^/statements/\?abn="))
        if abn_link:
            digits = re.sub(r"\D", "", abn_link.get_text())
            abn = digits if len(digits) == 11 else None
        if name:
            out.append({"name": name, "abn": abn})
    return out


def parse_statement_page(page_html: str) -> dict:
    """Reporting and included entities as {name, abn}. Included entities are de-duplicated.

    Many statements list included entities by name only; others give an ABN for some or all.
    """
    soup = BeautifulSoup(page_html, "html.parser")
    reporting = _entities(soup.find(id="statement-reporting-entities"))
    included: list[dict] = []
    seen: set[tuple[str, str | None]] = set()
    for ent in _entities(soup.find(id="statement-included-entities")):
        key = (normalise(ent["name"]), ent["abn"])
        if key[0] and key not in seen:
            seen.add(key)
            included.append(ent)
    return {"reporting": reporting, "included": included}


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


def normalise(name: str | None) -> str:
    """Case, whitespace, punctuation, PTY LTD variants and a leading THE (join_enforcement)."""
    return normalise_provider_name(name)


def loose_key(name: str | None) -> str:
    """Normalised name without its trailing PTY LTD, LTD or INC. Review queue only."""
    return _SUFFIX_TAIL.sub("", normalise(name)).strip()


def _excluded(profile: dict) -> bool:
    return (profile.get("entity_form") or "").strip() in EXCLUDED_FORMS or (
        profile.get("name_withheld") or ""
    ).strip().lower() == "true"


def _shown_name(name: str | None) -> str | None:
    """An MSR entity name, or WITHHELD when it reads as a person's name.

    MSR names are entities named in a statement under the Act, so a name the classifier cannot
    place ('unknown', for example a university or a school) is shown. A name that reads as a
    person ('likely_individual') is always withheld, even though most are organisations.
    """
    if not name:
        return None
    return WITHHELD if classify_entity_form(name) == "likely_individual" else name


class _Index:
    def __init__(self, profiles: list[dict], abn_rows: list[dict]):
        self.legal: dict[str, str] = {}
        self.excluded: set[str] = set()
        self.by_name: dict[str, set[str]] = defaultdict(set)
        self.by_loose: dict[str, set[str]] = defaultdict(set)
        for p in profiles:
            pr = normalise_pr(p.get("provider_approval_number"))
            if not pr:
                continue
            legal = (p.get("legal_name") or "").strip()
            if _excluded(p):
                self.excluded.add(pr)
            else:
                self.legal[pr] = legal
            if normalise(legal):
                self.by_name[normalise(legal)].add(pr)
                self.by_loose[loose_key(legal)].add(pr)
        self.abn_of: dict[str, str] = {}
        self.abr_name: dict[str, str] = {}
        self.by_abn: dict[str, list[str]] = defaultdict(list)
        for r in abn_rows:
            pr = normalise_pr(r.get("provider_approval_number"))
            abn = (r.get("abn") or "").strip()
            if not pr or not abn or pr in self.excluded:
                continue
            if (r.get("match_kind") or "") not in ACCEPTED_KINDS:
                continue
            if (r.get("entity_type_code") or "").strip().upper() == "IND":
                self.excluded.add(pr)
                continue
            self.abn_of[pr] = abn
            self.abr_name[pr] = (r.get("abr_entity_name") or "").strip()
            self.by_abn[abn].append(pr)
            self.legal.setdefault(pr, (r.get("legal_name") or "").strip())


def _statement_facts(statement: dict) -> dict:
    reporting = statement["parsed"]["reporting"]
    return {
        "statement_id": statement["statement_id"],
        "statement_page_id": statement["page_id"],
        "statement_url": statement["statement_url"],
        "statement_type": statement.get("type"),
        "reporting_period": statement.get("reporting_period"),
        "period_end": statement.get("period_end") or statement.get("reporting_period") or "",
        "reporting_entity_count": len(reporting),
        "first_listed_reporting_entity": _shown_name(reporting[0]["name"]) if reporting else None,
        "included_entities_listed": len(statement["parsed"]["included"]),
        "captured_at": statement.get("captured_at"),
        "page_sha256": statement.get("page_sha256"),
    }


def _name_abn_map(statements: list[dict]) -> dict[str, str]:
    """Normalised reporting-entity name -> ABN, where every statement giving one agrees."""
    seen: dict[str, set[str]] = defaultdict(set)
    for s in statements:
        for rep in (s.get("parsed") or {}).get("reporting", []):
            if rep["abn"] and normalise(rep["name"]):
                seen[normalise(rep["name"])].add(rep["abn"])
    return {k: next(iter(v)) for k, v in seen.items() if len(v) == 1}


def _single_group(statement: dict, name_abn: dict[str, str]) -> dict:
    """Group key and name of a statement with exactly one reporting entity."""
    rep = statement["parsed"]["reporting"][0]
    key = normalise(rep["name"])
    if rep["abn"]:
        group_key, source = rep["abn"], "abn_on_statement"
    elif key in name_abn:
        group_key, source = name_abn[key], "abn_of_same_name_on_another_statement"
    else:
        group_key, source = f"NAME:{key}", "name_only"
    return {
        "group_key": group_key,
        "group_key_source": source,
        "group_name": _shown_name(rep["name"]),
    }


def classify_relation(rel: dict) -> str:
    """Exactly one class per relation. Only CONTROLLED is an ownership edge."""
    if rel["statement_type"] == "Joint":
        return JOINT
    if rel["statement_type"] != "Single" or rel["reporting_entity_count"] != 1:
        return UNCLASSIFIED
    if rel["msr_role"] == "included_entity":
        return CONTROLLED
    return HEAD if rel["included_entities_listed"] > 0 else SELF_ONLY


def match_relations(
    statements: list[dict], profiles: list[dict], abn_rows: list[dict]
) -> tuple[list[dict], list[dict], dict]:
    """Provider-statement relations, review queue and match statistics.

    A relation is one provider named in one statement, by its strongest match. A relation is not
    an edge: classify_relation decides what each one means.
    """
    idx = _Index(profiles, abn_rows)
    relations: dict[tuple[str, str], dict] = {}
    review: list[dict] = []
    stats = Counter()

    def add_relation(s: dict, pr: str, role: str, method: str, msr_name: str) -> None:
        k = (pr, s["page_id"])
        if k in relations and _RANK[relations[k]["match_method"]] <= _RANK[method]:
            return
        relations[k] = {
            **_statement_facts(s),
            "provider_approval_number": pr,
            "provider_legal_name": idx.legal.get(pr),
            "provider_abn": idx.abn_of.get(pr),
            "msr_role": role,
            "match_method": method,
            "msr_entity_name": _shown_name(msr_name),
        }

    def add_review(s: dict, role: str, name: str, abn: str | None, reason: str, prs) -> None:
        prs = sorted(prs)
        shown = _shown_name(name)
        names = "" if shown == WITHHELD else "; ".join(idx.legal.get(p, "") for p in prs)
        facts = _statement_facts(s)
        review.append(
            {
                **{k: facts[k] for k in facts if k in REVIEW_COLUMNS},
                "msr_role": role,
                "msr_entity_name": shown,
                "msr_entity_abn": abn,
                "reason": reason,
                "candidate_provider_approval_numbers": "; ".join(prs),
                "candidate_provider_legal_names": names,
            }
        )

    def match_entity(s: dict, role: str, name: str, abn: str | None) -> None:
        matched = idx.by_abn.get(abn or "", [])
        for pr in matched:
            add_relation(s, pr, role, f"{role}_abn_equals_provider_abn", name)
        if matched:
            return
        key = normalise(name)
        if not key:
            return
        prs = idx.by_name.get(key, set())
        visible = prs - idx.excluded
        if prs & idx.excluded:
            stats["matches_to_excluded_providers"] += 1
        if len(prs) > 1:
            if visible:
                add_review(s, role, name, abn, "ambiguous_matches_several_providers", visible)
            return
        if len(prs) == 1:
            if not visible:
                return
            (pr,) = visible
            if abn and pr in idx.abn_of:
                reason = "msr_abn_differs_from_provider_abn"
            elif abn:
                reason = "name_match_provider_abn_not_resolved"
            elif role == "reporting_entity":
                reason = "reporting_entity_name_only"
            elif pr not in idx.abn_of:
                reason = "name_unique_provider_without_abn"
            elif normalise(idx.abr_name.get(pr)) == key:
                add_relation(s, pr, role, "included_name_equals_acecqa_and_abr_name", name)
                return
            else:
                reason = "abr_name_disagrees"
            add_review(s, role, name, abn, reason, visible)
            return
        loose = idx.by_loose.get(loose_key(name), set())
        if loose & idx.excluded:
            stats["matches_to_excluded_providers"] += 1
        if loose - idx.excluded:
            add_review(s, role, name, abn, "fuzzy_corporate_suffix_differs", loose - idx.excluded)

    name_abn = _name_abn_map(statements)
    for s in statements:
        s = {**s, "parsed": s.get("parsed") or {"reporting": [], "included": []}}
        parsed = s["parsed"]
        for rep in parsed["reporting"]:
            match_entity(s, "reporting_entity", rep["name"], rep["abn"])
        stats["included_entities_parsed"] += len(parsed["included"])
        stats["included_entities_with_abn"] += sum(1 for i in parsed["included"] if i["abn"])
        for inc in parsed["included"]:
            match_entity(s, "included_entity", inc["name"], inc["abn"])
        single = (s.get("type") or "") == "Single" and len(parsed["reporting"]) == 1
        group = (
            _single_group(s, name_abn)
            if single
            else {"group_key": None, "group_key_source": None, "group_name": None}
        )
        for (_, page), rel in relations.items():
            if page == s["page_id"]:
                rel.update(group)
                rel["relation"] = classify_relation(rel)

    out = sorted(
        relations.values(),
        key=lambda r: (r["provider_approval_number"], r["period_end"], r["statement_id"]),
    )
    review.sort(key=lambda r: (r["statement_id"], r["msr_role"], r["msr_entity_name"] or ""))
    stats.setdefault("matches_to_excluded_providers", 0)
    return out, review, dict(stats)


def _page_order(rel: dict) -> tuple[str, int]:
    page = str(rel.get("statement_page_id") or "0")
    return (rel["period_end"], int(page) if page.isdigit() else 0)


def collapse(relations: list[dict], relation: str) -> list[dict]:
    """One row per provider and group for a class: the latest statement, listing every one."""
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in relations:
        if r["relation"] == relation:
            grouped[(r["provider_approval_number"], r["group_key"])].append(r)
    out = []
    for _, rows in sorted(grouped.items()):
        rows.sort(key=_page_order)
        latest = rows[-1]
        out.append(
            {
                **latest,
                "edge_type": relation,
                "statement_count": len(rows),
                "statement_ids": "; ".join(r["statement_id"] for r in rows),
                "statement_urls": "; ".join(r["statement_url"] for r in rows),
                "match_methods": "; ".join(sorted({r["match_method"] for r in rows})),
            }
        )
    return out


def build_layer(statements: list[dict], profiles: list[dict], abn_rows: list[dict]) -> dict:
    """Edges (controlled_entity_of only), group heads, joint co-reporting rows and review queue."""
    relations, review, stats = match_relations(statements, profiles, abn_rows)
    edges = collapse(relations, CONTROLLED)
    heads = collapse(relations, HEAD)
    linked: dict[str, set[str]] = defaultdict(set)
    for e in edges:
        linked[e["group_key"]].add(e["provider_approval_number"])
    for h in heads:
        h["controlled_providers_linked"] = len(linked.get(h["group_key"], set()))
    coreported = [
        {**r, "caveat": JOINT_CAVEAT, "statement_key": f"MSR-{r['statement_page_id']}"}
        for r in relations
        if r["relation"] == JOINT
    ]
    return {
        "relations": relations,
        "edges": edges,
        "heads": heads,
        "coreported": coreported,
        "review": review,
        "stats": stats,
    }


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def _services(services: list[dict], prs: set[str]) -> int:
    return sum(1 for s in services if normalise_pr(s.get("provider_approval_number")) in prs)


def joint_manual_candidates(coreported: list[dict]) -> list[dict]:
    """Joint statements that list a provider as an included entity. Never promoted to edges.

    Some are filed by one corporate group and may describe ownership; that needs confirmation
    from another source.
    """
    by_stmt: dict[str, list[dict]] = defaultdict(list)
    for r in coreported:
        if r["msr_role"] == "included_entity":
            by_stmt[r["statement_key"]].append(r)
    out = []
    for _, rows in sorted(by_stmt.items(), key=lambda kv: kv[1][0]["statement_id"]):
        first = rows[0]
        out.append(
            {
                "statement_id": first["statement_id"],
                "statement_url": first["statement_url"],
                "reporting_period": first["reporting_period"],
                "reporting_entity_count": first["reporting_entity_count"],
                "first_listed_reporting_entity": first["first_listed_reporting_entity"],
                "included_providers": sorted({r["provider_approval_number"] for r in rows}),
            }
        )
    return out


def summarise(
    layer: dict, abn_rows: list[dict], services: list[dict], *, candidates_count: int
) -> dict:
    edges, heads, coreported = layer["edges"], layer["heads"], layer["coreported"]
    relations, review, stats = layer["relations"], layer["review"], layer["stats"]
    priority = {normalise_pr(r.get("provider_approval_number")) for r in abn_rows} - {None}
    priority_with_abn = {
        normalise_pr(r.get("provider_approval_number")) for r in abn_rows if r.get("abn")
    } - {None}
    edge_prs = {e["provider_approval_number"] for e in edges}
    head_prs = {h["provider_approval_number"] for h in heads}
    joint_prs = {r["provider_approval_number"] for r in coreported}
    group_keys = sorted({e["group_key"] for e in edges})
    periods = sorted(e["reporting_period"] for e in edges if e.get("reporting_period"))
    groups = []
    for key in group_keys:
        members = [e for e in edges if e["group_key"] == key]
        latest = max(members, key=_page_order)
        prs = {e["provider_approval_number"] for e in members}
        groups.append(
            {
                "group_key": key,
                "group_name": latest["group_name"],
                "controlled_providers": len(prs),
                "services_of_controlled_providers": _services(services, prs),
                "head_provider": next(
                    (h["provider_approval_number"] for h in heads if h["group_key"] == key), None
                ),
            }
        )
    groups.sort(key=lambda g: (-g["controlled_providers"], g["group_key"]))
    return {
        "generated_at": utc_now().isoformat(),
        "definitions": [EDGE_DEFINITION, HEAD_DEFINITION, JOINT_DEFINITION],
        "counts": {
            "candidate_statements": candidates_count,
            "included_entities_parsed": stats.get("included_entities_parsed", 0),
            "included_entities_with_abn": stats.get("included_entities_with_abn", 0),
            "relations_total": len(relations),
            "relations_by_class": dict(sorted(Counter(r["relation"] for r in relations).items())),
            "controlled_entity_of": {
                "edges": len(edges),
                "distinct_providers": len(edge_prs),
                "groups": len(group_keys),
                "priority_providers_gained_edge": len(edge_prs & priority),
                "services_of_those_providers": _services(services, edge_prs),
                "edges_by_latest_match_method": dict(
                    sorted(Counter(e["match_method"] for e in edges).items())
                ),
            },
            "group_parent_self_not_ownership_edges": {
                "rows": len(heads),
                "distinct_providers": len(head_prs),
                "services_of_those_providers": _services(services, head_prs),
            },
            "co_reported_joint_not_ownership": {
                "rows": len(coreported),
                "distinct_providers": len(joint_prs),
                "statements": len({r["statement_key"] for r in coreported}),
                "providers_only_in_joint_statements": len(joint_prs - edge_prs - head_prs),
            },
            "priority_providers_total": len(priority),
            "priority_providers_with_abn": len(priority_with_abn),
            "services_total": len(services),
            "review_queue": len(review),
            "review_by_reason": dict(sorted(Counter(r["reason"] for r in review).items())),
            "matches_to_excluded_providers": stats.get("matches_to_excluded_providers", 0),
        },
        "window": {
            "edge_reporting_periods_earliest": periods[0] if periods else None,
            "edge_reporting_periods_latest": periods[-1] if periods else None,
        },
        "groups": groups,
        "joint_statements_for_manual_confirmation": joint_manual_candidates(coreported),
        "caveats": [
            EDGE_DEFINITION,
            HEAD_DEFINITION,
            JOINT_DEFINITION,
            "The register covers entities with annual consolidated revenue of at least AUD 100 "
            "million, plus voluntary reporters. Absence of an edge says nothing about ownership.",
            "Name-matched edges are not verified by ABN or ACN; they need the ACECQA legal name "
            "and the ABR entity name to agree.",
            "Each edge is collapsed to one row per provider and group from the latest statement; "
            "statement_ids lists every statement. A provider in an older statement may since have "
            "changed hands.",
            "MSR licence unclear (Copyright Attorney-General's Department). Raw MSR files are not "
            "committed. Ask the department before any public display.",
            "Service counts are current ACECQA service approvals from acecqa-services-latest.csv. "
            "ACECQA content is not openly licensed.",
        ],
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _load_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _meta(path: Path) -> dict:
    meta = Path(f"{path}.meta.json")
    return json.loads(meta.read_text(encoding="utf-8")) if meta.exists() else {}


def acquire_csv(no_fetch: bool) -> tuple[Path, dict]:
    """Newest privacy-filtered all-statements CSV snapshot, fetching a new one unless no_fetch."""
    if not no_fetch:
        page = fetch(RESOURCES_URL)
        write_snapshot(SOURCE_RESOURCES, page, "html")
        url = find_all_statements_link(page.text)
        if not url:
            raise SystemExit("no all-statements CSV link on the MSR resources page")
        got = fetch(url)
        text, kept, dropped = privacy_filter_csv(got.content.decode("utf-8-sig"))
        filtered = got
        if dropped:
            filtered = Fetched(**{**got.__dict__, "content": text.encode("utf-8")})
        write_snapshot(
            SOURCE_CSV,
            filtered,
            "csv",
            extra_meta={
                "source_sha256": got.sha256,
                "source_bytes": len(got.content),
                "columns_kept": kept,
                "columns_dropped_for_privacy": dropped,
            },
        )
    snaps = list_snapshots(SOURCE_CSV)
    if not snaps:
        raise SystemExit("no MSR CSV snapshot: run without --no-fetch first")
    return snaps[-1], _meta(snaps[-1])


def acquire_page(statement: dict, no_fetch: bool, last: list[float]) -> tuple[Path | None, dict]:
    """Newest snapshot of a statement page; fetched only when no local copy exists."""
    source = f"{SOURCE_PAGES}/{statement['page_id']}"
    snaps = list_snapshots(source)
    if not snaps and not no_fetch:
        wait = PAGE_DELAY_SECONDS - (time.monotonic() - last[0])
        if wait > 0:
            time.sleep(wait)
        got = fetch(statement["statement_url"])
        last[0] = time.monotonic()
        write_snapshot(source, got, "html")
        snaps = list_snapshots(source)
    if not snaps:
        return None, {}
    return snaps[-1], _meta(snaps[-1])


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--no-fetch", action="store_true", help="use local snapshots only")
    args = parser.parse_args(argv)

    csv_path, csv_meta = acquire_csv(args.no_fetch)
    statements = parse_statements_csv(csv_path.read_text(encoding="utf-8-sig"))
    abn_rows = _load_csv(PROVIDER_ABN_CSV)
    provider_abns = {r["abn"] for r in abn_rows if r.get("abn")}
    candidates = select_candidates(statements, provider_abns)
    log.info("%d statements, %d candidates", len(statements), len(candidates))

    last = [0.0]
    page_paths: list[Path] = []
    missing = []
    for s in candidates:
        path, meta = acquire_page(s, args.no_fetch, last)
        if path is None:
            missing.append(s["statement_id"])
            continue
        page_paths.append(path)
        s["parsed"] = parse_statement_page(path.read_text(encoding="utf-8"))
        s["captured_at"] = meta.get("fetched_at")
        s["page_sha256"] = meta.get("sha256")

    profiles = _load_csv(PROFILE_CSV)
    parsed = [s for s in candidates if "parsed" in s]
    layer = build_layer(parsed, profiles, abn_rows)
    services = _load_csv(SERVICES_CSV) if SERVICES_CSV.exists() else []
    if not services:
        log.warning("no %s: service counts will be 0", SERVICES_CSV.name)

    raw_inputs = [csv_path, *page_paths, PROVIDER_ABN_CSV, PROFILE_CSV]
    local_only = (
        " Raw MSR inputs listed here are a local cache only (data/raw/msr/ is gitignored: licence "
        "unclear)."
    )
    write_processed(
        EDGES_NAME,
        layer["edges"],
        EDGE_COLUMNS,
        raw_inputs=raw_inputs,
        notes=EDGE_DEFINITION
        + " One row per provider and group, from the latest statement; statement_ids and "
        "statement_urls list every statement. group_key is the reporting entity's ABN "
        "(group_key_source says where it came from) or NAME:<normalised name>." + local_only,
    )
    write_processed(
        HEADS_NAME,
        layer["heads"],
        HEAD_COLUMNS,
        raw_inputs=raw_inputs,
        notes=HEAD_DEFINITION + local_only,
    )
    write_processed(
        COREPORTED_NAME,
        layer["coreported"],
        COREPORTED_COLUMNS,
        raw_inputs=raw_inputs,
        notes=JOINT_DEFINITION + f" Every row carries the caveat '{JOINT_CAVEAT}'." + local_only,
    )
    write_processed(
        REVIEW_NAME,
        layer["review"],
        REVIEW_COLUMNS,
        raw_inputs=raw_inputs,
        notes="Possible links that did not meet the matching rule: ambiguous names, ABR or ABN "
        "disagreement, providers without a resolved ABN, corporate-suffix differences and "
        "reporting entities matched by name only. Not evidence of ownership. MSR names that may "
        f"be an individual's are shown as '{WITHHELD}'." + local_only,
    )
    summary = summarise(layer, abn_rows, services, candidates_count=len(candidates))
    summary["counts"]["candidate_pages_missing"] = len(missing)
    summary["source"] = {
        "csv_url_pattern": f"{BASE_URL}/resources/all-statement-information_<date>.csv",
        "csv_fetched_at": csv_meta.get("fetched_at"),
        "csv_url": csv_meta.get("url"),
        "csv_sha256": csv_meta.get("source_sha256") or csv_meta.get("sha256"),
        "csv_statement_rows": len(statements),
        "columns_kept": csv_meta.get("columns_kept"),
        "columns_dropped_for_privacy": csv_meta.get("columns_dropped_for_privacy"),
        "robots": "robots.txt honoured via scrapers.common.fetch; statement pages fetched at "
        f"least {PAGE_DELAY_SECONDS:.0f} s apart",
        "licence": "No licence shown; 'Copyright Attorney-General's Department'. Raw not committed.",
    }
    summary["candidate_statements"] = [
        {
            "statement_id": s["statement_id"],
            "statement_url": s["statement_url"],
            "reporting_period": s["reporting_period"],
            "candidate_reason": s["candidate_reason"],
            "reporting_entities": [
                {"name": _shown_name(r["name"]), "abn": r["abn"]}
                for r in (s.get("parsed") or {}).get("reporting", [])
            ],
            "included_entities": len((s.get("parsed") or {}).get("included", [])),
        }
        for s in candidates
    ]
    summary["inputs"] = [
        p.relative_to(PROJECT_ROOT).as_posix()
        for p in (PROVIDER_ABN_CSV, PROFILE_CSV, SERVICES_CSV)
    ] + [RAW_DIR.relative_to(PROJECT_ROOT).as_posix() + "/msr/ (local only)"]
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    log.info("summary: %s", json.dumps(summary["counts"]))


if __name__ == "__main__":
    main()
