"""Shared test set-up."""

import pytest
from scrapers import common


@pytest.fixture(autouse=True)
def _fresh_in_memory_names():
    # The prose rule's in-memory name set is per process; start every test without one.
    common.reset_run_names()
    common.set_person_names(None)
    yield
    common.reset_run_names()
    common.set_person_names(None)
