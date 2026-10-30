# Gap evidence: GAP-004 and GAP-006 against official sources (2026-10-30)

Finding: both gaps should be revised, not validated as written.

- **GAP-004:** none of the official sources examined publishes a count or national list of
  services outside the NQF, and quality coverage and publication vary by jurisdiction. The "473
  services" figure was not found in any official source examined. NSW now assesses and rates its state-law services, which contradicts the
  baseline's claim that such services show "Not rated by NQF" and nothing more.
- **GAP-006:** for a single service this is mostly a presentation issue, because rating dates are
  public in the ACECQA register. The real, narrower gap is that none of the official sources
  examined publishes the distribution of rating age or a stated reassessment cycle.

`data/gap-ledger.json` statuses are unchanged (both `hypothesis`) pending the owner's decision.

Evidence compiled by the hub from official pages; ROGS figures re-checked against the page on
30 October 2026. Written up by an implementer spoke at the hub's request. No individual is named in this note.

## GAP-004: services outside the NQF

Recommendation: **revise**. Restate the gap as "none of the official sources examined publishes
a count or national list of non-NQF services; quality coverage and publication vary by
jurisdiction".

| Finding | Source and section | Confidence |
|---|---|---|
| Some services are licensed or registered by states and territories but not approved under the NQF (examples given: occasional care, mobile preschools). The data is attributed to "state and territory governments, unpublished". No count is given. | Report on Government Services 2026, Early childhood education and care, section 7 "NQF quality and compliance": https://www.pc.gov.au/ongoing/report-on-government-services/child-care-education-and-training/early-childhood-education-and-care/ | High |
| NSW State Law covers mobile, occasional care and MACS services. These must take part in assessment and rating on the same basis as National Law services. The page does not say whether those ratings are published. | NSW Department of Education, "Amendment of the Children (Education and Care Services) Supplementary Provisions Act 2011", summary of changes, updated 1 October 2026: https://education.nsw.gov.au/early-childhood-education/regulation-and-compliance/regulation-assessment-and-rating/regulatory-framework/amendment-of-the-children-education-and-care-services-supplementary-provisions-act-2011 | High |
| The NSW quality data page covers NQF services only. | NSW Department of Education, Regulatory data, "Quality data": https://education.nsw.gov.au/early-childhood-education/regulation-and-compliance/regulatory-data/quality-data | High |
| In Victoria, NQF assessment and rating does not cover occasional care and limited hours services regulated under the Children's Services Act 1996. | VECRA, "Assessment and quality rating of early childhood services", updated 1 June 2026: https://www.vecra.vic.gov.au/assessment-quality-rating-early-childhood-services | High |
| In Queensland, QEC services are regulated under the Education and Care Services Act 2013 and the register is updated annually. The page states neither a rating process nor a count. | Queensland Early Childhood, "Education and Care Services Act", updated 28 August 2026: https://earlychildhood.qld.gov.au/regulation/education-and-care-services-act | High |
| The Queensland quality data page covers NQF services only. | Queensland Early Childhood, Regulatory data, "Quality data": https://earlychildhood.qld.gov.au/regulation/regulatory-approach/regulatory-data/quality-data | High |

Correction needed elsewhere: `docs/01-gap-analysis.md`, Gap 4, says non-NQF services "show as
'Not rated by NQF' and nothing more". The NSW page above shows NSW state-law services are assessed
and rated. The baseline should be corrected; this note does not edit it.

Inferences:

- The ROGS attribution "state and territory governments, unpublished" shows that state and
  territory governments hold unpublished information on services outside the NQF. It does not
  show that they hold a count of these services. Whether such counts exist is a question for a
  question on notice or a freedom of information request. Medium. `[Verify This]`
- A 2021 Closing the Gap early childhood care and development sector strengthening plan reportedly
  says 59 of 154 CCCFR (Community Child Care Fund Restricted) services were outside the NQF's
  scope. This is dated, partial and not a total; the PDF was not read. Low. `[Verify This]`

## GAP-006: rating age

Recommendation: **revise**. For a single service, the rating date is already public in the ACECQA
register, so the gap is mostly about presentation. The narrower gap is that none of the official
sources examined publishes how old ratings are across all services or states a reassessment cycle.

| Finding | Source and section | Confidence |
|---|---|---|
| At 30 June 2025, 92.8% of NQF approved services had a quality rating, and 24.5% were assessed or reassessed in the previous 12 months. No cycle and no breakdown by time since rating are given. | Report on Government Services 2026, Early childhood education and care, Table 3A.29 (same page as above) | High |
| StartingBlocks states no reassessment cycle. New services receive a first rating within 18 months. | StartingBlocks, "The assessment and rating process": https://startingblocks.gov.au/resources/choosing-a-service/the-assessment-and-rating-process and "Service quality ratings": https://startingblocks.gov.au/resources/choosing-a-service/service-quality-ratings | High |
| Victorian services are assessed 12 to 18 months after opening "and regularly after that". No interval is stated. | VECRA, "Assessment and quality rating of early childhood services" (same page as above) | High |

Inferences:

- If 24.5% of services are assessed each year and that rate is steady, the average cycle is
  roughly four years. This is arithmetic only, not an official figure, and must not be published
  as one. Low. `[Verify This]`
- NSW Legislative Council Report 55 (20 May 2026), Recommendation 14, reportedly calls for every
  service to be rated at least every three years. Not read (the PDF returned HTTP 403). Low.
  `[Verify This]`

## Open questions

1. What did the Education Ministers Meeting communique of November 2026 say on non-NQF services
   or reassessment cycles?
2. What was said at Senate Education and Employment Supplementary Estimates, 28 to 29 October
   2026 (Hansard)?
3. Does NSW publish the ratings of its state-law services, and if so, where?
4. PDFs not readable here, to be checked by another route: ACECQA Letter of Expectation 2025 to
   2027; NQF Snapshot Q2 2026; NSW Legislative Council Report 55; the 2025 NSW Independent Review;
   the Closing the Gap early childhood care and development sector strengthening plan.
5. Owner decision: the new status and wording of GAP-004 and GAP-006 in `data/gap-ledger.json`.
