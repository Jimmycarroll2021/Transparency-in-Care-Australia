# Transparency in Care Australia — Gap Analysis

**Date:** 27 October 2026
**Status:** Research brief. No build decision taken.
**Purpose:** Establish (a) what the Four Corners investigations actually found, (b) what childcare
data is already public, (c) whether a real gap exists that a public-interest site could fill.

---

## TL;DR

There is a real gap, but it is **not** the one the project name implies.

Service discovery and quality ratings are solved — StartingBlocks.gov.au does this well, and two
commercial aggregators already mirror the same ACECQA feed. Building another "search a childcare
centre" site would duplicate working infrastructure.

The genuine gaps are four:

1. **Confirmed breaches are not published anywhere.** Only the small minority that escalate to
   formal enforcement appear publicly. Four Corners found 320 confirmed breaches at one operator's
   NSW centres with zero infringement notices issued — none of which is publicly visible.
2. **Enforcement data is fragmented across eight jurisdictions in incompatible, mostly
   non-machine-readable formats.** NSW publishes quarterly PDFs. Victoria publishes monthly HTML
   pages. No one joins them.
3. **No public ownership graph.** You cannot ask "show me every service this corporate group
   operates, across all states and brands, with their combined regulatory history."
4. **473 services sit entirely outside the National Quality Framework** and have no public quality
   data at all. No public list of which ones exists.

**The hard blocker is not engineering — it is licensing.** ACECQA's terms of use expressly prohibit
using their content "as the source of quality rating data for regulated services," which is
precisely what this project would do. That needs resolving in writing before a line of code is
worth writing.

---

## 1. What Four Corners actually found

Three episodes, reported by Adele Ferguson, plus a series of 7.30 reports and online articles.

### 1.1 "Betrayal of Trust" — March 2025

- Examined abuse, neglect and injury across a sector spending ~$20bn/year.
- Found the sector failing to prioritise child safety over profit.
- Three centres linked to one group attracted **360+ breach, show-cause, prohibition and emergency
  action notices between 2014 and 2024**.
- One centre recorded **136 confirmed breaches over 10 years**.
- 10% of centres had never been given a quality rating; a similar share operated under staff waivers.
- For-profit long day care consistently underperformed not-for-profit against the NQS.
- Named operators: Affinity Education (private-equity owned, worst centre suspended), 3 Bears (shut
  down after a decade of non-compliance; a child kept in a van for three hours to hide them from the
  regulator), Jumpstart (closed, never met NQS; toddlers strapped in highchairs up to six hours/day).
- **Outcome:** NSW parliamentary inquiry; 30 NSW reforms passed 23 October 2025; federal policy
  announcements.

### 1.2 "Hunting Ground" / childcare paedophile crisis — October 2025

- **~150 childcare workers** identified as convicted, charged or credibly accused of sexual abuse or
  inappropriate conduct. 42 convicted; half sentenced in the last five years; 14 more before the
  courts; 13 cannot be named due to suppression orders.
- **More than three reports** of sexual or physical abuse in childcare are made **each working day**.
- Only ~15% of child sexual abuse reports lead to charges, ~2% to conviction. 84% of victims never
  disclose in their lifetime.
- **700+ cases involved missing, expired or unverified Working With Children Checks.**
- 82 Queensland centres received breaches for children absconding in Jan–Jun 2025 alone.
- Union survey: 77% of educators said their centre was understaffed at least weekly.
- Penrith case: 25 children, about half under two, supervised by two educators where six were
  required.
- **Only About Children: 320 confirmed breaches across NSW centres (Jan 2024 – Sep 2025), zero
  infringement notices issued.**
- Across hundreds of serious supervision breaches, the investigation found **one fine — $200**,
  after a child escaped a fence.
- Joshua Dale Brown, charged July 2025 with 70+ child sex offences, worked for G8 and Affinity and
  held a **valid Victorian Working With Children Check**.

### 1.3 "Monstrous" — 26 October 2026 (most recent)

- Centres on Injinoo Childcare Centre, Cape York, Queensland. Edwina Ling assaulted three boys aged
  13–30 months; CCTV captured **82 assaults** over three days (55 of them on the 13-month-old).
  Sentenced to four years, one-year non-parole. Pleaded guilty to 80 counts of common assault and
  two of assault occasioning bodily harm.
- **Key finding: 473 childcare services across Australia operate outside the National Quality
  Framework.** They include occasional care, some long day care, and remote-area services including
  Aboriginal and Torres Strait Islander community-controlled organisations. Injinoo was one — it was
  regulated under separate Queensland law, was never assessed against the NQS, and parents had no
  quality rating to check. NQF safeguards on supervising sleeping children and bus checks did not
  apply.
- State governments have agreed to bring **142** of the 473 under the NQF. The fate of the remaining
  **331 is unstated**. [Verify This — the 142 figure appears in ABC coverage and a syndicated
  headline; confirm against the education ministers' communiqué.]
- Commonwealth has acted against 120 centres under new subsidy powers; 12 have lost CCS access;
  ~half of the 120 have since met standards. 600 service cancellations in the last reporting period.
- Abuse at Injinoo continued for about a week after a visiting educator raised concerns. The report
  to police came from outside the organisation. The operator says it is not required to review CCTV
  daily. The family says it has **never received the Queensland regulator's internal report**,
  despite repeated requests.
- Structural criticism unchanged: Gabrielle Meagher (researcher) says the system's architecture is
  untouched; Georgie Dent (The Parenthood) says the subsidy model drives for-profit expansion
  without guaranteeing quality.

### 1.4 The transparency failure that made the reporting possible

This is the single most important point for this project.

Four Corners could not obtain regulator records through FOI — requests were too slow and heavily
redacted. The documents were ultimately obtained through a **NSW Legislative Council Standing Order
52 production order**, then withheld under parliamentary privilege until an independent arbiter
ruled for release. **More than 200,000 pages** were eventually received.

Everything in section 1.1 and 1.2 above came from records that already existed inside government and
were not public. That is the gap, stated plainly: the data exists; the public cannot see it.

A 2025 NSW independent review separately found services on a **secret government list of "very high
risk" providers that were publicly rated as "Meeting" the national standards.**

---

## 2. What is already public — source inventory

| Source | Contents | Format | Machine-readable? | Coverage |
|---|---|---|---|---|
| **ACECQA National Registers** | Approved services + approved providers; name, address, service type, approval number, provider link | Online view + **CSV export**, per state/territory and national | **Yes** | All NQF services, updated daily from NQA ITS |
| **ACECQA NQF Snapshots** | Quarterly ratings data + NQS time series Q3 2013 – Q2 2026 | Downloadable data files | Yes (aggregate) | National, aggregate only |
| **ACECQA NQF Annual Performance Report** | Serious incident rates, compliance activity | PDF | No | National, aggregate only |
| **StartingBlocks.gov.au** | Ratings, fees, vacancies, inclusions, CCS estimator, last regulator visit date, current conditions, provider-linked services, enforcement-action flag (2-year window) | Website (Next.js, Sanity CMS) | **No public API, no bulk export** | NQF services only |
| **Commonwealth Dept of Education enforcement register** | CCS approval suspensions/cancellations, civil penalty orders, conditions, criminal convictions (s199B FAA Act) | Web page | No | Rolling **12 months** only; older actions on a separate page |
| **NSW register of published enforcement actions** | Provider, service name, location and/or nominated supervisor | **Quarterly PDFs** | **No** | Jan 2025 onward; retained 5 years. Prosecutions published separately |
| **VECRA (Vic) enforcement actions** | Service + provider details, approval numbers, action taken, reason with National Law/Reg references, date issued | **Monthly HTML pages** | **No bulk/CSV/API** | Published only after review periods lapse |
| **Queensland register of published enforcement actions** | Fines, cancellations, suspensions | Web page | No | — |
| **data.gov.au / data.qld.gov.au** | Queensland Education and Care (QEC) licence register | CSV | Yes | **Non-NQF Queensland services only** — explicitly excludes NQF services |
| **National Early Childhood Worker Register** | ~304,000 workers, ~500,000 positions, 96% of services enrolled | Regulator system | n/a | Live from 27 Feb 2026. **Not public-facing.** WA voluntary |

### 2.1 What StartingBlocks added in 2025 and what it still withholds

September 2025 added: last regulatory authority visit date, conditions currently placed on services
and providers, and provider-linked services.

November 2025 added: an enforcement-action flag covering the **past two years**, across six action
types — conditions on approval, amendment of approval, suspension of approval, compliance notices,
emergency action notices, enforceable undertakings.

What it still does **not** show, per ACECQA's own page:

- The **reasons** for compliance notices, emergency action notices or enforceable undertakings.
- Visit findings, visit type, or the outcome of any complaint or incident.
- A full register of compliance actions — the page tells families to **ask the service for it**.
- Any statement of whether an absent flag means no compliance issues.
- Enforcement actions "may be made public depending on the circumstances," so the flag is
  acknowledged to be incomplete.

Non-NQF services display a grey **"Not rated by NQF"** label and nothing else.

### 2.2 Who is already building in this space

- **ChildcareScan** and **AU Childcare Finder** — both mirror ACECQA ratings for ~18,200–18,500
  centres. Neither surfaces enforcement history. Both are commercial.
- Nobody found doing cross-jurisdiction enforcement aggregation or ownership mapping.
- The Macquarie University analysis that **56% of Little Zak's centres had enforcement action in the
  prior two years** had to be done by academics. A parent cannot run that query. [Verify This —
  reported in media as an analyst's figure, not an official regulator statistic.]

---

## 3. The gaps, ranked

### Gap 1 — Confirmed breaches are invisible (highest value, hardest)

**Confidence: High.** Only formal enforcement actions are published. Confirmed breaches — the
regulator's own finding that a service broke the law — are not published at all, anywhere, by any
jurisdiction.

The evidence that this matters is overwhelming: 320 confirmed breaches at one operator with zero
infringement notices; 136 confirmed breaches at a single centre over a decade; hundreds of serious
supervision breaches producing one $200 fine. A parent checking StartingBlocks for any of those
centres would have seen a clean enforcement flag.

**Why it is hard:** this data is not published. Obtaining it means FOI (slow, redacted, as Four
Corners found) or parliamentary production orders (not available to a private project). This gap
cannot be closed by aggregation. It can only be closed by campaigning for publication — or by
systematic FOI as a long-run programme.

### Gap 2 — No joined national enforcement picture

**Confidence: High.** Eight jurisdictions, three formats, no common key exposed publicly, no
historical series. NSW's quarterly PDFs and Victoria's monthly HTML pages cannot be compared without
manual extraction.

**This is tractable.** The ACECQA national registers provide a clean spine (service approval number,
provider approval number, updated daily, CSV). Parsing NSW PDFs and VECRA monthly pages onto that
spine is straightforward engineering. Nobody has done it.

### Gap 3 — No public ownership graph

**Confidence: High.** StartingBlocks shows other services operated by the same *approved provider*.
It does not map corporate ownership: a group operating under multiple approved-provider entities,
multiple brands, across state lines, with acquisitions over time, appears as unrelated services.

Given that the Four Corners findings are overwhelmingly about *operators* rather than individual
centres, and that private equity ownership is a central theme, this is the question the public most
needs answered and cannot answer.

**Tractable** by joining ACECQA provider records to ABN/ASIC company data.

### Gap 4 — The 473 services outside the NQF

**Confidence: High that the gap exists; Low on the detail.** No public list exists of which 473
services these are, where they are, how many children they serve, or which state instrument
regulates each. They show as "Not rated by NQF" and nothing more. 142 are to be brought in; the
other 331 are unaccounted for publicly.

**Partly tractable.** Queensland's QEC register is on data.gov.au as CSV. Other states' equivalents
would need locating. Simply *publishing the list* — "here are the 473, here is who regulates each,
here is what standard applies" — would be a genuine first.

Caution: these include Aboriginal and Torres Strait Islander community-controlled services in remote
areas. A naive "unregulated = unsafe" framing would be both wrong and harmful. Many are
under-resourced, not negligent.

### Gap 5 — No per-service history

**Confidence: High.** Ratings and conditions are shown as current state. A centre rated Working
Towards for six years that was upgraded last month is indistinguishable from one that has been
Meeting for a decade. ACECQA publishes a national time series in aggregate but not per-service
publicly.

**Tractable, and cheap.** Snapshot the ACECQA register daily and you build the history yourself from
day one. The archive becomes more valuable every month. This is the single highest
value-per-engineering-hour item on the list.

### Gap 6 — Assessment recency is not surfaced as a risk signal

**Confidence: Medium-High.** Many services go more than four years between assessment visits; in
some states the gap reaches ten. StartingBlocks shows the last visit date but gives it no context. A
rating that is eight years old is a weaker signal than a rating from last quarter, and nothing on
the page says so.

**Trivially tractable** and genuinely useful: "this rating is 7.2 years old; the national median is
X."

### Gap 7 — Serious incident data is aggregate only

**Confidence: High.** Serious incidents rose to 160 per 100 services in 2024-25 (from 148, then
139). Up 62% since 2016-17. 77.7% are injury/illness/trauma. But this is never published per
service, and never broken down by for-profit vs not-for-profit — which makes the central contested
claim of the whole debate untestable from public data.

**Not tractable by aggregation.** Another campaigning target.

---

## 4. What is *not* a gap — be honest about this

Three things that look like gaps and are not:

- **Finding a centre and seeing its NQS rating.** Solved, three times over. StartingBlocks does it
  well and won a Good Design award for it.
- **Current conditions and last visit date.** Published since September 2025.
- **Individual worker records.** The National Early Childhood Worker Register went live February
  2026 and covers ~304,000 workers at 96% of services. It is not public — and should not be
  replicated. Suppression orders cover 13 of the ~150 accused workers Four Corners identified, and
  child protection law restricts naming. **Do not build anything that names individual workers.**

---

## 5. The real blocker: licensing

**This is the finding that should drive the next decision, not the gap analysis above.**

ACECQA's terms of use and copyright notice state:

- Content is owned by or licensed to ACECQA; the National Registers data is **jointly managed by
  each state and territory regulatory authority and ACECQA**.
- Personal and non-commercial use is permitted **with attribution** — "Source: Australian Children's
  Education and Care Quality Authority (ACECQA)".
- "Reproduce" is defined to include **downloading or storing in electronic form**. Scraping is not
  named but is plainly caught.
- You must not use Content **"to compete with or displace the market for it, including as the source
  of quality rating data for regulated services."**
- Content must not be used in a way that is misleading or deceptive, or conveys inaccurate or
  incomplete information.
- Sub-licensing is prohibited. Other uses require written consent from copyright@acecqa.gov.au, which
  may be refused at ACECQA's discretion.
- **No Creative Commons licence applies.** Breach automatically revokes permission.

A site whose core function is republishing NQS quality ratings is squarely within the prohibited
use, whether or not it is commercial.

**Three things follow:**

1. **Write to ACECQA before building.** A non-commercial, public-interest, clearly-attributed
   aggregator with a named gap-filling purpose is a reasonable consent request. Get it in writing.
2. **State and territory enforcement registers are a different and probably friendlier licensing
   position** — they are published by state education departments, many of which carry open
   licences on their web content. Check each individually. [Verify This — not yet confirmed per
   jurisdiction.]
3. **ABN/ASIC company data for the ownership graph is separately licensed** and generally open. The
   ownership-mapping gap may be buildable without touching ACECQA content at all.

Access note: ACECQA's web server blocked automated requests from this research environment (HTTP
403). That is a bot-protection layer, not a legal barrier, but it means CSV exports will need to be
obtained through a sanctioned route — which is another reason to ask first.

---

## 6. Legal and ethical design constraints

These are not optional. A transparency site about child safety that gets a fact wrong about a named
business is a defamation case, and a site that implies wrongdoing from a raw number is both unfair
and legally exposed.

1. **Publish verified regulatory facts, never allegations or inference.** Every published fact
   carries its source, its date, and a link to the primary record.
2. **Never publish a count without a denominator and a window.** "12 breaches" is meaningless.
   "12 confirmed breaches across 4 services over 24 months; sector median for operators of this size
   is 7" is a fact. A raw number implies wrongdoing it may not support.
3. **Distinguish breach / confirmed breach / enforcement action / prosecution / conviction
   explicitly** in the UI. They are not the same thing and conflating them is the fastest route to a
   claim.
4. **Never name individuals.** Suppression orders; child protection law; the register of
   prosecutions is the regulator's to publish, not ours.
5. **Right of reply.** A published correction and response mechanism for operators, acted on
   quickly. This is both ethically right and a defence.
6. **Serious harm threshold** (2021 defamation reforms) raises the bar for corporate claimants, and
   public interest and honest opinion defences exist — but none of that substitutes for being
   accurate. Get Australian defamation advice before launch, not after.
7. **Absence of a flag is not evidence of safety.** State this prominently. ACECQA's own page
   refuses to make that claim and nor should we.
8. **Non-NQF and remote community services need careful framing.** Under-resourced is not the same
   as unsafe.

---

## 7. Recommendation

**Build the longitudinal provider-level regulatory record — not another centre finder.**

Concretely, in order:

1. **Start the archive today.** Daily snapshot of the ACECQA national registers (service + provider
   CSVs), stored immutably with the capture date. Every day you don't do this is a day of history
   permanently lost. This is a cron job and a git repo. It does not require a website, a decision,
   or a licence negotiation — it is a private archive until published.
2. **In parallel, write to copyright@acecqa.gov.au** setting out the non-commercial public-interest
   purpose and requesting written consent. Nothing public ships before that answer.
3. **Build the parsers** for NSW quarterly PDFs and VECRA monthly pages onto the ACECQA service
   approval number as the join key. Add Queensland and the Commonwealth CCS register.
4. **Build the ownership graph** from provider records joined to ABN/ASIC. This is the differentiated
   asset and it is probably licence-clean.
5. **Then** decide what the public surface looks like.

The product is not "search a childcare centre." It is **"this operator, across every service it runs
in every state, over its entire recorded history, against sector benchmarks"** — the query Four
Corners needed 200,000 pages and a parliamentary production order to answer, and which a parent
should be able to run in four seconds.

---

## Sources

- [The ABC's explosive childcare investigations began with an email — ABC News](https://www.abc.net.au/news/2025-11-28/four-corners-childcare-safety-investigation-profit-abuse/106054128)
- [Paedophiles exploiting Australia's broken childcare system as safeguards crumble — ABC News](https://www.abc.net.au/news/2025-10-27/childcare-centres-paedophiles-abuse-four-corners/105926324)
- [Hunting Ground — ABC News](https://www.abc.net.au/news/2025-10-27/hunting-ground-four-corners-childcare/105939378)
- [Monstrous — ABC News](https://www.abc.net.au/news/2026-10-26/monstrous-four-corners-childcare/107309190)
- [Childcare worker's 'monstrous' violence captured on CCTV — ABC News](https://www.abc.net.au/news/2026-10-26/cctv-captures-childcare-worker-assaulting-babies-four-corners/107274426)
- [Four Corners: Betrayal of Trust — ABC iview](https://iview.abc.net.au/show/four-corners/series/2025/video/NC2503H007S00)
- [Powerful parliamentary inquiry to scrutinise childcare sector after ABC investigation — ABC News](https://www.abc.net.au/news/2025-03-21/nsw-to-launch-inquiry-into-childcare-sector/105078484)
- [ACECQA — National registers](https://www.acecqa.gov.au/resources/national-registers)
- [ACECQA — NQF Snapshots](https://www.acecqa.gov.au/national-quality-framework/national-quality-framework-snapshots)
- [ACECQA — NQF Annual Performance Report (Dec 2025)](https://www.acecqa.gov.au/sites/default/files/2025-12/2025-NQF-Annual-Performance-Report.pdf)
- [ACECQA — More compliance information for families on StartingBlocks.gov.au](https://www.acecqa.gov.au/latest-news/more-compliance-information-families-startingblocksgovau)
- [ACECQA — Expanding transparency to empower family decision-making](https://www.acecqa.gov.au/node/1111416)
- [ACECQA — National Worker Register](https://www.acecqa.gov.au/latest-news/national-worker-register)
- [ACECQA — Terms of use](https://acecqa.gov.au/terms-of-use)
- [StartingBlocks.gov.au](https://www.startingblocks.gov.au/)
- [StartingBlocks — Child safety and compliance](https://startingblocks.gov.au/resources/regulatory-activities/child-safety-and-compliance)
- [StartingBlocks — Terms of use](https://www.startingblocks.gov.au/terms-of-use)
- [NSW — Register of published enforcement actions](https://education.nsw.gov.au/early-childhood-education/regulation-and-compliance/compliance-and-enforcement-actions/register-of-published-enforcement-actions)
- [Victoria (VECRA) — Enforcement actions, August 2026](https://www.vecra.vic.gov.au/enforcement-actions-august-2026)
- [VECRA — Which early childhood services are regulated](https://www.vecra.vic.gov.au/which-early-childhood-services-are-regulated)
- [Queensland — Register of published enforcement actions](https://earlychildhood.qld.gov.au/regulation/compliance-and-enforcement/register-published-enforcement-actions)
- [Commonwealth Department of Education — Enforcement action register](https://www.education.gov.au/early-childhood/providers/compliance-and-enforcement/enforcement-action-register)
- [data.gov.au — Queensland child care licence register](https://data.gov.au/data/dataset/child-care-licence-register)
- [Serious incidents in childcare centres are still rising. Why? — The Conversation](https://theconversation.com/serious-incidents-in-childcare-centres-are-still-rising-why-275434)
- [ACECQA: ECEC enforcement doubles as quality standards improve — The Sector](https://thesector.com.au/article/enforcement-action-doubles-quality-standards-record-high-ecec)
- [ChildcareScan](https://childcarescan.com/)
- [AU Childcare Finder](https://childcare.rollersoft.com.au/)
