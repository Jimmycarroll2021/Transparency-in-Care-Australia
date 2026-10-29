# Transparency in Care Australia

Public-interest, non-commercial project. Goal: find out whether a real transparency gap exists in
Australian childcare regulatory data, and if it does, close it with a site that publishes verified
regulatory facts.

## Current phase

**Phase 2: Archive and parsers.** Gate passed 2026-10-29. Condition 1: GAP-001, 002, 003, 005
and 007 validated (`research/2026-10-29-phase-1-learnings.md`). Condition 2: the project owner
has stated that consent has been obtained from ACECQA and the other data owners for the uses in
`docs/02-acecqa-consent-request.md`. Save each written reply to `data/evidence/` by script.
Execution plan: `docs/02-execution-plan.md`.

Phase 2 scope: daily ACECQA register snapshots, enforcement parsers for NSW, Victoria, Queensland
and the Commonwealth, shared helpers in `scrapers/common.py`, and the enforcement action schema in
`data/schemas/enforcement-action.schema.json`. No public site yet (Phase 5, after legal review).

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

Add commands here only once the script exists.

## Writing style

British English. Plain language. No em dashes or en dashes. Lead with the finding.

## Compaction

When compacting, keep: current phase, ledger gap IDs and their statuses, sources already checked,
open questions, and any licensing or legal decisions made.
