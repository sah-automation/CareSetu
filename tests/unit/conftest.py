"""Shared pytest fixtures for the Phase 0 harness tests."""

import pytest

from phase0.loader import load_corpus


@pytest.fixture(scope="session")
def corpus():  # type: ignore[no-untyped-def]
    return load_corpus()
