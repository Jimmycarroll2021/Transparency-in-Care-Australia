"""Build the private prototype site from the committed processed data.

Usage: python site/build_site.py --out site/dist [--data data/processed]

Static HTML only: no framework, no external requests, no analytics, no cookies. The build reads
four processed files and makes no network calls:

- enforcement-actions-all.csv  (one row per published action, with join columns)
- enforcement-by-service.csv   (one row per service, counts by action type)
- enforcement-by-provider.csv  (one row per provider, counts by action type)
- enforcement-join-report.json (window, join rates, unmatched reasons)

Rendering safety:
- Every input row passes through an explicit column allowlist (pick) before any renderer sees
  it. Columns not in the allowlist, ACECQA ratings above all, never reach a page.
- Every value is HTML-escaped. Links are written only for https:// URLs.
- A withheld value shows its note, never a guess.
- Where a provider's name is withheld as a possible individual, its provider approval number is
  withheld too and no provider page is built.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import shutil
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
DEFAULT_DATA = REPO / "data" / "processed"
STATIC = HERE / "static"

BANNER = "Private prototype. Not for publication. Data and wording under legal review."
ABSENCE = "Absence of a record here is not evidence that a service is safe or compliant."
ROBOTS_META = '<meta name="robots" content="noindex,nofollow">'
ROBOTS_TXT = "User-agent: *\nDisallow: /\n"

ACTION_TYPES = [
    "condition_imposed",
    "approval_amended",
    "approval_suspended",
    "approval_cancelled",
    "compliance_notice",
    "compliance_direction",
    "emergency_action_notice",
    "enforceable_undertaking",
    "prohibition_notice",
    "direction_to_exclude",
    "infringement_notice",
    "show_cause_notice",
    "prosecution",
    "ccs_sanction",
    "other",
]

TYPE_LABELS = {
    "condition_imposed": "Condition imposed",
    "approval_amended": "Approval amended",
    "approval_suspended": "Approval suspended",
    "approval_cancelled": "Approval cancelled",
    "compliance_notice": "Compliance notice",
    "compliance_direction": "Compliance direction",
    "emergency_action_notice": "Emergency action notice",
    "enforceable_undertaking": "Enforceable undertaking",
    "prohibition_notice": "Prohibition notice",
    "direction_to_exclude": "Direction to exclude",
    "infringement_notice": "Infringement notice",
    "show_cause_notice": "Show cause notice",
    "prosecution": "Prosecution",
    "ccs_sanction": "Child Care Subsidy action",
    "other": "Other",
}

# Plain-language summaries for the sources and methods page. They describe this project's
# categories; the law and each register's own text govern.
TYPE_DEFINITIONS = {
    "condition_imposed": "The regulator placed a condition on a provider or service approval.",
    "approval_amended": "The regulator changed the terms of a provider or service approval.",
    "approval_suspended": "A provider or service approval was suspended for a period.",
    "approval_cancelled": (
        "A provider or service approval was cancelled. Some registers list cancellations made "
        "because a provider had stopped operating any service."
    ),
    "compliance_notice": (
        "A written notice requiring the approved provider to take stated steps to comply with "
        "the law."
    ),
    "compliance_direction": (
        "A written direction to the approved provider to take stated steps to comply with the law."
    ),
    "emergency_action_notice": (
        "A notice requiring urgent steps where the regulator considered there was an immediate "
        "risk to children."
    ),
    "enforceable_undertaking": (
        "A written undertaking given by the provider and accepted by the regulator, which the "
        "regulator can enforce."
    ),
    "prohibition_notice": "A notice prohibiting a person from working in or providing a service.",
    "direction_to_exclude": "A direction to exclude a person from the service premises.",
    "infringement_notice": "A notice issuing a fixed penalty for an alleged offence.",
    "show_cause_notice": (
        "A notice asking the provider to explain why the regulator should not take a further "
        "step, such as suspension or cancellation."
    ),
    "prosecution": (
        "Court or tribunal proceedings brought by a regulator, including Western Australian "
        "State Administrative Tribunal disciplinary proceedings. A prosecution is not a "
        "conviction. Where the register prints an outcome, it is shown as printed."
    ),
    "ccs_sanction": (
        "An action by the Australian Government Department of Education under family assistance "
        "law, such as conditions on, or cancellation of, approval to administer the Child Care "
        "Subsidy."
    ),
    "other": (
        "An action that fits none of the categories above, or that could not be classified with "
        "confidence. The register's own label is always shown."
    ),
}

JURISDICTION_ORDER = ["NSW", "VIC", "QLD", "SA", "WA", "TAS", "CTH"]

# Regulator facts for the sources and methods page. Licence wording follows the project's
# register audits: research/2026-10-29-register-enforcement-nsw-vic-qld-cth.md and
# research/2026-10-29-register-enforcement-sa-wa-tas-nt-act.md. Where an audit could not confirm
# a licence, the page says so rather than assuming one.
REGULATORS = {
    "NSW": {
        "name": "NSW Department of Education",
        "published": (
            "Quarterly PDF registers of enforcement actions, cancellations and suspensions, "
            "printing service and provider approval numbers."
        ),
        "licence": (
            "Creative Commons Attribution 4.0 (CC BY 4.0). Copyright State of New South Wales "
            "(Department of Education)."
        ),
    },
    "VIC": {
        "name": "Victorian regulator (VECRA)",
        "published": (
            "Monthly HTML pages of enforcement actions, printing service and provider approval "
            "numbers. Earlier years are PDF and Word files excluded by the site's robots.txt and "
            "not collected."
        ),
        "licence": (
            "Creative Commons Attribution 4.0 (CC BY 4.0). Copyright State Government of Victoria."
        ),
    },
    "QLD": {
        "name": "Queensland Department of Education",
        "published": (
            "One HTML register of published enforcement actions. It prints no approval numbers "
            "and states that it is not a comprehensive list; entries can be removed."
        ),
        "licence": (
            "The Department's copyright statement applies CC BY 4.0 unless otherwise noted. The "
            "register page states no licence of its own, and it is not confirmed that the "
            "statement covers it."
        ),
    },
    "SA": {
        "name": "Education Standards Board (South Australia)",
        "published": (
            "Current and historical compliance action pages. Pages before 2022 print no approval "
            "numbers."
        ),
        "licence": (
            "All rights reserved. Copyright Government of South Australia. Not openly licensed; "
            "used here for non-commercial research only."
        ),
    },
    "WA": {
        "name": "Department of Communities, Education and Care Regulatory Unit (Western Australia)",
        "published": (
            "A search form over finalised enforcement actions, including State Administrative "
            "Tribunal proceedings, from 2013."
        ),
        "licence": (
            "wa.gov.au terms of use: personal and non-commercial use with attribution; no "
            "commercial reuse. Not openly licensed."
        ),
    },
    "TAS": {
        "name": "Education and Care Unit, Department for Education, Children and Young People "
        "(Tasmania)",
        "published": "One HTML page of published enforcement actions under the National Law.",
        "licence": "Not confirmed. No licence statement was found on the data page.",
    },
    "CTH": {
        "name": "Australian Government Department of Education",
        "published": (
            "The Child Care Subsidy enforcement action register, current and past pages. It "
            "prints no approval numbers. Saved by hand from a browser, because the site does not "
            "answer scripts."
        ),
        "licence": "Not confirmed. The licence could not be retrieved when the register was audited.",
    },
}

MATCH_LABELS = {
    "exact_key": "Joined by the approval number printed in the register.",
    "exact_key_unlisted": (
        "Joined by the approval number printed in the register. The approval is not in the "
        "current ACECQA register export, usually because it has ceased."
    ),
    "provider_and_service_name": (
        "Joined by name, not by a printed approval number: exactly one approved provider has "
        "this name, and the service was pinned by name among its services."
    ),
    "provider_name_unique": (
        "Joined by name, not by a printed approval number: exactly one approved provider has "
        "this name."
    ),
    "name_only": (
        "Joined by name, not by a printed approval number: exactly one approved service has "
        "this name."
    ),
    "abn_unique_entity": (
        "Joined through the ABN printed in the register, matched by name to exactly one "
        "approved provider. This is a name match anchored by the ABN."
    ),
}

RESIDUAL_LABELS = {
    "no_key_and_name_withheld": (
        "No approval number printed, and the subject's name was withheld as a possible "
        "individual, so no name match was attempted."
    ),
    "no_key_no_name_match": (
        "No approval number printed, and no approved service or provider has the printed name "
        "(or a unique name match was not possible)."
    ),
    "ambiguous_name": "No approval number printed, and more than one candidate shares the name.",
    "other": "Another stated reason, for example a printed key that could not be parsed.",
}

# ---------------------------------------------------------------------------------------------
# Column allowlists. A renderer only ever receives the output of pick(row, ALLOWLIST).

ACTION_COLUMNS = (
    "record_id",
    "jurisdiction",
    "source_register",
    "source_document",
    "captured_at",
    "action_type",
    "action_type_raw",
    "reason",
    "date_issued",
    "period_label",
    "penalty_amount_aud",
    "match_confidence",
    "notes",  # only withheld and date segments are rendered: see note_segments()
)

COUNT_COLUMNS = tuple(f"count_{t}" for t in ACTION_TYPES) + tuple(
    f"last24m_{t}" for t in ACTION_TYPES
)

SERVICE_COLUMNS = (
    "service_approval_number",
    "provider_approval_number",
    "service_name",
    "suburb",
    "state",
    "spine_status",
    "window_start",
    "window_end",
    "actions_total",
    "actions_last_24_months",
    "first_action_date",
    "last_action_date",
    "actions_matched_by_name",
    "jurisdictions_publishing",
    "coverage_note",
    *COUNT_COLUMNS,
)

PROVIDER_COLUMNS = (
    "provider_approval_number",
    "legal_name",
    "trading_name",
    "name_withheld",
    "spine_status",
    "service_count",
    "service_count_basis",
    "services_with_any_action",
    "service_level_actions",
    "provider_level_actions",
    "actions_matched_by_name",
    "window_start",
    "window_end",
    "actions_total",
    "actions_last_24_months",
    "first_action_date",
    "last_action_date",
    "jurisdictions_publishing",
    "coverage_note",
    *COUNT_COLUMNS,
)

# The search index carries postcode as well, for search only.
INDEX_SERVICE_COLUMNS = (
    "service_approval_number",
    "service_name",
    "suburb",
    "postcode",
    "state",
)

# Columns deliberately not rendered, with the reason. Reported by --report-columns and checked
# by the tests: every column of each input is either allowlisted or listed here.
EXCLUDED = {
    "actions": {
        "occurrence": "internal row counter",
        "source_snapshot": "local archive path, not a public source",
        "service_approval_number": "the joined entity's number is shown instead",
        "service_approval_number_raw": "raw printed text; the normalised key is shown",
        "provider_approval_number": "the joined entity's number is shown instead",
        "provider_approval_number_raw": "raw printed text; the normalised key is shown",
        "service_name": "name as printed in the register; the joined entity's name is shown",
        "provider_name": "name as printed in the register; the joined entity's name is shown",
        "address": "street address: can locate an individual provider",
        "suburb": "the joined entity's suburb is shown instead",
        "state": "the joined entity's state is shown instead",
        "postcode": "the joined entity's postcode is used in search instead",
        "legal_references": "not in the page specification; the reason text cites them",
        "date_issued_raw": "raw printed text; the parsed date is shown",
        "linked_documents": "QLD supporting documents were not fetched or reviewed",
        "service_type": "not in the page specification",
        "start_date": "not in the page specification",
        "end_date": "not in the page specification",
        "date_charged": "prosecution detail, pending legal review",
        "date_of_sentence": "prosecution detail, pending legal review",
        "plea": "prosecution detail, pending legal review",
        "abn": "not in the page specification",
        "join_key_kind": "internal; the join basis is shown in plain words",
        "join_note": "internal; the join basis is shown in plain words",
        "acecqa_service_approval_number": "used for joining only",
        "acecqa_service_name": "ACECQA content; the service table name is shown",
        "acecqa_provider_approval_number": "used for joining only",
        "acecqa_provider_legal_name": "ACECQA content; the provider table name is shown",
        "acecqa_state": "ACECQA content, used for joining only",
        "acecqa_service_type": "ACECQA content, not in the page specification",
        "acecqa_overall_rating": "ACECQA rating: no consent held",
        "acecqa_rating_issued": "ACECQA rating date: no consent held",
        "provider_entity_form": "heuristic classification, can mislabel",
        "provider_service_count": "shown on the provider page from the provider table",
        "counted_in_totals": "used to drop duplicate source rows",
        "spine_status": "used to label stub entities",
    },
    "services": {
        "postcode": "search index only",
        "service_type": "not in the page specification",
        "acecqa_overall_rating": "ACECQA rating: no consent held",
        "acecqa_rating_issued": "ACECQA rating date: no consent held",
    },
    "providers": {
        "entity_form": "heuristic classification, can mislabel",
        "provider_state": "not in the page specification",
        "states_operated_in": "not in the page specification",
        "services_with_any_action_last_24_months": "not in the page specification",
        "actions_last_24_months_per_service": (
            "rate mixes a historic numerator with a current denominator"
        ),
    },
}

RATING_PATTERN = re.compile(r"rating", re.I)

# A joined action whose notes say the subject is, or may be, an individual, or that a service or
# provider name was withheld. The service's own name is then withheld too: an ACECQA service name
# can embed the name of an individual approved provider.
INDIVIDUAL_NOTE = re.compile(
    r"subject is an individual|subject may be an individual|service name withheld|"
    r"provider name withheld|name withheld",
    re.I,
)
SERVICE_NAME_WITHHELD = (
    "Service name withheld: the service's provider is, or may be, an individual, and a service "
    "name can contain the provider's name."
)


def pick(row: dict, allowlist: tuple[str, ...]) -> dict:
    """Return a copy of row holding only allowlisted, non-rating columns."""
    return {c: (row.get(c) or "").strip() for c in allowlist if not RATING_PATTERN.search(c)}


# ---------------------------------------------------------------------------------------------
# Small helpers


def esc(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def is_true(value: str | None) -> bool:
    return (value or "").strip().lower() == "true"


def to_int(value: str | None) -> int:
    try:
        return int(float(value or 0))
    except ValueError:
        return 0


def fmt_int(n: int) -> str:
    return f"{n:,}"


MONTHS = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]


def fmt_date(value: str | None) -> str:
    """'2026-10-28' (or an ISO timestamp) as '28 October 2026'. Unparsable text is returned as is."""
    text = (value or "").strip()
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", text)
    if not m:
        return text
    try:
        d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return text
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}"


def fmt_date_short(value: str | None) -> str:
    """'2026-10-28' as '28 Oct 2026', for narrow table headers."""
    full = fmt_date(value)
    m = re.match(r"^(\d{1,2}) ([A-Z][a-z]+) (\d{4})$", full)
    return f"{m.group(1)} {m.group(2)[:3]} {m.group(3)}" if m else full


def fmt_money(value: str) -> str:
    try:
        amount = float(value)
    except ValueError:
        return value
    return f"${amount:,.0f}" if amount == int(amount) else f"${amount:,.2f}"


def date_range(first: str, last: str) -> str:
    """Plain wording for a span of dates; one date when both ends agree."""
    a, b = fmt_date(first), fmt_date(last)
    if not a and not b:
        return "with no parsable date"
    if a == b or not b:
        return f"dated {a}"
    if not a:
        return f"dated {b}"
    return f"dated {a} to {b}"


def are(n: int) -> str:
    return "is" if n == 1 else "are"


def percent(part: int, whole: int) -> str:
    return f"{100 * part / whole:.1f} per cent" if whole else "not defined"


def safe_url(url: str) -> str | None:
    url = (url or "").strip()
    return url if re.match(r"^https://[^\s\"'<>]+$", url) else None


KEY_PATTERN = re.compile(r"^(SE|PR)-\d{8}$")


def safe_key(key: str) -> str | None:
    key = (key or "").strip()
    return key if KEY_PATTERN.match(key) else None


def note_segments(notes: str) -> tuple[list[str], list[str]]:
    """Return (withheld notes, date notes) from a parser notes field.

    Only fixed parser wording is rendered: segments that say a value was withheld, and segments
    that qualify the date. Segments quoting printed values (in quotes) are never rendered.
    """
    withheld, dated = [], []
    for seg in re.split(r"; | \| ", notes or ""):
        seg = seg.strip()
        if not seg or "'" in seg or '"' in seg:
            continue
        if "withheld" in seg.lower() or seg.lower() in ("subject is an individual",):
            if seg not in withheld:
                withheld.append(seg)
        elif seg.lower().startswith("date "):
            if seg not in dated:
                dated.append(seg)
    return withheld, dated


# ---------------------------------------------------------------------------------------------
# Loading


def read_csv(path: Path) -> tuple[list[str], list[dict]]:
    csv.field_size_limit(10**8)
    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
        return list(reader.fieldnames or []), rows


class Data:
    def __init__(self, data_dir: Path):
        self.action_columns, actions = read_csv(data_dir / "enforcement-actions-all.csv")
        self.service_columns, services = read_csv(data_dir / "enforcement-by-service.csv")
        self.provider_columns, providers = read_csv(data_dir / "enforcement-by-provider.csv")
        self.report = json.loads(
            (data_dir / "enforcement-join-report.json").read_text(encoding="utf-8")
        )
        self.actions_all = actions
        self.services = {
            r["service_approval_number"]: r for r in services if r.get("service_approval_number")
        }
        self.providers = {
            r["provider_approval_number"]: r for r in providers if r.get("provider_approval_number")
        }
        self.stub_providers = {
            k for k, r in self.providers.items() if r.get("spine_status") != "current"
        }
        self.window_start = self.report["window"]["start"]
        self.window_end = self.report["window"]["end"]
        self.assign()

    def assign(self) -> None:
        """Attribute each counted action to a service and provider, as the join does."""
        self.by_service: dict[str, list[dict]] = defaultdict(list)
        self.provider_level: dict[str, list[dict]] = defaultdict(list)
        self.uncounted = 0
        self.withheld_service_names: set[str] = {
            se
            for se, r in self.services.items()
            if is_true(
                self.providers.get(r.get("provider_approval_number") or "", {}).get("name_withheld")
            )
        }
        for row in self.actions_all:
            se_any = row.get("acecqa_service_approval_number") or (
                row.get("service_approval_number")
                if row.get("join_key_kind") == "service_key_unlisted"
                else None
            )
            if se_any and INDIVIDUAL_NOTE.search(row.get("notes") or ""):
                self.withheld_service_names.add(se_any)
            if not is_true(row.get("counted_in_totals")):
                self.uncounted += 1
                continue
            kind = row.get("join_key_kind") or "none"
            se = pr = None
            if kind in ("service", "name_match"):
                se = row.get("acecqa_service_approval_number") or None
                pr = row.get("acecqa_provider_approval_number") or None
            elif kind in ("provider_name_match", "abn_entity_match", "provider"):
                se = row.get("acecqa_service_approval_number") or None
                pr = row.get("acecqa_provider_approval_number") or None
            elif kind == "service_key_unlisted":
                se = row.get("service_approval_number") or None
                pr = row.get("provider_approval_number") or None
                if pr not in self.stub_providers:
                    pr = None
            elif kind == "provider_key_unlisted":
                pr = row.get("provider_approval_number") or None
            if se:
                self.by_service[se].append(row)
            elif pr:
                self.provider_level[pr].append(row)

    def service_name(self, se: str) -> str | None:
        """The service's published name, or None when it is withheld or not published."""
        if se in self.withheld_service_names:
            return None
        return (self.services.get(se, {}).get("service_name") or "").strip() or None

    def check(self) -> list[str]:
        """Return mismatches between the listed actions and the processed totals."""
        problems = []
        for se, svc in self.services.items():
            listed = len(self.by_service.get(se, []))
            if listed != to_int(svc.get("actions_total")):
                problems.append(f"{se}: {listed} listed, actions_total {svc.get('actions_total')}")
        for pr, prov in self.providers.items():
            level = len(self.provider_level.get(pr, []))
            if level != to_int(prov.get("provider_level_actions")):
                problems.append(
                    f"{pr}: {level} provider-level listed, "
                    f"provider_level_actions {prov.get('provider_level_actions')}"
                )
        return problems


# ---------------------------------------------------------------------------------------------
# Page frame

NAV = (
    ("index.html#search", "Search"),
    ("sources.html", "Sources and methods"),
)

FAVICON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 22 22">'
    '<rect x="1" y="1" width="20" height="20" rx="4" fill="#0B5566"/>'
    '<rect x="5" y="6" width="12" height="2" rx="1" fill="#fff"/>'
    '<rect x="5" y="10" width="9" height="2" rx="1" fill="#fff"/>'
    '<rect x="5" y="14" width="11" height="2" rx="1" fill="#fff"/></svg>\n'
)

# A small register mark for the wordmark: three ruled lines of differing length.
MARK_SVG = (
    '<svg class="wm-mark" width="22" height="22" viewBox="0 0 22 22" aria-hidden="true" '
    'focusable="false"><rect x="1" y="1" width="20" height="20" rx="4" class="wm-box"/>'
    '<rect x="5" y="6" width="12" height="2" rx="1" class="wm-line"/>'
    '<rect x="5" y="10" width="9" height="2" rx="1" class="wm-line"/>'
    '<rect x="5" y="14" width="11" height="2" rx="1" class="wm-line"/></svg>'
)


def page(
    title: str,
    body: str,
    depth: int = 0,
    description: str = "",
    current: str = "",
    base: str | None = None,
) -> str:
    """Wrap a page body in the shared frame. base overrides the relative prefix: the 404 page is
    served at any path, so it links from the site root."""
    up = base if base is not None else "../" * depth
    links = []
    for href, label in NAV:
        mark = ' aria-current="page"' if href == current else ""
        links.append(f'<a href="{up}{href}"{mark}>{esc(label)}</a>')
    desc = f'<meta name="description" content="{esc(description)}">\n' if description else ""
    return (
        "<!doctype html>\n"
        '<html lang="en-AU">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"{ROBOTS_META}\n"
        '<meta name="referrer" content="no-referrer">\n'
        '<meta name="color-scheme" content="light dark">\n'
        f"{desc}"
        f"<title>{esc(title)} | Transparency in Care Australia (prototype)</title>\n"
        f'<link rel="stylesheet" href="{up}assets/site.css">\n'
        f'<link rel="icon" href="{up}assets/favicon.svg" type="image/svg+xml">\n'
        "</head>\n<body>\n"
        '<a class="skip" href="#main">Skip to content</a>\n'
        f'<div class="banner" role="note"><div class="wrap"><strong>{esc(BANNER)}</strong></div></div>\n'
        '<header class="site-header"><div class="wrap header-inner">'
        f'<a class="wordmark" href="{up}index.html">{MARK_SVG}'
        "<span>Transparency in Care Australia</span></a>\n"
        f'<nav class="site-nav" aria-label="Main">{"".join(links)}</nav></div></header>\n'
        f'<main id="main" class="wrap">\n{body}\n</main>\n'
        '<footer class="site-footer"><div class="wrap">'
        f"<p><strong>{esc(BANNER)}</strong></p>"
        "<p>Every entry links to the regulator's own published record. An enforcement action is a "
        "step a regulator took; it is not a finding of guilt and not a conviction. "
        f"{esc(ABSENCE)}</p>"
        f'<p><a href="{up}sources.html">Sources and methods</a></p>'
        "</div></footer>\n"
        "</body>\n</html>\n"
    )


def absence_block() -> str:
    return (
        '<div class="absence" role="note"><svg class="absence-icon" width="20" height="20" '
        'viewBox="0 0 20 20" aria-hidden="true" focusable="false"><circle cx="10" cy="10" r="9" '
        'class="icon-ring"/><rect x="9" y="8.5" width="2" height="6" rx="1" class="icon-glyph"/>'
        '<circle cx="10" cy="5.8" r="1.2" class="icon-glyph"/></svg>'
        f"<p><strong>{esc(ABSENCE)}</strong></p></div>"
    )


# ---------------------------------------------------------------------------------------------
# Visual building blocks: category badges, chips, charts. Every chart is inline SVG with a
# title, a description and a table alternative; every badge carries its category's text label.

JURISDICTION_NAMES = {
    "NSW": "New South Wales",
    "VIC": "Victoria",
    "QLD": "Queensland",
    "SA": "South Australia",
    "WA": "Western Australia",
    "TAS": "Tasmania",
    "CTH": "Commonwealth (Child Care Subsidy)",
}


def category(action_type: str) -> str:
    return action_type if action_type in TYPE_LABELS else "other"


def badge(action_type: str) -> str:
    t = category(action_type)
    return f'<span class="badge cat-{t}">{esc(TYPE_LABELS[t])}</span>'


def time_tag(value: str) -> str:
    """A <time> element for an ISO date, or the plain text when it does not parse."""
    text = (value or "").strip()
    m = re.match(r"^\d{4}-\d{2}-\d{2}", text)
    if not m:
        return esc(fmt_date(text))
    return f'<time datetime="{esc(m.group(0))}">{esc(fmt_date(text))}</time>'


def chips(items: list[tuple[str, str]]) -> str:
    """A row of stat chips: (value html, label html)."""
    lis = "".join(
        f'<li class="chip"><span class="chip-value">{v}</span>'
        f'<span class="chip-label">{lab}</span></li>'
        for v, lab in items
    )
    return f'<ul class="chips">{lis}</ul>'


def bar_chart(
    cid: str, title: str, desc: str, items: list[tuple[str, int, str]], total: int
) -> str:
    """A horizontal bar chart as inline SVG, with a table alternative.

    Bars are sized in percentages of the SVG's own width and the SVG has no viewBox, so the text
    keeps its size at any screen width. Each value is printed with its denominator.
    """
    row_h = 46
    peak = max((v for _, v, _ in items), default=0) or 1
    rows = []
    for i, (label, value, cls) in enumerate(items):
        y = i * row_h
        width = 100 * value / peak
        if value and width < 0.8:
            width = 0.8
        rows.append(
            f'<g class="chart-row"><text class="chart-label" x="0" y="{y + 17}">{esc(label)}</text>'
            f'<text class="chart-value" x="100%" y="{y + 17}" text-anchor="end">'
            f"{fmt_int(value)} of {fmt_int(total)}</text>"
            f'<rect class="chart-track" x="0" y="{y + 25}" width="100%" height="12" rx="3"/>'
            f'<rect class="bar {cls}" x="0" y="{y + 25}" width="{width:.2f}%" height="12" '
            'rx="3"/></g>'
        )
    height = row_h * len(items)
    table_rows = "".join(
        f'<tr><th scope="row">{esc(label)}</th><td>{fmt_int(value)} of {fmt_int(total)}</td></tr>'
        for label, value, _ in items
    )
    return (
        f'<figure class="chart-figure" aria-labelledby="{cid}-cap">'
        f'<figcaption id="{cid}-cap"><span class="chart-title">{esc(title)}</span>'
        f'<span class="chart-desc">{esc(desc)}</span></figcaption>'
        f'<svg class="chart" width="100%" height="{height}" role="img" '
        f'aria-labelledby="{cid}-t {cid}-d"><title id="{cid}-t">{esc(title)}</title>'
        f'<desc id="{cid}-d">{esc(desc)}</desc>{"".join(rows)}</svg>'
        '<details class="chart-table"><summary>Show the figures as a table</summary>'
        f'<table class="counts"><caption>{esc(title)}</caption><thead><tr>'
        '<th scope="col">Group</th><th scope="col">Rows</th></tr></thead>'
        f"<tbody>{table_rows}</tbody></table></details></figure>"
    )


def sparkline(per_year: dict[int, int], years: list[int], label: str, undated: int = 0) -> str:
    """A small bar sparkline of actions per year, with a text title."""
    if not years:
        return ""
    width, height = 120, 30
    slot = width / len(years)
    bar = max(slot - 2, 1.5)
    peak = max(per_year.values(), default=0) or 1
    rects = []
    for i, year in enumerate(years):
        n = per_year.get(year, 0)
        x = i * slot + (slot - bar) / 2
        if n:
            h = max(3.0, (height - 2) * n / peak)
            rects.append(
                f'<rect class="spark-bar" x="{x:.1f}" y="{height - h:.1f}" '
                f'width="{bar:.1f}" height="{h:.1f}" rx="1"/>'
            )
        else:
            rects.append(
                f'<rect class="spark-zero" x="{x:.1f}" y="{height - 1:.1f}" '
                f'width="{bar:.1f}" height="1"/>'
            )
    parts = [f"{y}: {per_year[y]}" for y in years if per_year.get(y)]
    text = f"{label}, {years[0]} to {years[-1]}. " + ("; ".join(parts) or "None dated") + "."
    if undated:
        text += f" {fmt_int(undated)} with no parsable date."
    return (
        f'<svg class="spark" width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'role="img"><title>{esc(text)}</title>{"".join(rects)}</svg>'
    )


# ---------------------------------------------------------------------------------------------
# Action rendering


SHORT_TEXT = 300


def withheld_text(notes: list[str]) -> str:
    if not notes:
        return "Withheld by the parser. No note was recorded."
    return "Withheld: " + "; ".join(notes) + "."


def action_label_html(a: dict, withheld: list[str]) -> str:
    """The register's own label, or the withheld note where the label was withheld."""
    label = a["action_type_raw"]
    if not label or label == "(withheld)":
        return f'<span class="withheld">{esc(withheld_text(withheld))}</span>'
    return esc(label)


def source_link(a: dict) -> str:
    doc = safe_url(a["source_document"])
    register = safe_url(a["source_register"])
    captured = fmt_date(a["captured_at"])
    if doc:
        host = re.sub(r"^https://([^/]+).*$", r"\1", doc)
        link = (
            f'<a class="source-link" href="{esc(doc)}" rel="noreferrer">View source record</a> '
            f'<span class="note">on {esc(host)}.</span>'
        )
    elif register:
        link = (
            f'<a class="source-link" href="{esc(register)}" rel="noreferrer">View the register</a> '
            '<span class="note">(the specific page is withheld: it may name an individual).</span>'
        )
    else:
        link = '<span class="note">Source not available.</span>'
    return f'<p class="action-source">{link} <span class="note">Captured {esc(captured)} (UTC).</span></p>'


def render_action(raw: dict) -> str:
    """One timeline item: the date, then a card with the category badge and the register's label."""
    a = pick(raw, ACTION_COLUMNS)
    withheld, dated = note_segments(a["notes"])
    jurisdiction = a["jurisdiction"]
    regulator = REGULATORS.get(jurisdiction, {}).get("name", jurisdiction)

    if a["date_issued"]:
        date_html = time_tag(a["date_issued"])
    else:
        date_html = (
            '<span class="nodate">Date not printed as a parsable date. See the source.</span>'
        )
    if dated:
        date_html += f'<span class="note date-note">({esc("; ".join(dated))})</span>'

    sub = esc(f"{regulator} ({jurisdiction}).")
    if a["period_label"]:
        sub += f" Register period {esc(a['period_label'])}."

    facts = []
    if a["penalty_amount_aud"]:
        facts.append(
            (
                "Penalty",
                f'<span class="penalty">{esc(fmt_money(a["penalty_amount_aud"]))}</span> '
                '<span class="note">(the fine amount printed in the register entry\'s headline; '
                "read the register entry for the full outcome)</span>",
            )
        )
    facts.append(("How it was joined", esc(MATCH_LABELS.get(a["match_confidence"], "Not stated."))))
    facts.append(("Record", f"<code>{esc(a['record_id'])}</code>"))
    facts_html = "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in facts)

    if a["reason"] and len(a["reason"]) <= SHORT_TEXT:
        reason = (
            '<div class="reason"><p class="reason-label">Description as printed</p>'
            f'<blockquote class="quote">{esc(a["reason"])}</blockquote></div>'
        )
    elif a["reason"]:
        reason = (
            '<details class="reason"><summary>Description as printed '
            f'<span class="note">({fmt_int(len(a["reason"]))} characters)</span></summary>'
            f'<blockquote class="quote">{esc(a["reason"])}</blockquote></details>'
        )
    elif any("free text withheld" in n for n in withheld):
        reason = (
            '<div class="reason"><p class="reason-label">Description</p>'
            f'<p class="withheld">{esc(withheld_text(withheld))}</p></div>'
        )
    else:
        reason = ""

    return (
        '<li class="tl-item">'
        f'<p class="tl-date">{date_html}</p>'
        '<article class="action">'
        f'<header class="action-head"><p class="action-cat"><span class="visually-hidden">Category: </span>{badge(a["action_type"])}</p>'
        f'<h3 class="action-label"><span class="visually-hidden">Action as labelled by the '
        f"register: </span>{action_label_html(a, withheld)}</h3>"
        f'<p class="action-sub">{sub}</p></header>'
        f"{reason}"
        f'<dl class="action-facts">{facts_html}</dl>'
        f"{source_link(a)}"
        "</article></li>"
    )


def timeline(rows: list[dict]) -> str:
    return '<ol class="timeline">' + "".join(render_action(a) for a in rows) + "</ol>"


def sort_actions(rows: list[dict]) -> list[dict]:
    return sorted(
        rows,
        key=lambda r: (r.get("date_issued") or "", r.get("record_id") or ""),
        reverse=True,
    )


def counts_table(row: dict, window_start: str, window_end: str, caption: str) -> str:
    total = to_int(row.get("actions_total"))
    recent = to_int(row.get("actions_last_24_months"))
    lines = []
    for t in ACTION_TYPES:
        n_all = to_int(row.get(f"count_{t}"))
        n_recent = to_int(row.get(f"last24m_{t}"))
        if n_all or n_recent:
            lines.append(
                f'<tr><th scope="row">{badge(t)}</th>'
                f"<td>{fmt_int(n_all)} of {fmt_int(total)}</td>"
                f"<td>{fmt_int(n_recent)} of {fmt_int(recent)}</td></tr>"
            )
    head = (
        '<tr><th scope="col">Category</th>'
        '<th scope="col">All published dates</th>'
        f'<th scope="col">{esc(fmt_date_short(window_start))} to '
        f"{esc(fmt_date_short(window_end))}</th></tr>"
    )
    return (
        f'<div class="table-wrap"><table class="counts"><caption>{esc(caption)}</caption>'
        f"<thead>{head}</thead><tbody>{''.join(lines)}</tbody></table></div>"
    )


# ---------------------------------------------------------------------------------------------
# Service and provider pages


def provider_display(data: Data, pr: str) -> tuple[str | None, str | None, str | None]:
    """Return (display name or None, PR key or None, withheld note or None) for a provider."""
    prov = data.providers.get(pr) if pr else None
    if not prov:
        return None, None, None
    p = pick(prov, PROVIDER_COLUMNS)
    if is_true(p["name_withheld"]) or not p["legal_name"]:
        return (
            None,
            None,
            "Provider name withheld: it may identify an individual. Its provider approval "
            "number is withheld for the same reason.",
        )
    name = p["legal_name"]
    if p["trading_name"] and p["trading_name"] != name:
        name = f"{name} (trading as {p['trading_name']})"
    return name, safe_key(p["provider_approval_number"]), None


def has_provider_page(data: Data, pr: str | None) -> bool:
    prov = data.providers.get(pr) if pr else None
    return bool(
        prov
        and to_int(prov.get("actions_total")) > 0
        and not is_true(prov.get("name_withheld"))
        and (prov.get("legal_name") or "").strip()
        and safe_key(pr)
    )


def coverage_block(row: dict) -> str:
    """The processed coverage wording: which registers can contribute, and the caveat."""
    parts = []
    if row["jurisdictions_publishing"]:
        parts.append(
            f'<p class="note">Registers that can contribute: {esc(row["jurisdictions_publishing"])}.</p>'
        )
    note = row["coverage_note"].replace(
        "see jurisdictions_publishing", "see the registers that can contribute"
    )
    if note:
        parts.append(f'<p class="note">{esc(note)}</p>')
    if not parts:
        return ""
    return '<section class="side-block"><h2>Coverage</h2>' + "".join(parts) + "</section>"


def stub_note(kind: str) -> str:
    return (
        f'<p class="stub-note">This {kind} approval is not in the ACECQA register export of the '
        "snapshot date, usually because it has ceased. Its details here come from the "
        "enforcement register that printed it.</p>"
    )


def action_jurisdictions(rows: list[dict]) -> list[str]:
    present = {r.get("jurisdiction") or "" for r in rows} - {""}
    return [j for j in JURISDICTION_ORDER if j in present] + sorted(
        present - set(JURISDICTION_ORDER)
    )


def render_service(data: Data, se: str) -> str:
    s = pick(data.services[se], SERVICE_COLUMNS)
    published = data.service_name(se)
    name = published or f"Service {se}"
    total = to_int(s["actions_total"])
    recent = to_int(s["actions_last_24_months"])
    by_name = to_int(s["actions_matched_by_name"])
    pr = s["provider_approval_number"]
    prov_name, prov_key, prov_note = provider_display(data, pr)
    actions = sort_actions(data.by_service.get(se, []))
    ws, we = fmt_date(s["window_start"]), fmt_date(s["window_end"])

    keys = [("Service approval number", f"<code>{esc(se)}</code>")]
    if not published:
        note = SERVICE_NAME_WITHHELD if se in data.withheld_service_names else "Not published."
        keys.append(("Service name", f'<span class="withheld">{esc(note)}</span>'))
    if prov_name and prov_key:
        link = (
            f'<a href="../provider/{esc(prov_key)}.html">{esc(prov_name)}</a>'
            if has_provider_page(data, prov_key)
            else esc(prov_name)
        )
        keys.append(("Approved provider", link))
        keys.append(("Provider approval number", f"<code>{esc(prov_key)}</code>"))
    elif prov_note:
        keys.append(("Approved provider", f'<span class="withheld">{esc(prov_note)}</span>'))
    else:
        keys.append(("Approved provider", "Not stated in the source."))
    keys_html = "".join(f"<div><dt>{k}</dt><dd>{v}</dd></div>" for k, v in keys)
    place = ", ".join(x for x in (s["suburb"], s["state"]) if x) or "Suburb and state not published"

    summary = (
        f'<p class="count">{fmt_int(total)} published enforcement '
        f"{'action is' if total == 1 else 'actions are'} joined to this service, "
        f"{esc(date_range(s['first_action_date'], s['last_action_date']))}. "
        f"{fmt_int(recent)} of {fmt_int(total)} {are(recent)} dated "
        f"{esc(ws)} to {esc(we)}."
    )
    if by_name:
        summary += (
            f" {fmt_int(by_name)} of {fmt_int(total)} {'rests' if by_name == 1 else 'rest'} on a "
            "name match, not a printed key."
        )
    summary += "</p>"

    chip_items = [
        (fmt_int(total), "published actions, all dates"),
        (f"{fmt_int(recent)} of {fmt_int(total)}", f"dated {esc(ws)} to {esc(we)}"),
    ]
    if s["first_action_date"]:
        chip_items.append((esc(fmt_date(s["first_action_date"])), "first dated action"))
    if s["last_action_date"]:
        chip_items.append((esc(fmt_date(s["last_action_date"])), "latest dated action"))
    jurs = action_jurisdictions(actions)
    if jurs:
        chip_items.append(
            (esc(", ".join(jurs)), "regulator publishing" if len(jurs) == 1 else "regulators")
        )
    if by_name:
        chip_items.append((f"{fmt_int(by_name)} of {fmt_int(total)}", "joined by name"))

    body = (
        '<header class="entity-head">'
        '<p class="entity-kind">Approved education and care service</p>'
        f"<h1>{esc(name)}</h1>"
        f'<p class="entity-place">{esc(place)}</p>'
        f'<dl class="keys">{keys_html}</dl>'
        + (stub_note("service") if s["spine_status"] != "current" else "")
        + chips(chip_items)
        + "</header>\n"
        + summary
        + absence_block()
        + '<div class="entity-layout"><section class="entity-main" aria-labelledby="tl-h">'
        + '<h2 id="tl-h">Actions, newest first</h2>'
        + f'<p class="note">{fmt_int(len(actions))} of {fmt_int(total)} listed. Each card shows '
        "the register's own label, with this site's category alongside.</p>"
        + timeline(actions)
        + "</section>"
        + '<aside class="entity-side">'
        + '<section class="side-block"><h2>By category</h2>'
        + counts_table(s, s["window_start"], s["window_end"], "Actions by category")
        + "</section>"
        + coverage_block(s)
        + "</aside></div>"
        + absence_block()
    )
    return page(name, body, depth=1, description=f"Published enforcement actions for {se}.")


def per_year(rows: list[dict]) -> tuple[dict[int, int], int]:
    counts: dict[int, int] = defaultdict(int)
    undated = 0
    for r in rows:
        m = re.match(r"^(\d{4})-", r.get("date_issued") or "")
        if m:
            counts[int(m.group(1))] += 1
        else:
            undated += 1
    return dict(counts), undated


def render_provider(data: Data, pr: str) -> str:
    p = pick(data.providers[pr], PROVIDER_COLUMNS)
    name, key, _ = provider_display(data, pr)
    total = to_int(p["actions_total"])
    recent = to_int(p["actions_last_24_months"])
    service_count = to_int(p["service_count"])
    with_any = to_int(p["services_with_any_action"])
    svc_level = to_int(p["service_level_actions"])
    prov_level = to_int(p["provider_level_actions"])
    by_name = to_int(p["actions_matched_by_name"])
    ws, we = fmt_date(p["window_start"]), fmt_date(p["window_end"])

    services = sorted(
        (
            pick(r, SERVICE_COLUMNS)
            for r in data.services.values()
            if r.get("provider_approval_number") == pr
            and to_int(r.get("actions_total")) > 0
            and safe_key(r.get("service_approval_number") or "")
        ),
        key=lambda r: (
            -to_int(r["actions_total"]),
            (data.service_name(r["service_approval_number"]) or "~").lower(),
            r["service_approval_number"],
        ),
    )
    provider_actions = sort_actions(data.provider_level.get(pr, []))

    lines = [
        f'<p class="count">{fmt_int(total)} published enforcement '
        f"{'action is' if total == 1 else 'actions are'} joined to this provider, "
        f"{esc(date_range(p['first_action_date'], p['last_action_date']))}: "
        f"{fmt_int(svc_level)} of {fmt_int(total)} against one of its services and "
        f"{fmt_int(prov_level)} of {fmt_int(total)} against the provider itself. "
        f"{fmt_int(recent)} of {fmt_int(total)} {are(recent)} dated "
        f"{esc(ws)} to {esc(we)}.</p>"
    ]
    counted_services = (
        p["spine_status"] == "current" and p["service_count_basis"] == "acecqa_current_register"
    )
    if counted_services:
        lines.append(
            f'<p class="count">{fmt_int(with_any)} of its {fmt_int(service_count)} services in '
            "the ACECQA register export have at least one joined action.</p>"
        )
    if by_name:
        lines.append(
            f'<p class="count">{fmt_int(by_name)} of {fmt_int(total)} '
            f"{'rests' if by_name == 1 else 'rest'} on a name match, not a printed key.</p>"
        )

    chip_items = [
        (fmt_int(total), "published actions, all dates"),
        (f"{fmt_int(recent)} of {fmt_int(total)}", f"dated {esc(ws)} to {esc(we)}"),
    ]
    if counted_services:
        chip_items.append(
            (f"{fmt_int(with_any)} of {fmt_int(service_count)}", "services with an action")
        )
    chip_items.append((f"{fmt_int(prov_level)} of {fmt_int(total)}", "against the provider itself"))
    if p["last_action_date"]:
        chip_items.append((esc(fmt_date(p["last_action_date"])), "latest dated action"))

    # One shared year axis for every sparkline on the page.
    all_rows = [a for s in services for a in data.by_service.get(s["service_approval_number"], [])]
    years_seen = sorted(per_year(all_rows)[0])
    years = list(range(years_seen[0], years_seen[-1] + 1)) if years_seen else []
    if years and len(years) < 3:
        years = list(range(years[-1] - 2, years[-1] + 1))

    rows_html = []
    for s in services:
        se = s["service_approval_number"]
        n = to_int(s["actions_total"])
        counts, undated = per_year(data.by_service.get(se, []))
        svc_name = data.service_name(se)
        name_html = (
            esc(svc_name) if svc_name else '<span class="withheld">Service name withheld</span>'
        )
        place = ", ".join(x for x in (s["suburb"], s["state"]) if x)
        rows_html.append(
            "<tr>"
            f'<th scope="row"><a href="../service/{esc(se)}.html">{name_html}</a>'
            f'<span class="row-key"><code>{esc(se)}</code></span></th>'
            f"<td>{esc(place)}</td>"
            f"<td>{fmt_int(n)} of {fmt_int(total)}</td>"
            f"<td>{time_tag(s['last_action_date']) if s['last_action_date'] else 'Not dated'}</td>"
            f'<td class="spark-cell">{sparkline(counts, years, "Actions per year at this service", undated)}</td>'
            "</tr>"
        )
    span = f"{years[0]} to {years[-1]}" if years else "no dated actions"
    services_html = (
        '<div class="table-wrap"><table class="services">'
        f"<caption>Services with at least one joined action ({fmt_int(len(services))}). "
        f"Counts are of the provider's {fmt_int(total)} actions; the bars show actions per year, "
        f"{esc(span)}.</caption>"
        '<thead><tr><th scope="col">Service</th><th scope="col">Suburb and state</th>'
        '<th scope="col">Actions</th><th scope="col">Latest action</th>'
        '<th scope="col">Per year</th></tr></thead>'
        f"<tbody>{''.join(rows_html)}</tbody></table></div>"
        if rows_html
        else "<p>None joined to a named service.</p>"
    )

    body = (
        '<header class="entity-head">'
        '<p class="entity-kind">Approved provider</p>'
        f"<h1>{esc(name)}</h1>"
        f'<dl class="keys"><div><dt>Provider approval number</dt><dd><code>{esc(key)}</code></dd>'
        "</div></dl>"
        + (stub_note("provider") if p["spine_status"] != "current" else "")
        + chips(chip_items)
        + "</header>\n"
        + "".join(lines)
        + absence_block()
        + '<div class="entity-layout"><section class="entity-main">'
        + f"<h2>Services with actions ({fmt_int(len(services))})</h2>"
        + services_html
        + f"<h2>Actions against the provider itself ({fmt_int(len(provider_actions))})</h2>"
        + (timeline(provider_actions) if provider_actions else "<p>None.</p>")
        + "</section>"
        + '<aside class="entity-side">'
        + '<section class="side-block"><h2>By category</h2>'
        + counts_table(p, p["window_start"], p["window_end"], "Actions by category")
        + "</section>"
        + coverage_block(p)
        + "</aside></div>"
        + absence_block()
    )
    return page(name or pr, body, depth=1, description=f"Published enforcement actions for {pr}.")


# ---------------------------------------------------------------------------------------------
# Home, sources and search index


def jurisdiction_stats(data: Data) -> dict[str, dict]:
    stats: dict[str, dict] = {}
    for row in data.actions_all:
        j = row.get("jurisdiction") or ""
        s = stats.setdefault(j, {"rows": 0, "dates": [], "captured": [], "nodate": 0})
        s["rows"] += 1
        if row.get("date_issued"):
            s["dates"].append(row["date_issued"])
        else:
            s["nodate"] += 1
        if row.get("captured_at"):
            s["captured"].append(row["captured_at"][:10])
    return stats


def ordered_jurisdictions(stats: dict) -> list[str]:
    return [j for j in JURISDICTION_ORDER if j in stats] + sorted(
        j for j in stats if j not in JURISDICTION_ORDER
    )


def headline(data: Data) -> dict:
    rows = data.actions_all
    overall = data.report["overall"]
    dates = sorted(r["date_issued"] for r in rows if r.get("date_issued"))
    captured = sorted(r["captured_at"][:10] for r in rows if r.get("captured_at"))
    current_services = [r for r in data.services.values() if r.get("spine_status") == "current"]
    current_providers = [r for r in data.providers.values() if r.get("spine_status") == "current"]
    return {
        "rows": len(rows),
        "regulators": len({r.get("jurisdiction") for r in rows}),
        "first": dates[0] if dates else "",
        "last": dates[-1] if dates else "",
        "nodate": sum(1 for r in rows if not r.get("date_issued")),
        "captured_first": captured[0] if captured else "",
        "captured_last": captured[-1] if captured else "",
        "uncounted": data.uncounted,
        "joined": to_int(overall.get("joined")),
        "joined_live": to_int(overall.get("joined_live_spine")),
        "joined_unlisted": to_int(overall.get("joined_by_unlisted_key")),
        "unmatched": to_int(overall.get("unmatched")),
        "rows_in": to_int(overall.get("rows_in")),
        "services_recent": sum(
            1 for r in current_services if to_int(r.get("actions_last_24_months")) > 0
        ),
        "services_total": len(current_services),
        "providers_recent": sum(
            1 for r in current_providers if to_int(r.get("actions_last_24_months")) > 0
        ),
        "providers_total": len(current_providers),
        "window_start": data.window_start,
        "window_end": data.window_end,
    }


def captured_text(first: str, last: str) -> str:
    if first == last:
        return fmt_date(first)
    return f"{fmt_date(first)} to {fmt_date(last)}"


RECENT_LIMIT = 10


def recent_actions(data: Data, service_keys: list[str]) -> list[tuple[str, dict]]:
    """The latest dated actions joined to a service that has a page, newest first."""
    pairs = [
        (se, row)
        for se in service_keys
        for row in data.by_service.get(se, [])
        if row.get("date_issued")
    ]
    pairs.sort(key=lambda p: (p[1]["date_issued"], p[1].get("record_id") or ""), reverse=True)
    return pairs[:RECENT_LIMIT]


def render_recent(data: Data, pairs: list[tuple[str, dict]]) -> str:
    items = []
    for se, raw in pairs:
        a = pick(raw, ACTION_COLUMNS)
        withheld, _ = note_segments(a["notes"])
        s = pick(data.services[se], SERVICE_COLUMNS)
        svc_name = data.service_name(se)
        name_html = esc(svc_name) if svc_name else "Service name withheld"
        place = ", ".join(x for x in (s["suburb"], s["state"]) if x)
        items.append(
            '<li class="recent-item">'
            f'<p class="recent-date">{time_tag(a["date_issued"])}</p>'
            '<div class="recent-body">'
            f'<p class="recent-what">{badge(a["action_type"])} '
            f'<span class="recent-label">{action_label_html(a, withheld)}</span></p>'
            f'<p class="recent-where"><a href="service/{esc(se)}.html">{name_html}</a>'
            f"{', ' + esc(place) if place else ''} "
            f'<span class="row-key"><code>{esc(se)}</code></span> '
            f'<span class="note">Published by {esc(a["jurisdiction"])}.</span></p>'
            "</div></li>"
        )
    return '<ol class="recent">' + "".join(items) + "</ol>"


def stat_card(number: str, of: str, label: str, basis: str) -> str:
    of_html = f' <span class="stat-of">{of}</span>' if of else ""
    return (
        '<div class="stat">'
        f'<p class="stat-number">{number}{of_html}</p>'
        f'<p class="stat-label">{label}</p>'
        f'<p class="stat-basis">{basis}</p></div>'
    )


def render_home(data: Data, h: dict, service_keys: list[str], n_providers: int) -> str:
    stats = jurisdiction_stats(data)
    jur = ordered_jurisdictions(stats)
    names = [j if j != "CTH" else "the Commonwealth" for j in jur]
    regulator_list = ", ".join(names[:-1]) + (f" and {names[-1]}" if len(names) > 1 else names[0])
    ws, we = fmt_date(h["window_start"]), fmt_date(h["window_end"])
    all_dates = f"{fmt_date(h['first'])} to {fmt_date(h['last'])}"
    captured = captured_text(h["captured_first"], h["captured_last"])
    n_services = len(service_keys)

    counts = [
        f"{fmt_int(h['rows'])} enforcement action rows published by {h['regulators']} regulators "
        f"({esc(regulator_list)}), dated between {esc(fmt_date(h['first']))} and "
        f"{esc(fmt_date(h['last']))} and captured {esc(captured)}. "
        f"{fmt_int(h['nodate'])} of {fmt_int(h['rows'])} print no parsable date. "
        f"{fmt_int(h['uncounted'])} of {fmt_int(h['rows'])} are rows a source printed twice and are "
        "not counted.",
        f"{fmt_int(h['joined'])} of {fmt_int(h['rows_in'])} rows ({percent(h['joined'], h['rows_in'])}) "
        f"are joined to an approved service or provider: {fmt_int(h['joined_live'])} of "
        f"{fmt_int(h['rows_in'])} to an approval in the current ACECQA register export and "
        f"{fmt_int(h['joined_unlisted'])} of {fmt_int(h['rows_in'])} to an approval no longer in "
        f"it. The other {fmt_int(h['unmatched'])} of {fmt_int(h['rows_in'])} each carry a stated "
        "reason (see Sources and methods).",
        f"{fmt_int(h['services_recent'])} of {fmt_int(h['services_total'])} services in the "
        f"ACECQA register export have at least one joined action dated {esc(ws)} to {esc(we)}. "
        "Only states whose registers are collected can contribute, and coverage windows differ.",
        f"{fmt_int(h['providers_recent'])} of {fmt_int(h['providers_total'])} approved providers in "
        f"the ACECQA register export have at least one joined action dated {esc(ws)} to {esc(we)}.",
    ]
    counts_html = "".join(f'<li class="count">{c}</li>' for c in counts)

    cards = "".join(
        [
            stat_card(
                fmt_int(h["rows"]),
                "",
                f"enforcement action rows published by {h['regulators']} regulators",
                f"All published dates, {esc(all_dates)}. Captured {esc(captured)}.",
            ),
            stat_card(
                fmt_int(h["joined"]),
                f"of {fmt_int(h['rows_in'])}",
                "rows joined to an approved service or provider",
                f"{esc(percent(h['joined'], h['rows_in']))}. All published dates.",
            ),
            stat_card(
                fmt_int(h["services_recent"]),
                f"of {fmt_int(h['services_total'])}",
                "services in the ACECQA register export with a joined action",
                f"Actions dated {esc(ws)} to {esc(we)}.",
            ),
            stat_card(
                fmt_int(h["providers_recent"]),
                f"of {fmt_int(h['providers_total'])}",
                "approved providers in the ACECQA register export with a joined action",
                f"Actions dated {esc(ws)} to {esc(we)}.",
            ),
        ]
    )

    by_jur = sorted(
        ((JURISDICTION_NAMES.get(j, j), stats[j]["rows"], "bar-primary") for j in jur),
        key=lambda item: -item[1],
    )
    jur_chart = bar_chart(
        "chart-jurisdiction",
        "Rows by publishing regulator",
        f"Enforcement action rows each regulator publishes, of {fmt_int(h['rows'])} rows in all. "
        f"All published dates, {all_dates}. Coverage windows differ by regulator, so the bars "
        "compare what is published, not how often actions happen.",
        by_jur,
        h["rows"],
    )
    type_counts: dict[str, int] = defaultdict(int)
    for row in data.actions_all:
        type_counts[category(row.get("action_type") or "")] += 1
    by_type = sorted(
        ((TYPE_LABELS[t], n, f"cat-{t}") for t, n in type_counts.items() if n),
        key=lambda item: -item[1],
    )
    type_chart = bar_chart(
        "chart-category",
        "Rows by action category",
        f"Enforcement action rows in each of this site's categories, of {fmt_int(h['rows'])} rows "
        f"in all. All published dates, {all_dates}. A category describes the step a regulator "
        "took; it is not a finding of guilt.",
        by_type,
        h["rows"],
    )

    recent = recent_actions(data, service_keys)
    body = f"""<section class="hero" aria-labelledby="hero-title">
<h1 id="hero-title">Childcare enforcement actions, joined across regulators</h1>
<p class="lede">Australian education and care regulators each publish their own enforcement
registers. This prototype gathers them in one place and links each action, where the source
allows, to the approved service or provider it concerns.</p>
<p class="lede-note">Every entry links to the regulator's own published record. An enforcement
action is a step a regulator took; it is not a finding of guilt and not a conviction.</p>
<div class="search" id="search" role="search">
<label for="q">Search services and providers</label>
<div class="search-field"><svg class="search-icon" width="22" height="22" viewBox="0 0 22 22" aria-hidden="true" focusable="false"><circle cx="9.5" cy="9.5" r="6.5" class="icon-stroke"/><rect x="14.2" y="15.6" width="7" height="2.4" rx="1.2" transform="rotate(45 14.2 15.6)" class="icon-glyph"/></svg>
<input id="q" type="search" autocomplete="off" spellcheck="false" placeholder="Name, suburb, postcode or approval number" aria-describedby="search-help" aria-controls="results"></div>
<p id="search-help" class="note">Searches {fmt_int(n_services)} services and {fmt_int(n_providers)} providers that have at least one joined action, by name, suburb, postcode or SE- or PR- approval number. Names withheld as possible individuals are not searchable.</p>
<p id="status" role="status" aria-live="polite"></p>
<ul id="results" class="results"></ul>
<noscript><p>Search needs JavaScript. The sources and methods page explains what is here.</p></noscript>
</div>
</section>
{absence_block()}
<section class="section" aria-labelledby="stats-heading">
<h2 id="stats-heading">The data at a glance</h2>
<div class="stat-grid">{cards}</div>
</section>
<section class="section" aria-labelledby="charts-heading">
<h2 id="charts-heading">Where the rows come from</h2>
<div class="chart-grid">{jur_chart}{type_chart}</div>
</section>
<section class="section" aria-labelledby="recent-heading">
<h2 id="recent-heading">Most recent actions</h2>
<p class="note">The {fmt_int(len(recent))} latest dated actions joined to a service, newest first. Each links to the service's page.</p>
{render_recent(data, recent)}
</section>
<section class="section notes" aria-labelledby="counts-heading">
<h2 id="counts-heading">Reading these figures</h2>
<ul class="headline">{counts_html}</ul>
</section>
<script src="assets/search.js"></script>"""
    return page(
        "Home",
        body,
        depth=0,
        description="Private prototype. Not for publication.",
        current="index.html#search",
    )


def render_sources(data: Data, h: dict, withheld_providers: int, withheld_services: int) -> str:
    stats = jurisdiction_stats(data)
    report = data.report
    per = report.get("per_jurisdiction", {})
    coverage = report.get("coverage", {})
    reg_sections = []
    overview_rows = []
    for j in ordered_jurisdictions(stats):
        s = stats[j]
        reg = REGULATORS.get(
            j, {"name": j, "published": "Not described.", "licence": "Not confirmed."}
        )
        dates = sorted(s["dates"])
        caps = sorted(s["captured"])
        pj = per.get(j, {})
        rows_in = to_int(pj.get("rows_in")) or s["rows"]
        unmatched = to_int(pj.get("unmatched"))
        window = (
            f"Rows dated {fmt_date(dates[0])} to {fmt_date(dates[-1])}"
            if dates
            else "No parsable dates"
        )
        if s["nodate"]:
            window += (
                f"; {fmt_int(s['nodate'])} of {fmt_int(s['rows'])} "
                f"{'prints' if s['nodate'] == 1 else 'print'} no parsable date"
            )
        span = f"{time_tag(dates[0])} to {time_tag(dates[-1])}" if dates else "No parsable dates"
        overview_rows.append(
            f'<tr><th scope="row"><a href="#reg-{esc(j.lower())}">{esc(reg["name"])}</a> '
            f'<span class="row-key">{esc(j)}</span></th>'
            f"<td>{fmt_int(s['rows'])} of {fmt_int(h['rows'])}</td>"
            f"<td>{fmt_int(rows_in - unmatched)} of {fmt_int(rows_in)}</td>"
            f"<td>{span}</td></tr>"
        )
        reg_sections.append(
            f'<section class="reg-card" id="reg-{esc(j.lower())}" aria-labelledby="reg-{esc(j.lower())}-h">'
            f'<h3 id="reg-{esc(j.lower())}-h">{esc(reg["name"])} <span class="row-key">{esc(j)}</span></h3>'
            '<dl class="reg-facts">'
            f"<div><dt>What is published</dt><dd>{esc(reg['published'])}</dd></div>"
            f"<div><dt>Coverage as collected</dt><dd>{esc(coverage.get(j, 'Not stated.'))}</dd></div>"
            f"<div><dt>Licence</dt><dd>{esc(reg['licence'])}</dd></div>"
            f"<div><dt>Window</dt><dd>{esc(window)}.</dd></div>"
            f"<div><dt>Captured</dt><dd>{esc(captured_text(caps[0], caps[-1]) if caps else 'Not stated')} (UTC).</dd></div>"
            f"<div><dt>Rows and joins</dt><dd>{fmt_int(s['rows'])} {'row' if s['rows'] == 1 else 'rows'}; "
            f"{fmt_int(rows_in - unmatched)} of "
            f"{fmt_int(rows_in)} joined; {fmt_int(unmatched)} of {fmt_int(rows_in)} unmatched.</dd></div>"
            "</dl></section>"
        )
    overview = (
        '<div class="table-wrap"><table class="counts overview">'
        "<caption>Regulators at a glance</caption>"
        '<thead><tr><th scope="col">Regulator</th><th scope="col">Rows of all rows</th>'
        '<th scope="col">Joined of its rows</th><th scope="col">Dates published</th></tr></thead>'
        f"<tbody>{''.join(overview_rows)}</tbody></table></div>"
    )

    residual = report["overall"].get("unmatched_residual", {})
    residual_items = "".join(
        f"<li>{fmt_int(to_int(v))} of {fmt_int(h['unmatched'])}: {esc(RESIDUAL_LABELS.get(k, k))}</li>"
        for k, v in residual.items()
    )
    per_residual = "".join(
        f'<tr><th scope="row">{esc(j)}</th><td>{fmt_int(to_int(per[j].get("unmatched")))} of '
        f"{fmt_int(to_int(per[j].get('rows_in')))}</td>"
        + "".join(
            f"<td>{fmt_int(to_int(per[j].get('unmatched_residual', {}).get(k)))}</td>"
            for k in RESIDUAL_LABELS
        )
        + "</tr>"
        for j in ordered_jurisdictions(per)
    )
    residual_head = "".join(
        f'<th scope="col">{esc(k.replace("_", " ").capitalize())}</th>' for k in RESIDUAL_LABELS
    )
    definitions = "".join(
        f"<div><dt>{badge(t)}</dt><dd>{esc(TYPE_DEFINITIONS[t])}</dd></div>" for t in ACTION_TYPES
    )
    ws, we = fmt_date(h["window_start"]), fmt_date(h["window_end"])
    h_services = sum(1 for r in data.services.values() if to_int(r.get("actions_total")) > 0)
    toc = "".join(
        f'<li><a href="#{a}">{esc(t)}</a></li>'
        for a, t in (
            ("regulators", "Regulators"),
            ("joins", "How joins work"),
            ("withholding", "How names are withheld"),
            ("categories", "What the categories mean"),
            ("windows", "Counts and windows"),
            ("licences", "Licences"),
            ("limitations", "Known limitations"),
        )
    )

    body = f"""<header class="page-head">
<h1>Sources and methods</h1>
<p class="lede">Where every row comes from, how rows are joined to services and providers, what is
withheld and why, and what the categories mean.</p>
</header>
{absence_block()}
<div class="doc-layout">
<nav class="toc" aria-label="On this page"><p class="toc-title">On this page</p><ol>{toc}</ol></nav>
<div class="doc">
<section id="regulators" aria-labelledby="regulators-h">
<h2 id="regulators-h">Regulators</h2>
<p>Each figure below is counted from the processed data this site was built from. Text quoted
from a register is reproduced as printed, including its punctuation.</p>
{overview}
<div class="reg-grid">{"".join(reg_sections)}</div>
<p>The Northern Territory publishes no enforcement register and the ACT has no register, so
neither contributes rows.</p>
</section>

<section id="joins" aria-labelledby="joins-h">
<h2 id="joins-h">How joins work</h2>
<p>Each action is joined to the national register of approved services and providers kept by
ACECQA, using the export captured for the snapshot date {esc(we)}. The join tries, in order:
the service or provider approval number printed in the register; then, where no number is
printed, a name that exactly one approved service or provider has; then, for Commonwealth rows,
a printed ABN resolved to one provider's name. A name match is weaker evidence than a printed
number, and each page says which basis applies.</p>
<p>Where a printed approval number is not in the current ACECQA export, usually because the
approval has ceased, the action joins to a stub built from the enforcement register. Stubs are
kept out of the counts of current services and providers.</p>
<p>{fmt_int(h["joined"])} of {fmt_int(h["rows_in"])} rows are joined ({fmt_int(h["joined_live"])}
to the current export and {fmt_int(h["joined_unlisted"])} to stubs). {fmt_int(h["unmatched"])} of
{fmt_int(h["rows_in"])} are unmatched, each for one stated reason:</p>
<ul>{residual_items}</ul>
<div class="table-wrap"><table class="counts"><caption>Unmatched rows by regulator and reason</caption>
<thead><tr><th scope="col">Regulator</th><th scope="col">Unmatched of rows</th>{residual_head}</tr></thead>
<tbody>{per_residual}</tbody></table></div>
<p>Unmatched rows are not shown on any service or provider page. The aim is that every row is
joined or explained; a full match rate is not the goal, because reaching it would mean guessing.</p>
</section>

<section id="withholding" aria-labelledby="withholding-h">
<h2 id="withholding-h">How names are withheld</h2>
<p>This site never names individuals. The parsers withhold a provider name, service name, free
text, street address, ABN or source address when it is classed as, or cannot be confirmed not to
be, a person's name. A withheld value shows its note, never a guess. This is a keyword heuristic,
not a guarantee: it can miss a name, and it often withholds an organisation's name.</p>
<p>Where a provider's name is withheld, this site also withholds its provider approval number and
builds no provider page, because the number leads straight to the name. {fmt_int(withheld_providers)}
providers with at least one action are treated this way.</p>
<p>A service's name is withheld too when its provider's name is withheld, or when any action
joined to it notes that the subject is, or may be, an individual, because a service name can
contain the provider's own name. {fmt_int(withheld_services)} of the {fmt_int(h_services)}
services with a page are shown by approval number, suburb and state only. Street addresses are
not shown anywhere.</p>
</section>

<section id="categories" aria-labelledby="categories-h">
<h2 id="categories-h">What the categories mean</h2>
<p>These are plain-language summaries of this project's categories. The law and each register's
own text govern, and every action also shows the register's own label. Category colours only
help tell categories apart; they do not rank them.</p>
<dl class="definitions">{definitions}</dl>
<div class="distinction">
<p>Several different things must not be confused. A <strong>breach</strong> is a contravention of
the law, whether alleged or found. A <strong>confirmed breach</strong> is one a regulator has
confirmed. An <strong>enforcement action</strong> is a step a regulator took, such as a notice, a
condition or a cancellation. A <strong>prosecution</strong> is a proceeding brought in a court or
tribunal. A <strong>conviction</strong> is a court's finding of guilt. This site counts published
enforcement actions only. It does not count breaches or convictions.</p>
</div>
</section>

<section id="windows" aria-labelledby="windows-h">
<h2 id="windows-h">Counts and windows</h2>
<p>Every count is given with its denominator and its window. Two windows are used: all dates the
collected registers publish, which differ by regulator (see above); and the 24 months
{esc(ws)} to {esc(we)}, ending on the ACECQA snapshot date. Rows a source printed twice are listed
once and counted once.</p>
</section>

<section id="licences" aria-labelledby="licences-h">
<h2 id="licences-h">Licences</h2>
<ul>
<li>NSW and Victorian content is licensed under CC BY 4.0.</li>
<li>South Australian (Education Standards Board) content is all rights reserved. It is used here
for non-commercial research only.</li>
<li>Western Australian content is for personal and non-commercial use only.</li>
<li>Queensland, Tasmanian and Commonwealth licences are not confirmed (see above).</li>
<li>ACECQA content is not openly licensed. A request for written consent was sent to ACECQA on
30 October 2026 and no reply has been received. <strong>No ACECQA quality ratings are shown on this
site</strong> while consent is pending. ACECQA data is used only to join actions to services and
providers, and for service and provider names, suburbs, states and service counts.</li>
</ul>
</section>

<section id="limitations" aria-labelledby="limitations-h">
<h2 id="limitations-h">Known limitations</h2>
<ul>
<li>Coverage differs by regulator: NSW from January 2025, Victoria from January 2026, Queensland
entries can be removed at the regulator's discretion, the Commonwealth register is a rolling
period plus past registers, and Western Australia lists finalised actions only.</li>
<li>Queensland and Commonwealth registers print no approval numbers, so most of their rows join by
name or not at all.</li>
<li>South Australian pages before 2022 print no approval numbers.</li>
<li>Name matching and name withholding are heuristics. Both can be wrong.</li>
<li>Some Western Australian name fields carry address text or key fragments.</li>
<li>Two NSW rows print malformed approval numbers. A re-issued NSW PDF could be counted twice.</li>
<li>The data is a snapshot captured on the dates shown, not a live feed.</li>
<li>Nothing on this site has had legal review.</li>
</ul>
</section>
</div>
</div>
{absence_block()}"""
    return page("Sources and methods", body, depth=0, current="sources.html")


def search_index(data: Data, service_keys: list[str], provider_keys: list[str]) -> list[list]:
    """Compact rows: [kind, name, suburb, postcode, state, key, provider name, provider key, url,
    actions total]."""
    out: list[list] = []
    for se in service_keys:
        s = pick(data.services[se], INDEX_SERVICE_COLUMNS)
        prov_name, prov_key, _ = provider_display(
            data, data.services[se].get("provider_approval_number") or ""
        )
        out.append(
            [
                "s",
                data.service_name(se) or "Service name withheld",
                s["suburb"],
                s["postcode"],
                s["state"],
                se,
                prov_name or "",
                prov_key or "",
                f"service/{se}.html",
                to_int(data.services[se].get("actions_total")),
            ]
        )
    for pr in provider_keys:
        name, key, _ = provider_display(data, pr)
        out.append(
            [
                "p",
                name or "",
                "",
                "",
                "",
                key or "",
                "",
                "",
                f"provider/{pr}.html",
                to_int(data.providers[pr].get("actions_total")),
            ]
        )
    return out


# ---------------------------------------------------------------------------------------------
# Build


def build(data_dir: Path, out: Path) -> dict:
    data = Data(data_dir)
    problems = data.check()
    if problems:
        raise SystemExit(
            "Listed actions do not match the processed totals:\n  " + "\n  ".join(problems[:20])
        )

    service_keys = sorted(
        se for se, r in data.services.items() if to_int(r.get("actions_total")) > 0 and safe_key(se)
    )
    provider_keys = sorted(pr for pr in data.providers if has_provider_page(data, pr))
    withheld_providers = sum(
        1
        for r in data.providers.values()
        if to_int(r.get("actions_total")) > 0
        and not has_provider_page(data, r.get("provider_approval_number"))
    )

    if out.exists():
        shutil.rmtree(out)
    (out / "service").mkdir(parents=True)
    (out / "provider").mkdir(parents=True)
    (out / "assets").mkdir(parents=True)

    def write(rel: str, text: str) -> None:
        (out / rel).write_text(text, encoding="utf-8", newline="\n")

    h = headline(data)
    for se in service_keys:
        write(f"service/{se}.html", render_service(data, se))
    for pr in provider_keys:
        write(f"provider/{pr}.html", render_provider(data, pr))
    write("index.html", render_home(data, h, service_keys, len(provider_keys)))
    withheld_services = sum(1 for se in service_keys if data.service_name(se) is None)
    write("sources.html", render_sources(data, h, withheld_providers, withheld_services))
    write(
        "404.html",
        page(
            "Not found",
            '<header class="page-head"><h1>Not found</h1><p class="lede">No page at this '
            'address. Try the <a href="/index.html#search">search</a>.</p></header>'
            f"{absence_block()}",
            base="/",
        ),
    )
    write("robots.txt", ROBOTS_TXT)
    write("assets/favicon.svg", FAVICON_SVG)
    write(
        "assets/search-index.json",
        json.dumps(
            search_index(data, service_keys, provider_keys),
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    )
    for name in ("site.css", "search.js"):
        shutil.copyfile(STATIC / name, out / "assets" / name)
    shutil.copyfile(HERE / "vercel.json", out / "vercel.json")

    files = [p for p in out.rglob("*") if p.is_file()]
    return {
        "service_pages": len(service_keys),
        "provider_pages": len(provider_keys),
        "other_pages": 3,
        "withheld_providers_without_page": withheld_providers,
        "service_pages_with_name_withheld": withheld_services,
        "files": len(files),
        "bytes": sum(p.stat().st_size for p in files),
        "headline": h,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=HERE / "dist")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    args = parser.parse_args(argv)
    summary = build(args.data, args.out)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
