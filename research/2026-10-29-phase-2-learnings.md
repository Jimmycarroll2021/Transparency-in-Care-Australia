# Phase 2 learnings (29 October 2026)

What was built in the first Phase 2 pass, what the data says, and what changes the plan.

## Built today

| Script | Source | Captured | Rows | Join key present |
|---|---|---|---|---|
| `snapshot_acecqa_registers.py` | ACECQA national services and providers CSV | 2 files, last-modified 28 Oct 2026 | 18,186 services, 10,073 providers | SE- and PR- on every row |
| `parse_nsw_enforcement.py` | NSW register, 21 quarterly PDFs, Jan 2025 to Jun 2026 | 21 PDFs | 1,738 actions | SE- on service rows, PR- on provider rows |
| `parse_vecra_enforcement.py` | VECRA monthly HTML, Jan to Aug 2026, plus summary table | 5 pages | 132 actions, 99 count rows | SE- and PR- |
| `parse_qld_enforcement.py` | Queensland register HTML, 2017 to 2026 | 1 page | 69 actions | none printed |
| `parse_cth_ccs_enforcement.py` | Commonwealth CCS register | none, site refuses connections | 0 | unknown |
| `profile_providers.py` | ACECQA providers joined to services | derived | 10,073 providers | PR- |

Full test suite: 142 tests. CI runs ruff, the ledger validator, the hook tests and pytest on every push.

## What the data says

1. **NSW publishes far more than the others.** 1,738 actions over six quarters against 132 for
   Victoria over eight months and 69 for Queensland over nine years. This is a difference in what
   is published, not necessarily in what happened. Any cross-state comparison must say so.
2. **Victoria's published rows are a small subset of its actions.** August 2026: 19 rows published
   against 394 actions in the summary table, because caution letters and compliance report letters
   (about 360) are counted but never itemised. The denominator table captures this; the published
   list cannot be presented as a count of all actions.
3. **Queensland cannot be joined by key.** No SE- or PR- numbers on the register. Joining needs
   name and address matching against the ACECQA register, with a precision caveat on every row.
4. **Provider structure.** Companies hold 54.1 per cent of services. 146 providers operate in more
   than one state; 75 operate 25 or more services. The five largest by service count are Goodstart
   Early Learning Ltd (609), TheirCare Pty Ltd (503), Camp Australia Pty Limited (388), the South
   Australian Department for Education (382) and TEAM HOLIDAY PTY LTD (281). Neither ACECQA export
   carries management type; entity form is inferred from the legal name and is a heuristic.
5. **2,871 providers have no service row.** Approval held with no active service, or an export
   gap. Needs a register-auditor check before any provider count is published.

## Individuals at ingest

Three parsers and the profiler withhold names that look like natural persons: 751 likely
individual providers in the ACECQA profile, 112 provider names in NSW, 9 in Victoria, 20 rows in
Queensland. All use keyword heuristics (an organisation word keeps the name; none withholds it).
Over-withholding is the chosen failure direction. A human spot check of the withheld and the
`unknown` buckets is needed before any public use, and the `source_document` links for Queensland
individuals are replaced by the register page because the file names embed names.

## What changed the plan

- **Processed tables are not committed when large.** The two ACECQA latest tables (16 MB,
  rewritten daily) are gitignored; provenance files are kept. Raw gzip snapshots are committed
  (about 2.5 MB a day). Review at 500 MB.
- **Two hosts refuse the cloud environment entirely.** education.gov.au (Commonwealth register)
  closes connections; data.gov.au (ABR bulk extract) disallows all agents in robots.txt and the
  collector honours that. Both need a different route: the owner's own machine over Remote
  Control, a manual browser save handed to a snapshot script, or written permission.
- **VECRA's archive (2020 to 2025) is PDF and Word under a robots.txt disallow.** 14 files. Ask
  VECRA, or accept the 2026-only window for Victoria.
- **Duplicate rows share a record_id** in NSW (12 exact duplicates, 1,726 unique ids for 1,738
  rows). Add an occurrence index to the hash before any join.
- **Revised PDFs would double-count.** If NSW re-issues a quarterly PDF, both versions will be
  parsed. A latest-snapshot-per-URL rule is needed in the NSW parser.
- **Two malformed keys in NSW**: a seven-digit SE- value and a PR- value with a stray suffix. Both
  kept raw with null normalised key rather than guessed.

## Join results (added later the same day)

`scrapers/join_enforcement.py` stacks every `*-enforcement-actions.csv` onto the ACECQA spine.
2,175 action rows in; 64.0 per cent joined. By jurisdiction: NSW 72.5 per cent (1,260 of 1,738,
all by exact key), Victoria 89.4 per cent (118 of 132), Queensland 20.3 per cent (14 of 69, name
match only), Commonwealth 0 per cent (236 rows, no SE-/PR- keys printed; ABN on 64 rows is the
only identifier). Window: 24 months to 28 October 2026. Services with at least one joined action
in the window: 875 of 18,186. Providers: 593 of 10,073.

The Commonwealth parser was rewritten against the real pages the owner saved from a browser:
236 rows (149 current, 87 past), 226 CCS sanctions and 10 criminal outcomes, 64 rows withheld as
individuals.

What the join taught us:

- **About 490 NSW and Victorian rows carry keys absent from the live ACECQA register**, mostly
  cancellations. The likely cause is that cancelled approvals drop off the register [Verify This].
  This is exactly why the daily snapshot matters: a key that vanishes tomorrow is still in
  yesterday's file. Re-run the join against the earliest snapshot once a few weeks exist.
- **Queensland and the Commonwealth need a provider-name match** (unique, normalised, never for
  withheld providers) to lift their join rates. Not built yet.
- **Rates need care.** The report divides 24-month actions by the provider's current service
  count. Both lists in `enforcement-join-report.json` are internal only until the legal review.
- **Duplicates in source** (19 rows) are kept, numbered by `occurrence`, and excluded from counts.

## South Australia and the provider-name stage (later the same day)

- `parse_sa_enforcement.py`: 12 ESB register pages (current plus 2013 to 2022-23), 436 rows,
  SE- on 262 and PR- on 322. Pre-2022 pages print no keys. The page slugged 2022-23 actually
  holds 303 entries dated to October 2026 [Verify This]. The yearly summary table (681 actions in
  2025-26 against 45 published current entries) is the denominator; published rows are a subset.
- Provider-name stage in the join (unique normalised legal or trading name within state, never on
  withheld rows, never where a key is printed): Commonwealth 0 to 28.4 per cent, Queensland 20.3
  to 47.8 per cent. SA joined 82.8 per cent on first run.
- Overall: 2,611 actions across five jurisdictions, 70.4 per cent joined. 1,072 of 18,186
  services and 730 of 10,073 providers have at least one joined action in the 24 months to
  28 October 2026.
- Queensland prints no location at all; its suburb stays null by design rather than inferred
  from a place word in the service name.

## Next

1. Join: `scrapers/join_enforcement.py` that stacks the four jurisdiction tables, attaches the
   ACECQA service and provider rows by SE-/PR-, and reports match rates. Queensland by name match
   with a flag.
2. Owner tasks: run `parse_cth_ccs_enforcement.py` and the ABR download from a residential
   connection; register for an ABN Lookup GUID; spot-check the withheld-name buckets.
3. Remaining jurisdictions: SA (keys present, all rights reserved), WA, Tasmania, NT, ACT.
