# Transparency in Care Australia

A public-interest project investigating whether Australia's childcare regulatory data can be
joined into a single, honest, longitudinal record — and whether that is legally possible.

## Status

Research phase. No build decision taken.

## Documents

- [`docs/01-gap-analysis.md`](docs/01-gap-analysis.md) — what the Four Corners investigations found,
  a full inventory of public childcare data sources, the seven real gaps, the licensing blocker,
  and a recommendation.
- [`docs/02-execution-plan.md`](docs/02-execution-plan.md): phases, workstreams, who does what,
  and the five things only a human can do.
- [`docs/02-acecqa-consent-request.md`](docs/02-acecqa-consent-request.md): the consent letter to
  ACECQA, ready to send.
- `research/`: dated spoke audits of every public register (format, join keys, licence, window).

## Short version

Service discovery and quality ratings are already solved by StartingBlocks.gov.au. The real gaps
are the *join* (enforcement data fragmented across eight jurisdictions in PDFs and HTML), the
*history* (everything is published as current state only), the *ownership graph* (no way to see
every service a corporate group runs), and the *blind spot* (473 services outside the National
Quality Framework with no public quality data at all).

The hard blocker is licensing, not engineering. ACECQA's terms of use prohibit using their content
"as the source of quality rating data for regulated services". That needs written consent before
anything ships.

## Working with Claude Code

The repo is set up for Claude Code with a hub-and-spoke model. Start Claude Code at the repo root
and accept the workspace trust prompt once.

- `CLAUDE.md`: project rules, current phase and delegation table
- `.claude/agents/`: `source-researcher`, `register-auditor`, `gap-analyzer`, `data-engineer`
- `.claude/skills/`: `/validate-gap [GAP-001|all]` and `/source-check <file>`
- `.claude/rules/`: path-scoped rules for the data pipeline and for public content
- `.claude/hooks/`: blocks edits to `data/raw/` and `data/evidence/`, formats Python with ruff,
  and validates `data/gap-ledger.json` on every edit. Test with `bash .claude/hooks/test_hooks.sh`
- `data/gap-ledger.json`: the seven gaps from the gap analysis, all at `hypothesis`

First run: `/validate-gap all`
