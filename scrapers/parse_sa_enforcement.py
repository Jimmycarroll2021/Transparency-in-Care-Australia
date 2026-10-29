"""Fetch and parse the South Australia (ESB) compliance action register.

Source: Education Standards Board (South Australia), early childhood compliance and enforcement.
URL: https://www.esb.sa.gov.au/early-childhood/compliance-and-enforcement/current-compliance-action

The register is published as an HTML page organised into service sections under headings
carrying the service name and SE- approval number (e.g. `Happy Haven OSHC Mitcham (SE-00010642)`).
Each section specifies the address, approved provider and PR- number, contravention details,
action taken, legal references, and date of issue.

Mapping:
- Issue of Compliance Notice -> compliance_notice
- Issue of Emergency Action Notice -> emergency_action_notice
- Conditions imposed / Amendment of approval -> condition_imposed
- Enforceable Undertaking -> enforceable_undertaking
- Suspension of service / provider approval -> approval_suspended
- Cancellation -> approval_cancelled
- Prohibition Notice -> prohibition_notice

Privacy:
Natural persons (sole traders / individuals) have their names withheld and INDIVIDUAL_NOTE added.

Run: python3 scrapers/parse_sa_enforcement.py [--skip-fetch] [--force]
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

SOURCE = "sa-enforcement"
JURISDICTION = "SA"
INDEX_URL = (
    "https://www.esb.sa.gov.au/early-childhood/compliance-and-enforcement/current-compliance-action"
)
SCHEMA_PATH = "data/schemas/enforcement-action.schema.json"
OUTPUT_NAME = "sa-enforcement-actions"

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


def map_sa_action_type(raw: str) -> tuple[str, str | None]:
    low = raw.lower()
    if "emergency action" in low:
        return "emergency_action_notice", None
    if "compliance notice" in low:
        return "compliance_notice", None
    if "enforceable undertaking" in low:
        return "enforceable_undertaking", None
    if "condition" in low or "amendment of service approval" in low:
        return "condition_imposed", None
    if "suspend" in low:
        return "approval_suspended", None
    if "cancel" in low:
        return "approval_cancelled", None
    if "prohibition" in low:
        return "prohibition_notice", None
    return "other", None


def parse_sa_date(text: str | None) -> str | None:
    if not text:
        return None
    text_clean = re.sub(r"(\d+)(st|nd|rd|th)\b", r"\1", text)
    m = re.search(
        r"\b(?:on|from|effective(?: from)?|dated?)\s+(?:(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+)?(\d{1,2}\s+[A-Za-z]+\s+\d{4})\b",
        text_clean,
        re.I,
    )
    if m:
        return parse_cth_date(m.group(1))
    m2 = re.search(r"\b(\d{1,2}\s+[A-Za-z]+\s+\d{4})\b", text_clean)
    if m2:
        return parse_cth_date(m2.group(1))
    return None


def parse_sa_address(text: str | None) -> dict[str, str | None]:
    out: dict[str, str | None] = {"address": text, "suburb": None, "state": "SA", "postcode": None}
    if not text:
        return out
    m = re.search(
        r",?\s+(?P<suburb>[A-Za-z\s]+?)\s+(?P<state>SA|NSW|VIC|QLD|WA|TAS|NT|ACT)(?:\s+(?P<pc>\d{4}))?$",
        text.strip(),
    )
    if m:
        out["suburb"] = m.group("suburb").strip(" ,")
        out["state"] = m.group("state")
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
    headings = [h for h in soup.find_all(["h2", "h3", "h4"]) if re.search(r"SE[\s_-]*\d+", h.get_text())]
    rows: list[dict] = []

    for h in headings:
        raw_head = clean(h.get_text())
        se_norm = normalise_se(raw_head)
        srv_name = clean(re.sub(r"\(?\bSE[\s_-]*\d+\b\)?.*", "", raw_head).rstrip("–- "))

        p_texts = []
        curr = h.next_sibling
        while curr:
            if getattr(curr, "name", None) in ["h2", "h3", "h4"] and re.search(
                r"SE[\s_-]*\d+", curr.get_text()
            ):
                break
            txt = clean(curr.get_text(" ", strip=True)) if hasattr(curr, "get_text") else ""
            if txt:
                p_texts.append(txt)
            curr = curr.next_sibling

        blob = " ".join(p_texts)
        pr_norm = normalise_pr(blob)

        addr_m = re.search(r"Address:\s*(.*?)\s*Approved Provider:", blob)
        addr_raw = clean(addr_m.group(1)) if addr_m else None
        loc = parse_sa_address(addr_raw)

        prov_m = re.search(
            r"Approved Provider:\s*(.*?)(?:\(PR-|\bPR-|\bDetails:|\bAction Taken:)", blob
        )
        prov_raw = clean(prov_m.group(1)).rstrip("–- ") if prov_m else None

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

        action_m = re.search(
            r"Action Taken:\s*(.*?)(?:requiring the following|\.\s*Conduct|\.\s*Review|\.\s*Maintain|\.\s*Submit|\.\s*Develop|$)",
            blob,
            re.I,
        )
        action_raw = clean(action_m.group(1)) if action_m else "Compliance action"
        action_type, type_note = map_sa_action_type(action_raw)
        if type_note:
            notes.append(type_note)

        date_iso = parse_sa_date(action_raw)
        if not date_iso:
            date_iso = parse_sa_date(blob)

        det_m = re.search(r"Details:\s*(.*?)(?:Action Taken:|$)", blob)
        reason = clean(det_m.group(1)) if det_m else None

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
            "state": loc["state"] or "SA",
            "postcode": loc["postcode"],
            "action_type": action_type,
            "action_type_raw": action_raw,
            "reason": reason,
            "legal_references": legal_refs,
            "date_issued": date_iso,
            "date_issued_raw": date_iso,
            "period_label": "Current compliance action",
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
            fetched = fetch(INDEX_URL, retries=1, user_agent=common.BROWSER_USER_AGENT)
        except (httpx.HTTPError, common.RobotsDisallowed) as exc:
            log.error("SA ESB register unreachable: %r", exc)
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
        log.error("no enforcement rows parsed from SA ESB page")
        return 1

    out_rows = [{**r, "legal_references": json.dumps(r["legal_references"])} for r in rows]
    write_processed(
        OUTPUT_NAME,
        out_rows,
        FIELDNAMES,
        raw_inputs=[snapshot_path],
        schema=SCHEMA_PATH,
        notes="South Australia ESB compliance action register. Joined with SE- and PR- keys.",
    )
    log.info("%d rows parsed from %s", len(rows), snapshot_path.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
