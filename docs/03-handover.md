# Handover

**Date:** 30 October 2026
**From:** the first build team (owner plus a Claude Code hub session)
**To:** the incoming agentic team
**Read with:** `CLAUDE.md` (rules, phase, commands) and `docs/01-gap-analysis.md` (why this exists)

## In one paragraph

The project joins every published Australian childcare enforcement register onto the ACECQA
national register, so one service or provider can be seen across all regulators over time. Data
collection and joining work: 3,543 enforcement actions from seven regulators, 91.5 per cent joined,
every unmatched row explained. Phase 4 (ownership) is partly done: 901 providers resolved to an
ABN. There is **no public website**, and there must not be one until a legal review and ACECQA's
written consent. The work in flight is on PR #3.

## 1. Where things are

| Thing | Location |
|---|---|
| Repository | https://github.com/Jimmycarroll2021/Transparency-in-Care-Australia (public, by the owner's decision) |
| Default branch | `main`: Phases 1 to 3, merged 29 October 2026 |
| Work in flight | PR #3, branch `ccr-182a6719-4x23xl`: Phase 4, the corrected licence record, the README rewrite and this handover. CI green. **Merge it first.** |
| Owner's local copy | `C:\Users\Jimmy\Transparency-in-Care-Australia` (Windows, Python 3.10). Switch to `main` and pull after PR #3 merges. |
| Rules and phase | `CLAUDE.md`. The nine non-negotiable rules there bind every agent. |
| Gap register | `data/gap-ledger.json` |
| Source audits | `research/2026-10-29-*.md`, `research/2026-10-30-register-abn-lookup.md` |
| What we learnt | `research/2026-10-29-phase-1-learnings.md`, `research/2026-10-29-phase-2-learnings.md` |

## 2. State as of 30 October 2026

**Gaps** (`data/gap-ledger.json`): GAP-001, 002, 003, 005 and 007 validated on official evidence.
GAP-004 (non-NQF services; the 473 figure traces only to ABC reporting) and GAP-006 (rating age)
are still hypotheses.

**Enforcement join** (`data/processed/enforcement-join-report.json`):

| Jurisdiction | Rows | Joined | Notes |
|---|---|---|---|
| NSW | 1,738 | 99.9% | Quarterly PDFs from January 2025. Most joins by printed key. |
| WA | 931 | 96.8% | Caspio search form, read with headless Chromium under the project's named User-Agent. |
| SA | 436 | 84.9% | ESB current and historical pages. Pages before 2022 print no keys. |
| CTH | 236 | 29.2% | No approval keys printed. Joined by ABN and unique provider name only. |
| VIC | 132 | 100% | Monthly pages, 2026 only. The 2020 to 2025 archive is blocked by robots.txt. |
| QLD | 69 | 47.8% | No keys and no locations printed. Name match only. |
| TAS | 1 | 100% | |
| NT, ACT | 0 | | NT publishes none; the ACT has no register. Both verified. |

Rows whose printed key is missing from today's ACECQA export (mostly ceased approvals) join to
stub records in `data/processed/spine-unlisted.csv`, which are kept out of the live denominators.
Each of the 301 unmatched rows carries one stated reason in the report.

**Ownership (Phase 4):** 901 of the 1,210 priority providers have an ABN
(`data/processed/provider-abn.csv`). No two provider approvals share an ABN or ACN, because ACECQA
gives each legal entity one approval. Parent and subsidiary ownership therefore needs paid ASIC
extracts. Free ABR data cannot show it.

**Quality:** 282 tests; ruff clean; CI on every push.

## 3. Licence and legal position (read before touching data)

- **ACECQA consent is not held.** The request went to copyright@acecqa.gov.au on 30 October 2026
  from jimmisound@gmail.com (subject begins "Request for written consent under ACECQA Terms of
  Use"). It disclosed that daily downloads began on 29 October and that copies sit in this public
  repository, and it offered same-day removal if asked. No reply yet.
- **Until a written yes:** research use only; no public display of ACECQA ratings. If ACECQA asks,
  remove the stored copies from public view the same day. Save any reply to `data/evidence/` by
  script.
- **Follow-up due 21 November 2026** if there is no reply. A reminder was scheduled from the old
  cloud session and will not reach you. Put it in your own calendar.
- **Other sources:** NSW and VECRA are CC BY 4.0. SA ESB is all rights reserved and WA is
  non-commercial; both are used for non-commercial research. The ABN Lookup Web Services
  Agreement allows use and extracts to third parties, but records withdrawn for privacy must be
  deleted on notice.
- **Owner decision, 30 October 2026:** keep the repository public. Do not re-raise it unless
  ACECQA replies or the facts change.
- **Before any public site:** an Australian defamation, child protection and privacy review is
  mandatory (Phase 5). Nothing published yet has had legal review.

## 4. Running it

On Windows use `python`; on Linux or macOS use `python3`.

```
pip install -r requirements.txt
python scrapers/snapshot_acecqa_registers.py --no-fetch   # REQUIRED after a fresh clone
python scrapers/join_enforcement.py
python -m pytest -q
ruff check scrapers tests
```

**Gotcha:** the two large `acecqa-*-latest.csv` tables are gitignored. A fresh clone has only the
compressed raw snapshots, so `--no-fetch` must rebuild the tables before the join will run.

**Collection** (full list in the `CLAUDE.md` commands section):

| Source | How | Automated? |
|---|---|---|
| ACECQA registers | `snapshot_acecqa_registers.py`, daily via `.github/workflows/snapshot-acecqa.yml` at 19:15 UTC | **Yes.** First automated commit on 29 Oct (`221d8af`). Check the Actions tab. If GitHub's runners start getting 403s, run it locally. |
| NSW, VIC, QLD, SA, TAS | `parse_<state>_enforcement.py` (`--skip-fetch` re-parses snapshots) | No. Run monthly. |
| WA | `parse_wa_enforcement.py`, after `pip install playwright` then `playwright install chromium` | No |
| Commonwealth | Save both register pages from a **browser** (education.gov.au drops scripts), then run `parse_cth_ccs_enforcement.py --current-file F --past-file G` | No. Manual by design. |
| ABN Lookup | `abn_lookup.py` and `build_provider_groups.py`. They need `ABN_LOOKUP_GUID` in `.env` | No |

**Secrets:** the ABN Lookup GUID is in the ABR email to jimmisound@gmail.com (registration
reference ABNL33777). Put it in a local `.env` as `ABN_LOOKUP_GUID=...`. `.env` is gitignored;
never commit it, log it or paste it into a chat. The raw ABR response cache
(`data/raw/abr-lookup/`) is gitignored and was not carried over, so re-running stage B costs API
calls. The committed `provider-abn.csv` and `abn-details.csv` are enough for the join.

## 5. Open work, in priority order

**Needs a human (the owner):**
1. Merge PR #3.
2. Watch for ACECQA's reply; follow up on 21 November if there is none.
3. Book the legal review before any public output.
4. Review the withheld-name and `unknown` entity buckets by hand. The individual-detection
   heuristics deliberately over-withhold, and no test can prove a name was not missed.
5. Decide whether to buy ASIC extracts to answer real ownership (parent and subsidiary).

**Can be delegated to agents:**
6. Watch the daily snapshot job. Re-run the join every few weeks so that keys of ceased approvals
   resolve against older snapshots.
7. GAP-004 and GAP-006: trace the non-NQF figures to an official source; decide whether rating age
   is a real gap or a presentation issue.
8. Data quality:
   - WA name fields sometimes carry address text or key fragments.
   - NSW has two malformed printed keys.
   - NSW needs a "latest snapshot per URL" rule so a re-issued PDF is not double counted.
   - The SA page slugged "2022-23" holds entries up to October 2026.
   - Ask VECRA for its 2020 to 2025 archive.
9. Wider ABN coverage: download the ABR bulk extract from data.gov.au in a browser (CC BY 3.0 AU;
   its robots.txt blocks scripts) and match all 10,073 providers offline.
10. Add a model routing rule to `CLAUDE.md`: Opus for privacy, legal wording and ledger status;
    Sonnet by default; Haiku for mechanical work. Proposed but not yet adopted.

## 6. Lessons the next team should not relearn

- **One agent session per branch.** Two sessions pushing to one branch on 29 October produced a
  duplicate parser, a browser-impersonating User-Agent, unformatted files and a privacy leak.
- **Spokes edit only the files they own.** A repo-wide `ruff format` by one spoke rewrote another's
  files.
- **Commit early.** Container restarts silently kill background work; twice now.
- **Confirm plan mode is off before dispatching writing agents.** Spokes inherit it and cannot
  write.
- **Collect honestly.** Use the named User-Agent, honour robots.txt, never impersonate a browser.
  Where a site rejects scripts, a human saves the page in a browser.
- **The goal is "every row explained", not "100 per cent matched".** A forced match on a withheld
  individual is a defamation risk.
- **Verify agents' claims before they enter the ledger or a commit.** Every agent report in this
  project needed at least one correction or clarification.
