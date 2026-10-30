"""Ownership layer 1: provider-to-group edges from the Modern Slavery Statements Register (MSR).

Every screened provider found in a candidate statement by ABN is a relation, classified into
exactly one of:
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

Matching is by ABN only. A relation exists only when an entity's ABN on the statement page,
parsed and valid (11 digits passing the ABN checksum), equals the ABN of a screened provider.
A name never makes a relation: an entity whose name matches a provider without a matching ABN
goes to the review queue, which carries ids and ABNs only.

Screening (fail closed, every exclusion counted): a provider is used only when it has exactly one
row in provider-profile.csv, that row is positively classified as an organisation (entity_form
company, incorporated_association, trust_or_trustee, cooperative, government or
church_or_religious), the name is not withheld and not blank, it has at most one row in
provider-abn.csv, and no local ABR source (provider-abn.csv, abn-details.csv) marks it as an
individual or disagrees on its ABN's entity type. The ABN index holds screened providers only,
with an accepted, checksum-valid ABN.

Steps:
1. Read the MSR resources page, find the all-statements CSV, download it. Columns that could hold
   an individual's name (signatories, approvers, contacts) are dropped before anything is stored.
2. Candidate statements: any ABN listed on the statement (the CSV ABN column holds reporting and
   included entities' ABNs) equals a screened provider's ABN, or the reporting entities' text
   contains a childcare term.
3. Fetch each candidate's statement page (at least 2 s apart, robots.txt honoured) and parse the
   reporting and included entity sections against a strict schema: anything not recognised, at
   any depth, makes the page unparseable.
4. Edges and group heads are collapsed to one row per provider and group from the latest
   statement, listing every statement id and URL. A group is identified by the reporting
   entity's ABN on that statement, else by MSR-<statement page id>. No group name is written.

Licence: the MSR shows "Copyright Attorney-General's Department" and no open licence. Raw MSR files
and their sidecars stay in data/raw/msr/, which is gitignored. Only derived facts are written to
data/processed/.

Name policy: the only name in any output is provider_legal_name, the ACECQA legal name of a
screened provider. No name read from the register is ever written.

Writes data/processed/provider-group-edges-msr.csv (controlled_entity_of only),
provider-group-heads-msr.csv, provider-coreported-msr.csv and provider-group-review-msr.csv, each
with a provenance JSON, plus provider-group-edges-msr-summary.json.

Run:
  python3 scrapers/build_msr_group_edges.py              fetch the CSV and candidate pages
  python3 scrapers/build_msr_group_edges.py --no-fetch   rebuild from the newest local snapshots
  python3 scrapers/build_msr_group_edges.py --refresh    take a new snapshot of every candidate page

Exit codes: 0 complete. 2 incomplete or inconsistent, outputs left unchanged: the CSV lacks a
required column, duplicate
provider_approval_number rows in provider-profile.csv or provider-abn.csv, a candidate without a
page id, a candidate page missing, a fetch failed (always 2 with --refresh), a page that does not
match the schema (including an ABN link whose text is not a valid ABN), or a page whose
reporting or included entities do not reconcile with its CSV row by ABN and name. 1 nothing usable: no CSV snapshot, no candidate, or no
page readable.
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

from bs4 import BeautifulSoup, NavigableString, Tag

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
# An ABN in brackets in the CSV IncludedEntities field, as the register writes it.
_CSV_BRACKET_ABN = re.compile(r"\(\s*((?:\d\s?){11})\)")
_CSV_TRAILING_ABN = re.compile(r"\s*\(\s*((?:\d\s?){11})\)\s*$")
# Most candidate entries the grouping search may try for one entity field before it gives up and
# marks the page unparseable. On the 2026-10-30 snapshots the most any field needed was under
# 100 (272 fields, the largest 79 comma pieces), so this leaves about 1,000 times headroom.
MAX_GROUPING_STEPS = 100_000
# Columns the candidate selection and the page reconciliation read. A missing or renamed column
# stops the run; no column is ever defaulted to empty.
REQUIRED_CSV_COLUMNS = (
    "IDX",
    "PeriodStart",
    "PeriodEnd",
    "Type",
    "ReportingEntities",
    "IncludedEntities",
    "ABN",
    "Link",
)
_ABN_TEXT = re.compile(r"\d{2} ?\d{3} ?\d{3} ?\d{3}")
# The register shows some entities without an ABN as "ABN: 00 NNN NNN NNN" (00 then a 9-digit
# number; seen once, where the number is the entity's ARBN). The checksum runs first: a value
# that passes it is an ABN, 00 prefix or not. Only a value of this form that fails the checksum
# is read as "no ABN", and every one is listed in the summary. Any other ABN text that is not a
# valid ABN is an error.
_ABN_PLACEHOLDER = re.compile(r"00 ?\d{3} ?\d{3} ?\d{3}")
_ABN_WEIGHTS = (10, 1, 3, 5, 7, 9, 11, 13, 15, 17, 19)
# Identifier paragraphs in an entity block: label -> href pattern of its link.
_ID_HREF = {
    "ABN": re.compile(r"/statements/\?abn=(\d+)"),
    "ACN": re.compile(r"/statements/\?acn=(\d+)"),
    "ARBN": re.compile(r"/statements/\?arbn=(\d+)"),
}
NON_PROFIT_TEXT = "Non-profit organisation"

ORGANISATION_FORMS = {
    "company",
    "incorporated_association",
    "trust_or_trustee",
    "cooperative",
    "government",
    "church_or_religious",
}
ACCEPTED_KINDS = {"accepted_unique", "accepted_unique_in_state"}
# provider-abn.csv match kinds that mark a provider as, or possibly as, an individual.
INDIVIDUAL_KINDS = {"excluded_individual_abr", "excluded_individual_or_unknown"}
# ABR entity type codes that mean an individual or sole trader.
INDIVIDUAL_ABR_TYPES = {"IND"}
# Screening exclusions, checked in this order; each excluded provider is counted once, under the
# first reason that applies.
SCREEN_REASONS = [
    "excluded_missing_profile",
    "excluded_duplicate_profile_rows",
    "excluded_duplicate_provider_abn_rows",
    "excluded_not_positively_organisation",
    "excluded_name_withheld",
    "excluded_blank_legal_name",
    "excluded_abn_step_individual_or_unknown",
    "excluded_abr_individual",
    "excluded_abr_type_conflict",
]
NAME_POLICY = (
    "Names in MSR outputs: the only name is provider_legal_name, the ACECQA legal name keyed by "
    "provider_approval_number, for providers that pass screening. No group name is written; a "
    "group is identified by the reporting entity's ABN or by its statement page. No name read "
    "from the register is ever written."
)
# One relation per provider and statement: the reporting role wins over the included role.
_RANK = {
    "reporting_entity_abn_equals_provider_abn": 0,
    "included_entity_abn_equals_provider_abn": 1,
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
    "only by the included entity's ABN on the statement page equalling the provider's ABN. It is "
    "not a verified ownership chain, shareholding or date of acquisition. This is the only "
    "ownership edge in this layer."
)
HEAD_DEFINITION = (
    "group_parent_self: the provider, matched by ABN, is itself the one reporting entity of a "
    "Single statement that lists included entities. It marks the provider as a group head; it is "
    "not an edge to another provider."
)
JOINT_DEFINITION = (
    "co_reported_joint: the provider is named by ABN (as a reporting or included entity) in a "
    "Joint statement. Joint statements can combine unrelated bodies, so these rows are never "
    "edges."
)
REVIEW_REASONS = (
    "name_match_without_msr_abn: the entity's name equals one screened provider's legal name but "
    "the statement gives no ABN for it. msr_abn_differs_from_provider_abn: the name matches but "
    "the statement's ABN differs from the provider's. name_match_provider_abn_not_resolved: the "
    "name matches and the statement gives an ABN, but the provider has no accepted ABN. "
    "ambiguous_matches_several_providers: the name equals several providers' legal names. "
    "fuzzy_corporate_suffix_differs: the names match only without a PTY LTD, LTD or INC suffix."
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


class CsvSchemaError(ValueError):
    """The all-statements CSV lacks a required column, or a row does not match the header."""


def _rows_matching_header(text: str) -> tuple[list[str], list[list[str]]]:
    """Header (BOM stripped) and rows. Raises CsvSchemaError when any row's field count
    differs from the header's. Nothing is padded or cut."""
    rows = list(csv.reader(io.StringIO(text.lstrip("\ufeff"))))
    if not rows:
        raise CsvSchemaError("all-statements CSV is empty")
    header = [h.lstrip("\ufeff") for h in rows[0]]
    for n, row in enumerate(rows[1:], start=2):
        if len(row) != len(header):
            raise CsvSchemaError(
                f"all-statements CSV record {n} has {len(row)} fields, the header {len(header)}"
            )
    return header, rows[1:]


def privacy_filter_csv(text: str) -> tuple[str, list[str], list[str]]:
    """Drop columns that could hold an individual's name. Returns (text, kept, dropped).

    Every row's length is checked against the header first (CsvSchemaError otherwise); no row is
    ever padded. The text is returned unchanged when nothing is dropped, so its hash equals the
    source's.
    """
    header, rows = _rows_matching_header(text)
    dropped = [h for h in header if _PERSON_COLUMN.search(h)]
    kept = [h for h in header if h not in dropped]
    if not dropped:
        return text, kept, dropped
    keep_idx = [i for i, h in enumerate(header) if h in kept]
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(kept)
    for row in rows:
        writer.writerow([row[i] for i in keep_idx])
    return buf.getvalue(), kept, dropped


# ---------------------------------------------------------------------------
# ABN checksum, CSV parsing and candidates
# ---------------------------------------------------------------------------


def valid_abn(value: str | None) -> bool:
    """True for 11 digits that pass the ABN checksum (first digit less 1, weighted, mod 89)."""
    if not isinstance(value, str) or not re.fullmatch(r"\d{11}", value):
        return False
    digits = [int(c) for c in value]
    digits[0] -= 1
    return sum(d * w for d, w in zip(digits, _ABN_WEIGHTS, strict=True)) % 89 == 0


def _abns(value: str | None) -> list[str]:
    out = []
    for part in (value or "").split(","):
        digits = re.sub(r"\D", "", part)
        if len(digits) == 11:
            out.append(digits)
    return out


def parse_statements_csv(text: str) -> list[dict]:
    """One dict per statement row. page_id comes from the statement URL (IDX is not unique).

    Raises CsvSchemaError when a column in REQUIRED_CSV_COLUMNS is missing (or renamed), or any
    row is shorter or longer than the header, whichever column it lacks. The ReportingEntities
    and IncludedEntities text is kept for the page reconciliation (reconcile_entities); it is
    never written out.
    """
    header, records = _rows_matching_header(text)
    missing = [c for c in REQUIRED_CSV_COLUMNS if c not in header]
    if missing:
        raise CsvSchemaError(
            "all-statements CSV lacks required column(s) "
            + ", ".join(missing)
            + f"; header has {len(header)} columns"
        )
    out = []
    for values in records:
        row = dict(zip(header, values, strict=True))
        link = row["Link"].strip()
        m = _PAGE_ID.search(link)
        start, end = row["PeriodStart"].strip(), row["PeriodEnd"].strip()
        included = row["IncludedEntities"]
        out.append(
            {
                "statement_id": row["IDX"].strip(),
                "page_id": m.group(1) if m else None,
                "statement_url": link or None,
                "type": row["Type"].strip(),
                "period_start": start or None,
                "period_end": end or None,
                "reporting_period": f"{start} to {end}" if start and end else None,
                "reporting_entities_text": row["ReportingEntities"].strip(),
                "included_entities_text": included.strip(),
                "abns": _abns(row["ABN"]),
                "csv_lists_included": bool(included.strip()),
                "csv_included_abn_count": len(_CSV_BRACKET_ABN.findall(included)),
            }
        )
    return out


def _fold(text: str | None) -> str:
    """Whitespace collapsed and case folded, for comparing page names with CSV text."""
    return " ".join((text or "").split()).casefold()


def _entry_pair(text: str) -> tuple[str, str | None]:
    """(folded name, ABN digits or None) of one CSV entry; a trailing bracketed ABN is its ABN."""
    m = _CSV_TRAILING_ABN.search(text)
    if not m:
        return _fold(text), None
    return _fold(text[: m.start()]), re.sub(r"\D", "", m.group(1))


def reconcile_entities(csv_field: str, entities: list[dict]) -> dict[str, int]:
    """Problems reconciling a CSV entities field with the page's entities, as counts only.

    The page gives a multiset of (folded name, ABN or placeholder or None) pairs, duplicates
    counted. The CSV field is split on commas into pieces, and the pieces are grouped into
    entries (a name can contain commas); an entry's trailing bracketed ABN is its ABN. A comma
    directly after a bracketed ABN always separates entries. The field reconciles only when
    exactly one grouping gives the page's multiset:
    - no_grouping_matches_page: no grouping does (abn_multiset_differs is added, with the size
      of the difference, when even the bracketed ABNs disagree);
    - several_groupings_match_page: more than one does, so the split is ambiguous;
    - grouping_search_limit_exceeded: the search tried MAX_GROUPING_STEPS entries, or the field
      has too many pieces to search, without finishing.
    An empty dict means the two agree. No name is returned.
    """
    target = Counter((_fold(e["name"]), e["abn"] or e.get("abn_placeholder")) for e in entities)
    pieces = csv_field.split(",") if csv_field.strip() else []
    # A piece ending in a bracketed ABN ends its entry: the comma after it always separates.
    closes = [bool(_CSV_TRAILING_ABN.search(piece)) for piece in pieces]
    max_span = 1 + max((name.count(",") for name, _ in target), default=0)
    found = steps = 0
    used: Counter = Counter()

    def search(i: int) -> None:
        nonlocal found, steps
        if found > 1 or steps > MAX_GROUPING_STEPS:
            return
        if i == len(pieces):
            found += used == target
            return
        for j in range(i + 1, min(len(pieces), i + max_span) + 1):
            steps += 1
            if steps > MAX_GROUPING_STEPS:
                return
            pair = _entry_pair(",".join(pieces[i:j]))
            if used[pair] < target[pair]:
                used[pair] += 1
                search(j)
                used[pair] -= 1
            if closes[j - 1]:
                break

    try:
        search(0)
    except RecursionError:  # a field too long to search: fail closed like the step limit
        steps = MAX_GROUPING_STEPS + 1
    if steps > MAX_GROUPING_STEPS:
        return {"grouping_search_limit_exceeded": MAX_GROUPING_STEPS}
    if found == 1:
        return {}
    if found > 1:
        return {"several_groupings_match_page": found}
    problems = {"no_grouping_matches_page": 1}
    csv_abns = Counter(re.sub(r"\D", "", v) for v in _CSV_BRACKET_ABN.findall(csv_field))
    page_abns = Counter(abn for (_, abn), n in target.items() for _ in range(n) if abn)
    if csv_abns != page_abns:
        problems["abn_multiset_differs"] = sum(
            ((csv_abns - page_abns) + (page_abns - csv_abns)).values()
        )
    return problems


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
# Statement pages: strict schema
# ---------------------------------------------------------------------------


class PageParseError(ValueError):
    """A statement page whose entity markup is missing or not exactly the known structure."""


def _classes(tag: Tag) -> list[str]:
    return list(tag.get("class") or [])


def _elements(tag: Tag, where: str) -> list[Tag]:
    """Element children of tag. Any non-blank text, comment or other node is an error."""
    out = []
    for child in tag.children:
        if isinstance(child, Tag):
            out.append(child)
        elif type(child) is NavigableString:
            if child.strip():
                raise PageParseError(f"{where}: unexpected text")
        else:
            raise PageParseError(f"{where}: unexpected {type(child).__name__}")
    return out


def _plain_text(tag: Tag, where: str) -> str:
    """Text of a tag whose children must all be plain text."""
    for child in tag.children:
        if type(child) is not NavigableString:
            raise PageParseError(f"{where}: unexpected content in <{tag.name}>")
    return tag.get_text()


def _entity_name(name_div: Tag, where: str) -> str:
    """The name link's own text. A <small> former name is allowed and left out."""
    kids = _elements(name_div, where)
    if (
        len(kids) != 1
        or kids[0].name != "a"
        or _classes(kids[0]) != ["statement-entity__name-link"]
    ):
        raise PageParseError(f"{where}: name block is not one name link")
    parts = []
    for child in kids[0].children:
        if type(child) is NavigableString:
            parts.append(str(child))
        elif isinstance(child, Tag) and child.name == "small" and not child.attrs:
            _plain_text(child, where)
        else:
            raise PageParseError(f"{where}: unexpected content in the name link")
    name = " ".join(re.sub(r"\(\s*\)", " ", " ".join(parts)).split())
    if not name:
        raise PageParseError(f"{where}: empty entity name")
    return name


def _paragraph(p: Tag, where: str) -> tuple[str, str | None]:
    """Kind of an entity paragraph: empty, non_profit, or ABN/ACN/ARBN with its digits."""
    if p.attrs:
        raise PageParseError(f"{where}: paragraph with attributes")
    kids = list(p.children)
    for child in kids:
        if not isinstance(child, Tag) and type(child) is not NavigableString:
            raise PageParseError(f"{where}: unexpected {type(child).__name__}")
    tags = [c for c in kids if isinstance(c, Tag)]
    text = " ".join("".join(str(c) for c in kids if not isinstance(c, Tag)).split())
    if not tags and not text:
        return "empty", None
    if text == NON_PROFIT_TEXT and all(t.name == "br" and not list(t.children) for t in tags):
        return "non_profit", None
    if len(tags) != 1 or tags[0].name != "a":
        raise PageParseError(f"{where}: unrecognised paragraph")
    link = tags[0]
    i = kids.index(link)
    before = "".join(str(c) for c in kids[:i]).strip()
    after = "".join(str(c) for c in kids[i + 1 :]).strip()
    label = before[:-1] if before.endswith(":") else None
    if label not in _ID_HREF or after:
        raise PageParseError(f"{where}: unrecognised paragraph")
    href = _ID_HREF[label].fullmatch(link.get("href") or "")
    shown = _plain_text(link, where).strip()
    digits = shown.replace(" ", "")
    if not href or not re.fullmatch(r"[\d ]+", shown) or digits != href.group(1):
        raise PageParseError(f"{where}: {label} link text and target disagree or are not digits")
    if label != "ABN" or (_ABN_TEXT.fullmatch(shown) and valid_abn(digits)):
        return label, digits
    # The checksum runs first: a 00-prefixed value that passes it is a real ABN.
    if _ABN_PLACEHOLDER.fullmatch(shown):
        return "ABN_PLACEHOLDER", digits
    raise PageParseError(f"{where}: ABN link text is not a valid ABN")


def _entity(div: Tag, where: str, allow_non_profit: bool) -> dict:
    kids = _elements(div, where)
    if not kids or kids[0].name != "div" or _classes(kids[0]) != ["statement-entity__name"]:
        raise PageParseError(f"{where}: entity does not start with its name block")
    name = _entity_name(kids[0], where)
    abn = placeholder = None
    seen: set[str] = set()
    for p in kids[1:]:
        if p.name != "p":
            raise PageParseError(f"{where}: unexpected element <{p.name}> in an entity")
        kind, digits = _paragraph(p, where)
        if kind == "ABN_PLACEHOLDER":
            placeholder, kind = digits, "ABN"
        if kind == "non_profit" and not allow_non_profit:
            raise PageParseError(f"{where}: non-profit flag outside the reporting section")
        if kind != "empty" and kind in seen:
            raise PageParseError(f"{where}: repeated {kind} paragraph")
        seen.add(kind)
        if kind == "ABN" and not placeholder:
            abn = digits
    out = {"name": name, "abn": abn}
    if placeholder:
        out["abn_placeholder"] = placeholder
    return out


def _section(soup: BeautifulSoup, element_id: str, label: str) -> list[dict] | None:
    """Entities of one section, None when the section is absent."""
    found = soup.find_all(id=element_id)
    if not found:
        return None
    if len(found) > 1:
        raise PageParseError(f"{label} section appears more than once")
    kids = _elements(found[0], f"{label} section")
    if not kids:
        raise PageParseError(f"{label} section present but holds no entity")
    out = []
    for n, div in enumerate(kids, 1):
        if div.name != "div" or _classes(div) != ["statement-entity"]:
            raise PageParseError(f"{label} section holds an unrecognised element <{div.name}>")
        out.append(_entity(div, f"{label} entity {n}", allow_non_profit=label == "reporting"))
    return out


def parse_statement_page(page_html: str) -> dict:
    """Reporting and included entities as {name, abn}. Included entities are de-duplicated.

    Inside both entity sections every element and text node must match the known structure:
    entity blocks, each a name block holding one name link (optionally with a <small> former
    name), then paragraphs that are empty, a non-profit flag (reporting entities only), or one
    ABN, ACN or ARBN link whose digits equal its target. An ABN link's text must be a valid ABN,
    or the register's 00-prefixed placeholder, which is read as no ABN and listed in
    abn_placeholders. Anything else raises PageParseError. A page with no included-entity section is a statement
    with no included entities; main() cross-checks that against the CSV. Names are used only for
    the review queue and are never written out.
    """
    soup = BeautifulSoup(page_html, "html.parser")
    reporting = _section(soup, "statement-reporting-entities", "reporting")
    if not reporting:
        raise PageParseError("no reporting entity section")
    listed = _section(soup, "statement-included-entities", "included") or []
    included: list[dict] = []
    seen: set[tuple[str, str | None]] = set()
    for ent in listed:
        key = (normalise(ent["name"]), ent["abn"])
        if key not in seen:
            seen.add(key)
            included.append(ent)
    return {
        "reporting": reporting,
        "included": included,
        "included_listed": listed,
        "included_abn_count": sum(1 for e in listed if e["abn"] or e.get("abn_placeholder")),
        "abn_placeholders": [
            {"msr_role": role, "value": e["abn_placeholder"]}
            for role, ents in (("reporting_entity", reporting), ("included_entity", listed))
            for e in ents
            if e.get("abn_placeholder")
        ],
    }


# ---------------------------------------------------------------------------
# Screening and matching
# ---------------------------------------------------------------------------


def normalise(name: str | None) -> str:
    """Case, whitespace, punctuation, PTY LTD variants and a leading THE (join_enforcement)."""
    return normalise_provider_name(name)


def loose_key(name: str | None) -> str:
    """Normalised name without its trailing PTY LTD, LTD or INC. Review queue only."""
    return _SUFFIX_TAIL.sub("", normalise(name)).strip()


def duplicate_keys(rows: list[dict], key: str = "provider_approval_number") -> list[str]:
    """Provider approval numbers that appear on more than one row."""
    counts = Counter(normalise_pr(r.get(key)) for r in rows)
    return sorted(pr for pr, n in counts.items() if pr and n > 1)


def abr_types_from(abn_rows: list[dict], details_rows: list[dict] = ()) -> dict[str, dict]:
    """ABN -> {entity_type_code, source, conflict} from ABR data held locally.

    provider-abn.csv gives the type of accepted provider ABNs; abn-details.csv gives it for ABNs
    looked up in stage A. When the sources disagree, the entry is a conflict: its code is IND if
    either source says individual, otherwise None.
    """
    seen: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for r in details_rows:
        abn = (r.get("abn") or "").strip()
        code = (r.get("entity_type_code") or "").strip().upper()
        status = (r.get("lookup_status") or "").strip()
        if not abn:
            continue
        if status == "excluded_individual" or code in INDIVIDUAL_ABR_TYPES:
            seen[abn].append(("IND", "abn-details.csv"))
        elif status == "ok" and code:
            seen[abn].append((code, "abn-details.csv"))
    for r in abn_rows:
        abn = (r.get("abn") or "").strip()
        code = (r.get("entity_type_code") or "").strip().upper()
        if not abn or not code:
            continue
        if (r.get("match_kind") or "") not in ACCEPTED_KINDS and code not in INDIVIDUAL_ABR_TYPES:
            continue
        seen[abn].append((code, "provider-abn.csv"))
    out: dict[str, dict] = {}
    for abn, entries in seen.items():
        codes = {code for code, _ in entries}
        sources = "; ".join(sorted({src for _, src in entries}))
        if len(codes) > 1:
            code = "IND" if "IND" in codes else None
            out[abn] = {"entity_type_code": code, "source": sources, "conflict": True}
        else:
            (code,) = codes
            out[abn] = {"entity_type_code": code, "source": sources, "conflict": False}
    return out


def _screen_reason(
    profiles: list[dict], abn_rows: list[dict], abr_types: dict[str, dict]
) -> str | None:
    """The first screening reason that excludes a provider, or None when it passes."""
    if not profiles:
        return "excluded_missing_profile"
    if len(profiles) > 1:
        return "excluded_duplicate_profile_rows"
    if len(abn_rows) > 1:
        return "excluded_duplicate_provider_abn_rows"
    p = profiles[0]
    if (p.get("entity_form") or "").strip() not in ORGANISATION_FORMS:
        return "excluded_not_positively_organisation"
    if (p.get("name_withheld") or "").strip().lower() != "false":
        return "excluded_name_withheld"
    if not (p.get("legal_name") or "").strip():
        return "excluded_blank_legal_name"
    for r in abn_rows:
        kind = (r.get("match_kind") or "").strip()
        if kind == "excluded_individual_abr":
            return "excluded_abr_individual"
        if kind in INDIVIDUAL_KINDS:
            return "excluded_abn_step_individual_or_unknown"
        info = abr_types.get((r.get("abn") or "").strip()) or {}
        row_code = (r.get("entity_type_code") or "").strip().upper()
        if row_code in INDIVIDUAL_ABR_TYPES or info.get("entity_type_code") in INDIVIDUAL_ABR_TYPES:
            return "excluded_abr_individual"
        if info.get("conflict"):
            return "excluded_abr_type_conflict"
    return None


def screen_providers(
    profiles: list[dict], abn_rows: list[dict], abr_types: dict[str, dict] | None = None
) -> tuple[dict[str, dict], dict]:
    """Providers that pass screening, as pr -> {legal_name, abn}, and the counts.

    abn is the accepted provider ABN when it passes the checksum, else None. Every provider in
    either input is considered; each excluded one is counted under its first reason.
    """
    abr_types = abr_types or {}
    by_profile: dict[str, list[dict]] = defaultdict(list)
    by_abn_row: dict[str, list[dict]] = defaultdict(list)
    for p in profiles:
        pr = normalise_pr(p.get("provider_approval_number"))
        if pr:
            by_profile[pr].append(p)
    for r in abn_rows:
        pr = normalise_pr(r.get("provider_approval_number"))
        if pr:
            by_abn_row[pr].append(r)
    stats: dict[str, int] = {"providers_considered": 0, "providers_screened_in": 0}
    stats.update({reason: 0 for reason in SCREEN_REASONS})
    stats["screened_abn_failing_checksum_not_used"] = 0
    out: dict[str, dict] = {}
    for pr in sorted(set(by_profile) | set(by_abn_row)):
        stats["providers_considered"] += 1
        rows = by_abn_row.get(pr, [])
        reason = _screen_reason(by_profile.get(pr, []), rows, abr_types)
        if reason:
            stats[reason] += 1
            continue
        abn = None
        if rows and (rows[0].get("match_kind") or "").strip() in ACCEPTED_KINDS:
            candidate = (rows[0].get("abn") or "").strip()
            if valid_abn(candidate):
                abn = candidate
            elif candidate:
                stats["screened_abn_failing_checksum_not_used"] += 1
        out[pr] = {"legal_name": by_profile[pr][0]["legal_name"].strip(), "abn": abn}
        stats["providers_screened_in"] += 1
    return out, stats


class _Index:
    """Lookups over screened providers. Names index every profile only to detect ambiguity."""

    def __init__(self, profiles: list[dict], screened: dict[str, dict]):
        self.by_abn: dict[str, list[str]] = defaultdict(list)
        for pr, info in sorted(screened.items()):
            if info["abn"]:
                self.by_abn[info["abn"]].append(pr)
        self.by_name: dict[str, set[str]] = defaultdict(set)
        self.by_loose: dict[str, set[str]] = defaultdict(set)
        for p in profiles:
            pr = normalise_pr(p.get("provider_approval_number"))
            legal = (p.get("legal_name") or "").strip()
            if pr and normalise(legal):
                self.by_name[normalise(legal)].add(pr)
                self.by_loose[loose_key(legal)].add(pr)


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


def _single_group(statement: dict) -> dict:
    """Group of a statement with one reporting entity: its ABN on this statement, else the page."""
    abn = statement["parsed"]["reporting"][0]["abn"]
    if valid_abn(abn):
        return {"group_key": abn, "group_key_source": "abn_on_statement", "group_abn": abn}
    return {
        "group_key": f"MSR-{statement['page_id']}",
        "group_key_source": "statement_page_no_abn",
        "group_abn": None,
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
    statements: list[dict], profiles: list[dict], screened: dict[str, dict]
) -> tuple[list[dict], list[dict], dict]:
    """Provider-statement relations (by ABN only), review queue and match statistics."""
    idx = _Index(profiles, screened)
    relations: dict[tuple[str, str], dict] = {}
    review: list[dict] = []
    stats: Counter = Counter()

    def add_relation(s: dict, pr: str, role: str, abn: str) -> None:
        method = f"{role}_abn_equals_provider_abn"
        k = (pr, s["page_id"])
        if k in relations and _RANK[relations[k]["match_method"]] <= _RANK[method]:
            return
        relations[k] = {
            **_statement_facts(s),
            "provider_approval_number": pr,
            "provider_legal_name": screened[pr]["legal_name"],
            "provider_abn": screened[pr]["abn"],
            "msr_role": role,
            "match_method": method,
            "msr_entity_abn": abn,
        }

    def add_review(s: dict, role: str, abn: str | None, reason: str, prs: set[str]) -> None:
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

    def visible(prs: set[str]) -> set[str]:
        if any(pr not in screened for pr in prs):
            stats["name_matches_to_excluded_providers"] += 1
        return {pr for pr in prs if pr in screened}

    def match_entity(s: dict, role: str, name: str, abn: str | None) -> None:
        if valid_abn(abn) and abn in idx.by_abn:
            for pr in idx.by_abn[abn]:
                add_relation(s, pr, role, abn)
            return
        key = normalise(name)
        if not key:
            return
        prs = idx.by_name.get(key, set())
        shown = visible(prs)
        if len(prs) > 1:
            if shown:
                add_review(s, role, abn, "ambiguous_matches_several_providers", shown)
            return
        if len(prs) == 1:
            if not shown:
                return
            (pr,) = shown
            if abn and screened[pr]["abn"]:
                reason = "msr_abn_differs_from_provider_abn"
            elif abn:
                reason = "name_match_provider_abn_not_resolved"
            else:
                reason = "name_match_without_msr_abn"
            add_review(s, role, abn, reason, shown)
            return
        loose = visible(idx.by_loose.get(loose_key(name), set()))
        if loose:
            add_review(s, role, abn, "fuzzy_corporate_suffix_differs", loose)

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
            _single_group(s)
            if single
            else {"group_key": None, "group_key_source": None, "group_abn": None}
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
    stats.setdefault("name_matches_to_excluded_providers", 0)
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
    abr_types = abr_types if abr_types is not None else abr_types_from(abn_rows)
    screened, screening = screen_providers(profiles, abn_rows, abr_types)
    relations, review, stats = match_relations(statements, profiles, screened)
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
        "screening": screening,
        "screened_abn_count": sum(1 for info in screened.values() if info["abn"]),
        "screened_prs": sorted(screened),
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
    latest_periods = sorted(e["reporting_period"] for e in edges if e.get("reporting_period"))
    all_periods = sorted(
        {
            r["reporting_period"]
            for r in relations
            if r["relation"] == CONTROLLED and r.get("reporting_period")
        }
    )
    groups = []
    for key in group_keys:
        members = [e for e in edges if e["group_key"] == key]
        latest = max(members, key=_page_order)
        prs = {e["provider_approval_number"] for e in members}
        groups.append(
            {
                "group_key": key,
                "group_abn": latest["group_abn"],
                "controlled_providers": len(prs),
                "services_of_controlled_providers": _services(services, prs),
                "head_provider": next(
                    (h["provider_approval_number"] for h in heads if h["group_key"] == key), None
                ),
            }
        )
    groups.sort(key=lambda g: (-g["controlled_providers"], g["group_key"]))
    screened_prs = set(layer.get("screened_prs", []))
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
            "priority_providers_total": len(priority),
            "priority_providers_with_abn": len(priority_with_abn),
            "priority_providers_screened_in": len(priority & screened_prs),
            "screened_providers_with_valid_abn": layer.get("screened_abn_count", 0),
            "services_total": None if services is None else len(services),
            "services_note": None if services is not None else SERVICES_MISSING_NOTE,
            "review_queue": len(review),
            "review_by_reason": dict(sorted(Counter(r["reason"] for r in review).items())),
            "name_matches_to_excluded_providers": stats.get(
                "name_matches_to_excluded_providers", 0
            ),
            "screening": {
                **layer.get("screening", {}),
                "rule": "A provider is used only with exactly one provider-profile.csv row "
                "positively classified as an organisation, not withheld, with a legal name, at "
                "most one provider-abn.csv row, and no local ABR source marking it as an "
                "individual or disagreeing on its ABN's type. Each excluded provider is counted "
                "once, under the first reason that applies.",
            },
        },
        "window": {
            "note": "Each edge shows its latest statement; statement_ids lists every statement "
            "that links the provider to the group, across all reporting years.",
            "latest_statement_period_earliest": latest_periods[0] if latest_periods else None,
            "latest_statement_period_latest": latest_periods[-1] if latest_periods else None,
            "all_edge_statement_periods": all_periods,
        },
        "groups": groups,
        "joint_statements_for_manual_confirmation": joint_manual_candidates(coreported),
        "name_policy": NAME_POLICY,
        "review_reasons": REVIEW_REASONS,
        "caveats": [
            EDGE_DEFINITION,
            HEAD_DEFINITION,
            JOINT_DEFINITION,
            "The register covers entities with annual consolidated revenue of at least AUD 100 "
            "million, plus voluntary reporters. Absence of an edge says nothing about ownership.",
            "Edges need an ABN on the statement page. An included entity listed without an ABN "
            "never makes an edge; when its name matches a provider it is in the review queue.",
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
    """Parsed page, or None when it is unreadable, unrecognised or disagrees with the CSV.

    The page must agree with its CSV row: the IncludedEntities field is non-empty exactly when
    the page has an included-entity section, the number of bracketed ABNs equals the number of
    included entities with an ABN link, and both entity sections reconcile with the
    ReportingEntities and IncludedEntities fields as multisets of (name, ABN) pairs, through
    exactly one grouping of the CSV text (reconcile_entities).
    """
    try:
        parsed = parse_statement_page(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        log.error("statement page %s not usable: %s", path.as_posix(), exc)
        return None
    if bool(statement.get("csv_lists_included")) != bool(parsed["included"]):
        log.error(
            "statement page %s: the CSV %s included entities but the page %s",
            path.as_posix(),
            "lists" if statement.get("csv_lists_included") else "lists no",
            "has some" if parsed["included"] else "has none",
        )
        return None
    if parsed["included_abn_count"] != statement.get("csv_included_abn_count", 0):
        log.error(
            "statement page %s: the CSV gives %d included-entity ABNs, the page %d",
            path.as_posix(),
            statement.get("csv_included_abn_count", 0),
            parsed["included_abn_count"],
        )
        return None
    for label, field, entities in (
        ("reporting", "reporting_entities_text", parsed["reporting"]),
        ("included", "included_entities_text", parsed["included_listed"]),
    ):
        problems = reconcile_entities(statement[field], entities)
        if problems:
            log.error(
                "statement %s page %s: %s entities do not reconcile with the CSV: %s",
                statement["statement_id"],
                path.as_posix(),
                label,
                json.dumps(problems, sort_keys=True),
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

    try:
        got_csv = acquire_csv(args.no_fetch)
    except CsvSchemaError as exc:
        log.error("fetched all-statements CSV not stored: %s; outputs left unchanged", exc)
        return 2
    if got_csv is None:
        log.error("no MSR CSV snapshot in data/raw/msr/all-statements/: nothing to build")
        return 1
    csv_path, csv_meta = got_csv
    try:
        statements = parse_statements_csv(csv_path.read_text(encoding="utf-8-sig"))
    except CsvSchemaError as exc:
        log.error("%s: %s; outputs left unchanged", csv_path.as_posix(), exc)
        return 2
    abn_rows = _load_csv(PROVIDER_ABN_CSV)
    profiles = _load_csv(PROFILE_CSV)
    for path, rows in ((PROFILE_CSV, profiles), (PROVIDER_ABN_CSV, abn_rows)):
        dups = duplicate_keys(rows)
        if dups:
            log.error(
                "%s has %d provider_approval_number values on more than one row (first: %s); "
                "outputs left unchanged",
                path.name,
                len(dups),
                dups[0],
            )
            return 2
    details = _load_csv(ABN_DETAILS_CSV) if ABN_DETAILS_CSV.exists() else []
    abr_types = abr_types_from(abn_rows, details)
    screened, _ = screen_providers(profiles, abn_rows, abr_types)
    provider_abns = {info["abn"] for info in screened.values() if info["abn"]}
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
        "on that statement, or MSR-<statement page id> when the statement gives none "
        "(group_key_source says which). No key is derived from a name. " + NAME_POLICY + local_only,
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
        notes="Name matches that are not ABN matches, so never relations or edges. "
        + REVIEW_REASONS
        + " Not evidence of ownership. Rows carry statement ids, URLs, ABNs and candidate "
        "provider approval numbers; no names." + local_only,
    )
    summary = summarise(layer, abn_rows, services, candidates_count=len(candidates))
    summary["counts"]["candidate_pages_missing"] = 0
    summary["abn_placeholders_read_as_no_abn"] = [
        {"statement_id": s["statement_id"], "statement_url": s["statement_url"], **ph}
        for s in candidates
        for ph in s["parsed"].get("abn_placeholders", [])
    ]
    summary["counts"]["abn_placeholders_read_as_no_abn"] = len(
        summary["abn_placeholders_read_as_no_abn"]
    )
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
