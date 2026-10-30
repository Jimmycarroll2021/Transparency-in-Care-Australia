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


def test_summary_records_posix_paths_on_every_platform(tmp_path, monkeypatch):
    # A run on Windows must not write backslashes into the summary inputs.
    processed = tmp_path / "data" / "processed"
    processed.mkdir(parents=True)
    providers = processed / "acecqa-providers-latest.csv"
    services = processed / "acecqa-services-latest.csv"
    providers.write_text(
        "Legal Name,Trading Name,State,Date Approval Granted,provider_approval_number\n"
        "Sunny Days Pty Ltd,Sunny Days,VIC,01/01/2021,PR-00000002\n",
        encoding="utf-8",
    )
    services.write_text(
        "provider_approval_number,State,ServiceType,NumberOfApprovedPlaces\n"
        "PR-00000002,VIC,Centre-Based Care,40\n",
        encoding="utf-8",
    )
    providers.with_suffix(".provenance.json").write_text(
        '{"raw_inputs": ["data/raw/acecqa/2026-10-29T0700Z-providers.csv.gz"]}', encoding="utf-8"
    )
    monkeypatch.setattr(pp, "PROVIDERS_CSV", providers)
    monkeypatch.setattr(pp, "SERVICES_CSV", services)
    monkeypatch.setattr(pp, "SUMMARY_JSON", processed / "provider-profile-summary.json")
    monkeypatch.setattr(pp, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(pp, "PROCESSED_DIR", processed)
    monkeypatch.setattr(pp, "write_processed", lambda *a, **k: None)
    inputs = pp.build_profile()["inputs"]
    assert inputs["providers_file"] == "data/processed/acecqa-providers-latest.csv"
    assert inputs["services_file"] == "data/processed/acecqa-services-latest.csv"
    assert inputs["raw_inputs"] == [
        "data/processed/acecqa-providers-latest.csv",
        "data/raw/acecqa/2026-10-29T0700Z-providers.csv.gz",
        "data/processed/acecqa-services-latest.csv",
    ]


# ---------------------------------------------------------------------------
# Fail-closed name withholding (CLAUDE.md rule 2). Every name below is synthetic.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "Jane Example & John Example ATF Example Family Trust",
        "Jane Example and John Example as Trustees for The Example Family Trust",
        "Jane Example as trustee for the Sunny Days Trust",
        "Jane Q Example ATF Sunny Days Unit Trust",
    ],
)
def test_individual_trustee_is_classed_individual_and_withheld(name):
    assert pp.classify_entity_form(name) == "likely_individual"
    assert pp.name_is_withheld(name) is True


@pytest.mark.parametrize(
    "name",
    [
        "Mrs Jane Example and Mr John Example - executors of the estate of Mary Example",
        "Estate of the late John Example",
        "The Estate of Mary Example",
        "John Example Executor",
        "Jane Example (deceased)",
    ],
)
def test_estate_or_executor_name_is_classed_individual_and_withheld(name):
    assert pp.classify_entity_form(name) == "likely_individual"
    assert pp.name_is_withheld(name) is True


@pytest.mark.parametrize(
    "name", ["Zoë Exämple", "José Ñandú", "Ana-Lúcia Exemplo", "Renée Exampleé"]
)
def test_accented_personal_name_is_withheld(name):
    assert pp.classify_entity_form(name) == "likely_individual"
    assert pp.name_is_withheld(name) is True


@pytest.mark.parametrize(
    "name",
    [
        "Example Holdings Pty Ltd as trustee for Jane Example",
        "Example Holdings Pty Ltd ATF the Jane Example Family Trust",
        "Jane Example/John Example",
        "Mrs Jane Example",
        "Goodstart",
        "Kind Hearts Childcare",
        "Jane Example Family Day Care",
        "J & K Example Gum Tree Pre School",
        "Jane L Example and John M Example Partnership",
        "Jane example",
    ],
)
def test_name_not_positively_an_organisation_is_withheld(name):
    assert pp.name_is_withheld(name) is True


@pytest.mark.parametrize(
    "name",
    [
        "Sunny Days Early Learning Pty Ltd",
        "Jane Citizen Pty Ltd",
        "Hillview Kindergarten Inc",
        "Exampleton Shire Council",
        "Valley Co-operative Child Care Society Ltd",
        "ABC Services Pty Ltd as trustee for The Example Family Trust",
        "Example Holdings Pty Ltd ATF Smith Family Trust",
        "Example Valley Aboriginal Corporation",
        "MS Example Education Pty Ltd",
        "Corporation of the Trustees of the Example Diocese - Example Services",
        "Little Stars Exampleton Pty Ltd ATF Little Stars Exampleton Unit Trust",
    ],
)
def test_organisation_name_is_still_shown(name):
    assert pp.name_is_withheld(name) is False


def test_build_profile_fails_closed_on_trustees_estates_and_accents(tmp_path, monkeypatch):
    providers = tmp_path / "providers.csv"
    services = tmp_path / "services.csv"
    fixtures = [
        ("PR-00000011", "Jane Example & John Example ATF Example Family Trust", "Example Kids"),
        (
            "PR-00000012",
            "Jane Example - executor of the estate of Mary Example",
            "Mrs Mary Example",
        ),
        ("PR-00000013", "Zoë Exämple", ""),
        ("PR-00000014", "Example Holdings Pty Ltd ATF Smith Family Trust", "Sunny Days"),
        ("PR-00000015", "Sunny Days Pty Ltd", "Sunny Days"),
    ]
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
        for pr, legal, trading in fixtures:
            w.writerow([legal, trading, "NSW", "01/01/2020", pr])
    with services.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["provider_approval_number", "State", "ServiceType", "NumberOfApprovedPlaces"])
        for pr, _, _ in fixtures:
            w.writerow([pr, "NSW", "Centre-Based Care", "30"])
    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.setattr(pp, "PROVIDERS_CSV", providers)
    monkeypatch.setattr(pp, "SERVICES_CSV", services)
    monkeypatch.setattr(pp, "SUMMARY_JSON", out / "summary.json")
    monkeypatch.setattr(pp, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(pp, "PROCESSED_DIR", out)
    written = {}
    monkeypatch.setattr(
        pp, "write_processed", lambda name, rows, fieldnames, **k: written.update(rows=rows)
    )
    pp.build_profile()

    by_pr = {r["provider_approval_number"]: r for r in written["rows"]}
    for pr in ("PR-00000011", "PR-00000012", "PR-00000013"):
        row = by_pr[pr]
        assert row["name_withheld"] == "true", pr
        assert row["legal_name"] is None and row["trading_name"] is None, pr
    for pr in ("PR-00000014", "PR-00000015"):
        assert by_pr[pr]["name_withheld"] == "false", pr
        assert by_pr[pr]["legal_name"], pr
    text = (out / "summary.json").read_text(encoding="utf-8")
    assert "Example Family" not in text and "Exämple" not in text and "executor" not in text


# Codex round 1, finding 4: an institutional keyword alone is not organisation evidence. These
# names were shown before; they are now withheld unless a legal form, a government form or a
# non-individual ABR entity type supports them.
@pytest.mark.parametrize(
    "name",
    [
        "Example Parish Child Care",
        "The Trustee for the Example Education Trust",
        "The Example Education Trust",
        "Exampleton Primary School",
        "Exampleton Grammar School",
        "Exampleton Regional Community Services",
        "Exampleton Pre-School Kindergarten",
        "Jane Example Primary School",
        "Jane Example Community Kindergarten",
        "Jane Example Aboriginal Community Services",
    ],
)
def test_institutional_keyword_alone_is_withheld(name):
    assert pp.name_is_withheld(name) is True


@pytest.mark.parametrize(
    ("name", "abr_type", "withheld"),
    [
        ("Exampleton Primary School", "SGE", False),
        ("Exampleton Regional Community Services", "OIE", False),
        ("Example Child Care Centre", "PRV", False),
        ("The Example Education Trust", "DTT", True),  # a trust type is not organisation evidence
        ("Jane Example", "PRV", True),  # person signals always win
        ("Example Holdings Pty Ltd ATF Jane Example Family Trust", "PRV", True),
        ("Exampleton Primary School", None, True),
        ("Exampleton Primary School", "IND", True),
    ],
)
def test_abr_entity_type_is_organisation_evidence(name, abr_type, withheld):
    assert pp.name_is_withheld(name, abr_entity_type=abr_type) is withheld


def test_build_profile_uses_abr_entity_type_as_evidence(tmp_path, monkeypatch):
    providers = tmp_path / "providers.csv"
    services = tmp_path / "services.csv"
    abn = tmp_path / "provider-abn.csv"
    providers.write_text(
        "Legal Name,Trading Name,State,Date Approval Granted,provider_approval_number\n"
        "Exampleton Primary School,,VIC,01/01/2020,PR-00000041\n"
        "Westvale Primary School,,VIC,01/01/2020,PR-00000042\n",
        encoding="utf-8",
    )
    services.write_text(
        "provider_approval_number,State,ServiceType,NumberOfApprovedPlaces\n"
        "PR-00000041,VIC,Centre-Based Care,30\nPR-00000042,VIC,Centre-Based Care,30\n",
        encoding="utf-8",
    )
    abn.write_text(
        "provider_approval_number,abn,match_kind,entity_type_code\n"
        "PR-00000041,11111111111,accepted_unique,SGE\n",
        encoding="utf-8",
    )
    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.setattr(pp, "PROVIDERS_CSV", providers)
    monkeypatch.setattr(pp, "SERVICES_CSV", services)
    monkeypatch.setattr(pp, "PROVIDER_ABN_CSV", abn)
    monkeypatch.setattr(pp, "SUMMARY_JSON", out / "summary.json")
    monkeypatch.setattr(pp, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(pp, "PROCESSED_DIR", out)
    written = {}
    monkeypatch.setattr(
        pp, "write_processed", lambda name, rows, fieldnames, **k: written.update(rows=rows)
    )
    pp.build_profile()
    by_pr = {r["provider_approval_number"]: r for r in written["rows"]}
    assert by_pr["PR-00000041"]["name_withheld"] == "false"
    assert by_pr["PR-00000042"]["name_withheld"] == "true"
