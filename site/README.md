# Private prototype site

**This site must stay access-protected.** It may not be made public until (1) the Australian
defamation, child protection and privacy review is complete, and (2) ACECQA has replied in writing
to the consent request of 30 October 2026 (`docs/02-acecqa-consent-request.md`). Every page
carries the banner "Private prototype. Not for publication. Data and wording under legal review."

## Build

```
python site/build_site.py --out site/dist
```

The build uses the standard library only and makes no network calls. It reads four committed
files from `data/processed/` (`enforcement-actions-all.csv`, `enforcement-by-service.csv`,
`enforcement-by-provider.csv`, `enforcement-join-report.json`); `--data DIR` points it elsewhere.
It stops with an error if the actions it lists do not match the processed totals.

Output (`site/dist/`, gitignored): `index.html`, `sources.html`, `404.html`, one page per service
and per provider with at least one joined action, `assets/` (one stylesheet, one search script,
the search index), `robots.txt` (disallow all) and `vercel.json`.

Preview locally with `python -m http.server -d site/dist` (search fetches its index, so it needs
a server rather than `file://`).

## What is rendered

Each page type renders an explicit column allowlist (`ACTION_COLUMNS`, `SERVICE_COLUMNS`,
`PROVIDER_COLUMNS` in `build_site.py`); every other column, with its reason, is in `EXCLUDED`.
No ACECQA rating is rendered anywhere. All values are HTML-escaped. Where a provider's name is
withheld, its provider approval number is withheld too and it gets no page; the service's name is
withheld when its provider is, or may be, an individual.

## Deploy (not done by the build)

Deploy `site/dist/` as a static project with no build step. `vercel.json` is copied into it and
sets `X-Robots-Tag: noindex, nofollow`, `X-Frame-Options: DENY`, a `'self'`-only
Content-Security-Policy and `Referrer-Policy: no-referrer`.

Before any deploy, turn on access protection for the project (Vercel deployment protection, for
example password or Vercel Authentication on every deployment, production included) and confirm
an unauthenticated request is refused. A deploy without protection is a publication.

## Tests

`pytest -q tests/test_site_build.py` builds a small synthetic fixture and checks the banner,
noindex, absence of ratings, the column allowlist, escaping, the absence-of-record statement and
denominators on counts.
