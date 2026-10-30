# Ownership layer 1: provider groups from the Modern Slavery Register (2026-10-31)

Finding: 17 of the 1,210 priority providers (1.4%; 17 of the 901 with a resolved ABN) gained an
ownership edge (`controlled_entity_of`) from the Modern Slavery Statements Register (MSR). They roll
up to 8 groups and operate 254 of the 18,186 service approvals in the current ACECQA export
(1.4%). G8 Education accounts for 9 of the 17. Joint-statement rows (56) and group-head rows (2)
are recorded separately and are not ownership. Confidence: High for the counts as produced by the
script; Medium for what an edge means (see Definitions).

Serves GAP-003 (no public ownership graph). Written by the data-engineer spoke and reworked after
the hub gate on PR #5, which found the first version counted co-reporting and self links as
ownership. Script: `scrapers/build_msr_group_edges.py`; tests: `tests/test_msr_group_edges.py`.

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
| Services those providers operate | 254 | 18,186 current ACECQA services |
| `group_parent_self` relations / rows / providers | 3 / 2 / 2 | not ownership |
| Services of group-head providers | 298 | 18,186; not ownership |
| `co_reported_joint` rows / providers / statements | 56 / 25 / 23 | not ownership |
| Providers that appear only in joint statements | 21 | 25 |
| `self_report_no_included_entities` relations / providers | 25 / 6 | not ownership |
| Review queue rows | 103 | |

All 17 providers with an edge are priority providers. That follows from the method: every edge
needs a provider ABN or ABR name from `provider-abn.csv`, which covers only the priority subset.

### Groups

| Group (reporting entity) | Group key | Controlled providers | Their services | Head provider |
|---|---|---|---|---|
| G8 Education Limited | 95123828553 | 9 | 54 | PR-00000898 |
| SHEL Holdco Pty Limited | 68670538780 | 2 | 46 | none |
| Goodstart Early Learning Ltd | 69139967794 | 2 | 50 | none |
| The Corporation of the Synod of the Diocese of Brisbane | 32025287736 | 1 | 6 | none |
| The Uniting Church in Australia Property Trust (Victoria) | 39703442583 | 1 | 89 | none |
| MQ Health Pty Limited | 46141203125 | 1 | 4 | none |
| Christian Education Ministries Ltd | 65124826722 | 1 | 5 | none |
| Macquarie University | 90952801237 | 1 | 4 | none |

Goodstart's 2024 and 2025 statements give no ABN for the reporting entity. Its group key comes from
the same reporting entity's ABN on its other statements (`group_key_source`
`abn_of_same_name_on_another_statement`). G8 Education is the only group head with a matched
controlled provider. Wesley Community Services is a head whose one included entity matched no
provider.

## Joint statements for manual confirmation

Joint statements are never promoted to edges. Four list priority providers as included entities.
Two appear to be filed by a single corporate group and should be confirmed through another source
(for example ASIC extracts or company annual reports) before any ownership claim:

| Statement | Reporting entities | Included providers | Assessment |
|---|---|---|---|
| 2026-1450 (https://modernslaveryregister.gov.au/statements/29210/) | 4: Busy Bees Australia Bidco, Busy Bees Australia Holding, Busy Bees Early Learning Australia, Think Childcare Limited | 9 | One brand group on its face; confirm |
| 2023-2461 (https://modernslaveryregister.gov.au/statements/15563/) | 1: Goodstart Early Learning Ltd, typed Joint | 1 | Same provider already linked by Goodstart's later Single statements |
| 2024-1335 (https://modernslaveryregister.gov.au/statements/18637/) | 53 Catholic bodies, including universities, hospitals and cemetery trusts | 4 | Many separate bodies; not one group |
| 2025-1579 (https://modernslaveryregister.gov.au/statements/23594/) | 44 Catholic bodies | 5 | Many separate bodies; not one group |

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
   one ACECQA provider legal name and that provider's ABR entity name. Normalisation:
   `normalise_provider_name` in `scrapers/join_enforcement.py`.
5. Classification as in the Definitions table. Edges and heads are collapsed to one row per
   provider and group, taken from the latest statement, with `statement_ids` and `statement_urls`
   listing every statement.

## Review queue (103 rows)

| Reason | Rows |
|---|---|
| name_match_provider_abn_not_resolved (MSR gives an ABN; provider's ABN not resolved) | 63 |
| name_unique_provider_without_abn | 28 |
| fuzzy_corporate_suffix_differs | 9 |
| reporting_entity_name_only | 3 |

Most queue rows are operating subsidiaries outside the priority subset (for example G8 and Story
House centre companies). Resolving their ABNs with `scrapers/abn_lookup.py` would turn many into
ABN-backed matches. Confidence: Medium.

## Limits

- Coverage: the MSR covers entities with annual consolidated revenue of at least AUD 100 million,
  plus voluntary reporters. Absence of an edge says nothing about ownership.
- Name-matched edges (11 of 18) are not verified by ABN or ACN.
- Statements are self-reported. A provider in an older statement may since have changed hands;
  every edge lists all its statements and reporting periods.
- Names that read as a person are withheld as `[withheld: may name an individual]`. Most are
  organisations.
- Licence unclear: the MSR shows "Copyright Attorney-General's Department" and no open licence.
  Raw MSR files and their sidecars stay in `data/raw/msr/` (gitignored). Only derived facts are
  committed. This note does not clear the licence under `.claude/rules/data-pipeline.md`; ask the
  Attorney-General's Department before any public display.

## Outputs

- `data/processed/provider-group-edges-msr.csv` (18 rows, `controlled_entity_of` only)
- `data/processed/provider-group-heads-msr.csv` (2 rows)
- `data/processed/provider-coreported-msr.csv` (56 rows, caveat on every row)
- `data/processed/provider-group-review-msr.csv` (103 rows)
- Each with a `.provenance.json`, plus `data/processed/provider-group-edges-msr-summary.json`

Rebuild offline: `python3 scrapers/build_msr_group_edges.py --no-fetch`.

## Open questions

1. Licence: will the Attorney-General's Department permit display of derived group links?
2. Busy Bees statement 2026-1450: confirm the 9 included providers' ownership from another source.
3. Should the 28 unique name matches to providers without an ABN be looked up and re-run?
4. Confirm the section 16 reading of "Included entities". `[Verify This]`
