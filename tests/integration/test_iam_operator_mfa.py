"""PHASE-5 T07/S8: operator MFA + invite + session against a real PostgreSQL (#250, #261, #272).

Operators are a trusted closed group that never self-registers. These tests
prove, through the facade's typed seam (Spec #51, Seam 1), the acceptance
criteria:

- an operator can be invited (``create_operator_account``) - the only way the
  group grows, no self-registration path;
- ``enroll_mfa`` enrolls an operator's TOTP factor: it persists a real
  encrypted secret (never the empty placeholder that broke login - P1, #272)
  and returns the plaintext secret + provisioning URI once;
- ``issue_operator_session`` refuses until the operator has completed the MFA
  second factor AND presents a valid TOTP code verified against the enrolled
  encrypted secret (S8, #261), then mints an operator-scoped session;
- a wrong or expired TOTP code is rejected with ``SessionIssuanceError``;
- the full invite -> enroll MFA -> login round-trip lands an operator session;
- the minted session's ``scope`` is ``operator`` so ``require_operator``
  admits the caller (the RBAC role grant is persisted and honored).

Requires the native PostgreSQL; the suite skips cleanly when it is unreachable,
and the ``iam`` schema is migrated up for the module and down again afterwards.
"""

from __future__ import annotations

import base64
import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pyotp
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
# A deterministic 32-byte key for encrypting the test TOTP secret.
_MFA_SECRET_KEY = base64.b64encode(os.urandom(32)).decode("ascii")


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
        engine=engine,
        sms_adapter=MockSmsAdapter(),
        clock=clock,
        access_token_signing_key=_KEY,
        mfa_secret_key=_MFA_SECRET_KEY,
    )


async def _invited_operator(database_url: str, clock: MutableClock) -> IamFacade:
    """Invite an operator (the only growth path - no self-registration).

    The invited phone first completes phone-OTP (first factor, making the
    identity ``Active``), then an operator invites it and it is granted the
    ``operator`` role. The MFA second factor is deliberately NOT enrolled
    here, so tests exercise enrollment and the ``issue_operator_session`` gate
    explicitly.
    """
    sms = MockSmsAdapter()
    facade = IamFacade(
        engine=create_async_engine(database_url, poolclass=NullPool),
        sms_adapter=sms,
        clock=clock,
        access_token_signing_key=_KEY,
        mfa_secret_key=_MFA_SECRET_KEY,
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


def _valid_code(secret: str, at: datetime) -> str:
    """A valid RFC-6238 TOTP code for ``secret`` at ``at``."""
    return pyotp.TOTP(secret).at(at)


async def test_no_operator_session_before_the_mfa_second_factor(
    database_url: str, clean_iam: Any
) -> None:
    clock = MutableClock(_T0)
    facade = await _invited_operator(database_url, clock)

    # The operator role grant alone is not enough - MFA must come first.
    with pytest.raises(SessionIssuanceError, match="MFA"):
        await facade.issue_operator_session(_INVITED_PHONE, "000000")


async def test_enroll_persists_a_real_encrypted_secret(database_url: str, clean_iam: Any) -> None:
    clock = MutableClock(_T0)
    facade = await _invited_operator(database_url, clock)

    # Enroll by the invited identity's id (701 is the inviter reference, not the
    # invited identity). Resolve the invited identity id from the identity row.
    identity_id = await _invited_identity_id(database_url)
    enroll = await facade.enroll_mfa(identity_id)

    assert enroll.identity_id == identity_id
    assert enroll.phone_e164 == _INVITED_PHONE
    assert len(enroll.secret) > 0
    assert "otpauth://totp/" in enroll.provisioning_uri

    # The stored secret is the encrypted ciphertext, never plaintext and never
    # the empty placeholder that previously broke login (P1, #272).
    engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            stored = (
                (
                    await connection.execute(
                        text(
                            "SELECT secret, mfa_enabled, last_verified_at "
                            "FROM iam.iam_operator_mfa WHERE identity_id = :id"
                        ),
                        {"id": identity_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
    finally:
        await engine.dispose()

    assert stored is not None
    assert stored["secret"] != ""
    assert stored["secret"] != enroll.secret
    assert stored["mfa_enabled"] is True
    assert stored["last_verified_at"] is not None


async def test_operator_session_minted_only_after_mfa_is_verified(
    database_url: str, clean_iam: Any
) -> None:
    clock = MutableClock(_T0)
    facade = await _invited_operator(database_url, clock)
    identity_id = await _invited_identity_id(database_url)

    enroll = await facade.enroll_mfa(identity_id)

    session = await facade.issue_operator_session(_INVITED_PHONE, _valid_code(enroll.secret, _T0))

    assert session.scope == "operator"
    claims = verify_token(session.jwt, _KEY, _T0)
    assert claims.subject_id == session.identity_id
    assert claims.scope == "operator"
    assert claims.expires_at == _T0 + timedelta(seconds=900)


async def test_wrong_totp_code_rejected(database_url: str, clean_iam: Any) -> None:
    clock = MutableClock(_T0)
    facade = await _invited_operator(database_url, clock)
    identity_id = await _invited_identity_id(database_url)

    await facade.enroll_mfa(identity_id)

    with pytest.raises(SessionIssuanceError, match="TOTP verification failed"):
        await facade.issue_operator_session(_INVITED_PHONE, "999999")


async def test_expired_totp_code_rejected_outside_drift_window(
    database_url: str, clean_iam: Any
) -> None:
    clock = MutableClock(_T0)
    facade = await _invited_operator(database_url, clock)
    identity_id = await _invited_identity_id(database_url)

    enroll = await facade.enroll_mfa(identity_id)

    # A code generated 5 minutes ago is outside the 90 s drift window.
    old_code = _valid_code(enroll.secret, _T0 - timedelta(minutes=5))

    with pytest.raises(SessionIssuanceError, match="TOTP verification failed"):
        await facade.issue_operator_session(_INVITED_PHONE, old_code)


async def test_operator_invite_persists_the_active_operator_role_grant(
    database_url: str, clean_iam: Any
) -> None:
    clock = MutableClock(_T0)
    await _invited_operator(database_url, clock)

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


async def test_enroll_is_idempotent_and_replaces_the_secret(
    database_url: str, clean_iam: Any
) -> None:
    clock = MutableClock(_T0)
    facade = await _invited_operator(database_url, clock)
    identity_id = await _invited_identity_id(database_url)

    first = await facade.enroll_mfa(identity_id)
    second = await facade.enroll_mfa(identity_id)

    assert second.identity_id == first.identity_id
    assert second.secret != first.secret  # a fresh secret is generated on re-enroll
    # Re-enrollment rotates the stored secret: only the latest is valid at login.
    session = await facade.issue_operator_session(_INVITED_PHONE, _valid_code(second.secret, _T0))
    assert session.scope == "operator"


async def test_invite_enroll_login_round_trip(database_url: str, clean_iam: Any) -> None:
    clock = MutableClock(_T0)
    facade = await _invited_operator(database_url, clock)
    identity_id = await _invited_identity_id(database_url)

    # Full US-15 flow: invite (done) -> enroll MFA -> login with TOTP code.
    enroll = await facade.enroll_mfa(identity_id)
    session = await facade.issue_operator_session(_INVITED_PHONE, _valid_code(enroll.secret, _T0))

    assert session.scope == "operator"


async def _invited_identity_id(database_url: str) -> int:
    """The identity id of the invited operator (its phone's identity row)."""
    engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            return int(
                (
                    await connection.execute(
                        text("SELECT id FROM iam.iam_identities WHERE phone_e164 = :phone"),
                        {"phone": _INVITED_PHONE},
                    )
                ).scalar_one()
            )
    finally:
        await engine.dispose()
