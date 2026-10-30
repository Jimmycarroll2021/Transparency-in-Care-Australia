# Transparency in Care Australia

A volunteer, non-commercial, public-interest project. It joins Australia's published childcare
regulatory records (quality ratings and enforcement actions from every regulator that publishes
them) into one honest, longitudinal record per service and provider.

**New to the project? Start with [`docs/03-handover.md`](docs/03-handover.md).**

## Status

Data collection and joining are working. There is no public website yet: one follows only after
legal review, and ACECQA ratings will not be displayed publicly until ACECQA has replied to our
consent request (`docs/02-acecqa-consent-request.md`).

| | |
|---|---|
| Enforcement actions collected | 3,543, from NSW, Victoria, Queensland, South Australia, Western Australia, Tasmania and the Commonwealth (NT and the ACT publish none) |
| Joined to an ACECQA service or provider | 91.5 per cent; every remaining row carries a stated reason |
| Providers resolved to an ABN | 901 of the 1,210 with the largest footprint or any enforcement action |

## How data is collected

Every collector follows the same rules (`scrapers/common.py`):

- It identifies itself with a User-Agent naming this project and a contact address. It never
  impersonates a browser or uses any AI crawler identity.
- It honours robots.txt and any crawl delay, and waits at least 1.5 seconds between requests to the
  same site.
- It fetches only what it needs, and skips files it already holds (checked by content hash).
- It drops the names of individuals at ingest. Only approved services and provider entities are kept.

| Source | What is fetched | How often |
|---|---|---|
| ACECQA National Registers | The two static CSV exports (services and providers), with the same cache-busting parameter the site's own Export button uses | Once a day |
| NSW Department of Education | Quarterly enforcement register PDFs, new files only | On demand |
| Victoria (VECRA) | Monthly enforcement pages (HTML only; archived PDF and Word files are excluded by robots.txt and are not fetched) | On demand |
| Queensland, Tasmania | One register page each | On demand |
| South Australia (ESB) | Current and historical compliance action pages | On demand |
| Western Australia (ECRU) | The public enforcement search form, read with a browser engine because it has no static page, under the project's own User-Agent | On demand |
| Commonwealth (Department of Education) | The enforcement register, saved by hand from a browser, because the site does not answer scripts | On demand |
| ABN Lookup | The official ABN Lookup web services, with a registered key | On demand |

Licences differ by source: NSW and Victorian content is CC BY 4.0; ACECQA, South Australian and
Western Australian content is used for non-commercial research under their terms. See
`research/` for each source's audit.

## Documents

- [`docs/01-gap-analysis.md`](docs/01-gap-analysis.md): what the Four Corners investigations found,
  the public data sources, and the gaps this project addresses.
- [`docs/02-execution-plan.md`](docs/02-execution-plan.md): phases and workstreams.
- [`docs/03-handover.md`](docs/03-handover.md): state, licence position, how to run it, open work.
- [`docs/02-acecqa-consent-request.md`](docs/02-acecqa-consent-request.md): the consent request sent
  to ACECQA on 30 October 2026.
- [`research/`](research/): dated audits of every register (format, join keys, licence, window).
- [`data/gap-ledger.json`](data/gap-ledger.json): the transparency gaps and the evidence for each.

## Running it

Python 3.10 or later. `pip install -r requirements.txt`, then see the commands list in
`CLAUDE.md`. Tests: `pytest`.
