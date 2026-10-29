"""Fetch and parse the Western Australia (ECRU) enforcement actions register.

Source: Department of Communities, Education and Care Regulatory Unit (WA).
URL: https://www.wa.gov.au/government/document-collections/education-and-care-regulatory-unit-enforcement-actions

The register is published via an embedded Caspio database application containing all
formal enforcement actions finalised in Western Australia under the Education and Care Services
National Law (WA) since 2013.

Action types:
- Compliance Notice -> compliance_notice
- Disciplinary Proceedings State Administrative Tribunal -> prosecution
- Prosecution -> prosecution
- Emergency Action Notice -> emergency_action_notice
- Cancellation of Provider / Service Approval -> approval_cancelled
- Suspension of Provider / Service Approval -> approval_suspended
- Service / Provider Approval Conditions Imposed -> condition_imposed
- Enforceable Undertaking -> enforceable_undertaking

Privacy:
Natural persons (sole traders / individuals / certified supervisors) have their names
withheld at ingest and INDIVIDUAL_NOTE added.

Run: python3 scrapers/parse_wa_enforcement.py [--skip-fetch] [--force]
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scrapers import common
from scrapers.common import (
    PROJECT_ROOT,
    RAW_DIR,
    USER_AGENT,
    list_snapshots,
    log,
    normalise_pr,
    normalise_se,
    record_hash,
    utc_now,
    write_processed,
)
from scrapers.profile_providers import classify_entity_form

INDIVIDUAL_NOTE = "subject is an individual; name withheld"
_PERSON_ROLE = re.compile(
    r"\b(?:director|secretary|nominee|owner|proprietor|manager|supervisor|educator)\s+(?:of|for)\b",
    re.IGNORECASE,
)
SOURCE = "wa-enforcement"
JURISDICTION = "WA"
INDEX_URL = "https://www.wa.gov.au/government/document-collections/education-and-care-regulatory-unit-enforcement-actions"
CASPIO_DIRECT_URL = "https://c0hcb777.caspio.com/dp/fca3a000e3e8111533de4a83871a"
OUTPUT_NAME = "wa-enforcement-actions"
SCHEMA_PATH = PROJECT_ROOT / "data" / "schemas" / "enforcement-action.schema.json"

COLUMNS = [
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


def map_wa_action_type(raw: str) -> tuple[str, str | None]:
    low = raw.lower().strip()
    if "compliance notice" in low:
        return "compliance_notice", None
    if "state administrative tribunal" in low or "sat" in low:
        return "prosecution", "State Administrative Tribunal disciplinary proceeding"
    if "prosecution" in low:
        return "prosecution", None
    if "emergency action" in low:
        return "emergency_action_notice", None
    if "cancellation" in low:
        return "approval_cancelled", None
    if "suspension" in low:
        return "approval_suspended", None
    if "condition" in low:
        return "condition_imposed", None
    if "enforceable undertaking" in low:
        return "enforceable_undertaking", None
    if "prohibition" in low:
        return "prohibition_notice", None
    return "other", None


def parse_wa_date(text: str | None) -> str | None:
    if not text or not text.strip():
        return None
    # e.g. 16/09/2013 or 2013-09-16
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", text.strip())
    if m:
        day, month, year = m.groups()
        try:
            return f"{year}-{int(month):02d}-{int(day):02d}"
        except ValueError:
            return None
    m_iso = re.search(r"(\d{4})-(\d{2})-(\d{2})", text.strip())
    if m_iso:
        return m_iso.group(0)
    return None


def extract_provider_info(
    raw_text: str | None,
) -> tuple[str | None, str | None, str | None, list[str]]:
    """Extract (provider_name, pr_norm, cs_norm, notes) from 'Provider (provider number)' cell."""
    if not raw_text or not raw_text.strip():
        return None, None, None, []

    clean_text = raw_text.strip()
    # Strip label prefix if present: "Provider (provider number): ..."
    if ":" in clean_text and clean_text.lower().startswith("provider"):
        clean_text = clean_text.split(":", 1)[1].strip()

    notes: list[str] = []
    pr_norm: str | None = None
    cs_norm: str | None = None

    # Check for PR number: e.g. (PR-00007392), (PR 00007412), (PR: 00007040)
    pr_match = re.search(r"\bPR[-:\s]*(\d+)\b", clean_text, re.IGNORECASE)
    if pr_match:
        pr_norm = normalise_pr(f"PR-{pr_match.group(1)}")

    # Check for CS number: e.g. (CS-00051586) Certified Supervisor
    cs_match = re.search(r"\bCS[-:\s]*(\d+)\b", clean_text, re.IGNORECASE)
    if cs_match:
        cs_norm = f"CS-{cs_match.group(1).zfill(8)}"
        notes.append(f"certified_supervisor: {cs_norm}")

    # Remove parenthesized numbers from name
    name_part = re.sub(r"\((?:PR|CS)[^)]*\)", "", clean_text, flags=re.IGNORECASE).strip()
    name_part = re.sub(r"\s+", " ", name_part).strip(" ,-")

    prov_name: str | None = name_part if name_part else None

    # Privacy check: withhold individuals, including a person named with a role
    # ("<person>, director of <company>").
    if prov_name:
        form = classify_entity_form(prov_name)
        if form == "likely_individual" or cs_norm is not None or _PERSON_ROLE.search(prov_name):
            prov_name = None
            notes.append(INDIVIDUAL_NOTE)

    return prov_name, pr_norm, cs_norm, notes


def extract_service_info(
    raw_text: str | None,
) -> tuple[str | None, str | None, str | None, str | None]:
    """Extract (service_name, se_norm, address, suburb) from 'Service name' cell."""
    if not raw_text or not raw_text.strip():
        return None, None, None, None

    clean_text = raw_text.strip()
    if ":" in clean_text and clean_text.lower().startswith("service"):
        clean_text = clean_text.split(":", 1)[1].strip()

    se_norm: str | None = None
    se_match = re.search(r"\bSE[-:\s]*(\d+)\b", clean_text, re.IGNORECASE)
    if se_match:
        se_norm = normalise_se(f"SE-{se_match.group(1)}")

    # Split name and address if comma present
    # e.g. "Melville Day Care Centre, 39 Rome Road, Melville WA 6158"
    # or "Tiny Beez Education and Care Centre Claremont (SE-00012493), 2 Alfred Road Claremont WA"
    text_no_se = re.sub(r"\(SE[^)]*\)", "", clean_text, flags=re.IGNORECASE).strip()
    text_no_se = re.sub(r"\s+", " ", text_no_se)

    parts = [p.strip() for p in text_no_se.split(",") if p.strip()]
    if not parts:
        return None, se_norm, None, None

    srv_name = parts[0]
    address: str | None = None
    suburb: str | None = None

    if len(parts) > 1:
        address = ", ".join(parts[1:])
        # Try to extract suburb from end of address (before WA and postcode)
        m_sub = re.search(r",?\s*([A-Za-z\s]+)\s+(?:WA\s*)?(?:\d{4})?$", address)
        if m_sub and len(m_sub.group(1).strip().split()) <= 3:
            suburb = m_sub.group(1).strip().upper()

    return srv_name, se_norm, address, suburb


def _get_field(raw_texts: list[str], label: str, default_idx: int) -> str:
    for txt in raw_texts:
        if txt.lower().startswith(label.lower() + ":"):
            return txt.split(":", 1)[1].strip()
    if default_idx < len(raw_texts):
        t = raw_texts[default_idx]
        if ":" in t:
            return t.split(":", 1)[1].strip()
        return t
    return ""


def parse_wa_html_table(html_content: str, source_snapshot: str, captured_at: str) -> list[dict]:
    soup = BeautifulSoup(html_content, "html.parser")
    table = soup.find("table", class_="cbResultSetTable")
    if not table:
        return []

    rows = []
    data_trs = [tr for tr in table.find_all("tr") if tr.find_all("td")]

    for tr in data_trs:
        tds = tr.find_all("td")
        if len(tds) < 5:
            continue

        raw_texts = [td.get_text(separator=" ", strip=True) for td in tds]

        year_raw = _get_field(raw_texts, "Year of action", 0)
        date_raw = _get_field(raw_texts, "Date of action", 1)
        prov_raw = _get_field(raw_texts, "Provider (provider number)", 2)
        srv_raw = _get_field(raw_texts, "Service name", 3)
        action_raw = _get_field(raw_texts, "Compliance action type", 4)
        postcode_raw = _get_field(raw_texts, "Post code", 5) if len(tds) > 5 else ""

        if not action_raw and not prov_raw and not srv_raw:
            continue

        date_iso = parse_wa_date(date_raw)
        action_type, type_note = map_wa_action_type(action_raw)

        prov_name, pr_norm, cs_norm, prov_notes = extract_provider_info(prov_raw)
        srv_name, se_norm, address, suburb = extract_service_info(srv_raw)

        notes = list(prov_notes)
        if type_note:
            notes.append(type_note)

        postcode: str | None = None
        if postcode_raw:
            m_pc = re.search(r"\b(\d{4})\b", postcode_raw)
            if m_pc:
                postcode = m_pc.group(1)

        row = {
            "record_id": record_hash(
                JURISDICTION,
                srv_name or "",
                se_norm or pr_norm or "",
                action_type,
                date_iso or year_raw,
            ),
            "jurisdiction": JURISDICTION,
            "source_register": INDEX_URL,
            "source_document": INDEX_URL,
            "source_snapshot": source_snapshot,
            "captured_at": captured_at,
            "service_approval_number": se_norm,
            "service_approval_number_raw": se_norm,
            "provider_approval_number": pr_norm,
            "provider_approval_number_raw": pr_norm,
            "service_name": srv_name,
            "provider_name": prov_name,
            "address": address,
            "suburb": suburb,
            "state": "WA",
            "postcode": postcode,
            "action_type": action_type,
            "action_type_raw": action_raw if action_raw else "unspecified",
            "reason": None,
            "legal_references": [],
            "date_issued": date_iso,
            "date_issued_raw": date_raw if date_raw else None,
            "period_label": f"WA ECRU {year_raw}" if year_raw else "WA ECRU",
            "notes": "; ".join(notes) if notes else None,
        }
        rows.append(row)

    return rows


async def fetch_all_wa_playwright() -> str:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        # Identify the project honestly even through a real browser engine.
        page = await browser.new_page(user_agent=USER_AGENT)

        log.info("navigating to WA ECRU Caspio application: %s", CASPIO_DIRECT_URL)
        await page.goto(CASPIO_DIRECT_URL, wait_until="networkidle")

        search_btn = page.locator("input.cbSearchButton").first
        await search_btn.wait_for(timeout=15000)
        await search_btn.click()
        await page.wait_for_timeout(1500)
        await page.wait_for_load_state("networkidle")

        all_rows_html = []
        page_num = 1

        while True:
            # Wait for any modal spinner/overlay to clear
            try:
                await page.wait_for_selector(".UILocker", state="hidden", timeout=5000)
            except Exception:
                pass

            html = await page.content()
            soup = BeautifulSoup(html, "html.parser")
            table = soup.find("table", class_="cbResultSetTable")
            if not table:
                break

            data_rows = [tr for tr in table.find_all("tr") if tr.find_all("td")]
            for tr in data_rows:
                all_rows_html.append(str(tr))

            log.info(
                "WA page %d: collected %d rows (total: %d)",
                page_num,
                len(data_rows),
                len(all_rows_html),
            )

            next_links = page.locator('a.cbResultSetNavigationLinks:has(img[src*="set7_next"])')
            if await next_links.count() == 0 or not await next_links.first.is_visible():
                break

            clicked = False
            for attempt in range(3):
                try:
                    try:
                        await page.wait_for_selector(".UILocker", state="hidden", timeout=5000)
                    except Exception:
                        pass
                    await page.evaluate("""() => {
                        const el = document.querySelector('a.cbResultSetNavigationLinks img[src*="set7_next"]');
                        if (el && el.parentElement) {
                            el.parentElement.click();
                        }
                    }""")
                    await page.wait_for_timeout(800)
                    await page.wait_for_load_state("networkidle")
                    clicked = True
                    break
                except Exception as e:
                    log.warning("retry %d clicking next page: %r", attempt + 1, e)
                    await page.wait_for_timeout(1000)

            if not clicked:
                log.error("Failed to advance past page %d", page_num)
                break

            page_num += 1

        await browser.close()

        full_html = (
            f"<!DOCTYPE html><html><head><title>WA ECRU All Enforcement Actions</title></head>"
            f'<body><table class="cbResultSetTable">{"".join(all_rows_html)}</table></body></html>'
        )
        return full_html


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
        log.info("launching Playwright to scrape WA Caspio database...")
        html_content = asyncio.run(fetch_all_wa_playwright())
        stamp = common.utc_stamp()
        out_path = common._unique_path(RAW_DIR / SOURCE, stamp, "html")
        out_path.write_text(html_content, encoding="utf-8")

        # Write metadata sidecar
        meta = {
            "source": SOURCE,
            "url": INDEX_URL,
            "final_url": INDEX_URL,
            "status": 200,
            "fetched_at": utc_now().isoformat(),
            "content_type": "text/html;charset=utf-8",
            "last_modified": None,
            "etag": None,
            "bytes": len(html_content.encode("utf-8")),
            "sha256": hashlib.sha256(html_content.encode("utf-8")).hexdigest(),
            "user_agent": USER_AGENT,
        }
        Path(f"{out_path}.meta.json").write_text(
            json.dumps(meta, indent=2) + "\n", encoding="utf-8"
        )
        log.info("snapshot %s (%d bytes)", out_path.relative_to(PROJECT_ROOT), len(html_content))
        snapshot_path = out_path

    captured_at = utc_now().isoformat()
    meta_path = Path(f"{snapshot_path}.meta.json")
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            captured_at = meta.get("fetched_at", captured_at)
        except Exception:
            pass

    content = snapshot_path.read_text(encoding="utf-8")
    rows = parse_wa_html_table(content, snapshot_path.name, captured_at)
    log.info("parsed %d enforcement action rows from WA ECRU", len(rows))

    if SCHEMA_PATH.exists():
        import jsonschema

        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        validator = jsonschema.Draft202012Validator(schema)
        for i, row in enumerate(rows):
            errors = list(validator.iter_errors(row))
            if errors:
                for err in errors[:5]:
                    log.error(
                        "schema validation error row %d: %s (at %s)", i, err.message, list(err.path)
                    )
                return 1

    out_rows = [{**r, "legal_references": json.dumps(r["legal_references"])} for r in rows]
    write_processed(OUTPUT_NAME, out_rows, fieldnames=COLUMNS, raw_inputs=[snapshot_path])
    return 0


if __name__ == "__main__":
    sys.exit(main())
