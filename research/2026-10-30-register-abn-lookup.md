# Register audit: ABN Lookup web services agreement (2026-10-30)

Finding: nothing in the ABN Lookup Web Services Agreement prohibits the planned use (look up ABNs
and organisation names, keep a local cache of responses, publish derived provider-to-ABN links and
provider groups). The agreement grants a non-exclusive licence to access and use the services and
lets us give relevant extracts to third parties at our own risk. It says nothing on caching,
attribution or rate limits. Its one hard duty is to delete information on notice when the ABR
withdraws it to protect an individual's privacy.

Serves GAP-003 (no public ownership graph). Written by the data-engineer spoke at the hub's request
on 2026-10-30; the register-auditor spoke did not write this note, so the hub may wish to have it
reviewed. `[Verify This]`

## Summary

| Question | Answer | Clause | Confidence |
|---|---|---|---|
| Licence | Non-exclusive, non-transferable licence to access and use, for the term of the agreement | Licence | High |
| Extracts to third parties | Allowed, at our own risk: "relevant extracts" | Use of ABN Lookup Web Services | High |
| Storage or caching | Not addressed. No clause forbids storing responses; the web services page names "keeping ABN details stored in your database up-to-date" as a use | None (silence); web services page | Medium |
| Privacy withdrawal | Details may be withdrawn (for example to protect an individual's privacy). On notice we must delete all copies | Use of ABN Lookup Web Services | High |
| Attribution | Not required by the agreement. We must not imply Commonwealth endorsement or affiliation | Use of ABN Lookup Web Services | High |
| Accuracy | Provided "as is"; no warranty that data is correct, accurate, up to date or complete | Disclaimer | High |
| Rate or volume limits | None stated in the agreement, the web services page or the user guide pages read | None | Medium |
| Cost | Free of charge | Web services page | High |
| Suspension and termination | We may terminate at any time; they may suspend during a breach investigation, or terminate on 30 days' notice | Termination | High |
| JSON endpoints covered? | The definition names `abrxmlsearch` and `abrxmlsearchRPC` "or such other location as we may notify". The JSON service is published on the same site and uses the same GUID, so it is treated as covered | Definitions | Medium `[Verify This]` |

## Source

- https://abr.business.gov.au/Tools/WebServicesAgreement, "Web Services Agreement", version 9.9.7.
  Fetched 2026-10-30T04:42:53Z with `scrapers.common.fetch` (httpx, project User-Agent, robots.txt
  honoured). HTTP 200, 17,796 bytes, sha256
  `6f33a256865e10e87e2a18f48884b1264ce39e02e1d5c769991466db318b2aa8`. Read in full.
- https://abr.business.gov.au/Tools/WebServices (sha256 `53b6ab81...`), https://abr.business.gov.au/json/
  (sha256 `05edaed6...`), https://abr.business.gov.au/Documentation/WebServiceRegistration and
  https://abr.business.gov.au/Documentation/WebServiceMethods, all fetched 2026-10-30 for limits and
  methods.
- robots.txt at https://abr.business.gov.au/robots.txt (read 2026-10-30) disallows only
  `/AbnRefresh.aspx`, `/Tools/DownloadLookupTool` and `/Downloads/*.xlsm$`, then `Allow: /`. The
  `/json/` path is allowed. Confidence: High.

## Clauses, quoted

### Licence

> We grant you, during the term of this agreement and subject to these terms and conditions, a
> non-exclusive non-transferable licence to access and use the ABN Lookup Web Services.

### Extracts to third parties

> You may, at your own risk, provide relevant extracts of the ABN Lookup Web Services to third
> parties.

Reading: a derived table that says "provider PR-x matched ABN y (ABR entity name z, status
Active)" is a relevant extract. Publishing it later is therefore within the licence, subject to the
project's own rules (verification, legal review before Phase 5).

### Misrepresentation and endorsement

> You must not misrepresent your rights under this agreement or use the ABN Lookup Web Services in
> any way that is or may be false, misleading or deceptive.

> You must not represent or imply, or allow any associated person to represent or imply, that the
> Commonwealth endorses, approves, or is affiliated in any way with you or any use you may make of
> the ABN Lookup Web Services or any of your products or services.

Consequence for outputs: any public use should say the data comes from ABN Lookup and that the ABR
does not endorse the project. A name match must not be presented as an ABR statement of ownership
(that would be misleading).

### Privacy withdrawal

> You acknowledge that details that form part of the ABN Lookup Web Services may subsequently be
> withdrawn from the ABN Lookup database (for example to protect the privacy of an individual). If
> we notify you that specific information has been withdrawn you must immediately take all
> reasonable action to delete all copies of that information in your possession or control.

Consequence: the local cache `data/raw/abr-lookup/` must be deletable on notice. It is kept out of
git (`.gitignore`) partly for this reason, since a public commit cannot be fully recalled. Deletion
on notice would be a documented exception to the append-only rule for `data/raw/`, to be decided by
the project owner. `[Verify This]`

### Contact details

> You are responsible for ensuring that your contact details provided to us remain accurate and up
> to date.

### Service availability

> You acknowledge and agree that your use of the ABN Lookup Web Services is on an 'as is, as
> available' basis only.

> We may alter or, where there is reasonable cause, suspend the ABN Lookup Web Services at any
> time.

### Termination

> You may terminate this agreement at anytime.

> Access to and use of the ABN Lookup Web Services by you or any of your users may be suspended if
> we feel it is necessary to protect our interests or those of any other person while we are
> investigating any breach of security or possible breach of this agreement or while any such
> breach is being rectified by you.

> We may also terminate this agreement for our own reasons and without fault on your part providing
> we give you not less than 30 days prior written notice.

### Accuracy

> we do not warrant or make any representation that the ABN Lookup Web Services is correct,
> accurate, up to date, complete, reliable or is not subject to errors or malfunctions of any kind

Consequence: every ABN shown publicly must be verified on ABN Lookup (CLAUDE.md rule 1 already
requires this).

### Indemnity

> You indemnify us against any loss, damage, cost, expense, claim, proceeding or liability of any
> kind that we (or our personnel) may incur to any third party arising out of your use (including
> unauthorised use) of or access to the ABN Lookup Web Services

This is a reason for legal review before any public output (already the Phase 5 rule).

### Definition of the service

> ABN Lookup Web Services means the website located at: https://abr.business.gov.au/abrxmlsearch
> https://abr.business.gov.au/abrxmlsearchRPC or such other location as we may notify to you from
> time to time.

### Storage, caching, attribution, rate and volume

The agreement has no clause on any of these. The web services page lists "Keeping ABN details
stored in your database up-to-date" as an intended use, which supports storing responses. No rate
limit is published; the project minimum of 1.5 seconds between requests is applied. Confidence:
Medium (absence of a clause, on the pages read).

## JSON service as used

From https://abr.business.gov.au/json/ ("limited JSON support for ABN and name searching"):

- `AbnDetails.aspx?abn=<11 digits>&callback=<fn>&guid=<GUID>` returns keys `Abn`, `AbnStatus`,
  `AbnStatusEffectiveFrom`, `Acn`, `AddressDate`, `AddressPostcode`, `AddressState`,
  `BusinessName` (list), `EntityName`, `EntityTypeCode`, `EntityTypeName`, `Gst`, `Message`
  (observed 2026-10-30).
- `MatchingNames.aspx?name=<name>&maxResults=<n>&callback=<fn>&guid=<GUID>` returns `Message` and
  `Names`, each with `Abn`, `AbnStatus`, `IsCurrent`, `Name`, `NameType`, `Postcode`, `Score`,
  `State` (observed). No state filter is documented for the JSON name search; the SOAP
  `ABRSearchByNameAdvanced` methods have one. An exact name scored 99 in the one sample checked.
- `NameType` values seen: `Entity Name`, `Business Name`. Individuals are expected to appear as
  `Legal Name`; this was not observed directly. `[Verify This]`

## Privacy handling (CLAUDE.md rule 2)

- Providers classed `likely_individual` or `unknown`, or withheld, are never queried.
- ABR records with `EntityTypeCode` IND, or a type name containing Individual or Sole Trader, or an
  entity name that the project classifier reads as a person's name, are excluded; only the fact of
  exclusion is recorded.
- Raw responses are a local cache only (gitignored). Processed outputs record endpoint, query
  timestamp and response sha256.
- The GUID is never stored; every recorded URL has the `guid` parameter removed.

## Open questions for the hub

1. Confirm that the JSON endpoints count as "such other location as we may notify" (Medium).
   `[Verify This]`
2. Decide the procedure for deleting cached records on an ABR withdrawal notice, as an exception to
   the append-only rule for `data/raw/`.
3. Whether the register-auditor spoke should re-check this note.
