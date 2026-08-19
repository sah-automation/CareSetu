"""MOD-001: Identity sub-facade (ADR-0006, ticket #169).

Extracts the identity registration lifecycle from the coordinator
``IamFacade``: ``register_patient`` and its result model
``RegisterPatientResult``.  The sub-facade accepts an ``OtpSender`` port
(from ``domain/shared.py``) instead of adapter types, and imports
lockout/challenge helpers from ``domain/shared.py``.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.ext.asyncio import AsyncEngine

from bus.outbox_writer import write_outbox
from modules.iam.domain import events
from modules.iam.domain.exceptions import IamError
from modules.iam.domain.otp import (
    MAX_ATTEMPTS,
    OTP_TTL_SECONDS,
    RESEND_COOLDOWN_SECONDS,
)
from modules.iam.domain.phone import normalize_phone
from modules.iam.domain.resend import evaluate_resend
from modules.iam.domain.shared import (
    OtpSender as OtpSender,
)
from modules.iam.domain.shared import (
    _invalidate_pending_challenges,
    _issue_challenge,
    _latest_cooldown_until,
    _lock_identity_row,
)
from modules.iam.outbox import IAM_OUTBOX_TABLE
from modules.iam.schema.models import iam_identities

_IAM_SCHEMA = "iam"


class RegisterPatientResult(BaseModel):
    """Outcome of the begin-or-resume entry, as the PWA renders it (spec #51 sec 2.1/2.4).

    ``sent``: a challenge was issued (first-time registration or an
    out-of-cooldown login) and the challenge fields seed the countdown ring,
    the resend cooldown, and the attempts-left strip; ``is_existing``/``flow``
    tell the client which notice to show. ``cooldown``/``locked``/``suspended``:
    the entry was refused exactly like a resend - no fresh challenge was issued
    and no SMS was sent - and the PWA stays on the phone step with the matching
    countdown or lockout state. ``no_identity`` is impossible on this path: the
    single begin-or-resume entry always resolves to an identity.
    """

    outcome: Literal["sent", "cooldown", "locked", "suspended"]
    phone_e164: str
    identity_id: int
    challenge_id: int | None = None
    is_existing: bool
    flow: Literal["register", "login"]
    expires_in_seconds: int | None = None
    cooldown_remaining_seconds: int | None = None
    attempts_left: int | None = None
    lockout_remaining_seconds: int | None = None


def _default_clock() -> datetime:
    return datetime.now(UTC)


class IdentityFacade:
    """Identity sub-facade: registration and identity lifecycle (ADR-0006)."""

    def __init__(
        self,
        engine: AsyncEngine,
        otp_sender: OtpSender,
        clock: Callable[[], datetime] = _default_clock,
    ) -> None:
        self._engine = engine
        self._otp_sender = otp_sender
        self._clock = clock

    async def register_patient(self, phone: str) -> RegisterPatientResult:
        """Begin-or-resume: create the identity on first use, else resolve it.

        The phone is normalized server-side to +91 E.164 (the country code is
        never trusted from the client). Concurrency converges via the unique
        ``phone_e164`` index: ``INSERT ... ON CONFLICT DO NOTHING`` then a
        re-read, never SELECT-then-INSERT (spec #51 section 2.3). A new identity is
        created ``[Unverified]`` and emits ``patient.registered``; a repeat
        phone resolves to the existing identity (no duplicate).

        The existing-phone login branch enforces the same anti-spam gate as a
        resend (spec #51 section 2.4, ADR-0004): while the phone is inside the >= 60 s
        resend cooldown measured from the last issuance, in the brute-force
        lockout, or ``Suspended``, the entry is refused - no fresh challenge is
        issued, no ``otp.sent`` is written, and no SMS is sent - so an attacker
        cannot defeat the cooldown by calling register repeatedly or poke a
        locked phone back into the OTP flow. The identity row is locked
        ``FOR UPDATE`` so the refusal reads stable guard state and concurrent
        writers serialize. First-time registration and out-of-cooldown login
        share the resend's latest-wins issuance: the pending challenge is
        invalidated before a fresh hashed one is issued (the old code can no
        longer verify), ``otp.sent`` lands in the iam outbox in the same
        transaction as the change, and the EXT-001 adapter delivers it as a
        background task afterwards - the request never blocks on the provider
        (PHASE-2 REM T4, #86).
        """
        phone_e164 = normalize_phone(phone)
        now = self._clock()

        async with self._engine.begin() as connection:
            inserted = await connection.execute(
                postgresql_insert(iam_identities)
                .values(phone_e164=phone_e164)
                .on_conflict_do_nothing(index_elements=["phone_e164"])
            )
            is_new = inserted.rowcount == 1
            if is_new:
                identity_id = (
                    await connection.execute(
                        select(iam_identities.c.id).where(iam_identities.c.phone_e164 == phone_e164)
                    )
                ).scalar_one()
                await write_outbox(
                    connection,
                    _IAM_SCHEMA,
                    IAM_OUTBOX_TABLE,
                    events.patient_registered_envelope(identity_id, phone_e164),
                )
            else:
                locked = await _lock_identity_row(
                    connection, iam_identities.c.phone_e164 == phone_e164
                )
                if locked is None:
                    raise IamError("existing identity disappeared between the insert and the lock")
                identity_id = locked.identity_id
                identity_status = locked.status
                lockout_until = locked.lockout_until
                latest_cooldown_until = await _latest_cooldown_until(connection, identity_id)
                decision = evaluate_resend(
                    identity_status=identity_status,
                    lockout_until=lockout_until,
                    cooldown_until=latest_cooldown_until,
                    now=now,
                )
                if decision.outcome != "sent":
                    return RegisterPatientResult(
                        outcome=decision.outcome,
                        phone_e164=phone_e164,
                        identity_id=identity_id,
                        is_existing=True,
                        flow="login",
                        cooldown_remaining_seconds=decision.cooldown_remaining_seconds,
                        lockout_remaining_seconds=decision.lockout_remaining_seconds,
                    )
                await _invalidate_pending_challenges(connection, identity_id)
            challenge_id, otp = await _issue_challenge(
                connection,
                identity_id=identity_id,
                phone_e164=phone_e164,
                now=now,
            )

        await self._otp_sender(phone_e164, otp)

        return RegisterPatientResult(
            outcome="sent",
            phone_e164=phone_e164,
            identity_id=identity_id,
            challenge_id=challenge_id,
            is_existing=not is_new,
            flow="login" if not is_new else "register",
            expires_in_seconds=OTP_TTL_SECONDS,
            cooldown_remaining_seconds=RESEND_COOLDOWN_SECONDS,
            attempts_left=MAX_ATTEMPTS,
        )
