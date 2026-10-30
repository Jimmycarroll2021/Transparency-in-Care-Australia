# Ownership layer 1: provider groups from the Modern Slavery Register (2026-10-31)

Finding: 44 of the 1,210 priority providers (3.6%; 44 of the 901 with a resolved ABN) gained at
least one group edge from the Modern Slavery Statements Register (MSR). Those 44 providers hold
2,379 of the 18,186 service approvals in the current ACECQA export (13.1%). The 31 providers linked
as an included (owned or controlled) entity hold 665 of them. Confidence: High for the counts as
produced by the script; Medium for what an edge means (see Definition).

Serves GAP-003 (no public ownership graph). Written by the data-engineer spoke. Script:
`scrapers/build_msr_group_edges.py`; tests: `tests/test_msr_group_edges.py`.

## Definition

An edge means the provider's legal entity is named in a modern slavery statement on the MSR:

- `reporting_entity`: the provider is a reporting entity of the statement, matched by ABN.
- `included_entity`: the provider is listed as an included entity, that is, included in the
  group's modern slavery statement as owned or controlled by the reporting entity.

The "owned or controlled" reading rests on the Modern Slavery Act 2018 (Cth), which requires a
statement to describe the reporting entity's consultation with the entities it owns or controls
(section 16) and on the register listing those entities as "Included entities". `[Verify This]`:
the register does not define the field on the statement pages read, and the section 16
interpretation has not been checked against the Act's text or the Home Affairs or
Attorney-General's guidance. An edge is not a verified ownership chain, a shareholding or a date of
acquisition.

## Counts (window and denominators)

Window: the all-statements CSV captured 2026-10-30T19:32Z (UTC; 31 October in Canberra), 18,869
statement rows, all years. Statement pages captured 2026-10-30T19:32Z to 19:37Z. Edges span
reporting periods from 1 July 2019 to 31 December 2025.

| Measure | Count | Denominator |
|---|---|---|
| Candidate statements | 136 | 18,869 statement rows |
| of which a listed ABN equals a provider ABN | 60 | |
| of which a childcare term in the reporting entities | 76 | |
| Statement pages fetched and parsed | 136 | 136 candidates (0 missing) |
| Included entities parsed | 530 | 136 pages |
| of which listed with an ABN | 350 | 530 |
| Edges, reporting_entity (by ABN) | 65 | |
| Edges, included_entity by ABN | 20 | |
| Edges, included_entity by name with ACECQA and ABR agreement | 22 | |
| Distinct providers with an edge | 44 | 1,210 priority providers |
| Distinct providers with a reporting_entity edge | 21 | 44 |
| Distinct providers with an included_entity edge | 31 | 44 |
| Services held by providers with an edge | 2,379 | 18,186 current ACECQA services |
| Services held by providers with an included_entity edge | 665 | 18,186 |
| Review queue rows | 103 | |
| Name matches to an excluded provider (individual or unknown form) | 4 | dropped, not shown |

All 44 providers with an edge are priority providers. That follows from the method: every edge
needs a provider ABN or ABR name from `provider-abn.csv`, which covers the priority subset only.

Largest groups by providers linked: G8 Education Limited (10 providers: itself plus 9 included
entities in statement 2024-1133, reporting year 2023); the Busy Bees and Think Childcare joint
statement 2026-1450 (9 included providers); Goodstart Early Learning (itself plus BFS Children's
Services and Goodstart Early Years, across statements from 2020 to 2025); SHEL Holdco (2 Story
House Early Learning companies). Six Catholic joint statements link 8 providers (19
co-reporting edges, 9 included-entity edges). Of the 107 edges, 56 come from statements typed
Joint (37 reporting_entity, 19 included_entity).

## Method

1. The script reads https://modernslaveryregister.gov.au/resources/, finds the
   `all-statement-information_<date>.csv` link and downloads it. Columns: IDX, PeriodStart,
   PeriodEnd, Type, VoluntaryCompliance, HeadquarteredCountries, AnnualRevenue,
   ReportingEntities, IncludedEntities, ABN, ACN, ARBN, Link, IndustrySectors, RelatedStatements.
   No column holds an individual's name, so the privacy filter dropped none. The filter still runs
   on every download and drops any signatory, approver or contact column if one appears.
2. Candidates: any ABN in the CSV ABN column (which lists reporting and included entities' ABNs)
   equals an ABN in `data/processed/provider-abn.csv`, or the reporting entities' text contains
   early learning, childcare, child care, kindergarten or education.
3. Each candidate's statement page is fetched once with the project User-Agent, robots.txt
   honoured (it disallows only `/admin/`, `/statements/file/` and `/compliance/`), at least 2 s
   apart. Reporting and included entities are parsed with their ABN where the page shows one.
   Statement numbers (IDX) are not unique in the CSV (10 repeat), so the page id from the URL is
   the key.
4. Edge rules, strongest first, one edge per provider and statement:
   a reporting or included entity's ABN equals a provider's ABN; or an included entity listed
   without an ABN whose normalised name equals exactly one ACECQA provider legal name and that
   provider's ABR entity name. Normalisation: upper case, punctuation and whitespace collapsed,
   PTY LTD, PTY. LIMITED and PROPRIETARY LIMITED made one form, LIMITED to LTD, leading THE
   dropped (`normalise_provider_name` in `scrapers/join_enforcement.py`).
5. Everything else that looks like a match goes to `provider-group-review-msr.csv`, never to the
   edges: several providers share the name; the ABR name disagrees; the MSR ABN differs from the
   provider's ABN; the provider has no resolved ABN; only the corporate suffix differs; a reporting
   entity is named without an ABN.
6. `group_key` is the single reporting entity's ABN, or `MSR-<page id>` for joint statements.

## Review queue (103 rows)

| Reason | Rows | Providers | Priority providers |
|---|---|---|---|
| name_match_provider_abn_not_resolved (MSR gives an ABN; provider's ABN not resolved) | 63 | 26 | 3 |
| name_unique_provider_without_abn | 28 | 28 | 0 |
| fuzzy_corporate_suffix_differs | 9 | 2 | 2 |
| reporting_entity_name_only | 3 | 2 | 2 |

Five priority providers in the queue have no edge yet. Most queue rows are operating subsidiaries
outside the priority subset (for example G8 and Story House centre companies). Resolving their
ABNs with `scrapers/abn_lookup.py` would turn many into ABN-backed edges. Confidence: Medium.

## Limits

- Coverage: the MSR covers entities with annual consolidated revenue of at least AUD 100 million,
  plus voluntary reporters. Smaller groups never appear. Absence of an edge says nothing about
  ownership.
- Included entities are often listed by name only (180 of 530 on the candidate pages). Name edges
  are not verified by ABN or ACN; they need the ACECQA legal name and the ABR entity name to agree.
- Statements are self-reported and not checked for compliance by the register. A provider in a 2023
  statement may since have been sold; every edge carries its reporting period.
- Joint statements: a `reporting_entity` edge from a joint statement means co-reporting, not
  common ownership.
- Names that read as a person (for example some charities with two-word names) are withheld as
  `[withheld: may name an individual]` in group names and the review queue. Most are organisations.
- Licence unclear: the MSR shows "Copyright Attorney-General's Department" and no open licence.
  Raw MSR files and their sidecars stay in `data/raw/msr/` (gitignored). Only derived facts are
  committed. This note does not clear the licence under `.claude/rules/data-pipeline.md`; ask the
  Attorney-General's Department before any public display.

## Outputs

- `data/processed/provider-group-edges-msr.csv` (107 rows) and `.provenance.json`
- `data/processed/provider-group-review-msr.csv` (103 rows) and `.provenance.json`
- `data/processed/provider-group-edges-msr-summary.json` (counts, groups, all 136 candidates)

Rebuild offline: `python3 scrapers/build_msr_group_edges.py --no-fetch`.

## Open questions

1. Licence: will the Attorney-General's Department permit display of derived group links?
2. Should the 28 unique name matches to providers without an ABN become edges after ABN lookup?
3. Confirm the section 16 reading of "Included entities". `[Verify This]`
