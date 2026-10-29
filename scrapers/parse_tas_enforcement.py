"""Fetch and parse the Tasmania (ECU) published enforcement action register.

Source: Education and Care Unit, Department for Education, Children and Young People (Tasmania).
URL: https://educationandcare.tas.gov.au/families-and-communities/published-enforcement-actions-under-the-national-law/

The register publishes formal enforcement actions taken under the Education and Care Services
National Law Act 2010. Each entry itemises the service name and SE- number, address, approved
provider name and PR- number, nature of action, reason, and date.

Mapping:
- Emergency Action Notice -> emergency_action_notice
- Compliance Notice -> compliance_notice
- Suspension of service / provider approval -> approval_suspended
- Cancellation -> approval_cancelled
- Enforceable Undertaking -> enforceable_undertaking
- Prohibition Notice -> prohibition_notice

Privacy:
Natural persons (sole traders / individuals) have their names withheld and INDIVIDUAL_NOTE added.

Run: python3 scrapers/parse_tas_enforcement.py [--skip-fetch] [--force]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scrapers import common
from scrapers.common import (
    PROJECT_ROOT,
    fetch,
    list_snapshots,
    log,
    normalise_pr,
    normalise_se,
    record_hash,
    write_processed,
    write_snapshot,
)
from scrapers.parse_cth_ccs_enforcement import clean, parse_cth_date
from scrapers.parse_qld_enforcement import (
    INDIVIDUAL_NOTE,
    classify_subject,
    contains_token,
    name_tokens,
)

SOURCE = "tas-enforcement"
JURISDICTION = "TAS"
INDEX_URL = (
    "https://educationandcare.tas.gov.au/families-and-communities/published-enforcement-actions-under-the-national-law/"
)
SCHEMA_PATH = "data/schemas/enforcement-action.schema.json"
OUTPUT_NAME = "tas-enforcement-actions"

FIELDNAMES = [
    "record_id",
    "jurisdiction",
    "source_register",
    "source_document",
    "source_snapshot",
    "captured_at",
    "service_approval_number",
    "service_approval_number_raw",
    "provider_approval_number",
    "provider_approval_number_raw",
    "service_name",
    "provider_name",
    "address",
    "suburb",
    "state",
    "postcode",
    "action_type",
    "action_type_raw",
    "reason",
    "legal_references",
    "date_issued",
    "date_issued_raw",
    "period_label",
    "notes",
]


def map_tas_action_type(raw: str) -> tuple[str, str | None]:
    low = raw.lower()
    if "emergency action" in low:
        return "emergency_action_notice", None
    if "compliance notice" in low:
        return "compliance_notice", None
    if "enforceable undertaking" in low:
        return "enforceable_undertaking", None
    if "condition" in low:
        return "condition_imposed", None
    if "suspen" in low:
        return "approval_suspended", None
    if "cancel" in low:
        return "approval_cancelled", None
    if "prohibition" in low:
        return "prohibition_notice", None
    return "other", None


def parse_tas_address(text: str | None) -> dict[str, str | None]:
    out: dict[str, str | None] = {"address": text, "suburb": None, "state": "TAS", "postcode": None}
    if not text:
        return out
    m = re.search(
        r"(?:,\s*)(?P<suburb>[A-Za-z\s]+?),\s*(?P<state>TAS|Tasmania)\s*(?P<pc>\d{4})?$",
        text.strip(),
        re.I,
    )
    if m:
        out["suburb"] = m.group("suburb").strip(" ,")
        st = m.group("state").strip()
        out["state"] = "TAS" if st.lower() in ["tas", "tasmania"] else st.upper()
        out["postcode"] = m.group("pc")
    return out


def parse_page(
    html: str,
    *,
    page_url: str = INDEX_URL,
    captured_at: str = "",
    source_snapshot: str = "",
) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    blocks = soup.find_all(lambda el: el.name == "p" and "service name and number" in el.get_text().lower())
    rows: list[dict] = []

    for b in blocks:
        txt = clean(b.get_text())
        srv_part = re.sub(r"Service name and number:\s*", "", txt, flags=re.I)
        se_norm = normalise_se(srv_part)
        srv_name = clean(re.sub(r",?\s*SE[\s_-]*\d+.*", "", srv_part))

        sib_texts = []
        curr = b.next_sibling
        while curr:
            if getattr(curr, "name", None) == "p" and "service name and number" in curr.get_text().lower():
                break
            if getattr(curr, "name", None) in ["h2", "h3"]:
                break
            t = clean(curr.get_text(" ", strip=True)) if hasattr(curr, "get_text") else ""
            if t:
                sib_texts.append(t)
            curr = curr.next_sibling

        blob = " ".join(sib_texts)
        addr_m = re.search(r"Address of the Service:\s*(.*?)(?:Approved Provider|\bNature of|\bReason|$)", blob, re.I)
        addr_raw = clean(addr_m.group(1)) if addr_m else None
        loc = parse_tas_address(addr_raw)

        prov_m = re.search(
            r"Approved Provider (?:name and number|name):\s*(.*?)(?:Nature of|\bReason|\bEnforcement|$)", blob, re.I
        )
        prov_blob = clean(prov_m.group(1)) if prov_m else ""
        pr_norm = normalise_pr(prov_blob)
        prov_raw = clean(re.sub(r",?\s*PR[\s_-]*\d+.*", "", prov_blob))

        notes: list[str] = []
        prov_name: str | None = None
        if prov_raw:
            kind = classify_subject(prov_raw, has_service_line=True)
            if kind in {"entity", "service_only"}:
                prov_name = prov_raw
            else:
                notes.append(INDIVIDUAL_NOTE)
                tokens = name_tokens(prov_raw) if kind == "individual" else set()
                if tokens and srv_name and contains_token(srv_name, tokens):
                    srv_name = None
                    notes.append("service text withheld: it repeated a word from the individual's name")
        else:
            notes.append("provider name not printed")

        nature_m = re.search(
            r"Nature of the enforcement action:\s*(.*?)(?:Reason for|\bEnforcement action taken|$)", blob, re.I
        )
        nature_raw = clean(nature_m.group(1)) if nature_m else "Compliance action"
        action_type, type_note = map_tas_action_type(nature_raw)
        if type_note:
            notes.append(type_note)

        det_m = re.search(
            r"Reason for taking the enforcement action:\s*(.*?)(?:Enforcement action taken|Details of|$)", blob, re.I
        )
        reason = clean(det_m.group(1)) if det_m else None

        date_m = re.search(r"\b(?:issued|taken|dated?)\s*[–-]?\s*(\d{1,2}\s+[A-Za-z]+\s+\d{4})", blob, re.I)
        date_raw = date_m.group(1) if date_m else None
        date_iso = parse_cth_date(date_raw) if date_raw else None

        legal_refs = sorted(
            set(
                re.findall(
                    r"\b(?:Section\s+\d+[a-zA-Z0-9()\-]*|Regulation\s+\d+[a-zA-Z0-9()\-]*)\b",
                    blob,
                    re.I,
                )
            )
        )

        row = {
            "record_id": record_hash(JURISDICTION, srv_name, se_norm, action_type, date_iso),
            "jurisdiction": JURISDICTION,
            "source_register": INDEX_URL,
            "source_document": page_url,
            "source_snapshot": source_snapshot,
            "captured_at": captured_at,
            "service_approval_number": se_norm,
            "service_approval_number_raw": se_norm,
            "provider_approval_number": pr_norm,
            "provider_approval_number_raw": pr_norm,
            "service_name": srv_name,
            "provider_name": prov_name,
            "address": loc["address"],
            "suburb": loc["suburb"],
            "state": loc["state"] or "TAS",
            "postcode": loc["postcode"],
            "action_type": action_type,
            "action_type_raw": nature_raw,
            "reason": reason,
            "legal_references": legal_refs,
            "date_issued": date_iso,
            "date_issued_raw": date_raw,
            "period_label": "Published Enforcement Actions under the National Law",
            "notes": "; ".join(notes) if notes else None,
        }
        rows.append(row)

    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--skip-fetch", action="store_true", help="parse newest local snapshot")
    ap.add_argument("--force", action="store_true", help="write snapshot even if duplicate")
    args = ap.parse_args(argv)

    snapshots = list_snapshots(SOURCE)
    snapshot_path: Path | None = None

    if args.skip_fetch:
        if not snapshots:
            log.error("no local %s snapshot found; run without --skip-fetch", SOURCE)
            return 2
        snapshot_path = snapshots[-1]
    else:
        try:
            fetched = fetch(INDEX_URL, retries=1)
        except (httpx.HTTPError, common.RobotsDisallowed) as exc:
            log.error("TAS ECU register unreachable: %r", exc)
            return 2
        snapshot_path = write_snapshot(SOURCE, fetched, "html")

    meta_path = Path(f"{snapshot_path}.meta.json")
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    captured_at = meta.get("fetched_at", "")
    html = snapshot_path.read_text(encoding="utf-8", errors="replace")

    rows = parse_page(
        html,
        page_url=INDEX_URL,
        captured_at=captured_at,
        source_snapshot=str(snapshot_path.relative_to(PROJECT_ROOT)),
    )

    if not rows:
        log.error("no enforcement rows parsed from TAS ECU page")
        return 1

    out_rows = [{**r, "legal_references": json.dumps(r["legal_references"])} for r in rows]
    write_processed(
        OUTPUT_NAME,
        out_rows,
        FIELDNAMES,
        raw_inputs=[snapshot_path],
        schema=SCHEMA_PATH,
        notes="Tasmania ECU published enforcement actions. Joined with SE- and PR- keys.",
    )
    log.info("%d rows parsed from %s", len(rows), snapshot_path.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
