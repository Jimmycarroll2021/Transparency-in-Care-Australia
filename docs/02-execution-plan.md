# Execution plan

**Date:** 29 October 2026
**Owner:** project owner (hub session is Claude Code; spokes are subagents)
**Read first:** `CLAUDE.md` (phase gate and delegation table), `docs/01-gap-analysis.md`

## The one-line plan

Validate the gaps against primary sources, get the licensing answer, start the history archive the
day it is permitted, then build the join and the ownership graph. A public site is the last step,
not the first.

## Phase gate (from CLAUDE.md)

Phase 2 does not start until both are true:

1. `data/gap-ledger.json` has at least one gap at `status: "validated"` (needs official evidence,
   enforced by the validator).
2. The ACECQA licensing question is answered. "Answered" means one of: written consent received;
   written refusal received (then the design excludes ACECQA content); or 30 business days with no
   reply, at which point the owner decides whether to proceed with non-ACECQA sources only.

Cost of the gate: every day without a register snapshot is a day of history lost. Mitigation: the
consent letter goes out now, not after validation.

**Gate passed 29 October 2026.** Five gaps validated; the owner has stated consent is held from
ACECQA and the other data owners. Phase 2 started the same day.

### Phase 2 decisions

- Snapshots are gzip-compressed CSVs committed to this repository under `data/raw/`, about 2.5 MB
  a day for the two ACECQA files. Review storage when `data/raw/` passes 500 MB (roughly six
  months): move older snapshots to release assets or object storage, keep the sidecar metadata in
  the repository.
- Shared helpers live in `scrapers/common.py`: polite fetch with robots.txt and crawl delay, one
  named User-Agent, immutable timestamped snapshots with sidecar metadata, SE-/PR- normalisation,
  processed outputs with provenance.
- One schema for every enforcement register: `data/schemas/enforcement-action.schema.json`.
  Parsers map printed action names to a small enum and keep the raw text; anything unsure is
  `other`.
- One `data-engineer` spoke per source, in parallel, each owning its own `scrapers/parse_*.py`,
  `data/raw/<source>/` and `tests/test_*.py`.
- CI (`.github/workflows/checks.yml`): ruff, ledger validator, hook tests, pytest on every push.

## Workstreams and who does them

| ID | Workstream | Phase | Owner | Depends on |
|---|---|---|---|---|
| W1 | Validate the seven gaps (`/validate-gap all`) | 1 | Hub dispatches `register-auditor`, `source-researcher`, then `gap-analyzer` | nothing |
| W2 | ACECQA consent letter | 1 | Hub drafts (`docs/02-acecqa-consent-request.md`); **owner sends** | nothing |
| W3 | Licence matrix for every non-ACECQA source | 1 | `register-auditor` (part of W1) | nothing |
| W4 | Daily register archive (ACECQA services and providers CSV) | 2 | `data-engineer` builds; GitHub Actions runs | W2 answered, W3 note clearing the source |
| W5 | Enforcement parsers: NSW PDF, VECRA HTML, QLD, Commonwealth, then the other five | 2 | `data-engineer`, one parser per spoke, in parallel | W3 licence cleared per source |
| W6 | Join enforcement onto SE- / PR- keys; processed tables with provenance | 3 | `data-engineer` | W4, W5 |
| W7 | Ownership graph: ACECQA providers to ABN (ABR bulk extract, CC BY) | 4 | `data-engineer` | W4 (provider register), W1 answer on ABN field |
| W8 | Non-NQF services list (the 473) from state registers | 2 | `register-auditor` then `data-engineer` | W1 GAP-004 result |
| W9 | Legal review: defamation, child protection, privacy | 5 | **Owner engages a lawyer** | W6 output to review against |
| W10 | Public site | 5 | Hub plus `data-engineer`; `/source-check` on every page | W9 |

## What only a human can do

These are the owner's tasks. Nothing on this list can be delegated to an agent.

1. **Send the ACECQA letter** (W2). Draft is ready in `docs/02-acecqa-consent-request.md`.
2. **Register for ABN Lookup web services** at https://abr.business.gov.au (free; a GUID arrives
   by email). Needed for W7 name-to-ABN resolution beyond the weekly bulk extract.
3. **Decide where private snapshots live** before W4. The repository is public, so ACECQA CSVs
   cannot be committed to it before consent. Recommended: a separate private GitHub repository
   written to by the Action through a fine-grained token stored as a secret. Alternative: a
   private Supabase storage bucket (the owner already runs Supabase projects in ap-southeast-2).
4. **Confirm the Action can reach ACECQA.** This environment gets HTTP 403 from
   www.acecqa.gov.au. GitHub-hosted runners may too. If so, the fallback is to run the snapshot
   script on the owner's own machine (Remote Control, or a plain cron job) on a residential
   connection, with the same script. Design W4 so it runs anywhere.
5. **Engage an Australian defamation lawyer** before W10. Not optional.

## How the hub delegates

- One spoke per independent question, launched in the same turn, each told the exact URLs, gap
  IDs and the output file path. Spokes write to `research/` and return a short JSON envelope.
- The hub spot-checks at least one key claim per envelope against the cited source before it goes
  into the ledger.
- `gap-analyzer` runs once for all gaps, sequentially within one spoke, because it edits a single
  file (`data/gap-ledger.json`) and parallel editors would conflict.
- `data-engineer` spokes are only dispatched once the phase gate is passed and the source has a
  licence-clearing note in `research/`. Each spoke owns one source directory under `scrapers/`
  and `data/raw/<source>/`, so parallel spokes never touch the same files.
- Spokes never commit. The hub reviews the diff, runs the validator and hook tests, and commits.

## Learning loop

Each phase ends with a short note in `research/` recording what was learned that changes the plan:
a source that turned out not to carry a join key, a licence that is friendlier than expected, a
fetch that is blocked. The ledger's `open_questions` fields are the backlog. CLAUDE.md "Current
phase" is updated at every gate.

## Verification

- `python3 .claude/hooks/validate_ledger.py data/gap-ledger.json` exits 0.
- `bash .claude/hooks/test_hooks.sh` passes.
- Every `research/` note has a summary table first, cites URLs, and contains no em or en dashes
  and no individual names (`/source-check <file>`).
- Phase 2 and later: each scraper writes a new timestamped file under `data/raw/<source>/` and
  never modifies an existing one; every processed table lists its raw inputs.

## Next concrete action

Send the ACECQA letter. Everything else in Phase 1 is already running.
