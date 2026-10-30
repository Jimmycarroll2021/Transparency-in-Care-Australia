# Ownership layer 1: provider groups from the Modern Slavery Register (2026-10-31)

Finding: 17 of the 1,210 priority providers (1.4%; 17 of the 901 with a resolved ABN) gained an
ownership edge (`controlled_entity_of`) from the Modern Slavery Statements Register (MSR). They roll
up to 8 groups and operate 254 of the 18,186 service approvals in the current ACECQA export
(1.4%). Nine of the 17 sit in one group (ABN 95123828553, ABR entity name G8 EDUCATION LIMITED).
Joint-statement rows (56) and group-head rows (2) are recorded separately and are not ownership.
Confidence: High for the counts as produced by the script; Medium for what an edge means (see
Definitions).

Serves GAP-003 (no public ownership graph). Written by the data-engineer spoke, reworked after the
hub gate and two Codex review rounds on PR #5. Script: `scrapers/build_msr_group_edges.py`; tests:
`tests/test_msr_group_edges.py`.

## Name policy

This note and every MSR output carry only two kinds of name:

1. Provider names from ACECQA (`provider_legal_name`, keyed by `provider_approval_number`).
   A provider is excluded, failing closed, when any local source marks it as an individual or
   sole trader: the ACECQA-derived profile (likely individual, unknown form or withheld name),
   `provider-abn.csv` (entity type IND, or the ABR lookup found an individual) or `abn-details.csv`.
   It is also excluded when the ABR sources disagree on its entity type. This run excluded 1,100
   providers on the profile, 0 on the ABR, with 0 type conflicts and 0 individual-status conflicts.
2. Group names from the ABR: the ABR entity name of the reporting entity's ABN. It is shown only
   when the ABR entity type for that ABN is held locally (`provider-abn.csv`, `abn-details.csv`),
   the sources agree, the type is a company (PRV, PUB), government entity or statutory authority
   (LGE, LGA, SGE, TGE), co-operative (COP) or other incorporated entity (OIE), and the name has no
   wording that can embed a person's name (family trust, trustee for, as trustee, ATF). Trusts,
   partnerships, unincorporated entities and any other type show the ABN and statement id only.

No name read from the register is published. Review, co-reported and summary rows carry statement
ids, URLs, ABNs and match methods only. The ABN Lookup API was not called for this layer.

## Definitions

Every provider named in a candidate statement is a relation. Each relation is classified into
exactly one class:

| Class | Rule | Ownership edge? | File |
|---|---|---|---|
| `controlled_entity_of` | The provider is an included entity in a Single statement (one reporting entity), matched by ABN or by name with ACECQA and ABR agreement | Yes, the only one | `provider-group-edges-msr.csv` |
| `group_parent_self` | The provider is the reporting entity of a Single statement that lists included entities | No: marks a group head | `provider-group-heads-msr.csv` |
| `co_reported_joint` | Any relation from a Joint statement | No: "joint statement: co-reporting, not evidence of ownership" | `provider-coreported-msr.csv` |
| `self_report_no_included_entities` | The provider is the reporting entity of a Single statement with no included entities | No | counted only |
| `unclassified_statement` | Any other statement type | No | counted only (0 this run) |

`controlled_entity_of` reads "included in the group's modern slavery statement as owned or
controlled by the reporting entity". That reading rests on the Modern Slavery Act 2018 (Cth),
which requires a statement to describe consultation with the entities the reporting entity owns or
controls (section 16), and on the register listing those entities as "Included entities".
`[Verify This]`: the register does not define the field on the pages read, and the section 16
reading has not been checked against the Act's text or departmental guidance. An edge is not a
verified ownership chain, shareholding or acquisition date.

## Counts (window and denominators)

Window: all-statements CSV captured 2026-10-30T19:32Z (UTC; 31 October in Canberra), 18,869
statement rows, all years. Statement pages captured 2026-10-30T19:32Z to 19:37Z. The latest
statements behind the 18 edges cover reporting periods from 1 January 2023 to 31 December 2025.

| Measure | Count | Denominator |
|---|---|---|
| Candidate statements (pages parsed) | 136 | 18,869 statement rows |
| Included entities parsed | 530 (350 with an ABN) | 136 pages |
| Provider-statement relations | 107 | |
| `controlled_entity_of` relations | 23 | 107 |
| `controlled_entity_of` edges (one per provider and group) | 18 | |
| of which latest match by ABN / by name with ABR agreement | 7 / 11 | 18 |
| Providers with an edge | 17 | 1,210 priority providers (901 with an ABN) |
| Groups they roll up to | 8 | |
| Group names shown (ABR type PUB) / ABN only (ABR type not held locally) | 2 / 6 | 8 groups |
| Services those providers operate | 254 | 18,186 current ACECQA services |
| `group_parent_self` rows / providers (both names shown) | 2 / 2 | not ownership |
| Services of group-head providers | 298 | 18,186; not ownership |
| `co_reported_joint` rows / providers / statements | 56 / 25 / 23 | not ownership |
| Providers whose only relations are joint | 21 | 25 |
| `self_report_no_included_entities` relations / providers | 25 / 6 | not ownership |
| Review queue rows | 103 | |

All 17 providers with an edge are priority providers. That follows from the method: every edge
needs a provider ABN or ABR name from `provider-abn.csv`, which covers only the priority subset.

### Groups

| Group name (ABR) | Group ABN | ABR type | Controlled providers (ACECQA) | Their services | Head provider |
|---|---|---|---|---|---|
| G8 EDUCATION LIMITED | 95123828553 | PUB | 9 | 54 | PR-00000898 |
| ABN only | 68670538780 | not held | 2: Story House Early Learning No 1 Pty Ltd, Story House Early Learning No 21 Pty Ltd | 46 | none |
| GOODSTART EARLY LEARNING LTD | 69139967794 | PUB | 2: BFS Children's Services Ltd, GOODSTART EARLY YEARS LIMITED | 50 | none |
| ABN only | 32025287736 | not held | 1: FSAC Ltd | 6 | none |
| ABN only | 39703442583 | not held | 1: UNITING (VICTORIA AND TASMANIA) LIMITED | 89 | none |
| ABN only | 46141203125 | not held | 1: U@MQ Ltd | 4 | none |
| ABN only | 65124826722 | not held | 1: SMARTPLAY EARLY LEARNERS PTY LTD | 5 | none |
| ABN only | 90952801237 | not held | 1: U@MQ Ltd | 4 | none |

The 2024 and 2025 statements behind group 69139967794 give no ABN for the reporting entity. The
key comes from the ABN given for the same reporting entity on its other statements, used only
because the ABR confirms it (entity type PUB, ABR entity name equal after normalisation;
`group_key_source` `abn_of_same_name_on_another_statement_abr_confirmed`). Looking up the ABR
entity type of the 6 ABN-only group ABNs would let their names be shown.

## Joint statements for manual confirmation

Joint statements are never promoted to edges. Four list priority providers as included entities.
Statement 2026-1450 looks like one corporate group's filing and should be confirmed through
another source (for example ASIC extracts or annual reports) before any ownership claim:

| Statement | Reporting entities | Included priority providers | Assessment |
|---|---|---|---|
| 2026-1450 (https://modernslaveryregister.gov.au/statements/29210/) | 4, no ABN given | 9, including Busy Bees Panania Pty Ltd, Busy Bees Cranbourne Pty Ltd and FEL Child Care Centres 1 Pty Ltd (ACECQA names) | Appears to be one group; confirm |
| 2023-2461 (https://modernslaveryregister.gov.au/statements/15563/) | 1 (ABN 69139967794), typed Joint | 1: GOODSTART EARLY YEARS LIMITED | Already linked by the same group's later Single statements |
| 2024-1335 (https://modernslaveryregister.gov.au/statements/18637/) | 53 | 4 | Many separate bodies; not one group |
| 2025-1579 (https://modernslaveryregister.gov.au/statements/23594/) | 44 | 5 | Many separate bodies; not one group |

## Method

1. The script reads https://modernslaveryregister.gov.au/resources/, finds the
   `all-statement-information_<date>.csv` link and downloads it. Columns: IDX, PeriodStart,
   PeriodEnd, Type, VoluntaryCompliance, HeadquarteredCountries, AnnualRevenue,
   ReportingEntities, IncludedEntities, ABN, ACN, ARBN, Link, IndustrySectors, RelatedStatements.
   No column holds an individual's name, so the privacy filter dropped none. The filter still runs
   on every download.
2. Candidates: any ABN in the CSV ABN column (reporting and included entities' ABNs) equals an ABN
   in `data/processed/provider-abn.csv` (60 statements), or the reporting entities' text contains
   early learning, childcare, child care, kindergarten or education (76).
3. Each candidate's statement page is fetched once with the project User-Agent, robots.txt honoured
   (it disallows only `/admin/`, `/statements/file/` and `/compliance/`), at least 2 s apart.
   Statement numbers (IDX) are not unique in the CSV (10 repeat), so the page id is the key.
4. Matching, strongest first, one relation per provider and statement: the entity's ABN equals a
   provider ABN; or an included entity listed without an ABN whose normalised name equals exactly
   one ACECQA provider legal name and that provider's ABR entity name. Names are used for matching
   only and are never written.
5. Classification as in the Definitions table. Edges and heads are collapsed to one row per
   provider and group, taken from the latest statement, with `statement_ids` and `statement_urls`
   listing every statement.

## Completeness checks

The run exits 2 and leaves every output unchanged when any of these happens:

- a candidate page is missing, or a fetch fails (always 2 with `--refresh`);
- a matching CSV row has no usable statement page id;
- an entity section holds any element or text that is not a recognised entity, or an entity has
  no name link;
- the CSV lists included entities but the page yields none;
- the page yields fewer included entities than a lower bound counted from the CSV
  IncludedEntities field. A comma-separated segment counts only when it ends with an ABN in
  brackets or a corporate suffix, because names can contain commas.

It exits 1 if nothing is usable. On the current snapshots every candidate passes. 38 list
included entities in both the CSV and the page, and 98 in neither. The lower bound equals the
page count for 37 of the 38 and is below it for 1. If `acecqa-services-latest.csv` is missing,
service counts are null (unknown), not zero.

## Review queue (103 rows)

| Reason | Rows |
|---|---|
| name_match_provider_abn_not_resolved (MSR gives an ABN; provider's ABN not resolved) | 63 |
| name_unique_provider_without_abn | 28 |
| fuzzy_corporate_suffix_differs | 9 |
| reporting_entity_name_only | 3 |

Rows carry the statement, the MSR-side ABN where given, the reason and candidate provider approval
numbers only. Resolving the candidates' ABNs with `scrapers/abn_lookup.py` would turn many into
ABN-backed matches. Confidence: Medium.

## Limits

- Coverage: the MSR covers entities with annual consolidated revenue of at least AUD 100 million,
  plus voluntary reporters. Absence of an edge says nothing about ownership.
- Name-matched edges (11 of 18) are not verified by ABN or ACN.
- Statements are self-reported. A provider in an older statement may since have changed hands;
  every edge lists all its statements and reporting periods.
- Licence unclear: the MSR shows "Copyright Attorney-General's Department" and no open licence.
  Raw MSR files and their sidecars stay in `data/raw/msr/` (gitignored). Only derived facts are
  committed. This note does not clear the licence under `.claude/rules/data-pipeline.md`; ask the
  Attorney-General's Department before any public display.
- Earlier commits on this branch published names taken from the register, which the current
  policy does not allow. They remain in the public branch history; see the PR for counts.

## Outputs

- `data/processed/provider-group-edges-msr.csv` (18 rows, `controlled_entity_of` only)
- `data/processed/provider-group-heads-msr.csv` (2 rows)
- `data/processed/provider-coreported-msr.csv` (56 rows, caveat on every row)
- `data/processed/provider-group-review-msr.csv` (103 rows)
- Each with a `.provenance.json`, plus `data/processed/provider-group-edges-msr-summary.json`

Rebuild offline: `python3 scrapers/build_msr_group_edges.py --no-fetch`. `--refresh` takes a new
snapshot of every candidate page beside the old ones.

## Open questions

1. Licence: will the Attorney-General's Department permit display of derived group links?
2. Statement 2026-1450: confirm the 9 included providers' ownership from another source.
3. Look up the ABR entity type of the 6 ABN-only group ABNs so their names can be shown?
4. Should the 28 unique name matches to providers without an ABN be looked up and re-run?
5. History: earlier commits expose names taken from the register; rewriting history is the
   owner's decision.
6. Confirm the section 16 reading of "Included entities". `[Verify This]`
