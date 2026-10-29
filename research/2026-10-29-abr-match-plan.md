# ABR match plan for GAP-003 (2026-10-29)

Status: the ABR bulk extract spike was not run. data.gov.au publishes a robots.txt of `User-agent: *` followed by `Disallow: /`, so the shared fetch helper refused the CKAN API call for `abn-bulk-extract`. We honour robots.txt, so nothing was downloaded and no licence text was captured from CKAN. Confidence in this finding: High (robots.txt read directly on 2026-10-29).

Written by the data-engineer spoke. Serves GAP-003 (no public ownership graph).

## What is not yet known

- The actual resource URLs and file sizes of the ABR parts. `[Verify This]`
- The licence text as published in CKAN metadata. The register audit note (`research/2026-10-29-register-acecqa-nqf-abr.md`, section C7) records CC BY 3.0 AU from a search snippet only. `[Verify This]`
- Whether the ABR hosts the same files on a crawlable host. The ABR page (https://abr.business.gov.au/Tools/BulkExtract) was readable in the earlier audit and links to data.gov.au. A human could download one part in a browser, which is not an automated crawl, and drop it where a script can snapshot it.

## Options to unblock

1. The project owner downloads one part by hand and places it in a scratch folder. A script then copies it into `data/raw/abr-bulk-extract/` with a sidecar recording the source URL, date and licence as read by the owner.
2. Ask the Australian Business Register or data.gov.au whether a polite, identified, rate-limited fetch of the bulk extract is acceptable despite the blanket `Disallow`. A written reply would go to `data/evidence/` by script.
3. Use the ABN Lookup web services instead (below).

## Normalisation

Applied to both sides before matching (implemented as `normalise_name` in `scrapers/profile_providers.py`, tested in `tests/test_profile_providers.py`):

1. Upper case.
2. Remove ACN tags such as "(ACN 123 456 789)".
3. Replace "&" with "AND". Delete apostrophes without a space. Replace every other non-alphanumeric run with one space. Collapse whitespace.
4. Canonicalise the trailing corporate form: PTY LTD, PTY LIMITED, PROPRIETARY LIMITED and P L become `PTY LTD`; LTD and LIMITED become `LTD`; INC and INCORPORATED become `INC`.
5. A looser key (`strip_corporate_suffix`) drops the tail entirely. Matches on the loose key are never auto-accepted.

## Match kinds

| match_kind | Test | Handling |
|---|---|---|
| exact_legal | ACECQA Legal Name equals ABR main name, byte for byte | strongest |
| exact_trading | ACECQA Trading Name equals an ABR business or trading name | weaker: trading names are not unique |
| normalised_legal | normalised Legal Name equals normalised ABR main name | strong |
| normalised_trading | normalised Trading Name equals a normalised ABR other name | weakest |

Accept automatically only a unique match with state agreement (ABR main business state against the ACECQA provider state). Everything else goes to a manual queue. Record `match_kind`, the state test result and a confidence value. Verify any ABN before it is shown publicly, on ABN Lookup.

Scope rules:

- Providers classed `likely_individual` are excluded from matching entirely. Their names are not loaded into the matcher, and ABR records with individual entity types (for example IND) are dropped at load.
- Match only the entity forms where an ABN or ACN is expected: company, incorporated_association, cooperative, trust_or_trustee. Government and church bodies often share an ABN across many services or hold none under that name.
- The ABR extract holds current names only. A renamed provider will not match.

## ABN Lookup web services fallback

https://abr.business.gov.au/Tools/WebServices is free but needs an authentication GUID. The project owner must register for it, read the limitations and user guide, and accept the web services agreement. We cannot register on the owner's behalf, and the GUID must not be committed. Rate limits are not stated on the page, so keep to the project minimum of 1.5 seconds between requests until the user guide says otherwise. Whether a name search method exists and what it returns is `[Verify This]`.

Cost shape: one request per distinct normalised name. There are about 7,000 non-individual providers, so about 7,000 requests, or roughly 3 hours at 1.5 seconds each, once the GUID exists.

## Expected precision problems

- Common names. "Little Learners Pty Ltd" and similar names can exist several times across ABR with different ABNs. Require a unique hit and state agreement.
- Franchise and brand trading names. Many unrelated providers trade under one brand, and a brand may be registered by a franchisor. Do not infer a shared owner from a brand name. Trading-name matches are lower confidence.
- Trustees. A provider shown as "X Pty Ltd as trustee for the Y Trust" holds an ABN under the trust, the trustee company, or both. The match could land on the wrong entity. Never state who benefits from a trust.
- Partnerships and sole traders. These carry individual names and are excluded under rule 2.
- Schools, councils and departments. A department or council may use one ABN for many services.
- Name changes and cancelled ABNs. The extract includes cancelled ABNs, so a match to a cancelled record is a signal to check, not a finding.
- A name match is not evidence of ownership or group membership. ASIC's free company dataset gives ACN to company name checks but no parent company.

## Open questions for the hub

1. Which unblock option does the owner prefer (manual download, written permission, or the ABN Lookup GUID)?
2. Confirm the licence wording from CKAN once reachable.
