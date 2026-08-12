"""MOD-001 Identity and access management: typed public sync API.

The only legal cross-module import target for the ``iam`` module
(coding-standards §2, ADR-0003). Phase 2 T3 (#54) implements the begin-or-
resume entry point ``register_patient``; T4 (#55) adds the verification
challenge machine ``verify_otp``; the remaining typed methods arrive with
their Phase 2 tickets.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

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
from modules.iam.domain.verify import (
    CHALLENGE_VERIFIED,
    IDENTITY_ACTIVE,
    IDENTITY_SUSPENDED,
    AttemptDecision,
    evaluate_attempt,
    failure_write_back,
    no_challenge_decision,
    suspended_decision,
)
from modules.iam.outbox import IAM_OUTBOX_TABLE
from modules.iam.schema.models import iam_identities, iam_otp_challenges, iam_role_grants

_IAM_SCHEMA = "iam"
_PATIENT_ROLE = "patient"


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


class VerifyOtpResult(BaseModel):
    """Outcome of submitting a 6-digit code, as the PWA renders it (spec #51 §2.4).

    ``verified``: the challenge was consumed, the identity is Active, and the
    patient role is granted. ``wrong_code``: the budget was decremented and
    ``attempts_left`` is the remaining budget. ``expired``/``spent``: the
    challenge is unusable and the PWA shows "request a new code".
    """

    outcome: Literal["verified", "wrong_code", "expired", "spent"]
    phone_e164: str
    identity_id: int | None = None
    attempts_left: int | None = None


def _default_clock() -> datetime:
    return datetime.now(UTC)


class IamFacade:
    """Typed public facade for iam (Phase 2: registration + OTP verify)."""

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

    async def verify_otp(self, phone: str, otp: str) -> VerifyOtpResult:
        """Verify a submitted 6-digit code against the identity's latest challenge.

        A correct code consumes the challenge (single-use), transitions the
        identity ``[Unverified] -> [Active]``, grants the patient role
        idempotently, and writes ``patient.verified`` to the outbox in the same
        transaction (spec #51 §2.4/§2.6). Wrong guesses decrement the 5-attempt
        budget without killing the code; at 0 the challenge is spent. Expired,
        spent, or already-used challenges reject with a "request a new code"
        outcome. Every rejection writes ``patient.auth_failed`` in the same
        transaction; success never does.

        The identity row is locked ``FOR UPDATE`` so concurrent verifications
        for the same phone serialize: the challenge can be consumed exactly
        once and the role grant stays unique.
        """
        phone_e164 = normalize_phone(phone)
        now = self._clock()

        async with self._engine.begin() as connection:
            locked = await self._lock_identity(connection, phone_e164)
            if locked is None:
                return await self._reject_no_challenge(connection, phone_e164, identity_id=None)
            identity_id, identity_status = locked

            if identity_status == IDENTITY_SUSPENDED:
                return await self._reject_suspended(connection, phone_e164, identity_id)

            challenge = (
                (
                    await connection.execute(
                        select(
                            iam_otp_challenges.c.id,
                            iam_otp_challenges.c.otp_hash,
                            iam_otp_challenges.c.status,
                            iam_otp_challenges.c.attempts,
                            iam_otp_challenges.c.expires_at,
                        )
                        .where(iam_otp_challenges.c.identity_id == identity_id)
                        .order_by(iam_otp_challenges.c.id.desc())
                        .limit(1)
                    )
                )
                .mappings()
                .first()
            )

            if challenge is None:
                return await self._reject_no_challenge(connection, phone_e164, identity_id)

            decision = evaluate_attempt(
                status=challenge["status"],
                attempts=challenge["attempts"],
                expires_at=challenge["expires_at"],
                now=now,
                guess=otp,
                stored_hash=challenge["otp_hash"],
            )

            if decision.outcome == "verified":
                await connection.execute(
                    iam_otp_challenges.update()
                    .where(iam_otp_challenges.c.id == challenge["id"])
                    .values(status=CHALLENGE_VERIFIED, verified_at=now)
                )
                await connection.execute(
                    iam_identities.update()
                    .where(iam_identities.c.id == identity_id)
                    .values(status=IDENTITY_ACTIVE, updated_at=now)
                )
                await self._grant_patient_role(connection, identity_id)
                await write_outbox(
                    connection,
                    _IAM_SCHEMA,
                    IAM_OUTBOX_TABLE,
                    events.patient_verified_envelope(identity_id, phone_e164),
                )
                return VerifyOtpResult(
                    outcome="verified", phone_e164=phone_e164, identity_id=identity_id
                )

            await self._record_failure(
                connection,
                challenge_id=challenge["id"],
                status=challenge["status"],
                attempts=challenge["attempts"],
                decision=decision,
            )
            await write_outbox(
                connection,
                _IAM_SCHEMA,
                IAM_OUTBOX_TABLE,
                events.patient_auth_failed_envelope(
                    identity_id=identity_id,
                    phone_e164=phone_e164,
                    reason=decision.reason or "expired",
                    attempts_left=decision.attempts_left,
                ),
            )
            return VerifyOtpResult(
                outcome=decision.outcome,
                phone_e164=phone_e164,
                identity_id=identity_id,
                attempts_left=decision.attempts_left,
            )

    @staticmethod
    async def _lock_identity(
        connection: AsyncConnection, phone_e164: str
    ) -> tuple[int, str] | None:
        """Row-lock the identity for ``phone_e164`` and return its id and status.

        ``FOR UPDATE`` serializes every verification for one phone so the
        challenge can be consumed exactly once and the role grant stays unique
        under concurrency (spec #51 §2.4 single-use). The status is read under
        the same lock so the Suspended guard sees a stable value.
        """
        row = (
            (
                await connection.execute(
                    select(iam_identities.c.id, iam_identities.c.status)
                    .where(iam_identities.c.phone_e164 == phone_e164)
                    .with_for_update()
                )
            )
            .mappings()
            .first()
        )
        return None if row is None else (row["id"], row["status"])

    @staticmethod
    async def _grant_patient_role(connection: AsyncConnection, identity_id: int) -> None:
        """Grant the patient role idempotently; safe under the identity lock."""
        existing = (
            await connection.execute(
                select(iam_role_grants.c.id).where(
                    iam_role_grants.c.identity_id == identity_id,
                    iam_role_grants.c.role == _PATIENT_ROLE,
                    iam_role_grants.c.status == "Active",
                )
            )
        ).first()
        if existing is None:
            await connection.execute(
                iam_role_grants.insert().values(
                    identity_id=identity_id, role=_PATIENT_ROLE, status="Active"
                )
            )

    @staticmethod
    async def _reject_no_challenge(
        connection: AsyncConnection,
        phone_e164: str,
        identity_id: int | None,
    ) -> VerifyOtpResult:
        """Reject a verification with no live challenge: "request a new code".

        Covers a phone never registered (``identity_id`` is ``None``) and an
        identity with no challenge row yet. Writes ``patient.auth_failed`` in
        the same transaction as the rejection.
        """
        decision = no_challenge_decision()
        await write_outbox(
            connection,
            _IAM_SCHEMA,
            IAM_OUTBOX_TABLE,
            events.patient_auth_failed_envelope(
                identity_id=identity_id,
                phone_e164=phone_e164,
                reason=decision.reason or "expired",
                attempts_left=decision.attempts_left,
            ),
        )
        return VerifyOtpResult(
            outcome=decision.outcome, phone_e164=phone_e164, identity_id=identity_id
        )

    @staticmethod
    async def _reject_suspended(
        connection: AsyncConnection,
        phone_e164: str,
        identity_id: int,
    ) -> VerifyOtpResult:
        """Reject verification for a Suspended identity without touching the challenge.

        ``Suspended`` is reachable only via the operator status-change interface
        (spec #51 §2.4), so no OTP can move the identity out of it; the attempt
        is refused with a "request a new code" outcome and ``patient.auth_failed``
        in the same transaction.
        """
        decision = suspended_decision()
        await write_outbox(
            connection,
            _IAM_SCHEMA,
            IAM_OUTBOX_TABLE,
            events.patient_auth_failed_envelope(
                identity_id=identity_id,
                phone_e164=phone_e164,
                reason=decision.reason or "expired",
                attempts_left=decision.attempts_left,
            ),
        )
        return VerifyOtpResult(
            outcome=decision.outcome, phone_e164=phone_e164, identity_id=identity_id
        )

    @staticmethod
    async def _record_failure(
        connection: AsyncConnection,
        *,
        challenge_id: int,
        status: str,
        attempts: int,
        decision: AttemptDecision,
    ) -> None:
        """Persist a rejected attempt via the challenge machine's write-back."""
        write_back = failure_write_back(decision, status=status, attempts=attempts)
        values: dict[str, object] = {}
        if write_back.attempts is not None:
            values["attempts"] = write_back.attempts
        if write_back.status is not None:
            values["status"] = write_back.status
        if values:
            await connection.execute(
                iam_otp_challenges.update()
                .where(iam_otp_challenges.c.id == challenge_id)
                .values(**values)
            )
