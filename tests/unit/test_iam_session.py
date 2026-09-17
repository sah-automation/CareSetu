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
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from sqlalchemy.pool import NullPool

from modules.iam.adapters.sms import MockSmsAdapter
from modules.iam.domain.exceptions import (
    AccessTokenExpiredError,
    AccessTokenMalformedError,
    AccessTokenSignatureError,
    RefreshTokenRevokedError,
    SessionIssuanceError,
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


async def test_issue_partner_session_fails_closed_without_verified_partner_status() -> None:
    """WI-3 (#336): the mint refuses an unverified partner status before DB work.

    The partner-profile gate is verified upstream by the calling route, and the
    already-verified ``partner_id`` is the only proof this method accepts. A
    non-positive ``partner_id`` (never passed by the route) fails closed with
    the 409 ``SESSION_REFUSED`` contract - against an unreachable engine, so any
    accidental database round-trip would error instead of pass.
    """
    facade = _facade()

    with pytest.raises(SessionIssuanceError, match="partner status was not verified"):
        await facade.issue_partner_session("9876543210", partner_id=0)


class _StubConnection:
    """AsyncConnection stand-in whose ``execute`` satisfies the refresh revoke.

    The refresh rotation updates the old session row (``revoked_at``) in the
    same transaction as the mint; the stub just records nothing and returns,
    so the revoke statement and anything else ``execute``-shaped is inert under
    test.
    """

    async def execute(self, *args: object, **kwargs: object) -> None:
        return None


_STUB_CONNECTION = _StubConnection()


class _StubAsyncEngine:
    """AsyncEngine stand-in whose ``begin()`` yields a sentinel connection.

    The in-transaction re-check and the mint are stubbed in the tests below, so
    the engine itself only has to provide a live transaction context without ever
    touching a database (the NullPool engine would fail to connect).
    """

    def begin(self) -> AbstractAsyncContextManager[AsyncConnection]:
        class _Transaction:
            async def __aenter__(self) -> AsyncConnection:
                return _STUB_CONNECTION

            async def __aexit__(self, *exc_info: object) -> bool:
                return False

        return _Transaction()


async def test_issue_partner_session_reverifies_profile_under_the_lock_at_mint() -> None:
    """F4 (#342): the injected callback re-confirms the profile inside the mint tx.

    A profile valid at the route-level pre-check can vanish before the mint (a
    concurrent deletion). ``issue_partner_session`` must re-verify existence
    atomically - on its own open connection, under the identity row lock and in
    the same transaction as the mint - before the JWT is minted. The lock and
    the session-row insert are stubbed so the callback's invocation and ordering
    are what is under test; the callback receives the live transaction
    connection, and the mint must not run ahead of it.
    """

    class _FakeLocked:
        identity_id = 42
        phone_verified = True

    seen_connections: list[int] = []
    mint_connections: list[int] = []
    minted_scopes: list[str] = []

    async def _profile_present(connection: AsyncConnection, partner_id: int) -> None:
        seen_connections.append(id(connection))
        assert partner_id == 3

    async def _fake_mint(
        connection: AsyncConnection, identity_id: int, scope: str, now: datetime
    ) -> tuple[str, str, str]:
        mint_connections.append(id(connection))
        minted_scopes.append(scope)
        assert identity_id == 42
        return "jti-race-1", "refresh-race-1", "partner.jwt.race"

    facade = _facade()
    facade._sessions._engine = _StubAsyncEngine()
    with (
        patch(
            "modules.iam.session_facade._lock_identity_by_phone",
            new=AsyncMock(return_value=_FakeLocked()),
        ),
        patch(
            "modules.iam.session_facade.SessionFacade._mint_session_row",
            new=staticmethod(_fake_mint),
        ),
    ):
        result = await facade.issue_partner_session(
            "9876543210", partner_id=3, verify_partner_exists=_profile_present
        )

    assert result.scope == "partner"
    assert result.jwt == "partner.jwt.race"
    assert result.identity_id == 42
    assert len(seen_connections) == 1
    assert mint_connections == seen_connections


async def test_issue_partner_session_refuses_a_profile_deleted_before_mint() -> None:
    """F4 (#342): the atomic re-check surfaces as SessionIssuanceError, no mint.

    The concurrent deletion scenario: the profile is present at the route-level
    pre-check, then deleted before ``issue_partner_session`` reaches the mint.
    The injected callback detects the gone profile (via the partner facade seam
    against the mint transaction's connection) and raises
    ``SessionIssuanceError``; the mint must not run and the error must propagate
    as the 409 ``SESSION_REFUSED`` contract.
    """

    class _FakeLocked:
        identity_id = 42
        phone_verified = True

    called: list[tuple[int, int]] = []

    async def _profile_gone(connection: AsyncConnection, partner_id: int) -> None:
        called.append((id(connection), partner_id))
        raise SessionIssuanceError(f"partner profile {partner_id} no longer exists at session mint")

    async def _fake_mint(*args: object, **kwargs: object) -> tuple[str, str, str]:
        raise AssertionError("mint must not run when the re-check refuses the issuance")

    facade = _facade()
    facade._sessions._engine = _StubAsyncEngine()
    with (
        patch(
            "modules.iam.session_facade._lock_identity_by_phone",
            new=AsyncMock(return_value=_FakeLocked()),
        ),
        patch(
            "modules.iam.session_facade.SessionFacade._mint_session_row",
            new=staticmethod(_fake_mint),
        ),
        pytest.raises(SessionIssuanceError, match="no longer exists at session mint"),
    ):
        await facade.issue_partner_session(
            "9876543210", partner_id=3, verify_partner_exists=_profile_gone
        )

    assert len(called) == 1
    assert called[0][1] == 3


async def test_issue_partner_session_refuses_a_phone_not_phone_verified() -> None:
    """F014-T04 (#464): the mint refuses an unverified phone, no mint, no callback.

    Knowing a partner's number is no longer enough to become them: the mint
    reads the ``phone_verified`` marker from the locked identity row and refuses
    the issuance with the 409 ``SESSION_REFUSED`` contract when it is not set -
    a brand-new registrant who skipped the OTP step stays locked out until they
    verify. The identity guard is under test, so the profile re-check and the
    session-row mint must not run.
    """

    class _FakeLocked:
        identity_id = 42
        phone_verified = False

    async def _profile_present(connection: AsyncConnection, partner_id: int) -> None:
        raise AssertionError("the profile re-check must not run for an unverified phone")

    async def _fake_mint(*args: object, **kwargs: object) -> tuple[str, str, str]:
        raise AssertionError("mint must not run when the phone is not phone-verified")

    facade = _facade()
    facade._sessions._engine = _StubAsyncEngine()
    with (
        patch(
            "modules.iam.session_facade._lock_identity_by_phone",
            new=AsyncMock(return_value=_FakeLocked()),
        ),
        patch(
            "modules.iam.session_facade.SessionFacade._mint_session_row",
            new=staticmethod(_fake_mint),
        ),
        pytest.raises(SessionIssuanceError, match="not phone-verified"),
    ):
        await facade.issue_partner_session(
            "9876543210", partner_id=3, verify_partner_exists=_profile_present
        )


def _partner_refresh_session_row(*, scope: str = "partner") -> dict[str, object]:
    """A live (non-expired, non-revoked) session row for refresh under test."""
    return {
        "id": 1,
        "identity_id": 42,
        "scope": scope,
        "revoked_at": None,
        "refresh_expires_at": _NOW + timedelta(days=30),
    }


class _FakeLockedIdentity:
    """Identity guard state the refresh test stubs (patched ``_lock_identity_by_id``)."""

    def __init__(self, *, identity_id: int = 42, status: str = "Unverified") -> None:
        self.identity_id = identity_id
        self.status = status
        self.lockout_failed_attempts = 0
        self.lockout_until = None
        self.phone_verified = True


async def test_refresh_partner_renews_without_an_active_role_grant() -> None:
    """F014-T05 (#465): a pre-activation partner renews with no partner grant.

    The ``partner`` scope is re-derived without consulting the
    activation-gated ``partner`` role grant: the renewal gates on the iam-side
    suspension signal (identity and partner grant both not ``Suspended``) and
    the composition-boundary re-check confirming the partner profile still
    exists. The pre-activation lifecycle states ([Registered], [Under
    Verification], [Rejected]) live in the partner schema iam never reads, so
    any non-suspended identity with no (or an Active) partner grant renews;
    this test pins that ``_resolve_active_role`` is never consulted for the
    partner scope, that the re-check runs on the lock-held connection, and
    that the mint follows it.
    """

    seen: list[tuple[int, int]] = []
    minted_scopes: list[str] = []

    async def _session_row(connection: AsyncConnection, token_hash: str) -> dict[str, object]:
        return _partner_refresh_session_row()

    async def _profile_present(connection: AsyncConnection, identity_id: int) -> None:
        seen.append((id(connection), identity_id))
        assert identity_id == 42

    async def _forbid_resolve(
        connection: AsyncConnection, identity_id: int, role: str
    ) -> str | None:
        raise AssertionError("partner renewal must not read an active role grant")

    async def _fake_mint(
        connection: AsyncConnection, identity_id: int, scope: str, now: datetime
    ) -> tuple[str, str, str]:
        minted_scopes.append(scope)
        return "jti-refresh-1", "refresh-new-1", "partner.jwt.1"

    facade = _facade()
    facade._sessions._engine = _StubAsyncEngine()
    with (
        patch(
            "modules.iam.session_facade._session_for_refresh",
            new=AsyncMock(side_effect=_session_row),
        ),
        patch(
            "modules.iam.session_facade._lock_identity_by_id",
            new=AsyncMock(return_value=_FakeLockedIdentity()),
        ),
        patch(
            "modules.iam.session_facade._resolve_active_role",
            new=AsyncMock(side_effect=_forbid_resolve),
        ),
        patch(
            "modules.iam.session_facade._partner_role_status",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "modules.iam.session_facade.SessionFacade._mint_session_row",
            new=staticmethod(_fake_mint),
        ),
    ):
        result = await facade.refresh_session(
            "opaque-token", verify_partner_profile=_profile_present
        )

    assert result.scope == "partner"
    assert result.identity_id == 42
    assert result.jwt == "partner.jwt.1"
    assert len(seen) == 1
    assert seen[0][1] == 42
    assert minted_scopes == ["partner"]


async def test_refresh_refuses_a_suspended_partner_identity() -> None:
    """F014-T05 (#465): a Suspended identity's partner-scope refresh is refused.

    ``Suspended`` is the only identity refusal on the partner renewal path;
    the refusal fires before the profile re-check or the mint can run.
    """

    async def _session_row(connection: AsyncConnection, token_hash: str) -> dict[str, object]:
        return _partner_refresh_session_row()

    async def _profile_must_not_run(connection: AsyncConnection, identity_id: int) -> None:
        raise AssertionError("the profile re-check must not run for a suspended identity")

    async def _fake_mint(*args: object, **kwargs: object) -> tuple[str, str, str]:
        raise AssertionError("mint must not run for a suspended identity")

    facade = _facade()
    facade._sessions._engine = _StubAsyncEngine()
    with (
        patch(
            "modules.iam.session_facade._session_for_refresh",
            new=AsyncMock(side_effect=_session_row),
        ),
        patch(
            "modules.iam.session_facade._lock_identity_by_id",
            new=AsyncMock(return_value=_FakeLockedIdentity(status="Suspended")),
        ),
        patch(
            "modules.iam.session_facade.SessionFacade._mint_session_row",
            new=staticmethod(_fake_mint),
        ),
        pytest.raises(RefreshTokenRevokedError, match="Suspended"),
    ):
        await facade.refresh_session("opaque-token", verify_partner_profile=_profile_must_not_run)


async def test_refresh_refuses_a_suspended_partner_role_grant() -> None:
    """F014-T05 (#465): a deactivated partner's suspended grant refuses renewal.

    ``Suspended`` on the iam side covers the ``partner`` role grant too: an
    identity that is still ``Active`` but whose grant was flipped by
    ``suspend_partner_role`` (the ``partner.rejected`` /
    ``credential.invalidated`` deactivation path) must not renew. The refusal
    fires before the profile re-check or the mint, and ``_resolve_active_role``
    is still never consulted for the partner scope.
    """

    async def _session_row(connection: AsyncConnection, token_hash: str) -> dict[str, object]:
        return _partner_refresh_session_row()

    async def _forbid_resolve(
        connection: AsyncConnection, identity_id: int, role: str
    ) -> str | None:
        raise AssertionError("partner renewal must not read an active role grant")

    async def _profile_must_not_run(connection: AsyncConnection, identity_id: int) -> None:
        raise AssertionError("the profile re-check must not run for a suspended grant")

    async def _fake_mint(*args: object, **kwargs: object) -> tuple[str, str, str]:
        raise AssertionError("mint must not run for a suspended grant")

    facade = _facade()
    facade._sessions._engine = _StubAsyncEngine()
    with (
        patch(
            "modules.iam.session_facade._session_for_refresh",
            new=AsyncMock(side_effect=_session_row),
        ),
        patch(
            "modules.iam.session_facade._lock_identity_by_id",
            new=AsyncMock(return_value=_FakeLockedIdentity(status="Active")),
        ),
        patch(
            "modules.iam.session_facade._partner_role_status",
            new=AsyncMock(return_value="Suspended"),
        ),
        patch(
            "modules.iam.session_facade._resolve_active_role",
            new=AsyncMock(side_effect=_forbid_resolve),
        ),
        patch(
            "modules.iam.session_facade.SessionFacade._mint_session_row",
            new=staticmethod(_fake_mint),
        ),
        pytest.raises(RefreshTokenRevokedError, match="suspended partner role"),
    ):
        await facade.refresh_session("opaque-token", verify_partner_profile=_profile_must_not_run)


async def test_refresh_refuses_when_the_partner_profile_was_deleted() -> None:
    """F014-T05 (#465): a deleted partner profile refuses the rotation.

    The composition-boundary re-check rides the callback the route wires; when
    it detects the profile is gone it raises the refresh envelope and the mint
    must not run. iam itself never reads the partner schema.
    """

    async def _session_row(connection: AsyncConnection, token_hash: str) -> dict[str, object]:
        return _partner_refresh_session_row()

    async def _profile_deleted(connection: AsyncConnection, identity_id: int) -> None:
        raise RefreshTokenRevokedError(
            f"identity {identity_id} has no partner profile; refusing to refresh"
        )

    async def _fake_mint(*args: object, **kwargs: object) -> tuple[str, str, str]:
        raise AssertionError("mint must not run when the partner profile is gone")

    facade = _facade()
    facade._sessions._engine = _StubAsyncEngine()
    with (
        patch(
            "modules.iam.session_facade._session_for_refresh",
            new=AsyncMock(side_effect=_session_row),
        ),
        patch(
            "modules.iam.session_facade._lock_identity_by_id",
            new=AsyncMock(return_value=_FakeLockedIdentity()),
        ),
        patch(
            "modules.iam.session_facade._partner_role_status",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "modules.iam.session_facade.SessionFacade._mint_session_row",
            new=staticmethod(_fake_mint),
        ),
        pytest.raises(RefreshTokenRevokedError, match="no partner profile"),
    ):
        await facade.refresh_session("opaque-token", verify_partner_profile=_profile_deleted)


@pytest.mark.parametrize("scope", ["patient", "operator"])
async def test_refresh_non_partner_scope_still_requires_an_active_role_grant(
    scope: str,
) -> None:
    """F014-T05 (#465): patient/operator refresh keeps the role-grant gate.

    Only the ``partner`` renewal is loosened. A patient/operator session whose
    identity holds no active grant for its scope is still refused with the
    refresh envelope, and the partner profile re-check is never consulted.
    """

    async def _session_row(connection: AsyncConnection, token_hash: str) -> dict[str, object]:
        return _partner_refresh_session_row(scope=scope)

    async def _no_grant(connection: AsyncConnection, identity_id: int, role: str) -> str | None:
        assert role == scope
        return None

    async def _profile_must_not_run(connection: AsyncConnection, identity_id: int) -> None:
        raise AssertionError("the partner re-check must not run for a non-partner scope")

    async def _fake_mint(*args: object, **kwargs: object) -> tuple[str, str, str]:
        raise AssertionError("mint must not run when the scope has no active grant")

    facade = _facade()
    facade._sessions._engine = _StubAsyncEngine()
    with (
        patch(
            "modules.iam.session_facade._session_for_refresh",
            new=AsyncMock(side_effect=_session_row),
        ),
        patch(
            "modules.iam.session_facade._lock_identity_by_id",
            new=AsyncMock(return_value=_FakeLockedIdentity(status="Active")),
        ),
        patch(
            "modules.iam.session_facade._resolve_active_role",
            new=AsyncMock(side_effect=_no_grant),
        ),
        patch(
            "modules.iam.session_facade.SessionFacade._mint_session_row",
            new=staticmethod(_fake_mint),
        ),
        pytest.raises(RefreshTokenRevokedError, match=f"{scope} role grant"),
    ):
        await facade.refresh_session("opaque-token", verify_partner_profile=_profile_must_not_run)


@pytest.mark.parametrize("scope", ["patient", "operator"])
async def test_refresh_non_partner_scope_still_requires_an_active_identity(
    scope: str,
) -> None:
    """F014-T05 (#465): only the partner path relaxes the identity-status gate.

    A non-Suspended-but-not-Active identity still cannot renew a patient or
    operator session (that relaxation is partner-only): the refusal fires from
    the identity gate before any grant lookup or mint.
    """

    async def _session_row(connection: AsyncConnection, token_hash: str) -> dict[str, object]:
        return _partner_refresh_session_row(scope=scope)

    async def _resolve_must_not_run(
        connection: AsyncConnection, identity_id: int, role: str
    ) -> str | None:
        raise AssertionError("grant lookup must not run for a non-Active identity")

    async def _fake_mint(*args: object, **kwargs: object) -> tuple[str, str, str]:
        raise AssertionError("mint must not run for a non-Active non-partner identity")

    facade = _facade()
    facade._sessions._engine = _StubAsyncEngine()
    with (
        patch(
            "modules.iam.session_facade._session_for_refresh",
            new=AsyncMock(side_effect=_session_row),
        ),
        patch(
            "modules.iam.session_facade._lock_identity_by_id",
            new=AsyncMock(return_value=_FakeLockedIdentity(status="Unverified")),
        ),
        patch(
            "modules.iam.session_facade._resolve_active_role",
            new=AsyncMock(side_effect=_resolve_must_not_run),
        ),
        patch(
            "modules.iam.session_facade.SessionFacade._mint_session_row",
            new=staticmethod(_fake_mint),
        ),
        pytest.raises(RefreshTokenRevokedError, match="Unverified"),
    ):
        await facade.refresh_session("opaque-token")


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
