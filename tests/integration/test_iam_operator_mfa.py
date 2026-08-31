"""PHASE-5 T07: operator MFA + invite + session against a real PostgreSQL (#250).

Operators are a trusted closed group that never self-registers. These tests
prove, through the facade's typed seam (Spec #51, Seam 1), the acceptance
criteria:

- an operator can be invited (``create_operator_account``) - the only way the
  group grows, no self-registration path;
- ``issue_operator_session`` refuses until the operator has completed the MFA
  second factor (``record_mfa_verified``), then mints an operator-scoped
  session;
- the minted session's ``scope`` is ``operator`` so ``require_operator``
  admits the caller (the RBAC role grant is persisted and honored).

Requires the native PostgreSQL; the suite skips cleanly when it is unreachable,
and the ``iam`` schema is migrated up for the module and down again afterwards.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from modules.iam.adapters.sms import MockSmsAdapter
from modules.iam.domain.exceptions import SessionIssuanceError
from modules.iam.domain.jwt import verify_token
from modules.iam.facade import IamFacade

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "apps" / "backend" / "alembic.ini"

_INVITED_PHONE = "+919111111111"
_T0 = datetime(2026, 8, 31, 12, 0, 0, tzinfo=UTC)
_KEY = "integration-test-operator-key"


class MutableClock:
    """Clock stand-in tests advance to walk the access-token expiry window."""

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
                    "iam.iam_role_grants, iam.iam_sessions, iam.iam_operator_mfa, "
                    "iam.iam_outbox CASCADE"
                )
            )
    finally:
        await engine.dispose()
    yield


def _facade(database_url: str, clock: MutableClock) -> IamFacade:
    engine = create_async_engine(database_url, poolclass=NullPool)
    return IamFacade(
        engine=engine, sms_adapter=MockSmsAdapter(), clock=clock, access_token_signing_key=_KEY
    )


async def _invited_facade(database_url: str, clock: MutableClock) -> IamFacade:
    """Invite an operator (the only growth path - no self-registration).

    The invited phone first completes phone-OTP (first factor, making the
    identity ``Active``), then an operator invites it and it is granted the
    ``operator`` role. The MFA second factor is deliberately NOT recorded
    here, so tests exercise the ``issue_operator_session`` gate explicitly.
    """
    sms = MockSmsAdapter()
    facade = IamFacade(
        engine=create_async_engine(database_url, poolclass=NullPool),
        sms_adapter=sms,
        clock=clock,
        access_token_signing_key=_KEY,
    )
    await facade.register_patient(_INVITED_PHONE)
    await facade.delivery_queue.flush()
    sent = sms.last_sent_code(_INVITED_PHONE)
    assert sent is not None and len(sent) == 6
    result = await facade.verify_otp(_INVITED_PHONE, sent)
    assert result.outcome == "verified"
    invited = await facade.create_operator_account(_INVITED_PHONE, invited_by_identity_id=701)
    assert invited.phone_e164 == _INVITED_PHONE
    return facade


async def test_no_operator_session_before_the_mfa_second_factor(
    database_url: str, clean_iam: Any
) -> None:
    clock = MutableClock(_T0)
    facade = await _invited_facade(database_url, clock)

    # The operator role grant alone is not enough - MFA must come first.
    with pytest.raises(SessionIssuanceError, match="MFA"):
        await facade.issue_operator_session(_INVITED_PHONE)


async def test_operator_session_minted_only_after_mfa_is_verified(
    database_url: str, clean_iam: Any
) -> None:
    clock = MutableClock(_T0)
    facade = await _invited_facade(database_url, clock)

    await facade.record_mfa_verified(_INVITED_PHONE)

    session = await facade.issue_operator_session(_INVITED_PHONE)

    assert session.scope == "operator"
    claims = verify_token(session.jwt, _KEY, _T0)
    assert claims.subject_id == session.identity_id
    assert claims.scope == "operator"
    assert claims.expires_at == _T0 + timedelta(seconds=900)


async def test_operator_invite_persists_the_active_operator_role_grant(
    database_url: str, clean_iam: Any
) -> None:
    clock = MutableClock(_T0)
    await _invited_facade(database_url, clock)

    engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            rows = (
                (
                    await connection.execute(
                        text(
                            "SELECT iam.iam_role_grants.role, iam.iam_role_grants.status "
                            "FROM iam.iam_role_grants "
                            "JOIN iam.iam_identities "
                            "ON iam.iam_role_grants.identity_id = iam.iam_identities.id "
                            "WHERE iam.iam_identities.phone_e164 = :phone"
                        ),
                        {"phone": _INVITED_PHONE},
                    )
                )
                .mappings()
                .all()
            )
    finally:
        await engine.dispose()

    rights = [dict(r) for r in rows]
    # The invited phone also carries a patient grant from its OTP verification;
    # the operator grant is what this ticket adds and what require_operator admits on.
    assert {"role": "operator", "status": "Active"} in rights


async def test_mfa_recording_is_idempotent(database_url: str, clean_iam: Any) -> None:
    clock = MutableClock(_T0)
    facade = await _invited_facade(database_url, clock)

    first = await facade.record_mfa_verified(_INVITED_PHONE)
    second = await facade.record_mfa_verified(_INVITED_PHONE)

    assert first.newly_enrolled is True
    assert second.newly_enrolled is False
    assert second.enrolled is True
    await facade.issue_operator_session(_INVITED_PHONE)
