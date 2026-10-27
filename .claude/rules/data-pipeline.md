---
paths:
  - "scrapers/**/*"
  - "data/**/*"
---

# Data pipeline rules

- `data/raw/` and `data/evidence/` are append-only and written by scripts only. A hook blocks
  direct edits. Derived data goes to `data/processed/`.
- Snapshot filenames carry a UTC capture timestamp: `data/raw/<source>/<YYYY-MM-DDTHHMMZ>.<ext>`.
- Never collect from a source without a register-auditor note in `research/` clearing its licence.
  ACECQA content is not openly licensed; no public republication without written consent.
- Minimum 1.5 seconds between requests to government hosts. Honour robots.txt. Set a User-Agent that
  names the project and a contact address.
- Join key: service approval number (`SE-` plus 8 digits). Provider key: `PR-` plus 8 digits. Keep
  the source's original value alongside the normalised one.
- Missing values are `null` with a logged reason. Never infer or fill.
- Drop person-level fields (nominated supervisors, educators) at ingest.
- Every processed table records the raw snapshot files it was built from.
