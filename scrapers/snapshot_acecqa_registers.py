"""Daily snapshot of the two ACECQA national register CSVs.

Fetches the national services and approved providers exports, validates them, stores each as a
new gzip-compressed, timestamped file under data/raw/<source>/ with a sidecar meta file, and then
rebuilds the processed tables under data/processed/ from the newest snapshot.

Licence note: ACECQA content is not openly licensed. These files are for internal archive and
analysis only; no public republication without written consent (CLAUDE.md rule 8).

Usage:
    python3 scrapers/snapshot_acecqa_registers.py [--force] [--no-fetch]

Exit codes: 0 success (including "unchanged"), 1 fetch failure, 2 validation failure,
3 no raw snapshot available for --no-fetch.
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import gzip
import hashlib
import io
import json
import logging
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

if __package__ in (None, ""):  # allow `python3 scrapers/snapshot_acecqa_registers.py`
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scrapers.common import (
    PROCESSED_DIR,
    RAW_DIR,
    Fetched,
    fetch,
    known_hashes,
    list_snapshots,
    normalise_pr,
    normalise_se,
    write_processed,
    write_snapshot,
)

log = logging.getLogger("scrapers.acecqa")

BASE = "https://www.acecqa.gov.au/sites/default/files/national-registers"
GZIP_LEVEL = 9
MAX_NULL_LOG_LINES = 20

# Columns whose names look like these may hold a personal number or a named person. They are
# dropped from processed outputs. The raw snapshot is kept exactly as published.
DROP_PATTERN = re.compile(r"phone|fax|e-?mail|contact|supervisor|nominated", re.IGNORECASE)


@dataclass(frozen=True)
class SourceSpec:
    name: str  # directory under data/raw/ and prefix under data/processed/
    url: str
    required_header: str
    min_rows: int  # guard against a truncated file or an error page
    service_col: str | None  # original column holding the SE number, if any
    provider_col: str


SERVICES = SourceSpec(
    name="acecqa-services",
    url=f"{BASE}/services/Education-services-au-export.csv",
    required_header="ServiceApprovalNumber",
    min_rows=10_000,
    service_col="ServiceApprovalNumber",
    provider_col="Provider Approval Number",
)
PROVIDERS = SourceSpec(
    name="acecqa-providers",
    url=f"{BASE}/providers/Approved-providers-au-export.csv",
    required_header="Provider Approval Number",
    min_rows=5_000,
    service_col="Service Approval Number",
    provider_col="Provider Approval Number",
)


class ValidationError(RuntimeError):
    """Raised when a downloaded file does not look like the register it should be."""


@dataclass
class ParsedCsv:
    columns: list[str]
    rows: list[list[str]]
    encoding: str

    @property
    def row_count(self) -> int:
        return len(self.rows)


def decode_csv_bytes(content: bytes) -> tuple[str, str]:
    """Decode as UTF-8 (BOM tolerated), falling back to Windows-1252. Returns (text, encoding)."""
    try:
        return content.decode("utf-8-sig"), "utf-8"
    except UnicodeDecodeError:
        return content.decode("cp1252", errors="replace"), "cp1252"


def parse_csv(content: bytes) -> ParsedCsv:
    text, encoding = decode_csv_bytes(content)
    reader = csv.reader(io.StringIO(text, newline=""))
    try:
        header = next(reader)
    except StopIteration:
        raise ValidationError("file is empty") from None
    columns = [c.strip() for c in header]
    rows = [r for r in reader if any(cell.strip() for cell in r)]
    return ParsedCsv(columns=columns, rows=rows, encoding=encoding)


def validate_parsed(parsed: ParsedCsv, spec: SourceSpec) -> None:
    """Raise ValidationError unless the header and row count look right for this register."""
    if spec.required_header not in parsed.columns:
        raise ValidationError(
            f"{spec.name}: header lacks {spec.required_header!r} "
            f"(first columns: {parsed.columns[:5]})"
        )
    if parsed.row_count <= spec.min_rows:
        raise ValidationError(
            f"{spec.name}: {parsed.row_count} rows, expected more than {spec.min_rows}"
        )


def split_columns(columns: list[str]) -> tuple[list[str], list[str]]:
    """Return (kept, dropped) column names, preserving order."""
    kept = [c for c in columns if not DROP_PATTERN.search(c)]
    dropped = [c for c in columns if DROP_PATTERN.search(c)]
    return kept, dropped


def dedupe_names(columns: list[str]) -> list[str]:
    """Make column names unique so a dict per row loses nothing (suffix __2, __3)."""
    seen: dict[str, int] = {}
    out = []
    for c in columns:
        seen[c] = seen.get(c, 0) + 1
        out.append(c if seen[c] == 1 else f"{c}__{seen[c]}")
    return out


def build_processed_rows(
    parsed: ParsedCsv, spec: SourceSpec, snapshot_last_modified: str | None
) -> tuple[list[dict], list[str], list[str]]:
    """Drop contact columns, add normalised approval numbers. Returns (rows, fieldnames, dropped)."""
    columns = dedupe_names(parsed.columns)
    kept, dropped = split_columns(columns)
    index = {c: i for i, c in enumerate(columns)}
    new_cols = ["service_approval_number", "provider_approval_number", "snapshot_last_modified"]
    fieldnames = kept + new_cols

    null_logged = 0
    null_total = 0
    rows: list[dict] = []
    for n, raw in enumerate(parsed.rows, start=2):  # line 1 is the header
        row = {c: (raw[index[c]] if index[c] < len(raw) else "") for c in kept}

        def cell(col: str | None, raw: list[str] = raw) -> str:
            if col is None or col not in index or index[col] >= len(raw):
                return ""
            return raw[index[col]].strip()

        se_orig, pr_orig = cell(spec.service_col), cell(spec.provider_col)
        se, pr = normalise_se(se_orig), normalise_pr(pr_orig)
        row["service_approval_number"] = se
        row["provider_approval_number"] = pr
        row["snapshot_last_modified"] = snapshot_last_modified

        # A blank service number in the providers file is normal; log only real failures:
        # a provider number that is missing/unparseable, a service number that is present but
        # unparseable, or a blank service number in the services file.
        problems = []
        if pr is None:
            problems.append(f"provider_approval_number null (original {pr_orig!r})")
        if se is None and (se_orig or spec.name == SERVICES.name):
            problems.append(f"service_approval_number null (original {se_orig!r})")
        if problems:
            null_total += 1
            if null_logged < MAX_NULL_LOG_LINES:
                log.warning("%s line %d: %s", spec.name, n, "; ".join(problems))
                null_logged += 1
        rows.append(row)
    if null_total > null_logged:
        log.warning(
            "%s: %d further rows with null approval numbers not shown",
            spec.name,
            null_total - null_logged,
        )
    if null_total:
        log.warning(
            "%s: %d rows had a null approval number (left null, not inferred)",
            spec.name,
            null_total,
        )
    return rows, fieldnames, dropped


def gzip_bytes(content: bytes) -> bytes:
    """Deterministic gzip (mtime 0) at level 9, so the same input gives the same bytes."""
    return gzip.compress(content, compresslevel=GZIP_LEVEL, mtime=0)


def with_cache_buster(url: str) -> str:
    return f"{url}?nocache={int(time.time() * 1000)}"


def write_if_new(
    spec: SourceSpec, fetched: Fetched, parsed: ParsedCsv, *, force: bool, raw_dir: Path = RAW_DIR
) -> Path | None:
    """Write a gzip snapshot unless its uncompressed hash is already stored. None if unchanged."""
    sha_plain = hashlib.sha256(fetched.content).hexdigest()
    if not force and sha_plain in known_hashes(
        spec.name, base_dir=raw_dir, key="sha256_uncompressed"
    ):
        log.info("%s: unchanged (sha256 %s already archived)", spec.name, sha_plain[:12])
        return None
    packed = gzip_bytes(fetched.content)
    stored = dataclasses.replace(fetched, content=packed)
    return write_snapshot(
        spec.name,
        stored,
        "csv.gz",
        base_dir=raw_dir,
        extra_meta={
            "stored_encoding": "gzip",
            "gzip_level": GZIP_LEVEL,
            "sha256_uncompressed": sha_plain,
            "sha256_gzip": hashlib.sha256(packed).hexdigest(),
            "bytes_uncompressed": len(fetched.content),
            "row_count": parsed.row_count,
            "columns": parsed.columns,
            "text_encoding": parsed.encoding,
        },
    )


def read_snapshot(path: Path) -> tuple[ParsedCsv, str | None]:
    """Parse a stored snapshot and return it with the last-modified value from its sidecar."""
    parsed = parse_csv(gzip.decompress(path.read_bytes()))
    meta = json.loads(Path(f"{path}.meta.json").read_text())
    return parsed, meta.get("last_modified")


def build_processed(spec: SourceSpec, raw_dir: Path = RAW_DIR) -> Path:
    snaps = list_snapshots(spec.name, base_dir=raw_dir)
    if not snaps:
        raise FileNotFoundError(f"no raw snapshot for {spec.name}")
    newest = snaps[-1]
    parsed, last_modified = read_snapshot(newest)
    validate_parsed(parsed, spec)
    rows, fieldnames, dropped = build_processed_rows(parsed, spec, last_modified)
    notes = (
        f"Built from {newest.name}. Dropped columns (name matches "
        f"{DROP_PATTERN.pattern!r}): {dropped if dropped else 'none'}. "
        "Added service_approval_number and provider_approval_number (normalised SE-/PR- plus 8 "
        "digits, null where the source is blank or unparseable; originals kept) and "
        "snapshot_last_modified (HTTP last-modified of the source file). Raw snapshot is kept "
        "unchanged. ACECQA content is not openly licensed: internal use only."
    )
    log.info("%s: dropped columns %s", spec.name, dropped)
    return write_processed(
        f"{spec.name}-latest",
        rows,
        fieldnames,
        raw_inputs=[newest, Path(f"{newest}.meta.json")],
        notes=notes,
    )


def run(*, force: bool, no_fetch: bool) -> int:
    specs = (SERVICES, PROVIDERS)
    wrote_any = False

    if not no_fetch:
        downloaded: list[tuple[SourceSpec, Fetched, ParsedCsv]] = []
        for spec in specs:
            try:
                fetched = fetch(with_cache_buster(spec.url))
            except Exception as exc:  # network, HTTP status or robots
                log.error("fetch failed for %s: %s", spec.name, exc)
                return 1
            log.info(
                "%s: %d bytes, last-modified %s",
                spec.name,
                len(fetched.content),
                fetched.last_modified,
            )
            try:
                parsed = parse_csv(fetched.content)
                validate_parsed(parsed, spec)
            except ValidationError as exc:
                log.error("validation failed, nothing written: %s", exc)
                return 2
            log.info("%s: %d rows, %d columns", spec.name, parsed.row_count, len(parsed.columns))
            downloaded.append((spec, fetched, parsed))

        # Both files are valid: only now write anything.
        for spec, fetched, parsed in downloaded:
            if write_if_new(spec, fetched, parsed, force=force) is not None:
                wrote_any = True

    for spec in specs:
        out_exists = (PROCESSED_DIR / f"{spec.name}-latest.csv").exists()
        if no_fetch or wrote_any or not out_exists:
            try:
                build_processed(spec)
            except FileNotFoundError as exc:
                log.error("%s", exc)
                return 3
            except ValidationError as exc:
                log.error("validation failed for stored snapshot: %s", exc)
                return 2
        else:
            log.info("%s: processed output left as is (no new snapshot)", spec.name)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--force", action="store_true", help="write snapshots even if unchanged")
    ap.add_argument(
        "--no-fetch", action="store_true", help="rebuild processed outputs from the latest snapshot"
    )
    args = ap.parse_args(argv)
    return run(force=args.force, no_fetch=args.no_fetch)


if __name__ == "__main__":
    sys.exit(main())
