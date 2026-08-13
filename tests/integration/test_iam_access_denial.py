"""PHASE-2 REM T7: access-denial attempts emit patient.auth_failed (ticket #87).

Against a real PostgreSQL: an authenticated caller refused on the protected
route (insufficient scope / missing role) gets the 403 envelope and writes
``patient.auth_failed`` (reason ``access_denied``) to the iam outbox in its own
transaction, naming the correct identity and phone. Anonymous 401s - no
identity to attribute - stay log-only and never touch the outbox, the
documented boundary. Requires the native PostgreSQL; the suite skips cleanly
when it is unreachable, and the ``iam`` schema is migrated up for the module
and down again afterwards.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import Settings
from app.main import create_app
from modules.iam.adapters.sms import MockSmsAdapter
from modules.iam.domain.jwt import issue_token
from modules.iam.facade import IamFacade

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "apps" / "backend" / "alembic.ini"

_PHONE = "+919876543210"
_T0 = datetime(2026, 8, 13, 12, 0, 0, tzinfo=UTC)
_KEY = "integration-test-signing-key"


class FixedClock:
    """Clock stand-in so token issuance and expiry are deterministic."""

    def __init__(self, now: datetime) -> None:
        self._now = now

    def __call__(self) -> datetime:
        return self._now


def _alembic_config(database_url: str) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


@pytest.fixture(scope="module")
def iam_schema(database_url: str) -> Iterator[None]:
    """Migrate the ``iam`` schema to head for the module, restore base after."""
    config = _alembic_config(database_url)
    try:
        command.upgrade(config, "head")
    except Exception as exc:
        pytest.skip(f"PostgreSQL unreachable at {database_url} - {exc}")
    yield
    command.downgrade(config, "base")


@pytest_asyncio.fixture
async def clean_iam(database_url: str, iam_schema: None) -> Iterator[None]:
    """Empty the iam tables before every test so they start from a clean slate."""
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "TRUNCATE TABLE iam.iam_identities, iam.iam_otp_challenges, "
                    "iam.iam_role_grants, iam.iam_sessions, iam.iam_outbox CASCADE"
                )
            )
    finally:
        await engine.dispose()
    yield


async def _query(database_url: str, sql: str) -> list[dict[str, Any]]:
    engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(text(sql))
            return [dict(row) for row in result.mappings().all()]
    finally:
        await engine.dispose()


async def _verified_session(database_url: str) -> IamFacade:
    """A verified patient facade holding a patient-scoped access JWT."""
    sms = MockSmsAdapter()
    facade = IamFacade(
        engine=create_async_engine(database_url, poolclass=NullPool),
        sms_adapter=sms,
        clock=FixedClock(_T0),
        access_token_signing_key=_KEY,
    )
    await facade.register_patient("9876543210")
    await facade.delivery_queue.flush()
    sent = sms.last_sent_code(_PHONE)
    assert sent is not None and len(sent) == 6
    assert (await facade.verify_otp("9876543210", sent)).outcome == "verified"
    return facade


def _token_for(subject_id: int, scope: str) -> str:
    """An access JWT minted exactly like ``issue_session`` does, for any scope.

    ``now`` is the real clock: the app facade validates tokens against
    ``datetime.now(UTC)`` (the default clock), so a ``_T0``-minted token would
    already be expired.
    """
    return issue_token(
        jti=uuid.uuid4().hex,
        subject_id=subject_id,
        scope=scope,
        signing_key=_KEY,
        now=datetime.now(UTC),
    )


def _app_client(database_url: str) -> TestClient:
    app = create_app(
        settings=Settings(
            database_url=database_url,
            gateway_jwt_verify_enabled=True,
            gateway_jwt_signing_key=_KEY,
        )
    )
    return TestClient(app)


async def test_authenticated_403_writes_access_denied_to_the_outbox(
    database_url: str, clean_iam: Any
) -> None:
    facade = await _verified_session(database_url)
    session = await facade.issue_session("9876543210")
    client = _app_client(database_url)

    response = client.get(
        "/v1/me",
        headers={"Authorization": f"Bearer {_token_for(session.identity_id, 'superadmin')}"},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_INSUFFICIENT_SCOPE"
    rows = await _query(
        database_url,
        "SELECT event_type, payload FROM iam.iam_outbox WHERE event_type = 'patient.auth_failed'",
    )
    assert rows == [
        {
            "event_type": "patient.auth_failed",
            "payload": {
                "identity_id": session.identity_id,
                "phone_e164": _PHONE,
                "reason": "access_denied",
                "attempts_left": None,
            },
        }
    ]


async def test_anonymous_401_writes_no_outbox_row(database_url: str, clean_iam: Any) -> None:
    client = _app_client(database_url)

    response = client.get("/v1/me")

    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_UNAUTHENTICATED"
    assert await _query(database_url, "SELECT id FROM iam.iam_outbox") == []


async def test_presented_invalid_token_401_writes_no_outbox_row(
    database_url: str, clean_iam: Any
) -> None:
    client = _app_client(database_url)

    response = client.get("/v1/me", headers={"Authorization": "Bearer not-a-jws"})

    assert response.status_code == 401
    assert await _query(database_url, "SELECT id FROM iam.iam_outbox") == []
