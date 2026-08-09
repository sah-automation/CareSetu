"""Shared pytest fixtures for the Phase 0 harness tests."""

import pytest

from phase0.loader import Corpus, load_corpus


@pytest.fixture(scope="session")
def corpus() -> Corpus:
    return load_corpus()
