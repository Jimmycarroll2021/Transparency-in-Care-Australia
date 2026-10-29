"""Tests for the entity_form classifier and name normalisation. Fixtures are inline and fictional."""

import csv

import pytest
from scrapers import profile_providers as pp


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Sunny Days Early Learning Pty Ltd", "company"),
        ("Example Care Pty. Limited", "company"),
        ("Goodstart Example Ltd", "company"),
        ("Bright Futures Limited", "company"),
        ("Northside Before and After School Care Incorporated", "incorporated_association"),
        ("Hillview Kindergarten Inc", "incorporated_association"),
        ("Riverbend Playgroup Association", "incorporated_association"),
        ("Greenbank State School Parents & Citizens Assoc", "incorporated_association"),
        ("Valley Co-operative Child Care Society Ltd", "cooperative"),
        ("Hilltop Community Cooperative", "cooperative"),
        ("City of Exampleton", "government"),
        ("Exampleton Shire Council", "government"),
        ("Department for Education", "government"),
        ("Minister for Education", "government"),
        ("Crown in Right of Example", "government"),
        ("Exampleton Public School", "government"),
        ("Example Community Council Inc", "incorporated_association"),
        ("ABC Services Pty Ltd as trustee for The Example Family Trust", "trust_or_trustee"),
        ("Example Holdings Pty Ltd ATF Smith Family Trust", "trust_or_trustee"),
        ("The Example Education Trust", "trust_or_trustee"),
        ("Example Parish Child Care", "church_or_religious"),
        ("Uniting Example Care", "church_or_religious"),
        ("St Example Catholic Primary School Ltd", "church_or_religious"),
        ("The Salvation Army (Example) Property Trust", "church_or_religious"),
        ("Example Lutheran Church Inc", "church_or_religious"),
        ("Jane Citizen", "likely_individual"),
        ("John Q Citizen", "likely_individual"),
        ("Mary-Anne O'Example", "likely_individual"),
        ("JANE CITIZEN", "likely_individual"),
        ("Jane Citizen & John Citizen", "likely_individual"),
        ("A Citizen & B Citizen", "likely_individual"),
        ("Jane Citizen T/A Happy Clowns Kindergarten", "likely_individual"),
        ("Exampleton Primary School", "unknown"),
        ("Goodstart", "unknown"),
        ("Little Gems Learning", "unknown"),
        ("Bright & Early", "unknown"),
        ("", "unknown"),
        (None, "unknown"),
    ],
)
def test_classify_entity_form(name, expected):
    assert pp.classify_entity_form(name) == expected


def test_company_marker_beats_person_shape():
    # Two capitalised words plus a marker is a company, never an individual.
    assert pp.classify_entity_form("Jane Citizen Pty Ltd") == "company"
    assert pp.classify_entity_form("Jane Citizen Inc") == "incorporated_association"


def test_business_word_blocks_individual():
    assert pp.classify_entity_form("Kind Hearts Childcare") == "unknown"
    assert pp.classify_entity_form("Rose Bay Kindergarten") == "unknown"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Sunny Days Pty Ltd", "SUNNY DAYS PTY LTD"),
        ("SUNNY DAYS PTY. LIMITED", "SUNNY DAYS PTY LTD"),
        ("Sunny Days Proprietary Limited", "SUNNY DAYS PTY LTD"),
        ("Sunny  Days (ACN 123 456 789) Pty Ltd", "SUNNY DAYS PTY LTD"),
        ("Sunny Days Limited", "SUNNY DAYS LTD"),
        ("Sunny Days Ltd.", "SUNNY DAYS LTD"),
        ("Sunny Days Incorporated", "SUNNY DAYS INC"),
        ("Sunny Days Inc.", "SUNNY DAYS INC"),
        ("Tom & Jerry's Kids Pty Ltd", "TOM AND JERRYS KIDS PTY LTD"),
        ("O'Brien’s Care", "OBRIENS CARE"),
        ("  ", None),
        (None, None),
    ],
)
def test_normalise_name(raw, expected):
    assert pp.normalise_name(raw) == expected


def test_normalise_name_makes_variants_equal():
    variants = ["Sunny Days Pty Ltd", "SUNNY DAYS PTY LIMITED", "Sunny Days P/L"]
    assert len({pp.normalise_name(v) for v in variants}) == 1


def test_strip_corporate_suffix():
    assert pp.strip_corporate_suffix("Sunny Days Pty Ltd") == "SUNNY DAYS"
    assert pp.strip_corporate_suffix("Sunny Days Incorporated") == "SUNNY DAYS"
    assert pp.strip_corporate_suffix("Sunny Days") == "SUNNY DAYS"
    assert pp.strip_corporate_suffix(None) is None


def test_build_profile_withholds_individual_names(tmp_path, monkeypatch):
    providers = tmp_path / "providers.csv"
    services = tmp_path / "services.csv"
    with providers.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(
            [
                "Legal Name",
                "Trading Name",
                "State",
                "Date Approval Granted",
                "provider_approval_number",
            ]
        )
        w.writerow(["Jane Citizen", "Citizen Kids", "NSW", "01/01/2020", "PR-00000001"])
        w.writerow(["Sunny Days Pty Ltd", "Sunny Days", "VIC", "01/01/2021", "PR-00000002"])
    with services.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["provider_approval_number", "State", "ServiceType", "NumberOfApprovedPlaces"])
        for _ in range(5):
            w.writerow(["PR-00000001", "NSW", "Centre-Based Care", "30"])
        w.writerow(["PR-00000002", "VIC", "Centre-Based Care", "40"])
        w.writerow(["PR-00000002", "QLD", "Family Day Care", ""])
    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.setattr(pp, "PROVIDERS_CSV", providers)
    monkeypatch.setattr(pp, "SERVICES_CSV", services)
    monkeypatch.setattr(pp, "SUMMARY_JSON", out / "summary.json")
    monkeypatch.setattr(pp, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(pp, "PROCESSED_DIR", out)
    written = {}

    def fake_write(name, rows, fieldnames, **kwargs):
        written["rows"] = rows

    monkeypatch.setattr(pp, "write_processed", fake_write)
    summary = pp.build_profile()

    by_pr = {r["provider_approval_number"]: r for r in written["rows"]}
    ind = by_pr["PR-00000001"]
    assert ind["entity_form"] == "likely_individual"
    assert ind["legal_name"] is None and ind["trading_name"] is None
    assert ind["name_withheld"] == "true"
    assert ind["service_count"] == 5
    co = by_pr["PR-00000002"]
    assert co["states_operated_in"] == "QLD|VIC" and co["state_count"] == 2
    assert co["total_approved_places"] == 40 and co["services_without_places_value"] == 1

    text = (out / "summary.json").read_text()
    assert "Citizen" not in text
    assert [
        t["provider_approval_number"] for t in summary["top_30_providers_by_service_count"]
    ] == ["PR-00000002"]
    assert summary["management_type"]["available"] is False
