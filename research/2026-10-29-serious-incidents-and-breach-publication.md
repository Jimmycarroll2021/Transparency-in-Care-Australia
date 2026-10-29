# Serious incidents (GAP-007) and publication of confirmed breaches (GAP-001)

Researcher: source-researcher spoke. Date written: 2026-10-29. All retrieval dates below are 2026-10-29.

Method note. WebFetch returns a model summary of a page, not a verbatim copy, except for the ACECQA PDF, which was saved locally and read directly with `pdftotext`, so those quotes are verbatim and carry PDF page numbers (printed page numbers match PDF page numbers). Quotes from web pages are as returned by the fetch tool and are marked Medium confidence until checked against the live page. Several parliamentary and ACECQA pages returned HTTP 403 to the fetch tool (see "Blocked fetches"). I did not try to get around those blocks.

## Section 1: GAP-007, serious incident data is aggregate only

### 1a. The figures

Primary source: ACECQA, *National Quality Framework Annual Performance Report 2025* (December 2025). PDF fetched successfully, 64 pages, PDF creation date 4 December 2025. Source type: official_report. Confidence: High.
URL: https://www.acecqa.gov.au/sites/default/files/2025-12/2025-NQF-Annual-Performance-Report.pdf

| Claim (quoted exactly) | Where | Unit and period |
|---|---|---|
| "The rate of reported serious incidents in 2024/25 was 160 per 100 approved services, higher than the rate of 148 in 2023/24 and 139 in 2022/23." | Executive Summary, p.12 | Reported serious incidents per 100 approved services, financial years 2022/23, 2023/24, 2024/25 |
| "Figure 1.4 shows that in 2024/25 there was a rate of 160 reported serious incidents per 100 approved services, higher than the rate of 148 in 2023/24." | Chapter 1, p.21, Figure 1.4 | As above, all services. Chart also splits by service type; the per-type values could not be reliably assigned from the text extraction, so they are not recorded [Verify This] |
| Footnote 2: "Rate is calculated by dividing the number of serious incidents during the financial year by the number of approved services as at 30 June (the final day of that financial year), multiplied by 100." | p.21 | Defines the denominator and window |
| "Figure 1.5 shows that in 2024/25 there was a rate of 2.36 reported serious incidents per 100 approved places at centre-based services, a slight increase from 2.33 in 2023/24." | p.22, Figure 1.5 | Per 100 approved places, centre-based services only (family day care excluded because places are not recorded). The source has a dash after "services"; replaced with a comma to keep the file dash-free. |
| "Figure 1.6 hows [sic] that almost three-fifths (58%) of all approved services reported one or more serious incidents in 2024/25. For long day care services, the proportion is more than two-thirds (69%)." | p.23, Figure 1.6 | Share of approved services reporting at least one serious incident, 2024/25 |
| "Regulatory authorities may determine that a serious incident was associated with a breach of the requirements of the National Law and Regulations, this determination applied to just under 8% of reported serious incidents in 2024/25." | p.20 | Share of reported serious incidents |

Reading note: "160 per 100 approved services" is a rate of notifications, not the share of services affected. The share of services with at least one notification is 58% (p.23).

Breakdown by incident type. Table 1.1, p.21, "Proportion of reported serious incidents by incident type", % of all reported serious incidents. Columns shown for the three most recent years (2022/23, 2023/24, 2024/25); the table runs from 2016/17.

| Incident type | 2022/23 | 2023/24 | 2024/25 |
|---|---|---|---|
| Injury/Trauma/Illness | 77.8% | 77.4% | 77.7% |
| Emergency services attended | 12.6% | 12.5% | 11.5% |
| Child missing or unaccounted for | 8.0% | 8.4% | 8.9% |
| Child locked in/out of the service | 1.4% | 1.5% | 1.6% |
| Child taken away or removed | 0.2% | 0.2% | 0.3% |

Serious incidents associated with a confirmed breach. Table 1.6, p.28, "Proportion of serious incidents associated with a confirmed breach of the National Law and Regulations", all serious incidents: 6.6% (2022/23), 6.7% (2023/24), 7.9% (2024/25). By type, 2024/25: Injury/Trauma/Illness 2.5%; Emergency services attended 2.5%; Child missing or unaccounted for 50.6%; Child locked in/out of the service 61.2%; Child taken away or removed 54.8%. This is the link between GAP-007 and GAP-001: only a minority of notified incidents are tied to a confirmed breach, and the national table is aggregate only.

Rate by quality rating. Table 1.2, p.23: rate per 100 approved services in 2024/25 was 165 (Working Towards NQS), 162 (Meeting NQS), 165 (Exceeding NQS), 160 (all services including unrated). The report says: "In 2024/25, there is no notable difference in reporting rates."

Productivity Commission, Report on Government Services (RoGS) 2026, Part B, Section 3 (Early childhood education and care). Source type: official_report. Confidence: Medium (page summary via fetch tool; Table 3A.33 itself was not opened).
URL: https://www.pc.gov.au/ongoing/report-on-government-services/child-care-education-and-training/early-childhood-education-and-care/
The page shows "Latest update 3 June 2026" and does not state an original publication date. As returned by the fetch tool:
- "Nationally in 2024-25, there were 159.8 serious incidents per 100 NQF approved services, up from 148.1 in 2023-24" (figure 3.7).
- "The majority of incidents involved serious injury or trauma to, or illness of, a child (77.7% of all serious incidents) followed by incidents where the attendance of emergency services was sought (11.5%) (table 3A.33)."
- "Nationally in 2024-25, there were 222.2 confirmed breaches per 100 NQF approved services, up from 200.8 in the previous year." (table 3.6a is cited for the breach rate by service type; family day care 460.9, centre based day care 278.7.)
The 2022-23 RoGS value was not retrieved; the ACECQA report supplies 139 for 2022/23. Data tables are on the RoGS 2026 data downloads page (https://www.pc.gov.au/ongoing/report-on-government-services/2026/data-downloads/, URL as given by the fetch tool, not opened).

Cross-check: ACECQA 160 and 148 match RoGS 159.8 and 148.1 after rounding. ACECQA's confirmed breach rates (222 in 2024/25, 201 in 2023/24, 193 in 2022/23, p.12) match RoGS 222.2 and 200.8.

### 1b. Is there a breakdown by provider management type?

ACECQA 2025 report: No. Evidence: I extracted the full text and searched for "management type", "provider type", "for profit" and "for-profit". The only hits are service-composition statistics on p.4 (for example "'private for profit' providers operated more than two-thirds (71%) of long day care services"), which are counts of services, not incident rates. The serious incident breakdowns in the report are by incident type (Table 1.1), service type (Figure 1.4), quality rating (Table 1.2) and association with a confirmed breach (Table 1.6). Confidence: High.

RoGS 2026: No, on the evidence available. The fetch tool reported "No breakdown by provider management type (for example, for-profit or not-for-profit) is shown for confirmed breaches or serious incidents. Management type appears only in the funding context table (table 3.2)." Confidence: Medium until Table 3A.33 is opened.

Secondary lead, not verified: a University of Sydney news item (https://www.sydney.edu.au/news-opinion/news/2026/03/02/serious-incidents-in-childcare-centres-are-still-rising.html, dated 2 March 2026 in the URL, source type academic) is reported by a search snippet to say the national agency's reports "do not let us compare serious incident rates of for-profit versus not-for-profit services". I did not open it. `[Verify This]`.

State regulator annual reports: not checked. No evidence found either way. Open question for a follow-up spoke (NSW, Victoria, Queensland annual reports).

### 1c. Are serious incidents published per service?

No official source publishing serious incident counts or notifications per service was found. Confidence: Medium. This is absence of evidence from a search, not a quote from a regulator.
- ACECQA publishes aggregate data only: the Annual Performance Report and the quarterly NQF Snapshot (p.29 says ACECQA "publishes the total number of quality assessment and rating visits compared to all other visits"). NSW publishes "Regulatory data" described as "The latest quarterly data showing compliance and enforcement actions, notifications and complaints submitted and quality ratings" (https://www.nsw.gov.au/departments-and-agencies/nsw-early-learning-commission, retrieved 2026-10-29). That description does not say per service. The linked Regulatory data page was not opened.
- What IS published per service is enforcement actions on StartingBlocks (see Section 2d), not notifications.
- I did not find a regulator statement that per-service incident data is confidential. A confidentiality statement was NOT confirmed. Lead to check: National Law information-sharing and confidentiality provisions, and any ACECQA or NSW freedom-of-information disclosure log entry. `[Verify This]`.
- ACECQA page "Helping services communicate with families on enforcement actions" (https://www.acecqa.gov.au/helping-services-communicate-families-enforcement-actions) returned 403 to the fetch tool.

### 1d. Official statement on better reporting versus more harm

The official position is that the data cannot tell the two apart. ACECQA 2025 report, p.20 (official_report, High confidence): "It is also very challenging to make robust comparisons of the rate of reported serious incidents across service types or financial years for a number of reasons. In common with other sectors, dealing with both the likely 'over' and 'under' reporting of serious incidents from different parts of the sector is particularly difficult."
It lists reasons a provider might report a high number: "Robust and comprehensive reporting mechanisms", "Overly cautious reporting procedures", "Unique child cohorts and service circumstances", "Lack of understanding of what constitutes a serious incident", "Poor health and safety standards." Reasons for a low number include "Lax reporting procedures" and "Concern around reputational impact."
Also p.20: "most reported serious incidents do not result in compliance action being taken by state and territory regulatory authorities."
Related: p.23 says historically "services with higher quality ratings were consistently more likely to report serious incidents", but "In 2024/25, there is no notable difference in reporting rates."
Reporting rules changed on 1 September 2025: "mandatory 24-hour reporting of any allegations or incidents of physical or sexual abuse" (p.16 of the report, executive summary developments list). This can affect future rates and is not a cause of the 2024/25 rise.
No official source found that attributes the rise to either better reporting or more harm. An Early Childhood Australia piece on RoGS (https://www.earlychildhoodaustralia.org.au/the-spoke/quality-and-safety-in-ecec-what-does-rogs-really-say-hint-it-isnt-what-you-read-in-some-media-reports/, source type other, advocacy, not opened) appears in search results as a lead only. `[Verify This]`.

## Section 2: GAP-001, confirmed breaches not published

### 2a. What did the NSW Legislative Council inquiry recommend?

Inquiry: Legislative Council Portfolio Committee No. 3 - Education, inquiry into the early childhood education and care sector in New South Wales, established 20 March 2025 (search result, parliamentary, `[Verify This]`). Final report: Report No. 55, dated 20 May 2026 (parliament.nsw.gov.au file name "Report No. 55 - PC3 - ECEC - 20 May 2026 - FINAL.pdf"; date from a search result and a provider statement dated 20 May 2026).
Report PDF URL: https://www.parliament.nsw.gov.au/lcdocs/inquiries/3098/Report%20No.%2055%20-%20PC3%20-%20ECEC%20-%2020%20May%202026%20-%20FINAL.pdf
STATUS: could not be read. The fetch returned 403, as did the inquiry page. Recommendation numbers and exact text were NOT obtained. Do not cite any recommendation number from this note.

Secondary reporting (media, leads only, all `[Verify This]`):
- thesector.com.au, 21 May 2026 (https://thesector.com.au/article/nsw-parliamentary-inquiry-ecec-sector-major-reform-warning): the report calls for "mandatory assessment and rating of every service at least every three years", recommends publishing the regulator's internal risk ratings for services, and calls for "significantly more unannounced spot checks". It records concern that the regulator "failed to respond appropriately to services with long histories of non-compliance". It does not mention publishing per-service compliance histories or an enforcement register. The report reportedly has 35 recommendations.
- thesector.com.au, 25 August 2026 (https://thesector.com.au/article/nsw-ecec-inquiry-government-response-sector-reform): the NSW Government response (received 20 August 2026) "rejected the Committee's recommendation that internal risk ratings" for individual services be made public, because the ratings "are regulatory intelligence used to prioritise activity" and publishing them "could unfairly affect services". It says other transparency measures "have been strengthened, including requirements around the publication of compliance and quality history". No recommendation numbers given.
- An earlier review is relevant: the Independent Review into the NSW ECEC Regulatory Authority, Recommendation 2, reportedly asks for a legislative amendment requiring services to display compliance history alongside quality ratings (https://education.nsw.gov.au/about-us/strategies-and-reports/our-reports-and-reviews/independent-review-into-the-nsw-ecec-regulatory-authority/recommendations, appeared in search results, not opened). `[Verify This]`.
- A separate Report No. 54 (Portfolio Committee No. 3, on the National Law amendment bill 2025) exists at https://www.parliament.nsw.gov.au/tp/files/191931/Report%20No.%2054%20-%20Portfolio%20Committee%20No.%203-%20National%20Law%20Amdt%20Bill%202025.pdf. Not opened. Likely to contain recommendations on the bill's transparency provisions.

### 2b. What did the October 2025 NSW legislation change on publication?

Name: the Department of Education page is titled "The Children (Education and Care Services National Law Application) Amendment Act 2025 (NSW)" (URL: https://education.nsw.gov.au/early-childhood-education/regulation-and-compliance/regulation-assessment-and-rating/regulatory-framework/the-children--education-and-care-services-national-law-applicati). The suggested bill PDF (https://www.parliament.nsw.gov.au/bill/files/1621/LC%2010410.pdf) returned 403, so the bill, explanatory note and second reading speech were NOT read.

What the official sources say (official, ministerial release dated 23 October 2025, https://www.nsw.gov.au/ministerial-releases/nation-leading-child-safety-reforms-pass-nsw-parliament, issued by the Minister for Education and Early Learning, with the quoted statement from the Acting Minister; Medium confidence as quoted by the fetch tool):
- Services are "expected to display a short-form compliance history at their premises and on their website".
- The Regulator can "publish more information about high-risk services, including details of current investigations".
- "Parents will be notified when the regulatory authority commences an investigation into a serious incident".
- Other changes: power to suspend or revoke quality ratings during or following investigations; supervision orders on individual educators; "A 900 per cent increase to maximum penalties for large providers operating 25 or more services"; limitation period for offences to run "from when the regulator is notified".
The release does not mention a public register by name.

What must be published, by whom, for how long, from the Department of Education guideline page (official, https://education.nsw.gov.au/early-childhood-education/regulation-and-compliance/compliance-and-enforcement-actions/displaying-compliance-and-quality-history, retrieved 2026-10-29, Medium confidence):
- By whom: the approved provider or service displays the history template. The Regulator's own publication powers are described only in general terms.
- What: "compliance actions" (cancellations, suspensions, conditions, infringement notices, compliance notices, compliance directions, enforceable undertakings, emergency action notices, prohibition notices, and directions to exclude an inappropriate person, including those under review); prosecutions (offences with a plea of guilt, finding of guilt or conviction, plus the penalty); and quality history (the two most recent ratings).
- For how long: compliance history covers the past 2 years (or since approval or transfer to the current approved provider). Updated within 7 days of a relevant compliance action appearing on the NQA ITS "Compliance Summary".
- Where: displayed so it is "clearly visible to anyone from the main entrance"; the page does not say each service's history must be published online, except prosecutions which providers "must publish" (location not specified).
- Start: the regulator will not enforce the requirement until 20 November 2025.
- Services with nothing to report must display "Our service has no statutory compliance history to display".

Does it include confirmed breaches? On this evidence, no. The listed items are formal compliance and enforcement actions and prosecutions outcomes. "Confirmed breach" does not appear as a category in the displayed history. Confidence: Medium, pending the bill and explanatory note. This matters for GAP-001: a confirmed breach that does not lead to a listed action is not published per service. CLAUDE.md rule 6 applies: breach, confirmed breach, enforcement action and prosecution must stay distinct.

### 2c. Does the NSW Early Learning Commission publish confirmed breaches per service?

Retrieved: https://education.nsw.gov.au/early-childhood-education/regulation-and-compliance returned a 302 redirect to https://www.nsw.gov.au/departments-and-agencies/nsw-early-learning-commission (official). Listed publications:
- "Regulatory data": "The latest quarterly data showing compliance and enforcement actions, notifications and complaints submitted and quality ratings." (https://education.nsw.gov.au/early-childhood-education/regulation-and-compliance/regulatory-data)
- "Register of enforcement actions": "Enforcement actions taken against early childhood providers and educators, including prosecutions, cancellations and more." (https://education.nsw.gov.au/early-childhood-education/regulation-and-compliance/compliance-and-enforcement-actions)
- Compliance monitoring, displaying compliance history, investigation process (which "does not mention publishing them"), internal reviews.
Answer: the page does not state that confirmed breaches per service are published. The register covers enforcement actions. The register and regulatory data pages were not opened, so what they contain per service is unconfirmed. Confidence: Medium. Note: an educator-level register entry would involve individuals; the project must not record any individual's name.
Search snippets (not verified, `[Verify This]`) say the Commission was established on 1 December 2025.

### 2d. Any national move?

Published to families already (official, ACECQA 2025 report p.16, High confidence): "increased transparency for families on StartingBlocks.gov.au: Additional information has been published on StartingBlocks.gov.au about conditions on a provider or service approval, as well as the most recent date the service was visited by a state and territory regulatory authority."

Enforcement actions on StartingBlocks. A news report (The Leader, 8 September 2025, media, https://www.theleader.com.au/story/9060208/childcare-centres-must-display-compliance-breaches) says StartingBlocks "will also begin publishing details of compliance breaches and enforcement actions" from 1 November (2025) and that centres would have to display information. `[Verify This]`: the article is media and its wording "compliance breaches" is looser than the regulatory terms.
ACECQA's own pages appeared in search results: "Communications toolkit: StartingBlocks.gov.au transparency updates Nov 2025" (https://www.acecqa.gov.au/communications-toolkit-startingblocksgovau-transparency-updates-nov-2025) and "Helping services communicate with families on enforcement actions" (https://www.acecqa.gov.au/helping-services-communicate-families-enforcement-actions). Per the search snippets (not verified): enforcement actions published on StartingBlocks in late November 2025, a service page can show actions from the past 2 years, six types (conditions, amendments, suspensions, compliance notices, emergency action notices, enforceable undertakings), and the reason for a compliance notice or enforceable undertaking is not shown. If confirmed, that is publication of enforcement actions, NOT of confirmed breaches. `[Verify This]`.

Education Ministers. A search result for the July 2026 Education Ministers Meeting communique (https://www.education.gov.au/download/20190/communiques-education-ministers-meetings-2026/45187/education-ministers-meeting-communique-july-2026/pdf and the page https://www.education.gov.au/node/20520) was returned but all fetches returned 503, so the text is NOT verified. From the search summary only: Ministers agreed a second tranche of quality and safety reforms "relating to supervision, transparency, and fencing safety"; legislative amendments to be prioritised with introduction planned in 2027; an Early Education and Care Commission to be explored with further advice at the October 2026 meeting. `[Verify This]` all of it. Not checked: the October 2025 and February 2026 communiques, and the October 2026 meeting outcome.

Conclusion for 2d: no verified national agreement to publish confirmed breach findings per service. Enforcement action publication on StartingBlocks is the closest verified-by-lead item.

## Implications for the ledger (for the gap-analyzer, not applied here)

- GAP-007: national serious incident data is aggregate (by incident type, service type, rating, and association with a confirmed breach). No management type breakdown in ACECQA or RoGS (High and Medium confidence). Per-service data: none found. Official sources say the trend cannot be read as either better reporting or more harm.
- GAP-001: NSW and national changes publish enforcement actions and prosecutions, over a 2 year window, not confirmed breaches as such. The NSW inquiry recommendation to publish internal risk ratings was rejected by the Government (secondary source). Primary text of the inquiry report, the bill and the communique remains unread.

## Blocked fetches (retry later)

- https://www.parliament.nsw.gov.au/bill/files/1621/LC%2010410.pdf (403)
- https://www.parliament.nsw.gov.au/committees/inquiries/Pages/inquiry-details.aspx?pk=3098 (403)
- https://www.parliament.nsw.gov.au/lcdocs/inquiries/3098/Report%20No.%2055%20-%20PC3%20-%20ECEC%20-%2020%20May%202026%20-%20FINAL.pdf (403)
- https://apo.org.au/sites/default/files/resource-files/2026-03/apo-nid333907.pdf (403)
- https://www.acecqa.gov.au/helping-services-communicate-families-enforcement-actions (403)
- https://www.education.gov.au/node/20520 and the July 2026 communique PDF and DOCX (503, three attempts)
- A Bash call to read proxy documentation was denied by the permission classifier and was not retried.

## Open questions

1. What are the exact numbers and text of Report 55 recommendations on transparency? (Needs a source that is reachable.)
2. What do the Act, explanatory note and second reading speech say about regulator publication and confirmed breaches?
3. What does the NSW Register of enforcement actions contain per service?
4. Does any state regulator annual report break serious incidents down by management type?
5. Is there a regulator statement that per-service serious incident data is confidential?
6. What did the July 2026 and October 2026 Education Ministers Meetings agree on transparency?
7. Does RoGS Table 3A.33 contain any breakdown beyond jurisdiction and incident type?

