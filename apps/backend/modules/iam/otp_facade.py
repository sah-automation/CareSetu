"""MOD-001: OTP sub-facade (ADR-0006, ticket #168).

Extracts the OTP challenge lifecycle from the coordinator ``IamFacade``:
``verify_otp`` and ``resend_otp`` with their result models.  The sub-facade
accepts an ``OtpSender`` port (from ``domain/shared.py``) instead of adapter
types, and imports lockout/challenge helpers from ``domain/shared.py``.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from bus.outbox_writer import write_outbox
from modules.iam.domain import events
from modules.iam.domain.lockout import evaluate_failure, lockout_remaining_seconds
from modules.iam.domain.otp import (
    MAX_ATTEMPTS,
    OTP_TTL_SECONDS,
    RESEND_COOLDOWN_SECONDS,
)
from modules.iam.domain.phone import normalize_phone
from modules.iam.domain.resend import evaluate_resend
from modules.iam.domain.shared import (
    _PATIENT_ROLE,
    IdentityGuardState,
    OtpSender,
    _invalidate_pending_challenges,
    _issue_challenge,
    _latest_cooldown_until,
    _lock_identity_row,
)
from modules.iam.domain.verify import (
    CHALLENGE_VERIFIED,
    IDENTITY_ACTIVE,
    IDENTITY_SUSPENDED,
    AttemptDecision,
    evaluate_attempt,
    failure_write_back,
    locked_decision,
    no_challenge_decision,
    suspended_decision,
)
from modules.iam.outbox import IAM_OUTBOX_TABLE
from modules.iam.schema.models import (
    iam_identities,
    iam_otp_challenges,
    iam_role_grants,
)

_IAM_SCHEMA = "iam"


class VerifyOtpResult(BaseModel):
    """Outcome of submitting a 6-digit code, as the PWA renders it (spec #51 section 2.4).

    ``verified``: the challenge was consumed, the identity is Active, and the
    patient role is granted. ``wrong_code``: the budget was decremented and
    ``attempts_left`` is the remaining budget. ``expired``/``spent``: the
    challenge is unusable and the PWA shows "request a new code". ``locked``:
    the brute-force lockout is active (either just triggered by this attempt or
    already running) and ``lockout_remaining_seconds`` is how long it lasts.
    """

    outcome: Literal["verified", "wrong_code", "expired", "spent", "locked"]
    phone_e164: str
    identity_id: int | None = None
    attempts_left: int | None = None
    lockout_remaining_seconds: int | None = None


class ResendOtpResult(BaseModel):
    """Outcome of requesting a fresh code, as the PWA renders it (spec #51 section 2.4).

    ``sent``: the pending challenge was invalidated (latest-wins) and a fresh
    one issued - the challenge fields seed the countdown and the resend
    cooldown. ``cooldown``/``locked``: the resend was refused and the PWA shows
    the matching countdown. ``suspended``: the identity is operator-suspended;
    ``no_identity``: the phone was never registered (call register instead).
    """

    outcome: Literal["sent", "cooldown", "locked", "suspended", "no_identity"]
    phone_e164: str
    challenge_id: int | None = None
    expires_in_seconds: int | None = None
    cooldown_remaining_seconds: int | None = None
    attempts_left: int | None = None
    lockout_remaining_seconds: int | None = None


class OtpFacade:
    """OTP challenge lifecycle: verify and resend (ADR-0006).

    The sub-facade owns the OTP verification and resend flows.  It accepts
    an ``OtpSender`` port instead of adapter types, and imports lockout/challenge
    helpers from ``domain/shared.py``.
    """

    def __init__(
        self,
        engine: AsyncEngine,
        clock: Callable[[], datetime],
        otp_sender: OtpSender,
    ) -> None:
        self._engine = engine
        self._clock = clock
        self._otp_sender = otp_sender

    async def verify_otp(self, phone: str, otp: str) -> VerifyOtpResult:
        """Verify a submitted 6-digit code against the identity's latest challenge.

        A correct code consumes the challenge (single-use), transitions the
        identity ``[Unverified] -> [Active]``, grants the patient role
        idempotently, resets the brute-force counter, and writes
        ``patient.verified`` to the outbox in the same transaction (spec #51
        section 2.4/section 2.6). Wrong guesses decrement the 5-attempt budget without
        killing the code; at 0 the challenge is spent. Expired, spent, or
        already-used challenges reject with a "request a new code" outcome.
        Every rejection writes ``patient.auth_failed`` in the same transaction;
        success never does.

        The brute-force lockout (spec #51 section 2.4) is enforced here: a locked
        phone refuses verification outright (``locked`` outcome) without
        touching the challenge or the counter. Each wrong guess increments the
        identity's ``lockout_failed_attempts`` counter; the 10th consecutive
        failure across challenges sets ``lockout_until`` 15 minutes out, writes
        ``otp.failed`` alongside ``patient.auth_failed``, and answers ``locked``.
        Once the window has fully elapsed the streak resets, so a failure after
        the lockout lifts starts a fresh count instead of re-locking. The
        lockout is a counter, never identity state - ``status`` stays
        Unverified/Active/Suspended and ``Suspended`` remains operator-only.

        The SMS-cost counting rule (ADR-0004 decision 4) is structural: every
        wrong-guess failure flows through ``_record_failed_attempt``, so only
        attempts against a challenge that was actually issued - ``wrong_code``,
        ``spent``, ``expired``, ``replay`` - count toward the streak, because
        only they incurred an SMS cost. ``no_challenge``, ``suspended``, and
        ``locked`` rejections route through ``_reject`` and never touch the
        counter.

        The identity row is locked ``FOR UPDATE`` so concurrent verifications
        for the same phone serialize: the challenge can be consumed exactly
        once, the role grant stays unique, and the failure counter cannot race.
        """
        phone_e164 = normalize_phone(phone)
        now = self._clock()

        async with self._engine.begin() as connection:
            locked = await self._lock_identity(connection, phone_e164)
            if locked is None:
                return await self._reject(connection, phone_e164, None, no_challenge_decision())
            identity_id = locked.identity_id
            identity_status = locked.status
            lockout_failed_attempts = locked.lockout_failed_attempts
            lockout_until = locked.lockout_until

            if identity_status == IDENTITY_SUSPENDED:
                return await self._reject(connection, phone_e164, identity_id, suspended_decision())

            lockout_left = lockout_remaining_seconds(lockout_until, now)
            if lockout_left is not None:
                return await self._reject(
                    connection,
                    phone_e164,
                    identity_id,
                    locked_decision(),
                    lockout_remaining_seconds=lockout_left,
                )

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
                return await self._reject(
                    connection, phone_e164, identity_id, no_challenge_decision()
                )

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
                    .values(
                        status=IDENTITY_ACTIVE,
                        lockout_failed_attempts=0,
                        lockout_until=None,
                        updated_at=now,
                    )
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

            return await self._record_failed_attempt(
                connection,
                identity_id=identity_id,
                phone_e164=phone_e164,
                challenge_id=challenge["id"],
                status=challenge["status"],
                attempts=challenge["attempts"],
                decision=decision,
                lockout_failed_attempts=lockout_failed_attempts,
                lockout_until=lockout_until,
                now=now,
            )

    async def resend_otp(self, phone: str) -> ResendOtpResult:
        """Request a fresh code: latest-wins over the pending challenge.

        Resend is safe and bounded (spec #51 section 2.4): it refuses while the phone
        is in the brute-force lockout (``locked``) or inside the >= 60 s resend
        cooldown measured from the last issuance (``cooldown``), and refuses a
        Suspended identity (``suspended``) - the lockout and ``Suspended`` stay
        distinct, and neither is cleared by a resend. Otherwise it invalidates
        the pending challenge (latest-wins: the previous code can no longer
        verify) and issues a fresh hashed one, writing ``otp.sent`` to the
        outbox in the same transaction and dispatching the EXT-001 delivery as
        a background task afterwards (PHASE-2 REM T4, #86) - the request never
        blocks on the provider.

        The identity row is locked ``FOR UPDATE`` so concurrent resends for one
        phone serialize: only one winner issues a challenge and the invalidation
        never races a verification.
        """
        phone_e164 = normalize_phone(phone)
        now = self._clock()

        async with self._engine.begin() as connection:
            locked = await self._lock_identity(connection, phone_e164)
            if locked is None:
                return ResendOtpResult(outcome="no_identity", phone_e164=phone_e164)
            identity_id = locked.identity_id
            identity_status = locked.status
            lockout_until = locked.lockout_until
            cooldown_until = await _latest_cooldown_until(connection, identity_id)

            decision = evaluate_resend(
                identity_status=identity_status,
                lockout_until=lockout_until,
                cooldown_until=cooldown_until,
                now=now,
            )
            if decision.outcome != "sent":
                return ResendOtpResult(
                    outcome=decision.outcome,
                    phone_e164=phone_e164,
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

        return ResendOtpResult(
            outcome="sent",
            phone_e164=phone_e164,
            challenge_id=challenge_id,
            expires_in_seconds=OTP_TTL_SECONDS,
            cooldown_remaining_seconds=RESEND_COOLDOWN_SECONDS,
            attempts_left=MAX_ATTEMPTS,
        )

    @staticmethod
    async def _lock_identity(
        connection: AsyncConnection, phone_e164: str
    ) -> IdentityGuardState | None:
        """Row-lock the identity for ``phone_e164`` and return its guard state.

        ``FOR UPDATE`` serializes every verification and resend for one phone
        so the challenge can be consumed exactly once, the role grant stays
        unique, and the failure counter cannot race (spec #51 section 2.4). The status
        and lockout columns are read under the same lock so the Suspended guard
        and the lockout check see stable values.
        """
        return await _lock_identity_row(connection, iam_identities.c.phone_e164 == phone_e164)

    @staticmethod
    async def _grant_patient_role(connection: AsyncConnection, identity_id: int) -> None:
        """Grant the patient role idempotently; safe under the identity lock."""
        existing = (
            await connection.execute(
                select(iam_role_grants.c.id).where(
                    iam_role_grants.c.identity_id == identity_id,
                    iam_role_grants.c.role == _PATIENT_ROLE,
                    iam_role_grants.c.status == IDENTITY_ACTIVE,
                )
            )
        ).first()
        if existing is None:
            await connection.execute(
                iam_role_grants.insert().values(
                    identity_id=identity_id, role=_PATIENT_ROLE, status=IDENTITY_ACTIVE
                )
            )

    @staticmethod
    async def _reject(
        connection: AsyncConnection,
        phone_e164: str,
        identity_id: int | None,
        decision: AttemptDecision,
        *,
        lockout_remaining_seconds: int | None = None,
    ) -> VerifyOtpResult:
        """Reject a verification: decision -> ``patient.auth_failed`` -> result.

        Every rejected verification - no live challenge (``no_challenge_decision``),
        a Suspended identity (``suspended_decision``), or an active brute-force
        lockout (``locked_decision``) - refuses with the same chain: the challenge
        machine's decision names the outcome and the failure reason,
        ``patient.auth_failed`` lands in the outbox in the same transaction as
        the rejection, and the returned ``VerifyOtpResult`` renders the outcome
        for the PWA. Only the lockout rejection carries
        ``lockout_remaining_seconds``, for its countdown.

        These are the SMS-cost rule's no-counter rejections (ADR-0004 decision
        4): none of them ever touched ``lockout_failed_attempts`` - a
        ``no_challenge`` verify had no SMS sent for it, and the ``suspended``
        and ``locked`` guards are not attempts - so this helper must not route
        through ``_record_failed_attempt``.
        """
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
            lockout_remaining_seconds=lockout_remaining_seconds,
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

    @staticmethod
    async def _record_failed_attempt(
        connection: AsyncConnection,
        *,
        identity_id: int,
        phone_e164: str,
        challenge_id: int,
        status: str,
        attempts: int,
        decision: AttemptDecision,
        lockout_failed_attempts: int,
        lockout_until: datetime | None,
        now: datetime,
    ) -> VerifyOtpResult:
        """Record a wrong-guess failure against a challenge that was actually issued.

        This is the SMS-cost counting rule (ADR-0004 decision 4): only attempts
        against a challenge an SMS was actually sent for - ``wrong_code``,
        ``spent``, ``expired``, ``replay`` - reach this helper and count toward
        the lockout streak, because only they incurred an SMS cost.
        ``no_challenge``, ``suspended``, and ``locked`` rejections never call it
        (they route through ``_reject``) and never touch the counter. The whole
        chain lives here in one place: challenge write-back, ``evaluate_failure``,
        the identity counter update, ``patient.auth_failed``, and ``otp.failed``
        when this failure crosses the lockout threshold.
        """
        await OtpFacade._record_failure(
            connection,
            challenge_id=challenge_id,
            status=status,
            attempts=attempts,
            decision=decision,
        )
        lockout = evaluate_failure(lockout_failed_attempts, now, lockout_until)
        await connection.execute(
            iam_identities.update()
            .where(iam_identities.c.id == identity_id)
            .values(
                lockout_failed_attempts=lockout.counter,
                lockout_until=lockout.lockout_until,
            )
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
        if lockout.locked:
            await write_outbox(
                connection,
                _IAM_SCHEMA,
                IAM_OUTBOX_TABLE,
                events.otp_failed_envelope(
                    identity_id=identity_id,
                    phone_e164=phone_e164,
                    lockout_until=lockout.lockout_until or now,
                ),
            )
            return VerifyOtpResult(
                outcome="locked",
                phone_e164=phone_e164,
                identity_id=identity_id,
                attempts_left=decision.attempts_left,
                lockout_remaining_seconds=lockout_remaining_seconds(lockout.lockout_until, now),
            )
        return VerifyOtpResult(
            outcome=decision.outcome,
            phone_e164=phone_e164,
            identity_id=identity_id,
            attempts_left=decision.attempts_left,
        )
