#!/usr/bin/env python3
"""Validate data/gap-ledger.json. Standard library only, so it runs anywhere.

Usage: python3 .claude/hooks/validate_ledger.py data/gap-ledger.json
Exit 0 if valid, 1 with a list of errors if not.
"""

import json
import re
import sys

STATUSES = {"hypothesis", "validated", "rejected", "closed_by_government"}
CONFIDENCE = {"High", "Medium", "Low"}
TRACTABILITY = {"aggregation", "campaign_or_foi", "partial", "unknown"}
SOURCE_TYPES = {
    "official_register",
    "official_report",
    "parliamentary",
    "media",
    "academic",
    "other",
}
GAP_ID = re.compile(r"^GAP-\d{3}$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DASHES = (chr(0x2014), chr(0x2013))  # em dash, en dash


def check(ledger: dict) -> list[str]:
    errors: list[str] = []
    if not isinstance(ledger.get("gaps"), list):
        return ["top level must contain a 'gaps' array"]
    if not DATE.match(str(ledger.get("last_updated", ""))):
        errors.append("last_updated must be YYYY-MM-DD")

    seen: set[str] = set()
    for i, g in enumerate(ledger["gaps"]):
        where = f"gaps[{i}]"
        gid = g.get("id", "")
        if not GAP_ID.match(gid):
            errors.append(f"{where}: id must look like GAP-001")
        if gid in seen:
            errors.append(f"{where}: duplicate id {gid}")
        seen.add(gid)
        for field in ("title", "description", "next_action"):
            if not str(g.get(field, "")).strip():
                errors.append(f"{gid or where}: '{field}' is required")
        if g.get("status") not in STATUSES:
            errors.append(f"{gid}: status must be one of {sorted(STATUSES)}")
        if g.get("confidence") not in CONFIDENCE:
            errors.append(f"{gid}: confidence must be High, Medium or Low")
        if g.get("tractability") not in TRACTABILITY:
            errors.append(f"{gid}: tractability must be one of {sorted(TRACTABILITY)}")
        if not DATE.match(str(g.get("last_reviewed", ""))):
            errors.append(f"{gid}: last_reviewed must be YYYY-MM-DD")

        evidence = g.get("evidence", [])
        if not evidence:
            errors.append(f"{gid}: at least one evidence item is required")
        official = 0
        for j, e in enumerate(evidence):
            ew = f"{gid}.evidence[{j}]"
            if not str(e.get("claim", "")).strip():
                errors.append(f"{ew}: claim is required")
            if not str(e.get("source_url", "")).startswith("https://"):
                errors.append(f"{ew}: source_url must be an https URL")
            if e.get("source_type") not in SOURCE_TYPES:
                errors.append(
                    f"{ew}: source_type must be one of {sorted(SOURCE_TYPES)}"
                )
            if e.get("source_type") in (
                "official_register",
                "official_report",
                "parliamentary",
            ):
                official += 1

        # A gap can only be marked validated on official evidence, not media alone.
        if g.get("status") == "validated" and official == 0:
            errors.append(
                f"{gid}: 'validated' needs at least one official or parliamentary source"
            )
        if (
            g.get("status") == "closed_by_government"
            and not str(g.get("closed_by", "")).strip()
        ):
            errors.append(f"{gid}: 'closed_by_government' needs a 'closed_by' note")

    text = json.dumps(ledger, ensure_ascii=False)
    if any(d in text for d in DASHES):
        errors.append(
            "ledger contains an em dash or en dash; use a plain hyphen or reword"
        )
    return errors


def main() -> None:
    path = sys.argv[1] if len(sys.argv) > 1 else "data/gap-ledger.json"
    try:
        with open(path, encoding="utf-8") as f:
            ledger = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"cannot read {path}: {exc}")
        sys.exit(1)
    errors = check(ledger)
    if errors:
        print("\n".join(f"- {e}" for e in errors))
        sys.exit(1)
    print(f"OK: {len(ledger['gaps'])} gaps valid")


if __name__ == "__main__":
    main()
