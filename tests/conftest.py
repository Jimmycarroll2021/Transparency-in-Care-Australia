"""Shared test set-up."""

import pytest
from scrapers import common

# A fixed, public test key for the keyed join (PR #11). Never the real TICA_JOIN_KEY.
TEST_JOIN_KEY = "5a" * 32


@pytest.fixture(autouse=True)
def _fresh_in_memory_names():
    # The prose rule's in-memory name set is per process; start every test without one.
    common.reset_run_names()
    common.set_person_names(None)
    yield
    common.reset_run_names()
    common.set_person_names(None)


@pytest.fixture(autouse=True)
def _test_join_key(monkeypatch, tmp_path):
    # CI has no TICA_JOIN_KEY; every test sees the fixed test key and never a local .env.
    monkeypatch.setenv(common.JOIN_KEY_VAR, TEST_JOIN_KEY)
    monkeypatch.setattr(common, "ENV_FILE", tmp_path / "no.env")
    common.skip_name_keys(False)
    yield
    common.skip_name_keys(False)
