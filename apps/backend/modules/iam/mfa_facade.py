"""MOD-001: MFA sub-facade for the operator second factor (T07, ticket #250).

The operator session is minted only after the MFA second factor completes
(``session_facade.issue_operator_session`` refuses without an enrolled,
verified ``iam_operator_mfa`` row). Two seams live here:

- ``enroll_mfa`` is the enrollment surface: it generates a fresh base32 TOTP
  secret, encrypts it at rest (AES-256-GCM, security-phii-standards S4/S5),
  persists the ciphertext in ``iam_operator_mfa.secret``, and returns the
  one-time plaintext secret + provisioning URI so the operator can add the
  factor to their authenticator app. Nothing else ever returns the plaintext.
- ``record_mfa_verified`` stamps ``last_verified_at`` on an existing
  enrollment. It deliberately never writes an empty/placeholder secret - an
  operator row is only ever created through ``enroll_mfa`` with a real
  encrypted secret (this fixes the Phase-5 review finding P1 where login
  always failed against a ``secret=""`` placeholder).

The TOTP code check itself (validating a live code against the encrypted
secret) is the operator console's login surface - ``session_facade`` reads
the encrypted secret this facade stored and verifies the code on the way to
minting a session. These seams are the session-facing contract that the
"second factor completed" flag is durable and attributed before a session can
be minted.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

import pyotp
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.ext.asyncio import AsyncEngine

from modules.iam.domain.exceptions import SessionIssuanceError
from modules.iam.domain.phone import normalize_phone
from modules.iam.domain.secret_encryption import encrypt_secret
from modules.iam.domain.shared import _identity_phone
from modules.iam.domain.totp import generate_secret
from modules.iam.schema.models import iam_identities, iam_operator_mfa

_OTP_ISSUER = "CareSetu"


class EnrollMfaResult(BaseModel):
    """Outcome of enrolling an operator's TOTP MFA factor (#272).

    ``secret`` is the base32 secret in plaintext - it is returned exactly
    once, here, so the operator can add the factor to their authenticator.
    ``provisioning_uri`` is the ``otpauth://`` URI an authenticator app
    imports (scan a QR of it). Only the encrypted ciphertext is ever stored.
    """

    identity_id: int
    phone_e164: str
    secret: str
    provisioning_uri: str


class VerifyMfaResult(BaseModel):
    """Outcome of recording a successful operator MFA verification (T07, #250).

    ``enrolled`` is True when the operator's MFA factor is enrolled and this
    call recorded a fresh ``last_verified_at``. Either way, after this call the
    operator satisfies the ``issue_operator_session`` MFA gate.
    """

    identity_id: int
    phone_e164: str
    enrolled: bool


def _default_clock() -> datetime:
    return datetime.now(UTC)


class MfaFacade:
    """MFA enrollment/verification recording for the operator second factor."""

    def __init__(
        self,
        engine: AsyncEngine,
        clock: Callable[[], datetime] = _default_clock,
        *,
        mfa_secret_key: str = "",
    ) -> None:
        self._engine = engine
        self._clock = clock
        self._mfa_secret_key = mfa_secret_key

    async def enroll_mfa(self, identity_id: int) -> EnrollMfaResult:
        """Enroll a TOTP MFA factor for an operator (P1, #272).

        Generates a fresh base32 secret, encrypts it at rest, and persists the
        ciphertext in ``iam_operator_mfa.secret`` (upserting on the unique
        ``identity_id``). The row is marked enrolled (``mfa_enabled``) with
        ``enrolled_at`` and ``last_verified_at`` stamped now, so the
        ``issue_operator_session`` gate is satisfied and the operator can
        immediately complete their first login with the presented code.

        The plaintext secret and its provisioning URI are returned exactly
        once, here, so the operator can add the factor to their authenticator;
        only the encrypted ciphertext is stored. An identity that does not
        exist (a stale token's subject) is refused - an operator MFA can only
        be enrolled against an identity an operator invited.
        """
        if not self._mfa_secret_key:
            raise SessionIssuanceError(
                "cannot enroll MFA: encryption key is not configured (set IAM_MFA_SECRET_KEY)"
            )
        now = self._clock()
        secret = generate_secret()
        encrypted_secret = encrypt_secret(secret, self._mfa_secret_key)

        async with self._engine.begin() as connection:
            phone = await _identity_phone(connection, identity_id)
            if not phone:
                raise SessionIssuanceError(
                    f"no identity {identity_id}; invite the operator before MFA enrollment"
                )
            await connection.execute(
                postgresql_insert(iam_operator_mfa)
                .values(
                    identity_id=identity_id,
                    secret=encrypted_secret,
                    mfa_enabled=True,
                    enrolled_at=now,
                    last_verified_at=now,
                )
                .on_conflict_do_update(
                    index_elements=["identity_id"],
                    set_={
                        "secret": encrypted_secret,
                        "mfa_enabled": True,
                        "enrolled_at": now,
                        "last_verified_at": now,
                    },
                )
            )

        provisioning_uri = _provisioning_uri(secret, name=phone)
        return EnrollMfaResult(
            identity_id=int(identity_id),
            phone_e164=phone,
            secret=secret,
            provisioning_uri=provisioning_uri,
        )

    async def record_mfa_verified(self, phone: str) -> VerifyMfaResult:
        """Record a successful operator MFA verification (T07, #250).

        Stamps ``last_verified_at`` (and ``mfa_enabled``) on the operator's
        existing ``iam_operator_mfa`` row. The TOTP secret is never touched
        here - it is written only by ``enroll_mfa`` with a real encrypted
        value, so this seam never persists an empty placeholder (P1, #272).
        A phone with no identity (never invited) or no enrollment yet is
        refused with ``SessionIssuanceError`` - there is nothing to record a
        verification against.
        """
        phone_e164 = normalize_phone(phone)

        async with self._engine.begin() as connection:
            identity_id = (
                await connection.execute(
                    select(iam_identities.c.id).where(iam_identities.c.phone_e164 == phone_e164)
                )
            ).scalar_one_or_none()
            if identity_id is None:
                raise SessionIssuanceError(
                    f"no identity for {phone_e164}; invite the operator before MFA"
                )
            enrolled = (
                await connection.execute(
                    select(iam_operator_mfa.c.id).where(
                        iam_operator_mfa.c.identity_id == identity_id
                    )
                )
            ).scalar_one_or_none()
            if enrolled is None:
                raise SessionIssuanceError(
                    f"identity {identity_id} has no enrolled MFA factor; enroll before recording"
                )
            now = self._clock()
            await connection.execute(
                iam_operator_mfa.update()
                .where(iam_operator_mfa.c.identity_id == identity_id)
                .values(mfa_enabled=True, last_verified_at=now)
            )

        return VerifyMfaResult(
            identity_id=int(identity_id),
            phone_e164=phone_e164,
            enrolled=True,
        )


def _provisioning_uri(secret: str, *, name: str) -> str:
    """The ``otpauth://`` provisioning URI for an authenticator to import."""
    return pyotp.TOTP(secret).provisioning_uri(name=name, issuer_name=_OTP_ISSUER)
