# Transparency in Care Australia

Public-interest, non-commercial project. Goal: find out whether a real transparency gap exists in
Australian childcare regulatory data, and if it does, close it with a site that publishes verified
regulatory facts.

## Current phase

**Phase 4: Ownership graph.** Phases 2 and 3 are on `main` (merged 2026-10-29): daily ACECQA
snapshots, enforcement parsers for NSW, VIC, QLD, SA, WA, TAS and the Commonwealth, and the national
join (`scrapers/join_enforcement.py`). Phase 2 gate: GAP-001, 002, 003, 005 and 007 validated.

**Licence position (corrected 2026-10-30): ACECQA consent is NOT yet held.** The consent request
was sent on 2026-10-30 (`docs/02-acecqa-consent-request.md`); no reply yet. Until a written yes is
saved to `data/evidence/` by script: do not display ACECQA ratings on any public site; ACECQA
data is used for non-commercial research only; if ACECQA asks, remove stored copies from public
view the same day. NSW and VECRA data are CC BY 4.0; SA ESB is all rights reserved; WA is
non-commercial only. An earlier note that consent was held was wrong.

Decision 2026-10-30: the owner keeps the repository public while the ACECQA request is pending,
including the committed ACECQA snapshots. The letter disclosed this and offered same-day removal
from public view if ACECQA asks. Do not re-raise unless ACECQA replies or the facts change.

Phase 4 scope: ABN Lookup web services (GUID in `.env`, never committed or logged), provider to ABN
resolution, and provider groups by shared ABN or ACN. Parent and subsidiary links are not in free ABR
data. Raw ABR responses are a local cache only (`data/raw/abr-lookup/` is gitignored) because
candidate lists can contain individuals' names. No public site yet (Phase 5, after legal review).

Phase plan:
1. Gap validation (now): `/validate-gap`
2. Licence consent and archive: daily ACECQA register snapshot, consent letter to ACECQA
3. Parsers and joins: state enforcement registers onto the ACECQA service approval number
4. Ownership graph: ACECQA providers joined to ABN/ASIC
5. Public site: only after legal review

Key document: `docs/01-gap-analysis.md` (read it before any gap work; do not paste it into chat).

## Hub and spoke

The main session is the hub. It plans, delegates, reviews and decides. It does not read raw
datasets, long transcripts or large web pages itself.

| Task | Spoke (subagent) |
|---|---|
| Media, inquiry, Senate estimates and transcript research | `source-researcher` |
| What a public register publishes, its format, licence, update cadence | `register-auditor` |
| Testing a gap against evidence, updating the ledger | `gap-analyzer` |
| Parsers, snapshot jobs, data joins (Phase 2 onward only) | `data-engineer` |

Delegation rules:
- Pass each spoke the exact URLs, IDs, file paths and question. Spokes start with no memory of this
  conversation.
- Spokes return a short JSON envelope (`status`, `summary`, `files_written`, `open_questions`),
  never raw dumps.
- Run independent spokes in parallel.
- The hub verifies a spoke's key claims before they go into the ledger or a public output.

## Non-negotiable rules

1. **Primary sources only for published facts.** Every public claim cites an official record:
   service approval number (`SE-`), provider approval number (`PR-`), register URL and capture date.
   Media reporting is context for research, never the basis of a published claim about a named
   service or provider.
2. **Never name individuals.** No children, families, educators or non-executive staff. Suppression
   orders and child protection law apply. Provider entities and approved services only.
3. **Never invent or approximate** approval numbers, ratings, dates, counts or enforcement actions.
   If a value is not in a source, it is `null` with a note.
4. **Raw data is immutable.** `data/raw/` and `data/evidence/` are written only by scripts, as
   timestamped snapshots. A hook blocks Claude from editing or deleting them.
5. **Counts need a denominator and a window.** Never publish '12 breaches' alone.
6. **Distinguish** breach, confirmed breach, enforcement action, prosecution and conviction. They
   are different things.
7. **Absence of a flag is not evidence of safety.** Say so wherever flags are shown.
8. **Respect licences.** ACECQA content is not openly licensed. No public republication of ACECQA
   ratings without written consent. Check each source's terms before ingesting it.
9. **Mark uncertainty.** Use `[Verify This]` and High / Medium / Low confidence in research notes.

## Layout

```
docs/                 Research briefs (01-gap-analysis.md is the baseline)
research/             Spoke outputs: dated notes, one topic per file
data/raw/             Immutable source snapshots (scripts only)
data/evidence/        Immutable saved copies of primary records (scripts only)
data/processed/       Derived, reproducible outputs
data/schemas/         JSON schemas
data/gap-ledger.json  The gap register; schema in data/schemas/gap-ledger.schema.json
scrapers/             Collection scripts (Phase 2 onward)
.claude/              Agents, skills, rules, hooks, settings
```

## Commands

- Validate the gap ledger: `python3 .claude/hooks/validate_ledger.py data/gap-ledger.json`
- Test the hooks: `bash .claude/hooks/test_hooks.sh`
- Snapshot ACECQA registers: `python3 scrapers/snapshot_acecqa_registers.py`
- Parse VECRA enforcement actions: `python3 scrapers/parse_vecra_enforcement.py`
- Profile providers: `python3 scrapers/profile_providers.py`
- Parse Queensland enforcement register: `python3 scrapers/parse_qld_enforcement.py`
- Parse Commonwealth CCS enforcement register: `python3 scrapers/parse_cth_ccs_enforcement.py --current-file F --past-file G` (education.gov.au drops non-browser clients: save both pages from a browser; `--skip-fetch` re-parses the newest snapshots)
- Parse NSW enforcement register: `python3 scrapers/parse_nsw_enforcement.py`
- Join enforcement onto the ACECQA spine: `python3 scrapers/join_enforcement.py` (needs TICA_JOIN_KEY in .env for the keyed-name stage, which matches names withheld by the shared fail-closed rule on keyed hashes kept in gitignored `data/private/name-keys/`; `--no-keyed-join` joins without it, with fewer joins)
- Re-parse every enforcement register offline and rejoin: `python3 scrapers/reparse_offline.py` (all or nothing; refuses to start without TICA_JOIN_KEY unless `--no-keyed-join`)
- Parse SA enforcement register: `python3 scrapers/parse_sa_enforcement.py`
- Parse WA enforcement register: `python3 scrapers/parse_wa_enforcement.py` (needs `pip install playwright && playwright install chromium`; the ECRU register is a Caspio search form with no static page)
- Resolve ABNs (needs ABN_LOOKUP_GUID in .env): `python3 scrapers/abn_lookup.py` (stage A: Commonwealth ABNs to `abn-details.csv`; `abn <ABN>` or `name "<name>" --state NSW` for single lookups; `--offline` uses the local cache)
- Build provider groups: `python3 scrapers/build_provider_groups.py` (stage B providers to ABN, capped by `--max-calls`, default 1500; `--skip-lookup` rebuilds groups from `provider-abn.csv`)
- Build group edges from the Modern Slavery Register: `python3 scrapers/build_msr_group_edges.py` (statement pages at least 2 s apart; raw MSR files stay in gitignored `data/raw/msr/`; `--no-fetch` rebuilds from local snapshots; `--refresh` re-snapshots pages; exit 2 leaves outputs unchanged when a page is missing)

Add commands here only once the script exists.

## Writing style

British English. Plain language. No em dashes or en dashes. Lead with the finding.

## Compaction

When compacting, keep: current phase, ledger gap IDs and their statuses, sources already checked,
open questions, and any licensing or legal decisions made.
