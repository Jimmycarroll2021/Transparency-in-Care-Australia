# Ownership layer 1: provider groups from the Modern Slavery Register (2026-10-31)

Finding: 6 of the 1,210 priority providers (0.5%; 6 of the 901 with a resolved ABN) gained an
ownership edge (`controlled_entity_of`) from the Modern Slavery Statements Register (MSR), on 7
edges. Every edge is an ABN match: the included entity's ABN on the statement page, checksum
valid, equals the provider's ABN. The 6 providers roll up to 6 groups, each identified by the
reporting entity's ABN, and operate 150 of the 18,186 service approvals in the current ACECQA
export (0.8%). The 11 edges that earlier versions made from name matches are now review rows.
Joint-statement rows (46) and group-head rows (2) are recorded separately and are not ownership.
Confidence: High for the counts as produced by the script; Medium for what an edge means (see
Definitions).

Serves GAP-003 (no public ownership graph). Written by the data-engineer spoke, reworked after the
hub gate and four Codex review rounds on PR #5; round 4 simplified the design to ABN-only edges
with no group names. Script: `scrapers/build_msr_group_edges.py`; tests:
`tests/test_msr_group_edges.py`.

## Name policy

The only name in any MSR output, and in this note, is the ACECQA provider legal name
(`provider_legal_name`, keyed by `provider_approval_number`), and only for providers that pass
screening. No group name is written: a group is identified by the reporting entity's ABN on the
statement, or by `MSR-<statement page id>` when the statement gives no ABN. No name read from the
register is published. Edge, group-head and co-reported rows carry the screened provider's
ACECQA legal name with its approval number. Review and summary rows carry statement ids, URLs,
ABNs and provider approval numbers only, with no names. The ABN Lookup API was not called for this
layer.

## Screening

A provider can appear in any output only if all of these hold. Anything missing, duplicated, blank
or conflicting excludes it, and each excluded provider is counted once, under the first reason in
this order:

| Rule | Excluded this run (of 10,073 providers considered) |
|---|---|
| Exactly one row in `provider-profile.csv` (missing) | 0 |
| Exactly one row in `provider-profile.csv` (duplicated) | 0 |
| At most one row in `provider-abn.csv` | 0 |
| `entity_form` positively an organisation: company, incorporated association, trust or trustee, cooperative, government, church or religious | 1,100 (likely individual or unknown) |
| Name not withheld | 0 |
| Legal name not blank | 0 |
| `provider-abn.csv` does not mark it as an individual or unknown | 0 |
| No ABR source (`provider-abn.csv`, `abn-details.csv`) gives entity type IND | 0 |
| ABR sources agree on its ABN's entity type | 0 |

10,073 providers considered, 8,973 screened in (1,121 of the 1,210 priority providers). The ABN
index is built from screened providers only: 901 accepted, checksum-valid ABNs. A duplicate
`provider_approval_number` row in `provider-profile.csv` or `provider-abn.csv` stops the run with
exit 2. The check runs after the all-statements CSV has been fetched, checked and stored as a raw
snapshot (unless `--no-fetch`), and before any statement page is fetched or any output is written.

## Definitions

Every screened provider found by ABN in a candidate statement is a relation. Each relation is
classified into exactly one class:

| Class | Rule | Ownership edge? | File |
|---|---|---|---|
| `controlled_entity_of` | The provider, by ABN, is an included entity in a Single statement (one reporting entity) | Yes, the only one | `provider-group-edges-msr.csv` |
| `group_parent_self` | The provider, by ABN, is the reporting entity of a Single statement that lists included entities | No: marks a group head | `provider-group-heads-msr.csv` |
| `co_reported_joint` | Any relation from a Joint statement | No: "joint statement: co-reporting, not evidence of ownership" | `provider-coreported-msr.csv` |
| `self_report_no_included_entities` | The provider is the reporting entity of a Single statement with no included entities | No | counted only |
| `unclassified_statement` | Any other statement type | No | counted only (0 this run) |

A name never makes a relation. An entity whose name equals a screened provider's legal name, but
whose ABN is missing or different, goes to the review queue.

`controlled_entity_of` reads "included in the group's modern slavery statement as owned or
controlled by the reporting entity". That reading rests on the Modern Slavery Act 2018 (Cth),
which requires a statement to describe consultation with the entities the reporting entity owns or
controls (section 16), and on the register listing those entities as "Included entities".
`[Verify This]`: the register does not define the field on the pages read, and the section 16
reading has not been checked against the Act's text or departmental guidance. An edge is not a
verified ownership chain, shareholding or acquisition date.

## Counts (window and denominators)

Source: the all-statements CSV captured 2026-10-30T19:32Z (UTC; 31 October in Canberra), 18,869
statement rows covering every reporting year on the register. Statement pages captured
2026-10-30T19:32Z to 19:37Z. Only candidate statements are read (see Method), so the edges cover
the reporting periods of those statements, not the whole register.

Reporting periods: each edge row shows its latest statement, and `statement_ids` lists every
statement that links the provider to the group. The latest statements behind the 7 edges have
reporting periods from 1 July 2023 to 30 June 2024 (the earliest) to the 2025 calendar year (the
latest). All statements behind the edges, older ones included, cover four reporting periods: the
2023, 2024 and 2025 calendar years and the year to 30 June 2024.

| Measure | Count | Denominator |
|---|---|---|
| Candidate statements (pages parsed) | 136 | 18,869 statement rows |
| Included entities parsed | 530 (350 with an ABN) | 136 pages |
| Provider-statement relations (ABN matches) | 85 | n/a: no fixed population; one per screened provider found by ABN in one of the 136 statements |
| `controlled_entity_of` relations | 11 | 85 |
| `controlled_entity_of` edges (one per provider and group) | 7 | 11 `controlled_entity_of` relations, collapsed |
| Providers with an edge | 6 | 1,210 priority providers (901 with an ABN) |
| Groups they roll up to | 6 | 7 edges |
| Services those providers operate | 150 | 18,186 current ACECQA services |
| `group_parent_self` rows / providers | 2 / 2 | 3 `group_parent_self` relations / 1,210 priority providers; not ownership |
| Services of group-head providers | 298 | 18,186; not ownership |
| `co_reported_joint` rows / providers / statements | 46 / 16 / 22 | 85 relations / 1,210 priority providers / 136 statements; not ownership |
| Providers whose only relations are joint | 14 | 16 |
| `self_report_no_included_entities` relations | 25 | 85 relations; not ownership |
| Review queue rows | 125 | n/a: no fixed population; one row per name match without a matching ABN |
| Former name-matched edges now in review | 11 | 11 |

All 6 providers with an edge are priority providers. That follows from the method: every edge
needs a provider ABN from `provider-abn.csv`, which covers only the priority subset.

### Groups

| Group ABN | Controlled providers (ACECQA) | Their services | Statements |
|---|---|---|---|
| 68670538780 | 2: Story House Early Learning No 1 Pty Ltd, Story House Early Learning No 21 Pty Ltd | 46 | 2025-785 |
| 32025287736 | 1: FSAC Ltd | 6 | 2024-1143, 2025-1400 |
| 39703442583 | 1: UNITING (VICTORIA AND TASMANIA) LIMITED | 89 | 2024-3070 |
| 46141203125 | 1: U@MQ Ltd | 4 | 2026-1300 |
| 65124826722 | 1: SMARTPLAY EARLY LEARNERS PTY LTD | 5 | 2024-513, 2025-1002, 2026-701 |
| 90952801237 | 1: U@MQ Ltd | 4 | 2024-1139, 2025-1018 |

None of the 6 groups has a group-head row: no reporting entity's ABN equals a provider ABN. The two
group heads (PR-00000898 G8 Education Limited and PR-40002186 Wesley Community Services Limited)
have no ABN-matched controlled providers. The 2024-1133 statement headed by PR-00000898 lists 73
included entities with no ABN; its 31 name matches are review rows.

## Former name-matched edges

Earlier versions also made an edge when an included entity listed without an ABN had a normalised
name equal to one ACECQA legal name and that provider's ABR entity name. Round 4 removed that
path. All 11 such edges (9 from statement 2024-1133, 2 from 2025-2897) are now review rows with
reason `name_match_without_msr_abn`. None of them became an ABN edge.

## Joint statements for manual confirmation

Joint statements are never promoted to edges. Two list screened providers as included entities by
ABN: 2024-1335 (https://modernslaveryregister.gov.au/statements/18637/, 53 reporting entities, 4
providers) and 2025-1579 (https://modernslaveryregister.gov.au/statements/23594/, 44 reporting
entities, 5 providers). Both combine many separate bodies; neither looks like one group.

Statement 2026-1450 (https://modernslaveryregister.gov.au/statements/29210/), which earlier
versions flagged as one corporate group's joint filing, gives no ABN for its included entities. Its
15 name matches are now review rows only. Any ownership claim needs another source (for example
ASIC extracts or annual reports).

## Method

1. The script reads https://modernslaveryregister.gov.au/resources/, finds the
   `all-statement-information_<date>.csv` link and downloads it. Columns: IDX, PeriodStart,
   PeriodEnd, Type, VoluntaryCompliance, HeadquarteredCountries, AnnualRevenue,
   ReportingEntities, IncludedEntities, ABN, ACN, ARBN, Link, IndustrySectors, RelatedStatements.
   No column holds an individual's name, so the privacy filter dropped none. The filter still runs
   on every download.
2. Candidates: any ABN in the CSV ABN column (reporting and included entities' ABNs) equals a
   screened provider's ABN (60 statements), or the reporting entities' text contains early
   learning, childcare, child care, kindergarten or education (76).
3. Each candidate's statement page is fetched once with the project User-Agent, robots.txt honoured
   (it disallows only `/admin/`, `/statements/file/` and `/compliance/`), at least 2 s apart.
   Statement numbers (IDX) are not unique in the CSV (10 repeat), so the page id is the key.
4. Each page's reporting-entity and included-entity sections are parsed against a strict schema
   (see Completeness checks).
5. Matching is by ABN only: an entity's ABN equals a screened provider's ABN. Classification as
   in the Definitions table. Edges and heads are collapsed to one row per provider and group,
   taken from the latest statement, with `statement_ids` and `statement_urls` listing every
   statement.

## Completeness checks

Exit codes. 0: complete; every output is written. 2: incomplete; some candidate pages are
missing or unparseable, or an input check fails (both listed below), and every output is left
unchanged. 1: nothing usable (no CSV snapshot, no candidate statement, or no candidate page that
can be read); every output is left unchanged. When no page at all can be read the run exits 1,
except with `--refresh`, where any failed fetch exits 2.

Input checks that exit 2 before any statement page is read, in this order:

- the all-statements CSV lacks a column that selection or reconciliation reads (IDX,
  PeriodStart, PeriodEnd, Type, ReportingEntities, IncludedEntities, ABN, Link), whether missing
  or renamed, two header names are the same after stripping spaces and folding case, or any
  record's field count differs from the header's, whichever column it lacks. The header and
  record checks run before the privacy filter and before a downloaded CSV is stored, and again
  when a snapshot is parsed; nothing is padded, and a downloaded CSV that fails is not stored;
- `provider-profile.csv` or `provider-abn.csv` has a duplicate `provider_approval_number` row.

Page checks: a page counts as missing or unparseable, and the run exits 2 (or 1 if no page is
usable), when any of these happens:

- a matching CSV row has no usable statement page id;
- a candidate page is missing, or its fetch fails;
- inside either entity section, any element or text node at any depth does not match the known
  structure: entity blocks, each a name block with one name link (a `<small>` former name allowed),
  then paragraphs that are empty, a non-profit flag (reporting entities only), or one ABN, ACN or
  ARBN link whose text and target digits agree. Comments, stray text, unknown elements and unknown
  labels all fail;
- an ABN link's text is not a valid ABN (11 digits passing the ABN checksum), with one listed
  exception below;
- the CSV IncludedEntities field is non-empty but the page has no included-entity section, or the
  reverse;
- the number of ABNs in brackets in the CSV IncludedEntities field differs from the number of
  included entities with an ABN link on the page;
- either entity section does not reconcile with its CSV field (ReportingEntities or
  IncludedEntities) as a multiset of (name, ABN) pairs. The page gives one pair per entity
  block, duplicates counted: the name folded for case and whitespace, and the ABN (or the listed
  placeholder, or none). The CSV field is split on commas, and the pieces are grouped into
  entries, because names can contain commas; an entry's trailing bracketed ABN is its ABN, and a
  comma directly after a bracketed ABN always separates entries. Exactly one grouping must give
  the page's multiset. No grouping, or more than one, makes the page unparseable. The search
  tries at most 100,000 candidate entries per field and fails closed beyond that; on the current
  snapshots no field needed more than 99.

On the current snapshots all 136 candidates reconcile in both sections (272 fields, 174 of them
non-empty), each through exactly one grouping. In 9 fields (8 statements) a name contains a
comma, so splitting on every comma would not match the page; the grouping resolves each one
uniquely. This page-constrained grouping is the hub's decision under the owner's "data truth"
rule. 38 statements list included entities in both the CSV and the page and 98 in neither. The
earlier comma-based lower bound was unreliable and has been removed. If
`acecqa-services-latest.csv` is missing, service counts are null (unknown), not zero.

Exception: one page (statement 2022-3013, https://modernslaveryregister.gov.au/statements/11943/)
shows its reporting entity's ABN as "00 649 711 026": 00 followed by the 9-digit ARBN the same
entity gives on another statement. The value fails the ABN checksum. The checksum runs first: a
value that passes it is an ABN, even with a 00 prefix (00000000019 passes). Only a value that fails
the checksum and has exactly the form 00 then 9 digits is read as "no ABN", and every occurrence is
listed in the summary (`abn_placeholders_read_as_no_abn`, 1 this run). The CSV gives the same value
in brackets, so the reconciliation compares it like an ABN. Any other invalid ABN text still stops
the run. This exception was added to complete the round 4 rebuild and needs the owner's
confirmation.

## Review queue (125 rows)

| Reason | Rows (of 125) |
|---|---|
| name_match_provider_abn_not_resolved (MSR gives an ABN; the provider has no accepted ABN) | 63 |
| name_match_without_msr_abn (name equals one provider; MSR gives no ABN) | 53 |
| fuzzy_corporate_suffix_differs | 9 |

Rows carry the statement, the MSR-side ABN where given, the reason and candidate provider approval
numbers only. Resolving the 63 providers' ABNs with `scrapers/abn_lookup.py` could turn some into
ABN matches. Confidence: Medium.

## Limits

- Coverage: the MSR covers entities with annual consolidated revenue of at least AUD 100 million,
  plus voluntary reporters. Absence of an edge says nothing about ownership.
- ABN-only matching misses every included entity listed without an ABN (180 of 530 parsed), so
  edges undercount ownership. That is the cost of not matching on names.
- Statements are self-reported. A provider in an older statement may since have changed hands;
  every edge lists all its statements.
- Licence unclear: the MSR shows "Copyright Attorney-General's Department" and no open licence.
  Raw MSR files and their sidecars stay in `data/raw/msr/` (gitignored). Only derived facts are
  committed. This note does not clear the licence under `.claude/rules/data-pipeline.md`; ask the
  Attorney-General's Department before any public display.
- Earlier commits on this branch published names taken from the register, which the current
  policy does not allow. They remain in the public branch history; see the PR for counts.

## Outputs

- `data/processed/provider-group-edges-msr.csv` (7 rows, `controlled_entity_of` only)
- `data/processed/provider-group-heads-msr.csv` (2 rows)
- `data/processed/provider-coreported-msr.csv` (46 rows, caveat on every row)
- `data/processed/provider-group-review-msr.csv` (125 rows)
- Each with a `.provenance.json`, plus `data/processed/provider-group-edges-msr-summary.json`

Rebuild offline: `python3 scrapers/build_msr_group_edges.py --no-fetch`. `--refresh` takes a new
snapshot of every candidate page beside the old ones.

## Open questions

1. Licence: will the Attorney-General's Department permit display of derived group links?
2. Confirm the 00-prefixed ABN exception (statement 2022-3013), or decide the run should stop.
3. Statement 2026-1450: confirm ownership of its included providers from another source.
4. Should the 63 providers matched by name but without an accepted ABN be looked up and re-run?
5. Screening admits `trust_or_trustee` providers, whose ACECQA legal names are already published
   in `provider-profile.csv`. Confirm that, or exclude trusts.
6. History: earlier commits expose names taken from the register; rewriting history is the
   owner's decision.
7. Confirm the section 16 reading of "Included entities". `[Verify This]`
