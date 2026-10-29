from scrapers.common import normalise_pr, normalise_se, record_hash, utc_stamp


def test_normalise_se_variants():
    assert normalise_se("SE-00010955") == "SE-00010955"
    assert normalise_se("SE 00010955") == "SE-00010955"
    assert normalise_se("se-10955") == "SE-00010955"
    assert normalise_se("Service ID SE-00008497 (NSW)") == "SE-00008497"
    assert normalise_se("no key here") is None
    assert normalise_se(None) is None


def test_normalise_pr_variants():
    assert normalise_pr("PR-40001361") == "PR-40001361"
    assert normalise_pr("pr 6942") == "PR-00006942"
    assert normalise_pr("") is None


def test_record_hash_is_stable_and_case_insensitive():
    assert record_hash("NSW", "SE-1", "Compliance notice") == record_hash(
        "nsw", "se-1", " compliance notice "
    )
    assert record_hash("NSW", None) == record_hash("NSW", "")


def test_utc_stamp_shape():
    s = utc_stamp()
    assert len(s) == 16 and s.endswith("Z") and s[10] == "T"
