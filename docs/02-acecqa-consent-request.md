# ACECQA consent request

**Status:** Sent 30 October 2026 from jimmisound@gmail.com to copyright@acecqa.gov.au (Gmail message 1a18b40f2bf475a2). No reply yet.
**Sent version differs from the draft below in two ways:** it adds a fifth ask (an extract of ceased or cancelled approvals, since about 500 published enforcement actions refer to approvals absent from the current export), and a disclosure that daily downloads began on 29 October 2026 for research, that some copies sit in the public repository, that nothing is published on a website, that ratings will not be displayed publicly until ACECQA replies, and an offer to remove the stored copies from public view the same day if asked.
**To:** copyright@acecqa.gov.au
**Why:** ACECQA's terms of use prohibit using its content "to compete with or displace the market for
it, including as the source of quality rating data for regulated services", define "Reproduce" to
include downloading or storing in electronic form, and reserve all other uses to written consent.
Nothing in this project republishes ACECQA content until that consent is held in writing.

Send from the project owner's own address so replies land with a person. Keep the subject line
exact: it names the clause we are asking about so it can be routed to the right team.

---

**Subject:** Request for written consent under ACECQA Terms of Use: non-commercial reuse of National
Registers data for a public-interest transparency project

Dear ACECQA Copyright team,

I am writing to request written consent to reuse data from the ACECQA National Registers
(approved services and approved providers) and, if available, the NQF Snapshot data files, for a
non-commercial public-interest project called Transparency in Care Australia.

**What the project is**

A volunteer, non-commercial project that aims to make existing public regulatory information about
children's education and care services easier for families and researchers to understand over
time. It is not a business, will not carry advertising, and will not sell, licence or sub-licence
any data. Its code and methods are published openly at
https://github.com/Jimmycarroll2021/Transparency-in-Care-Australia.

**What we would like to do with ACECQA data**

1. Download the National Registers CSV exports on a regular schedule (daily at most) and keep
   dated copies, so that changes over time can be seen. ACECQA publishes current state only; we
   would like to retain history.
2. Use the service approval number (SE-) and provider approval number (PR-) as join keys to link
   each service to the enforcement actions already published by the state and territory
   regulatory authorities and by the Commonwealth Department of Education.
3. Display, with the attribution "Source: Australian Children's Education and Care Quality
   Authority (ACECQA)" and a link to the relevant StartingBlocks.gov.au page, a service's current
   NQS rating and rating date alongside that linked public enforcement history.

**What we will not do**

- We will not present ourselves as a substitute for StartingBlocks.gov.au or the National
  Registers, and every service page will link to its StartingBlocks page as the authoritative
  record.
- We will not sell, licence or sub-license any ACECQA content, and will not use it for any
  commercial purpose.
- We will not publish any personal information, including nominated supervisors or educators.
  Person-level fields will be dropped at ingest.
- We will not alter ratings, dates or other values, and will show the capture date of every value.
- We will publish only regulatory facts from official records, never allegations or media
  reporting, and will provide a corrections and right-of-reply process for providers.
- We will request at a rate that places no material load on your systems (at most one export per
  register per day, with a User-Agent that identifies the project and this contact address).

**What we are asking for**

Written consent, under the "Other uses" provision of the Terms of Use, to the three uses listed
above. We would also be grateful for guidance on four points about the exports themselves:

- whether the approved providers export can carry the provider's ABN or ACN, so that providers
  can be linked to public company records without name matching;
- whether provider management type (private for profit, not for profit, government and so on) can
  be included;
- whether rating issued dates can be given to the day rather than the month; and
- whether fetching the static CSV files with a cache-busting parameter, as the "Export CSV" link
  does, is the method you prefer for a daily download.

We note that your robots.txt disallows a number of named AI crawlers. Our collection would be a
plain scheduled download of the static CSV files, once a day at most, under a user agent that
names this project and this address, honouring your crawl delay. If you would prefer a different
method, we will use it. If ACECQA would prefer a different arrangement (for example a data feed, an API key, a
data-sharing agreement, or a licence with specific conditions), we would welcome that and will
meet reasonable conditions, including attribution wording, a link-back requirement, a takedown
process, or periodic review.

If any of the three uses cannot be consented to, we would be grateful to know which, so that we
can design around it. In particular, if use 3 (displaying ratings) is not possible, we would still
like to proceed with uses 1 and 2 so that enforcement history can be shown against a service
approval number with a link to StartingBlocks for the rating.

I am happy to discuss by phone or in writing, and to provide any further detail about the project,
its governance or its safeguards.

Kind regards,

Jimmy Carroll
Transparency in Care Australia
jimmisound@gmail.com
https://github.com/Jimmycarroll2021/Transparency-in-Care-Australia

---

## After sending

- Record the date sent and any reference number at the top of this file.
- Set a reminder for 15 business days. If no reply, send one polite follow-up, then escalate to
  the ACECQA general enquiries address and note the escalation here.
- Any reply, in full, is saved to `data/evidence/` by script (immutable), and the decision it
  supports is recorded in `CLAUDE.md` under "Current phase".
- Until a reply: no public republication of ACECQA content. Private, non-commercial, attributed
  storage for research is within the terms' "non-commercial use" permission; publication is not.
