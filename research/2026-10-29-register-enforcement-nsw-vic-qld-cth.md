# Enforcement register audit: NSW, Victoria, Queensland, Commonwealth CCS

Date: 2026-10-29. Auditor: register-auditor spoke. Serves ledger gaps GAP-002 and GAP-001.
Method: the registers' own pages, copyright pages and robots.txt, plus one sampled NSW quarterly PDF. About 20 requests in total, spaced across four hosts. Commonwealth (education.gov.au) returned HTTP 503 on every attempt, so that section is incomplete.

## Summary table

| | NSW | Victoria (VECRA) | Queensland | Commonwealth CCS |
|---|---|---|---|---|
| Publisher | NSW Dept of Education (Early Learning Commission) | VECRA | Qld Dept of Education | Dept of Education (Cth) |
| Format | HTML index plus quarterly PDFs | HTML table, one page per period; older years as PDF/Word | HTML table, linked PDF/DOCX/DOC | HTML register; past registers on separate page `[Verify This]` |
| Bulk (CSV/API) | No | No | No (the Qld "Enforcement actions register" on data.qld.gov.au is an environmental dataset, not this one) | Not confirmed `[Verify This]` |
| SE- present | Yes ("Service ID" column) | Yes | No | Not confirmed `[Verify This]` |
| PR- present | Not in the service PDF sampled; provider PDFs not opened `[Verify This]` | Yes | No | Not confirmed `[Verify This]` |
| Window | 5 years from publication; quarterly PDFs from Jan 2025 | 2020 to Aug 2026 on the index; retention unstated | Entries 2017 to 2026; removal discretionary | Rolling 12 months (per brief) `[Verify This]` |
| Cadence | Quarterly | Monthly (some combined periods) | Not stated; page last updated 14 Oct 2026 | Not confirmed `[Verify This]` |
| Licence | CC BY 4.0 (site-wide) | CC BY 4.0 (site-wide) | CC BY 4.0 default on qed.qld.gov.au; host differs `[Verify This]` | Not confirmed (503) |
| robots.txt | No rules touching these pages | Crawl-delay 2; PDF/DOC/etc under /sites/default/files/ disallowed | 404, so no rules | Not retrieved (503) |
| Confirmed breaches (GAP-001) | Partial | Partial | Partial | Unknown `[Verify This]` |

## 1. NSW Department of Education

1. Publisher and URL: NSW Department of Education, https://education.nsw.gov.au/early-childhood-education/regulation-and-compliance/compliance-and-enforcement-actions/register-of-published-enforcement-actions
2. Contents: HTML landing page linking quarterly PDFs. Sampled `Q4_Service_Enforcement_Action_Information_2024_2025.pdf` (A4 landscape, 516 KB, April to June 2025). Exact columns: Service name; Address; Service ID; Nature of enforcement action; Reason for enforcement action; Date issued; Details of action taken. Example as printed: Service ID `SE-00008497`, nature "Compliance notice issued", reason cites "Regulation 103 Premises, furniture and equipment to be safe, clean and in good repair", date `01/04/2025`, details "Issue of compliance notice under section 177". The PDF carries a note that some services received enforcement actions on the same day for separate incidents. One service appears twice in identical consecutive rows, so de-duplication is needed (parser warning). Reasons are free text listing multiple regulation and law numbers.
3. Join keys: Service ID is SE- plus 8 digits (also seen `SE-40025725`). Provider approval numbers not seen in the sampled service PDF. Separate files exist for provider enforcement (Q3 FY2024-25), service and provider cancellations, and involuntary suspensions; their columns were not opened `[Verify This]`. ABN/ACN not seen.
4. Format: PDF only for data, no bulk download, no CSV or API found. Files are text-extractable (pdftotext -layout worked).
5. Coverage and window: NSW services under the National Law. Quarterly PDFs listed from Q3 FY2024-25 (Jan to Mar 2025) to Q4 FY2025-26 (Apr to Jun 2026). Page says information is available for 5 years from publication; resolved enforceable undertakings, compliance notices and emergency action notices stay as historical record. Pre-April 2025 information is on the cancellations and suspensions and enforceable undertakings pages (not opened `[Verify This]`). Related pages (URLs from the register page, not opened): `.../compliance-and-enforcement-actions/prosecutions`, `.../enforceable-undertakings`, `.../cancellations-and-suspensions`.
6. Cadence: quarterly, published after review periods complete. Q1 FY2025-26 service file marked updated 12 May 2026, so files can be revised after publication.
7. Licence: https://education.nsw.gov.au/rights-and-accountability/copyright states "Copyright material available on this website is licensed under a Creative Commons Attribution 4.0 International (CC BY 4.0) licence", allowing share and adapt "for any purpose, even commercially". Attribution: "© State of New South Wales (Department of Education), 2023." Excludes the Department logo, other logos, trademarks and third-party material. Confirmed CC BY 4.0. Whether the PDFs themselves carry a separate notice was not checked `[Verify This]`.
8. robots.txt (HTTP 200): User-agent * disallows only paths such as /search, /login, /content/dam/main-education/inside-the-department, /human-resources, /procurement, /policy-management-schools. The register PDFs under /content/dam/main-education/early-childhood-education/regulation-and-compliance/ are not disallowed. No crawl-delay stated.
9. Not published: no confirmed-breach finding list apart from enforcement actions; no per-service breach counts; no outcomes of compliance notices beyond a resolved flag `[Verify This]`; no provider numbers in the service file; PDF only; actions older than 5 years drop off.
GAP-001: partial. The page frames the register as actions for "confirmed non-compliance with the National Law" and describes compliance notices as addressing a "substantiated breach". That covers breaches that led to formal action only. Breaches confirmed without formal action are not published. No aggregate breach count was checked in annual reports `[Verify This]`.

## 2. Victoria (VECRA)

1. Publisher and URL: VECRA, https://www.vecra.vic.gov.au/enforcement-actions-august-2026 ; index https://vecra.vic.gov.au/enforcement-action
2. Contents: HTML table, 19 rows for August 2026. Columns: "Service and, or provider details"; "Action taken"; "Reason for enforcement action"; "Date enforcement action issued". The first column packs service name, address, service approval number and approved provider number. Example as printed: service approval `SE-00012251`, provider `PR-00006942`, "Compliance notice issued", 3 August 2026 (entity: Bulsho Family Day Care Pty Ltd).
3. Join keys: SE- and PR- both present (confirmed). They sit inside one text cell, so parsing needs a regex. ABN not seen.
4. Format: HTML per period. No CSV or API found. Older years as PDF and Word downloads.
5. Coverage and window: Index runs from "Enforcement actions 2020" (PDF/Word) to August 2026. It is not one page per month: 2026 has monthly pages (August, July, June), combined pages (April to May 2026; January to March 2026), and a separate "Cancelled providers with services that have not operated for more than 12 months" page. 2021 to 2025 are annual Word/PDF documents, plus one Children's Services Act document covering 2021 to 2025. Retention unstated.
6. Cadence: monthly, irregular combination of months.
7. Licence: https://www.vecra.vic.gov.au/copyright: "All material provided on this website is provided under a Creative Commons Attribution 4.0 International licence"; attribution "© Copyright State Government of Victoria"; excludes images, branding, the Victorian Coat of Arms and Government logo, and third-party content. Confirmed CC BY 4.0. The page footer itself only says "© Copyright State Government of Victoria".
8. robots.txt (HTTP 200): Crawl-delay: 2 for all agents; Disallow /oauth/*, /preview/*, /share-link; Disallow /sites/default/files/*.pdf, .doc, .xls, .csv, .txt, .ppt, .dot, .tif, .eps, .zip, .ics, .rtf; SemrushBot fully disallowed. The monthly HTML pages are allowed; the archived annual PDF/Word files are disallowed to crawlers. Any collector must honour crawl-delay 2 and avoid the archive files or seek consent.
9. Not published: no HTML history before 2026 (older years are documents); no structured fields beyond a text cell; no breach findings without action; no outcome or closure of notices `[Verify This]`.
GAP-001: partial. The index says VECRA publishes "details of all statutory sanctions in the public interest" and that reasons include the sections of the Act or Regulations breached. There is no separate list of confirmed breaches. Annual report counts not checked `[Verify This]`.

## 3. Queensland

1. Publisher and URL: Queensland Department of Education, https://earlychildhood.qld.gov.au/regulation/compliance-and-enforcement/register-published-enforcement-actions (page shows "Last updated 14 October 2026").
2. Contents: HTML table with columns "Provider or individual name"; "Service name"; "Date of action"; "Details"; "Breaches (if applicable)". The Breaches column lists National Law (NL) and National Regulations (NR) sections. Many rows link to supporting PDF, DOCX or DOC documents. Row-level example values were not extracted `[Verify This]`.
3. Join keys: no SE- or PR- numbers on the page. Linkage to ACECQA registers would need name and location matching. Privacy note: the first column can hold individuals; do not ingest or republish individual names.
4. Format: HTML plus linked documents. No CSV or API. The Qld dataset titled "Enforcement actions register" on data.qld.gov.au (59fc9567-d322-4bbd-9888-25589c12593f) was checked via researchdata.edu.au: it is an environmental enforcement dataset, not this register.
5. Coverage and window: entries from 2017 to 2026. No fixed retention; removal "will generally occur when the information is considered no longer relevant" and subjects can request removal. The page states it "is not a comprehensive list of all serious enforcement action" and that certain prohibition actions against individuals are not publishable.
6. Cadence: not stated. Publication after review periods are complete.
7. Licence: footer "© The State of Queensland (Department of Education)" linking https://qed.qld.gov.au/copyright-statement. That page (updated 23 July 2025) says CC BY 4.0 applies "Unless otherwise noted" and "The Queensland Government supports and encourages the distribution of its material." Attribution: "State of Queensland (Department of Education) [Year of publication]." Excludes Coat of Arms, logos, trademarks, third-party IP, personal information such as photographs. Reuse enquiries: Copyright.ITB@qed.qld.gov.au. Caveat: the register sits on earlychildhood.qld.gov.au while the statement is on qed.qld.gov.au; the register page itself states no licence `[Verify This]` that the statement covers it.
8. robots.txt: https://earlychildhood.qld.gov.au/robots.txt returned HTTP 404 (a SharePoint not-found page), so no disallow rules are published. No crawl-delay.
9. Not published: SE-/PR- numbers; any structured export; consistent retention; breach findings absent action.
GAP-001: partial and the strongest of the four on breach detail. The "Breaches (if applicable)" column names the NL/NR sections. The page does not use "confirmed" or "substantiated" and lists only entries that led to action. Annual report counts not checked `[Verify This]`.

## 4. Commonwealth Department of Education: CCS enforcement action register

Status: incomplete. https://www.education.gov.au/early-childhood/providers/compliance-and-enforcement/enforcement-action-register, its past-registers page, /copyright and /robots.txt all returned HTTP 503 (curl also gave an HTTP/2 INTERNAL_ERROR). Not retried further, per the constraints.
What a web search snippet of the department's own page indicates (not a direct read, confidence Low): the register records provider name, location, service type, type of sanction, conditions of approval or grounds for sanction, date of effect (and an end date on some entries). The past registers page is https://www.education.gov.au/early-childhood/providers/compliance-and-enforcement/enforcement-action-register/past-registers ; an older "2017-2018 (First Half)" register covers 1 July to 31 December 2017 and lists sanctions and immediate suspensions by state. Related pages seen in search results: the Child Care Enforcement Action Register at /early-childhood/provider-obligations/child-care-enforcement-action-register, an Infringement notices register, and a StartingBlocks page "The Department of Education Enforcement Action Register".
1. Publisher and URL: as above.
2. Contents: see snippet; not confirmed `[Verify This]`.
3. Join keys: unknown. Cth CCS approvals use provider and service identifiers that may or may not match SE-/PR-; ABN may be present `[Verify This]`.
4. Format: HTML per snippet; bulk unknown `[Verify This]`.
5. Window: brief says rolling 12 months under s199B of the A New Tax System (Family Assistance) (Administration) Act 1999. The search tool could not confirm s199B `[Verify This]`; the older register cites the Administration Act.
6. Cadence: unknown.
7. Licence: not retrieved. Do not assume CC BY 4.0 `[Verify This]`.
8. robots.txt: not retrieved (503).
9. Not published (inferred): sanctions relate to Child Care Subsidy law (Family Assistance Law), not National Law quality breaches; 12-month window means history lives only in past-registers.
GAP-001: unknown. The Commonwealth register covers FAL non-compliance and sanctions, a different regime from NQF quality breaches, so it is unlikely to answer GAP-001 `[Verify This]`.

## Cross-register findings

- Only NSW (Service ID column) and Victoria (embedded SE- and PR-) carry join keys. Queensland and, possibly, Commonwealth do not.
- Licences: NSW, Victoria confirmed CC BY 4.0 site-wide; Queensland CC BY 4.0 on a sibling host; Commonwealth unconfirmed. Even so, project rules require attribution and no naming of individuals; Queensland and prosecution lists contain individuals.
- No jurisdiction offers CSV, API or an open-data mirror for these registers.
- GAP-001: none of the four publishes a standalone list of confirmed breaches. All publish enforcement actions only (partial for NSW, Victoria, Queensland). Annual-report breach aggregates were not checked and remain open.
- Parsing risks: NSW duplicate rows and multi-line reasons; Victoria packed first cell; Queensland mixed HTML and linked documents; NSW files revised after publication.

## Open questions

1. Commonwealth register: retry later, confirm columns, join keys, window, licence, robots.txt, past-register format.
2. NSW: open a provider enforcement PDF and a cancellations PDF to confirm PR- numbers; open prosecutions and enforceable undertakings pages.
3. Queensland: confirm row-level example values and whether any rows carry approval numbers in linked documents.
4. GAP-001: check annual reports (NSW, Vic, Qld) and ACECQA NQF Snapshot for aggregate confirmed-breach counts.
5. Seek written confirmation that CC BY 4.0 on qed.qld.gov.au covers the earlychildhood.qld.gov.au register.

