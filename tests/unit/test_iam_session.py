"""PHASE-2 T6: facade session seam without a database (ticket #57).

``validate_token`` is the stateless hot path (MOD-001 §3.1: p95 < 100 ms) -
signature + expiry only, no DB round-trip. These tests drive it through the
facade against tokens minted by the domain ``issue_token``, using an engine
pointing at an unreachable host: if ``validate_token`` ever touched the
database the connect would fail and the test would error instead of pass.
"""

from __future__ import annotations

import statistics
import time
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from modules.iam.adapters.sms import MockSmsAdapter
from modules.iam.domain.exceptions import (
    AccessTokenExpiredError,
    AccessTokenMalformedError,
    AccessTokenSignatureError,
)
from modules.iam.domain.jwt import issue_token
from modules.iam.facade import IamFacade, ValidatedAccessToken

_KEY = "unit-test-signing-key"
_OTHER_KEY = "unit-test-other-key"
_NOW = datetime(2026, 8, 13, 12, 0, 0, tzinfo=UTC)

_PERF_BATCH_SIZE = 1000
_PERF_WARMUP_CALLS = 20
_P95_BUDGET_MS = 100.0


def _p95_ms(latencies_ms: list[float]) -> float:
    """The 95th percentile of the per-call latencies, in milliseconds."""
    return statistics.quantiles(latencies_ms, n=100)[94]


class MutableClock:
    """Clock stand-in tests advance to walk the access-token expiry window."""

    def __init__(self, now: datetime) -> None:
        self._now = now

    def set(self, now: datetime) -> None:
        self._now = now

    def __call__(self) -> datetime:
        return self._now


def _facade(clock: MutableClock | None = None) -> IamFacade:
    engine = create_async_engine(
        "postgresql+asyncpg://no-such-host.invalid/no-db", poolclass=NullPool
    )
    return IamFacade(
        engine=engine,
        sms_adapter=MockSmsAdapter(),
        clock=clock if clock is not None else MutableClock(_NOW),
        access_token_signing_key=_KEY,
    )


def _token(
    *,
    jti: str = "jti-unit-1",
    subject_id: int = 7,
    scope: str = "patient",
    key: str = _KEY,
) -> str:
    return issue_token(
        jti=jti,
        subject_id=subject_id,
        scope=scope,
        signing_key=key,
        now=_NOW,
    )


async def test_validate_token_resolves_scope_through_the_facade() -> None:
    token = _token()

    validated = await _facade().validate_token(token)

    assert validated == ValidatedAccessToken(subject_id=7, scope="patient", jti="jti-unit-1")


async def test_validate_token_rejects_an_expired_token() -> None:
    clock = MutableClock(_NOW)
    token = _token()
    clock.set(_NOW + timedelta(minutes=20))

    with pytest.raises(AccessTokenExpiredError):
        await _facade(clock).validate_token(token)


async def test_validate_token_rejects_a_tampered_token() -> None:
    token = _token()
    header, payload, _signature = token.split(".")

    with pytest.raises(AccessTokenSignatureError):
        await _facade().validate_token(f"{header}.{payload}.AAAA")


async def test_validate_token_rejects_a_malformed_token() -> None:
    with pytest.raises(AccessTokenMalformedError):
        await _facade().validate_token("not-a-jwt")


async def test_validate_token_rejects_a_wrong_signature_token() -> None:
    token = _token(key=_OTHER_KEY)

    with pytest.raises(AccessTokenSignatureError):
        await _facade().validate_token(token)


async def test_validate_token_fails_closed_without_a_configured_key() -> None:
    engine = create_async_engine(
        "postgresql+asyncpg://no-such-host.invalid/no-db", poolclass=NullPool
    )
    facade = IamFacade(
        engine=engine,
        sms_adapter=MockSmsAdapter(),
        access_token_signing_key="",
    )
    token = _token()

    with pytest.raises(AccessTokenSignatureError, match="signing key is not configured"):
        await facade.validate_token(token)


async def test_validate_token_p95_stays_under_the_100ms_budget() -> None:
    """Pin MOD-001 §3.1 / roadmap §2.2: validate_token p95 < 100 ms (ticket #79).

    The release-readiness criterion is asserted, not commented: a fixed batch of
    tokens is validated through the facade while each call is timed with
    ``perf_counter``, and the p95 of the per-call latencies must clear the 100 ms
    budget. A warm-up pass runs before the timed loop so the cold first-call
    path (module/bytecode warm-up) is excluded, and the generous bound keeps CI
    variance from flaking it. The engine points at an unreachable host, so any
    accidental database round-trip would fail the test instead of pass.
    """
    facade = _facade()
    tokens = [
        _token(jti=f"jti-perf-{i}", subject_id=(i % 100) + 1) for i in range(_PERF_BATCH_SIZE)
    ]

    validated = await facade.validate_token(tokens[0])
    assert validated.scope == "patient"
    for i in range(_PERF_WARMUP_CALLS):
        await facade.validate_token(tokens[i % _PERF_BATCH_SIZE])

    latencies_ms: list[float] = []
    for token in tokens:
        started = time.perf_counter()
        await facade.validate_token(token)
        latencies_ms.append((time.perf_counter() - started) * 1000.0)

    assert _p95_ms(latencies_ms) < _P95_BUDGET_MS
