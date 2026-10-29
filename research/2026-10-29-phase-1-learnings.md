# Phase 1 learnings (29 October 2026)

What the first validation pass changed about the plan. Ledger statuses are in
`data/gap-ledger.json`; the audits are the other `research/2026-10-29-*.md` files.

## Ledger outcome

| Gap | Old | New | Confidence | Tractability | One line |
|---|---|---|---|---|---|
| GAP-001 Confirmed breaches not published per service | hypothesis | validated | High | campaign_or_foi | Every register read publishes formal actions only; breaches exist only as aggregates (ACECQA, RoGS, Tasmania) |
| GAP-002 No joined national enforcement picture | hypothesis | validated | Medium | partial | Five formats, three licence regimes, Queensland has no approval numbers, no CSV or API anywhere |
| GAP-003 No public ownership graph | hypothesis | validated | Medium | partial | ACECQA CSV has no ABN, ACN or management type; group links sit in paid ASIC extracts |
| GAP-004 Non-NQF services have no public list | hypothesis | hypothesis | Medium | partial | 473 and 142 trace only to ABC; Queensland has an official non-NQF register, other states unconfirmed |
| GAP-005 No per-service history | hypothesis | validated | Medium | partial | CSV holds one previous rating set; NSW now displays two ratings and two years of actions |
| GAP-006 Rating age not surfaced | hypothesis | hypothesis | Low | aggregation | Data is public (RatingsIssued, Last Visit Date); a presentation gap at most, may be rejected |
| GAP-007 Serious incidents aggregate only | hypothesis | validated | Medium | campaign_or_foi | 160 per 100 services in 2024/25; no split by management type or service in ACECQA or RoGS |

Five of seven gaps validated on official evidence. Phase gate condition 1 is met. Condition 2
(ACECQA licensing answer) is not: the letter is drafted, not sent.

## What changed the plan

1. **The ACECQA CSV is reachable and fresh, but only with `?nocache=`.** The plain static URL
   serves a CDN copy about 93 days old; the cache-busted URL returned a file regenerated the
   previous day. Every snapshot must store the `last-modified` header. Hub-verified.
2. **ACECQA's robots.txt disallows ClaudeBot, anthropic-ai and Claude-Web site-wide** and sets
   `Content-Signal: ai-train=no`. The CSV paths are open to the generic agent with a 3 second
   crawl delay. Decision: the project collector uses its own named user agent, fetches only the
   static CSVs, never through an AI-vendor crawler. The consent letter says so.
3. **Licensing is a matrix, not a single answer.** NSW DoE and VECRA are CC BY 4.0 (read
   directly). SA ESB is "All rights reserved". WA is non-commercial only. Queensland's CC BY sits
   on a different host from the register. The Commonwealth register was unreachable (503).
   Consequence: W5 (parsers) can start with NSW and Victoria the moment the phase gate opens;
   SA and WA need their own consent requests.
4. **Queensland is the join problem.** Its register prints no SE- or PR- numbers. Joining it needs
   name and address matching against the ACECQA register, with a precision caveat on every row.
5. **The ownership graph needs name matching.** No ABN in any ACECQA export. The ABR bulk extract
   (CC BY 3.0 AU, weekly, XML) gives ABN, ACN, entity type and names; the ASIC open dataset adds
   company status but no officeholders or parent. Group structure beyond that is paid. Ask ACECQA
   for ABN or ACN in the consent letter (done).
6. **The 473 figure is the ABC's own count.** It cannot be published as fact. GAP-004 stays a
   hypothesis until an official source appears or each state confirms what it lists.
7. **Confirmed breaches are published as aggregates.** ACECQA reports 222 confirmed breaches per
   100 services in 2024/25 and 7.9 per cent of serious incidents associated with a confirmed
   breach [Verify This: figure quoted by the gap-analyzer from the 2025 report]. The gap is per
   service, and the ledger title now says so.

## Process learning

Spokes launched from a hub that had plan mode active inherited it and could not write to
`research/` or the ledger; each parked its output in a plan file. The hub copied the drafts in.
Fix: confirm plan mode is off before dispatching spokes, and tell each spoke the target path is
writable.

## Still blocked by HTTP 403 or 503 from this environment

www.acecqa.gov.au HTML pages, snapshots.acecqa.gov.au, data.gov.au, parliament.nsw.gov.au, the
Commonwealth enforcement register (education.gov.au), the Tasmanian enforcement page, QECNT and
the ACT CECA site. A human in a browser, or the owner's machine over Remote Control, can clear
most of the remaining `[Verify This]` marks in an hour.

## Next action

Send the ACECQA letter. Then a browser pass on the blocked pages above.
