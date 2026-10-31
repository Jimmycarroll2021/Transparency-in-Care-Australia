"""Tests for site/build_site.py on a small synthetic fixture.

The fixture puts a unique sentinel in every column the site must not render, so a test can prove
that only allowlisted columns reach the pages.
"""

from __future__ import annotations

import csv
import importlib.util
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("tica_build_site", ROOT / "site" / "build_site.py")
bs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bs)

ACTION_HEADER = [
    "record_id", "occurrence", "jurisdiction", "source_register", "source_document",
    "source_snapshot", "captured_at", "service_approval_number", "service_approval_number_raw",
    "provider_approval_number", "provider_approval_number_raw", "service_name", "provider_name",
    "address", "suburb", "state", "postcode", "action_type", "action_type_raw", "reason",
    "legal_references", "date_issued", "date_issued_raw", "period_label", "notes",
    "linked_documents", "service_type", "start_date", "end_date", "date_charged",
    "date_of_sentence", "plea", "penalty_amount_aud", "abn", "join_key_kind", "match_confidence",
    "join_note", "acecqa_service_approval_number", "acecqa_service_name",
    "acecqa_provider_approval_number", "acecqa_provider_legal_name", "acecqa_state",
    "acecqa_service_type", "acecqa_overall_rating", "acecqa_rating_issued",
    "provider_entity_form", "provider_service_count", "counted_in_totals", "spine_status",
]  # fmt: skip

TYPES = bs.ACTION_TYPES
COUNTS = [f"count_{t}" for t in TYPES]
LAST24 = [f"last24m_{t}" for t in TYPES]

SERVICE_HEADER = [
    "service_approval_number", "provider_approval_number", "service_name", "suburb", "state",
    "postcode", "service_type", "acecqa_overall_rating", "acecqa_rating_issued", "window_start",
    "window_end", "actions_total", *COUNTS, "actions_last_24_months", *LAST24,
    "first_action_date", "last_action_date", "actions_matched_by_name",
    "jurisdictions_publishing", "coverage_note", "spine_status",
]  # fmt: skip

PROVIDER_HEADER = [
    "provider_approval_number", "legal_name", "trading_name", "name_withheld", "entity_form",
    "provider_state", "states_operated_in", "service_count", "services_with_any_action",
    "services_with_any_action_last_24_months", "service_level_actions", "provider_level_actions",
    "actions_matched_by_name", "window_start", "window_end", "actions_total", *COUNTS,
    "actions_last_24_months", *LAST24, "first_action_date", "last_action_date",
    "actions_last_24_months_per_service", "jurisdictions_publishing", "coverage_note",
    "spine_status", "service_count_basis",
]  # fmt: skip

RATING = "RATINGSENTINEL Exceeding NQS"
WITHHELD_PERSON = "Jane Citizen"
SCRIPT = "<script>alert(1)</script>"
NSW_URL = "https://education.nsw.gov.au/register/q1.pdf"


def sentinel(column: str) -> str:
    return f"SENTINEL_{column.upper()}"


def action(**values) -> dict:
    """An action row: every excluded column holds its sentinel unless overridden."""
    row = {c: sentinel(c) for c in ACTION_HEADER}
    row.update(
        source_register="https://example.gov.au/register",
        captured_at="2026-10-29T07:18:22+00:00",
        reason="",
        notes="",
        period_label="2025-26 Q1",
        penalty_amount_aud="",
        acecqa_overall_rating=RATING,
        acecqa_rating_issued=RATING,
        counted_in_totals="True",
        spine_status="current",
    )
    row.update(values)
    return row


def tally(types_all: dict, types_recent: dict) -> dict:
    out = {f"count_{t}": str(types_all.get(t, 0)) for t in TYPES}
    out.update({f"last24m_{t}": str(types_recent.get(t, 0)) for t in TYPES})
    out["actions_total"] = str(sum(types_all.values()))
    out["actions_last_24_months"] = str(sum(types_recent.values()))
    return out


def service(se, pr, name, all_, recent, first="", last="", by_name=0, **extra) -> dict:
    row = {c: sentinel(c) for c in SERVICE_HEADER}
    row.update(
        service_approval_number=se,
        provider_approval_number=pr,
        service_name=name,
        suburb="TESTVILLE",
        state="NSW",
        postcode="2000",
        acecqa_overall_rating=RATING,
        acecqa_rating_issued=RATING,
        window_start="2024-10-29",
        window_end="2026-10-28",
        first_action_date=first,
        last_action_date=last,
        actions_matched_by_name=str(by_name),
        jurisdictions_publishing="NSW register: Jan 2025 onward (quarterly PDFs)",
        coverage_note="Absence of an action is not evidence of safety.",
        spine_status="current",
        **tally(all_, recent),
    )
    row.update(extra)
    return row


def provider(pr, legal, withheld, all_, recent, svc_level, prov_level, **extra) -> dict:
    row = {c: sentinel(c) for c in PROVIDER_HEADER}
    row.update(
        provider_approval_number=pr,
        legal_name=legal,
        trading_name="",
        name_withheld="true" if withheld else "false",
        service_count="3",
        services_with_any_action="1",
        service_level_actions=str(svc_level),
        provider_level_actions=str(prov_level),
        actions_matched_by_name="1",
        window_start="2024-10-29",
        window_end="2026-10-28",
        first_action_date="2025-07-04",
        last_action_date="2026-02-27",
        jurisdictions_publishing="NSW register: Jan 2025 onward (quarterly PDFs)",
        coverage_note="Coverage differs by state: see jurisdictions_publishing.",
        spine_status="current",
        service_count_basis="acecqa_current_register",
        **tally(all_, recent),
    )
    row.update(extra)
    return row


def write_csv(path: Path, header: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=header)
        writer.writeheader()
        writer.writerows(rows)


def make_fixture(data: Path) -> None:
    data.mkdir(parents=True, exist_ok=True)
    actions = [
        # Keyed NSW compliance notice on SE-00000001.
        action(
            record_id="a1",
            jurisdiction="NSW",
            source_document=NSW_URL,
            action_type="compliance_notice",
            action_type_raw="Compliance notice issued",
            reason=f"Reason text {SCRIPT} as printed",
            date_issued="2025-07-04",
            notes="outcome printed: SENTINEL_OUTCOME",
            join_key_kind="service",
            match_confidence="exact_key",
            acecqa_service_approval_number="SE-00000001",
            acecqa_provider_approval_number="PR-00000001",
        ),
        # Name-matched QLD prosecution with a fine on SE-00000001.
        action(
            record_id="a2",
            jurisdiction="QLD",
            source_document="https://earlychildhood.qld.gov.au/doc.pdf",
            action_type="prosecution",
            action_type_raw="Prosecution",
            reason="Approved provider fined $12,000",
            date_issued="2026-02-27",
            penalty_amount_aud="12000",
            join_key_kind="name_match",
            match_confidence="name_only",
            acecqa_service_approval_number="SE-00000001",
            acecqa_provider_approval_number="PR-00000001",
        ),
        # Duplicate row printed twice in the source: listed nowhere, not counted.
        action(
            record_id="a3",
            jurisdiction="NSW",
            source_document=NSW_URL,
            action_type="compliance_notice",
            action_type_raw="Compliance notice issued",
            date_issued="2025-07-04",
            notes="duplicate row in source",
            join_key_kind="service",
            match_confidence="exact_key",
            acecqa_service_approval_number="SE-00000001",
            acecqa_provider_approval_number="PR-00000001",
            counted_in_totals="False",
        ),
        # Provider-level action against PR-00000001.
        action(
            record_id="a4",
            jurisdiction="NSW",
            source_document=NSW_URL,
            action_type="enforceable_undertaking",
            action_type_raw="Enforceable undertaking accepted",
            date_issued="2025-09-01",
            join_key_kind="provider",
            match_confidence="exact_key",
            acecqa_service_approval_number="",
            acecqa_provider_approval_number="PR-00000001",
        ),
        # WA action whose subject is an individual, on SE-00000002 (provider name withheld).
        action(
            record_id="a5",
            jurisdiction="WA",
            source_document="https://www.wa.gov.au/register",
            action_type="compliance_notice",
            action_type_raw="(withheld)",
            date_issued="2025-11-11",
            notes="subject is an individual; name withheld; free text withheld: subject may be an individual",
            join_key_kind="service",
            match_confidence="exact_key",
            acecqa_service_approval_number="SE-00000002",
            acecqa_provider_approval_number="PR-00000002",
        ),
        # Unmatched CTH row.
        action(
            record_id="a6",
            jurisdiction="CTH",
            source_document="https://www.education.gov.au/register",
            action_type="ccs_sanction",
            action_type_raw="Sanction under section 197L",
            date_issued="",
            join_key_kind="none",
            match_confidence="unmatched",
            acecqa_service_approval_number="",
            acecqa_provider_approval_number="",
            spine_status="",
        ),
    ]
    write_csv(data / "enforcement-actions-all.csv", ACTION_HEADER, actions)

    services = [
        service(
            "SE-00000001",
            "PR-00000001",
            "Little <b>Stars</b> & Co",
            {"compliance_notice": 1, "prosecution": 1},
            {"compliance_notice": 1, "prosecution": 1},
            first="2025-07-04",
            last="2026-02-27",
            by_name=1,
        ),
        service(
            "SE-00000002",
            "PR-00000002",
            f"{WITHHELD_PERSON} Family Day Care",
            {"compliance_notice": 1},
            {"compliance_notice": 1},
            first="2025-11-11",
            last="2025-11-11",
        ),
        service("SE-00000003", "PR-00000001", "Quiet Service", {}, {}),
    ]
    write_csv(data / "enforcement-by-service.csv", SERVICE_HEADER, services)

    providers = [
        provider(
            "PR-00000001",
            "Acme Care Pty Ltd",
            False,
            {"compliance_notice": 1, "prosecution": 1, "enforceable_undertaking": 1},
            {"compliance_notice": 1, "prosecution": 1, "enforceable_undertaking": 1},
            2,
            1,
        ),
        provider("PR-00000002", "", True, {"compliance_notice": 1}, {"compliance_notice": 1}, 1, 0),
    ]
    write_csv(data / "enforcement-by-provider.csv", PROVIDER_HEADER, providers)

    report = {
        "window": {"months": 24, "start": "2024-10-29", "end": "2026-10-28"},
        "coverage": {"NSW": "NSW register: Jan 2025 onward (quarterly PDFs)"},
        "overall": {
            "rows_in": 6,
            "joined": 5,
            "joined_live_spine": 5,
            "joined_by_unlisted_key": 0,
            "unmatched": 1,
            "unmatched_residual": {
                "no_key_and_name_withheld": 0,
                "no_key_no_name_match": 1,
                "ambiguous_name": 0,
                "other": 0,
            },
        },
        "per_jurisdiction": {
            "CTH": {
                "rows_in": 1,
                "unmatched": 1,
                "unmatched_residual": {"no_key_no_name_match": 1},
            },
            "NSW": {"rows_in": 3, "unmatched": 0, "unmatched_residual": {}},
            "QLD": {"rows_in": 1, "unmatched": 0, "unmatched_residual": {}},
            "WA": {"rows_in": 1, "unmatched": 0, "unmatched_residual": {}},
        },
    }
    (data / "enforcement-join-report.json").write_text(json.dumps(report), encoding="utf-8")


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    base = tmp_path_factory.mktemp("site")
    make_fixture(base / "data")
    summary = bs.build(base / "data", base / "dist")
    pages = {p.relative_to(base / "dist").as_posix(): p.read_text(encoding="utf-8")
             for p in (base / "dist").rglob("*") if p.is_file()}  # fmt: skip
    return summary, pages


def html_pages(pages: dict) -> dict:
    return {k: v for k, v in pages.items() if k.endswith(".html")}


def test_build_succeeds_and_counts_pages(built):
    summary, pages = built
    assert summary["service_pages"] == 2  # SE-00000003 has no action and gets no page
    assert summary["provider_pages"] == 1  # PR-00000002's name is withheld
    assert "service/SE-00000001.html" in pages
    assert "service/SE-00000002.html" in pages
    assert "service/SE-00000003.html" not in pages
    assert "provider/PR-00000001.html" in pages
    assert "provider/PR-00000002.html" not in pages
    for name in ("index.html", "sources.html", "robots.txt", "vercel.json"):
        assert name in pages


def test_every_page_has_banner_and_noindex(built):
    _, pages = built
    for name, text in html_pages(pages).items():
        assert bs.BANNER in text, name
        assert '<meta name="robots" content="noindex,nofollow">' in text, name


def test_robots_txt_disallows_everything(built):
    _, pages = built
    assert "User-agent: *" in pages["robots.txt"]
    assert "Disallow: /" in pages["robots.txt"]


def test_vercel_headers(built):
    _, pages = built
    config = json.loads(pages["vercel.json"])
    headers = {h["key"]: h["value"] for rule in config["headers"] for h in rule["headers"]}
    assert headers["X-Robots-Tag"] == "noindex, nofollow"
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["Referrer-Policy"] == "no-referrer"
    csp = headers["Content-Security-Policy"]
    assert "default-src 'self'" in csp
    assert "unsafe-inline" not in csp and "unsafe-eval" not in csp
    assert "http" not in csp


def test_no_rating_appears(built):
    _, pages = built
    for name, text in pages.items():
        assert "RATINGSENTINEL" not in text, name
        assert "Exceeding NQS" not in text, name
        assert "acecqa_overall_rating" not in text, name


def test_only_allowlisted_columns_are_rendered(built):
    _, pages = built
    for name, text in pages.items():
        found = re.findall(r"SENTINEL_[A-Z0-9_]+", text)
        assert not found, f"{name} renders non-allowlisted columns: {sorted(set(found))}"


def test_every_input_column_is_allowlisted_or_excluded():
    lists = {
        "actions": (ACTION_HEADER, bs.ACTION_COLUMNS),
        "services": (SERVICE_HEADER, bs.SERVICE_COLUMNS),
        "providers": (PROVIDER_HEADER, bs.PROVIDER_COLUMNS),
    }
    for kind, (header, allow) in lists.items():
        for column in header:
            assert column in allow or column in bs.EXCLUDED[kind], (kind, column)
        for column in allow:
            assert "rating" not in column.lower()


def test_real_headers_are_covered():
    """The committed processed files carry no column the site has not classified."""
    data = ROOT / "data" / "processed"
    files = {
        "actions": ("enforcement-actions-all.csv", bs.ACTION_COLUMNS),
        "services": ("enforcement-by-service.csv", bs.SERVICE_COLUMNS),
        "providers": ("enforcement-by-provider.csv", bs.PROVIDER_COLUMNS),
    }
    for kind, (name, allow) in files.items():
        path = data / name
        if not path.exists():
            pytest.skip(f"{name} not present")
        with path.open(encoding="utf-8", newline="") as fh:
            header = next(csv.reader(fh))
        unclassified = [c for c in header if c not in allow and c not in bs.EXCLUDED[kind]]
        assert not unclassified, (kind, unclassified)


def test_html_is_escaped(built):
    _, pages = built
    svc = pages["service/SE-00000001.html"]
    assert SCRIPT not in svc
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in svc
    assert "Little &lt;b&gt;Stars&lt;/b&gt; &amp; Co" in svc
    assert "<b>Stars</b>" not in svc


def test_absence_statement_present(built):
    _, pages = built
    for name, text in html_pages(pages).items():
        if name.startswith(("service/", "provider/")) or name in ("index.html", "sources.html"):
            assert bs.ABSENCE in text, name


def test_counts_carry_a_denominator(built):
    _, pages = built
    seen = 0
    for name, text in html_pages(pages).items():
        for m in re.finditer(r'class="count">(.*?)</(?:p|li)>', text, re.S):
            seen += 1
            assert re.search(r"\d of (?:its )?[\d,]+", m.group(1)), (name, m.group(1))
        for cell in re.findall(r"<td>([^<]*)</td>", text):
            if re.fullmatch(r"[\d,]+", cell.strip()):
                continue  # residual breakdown cells sit under an 'Unmatched of rows' column
            assert " of " in cell or not re.search(r"\d", cell), (name, cell)
    assert seen >= 6


def test_headline_counts(built):
    _, pages = built
    home = pages["index.html"]
    assert "6 enforcement action rows published by 4 regulators" in home
    assert "5 of 6 rows" in home
    assert "1 of 6 are rows a source printed twice" in home
    assert "2 of 3 services in the ACECQA register export" in home
    assert "29 October 2024 to 28 October 2026" in home


def test_withheld_values_show_their_note(built):
    _, pages = built
    svc = pages["service/SE-00000002.html"]
    assert WITHHELD_PERSON not in svc
    assert "Service name withheld" in svc
    assert "Provider name withheld" in svc
    assert "PR-00000002" not in svc
    assert "Withheld: subject is an individual" in svc
    index = pages["assets/search-index.json"]
    assert WITHHELD_PERSON not in index
    assert "PR-00000002" not in index
    for text in pages.values():
        assert WITHHELD_PERSON not in text


def test_service_page_lists_actions(built):
    _, pages = built
    svc = pages["service/SE-00000001.html"]
    assert "Compliance notice issued" in svc
    assert "Prosecution" in svc
    assert "$12,000" in svc
    assert f'href="{NSW_URL}"' in svc
    assert "Captured 29 October 2026" in svc
    assert "Joined by name, not by a printed approval number" in svc
    assert "2 of 2" in svc
    # The duplicate row is not listed.
    assert ">a3<" not in svc


def test_provider_page_lists_services_and_counts(built):
    _, pages = built
    prov = pages["provider/PR-00000001.html"]
    assert "Acme Care Pty Ltd" in prov
    assert "service/SE-00000001.html" in prov
    assert "Enforceable undertaking accepted" in prov  # provider-level action
    assert "1 of 3" in prov
    assert "see jurisdictions_publishing" not in prov


def test_unmatched_rows_appear_on_no_entity_page(built):
    _, pages = built
    for name, text in pages.items():
        if name.startswith(("service/", "provider/")):
            assert "Sanction under section 197L" not in text


def test_no_external_requests(built):
    _, pages = built
    for name, text in html_pages(pages).items():
        for m in re.finditer(r'<(?:script|link|img)[^>]+(?:src|href)="([^"]+)"', text):
            assert not m.group(1).startswith(("http:", "https:", "//")), (name, m.group(1))
    assert "http" not in pages["assets/search.js"]
    assert "cookie" not in pages["assets/search.js"].lower()


def test_site_wording_has_no_en_or_em_dashes(built):
    _, pages = built
    for name, text in pages.items():
        assert "–" not in text and "—" not in text, name


def test_mismatched_totals_fail_the_build(tmp_path):
    make_fixture(tmp_path / "data")
    path = tmp_path / "data" / "enforcement-by-service.csv"
    with path.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    rows[0]["actions_total"] = "5"
    write_csv(path, SERVICE_HEADER, rows)
    with pytest.raises(SystemExit):
        bs.build(tmp_path / "data", tmp_path / "dist")


def test_charts_have_titles_descriptions_and_tables(built):
    _, pages = built
    home = pages["index.html"]
    charts = re.findall(r'<svg class="chart"[^>]*>.*?</svg>', home, re.S)
    assert len(charts) == 2
    for svg in charts:
        assert 'role="img"' in svg
        ids = re.search(r'aria-labelledby="([^"]+)"', svg).group(1).split()
        title = re.search(r'<title id="([^"]+)">([^<]+)</title>', svg)
        desc = re.search(r'<desc id="([^"]+)">([^<]+)</desc>', svg)
        assert title and desc
        assert ids == [title.group(1), desc.group(1)]
        assert "of 6" in svg  # every bar value keeps its denominator
    assert home.count('<details class="chart-table">') == 2
    assert "Rows by publishing regulator" in home
    assert "Rows by action category" in home
    for name, text in html_pages(pages).items():
        for svg in re.findall(r'<svg[^>]*role="img"[^>]*>.*?</svg>', text, re.S):
            assert re.search(r"<title[^>]*>[^<]+</title>", svg), name


def test_sparklines_have_text_titles(built):
    _, pages = built
    prov = pages["provider/PR-00000001.html"]
    sparks = re.findall(r'<svg class="spark"[^>]*>.*?</svg>', prov, re.S)
    assert sparks
    for svg in sparks:
        assert re.search(r"<title>Actions per year at this service, \d{4} to \d{4}\. ", svg)


def test_badges_carry_text_labels(built):
    _, pages = built
    seen = 0
    for name, text in html_pages(pages).items():
        opened = text.count('class="badge ')
        found = re.findall(r'<span class="badge cat-([a-z_]+)">([^<]*)</span>', text)
        assert opened == len(found), name
        for cat, label in found:
            assert cat in bs.TYPE_LABELS, (name, cat)
            assert label == bs.TYPE_LABELS[cat] and label.strip(), (name, cat, label)
        seen += len(found)
    assert seen > 10
    svc = pages["service/SE-00000001.html"]
    # The register's own label sits alongside this site's category.
    assert "Compliance notice issued" in svc
    assert '<span class="badge cat-compliance_notice">Compliance notice</span>' in svc
    assert '<span class="badge cat-prosecution">Prosecution</span>' in svc


def test_pages_need_no_inline_style_or_script(built):
    """The Content-Security-Policy allows 'self' only: no inline styles or scripts."""
    _, pages = built
    for name, text in html_pages(pages).items():
        assert "style=" not in text, name
        assert "<style" not in text, name
        for tag in re.findall(r"<script[^>]*>", text):
            assert 'src="' in tag, (name, tag)


def test_recent_actions_list_newest_first(built):
    _, pages = built
    home = pages["index.html"]
    recent = re.search(r'<ol class="recent">(.*?)</ol>', home, re.S).group(1)
    dates = re.findall(r'<time datetime="([\d-]+)">', recent)
    assert dates == ["2026-02-27", "2025-11-11", "2025-07-04"]  # a2, a5, a1; a3 and a4 not listed
    assert 'href="service/SE-00000001.html"' in recent
    assert "Service name withheld" in recent
    assert "Withheld: subject is an individual" in recent
    assert WITHHELD_PERSON not in recent


def test_service_timeline_is_newest_first(built):
    _, pages = built
    svc = pages["service/SE-00000001.html"]
    timeline = re.search(r'<ol class="timeline">(.*?)</ol>', svc, re.S).group(1)
    assert re.findall(r'<time datetime="([\d-]+)">', timeline) == ["2026-02-27", "2025-07-04"]
    assert timeline.count("View source record") == 2
