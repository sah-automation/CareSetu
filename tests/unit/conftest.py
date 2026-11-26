"""Shared pytest fixtures for the unit tests."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from observability.error_capture import (
    DEFAULT_ERROR_CAPTURE_MAX_RECORDS,
    configure_error_capture,
    reset_error_capture,
)
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


@pytest.fixture
def clean_error_buffer() -> Iterator[None]:
    """The process-global error-capture buffer, empty and at its default ceiling.

    The buffer is module-level state shared by every test in the process, so a test
    that captures without resetting would assert against another test's records.
    Requested rather than autouse: only the tests that touch the buffer should pay
    for it, and an autouse fixture here would reconfigure a module singleton for
    every test in the suite.
    """
    configure_error_capture(DEFAULT_ERROR_CAPTURE_MAX_RECORDS, enabled=True)
    reset_error_capture()
    yield
    configure_error_capture(DEFAULT_ERROR_CAPTURE_MAX_RECORDS, enabled=True)
    reset_error_capture()
