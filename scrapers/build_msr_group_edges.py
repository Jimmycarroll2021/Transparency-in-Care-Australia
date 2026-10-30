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
   taken from the statement, else an ABN given for the same name on another candidate statement
   when the ABR confirms it (non-individual type, same ABR entity name), else
   MSR-<statement page id>. No key is derived from a name.

Licence: the MSR shows "Copyright Attorney-General's Department" and no open licence. Raw MSR files
and their sidecars stay in data/raw/msr/, which is gitignored. Only derived facts are written to
data/processed/. Providers that are, or may be, individuals never appear in any output.

Name policy: outputs carry only two kinds of name. provider_legal_name is the ACECQA legal name,
keyed by provider_approval_number, for providers not classed as individuals by ACECQA or the ABR.
group_name is the ABR entity name of the reporting entity's ABN, shown only when the ABR entity
type for that ABN is known locally (provider-abn.csv, abn-details.csv) and is not an individual
or sole trader. No name read from the register is ever written: review, co-reported and summary
rows carry statement ids, URLs, ABNs and match methods only.

Writes data/processed/provider-group-edges-msr.csv (controlled_entity_of only),
provider-group-heads-msr.csv, provider-coreported-msr.csv and provider-group-review-msr.csv, each
with a provenance JSON, plus provider-group-edges-msr-summary.json.

Run:
  python3 scrapers/build_msr_group_edges.py              fetch the CSV and candidate pages
  python3 scrapers/build_msr_group_edges.py --no-fetch   rebuild from the newest local snapshots
  python3 scrapers/build_msr_group_edges.py --refresh    take a new snapshot of every candidate page

Exit codes: 0 complete. 2 incomplete, outputs left unchanged: a candidate page is missing, a
fetch failed (always 2 with --refresh), the entity markup is not recognised, or the CSV lists
included entities that the page does not yield. 1 nothing usable: no CSV snapshot, no candidate,
or no page readable.
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

from bs4 import BeautifulSoup, Comment, NavigableString

try:
    from scrapers.common import (
        PROCESSED_DIR,
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
except ImportError:  # run as a plain script
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from scrapers.common import (
        PROCESSED_DIR,
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

BASE_URL = "https://modernslaveryregister.gov.au"
RESOURCES_URL = f"{BASE_URL}/resources/"
SOURCE_RESOURCES = "msr/resources"
SOURCE_CSV = "msr/all-statements"
SOURCE_PAGES = "msr/statements"
PAGE_DELAY_SECONDS = 2.0
SERVICES_MISSING_NOTE = (
    "data/processed/acecqa-services-latest.csv was not available, so every service count is "
    "null (unknown), not zero. Run python3 scrapers/snapshot_acecqa_registers.py --no-fetch "
    "and rebuild."
)

PROFILE_CSV = PROCESSED_DIR / "provider-profile.csv"
PROVIDER_ABN_CSV = PROCESSED_DIR / "provider-abn.csv"
ABN_DETAILS_CSV = PROCESSED_DIR / "abn-details.csv"
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
# ABR entity type codes that mean an individual or sole trader. Any other known code is a
# non-individual entity (company, trust, partnership, government, charity and so on).
INDIVIDUAL_ABR_TYPES = {"IND"}
NAME_SHOWN = "shown_abr_organisation_type"
NAME_ABR_INDIVIDUAL = "withheld_abr_individual"
NAME_ABR_UNKNOWN = "withheld_abr_type_unknown"
NAME_NO_ABN = "withheld_no_abn"
NAME_TYPE_NOT_ALLOWED = "withheld_abr_type_not_allowed"
NAME_MAY_EMBED_PERSON = "withheld_name_may_embed_person"
NAME_ABR_CONFLICT = "withheld_abr_type_conflict"
# Owner rule 2, fail closed: a group name is shown only for these ABR entity types (companies,
# government entities and statutory authorities, co-operatives, other incorporated entities such
# as incorporated associations). Trusts, partnerships, unincorporated entities, superannuation
# funds and any type not listed show the ABN only. Only codes seen in local ABR data are listed.
ALLOWED_GROUP_ABR_TYPES = {"PRV", "PUB", "COP", "OIE", "LGE", "LGA", "SGE", "TGE"}
# Wording that can embed a person's name (a family trust, a trustee for a named trust).
_PERSON_WORDING = re.compile(
    r"family\s+trust|trustee\s+for|as\s+trustee|\bA\.?T\.?F\b\.?", re.IGNORECASE
)
# A CSV IncludedEntities segment that ends an entity: an ABN in brackets or a corporate suffix.
_ENTITY_END = re.compile(
    r"(?:\((?:\d\s?){11}\)|\b(?:PTY\.?\s*LTD|PTY\.?\s*LIMITED|PROPRIETARY\s+LIMITED|LTD|"
    r"LIMITED|INC|INCORPORATED|LLC|PLC|GMBH|PTE\.?\s*LTD|SDN\.?\s*BHD|CO-?OPERATIVE|TRUST|"
    r"CORPORATION)\.?)\s*$",
    re.IGNORECASE,
)
NAME_POLICY = (
    "Names in MSR outputs: provider_legal_name is the ACECQA legal name, keyed by "
    "provider_approval_number, for providers not classed as individuals by ACECQA or the ABR. "
    "group_name is the ABR entity name of the reporting entity's ABN, shown only when the ABR "
    "entity type for that ABN is known locally, is a company, government entity, co-operative or "
    "other incorporated entity (never a trust, partnership or individual), the sources agree, and "
    "the name has no trust wording (family trust, trustee for, ATF); otherwise it is blank and "
    "group_name_status says why. No name is taken from the register itself."
)
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
    "group_abn",
    "group_abr_entity_type",
    "group_name",
    "group_name_status",
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
    "msr_entity_abn",
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
    "msr_entity_abn",
    "statement_key",
    "statement_id",
    "statement_url",
    "reporting_period",
    "reporting_entity_count",
    "reporting_entity_abns",
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
    "reporting_entity_abns",
    "msr_role",
    "msr_entity_abn",
    "reason",
    "candidate_provider_approval_numbers",
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
                "csv_lists_included": bool((row.get("IncludedEntities") or "").strip()),
                "csv_included_min": csv_included_lower_bound(row.get("IncludedEntities")),
            }
        )
    return out


def csv_included_lower_bound(text: str | None) -> int:
    """A lower bound on the entities a CSV IncludedEntities field lists.

    Names can contain commas ("X COLLEGE, SUBURB", "X Holdings, LLC"), so segments are not
    counted directly. A segment counts only when it ends an entity: it ends with an ABN in
    brackets or a corporate suffix.
    """
    return sum(1 for seg in (text or "").split(",") if _ENTITY_END.search(seg.strip()))


def select_candidates(statements: list[dict], provider_abns: set[str]) -> list[dict]:
    """Statements naming a provider ABN, or with a childcare term in the reporting entities.

    A matching row without a usable page id is kept (page_id None) so that main() can report
    the run as incomplete rather than drop it silently.
    """
    out = []
    for s in statements:
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


class PageParseError(ValueError):
    """A statement page whose entity markup is missing or not recognised."""


def _entities(section, label: str) -> list[dict]:
    """Entities in a section. Raises PageParseError when the markup is not recognised."""
    if section is None:
        return []
    for child in section.children:
        if isinstance(child, NavigableString):
            if child.strip() and not isinstance(child, Comment):
                raise PageParseError(f"{label} section holds text outside an entity element")
        elif not (child.name == "div" and "statement-entity" in (child.get("class") or [])):
            raise PageParseError(f"{label} section holds an unrecognised element <{child.name}>")
    divs = section.find_all("div", class_="statement-entity", recursive=False)
    if not divs:
        raise PageParseError(f"{label} section present but holds no recognised entity")
    out = []
    for div in divs:
        link = div.find("a", class_="statement-entity__name-link")
        name = " ".join(link.get_text(" ").split()) if link else ""
        if not name:
            raise PageParseError(f"{label} entity without a recognised name link")
        abn = None
        abn_link = div.find("a", href=re.compile(r"^/statements/\?abn="))
        if abn_link:
            digits = re.sub(r"\D", "", abn_link.get_text())
            abn = digits if len(digits) == 11 else None
        out.append({"name": name, "abn": abn})
    return out


def parse_statement_page(page_html: str) -> dict:
    """Reporting and included entities as {name, abn}. Included entities are de-duplicated.

    Raises PageParseError when the reporting-entity section is missing or empty, or when either
    section's markup is not recognised. A page with no included-entity section is a statement
    with no included entities; main() cross-checks that against the CSV. Names are used only for
    matching and are never written out.
    """
    soup = BeautifulSoup(page_html, "html.parser")
    reporting = _entities(soup.find(id="statement-reporting-entities"), "reporting")
    if not reporting:
        raise PageParseError("no reporting entity found")
    included: list[dict] = []
    seen: set[tuple[str, str | None]] = set()
    listed = _entities(soup.find(id="statement-included-entities"), "included")
    for ent in listed:
        key = (normalise(ent["name"]), ent["abn"])
        if key[0] and key not in seen:
            seen.add(key)
            included.append(ent)
    return {"reporting": reporting, "included": included, "included_raw_count": len(listed)}


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


class _Index:
    """Provider lookups for matching. Excludes providers fail closed.

    A provider is excluded when any local source marks it as an individual or sole trader: the
    ACECQA-derived profile (entity_form likely_individual or unknown, or a withheld name),
    provider-abn.csv (entity type IND or match_kind excluded_individual_abr) or abn-details.csv;
    or when the ABR sources disagree on its ABN's entity type.
    """

    def __init__(
        self, profiles: list[dict], abn_rows: list[dict], abr_types: dict[str, dict] | None = None
    ):
        abr_types = abr_types or {}
        self.legal: dict[str, str] = {}
        self.excluded: set[str] = set()
        self.by_name: dict[str, set[str]] = defaultdict(set)
        self.by_loose: dict[str, set[str]] = defaultdict(set)
        self.stats: Counter = Counter()
        likely_individual: set[str] = set()
        for p in profiles:
            pr = normalise_pr(p.get("provider_approval_number"))
            if not pr:
                continue
            legal = (p.get("legal_name") or "").strip()
            if _excluded(p):
                self.excluded.add(pr)
                self.stats["providers_excluded_profile"] += 1
                if (p.get("entity_form") or "").strip() == "likely_individual":
                    likely_individual.add(pr)
            else:
                self.legal[pr] = legal
            if normalise(legal):
                self.by_name[normalise(legal)].add(pr)
                self.by_loose[loose_key(legal)].add(pr)
        self.abn_of: dict[str, str] = {}
        self.abr_name: dict[str, str] = {}
        self.by_abn: dict[str, list[str]] = defaultdict(list)

        def exclude(pr: str, reason: str) -> None:
            if pr not in self.excluded:
                self.stats["individual_status_conflicts"] += reason == "abr_individual"
            self.excluded.add(pr)
            self.legal.pop(pr, None)
            self.stats[f"providers_excluded_{reason}"] += 1

        for r in abn_rows:
            pr = normalise_pr(r.get("provider_approval_number"))
            if not pr:
                continue
            kind = r.get("match_kind") or ""
            if kind == "excluded_individual_abr":
                exclude(pr, "abr_individual")
                continue
            abn = (r.get("abn") or "").strip()
            if not abn or kind not in ACCEPTED_KINDS:
                continue
            info = abr_types.get(abn) or {}
            row_code = (r.get("entity_type_code") or "").strip().upper()
            if (
                row_code in INDIVIDUAL_ABR_TYPES
                or info.get("entity_type_code") in INDIVIDUAL_ABR_TYPES
            ):
                exclude(pr, "abr_individual")
                continue
            if pr in self.excluded:
                # The profile says individual while the ABR says a non-individual type.
                self.stats["individual_status_conflicts"] += pr in likely_individual
                continue
            if info.get("conflict"):
                self.excluded.add(pr)
                self.legal.pop(pr, None)
                self.stats["abr_type_conflicts"] += 1
                continue
            self.abn_of[pr] = abn
            self.abr_name[pr] = (r.get("abr_entity_name") or "").strip()
            self.by_abn[abn].append(pr)
            self.legal.setdefault(pr, (r.get("legal_name") or "").strip())


def abr_types_from(abn_rows: list[dict], details_rows: list[dict] = ()) -> dict[str, dict]:
    """ABN -> {entity_type_code, entity_name, source, conflict} from ABR data held locally.

    provider-abn.csv gives the type and ABR entity name of accepted provider ABNs; abn-details.csv
    gives them for ABNs looked up in stage A. When the sources disagree on the type, the entry is
    a conflict: its code is IND if either source says individual, otherwise None. An individual
    never keeps a name.
    """
    seen: dict[str, list[tuple[str, str | None, str]]] = defaultdict(list)
    for r in details_rows:
        abn = (r.get("abn") or "").strip()
        code = (r.get("entity_type_code") or "").strip().upper()
        status = (r.get("lookup_status") or "").strip()
        if not abn:
            continue
        if status == "excluded_individual" or code in INDIVIDUAL_ABR_TYPES:
            seen[abn].append(("IND", None, "abn-details.csv"))
        elif status == "ok" and code:
            seen[abn].append(
                (code, (r.get("entity_name") or "").strip() or None, "abn-details.csv")
            )
    for r in abn_rows:
        abn = (r.get("abn") or "").strip()
        code = (r.get("entity_type_code") or "").strip().upper()
        if not abn or not code:
            continue
        if (r.get("match_kind") or "") not in ACCEPTED_KINDS and code not in INDIVIDUAL_ABR_TYPES:
            continue
        name = None if code in INDIVIDUAL_ABR_TYPES else (r.get("abr_entity_name") or "").strip()
        seen[abn].append((code, name or None, "provider-abn.csv"))
    out: dict[str, dict] = {}
    for abn, entries in seen.items():
        codes = {code for code, _, _ in entries}
        sources = "; ".join(sorted({src for _, _, src in entries}))
        if len(codes) > 1:
            code = "IND" if "IND" in codes else None
            out[abn] = {
                "entity_type_code": code,
                "entity_name": None,
                "source": sources,
                "conflict": True,
            }
            continue
        (code,) = codes
        name = None if code in INDIVIDUAL_ABR_TYPES else next((n for _, n, _ in entries if n), None)
        out[abn] = {
            "entity_type_code": code,
            "entity_name": name,
            "source": sources,
            "conflict": False,
        }
    return out


def group_name_fields(abn: str | None, abr_types: dict[str, dict]) -> dict:
    """group_abn, group_abr_entity_type, group_name and group_name_status for one ABN.

    Fails closed: the ABR entity name is shown only for an allowed organisation type, with
    agreeing sources and no wording that can embed a person's name.
    """
    if not abn:
        return {
            "group_abn": None,
            "group_abr_entity_type": None,
            "group_name": None,
            "group_name_status": NAME_NO_ABN,
        }
    info = abr_types.get(abn) or {}
    code = info.get("entity_type_code")
    name = info.get("entity_name")
    if code in INDIVIDUAL_ABR_TYPES:
        status = NAME_ABR_INDIVIDUAL
    elif info.get("conflict"):
        status = NAME_ABR_CONFLICT
    elif not code:
        status = NAME_ABR_UNKNOWN
    elif code not in ALLOWED_GROUP_ABR_TYPES:
        status = NAME_TYPE_NOT_ALLOWED
    elif not name:
        status = NAME_ABR_UNKNOWN
    elif _PERSON_WORDING.search(name):
        status = NAME_MAY_EMBED_PERSON
    else:
        status = NAME_SHOWN
    return {
        "group_abn": abn,
        "group_abr_entity_type": code,
        "group_name": name if status == NAME_SHOWN else None,
        "group_name_status": status,
    }


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
        "reporting_entity_abns": "; ".join(r["abn"] for r in reporting if r["abn"]),
        "included_entities_listed": len(statement["parsed"]["included"]),
        "captured_at": statement.get("captured_at"),
        "page_sha256": statement.get("page_sha256"),
    }


def _name_abns(statements: list[dict]) -> dict[str, set[str]]:
    """Normalised reporting-entity name -> ABNs given for it. Internal only, never written."""
    seen: dict[str, set[str]] = defaultdict(set)
    for s in statements:
        for rep in (s.get("parsed") or {}).get("reporting", []):
            if rep["abn"] and normalise(rep["name"]):
                seen[normalise(rep["name"])].add(rep["abn"])
    return seen


def _single_group(
    statement: dict, name_abns: dict[str, set[str]], abr_types: dict[str, dict]
) -> dict:
    """Group key and ABR-gated name of a statement with exactly one reporting entity.

    With no ABN on the statement, an ABN given for the same name on another statement is used
    only when the ABR confirms it: a known non-individual type whose ABR entity name normalises
    to the same name. Otherwise the key is the statement page id; it is never a name.
    """
    rep = statement["parsed"]["reporting"][0]
    abn, source = rep["abn"], "abn_on_statement"
    if not abn:
        abn, source = None, "statement_page_no_abn"
        key = normalise(rep["name"])
        found = name_abns.get(key, set())
        if len(found) == 1:
            (other,) = found
            info = abr_types.get(other) or {}
            code = info.get("entity_type_code")
            if (
                code
                and code not in INDIVIDUAL_ABR_TYPES
                and normalise(info.get("entity_name")) == key
            ):
                abn, source = other, "abn_of_same_name_on_another_statement_abr_confirmed"
    group_key = abn or f"MSR-{statement['page_id']}"
    return {"group_key": group_key, "group_key_source": source, **group_name_fields(abn, abr_types)}


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
    statements: list[dict],
    profiles: list[dict],
    abn_rows: list[dict],
    abr_types: dict[str, dict] | None = None,
) -> tuple[list[dict], list[dict], dict]:
    """Provider-statement relations, review queue and match statistics.

    A relation is one provider named in one statement, by its strongest match. A relation is not
    an edge: classify_relation decides what each one means.
    """
    abr_types = abr_types if abr_types is not None else abr_types_from(abn_rows)
    idx = _Index(profiles, abn_rows, abr_types)
    relations: dict[tuple[str, str], dict] = {}
    review: list[dict] = []
    stats = Counter(idx.stats)

    def add_relation(s: dict, pr: str, role: str, method: str, abn: str | None) -> None:
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
            "msr_entity_abn": abn,
        }

    def add_review(s: dict, role: str, abn: str | None, reason: str, prs) -> None:
        facts = _statement_facts(s)
        review.append(
            {
                **{k: facts[k] for k in facts if k in REVIEW_COLUMNS},
                "msr_role": role,
                "msr_entity_abn": abn,
                "reason": reason,
                "candidate_provider_approval_numbers": "; ".join(sorted(prs)),
            }
        )

    def match_entity(s: dict, role: str, name: str, abn: str | None) -> None:
        matched = idx.by_abn.get(abn or "", [])
        for pr in matched:
            add_relation(s, pr, role, f"{role}_abn_equals_provider_abn", abn)
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
                add_review(s, role, abn, "ambiguous_matches_several_providers", visible)
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
                add_relation(s, pr, role, "included_name_equals_acecqa_and_abr_name", abn)
                return
            else:
                reason = "abr_name_disagrees"
            add_review(s, role, abn, reason, visible)
            return
        loose = idx.by_loose.get(loose_key(name), set())
        if loose & idx.excluded:
            stats["matches_to_excluded_providers"] += 1
        if loose - idx.excluded:
            add_review(s, role, abn, "fuzzy_corporate_suffix_differs", loose - idx.excluded)

    name_abns = _name_abns(statements)
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
            _single_group(s, name_abns, abr_types)
            if single
            else {"group_key": None, "group_key_source": None, **group_name_fields(None, {})}
        )
        for (_, page), rel in relations.items():
            if page == s["page_id"]:
                rel.update(group)
                rel["relation"] = classify_relation(rel)

    out = sorted(
        relations.values(),
        key=lambda r: (r["provider_approval_number"], r["period_end"], r["statement_id"]),
    )
    review.sort(
        key=lambda r: (
            r["statement_id"],
            r["msr_role"],
            r["reason"],
            r["msr_entity_abn"] or "",
            r["candidate_provider_approval_numbers"],
        )
    )
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


def build_layer(
    statements: list[dict],
    profiles: list[dict],
    abn_rows: list[dict],
    abr_types: dict[str, dict] | None = None,
) -> dict:
    """Edges (controlled_entity_of only), group heads, joint co-reporting rows and review queue."""
    relations, review, stats = match_relations(statements, profiles, abn_rows, abr_types)
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


def _services(services: list[dict] | None, prs: set[str]) -> int | None:
    """Services held by the providers, or None when the services table is unavailable."""
    if services is None:
        return None
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
                "reporting_entity_abns": first["reporting_entity_abns"],
                "included_providers": sorted({r["provider_approval_number"] for r in rows}),
            }
        )
    return out


def summarise(
    layer: dict, abn_rows: list[dict], services: list[dict] | None, *, candidates_count: int
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
    non_joint_prs = {r["provider_approval_number"] for r in relations if r["relation"] != JOINT}
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
                "group_abn": latest["group_abn"],
                "group_abr_entity_type": latest["group_abr_entity_type"],
                "group_name": latest["group_name"],
                "group_name_status": latest["group_name_status"],
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
                "providers_with_only_joint_relations": len(joint_prs - non_joint_prs),
            },
            "group_names": {
                "edge_groups_by_status": dict(
                    sorted(Counter(g["group_name_status"] for g in groups).items())
                ),
                "head_rows_by_status": dict(
                    sorted(Counter(h["group_name_status"] for h in heads).items())
                ),
            },
            "priority_providers_total": len(priority),
            "priority_providers_with_abn": len(priority_with_abn),
            "services_total": None if services is None else len(services),
            "services_note": None if services is not None else SERVICES_MISSING_NOTE,
            "review_queue": len(review),
            "review_by_reason": dict(sorted(Counter(r["reason"] for r in review).items())),
            "matches_to_excluded_providers": stats.get("matches_to_excluded_providers", 0),
            "provider_exclusions": {
                "profile_individual_unknown_or_withheld": stats.get(
                    "providers_excluded_profile", 0
                ),
                "abr_individual": stats.get("providers_excluded_abr_individual", 0),
                "abr_type_conflicts": stats.get("abr_type_conflicts", 0),
                "individual_status_conflicts": stats.get("individual_status_conflicts", 0),
                "rule": "A provider is excluded when any local source (ACECQA profile "
                "classification or withheld flag, provider-abn.csv, abn-details.csv) marks it as "
                "an individual or sole trader, or when the ABR sources disagree on its type.",
            },
        },
        "window": {
            "edge_reporting_periods_earliest": periods[0] if periods else None,
            "edge_reporting_periods_latest": periods[-1] if periods else None,
        },
        "groups": groups,
        "joint_statements_for_manual_confirmation": joint_manual_candidates(coreported),
        "name_policy": NAME_POLICY,
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


def acquire_csv(no_fetch: bool) -> tuple[Path, dict] | None:
    """Newest privacy-filtered all-statements CSV snapshot, fetching a new one unless no_fetch.

    Returns None when no snapshot exists.
    """
    if not no_fetch:
        page = fetch(RESOURCES_URL)
        write_snapshot(SOURCE_RESOURCES, page, "html")
        url = find_all_statements_link(page.text)
        if not url:
            log.error("no all-statements CSV link on the MSR resources page")
        else:
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
        return None
    return snaps[-1], _meta(snaps[-1])


def acquire_page(
    statement: dict, no_fetch: bool, last: list[float], *, refresh: bool = False
) -> tuple[Path | None, dict]:
    """Newest snapshot of a statement page.

    A page is fetched when no local copy exists, or always with refresh. A fetch writes a new
    timestamped snapshot beside the old ones; raw files are never overwritten.
    """
    source = f"{SOURCE_PAGES}/{statement['page_id']}"
    snaps = list_snapshots(source)
    if (refresh or not snaps) and not no_fetch:
        wait = PAGE_DELAY_SECONDS - (time.monotonic() - last[0])
        if wait > 0:
            time.sleep(wait)
        try:
            got = fetch(statement["statement_url"])
        except Exception as exc:  # robots refusal or HTTP error: the page counts as missing
            log.error("statement page %s not fetched: %s", statement["statement_url"], exc)
            last[0] = time.monotonic()
            return None, {}  # never fall back to an older snapshot when a fetch was required
        last[0] = time.monotonic()
        written = write_snapshot(source, got, "html")
        return written, _meta(written)
    if not snaps:
        return None, {}
    return snaps[-1], _meta(snaps[-1])


def _parse_page(path: Path, statement: dict) -> dict | None:
    """Parsed page, or None when it is unreadable, unrecognised or incomplete.

    Incomplete means the CSV says the statement lists included entities but none were parsed.
    """
    try:
        parsed = parse_statement_page(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        log.error("statement page %s not usable: %s", path.as_posix(), exc)
        return None
    if statement.get("csv_lists_included") and not parsed["included"]:
        log.error(
            "statement page %s: the CSV lists included entities but none were parsed",
            path.as_posix(),
        )
        return None
    if parsed["included_raw_count"] < statement.get("csv_included_min", 0):
        log.error(
            "statement page %s: the CSV lists at least %d included entities, the page yields %d",
            path.as_posix(),
            statement["csv_included_min"],
            parsed["included_raw_count"],
        )
        return None
    return parsed


def main(argv: list[str] | None = None) -> int:
    """Exit codes as in the module docstring: 0 complete, 2 incomplete, 1 nothing usable."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--no-fetch", action="store_true", help="use local snapshots only")
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="fetch every candidate page again, as a new snapshot beside the old ones",
    )
    args = parser.parse_args(argv)

    got_csv = acquire_csv(args.no_fetch)
    if got_csv is None:
        log.error("no MSR CSV snapshot in data/raw/msr/all-statements/: nothing to build")
        return 1
    csv_path, csv_meta = got_csv
    statements = parse_statements_csv(csv_path.read_text(encoding="utf-8-sig"))
    abn_rows = _load_csv(PROVIDER_ABN_CSV)
    provider_abns = {r["abn"] for r in abn_rows if r.get("abn")}
    candidates = select_candidates(statements, provider_abns)
    log.info("%d statements, %d candidates", len(statements), len(candidates))
    if not candidates:
        log.error("no candidate statements: nothing to build")
        return 1

    last = [0.0]
    page_paths: list[Path] = []
    missing: list[str] = []
    unparseable: list[str] = []
    for s in candidates:
        if not s["page_id"]:
            missing.append(f"{s['statement_id']} (no usable page id in {s['statement_url']!r})")
            continue
        path, meta = acquire_page(s, args.no_fetch, last, refresh=args.refresh)
        if path is None:
            missing.append(f"{s['statement_id']} ({s['statement_url']})")
            continue
        parsed = _parse_page(path, s)
        if parsed is None:
            unparseable.append(f"{s['statement_id']} ({path.as_posix()})")
            continue
        page_paths.append(path)
        s["parsed"] = parsed
        s["captured_at"] = meta.get("fetched_at")
        s["page_sha256"] = meta.get("sha256")

    if not page_paths and not (args.refresh and missing):
        log.error("no candidate statement page could be read: nothing to build")
        return 1
    if missing or unparseable:
        # A partial run must not replace the last good outputs (as in parse_nsw_enforcement.py).
        log.error(
            "run incomplete; data/processed/%s* left unchanged. Missing pages (%d): %s. "
            "Unparseable pages (%d): %s",
            EDGES_NAME,
            len(missing),
            "; ".join(missing) or "none",
            len(unparseable),
            "; ".join(unparseable) or "none",
        )
        return 2

    profiles = _load_csv(PROFILE_CSV)
    details = _load_csv(ABN_DETAILS_CSV) if ABN_DETAILS_CSV.exists() else []
    abr_types = abr_types_from(abn_rows, details)
    layer = build_layer(candidates, profiles, abn_rows, abr_types)
    services = _load_csv(SERVICES_CSV) if SERVICES_CSV.exists() else None
    if services is None:
        log.warning("%s missing: service counts are null (unknown)", SERVICES_CSV.name)

    raw_inputs = [csv_path, *page_paths, PROVIDER_ABN_CSV, PROFILE_CSV] + [
        path for path in (ABN_DETAILS_CSV, SERVICES_CSV) if path.exists()
    ]
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
        "(group_key_source says where it came from) or MSR-<statement page id> when no ABN is "
        "known. No key is derived from a name. " + NAME_POLICY + local_only,
    )
    write_processed(
        HEADS_NAME,
        layer["heads"],
        HEAD_COLUMNS,
        raw_inputs=raw_inputs,
        notes=HEAD_DEFINITION + " " + NAME_POLICY + local_only,
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
        "reporting entities matched by name only. Not evidence of ownership. Rows carry "
        "statement ids, URLs, ABNs and candidate provider approval numbers; no names." + local_only,
    )
    summary = summarise(layer, abn_rows, services, candidates_count=len(candidates))
    summary["counts"]["candidate_pages_missing"] = 0
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
            "reporting_entity_count": len(s["parsed"]["reporting"]),
            "reporting_entity_abns": [r["abn"] for r in s["parsed"]["reporting"] if r["abn"]],
            "included_entities": len(s["parsed"]["included"]),
        }
        for s in candidates
    ]
    summary["inputs"] = [
        f"data/processed/{p.name}"
        for p in (PROVIDER_ABN_CSV, ABN_DETAILS_CSV, PROFILE_CSV, SERVICES_CSV)
    ] + ["data/raw/msr/ (local only)"]
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    log.info("summary: %s", json.dumps(summary["counts"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
