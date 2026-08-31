"""PHASE-5 T07: operator MFA login, bootstrap seed, and operator RBAC (ticket #250).

Operators are a trusted closed group that never self-registers: an identity
only gains the ``operator`` role through ``create_operator_account`` (the
invite/seed path), and an operator-scoped session is minted only through
``issue_operator_session`` (the MFA-bound login) - the same ``issue_token`` +
``validate_token`` seam as the patient session, scoped to ``operator`` so the
gateway's ``require_operator`` admits the caller.

The pure-logic surfaces pinned here mirror ``test_iam_session.py`` (the
stateless ``validate_token`` resolves the ``operator`` scope without a
database) and ``test_gateway.py`` (the ``require_operator`` route guard admits
only an authenticated operator). The outbox event and role-grant persistence
are the integration suite's job.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool
from starlette.requests import Request

from app.gateway.errors import (
    AuthenticationRequiredError,
    InsufficientScopeError,
)
from app.gateway.principal import Principal
from app.gateway.rbac import require_operator
from modules.iam.adapters.sms import MockSmsAdapter
from modules.iam.domain.exceptions import (
    AccessTokenMalformedError,
    AccessTokenSignatureError,
)
from modules.iam.domain.jwt import issue_token
from modules.iam.facade import IamFacade, ValidatedAccessToken

_KEY = "unit-test-operator-signing-key"
_OTHER_KEY = "unit-test-operator-other-key"
_NOW = datetime(2026, 8, 31, 12, 0, 0, tzinfo=UTC)


class MutableClock:
    """Clock stand-in tests advance to walk the access-token expiry window."""

    def __init__(self, now: datetime) -> None:
        self._now = now

    def set(self, now: datetime) -> None:
        self._now = now

    def __call__(self) -> datetime:
        return self._now


def _facade() -> IamFacade:
    engine = create_async_engine(
        "postgresql+asyncpg://no-such-host.invalid/no-db", poolclass=NullPool
    )
    return IamFacade(
        engine=engine,
        sms_adapter=MockSmsAdapter(),
        clock=MutableClock(_NOW),
        access_token_signing_key=_KEY,
    )


def _operator_token(*, jti: str = "jti-operator-1", key: str = _KEY) -> str:
    return issue_token(
        jti=jti,
        subject_id=11,
        scope="operator",
        signing_key=key,
        now=_NOW,
    )


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _operator_request(principal: Principal) -> Request:
    """A crafted request carrying an authenticated (or anonymous) principal.

    The gateway wraps the verified access JWT into a ``Principal`` and attaches
    it to ``request.state``; ``require_operator`` reads only that. This builds
    the request shape the route guard consumes, so admission/denial is pinned
    without a database.
    """
    request = Request(
        scope={
            "type": "http",
            "method": "GET",
            "scheme": "http",
            "path": "/v1/operator/console",
            "raw_path": b"/v1/operator/console",
            "query_string": b"",
            "root_path": "",
            "headers": [],
            "client": ("testclient", 12345),
            "server": ("testserver", 80),
        }
    )
    request.state.principal = principal
    return request


# ---------------------------------------------------------------------------
# Operator session seam (mirrors test_iam_session.py)
# ---------------------------------------------------------------------------


async def test_validate_token_resolves_operator_scope_through_the_facade() -> None:
    validated = await _facade().validate_token(_operator_token())

    assert validated == ValidatedAccessToken(subject_id=11, scope="operator", jti="jti-operator-1")


async def test_validate_token_rejects_an_operator_token_signed_by_the_wrong_key() -> None:
    with pytest.raises(AccessTokenSignatureError):
        await _facade().validate_token(_operator_token(key=_OTHER_KEY))


async def test_validate_token_rejects_a_malformed_operator_token() -> None:
    with pytest.raises(AccessTokenMalformedError):
        await _facade().validate_token("not-a-jws")


# ---------------------------------------------------------------------------
# require_operator route guard (mirrors test_gateway.py)
# ---------------------------------------------------------------------------


async def test_require_operator_admits_an_operator_scoped_caller() -> None:
    principal = Principal.for_subject("11", "operator")

    admitted = await require_operator(_operator_request(principal))

    assert admitted == principal


async def test_require_operator_denies_an_anonymous_caller_with_401() -> None:
    with pytest.raises(AuthenticationRequiredError):
        await require_operator(_operator_request(Principal.anonymous()))


async def test_require_operator_denies_a_patient_caller_with_403() -> None:
    principal = Principal.for_subject("7", "patient")

    with pytest.raises(InsufficientScopeError):
        await require_operator(_operator_request(principal))


async def test_require_operator_denies_an_unknown_scope_principal_with_403() -> None:
    principal = Principal.for_subject("9", "partner")

    with pytest.raises(InsufficientScopeError):
        await require_operator(_operator_request(principal))


def test_operator_bearer_token_mints_the_operator_scope() -> None:
    # The token the session facade issues carries the operator scope claim, which
    # the gateway resolves to the singleton operator role - the seam the
    # route guard's admission depends on.
    _header, payload, _signature = _operator_token().split(".")
    import base64
    import json

    claims = json.loads(base64.urlsafe_b64decode(payload + "=="))
    assert claims["scope"] == "operator"
