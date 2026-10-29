# Register audit: ACECQA National Registers, NQF Snapshots, ABR and ASIC (2026-10-29)

Serves ledger gaps GAP-003 (no public ownership graph), GAP-005 (no per-service history) and GAP-006 (rating age not surfaced).
Auditor: register-auditor spoke. Captured 2026-10-29.

## Access note

- www.acecqa.gov.au HTML pages (national registers page, terms of use, copyright, media PDFs, NQF Snapshots page) and snapshots.acecqa.gov.au returned HTTP 403 to automated fetches. No header spoofing was attempted.
- Static files under `https://www.acecqa.gov.au/sites/default/files/national-registers/...` were reachable. I read the full NT services export, a 3.5 KB range of it for the verbatim header, and made HEAD requests to the national (au) services and providers files (not downloaded, because the services file is 14.7 MB).
- `robots.txt` on www.acecqa.gov.au was reachable.
- StartingBlocks terms were readable. data.gov.au, the ABR readme PDF and the ASIC data.gov.au pages returned 403; the ABR bulk extract page, the ABN Lookup web services page and the Open Net Zero and federal catalogue entries were readable.
- Everything marked "snippet" below comes from WebSearch result summaries and is `[Verify This]`.
- Fetch count: about 22 page or file fetches plus 3 small curl calls, spaced by more than 1.5 seconds per host.

## Summary table

| Question | Finding | Source type | Confidence |
|---|---|---|---|
| Services export has SE number, PR number | Yes (`ServiceApprovalNumber`, `Provider Approval Number`) | Primary (CSV header read) | High |
| Providers export has PR number | Yes (`Provider Approval Number`) plus a `Service Approval Number` column (blank in the sample rows) | Primary (NT file) | High |
| ABN or ACN in either export | No | Primary (both headers) | High |
| Provider management type in either export | No | Primary | High |
| Overall NQS rating | Yes (`OverallRating`, plus 7 quality area ratings) | Primary | High |
| Rating issued date | `RatingsIssued`, month and year only (sample value "Jan 2026"), not a day-level date | Primary (one sample row) | Medium |
| Previous rating | One prior set only: `PreviousQualityArea1Rating` to `PreviousQualityArea7Rating`, `PreviousOverallRating`, `PreviousRatingsIssued` | Primary | High |
| Service type, approved places, conditions | `ServiceType`, `NumberOfApprovedPlaces`, `Conditions on Approval` | Primary | High |
| Nominated supervisor (a person) fields | None present | Primary | High |
| Other fields to treat with care | `Phone`, `Fax` (free text; the sample carries a note such as "(school phone)") | Primary | High |
| Export mechanics | One static CSV per jurisdiction under `/sites/default/files/national-registers/{services,providers}/` | Primary (HEAD, fetch) | High |
| Cadence | Site says daily; older ACECQA text said weekly; the national files on the CDN were last modified in July 2026 | Snippet plus HTTP headers | Low to Medium |
| Terms | No reproduction for commercial use or competing use without written consent; consent contact copyright@acecqa.gov.au | StartingBlocks terms (primary, same owner); ACECQA pages blocked | Medium |
| Snapshot files per service? | Not evidenced; appear to be aggregates | Snippet only | Low |
| ABR bulk extract | CC BY 3.0 AU, weekly, XML in 20 parts, current data only, no historical names | ABR page (primary) plus snippets | Medium to High |
| ASIC company dataset | Open (CC BY 3.0 AU), weekly, company-level only; officeholders and ultimate holding company only via paid extract | Snippets | Low to Medium |
| Can a provider be joined to an ABN free? | Yes, by legal-name match, with precision caveats; not exact | Reasoned from A1 and C7 | Medium |

## A. ACECQA National Registers

### A1. Fields

Page: https://www.acecqa.gov.au/resources/national-registers (HTML blocked; no fact sheet or user guide PDF could be opened; the Open Net Zero and federal catalogue entries describe the registers as "machine-readable data files (CSV format)" and give no fields, licence "unknown" and "not specified").

**Services export** (`Education-services-nt-export.csv`, header read verbatim from the file, 98 columns), in order:

1. `ServiceApprovalNumber`, `Provider Approval Number`, `ServiceName`, `ProviderLegalName`, `ServiceType`
2. `ServiceAddress`, `Suburb`, `State`, `Postcode`, `Phone`, `Fax`
3. `Conditions on Approval`, `NumberOfApprovedPlaces`, `ServiceApprovalGrantedDate`
4. `QualityArea1Rating` to `QualityArea7Rating`, `OverallRating`, `RatingsIssued`
5. `PreviousQualityArea1Rating` to `PreviousQualityArea7Rating`, `PreviousOverallRating`, `PreviousRatingsIssued`
6. `Last Service Approval Transfer Date`, `Last Visit Date`
7. Service type flags: `Long Day Care`, `Preschool/Kindergarten - Part of a School`, `Preschool/Kindergarten - Stand alone`, `Outside school Hours Care - After School`, `... - Before School`, `... - Vacation Care`, `Other`
8. 14 `Annual <Day> Start/End Time` columns, 28 `School Terms Only Session 1/2 <Day> Start/End Time` columns, 14 `Holiday Care <Day> Start/End Time` columns (irregular spellings such as `Session1` exist in the header), then `Temporarily Closed`

Sample row observations (organisation level only): service approval number format `SE-` plus 8 digits; provider format `PR-` plus 8 digits; rating values are text such as "Meeting NQS"; `RatingsIssued` holds month and year text such as "Jan 2026"; `ServiceApprovalGrantedDate` is dd/mm/yyyy; postcodes keep leading zeros.

**Providers export** (`Approved-providers-nt-export.csv`, header read from the file, 10 columns): `Provider Approval Number`, `Service Approval Number`, `Legal Name`, `Trading Name`, `Address`, `Suburb`, `State`, `Postcode`, `Date Approval Granted`, `Conditions`. In the two sample rows (both school-run providers) `Service Approval Number` was empty. Whether larger providers repeat per service is `[Verify This]`.

Answers to the specific field questions:

| Field wanted | Services export | Providers export |
|---|---|---|
| Service approval number (SE-) | Yes | Column exists, sample blank |
| Provider approval number (PR-) | Yes | Yes |
| ABN or ACN | No | No |
| Provider management type | No | No |
| Overall NQS rating | Yes | No |
| Rating issued date | Month and year only | No |
| Service type | Yes | No |
| Approved places | Yes | No |
| Conditions on approval | Yes | Yes (`Conditions`) |
| Nominated supervisor | No | No |

Implications for ingest:
- Nominated supervisor fields are absent, so there is nothing person-level to drop for that reason. `Phone` and `Fax` are free text and can hold a personal number (the sample carries a "(school phone)" note). Drop both at ingest under non-negotiable rule 2.
- Provider management type is reported in the NQF Snapshot publications (an older snapshot reported services "by provider management type", snippet), so ACECQA holds the data but the exports do not carry it. Ask ACECQA for it as part of the consent request.
- The StartingBlocks provider page I read (one Queensland provider) showed provider name, address, approval number, date approval granted, a "large provider" membership line, conditions, and a count of enforcement actions in the past two years. It did not show ABN, ratings or management type. `[Verify This]` (single page, summarised).

### A2. Export mechanics

- Pattern, services: `https://www.acecqa.gov.au/sites/default/files/national-registers/services/Education-services-{code}-export.csv`. Confirmed for `nt` (fetched) and `au` (HEAD 200, 14,741,519 bytes, `last-modified` Mon 27 Jul 2026). Search results also show `vic` and `sa` variants, some with a `?nocache=<epoch milliseconds>` query string, which looks like the cache-busting parameter the "Export CSV" link adds. Other state codes follow the same pattern `[Verify This]`.
- Pattern, providers: `https://www.acecqa.gov.au/sites/default/files/national-registers/providers/Approved-providers-{code}-export.csv`. Confirmed for `nt` (fetched) and `au` (HEAD 200, 1,317,933 bytes, `last-modified` Tue 28 Jul 2026).
- A guessed services URL (`.../services/Approved-services-nt-export.csv`) returned 404, so the two file families use different names.
- Cache warning: on 29 Oct 2026 the `au` services response carried `cf-cache-status: HIT`, `age: 8053075` (about 93 days) and `cache-control: max-age=31536000`. A plain URL may therefore serve a copy that is months old. Whether the `nocache` parameter forces a fresh file is `[Verify This]`. Any scraper must record the `Last-Modified` header and a content hash with every snapshot, and compare two fetches before trusting "daily".
- The national services file is 14.7 MB, which is well above the few MB limit for this audit, so it was described, not downloaded.

### A3. Update cadence

- Current ACECQA page text (snippet): data sets for each state and territory "are updated daily from the NQA ITS data repository". `[Verify This]`
- Older ACECQA text (snippet, undated, an older FAQ or fact sheet): the registers "are updated weekly from data held in the National Quality Agenda IT System (NQA ITS)". `[Verify This]`
- ACECQA's submission to a competition inquiry (snippet) says NQAITS is the primary source of data on StartingBlocks and that "all information is updated daily". `[Verify This]`
- Observed: the national files showed `Last-Modified` dates of 27 and 28 July 2026 on 29 Oct 2026, which conflicts with "daily" unless the CDN is stale (see A2).

### A4. Terms of use, copyright, robots

Pages https://acecqa.gov.au/terms-of-use and https://www.acecqa.gov.au/copyright returned 403. I used the StartingBlocks terms (https://www.startingblocks.gov.au/terms-of-use, same owner) as instructed. The quotes below came back through the fetch tool's summariser, so exact wording is `[Verify This]` against the live page before anything is cited.

- Reproduction and storage, section 2e (a list of permitted acts): "to make a copy of the whole or any part of the Content from the Site in any form"; "storing in electronic form".
- Section 4d: "you must retain all copyright, trade mark and other proprietary notices"; reproduction "in whole or in part without material alteration".
- Commercial use, section 5a: you must not "reproduce, distribute or use in any manner any Content or any Derivative Work for any commercial purpose".
- Competing use, section 5b: you must not "use any Content or any Derivative Work to compete with or displace the market for or use of the Content".
- Attribution, section 4e: "you must acknowledge all Content from the Site that is used or relied upon in the following way ... Source: Australian Children's Education and Care Quality Authority (ACECQA)."
- Consent: "Any requests in relation to written consent should be addressed to: copyright@acecqa.gov.au".
- Scraping: the StartingBlocks terms do not mention scraping or automated collection.
- ACECQA terms (snippet only): no reproduction, distribution or use of Content, "the national registers, or data from them", for any commercial purpose without prior written permission; consent may be given with conditions or declined "in its absolute discretion"; Copyright Act 1968 (Cth) exceptions are preserved. The phrase "source of quality rating data for regulated services" was not found in any retrievable text. `[Verify This]`
- Licence on the registers: none stated. The federal catalogue lists "Licence not specified"; Open Net Zero lists "unknown". This matches CLAUDE.md rule 8: not openly licensed.
- robots.txt (read in full): `User-agent: *` carries `Content-Signal: search=yes,ai-train=no,use=reference` and `Allow: /`. Named AI and other crawlers, including ClaudeBot, anthropic-ai, Claude-Web, GPTBot and CCBot, are `Disallow: /`. The generic block disallows `/search`, `/resources/national-registers/services?` and `/resources/national-registers/providers?` (faceted query URLs) and sets `Crawl-delay: 3`. The `/sites/default/files/` CSV paths are not disallowed for the generic agent. Decision for the hub: a project scraper should use its own honest user agent, never one of the disallowed tokens, respect the 3 second crawl delay, and fetch only the static CSVs. Whether automated retrieval for a non-commercial public-interest project falls inside the terms is a legal question for the hub and ACECQA, not settled here.
- Bot protection: Cloudflare in front of the HTML pages (403 to automated fetches).

Recommendation: send the consent request to copyright@acecqa.gov.au before any public output. Ask for (1) written consent to store and republish per-service ratings with attribution, (2) provider management type and rating assessment dates at day level, (3) an ABN or ACN field, and (4) confirmation of cadence.

## B. NQF Snapshots

### B5. Per-service rows or aggregates

- Pages https://www.acecqa.gov.au/national-quality-framework/national-quality-framework-snapshots and https://snapshots.acecqa.gov.au returned 403, so no data file was opened.
- Snippet: the page offers "the latest NQS data (Q2 2026, data as at 1 July 2026)" and "the latest NQS time series data (Q3 2013 to Q2 2026)", and earlier editions offered an Excel workbook. Previous Snapshots are PDF reports (for example Q3 2022, Q2 2024). `[Verify This]`
- The reports are national aggregates by state, service type, management type and quality area. I found no evidence of a per-service file. Confidence: Low (not opened). The per-service rows that exist publicly are the register CSV in section A.
- Action for the hub: ask a human with a browser to open the Q2 2026 data workbook and record its sheet names and column headers.

### B6. Per-service rating history

- The register CSV carries exactly one prior rating set per service (`Previous...` columns and `PreviousRatingsIssued`, month and year). That is one prior cycle, not a series. There is no earlier history in any ACECQA export I could reach.
- StartingBlocks "previous ratings": the help page https://startingblocks.gov.au/resources/choosing-a-service/learn-about-quality did not mention previous ratings. A search found nothing on a look-back period. ACECQA's September 2025 transparency updates for StartingBlocks add safety history and regulatory action information (snippet), but whether a rating history is shown is unconfirmed. `[Verify This]`; a human should open one service page and record exactly what appears.
- Consequence for GAP-005: a real per-service history can only be built by taking our own dated snapshots of the register CSV (raw data immutable, per CLAUDE.md rule 4) and diffing them. The `Previous...` columns let the first snapshot back-fill one step. The 93 day cache age in A2 matters here: each snapshot must store `Last-Modified`.
- Consequence for GAP-006: rating age can be computed from `RatingsIssued`, but only to month precision. `Last Visit Date` is also in the CSV. Ask ACECQA for day-level dates.

## C. Ownership data (GAP-003)

### C7. ABR bulk extract and ABN Lookup web services

- ABR page https://abr.business.gov.au/Tools/BulkExtract (read): published weekly, XML, "a subset of the public information businesses provide when registering for an ABN". Licence is not stated on that page; it points to data.gov.au.
- data.gov.au dataset https://data.gov.au/data/dataset/abn-bulk-extract (403 to fetch; search snippet): licence Creative Commons Attribution 3.0 Australia; publisher Australian Business Register; XSD schema published as a resource; main page showed "Updated 08/04/2026" and a part 2 resource "Updated 31/12/2025" (unreconciled). `[Verify This]`
- Files (readme snippet): `yyyymmddPublic01.xml` to `yyyymmddPublic20.xml`, distributed as Part 1 and Part 2 zips. The readme's size figures are from November 2015 (11.7 million ABNs, 18 million names, about 6 GB uncompressed), so today's size is larger and unknown. `[Verify This]`
- Fields (ABR page): ABN, ABN status and date, entity type, legal name, business and trading names, state and postcode of the main business location, ACN/ARBN/ARSN/ARFN, GST status and date, Deductible Gift Recipient status and date. The ABR page does not list previous names.
- Historical names (readme snippet): the bulk extract holds current information only; the web services have an option to include historical details. `[Verify This]`
- Personal data warning: entity type includes individuals and sole traders, whose legal name is a person's name. Ingest must filter to non-individual entity types and discard the rest at load, in line with rule 2.
- ABN Lookup web services, https://abr.business.gov.au/Tools/WebServices (read): register, read the limitations and user guide, accept the web services agreement, and receive an authentication GUID by email. "Access to the ABN Lookup web services is free of charge." Rate limits are not stated on the page. Methods are not named on the page; they are in the user guide and WSDL. The page notes limited JSON support for ABN and name searches. From general knowledge a search by name method exists but I could not confirm it from the page, so `[Verify This]`. The services cannot be used to update ABN details.

### C8. ASIC

- ASIC Company Dataset on data.gov.au (https://www.data.gov.au/data/dataset/asic-companies, 403; snippets): CSV, snapshot of the register, updated weekly (Tuesdays, from 7 August 2018), licence Creative Commons Attribution 3.0 Australia. Fields per the help file: company name, ACN, type, class, subclass, status, registration and deregistration dates. No officeholder, shareholder or ultimate holding company fields seen. `[Verify This]`
- Other open ASIC datasets exist (business names, credit licensee, liquidator, banned and disqualified organisations) (snippets). Not examined.
- Paid: officeholders, shareholders and ultimate holding company appear on ASIC company extracts bought through ASIC Connect or a broker. Third-party figures (snippets): current company extract about $10 online or $13 by post; current and historical extract about $21 online or $24 by post (one broker, "2026-27 fees"; an older guide said $20 and $23). Brokers may add a service fee. ASIC's own search-fees page (https://asic.gov.au/online-services/search-asics-registers/search-fees/) showed template placeholders only, so current prices are `[Verify This]`.
- Rule 2 interaction: officeholder and shareholder records are mostly natural persons. Under the project rules only entity-level facts (parent company, ultimate holding company, ACN) could be stored or published. That removes most of the value of the paid extract except for the corporate-group link.

### C9. Conclusion: joining a provider to an ABN without paid data

- ACECQA exports have no ABN or ACN, so no exact key exists. A join needs the legal-name fallback.
- Fallback: normalise `ProviderLegalName` (case, punctuation, "PTY LTD" and "PTY LIMITED", "INC" and "INCORPORATED", "THE TRUSTEE FOR"), match to the ABR bulk extract entity name restricted to non-individual entity types, and corroborate with state (ABR main business state against the `State` in the provider or service row). Accept automatically only a unique exact normalised match with state agreement; send the rest to a manual queue; record `match_method` and a confidence value; verify any ABN shown publicly on ABN Lookup.
- Precision caveats: the ABR gives only the main business state and postcode, not the provider's address for notices; names change and the bulk extract has no history; trusts, partnerships and "trading as" providers appear under trustee or partner names; schools, councils and departments may share an ABN or have no ACN; several registrations can share a name; cancelled ABNs persist in the data. Do not assert ownership or group membership from a name match alone.
- ASIC company dataset (free) adds ACN-to-company-name checks but not parents. Corporate group links need either ACECQA's own "large provider" grouping (seen on one StartingBlocks provider page) or a paid ASIC extract per company. Cost is the per-extract fee multiplied by the number of providers sampled; the provider count was not established here.

## Open questions for the hub

1. Does the plain CSV URL serve a stale CDN copy (last modified 27 and 28 July 2026 on 29 October), and does `?nocache=` fix it? Compare two fetches.
2. What exactly do the Snapshot Q2 2026 workbook and time series contain? Needs a human with a browser.
3. Does a StartingBlocks service page show a rating history, and how far back? Needs a human with a browser.
4. Exact wording of the ACECQA terms of use and copyright pages (blocked), including the competing-use clause.
5. Does the providers export repeat a provider once per service (the `Service Approval Number` column)?
6. Current ASIC fees and whether any ASIC product gives ultimate holding company bulk or per company.
7. Whether ABN Lookup web services offer a name search and any documented rate limit.
8. Whether to ask ACECQA for ABN or ACN, management type and day-level rating dates in the consent request.

## Hub verification (2026-10-29)

Spot-checked by the hub after the spoke returned.

- CSV URL pattern confirmed with HEAD requests on the national (`au`) files. Plain URL: `last-modified` Mon 27 Jul 2026, `cf-cache-status: HIT`, `age` about 93 days. Same URL with `?nocache=<epoch ms>`: `last-modified` Wed 28 Oct 2026 19:28 GMT, `cf-cache-status: MISS`, 14,782,633 bytes. Conclusion: ACECQA does regenerate the file daily; the plain URL serves a year-long CDN cache. A collector must append the `nocache` parameter and record `last-modified` with each snapshot. Open question 1 in the section above is answered.
- VECRA copyright page read directly: "All material provided on this website is provided under a Creative Commons Attribution 4.0 International licence", excluding images, branding and third-party content. Confirmed.
- NSW Department of Education copyright page read directly: "licensed under a Creative Commons Attribution 4.0 International (CC BY 4.0) licence", excluding logos, trademarks and third-party material. Confirmed.
