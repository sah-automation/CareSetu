"""MOD-001 Identity and access management: typed public sync API.

The only legal cross-module import target for the ``iam`` module
(coding-standards §2, ADR-0003). Phase 2 T3 (#54) implements the begin-or-
resume entry point ``register_patient``; T4 (#55) adds the verification
challenge machine ``verify_otp``; T5 (#56) adds ``resend_otp`` with the
latest-wins resend, cooldown, and brute-force lockout; T6 (#57) adds the
session seam ``issue_session`` (access JWT mint) and the stateless
``validate_token`` the gateway RBAC consumes. The remaining typed methods
arrive with their Phase 2 tickets.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from bus.outbox_writer import write_outbox
from modules.iam.adapters.sms import SmsAdapter, SmsSendRequest, SmsTemplateParams
from modules.iam.domain import events, jwt
from modules.iam.domain.exceptions import SessionIssuanceError
from modules.iam.domain.lockout import evaluate_failure, lockout_remaining_seconds
from modules.iam.domain.otp import (
    MAX_ATTEMPTS,
    OTP_TTL_SECONDS,
    RESEND_COOLDOWN_SECONDS,
    generate_otp,
    hash_otp,
)
from modules.iam.domain.phone import normalize_phone
from modules.iam.domain.resend import evaluate_resend
from modules.iam.domain.verify import (
    CHALLENGE_EXPIRED,
    CHALLENGE_PENDING,
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
    iam_sessions,
)

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
    """Outcome of requesting a fresh code, as the PWA renders it (spec #51 §2.4).

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
    lockout_remaining_seconds: int | None = None
    attempts_left: int | None = None


class IssueSessionResult(BaseModel):
    """A freshly minted access session (spec #51 §2.5, ticket #57).

    ``jwt`` is the HS256 access JWT the PWA stores; ``jti``/``expires_in_seconds``
    mirror its claims so the client can show a session indicator, and ``scope``
    is the resolved RBAC scope - always from the patient role grant, never from
    client input.
    """

    jwt: str
    jti: str
    scope: str
    identity_id: int
    expires_in_seconds: int


class ValidatedAccessToken(BaseModel):
    """Claims of a verified access JWT, as the gateway attaches them (ticket #57, T8).

    ``subject_id`` is the identity id the gateway scopes to the patient's own
    record; ``scope`` is the RBAC scope resolved from the token claim.
    """

    subject_id: int
    scope: str
    jti: str


def _default_clock() -> datetime:
    return datetime.now(UTC)


class IamFacade:
    """Typed public facade for iam (Phase 2: registration + OTP + sessions)."""

    def __init__(
        self,
        engine: AsyncEngine,
        sms_adapter: SmsAdapter,
        clock: Callable[[], datetime] = _default_clock,
        *,
        access_token_signing_key: str = "",
        access_token_ttl_seconds: int = jwt.ACCESS_TOKEN_TTL_SECONDS,
    ) -> None:
        self._engine = engine
        self._sms = sms_adapter
        self._clock = clock
        self._access_token_signing_key = access_token_signing_key
        self._access_token_ttl_seconds = access_token_ttl_seconds

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
        idempotently, resets the brute-force counter, and writes
        ``patient.verified`` to the outbox in the same transaction (spec #51
        §2.4/§2.6). Wrong guesses decrement the 5-attempt budget without
        killing the code; at 0 the challenge is spent. Expired, spent, or
        already-used challenges reject with a "request a new code" outcome.
        Every rejection writes ``patient.auth_failed`` in the same transaction;
        success never does.

        The brute-force lockout (spec #51 §2.4) is enforced here: a locked
        phone refuses verification outright (``locked`` outcome) without
        touching the challenge or the counter. Each wrong guess increments the
        identity's ``lockout_failed_attempts`` counter; the 10th consecutive
        failure across challenges sets ``lockout_until`` 15 minutes out, writes
        ``otp.failed`` alongside ``patient.auth_failed``, and answers ``locked``.
        The lockout is a counter, never identity state - ``status`` stays
        Unverified/Active/Suspended and ``Suspended`` remains operator-only.

        The identity row is locked ``FOR UPDATE`` so concurrent verifications
        for the same phone serialize: the challenge can be consumed exactly
        once, the role grant stays unique, and the failure counter cannot race.
        """
        phone_e164 = normalize_phone(phone)
        now = self._clock()

        async with self._engine.begin() as connection:
            locked = await self._lock_identity(connection, phone_e164)
            if locked is None:
                return await self._reject_no_challenge(connection, phone_e164, identity_id=None)
            identity_id, identity_status, lockout_failed_attempts, lockout_until = locked

            if identity_status == IDENTITY_SUSPENDED:
                return await self._reject_suspended(connection, phone_e164, identity_id)

            lockout_left = lockout_remaining_seconds(lockout_until, now)
            if lockout_left is not None:
                return await self._reject_locked(connection, phone_e164, identity_id, lockout_left)

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

            await self._record_failure(
                connection,
                challenge_id=challenge["id"],
                status=challenge["status"],
                attempts=challenge["attempts"],
                decision=decision,
            )
            lockout = evaluate_failure(lockout_failed_attempts, now)
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

    @staticmethod
    async def _lock_identity(
        connection: AsyncConnection, phone_e164: str
    ) -> tuple[int, str, int, datetime | None] | None:
        """Row-lock the identity for ``phone_e164`` and return its guard state.

        Returns ``(id, status, lockout_failed_attempts, lockout_until)``.
        ``FOR UPDATE`` serializes every verification and resend for one phone
        so the challenge can be consumed exactly once, the role grant stays
        unique, and the failure counter cannot race (spec #51 §2.4). The status
        and lockout columns are read under the same lock so the Suspended guard
        and the lockout check see stable values.
        """
        row = (
            (
                await connection.execute(
                    select(
                        iam_identities.c.id,
                        iam_identities.c.status,
                        iam_identities.c.lockout_failed_attempts,
                        iam_identities.c.lockout_until,
                    )
                    .where(iam_identities.c.phone_e164 == phone_e164)
                    .with_for_update()
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            return None
        return (
            row["id"],
            row["status"],
            row["lockout_failed_attempts"],
            row["lockout_until"],
        )

    async def resend_otp(self, phone: str) -> ResendOtpResult:
        """Request a fresh code: latest-wins over the pending challenge.

        Resend is safe and bounded (spec #51 §2.4): it refuses while the phone
        is in the brute-force lockout (``locked``) or inside the >= 60 s resend
        cooldown measured from the last issuance (``cooldown``), and refuses a
        Suspended identity (``suspended``) - the lockout and ``Suspended`` stay
        distinct, and neither is cleared by a resend. Otherwise it invalidates
        the pending challenge (latest-wins: the previous code can no longer
        verify) and issues a fresh hashed one, writing ``otp.sent`` to the
        outbox in the same transaction and delivering it via the EXT-001
        adapter afterwards.

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
            identity_id, identity_status, _failed_attempts, lockout_until = locked
            cooldown_until = await self._latest_cooldown_until(connection, identity_id)

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

            await connection.execute(
                iam_otp_challenges.update()
                .where(
                    iam_otp_challenges.c.identity_id == identity_id,
                    iam_otp_challenges.c.status == CHALLENGE_PENDING,
                )
                .values(status=CHALLENGE_EXPIRED)
            )
            otp = generate_otp()
            expires_at = now + timedelta(seconds=OTP_TTL_SECONDS)
            cooldown_until_new = now + timedelta(seconds=RESEND_COOLDOWN_SECONDS)
            challenge_id = (
                await connection.execute(
                    iam_otp_challenges.insert()
                    .values(
                        identity_id=identity_id,
                        otp_hash=hash_otp(otp),
                        status="Pending",
                        attempts=0,
                        expires_at=expires_at,
                        cooldown_until=cooldown_until_new,
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

        return ResendOtpResult(
            outcome="sent",
            phone_e164=phone_e164,
            challenge_id=challenge_id,
            expires_in_seconds=OTP_TTL_SECONDS,
            cooldown_remaining_seconds=RESEND_COOLDOWN_SECONDS,
            attempts_left=MAX_ATTEMPTS,
        )

    async def issue_session(self, phone: str) -> IssueSessionResult:
        """Mint an access JWT for a verified patient (spec #51 §2.5, ticket #57).

        The scope claim is always derived from the patient's active role grant,
        never from the client (acceptance criterion #3): the identity must be
        ``Active`` (OTP-verified) and hold an ``Active`` patient grant, else a
        ``SessionIssuanceError`` names the missing precondition. A fresh ``jti``
        is generated per token, ``exp`` is ~15 minutes out so a stolen token has
        limited value, and the session row is recorded in the ``iam``
        ``sessions`` table in the same transaction - the jti is the anchor the
        refresh rotation (T7) and revocation check against. An empty signing key
        fails closed rather than minting a token anyone could forge.
        """
        phone_e164 = normalize_phone(phone)
        if not self._access_token_signing_key:
            raise SessionIssuanceError(
                "access-token signing key is not configured; refusing to issue a session"
            )
        now = self._clock()

        async with self._engine.begin() as connection:
            locked = await self._lock_identity(connection, phone_e164)
            if locked is None:
                raise SessionIssuanceError(
                    f"no identity for {phone_e164}; register the phone before issuing a session"
                )
            identity_id, identity_status, _failed_attempts, _lockout_until = locked
            if identity_status != IDENTITY_ACTIVE:
                raise SessionIssuanceError(
                    f"identity {identity_id} is {identity_status}, not Active; "
                    "verify the OTP before issuing a session"
                )
            scope = await self._resolve_active_role(connection, identity_id, _PATIENT_ROLE)
            if scope is None:
                raise SessionIssuanceError(
                    f"identity {identity_id} has no active patient role grant"
                )

            jti = uuid.uuid4().hex
            token = jwt.issue_token(
                jti=jti,
                subject_id=identity_id,
                scope=scope,
                signing_key=self._access_token_signing_key,
                now=now,
                ttl_seconds=self._access_token_ttl_seconds,
            )
            await connection.execute(
                iam_sessions.insert().values(
                    jti=jti,
                    identity_id=identity_id,
                    scope=scope,
                    issued_at=now,
                    expires_at=now + timedelta(seconds=self._access_token_ttl_seconds),
                )
            )

        return IssueSessionResult(
            jwt=token,
            jti=jti,
            scope=scope,
            identity_id=identity_id,
            expires_in_seconds=self._access_token_ttl_seconds,
        )

    async def validate_token(self, token: str) -> ValidatedAccessToken:
        """Resolve a valid access JWT to its scope for the gateway (ticket #57).

        A pure signature + expiry check with no database round-trip (acceptance
        criterion #4), so the edge hot path stays far under the 100 ms p95
        (MOD-001 §3.1): the signing key and the clock are all it needs. Every
        rejection raises the matching ``InvalidAccessTokenError`` subclass -
        expired, malformed, or wrong signature - for the gateway to deny with a
        single 401.
        """
        claims = jwt.verify_token(token, self._access_token_signing_key, now=self._clock())
        return ValidatedAccessToken(
            subject_id=claims.subject_id, scope=claims.scope, jti=claims.jti
        )

    @staticmethod
    async def _latest_cooldown_until(
        connection: AsyncConnection, identity_id: int
    ) -> datetime | None:
        """The latest challenge's ``cooldown_until`` for the identity, or None.

        The resend cooldown is measured per phone from the last issuance (spec
        #51 §2.4), and challenges are issued per identity - so the newest
        challenge row carries the cooldown boundary.
        """
        return (
            await connection.execute(
                select(iam_otp_challenges.c.cooldown_until)
                .where(iam_otp_challenges.c.identity_id == identity_id)
                .order_by(iam_otp_challenges.c.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    @staticmethod
    async def _resolve_active_role(
        connection: AsyncConnection, identity_id: int, role: str
    ) -> str | None:
        """The role name if ``identity_id`` holds an Active grant for ``role``.

        The source of the token's scope claim: session scope is always derived
        from a live role grant in ``iam``, never from the client (spec #51
        §2.5, ticket #57). ``None`` means no active grant - issuance refuses.
        """
        return (
            await connection.execute(
                select(iam_role_grants.c.role)
                .where(
                    iam_role_grants.c.identity_id == identity_id,
                    iam_role_grants.c.role == role,
                    iam_role_grants.c.status == "Active",
                )
                .limit(1)
            )
        ).scalar_one_or_none()

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
    async def _reject_locked(
        connection: AsyncConnection,
        phone_e164: str,
        identity_id: int,
        lockout_remaining: int,
    ) -> VerifyOtpResult:
        """Reject verification while the phone is in the brute-force lockout.

        The lockout is a temporary counter, never identity state (spec #51
        §2.4), so the attempt is refused with the ``locked`` outcome - the PWA
        shows the lockout countdown - without touching the challenge or the
        counter. The refusal writes ``patient.auth_failed`` in the same
        transaction.
        """
        decision = locked_decision()
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
            lockout_remaining_seconds=lockout_remaining,
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
