# Register audit: enforcement and compliance action registers, SA, WA, TAS, NT, ACT

Captured 2026-10-29. Serves ledger gaps GAP-002 and GAP-001. Auditor: register-auditor spoke.
Method: read each authority's own pages where reachable. Where a fetch returned 403 or 404, that is
recorded and the item is marked `[Verify This]`. Items learnt only from web search result summaries
(not from the source page itself) are marked `[Verify This]`. About 20 fetches, none bulk.

## Summary table

| Item | SA (ESB) | WA (ECRU) | TAS (ECU) | NT (QECNT) | ACT (CECA) |
|---|---|---|---|---|---|
| Public enforcement register exists | Yes, "Current compliance action" plus yearly historical pages | Yes, searchable HTML list on wa.gov.au | Yes per search results, page itself returned 403 `[Verify This]`; plus quarterly aggregate data | Page exists but reportedly states no published actions currently `[Verify This]`, page returned 403 | Not confirmed live. Government reform to create one reported by news only `[Verify This]` |
| SE- / PR- join keys | Yes, current page. Example: `Happy Haven OSHC Mitcham (SE-00010642)`, `HAPPY HAVEN OSHC PTY LTD (PR-40001361)`. Inconsistent: one entry prints `SE 00010955` without hyphen. Historical 2021 page: none | None seen on landing page. Result list not captured `[Verify This]` | Search snippet shows `SE-00009943` on the enforcement page `[Verify This]`; aggregate data: none | Unknown | Not applicable |
| Format | HTML, one long page, per-service sections; summary table by year. Older PDF tables (2019, 2020) | HTML with search form (year, provider, service name, action type, postcode). No PDF/CSV mentioned | Enforcement page HTML `[Verify This]`; aggregate data as Excel files (I1601 to I1613) | HTML page and policy PDF `[Verify This]` | Not applicable |
| Bulk download | No | No | Excel for aggregates only | No | No |
| Window | Current page: summary 2023-24 to 2026-27; entries from about Aug 2025. Historical pages by year (2020, 2021, 2022 found). No stated retention | Not stated | Not stated for register; aggregates cover quarters Sep 2025 to Jun 2026 | Not stated | Not applicable |
| Update cadence | "Table last updated: 18 October 2026" (no schedule) | "Last updated 14 July 2026"; published after action finalised | Aggregates quarterly (implied) | Unknown | Unknown |
| Licence | "All rights reserved". Not Creative Commons | wa.gov.au terms: personal and non-commercial use with attribution; no commercial reuse. Not Creative Commons | Not confirmed `[Verify This]`; no CC statement on data page | Not retrieved | Not retrieved |
| robots.txt | Fetched. No relevant disallow on compliance pages (disallows /search/) | Fetched via summariser, paraphrase only; reports query-string disallows `?keyword=`, `?q=` `[Verify This]` | 403 | Not fetched | 403 |
| Confirmed breaches (GAP-001) | Partial | Partial / no | Yes (aggregate only) | No evidence `[Verify This]` | No evidence `[Verify This]` |

Fetch failures: educationandcare.tas.gov.au (page and robots.txt) 403; education.nt.gov.au (page and
policy PDF) 403; www.education.act.gov.au/robots.txt 403; www.esb.sa.gov.au/copyright 404 (wrong
guess; the real page is /copyright-disclaimer, which returned 200). No retries, no header spoofing.

## 1. South Australia: Education Standards Board (ESB)

1. Publisher and URL. ESB, https://www.esb.sa.gov.au/early-childhood/compliance-and-enforcement/current-compliance-action
   (also surfaced under the older path /early-childhood/compliance-and-investigations/current-compliance-action).
   Historical: https://www.esb.sa.gov.au/node/758 (2021), /node/221 (2022), /historical-compliance-action-2020.
2. Contents. Summary table with columns Type plus four financial years (2023-24 to 2026-27) and a Total
   row. Rows: emergency action notice issued, compliance notice issued, condition imposed, enforceable
   undertaking issued, prohibition notice issued. Below it, one section per service: service name and
   address, approved provider, "Details" (contraventions) and "Action Taken". 2021 historical entries:
   service name, approved provider, address, date, type of action (s 179 emergency action directions,
   s 177 compliance notices), matters with section references, and whether evidence of compliance was provided.
3. Join keys. Current page carries both. Example exactly as printed: `Happy Haven OSHC Mitcham (SE-00010642)`
   and `HAPPY HAVEN OSHC PTY LTD (PR-40001361)`. Formatting is inconsistent: `St Michael's College OSHC - Extend (SE 00010955)`
   prints without a hyphen, so any parser must normalise. Historical 2021 page has no SE or PR numbers (name and address only).
   No ABN/ACN seen.
4. Format. HTML only (current and historical); older PDF tables for 2019 and 2020 exist
   (e.g. /sites/default/files/old_7_files/compliance-action-table-may2020_0.pdf, from search results `[Verify This]`).
   No bulk download, no CSV. The current page text is about 102,000 characters, i.e. one very large page.
5. Coverage and window. SA only, all NQF service types. Current page entries run from roughly 11 August 2025
   to October 2026. No retention statement on current or 2021 page. Historical years found: 2020, 2021, 2022; completeness of 2023 onward `[Verify This]`.
6. Cadence. "Table last updated: 18 October 2026." No schedule stated.
7. Licence. Copyright and disclaimer page (https://www.esb.sa.gov.au/copyright-disclaimer): "(c) Government of South Australia.
   Published 2022. All rights reserved." and "No part of this site may be reproduced by any process except in accordance
   with the provisions of the Copyright Act 1968". Creative Commons not mentioned: DENIED for esb.sa.gov.au.
   Note that many other SA government sites use CC BY, so do not assume it; ESB's own page reserves all rights.
   A separate Terms of use page (/terms-use) exists and was not read `[Verify This]`. Consent route: not stated; contact ESB `[Verify This]`.
8. robots.txt (https://www.esb.sa.gov.au/robots.txt, fetched). Standard Drupal file, `User-agent: *`. Relevant lines:
   `Disallow: /search/`, `Disallow: /core/`, `Disallow: /profiles/`, `Disallow: /admin/`, `Disallow: /node/add/`,
   `Disallow: /index.php/search/`. No disallow covers /early-childhood/compliance-and-enforcement/ or /node/NNN pages. No crawl-delay. Bot protection: none seen.
9. Not published. Dates of confirmed breaches independent of an action; outcomes after the action (only a statement
   whether evidence of compliance was provided on historical entries); closed or older actions beyond the visible window;
   consistent machine keys; denominators (number of services or visits) for the counts. Absence from the page is not evidence of safety.

GAP-001: PARTIAL. Entries state "A Delegate of the Education Standards Board (ESB) is satisfied that the Approved Provider has
contravened:" followed by section references. That is a regulator finding of contravention, attached only to services that
received a formal action. Some entries (e.g. conditions under s 55) list no contravention. No standalone count of confirmed breaches seen.
Annual report not checked `[Verify This]`.

## 2. Western Australia: Department of Communities, ECRU

1. Publisher and URL. Department of Communities, Education and Care Regulatory Unit,
   https://www.wa.gov.au/government/document-collections/education-and-care-regulatory-unit-enforcement-actions
2. Contents. Page text says lists cover serious non-compliance: suspension or cancellation of provider and service approvals,
   compliance notices, enforcement conditions, enforceable undertakings, and criminal prosecutions or State Administrative Tribunal
   applications. Search filters: year, provider, service name, compliance action type, post code. "Communities publishes details after
   all court, tribunal or administrative action is finalised." The result rows themselves were not in the captured content `[Verify This]`.
3. Join keys. None visible on the landing page, so no example can be given. Whether result rows carry SE-/PR- numbers is unconfirmed `[Verify This]`.
4. Format. HTML with a search tool. No PDF or CSV mentioned, no download links. Links out to SAT eCourts and National Law legislation sites.
5. Coverage and window. WA only. How far back and any retention period are not stated on the page. A 2018 trade-press article
   (not primary) said details stay up for 24 months `[Verify This]`.
6. Cadence. "Last updated 14 July 2026". No schedule.
7. Licence. wa.gov.au Terms of use (https://www.wa.gov.au/terms-of-use, updated 5 September 2023) as summarised by the fetch tool:
   "You may copy, distribute, display, download or print the material on this website for your own personal use", with permitted uses
   including non-commercial educational and internal organisational use, "provided you attribute the source of the information and
   reference any copyright or licence conditions", and "no part may be reproduced or re-used for any commercial purposes whatsoever".
   Footer: "(c) Government of Western Australia 2017 to 2026". Creative Commons: DENIED (not mentioned). Quotes are from the tool's
   extraction, not read verbatim from the browser, so confirm wording `[Verify This]`.
8. robots.txt (https://www.wa.gov.au/robots.txt). The tool refused to reproduce the file verbatim; paraphrase only: `User-agent: *`,
   blocks /core/, /profiles/, admin, search and user paths, and, per the paraphrase, `/search-results.html` and URLs containing
   `?keyword=` or `?q=`. The enforcement page's search form may therefore sit behind disallowed query patterns `[Verify This]`. Re-fetch raw with curl before any scraper design.
9. Not published (as far as seen). Dates of breaches versus finalisation; actions that are not finalised (so live or recent actions are
   absent by design); machine-readable bulk data; confirmed breaches not leading to an action.

GAP-001: PARTIAL to NO. Publication is of formal actions and prosecutions after finalisation. No confirmed-breach series seen. Annual report not checked `[Verify This]`.

## 3. Tasmania: Education and Care Unit (ECU), Department for Education, Children and Young People

1. Publisher and URLs. ECU. Enforcement list: https://educationandcare.tas.gov.au/families-and-communities/published-enforcement-actions-under-the-national-law
   (fetch returned 403; known only from search results). Aggregate data: https://decyp.tas.gov.au/about-us/policies-legislation-data/data-and-statistics/regulation-of-education-and-care-data/ (fetched, 200).
2. Contents. Enforcement list: per search snippets, entries include compliance notices and a suspension of service approval under s 73,
   by service name and locality `[Verify This]`. Aggregate page (read directly): quarterly Excel datasets (labelled I1601 to I1613) for
   approvals, service visits (assessment and rating, and compliance and monitoring), notifications and complaints, "Total breaches recorded as
   not confirmed or confirmed", top five National Law sections and National Regulations with confirmed breaches, counts of Compliance Notices,
   Prohibition Notices, Emergency Action Notices, amended approvals and accepted enforceable undertakings, and quality ratings.
3. Join keys. Enforcement list: a search snippet showed `SE-00009943` `[Verify This]`; PR- not confirmed. Aggregate files: none (counts).
4. Format. Enforcement list HTML `[Verify This]`. Aggregates: Excel files hosted on the department document centre. Per-record pages not applicable to aggregates.
5. Coverage and window. Tasmania only. Aggregates: quarters ending 30 September 2025 to 30 June 2026; page published 14 September 2026.
   Enforcement list window and retention unknown `[Verify This]`.
6. Cadence. No stated schedule; quarterly tables imply quarterly.
7. Licence. The data page has no Creative Commons or licence statement; it links to a "Copyright and Disclaimer" page under "Using this website"
   which was not read `[Verify This]`. educationandcare.tas.gov.au terms not retrieved (403). Creative Commons: NOT CONFIRMED either way.
8. robots.txt. https://educationandcare.tas.gov.au/robots.txt returned 403. decyp.tas.gov.au/robots.txt not fetched `[Verify This]`.
   The 403 on a plain fetch suggests bot protection (WAF) on the ECU host; do not design around it without permission.
9. Not published. Per-service breach history; breaches by provider; denominators per service type are partly implied by the approvals counts but not joined.

GAP-001: YES (aggregate only). Tasmania is the only one of the five where a primary page, read directly, publishes confirmed versus not confirmed breaches
as a distinct statistic, with the most frequent sections and regulations. It is not linked to named services or provider approval numbers, so it cannot be joined per service.

## 4. Northern Territory: Quality Education and Care NT (QECNT)

1. Publisher and URL. Department of Education, https://education.nt.gov.au/committees-regulators-and-advisory-groups/quality-education-and-care-nt/enforcement-action-taken-by-regulatory-authority
   (403 on fetch). Policy: https://education.nt.gov.au/__data/assets/pdf_file/0009/1488357/qecnt-published-enforcement-action-policy-procedure.pdf (403 on fetch).
2. Contents. From search-result summaries only `[Verify This]`: the page links to a register of published actions but states there are currently no published
   enforcement actions. The policy reserves publication for particularly serious, high-risk or repeated non-compliance, and excludes infringement notices,
   compliance directions and directions to exclude persons from premises.
3. Join keys. Unknown. 4. Format. HTML page and PDF policy `[Verify This]`. 5. Window and retention. Unknown.
6. Cadence. Unknown. A QECNT infringement notices operational procedure dated 18 June 2026 exists (search result) `[Verify This]`.
7. Licence. Not retrieved. Creative Commons: NOT CONFIRMED.
8. robots.txt. Not fetched (host returned 403 on two page fetches).
9. Not published. Effectively nothing, if the "no published actions" statement is current. Annual report counts not checked.

GAP-001: NO EVIDENCE. Could not read any primary page. `[Verify This]`.

## 5. ACT: Children's Education and Care Assurance (CECA), Education Directorate

1. Publisher and URL. CECA, https://www.education.act.gov.au. No register page found by search. The only reporting of a register is in news
   (region.com.au), which says an ACT register of specified enforcement actions publishable under the National Law is being developed alongside a website,
   and that the 2026-27 budget funds more regulation. Third-party, context only, not a basis for any claim `[Verify This]`.
2 to 6. Not applicable until a register is confirmed. No contents, keys, format, window or cadence can be stated.
7. Licence. Not retrieved. 8. robots.txt: https://www.education.act.gov.au/robots.txt returned 403. Creative Commons: NOT CONFIRMED.
9. Not published. What is published today by CECA (media releases, annual report counts) was not established in this audit.
   Commonwealth enforcement register (education.gov.au, Family Assistance Law, not National Law) lists some ACT services; that is a different instrument and is covered by another audit.
   StartingBlocks was described by a news article as the current public source for ACT regulatory action `[Verify This]`.

GAP-001: NO EVIDENCE. CECA statements reported by news say identifying details cannot be disclosed for privacy reasons `[Verify This]`.

## Cross-jurisdiction notes

- Only SA is confirmed from the page itself to carry both SE- and PR- numbers. That is the best join candidate of the five, and needs normalisation of `SE 00010955` style variants.
- No site was confirmed Creative Commons. SA ESB explicitly reserves all rights. WA permits non-commercial reuse with attribution only. Written consent will be needed for republication; none of the five documents a consent route that was seen.
- Confirmed breach statistics (GAP-001): Tasmania yes (aggregate), SA partial (per action), WA partial/no, NT and ACT no evidence. Keep "breach", "confirmed breach", "enforcement action" and "prosecution" separate in any ledger entry.
- Counts need denominators and windows: the SA summary table has no denominator of services.

## Follow-ups (not done within fetch budget)

1. Fetch TAS, NT, ACT pages in a normal browser or with permission; the plain fetcher received 403.
2. Read ESB /terms-use, ECU copyright page, NT and ACT terms.
3. Check annual reports (SA, WA, NT, ACT) for confirmed-breach counts.
4. Pull raw wa.gov.au robots.txt via curl and test whether the search results are reachable without disallowed query strings.
5. Confirm whether the WA result rows carry SE-/PR- numbers.

