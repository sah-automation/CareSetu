"""Shared pytest fixtures for the unit tests."""

import pytest

from phase0.loader import Corpus, load_corpus


@pytest.fixture(scope="session")
def corpus() -> Corpus:
    return load_corpus()


class FakeClock:
    """Deterministic ``time.monotonic`` stand-in that the test advances.

    Used by the idempotency store and route tests to drive TTL expiry without
    touching the wall clock.
    """

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def fake_clock() -> FakeClock:
    """A fresh ``FakeClock`` per test, starting at ``0.0``."""
    return FakeClock()
