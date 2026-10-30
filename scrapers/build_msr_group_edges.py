"""Ownership layer 1: provider-to-group edges from the Modern Slavery Statements Register (MSR).

An edge means: the provider's legal entity is named in a modern slavery statement either as a
reporting entity (matched by ABN) or as an entity included in the statement (matched by name, with
the ACECQA legal name and the ABR entity name both agreeing). Under the Modern Slavery Act 2018 a
reporting entity's statement covers the entities it owns or controls, so an included-entity edge
reads "included in the group's modern slavery statement as owned or controlled". The MSR covers
only entities with consolidated revenue of at least AUD 100 million, plus voluntary reporters.

Steps:
1. Read the MSR resources page, find the all-statements CSV, download it. Columns that could hold
   an individual's name (signatories, approvers, contacts) are dropped before anything is stored.
2. Candidate statements: any reporting-entity ABN equals a provider ABN in provider-abn.csv, or the
   reporting entities' text contains a childcare term.
3. Fetch each candidate's statement page (at least 2 s apart, robots.txt honoured) and parse the
   reporting entities (name, ABN) and the included entities (name only).
4. Edges: reporting_entity when a reporting-entity ABN equals a provider ABN; included_entity when
   an included entity's normalised name equals exactly one ACECQA provider legal name AND that
   provider has an ABN whose ABR entity name normalises to the same key. Everything else that
   looks like a match (ambiguous, ABR disagreement, provider without an ABN, corporate-suffix
   differences, reporting entities named without an ABN) goes to the review queue, never to edges.

Licence: the MSR shows "Copyright Attorney-General's Department" and no open licence. Raw MSR files
and their sidecars stay in data/raw/msr/, which is gitignored. Only derived facts are written to
data/processed/. Providers that are, or may be, individuals never appear in any output.

Writes data/processed/provider-group-edges-msr.csv, provider-group-review-msr.csv (each with a
provenance JSON) and provider-group-edges-msr-summary.json.

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

EDGE_COLUMNS = [
    "provider_approval_number",
    "provider_legal_name",
    "provider_abn",
    "group_key",
    "group_name",
    "statement_id",
    "statement_page_id",
    "statement_url",
    "statement_type",
    "reporting_period",
    "edge_type",
    "match_method",
    "msr_entity_name",
    "captured_at",
    "page_sha256",
]
REVIEW_COLUMNS = [
    "statement_id",
    "statement_page_id",
    "statement_url",
    "reporting_period",
    "group_key",
    "group_name",
    "msr_role",
    "msr_entity_name",
    "msr_entity_abn",
    "reason",
    "candidate_provider_approval_numbers",
    "candidate_provider_legal_names",
    "captured_at",
]

EDGE_DEFINITION = (
    "An edge means the provider's legal entity is named in a modern slavery statement on the "
    "Modern Slavery Statements Register: as a reporting entity (edge_type reporting_entity, matched "
    "by ABN) or as an entity included in the statement as owned or controlled by the reporting "
    "entity (edge_type included_entity, matched by exact normalised name agreeing with both the "
    "ACECQA legal name and the ABR entity name). It is not a verified ownership chain."
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
    """Reporting entities (name, ABN) and included entities (names, de-duplicated)."""
    soup = BeautifulSoup(page_html, "html.parser")
    reporting = _entities(soup.find(id="statement-reporting-entities"))
    included: list[str] = []
    seen: set[str] = set()
    for ent in _entities(soup.find(id="statement-included-entities")):
        key = normalise(ent["name"])
        if key and key not in seen:
            seen.add(key)
            included.append(ent["name"])
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
    """An MSR entity name, or WITHHELD when it is, or may be, an individual's name."""
    if not name:
        return None
    return WITHHELD if classify_entity_form(name) in EXCLUDED_FORMS else name


def _group(statement: dict) -> tuple[str, str]:
    reporting = statement["parsed"]["reporting"]
    if len(reporting) == 1 and reporting[0]["abn"]:
        key = reporting[0]["abn"]
    else:
        key = f"MSR-{statement['page_id']}"
    names = [_shown_name(r["name"]) or "" for r in reporting]
    return key, "; ".join(n for n in names if n)


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


def build_edges(
    statements: list[dict], profiles: list[dict], abn_rows: list[dict]
) -> tuple[list[dict], list[dict], dict]:
    """Edges, review queue and match statistics from parsed candidate statements."""
    idx = _Index(profiles, abn_rows)
    edges: dict[tuple[str, str], dict] = {}
    review: list[dict] = []
    stats = Counter()

    def base(s: dict) -> dict:
        key, name = _group(s)
        return {
            "group_key": key,
            "group_name": name,
            "statement_id": s["statement_id"],
            "statement_page_id": s["page_id"],
            "statement_url": s["statement_url"],
            "statement_type": s.get("type"),
            "reporting_period": s.get("reporting_period"),
            "captured_at": s.get("captured_at"),
            "page_sha256": s.get("page_sha256"),
        }

    def add_edge(s: dict, pr: str, edge_type: str, method: str, msr_name: str) -> None:
        k = (pr, s["page_id"])
        if k in edges and edges[k]["edge_type"] == "reporting_entity":
            return
        edges[k] = {
            **base(s),
            "provider_approval_number": pr,
            "provider_legal_name": idx.legal.get(pr),
            "provider_abn": idx.abn_of.get(pr),
            "edge_type": edge_type,
            "match_method": method,
            "msr_entity_name": msr_name,
        }

    def add_review(s: dict, role: str, name: str, abn: str | None, reason: str, prs) -> None:
        prs = sorted(prs)
        shown = _shown_name(name)
        names = "" if shown == WITHHELD else "; ".join(idx.legal.get(p, "") for p in prs)
        b = base(s)
        review.append(
            {
                **{k: b[k] for k in b if k in REVIEW_COLUMNS},
                "msr_role": role,
                "msr_entity_name": shown,
                "msr_entity_abn": abn,
                "reason": reason,
                "candidate_provider_approval_numbers": "; ".join(prs),
                "candidate_provider_legal_names": names,
            }
        )

    def match_name(s: dict, role: str, name: str, abn: str | None) -> None:
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
            if role == "reporting_entity":
                add_review(s, role, name, abn, "reporting_entity_name_only", visible)
            elif pr not in idx.abn_of:
                add_review(s, role, name, abn, "name_unique_provider_without_abn", visible)
            elif normalise(idx.abr_name.get(pr)) == key:
                add_edge(s, pr, "included_entity", "included_name_equals_acecqa_and_abr_name", name)
            else:
                add_review(s, role, name, abn, "abr_name_disagrees", visible)
            return
        loose = idx.by_loose.get(loose_key(name), set())
        if loose & idx.excluded:
            stats["matches_to_excluded_providers"] += 1
        if loose - idx.excluded:
            add_review(s, role, name, abn, "fuzzy_corporate_suffix_differs", loose - idx.excluded)

    for s in statements:
        parsed = s.get("parsed") or {"reporting": [], "included": []}
        for rep in parsed["reporting"]:
            matched = idx.by_abn.get(rep["abn"] or "", [])
            for pr in matched:
                add_edge(
                    s,
                    pr,
                    "reporting_entity",
                    "reporting_entity_abn_equals_provider_abn",
                    rep["name"],
                )
            if not matched:
                match_name(s, "reporting_entity", rep["name"], rep["abn"])
        stats["included_entities_parsed"] += len(parsed["included"])
        for name in parsed["included"]:
            match_name(s, "included_entity", name, None)

    out = sorted(
        edges.values(),
        key=lambda e: (
            e["provider_approval_number"],
            e["reporting_period"] or "",
            e["statement_id"],
        ),
    )
    review.sort(key=lambda r: (r["statement_id"], r["msr_role"], r["msr_entity_name"] or ""))
    stats.setdefault("matches_to_excluded_providers", 0)
    return out, review, dict(stats)


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def summarise(
    edges: list[dict],
    review: list[dict],
    stats: dict,
    abn_rows: list[dict],
    services: list[dict],
    *,
    candidates_count: int,
) -> dict:
    prs = {e["provider_approval_number"] for e in edges}
    priority = {normalise_pr(r.get("provider_approval_number")) for r in abn_rows} - {None}
    priority_with_abn = {
        normalise_pr(r.get("provider_approval_number")) for r in abn_rows if r.get("abn")
    } - {None}
    services_covered = sum(
        1 for s in services if normalise_pr(s.get("provider_approval_number")) in prs
    )
    by_type = Counter(e["edge_type"] for e in edges)
    periods = sorted(e["reporting_period"] for e in edges if e.get("reporting_period"))
    providers_by_type = {
        t: len({e["provider_approval_number"] for e in edges if e["edge_type"] == t})
        for t in ("reporting_entity", "included_entity")
    }
    groups = defaultdict(set)
    for e in edges:
        groups[(e["group_key"], e["group_name"])].add(e["provider_approval_number"])
    return {
        "generated_at": utc_now().isoformat(),
        "definition": EDGE_DEFINITION,
        "counts": {
            "candidate_statements": candidates_count,
            "included_entities_parsed": stats.get("included_entities_parsed", 0),
            "edges_reporting_entity": by_type.get("reporting_entity", 0),
            "edges_included_entity": by_type.get("included_entity", 0),
            "distinct_providers_with_edge": len(prs),
            "distinct_providers_by_edge_type": providers_by_type,
            "priority_providers_total": len(priority),
            "priority_providers_with_abn": len(priority_with_abn),
            "priority_providers_gained_edge": len(prs & priority),
            "services_covered": services_covered,
            "services_total": len(services),
            "review_queue": len(review),
            "review_by_reason": dict(sorted(Counter(r["reason"] for r in review).items())),
            "matches_to_excluded_providers": stats.get("matches_to_excluded_providers", 0),
        },
        "window": {
            "reporting_periods_earliest": periods[0] if periods else None,
            "reporting_periods_latest": periods[-1] if periods else None,
        },
        "groups": [
            {"group_key": k, "group_name": n, "providers": len(v)}
            for (k, n), v in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))
        ],
        "caveats": [
            EDGE_DEFINITION,
            "The register covers entities with annual consolidated revenue of at least AUD 100 "
            "million, plus voluntary reporters. Absence of an edge says nothing about ownership.",
            "Included entities are listed by name only. An included_entity edge needs the MSR name "
            "to equal, after normalisation, exactly one ACECQA provider legal name and that "
            "provider's ABR entity name. It is not verified by ABN or ACN.",
            "Edges span every reporting period on the register. A provider included in an older "
            "statement may since have changed hands; check reporting_period.",
            "MSR licence unclear (Copyright Attorney-General's Department). Raw MSR files are not "
            "committed. Ask the department before any public display.",
            "services_covered counts current ACECQA service approvals held by providers with an "
            "edge, from acecqa-services-latest.csv. ACECQA content is not openly licensed.",
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
    edges, review, stats = build_edges(parsed, profiles, abn_rows)
    services = _load_csv(SERVICES_CSV) if SERVICES_CSV.exists() else []
    if not services:
        log.warning("no %s: services_covered will be 0", SERVICES_CSV.name)

    raw_inputs = [csv_path, *page_paths, PROVIDER_ABN_CSV, PROFILE_CSV]
    write_processed(
        EDGES_NAME,
        edges,
        EDGE_COLUMNS,
        raw_inputs=raw_inputs,
        notes=EDGE_DEFINITION
        + " Raw MSR inputs listed here are a local cache only (data/raw/msr/ is gitignored: "
        "licence unclear). group_key is the single reporting entity's ABN, or MSR-<page id> for "
        "joint statements or reporting entities without an ABN.",
    )
    write_processed(
        REVIEW_NAME,
        review,
        REVIEW_COLUMNS,
        raw_inputs=raw_inputs,
        notes="Possible links that did not meet the edge rule: ambiguous names, ABR name "
        "disagreement, providers without an ABN, corporate-suffix differences and reporting "
        "entities matched by name only. Not evidence of ownership. MSR names that may be an "
        f"individual's are shown as '{WITHHELD}'.",
    )
    summary = summarise(edges, review, stats, abn_rows, services, candidates_count=len(candidates))
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
