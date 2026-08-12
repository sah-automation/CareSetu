"""MOD-001 Identity and access management: typed public sync API.

The only legal cross-module import target for the ``iam`` module
(coding-standards §2, ADR-0003). Phase 2 T3 (#54) implements the begin-or-
resume entry point ``register_patient``; the remaining typed methods arrive
with their Phase 2 tickets.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.ext.asyncio import AsyncEngine

from bus.outbox_writer import write_outbox
from modules.iam.adapters.sms import SmsAdapter, SmsSendRequest, SmsTemplateParams
from modules.iam.domain import events
from modules.iam.domain.otp import (
    MAX_ATTEMPTS,
    OTP_TTL_SECONDS,
    RESEND_COOLDOWN_SECONDS,
    generate_otp,
    hash_otp,
)
from modules.iam.domain.phone import normalize_phone
from modules.iam.outbox import IAM_OUTBOX_TABLE
from modules.iam.schema.models import iam_identities, iam_otp_challenges

_IAM_SCHEMA = "iam"


class RegisterPatientResult(BaseModel):
    """Flow state the PWA drives after ``register_patient`` (spec #51 §1, #51 §2.1).

    ``is_existing``/``flow`` tell the client which notice to show (the
    duplicate notice vs first-time), and the challenge fields seed the
    countdown ring, the resend cooldown, and the attempts-left strip.
    """

    phone_e164: str
    identity_id: int
    challenge_id: int
    is_existing: bool
    flow: Literal["register", "login"]
    expires_in_seconds: int
    cooldown_remaining_seconds: int
    attempts_left: int


def _default_clock() -> datetime:
    return datetime.now(UTC)


class IamFacade:
    """Typed public facade for iam (Phase 2: registration + OTP issuance)."""

    def __init__(
        self,
        engine: AsyncEngine,
        sms_adapter: SmsAdapter,
        clock: Callable[[], datetime] = _default_clock,
    ) -> None:
        self._engine = engine
        self._sms = sms_adapter
        self._clock = clock

    async def register_patient(self, phone: str) -> RegisterPatientResult:
        """Begin-or-resume: create the identity on first use, else resolve it.

        The phone is normalized server-side to +91 E.164 (the country code is
        never trusted from the client). Concurrency converges via the unique
        ``phone_e164`` index: ``INSERT ... ON CONFLICT DO NOTHING`` then a
        re-read, never SELECT-then-INSERT (spec #51 §2.3). A new identity is
        created ``[Unverified]`` and emits ``patient.registered``; a repeat
        phone resolves to the existing identity (no duplicate) and emits only
        a login ``otp.sent``. The challenge is hashed at rest, and both events
        land in the iam outbox in the same transaction as the change.
        """
        phone_e164 = normalize_phone(phone)
        now = self._clock()
        otp = generate_otp()
        expires_at = now + timedelta(seconds=OTP_TTL_SECONDS)
        cooldown_until = now + timedelta(seconds=RESEND_COOLDOWN_SECONDS)

        async with self._engine.begin() as connection:
            inserted = await connection.execute(
                postgresql_insert(iam_identities)
                .values(phone_e164=phone_e164)
                .on_conflict_do_nothing(index_elements=["phone_e164"])
            )
            identity_id = (
                await connection.execute(
                    select(iam_identities.c.id).where(iam_identities.c.phone_e164 == phone_e164)
                )
            ).scalar_one()
            is_new = inserted.rowcount == 1
            if is_new:
                await write_outbox(
                    connection,
                    _IAM_SCHEMA,
                    IAM_OUTBOX_TABLE,
                    events.patient_registered_envelope(identity_id, phone_e164),
                )
            challenge_id = (
                await connection.execute(
                    iam_otp_challenges.insert()
                    .values(
                        identity_id=identity_id,
                        otp_hash=hash_otp(otp),
                        status="Pending",
                        attempts=0,
                        expires_at=expires_at,
                        cooldown_until=cooldown_until,
                    )
                    .returning(iam_otp_challenges.c.id)
                )
            ).scalar_one()
            await write_outbox(
                connection,
                _IAM_SCHEMA,
                IAM_OUTBOX_TABLE,
                events.otp_sent_envelope(identity_id, challenge_id, expires_at),
            )

        await self._sms.send(
            SmsSendRequest(phone_e164=phone_e164, params=SmsTemplateParams(otp=otp))
        )

        return RegisterPatientResult(
            phone_e164=phone_e164,
            identity_id=identity_id,
            challenge_id=challenge_id,
            is_existing=not is_new,
            flow="login" if not is_new else "register",
            expires_in_seconds=OTP_TTL_SECONDS,
            cooldown_remaining_seconds=RESEND_COOLDOWN_SECONDS,
            attempts_left=MAX_ATTEMPTS,
        )
