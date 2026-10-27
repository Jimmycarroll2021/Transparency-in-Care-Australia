---
name: validate-gap
description: Runs the Phase 1 gap validation loop for one or all gaps in data/gap-ledger.json, using the source-researcher, register-auditor and gap-analyzer subagents. Use when asked to validate, test or update a transparency gap.
argument-hint: "[GAP-001 | all]"
---

# Validate a transparency gap

Target: $ARGUMENTS (if empty, use every gap with status `hypothesis`).

You are the hub. Do not read large web pages or datasets yourself.

1. **Read the ledger.** Open `data/gap-ledger.json`. For each target gap, list its
   `open_questions` and `next_action`.
2. **Dispatch research in parallel.** For each gap, send the questions to the spoke named in
   `next_action` (`source-researcher` or `register-auditor`). Give each one the gap ID, the exact
   questions and the URLs already in the ledger. Send independent spokes in the same turn.
3. **Check the returns.** For each envelope, spot-check one or two key claims yourself by opening
   the cited source. Discard any claim you cannot confirm.
4. **Dispatch `gap-analyzer`** once per gap, with the gap ID and the paths of the research notes.
5. **Validate.** Run `python3 .claude/hooks/validate_ledger.py data/gap-ledger.json`.
6. **Report** in this format:

| Gap | Old status | New status | Confidence | Tractability | Why |
|---|---|---|---|---|---|

Then state the one gap with the best ratio of public value to effort, and the next concrete action
for it. If no gap is `validated`, say so plainly.
