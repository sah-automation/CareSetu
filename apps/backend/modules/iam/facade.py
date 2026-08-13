"""MOD-001 Identity and access management: typed public sync API.

The only legal cross-module import target for the ``iam`` module
(coding-standards §2, ADR-0003). Phase 2 T3 (#54) implements the begin-or-
resume entry point ``register_patient``; T4 (#55) adds the verification
challenge machine ``verify_otp``; T5 (#56) adds ``resend_otp`` with the
latest-wins resend, cooldown, and brute-force lockout; T6 (#57) adds the
session seam ``issue_session`` (access JWT mint) and the stateless
``validate_token`` the gateway RBAC consumes; T7 (#58) adds the SMS-independent
``refresh_session`` that rotates an opaque refresh token. The remaining typed
methods arrive with their Phase 2 tickets.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import ColumnElement, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from bus.outbox_writer import write_outbox
from modules.iam.adapters.sms import (
    SmsAdapter,
    SmsDeliveryQueue,
    SmsSendRequest,
    SmsTemplateParams,
)
from modules.iam.domain import events, jwt, refresh
from modules.iam.domain.exceptions import (
    IamError,
    RefreshTokenExpiredError,
    RefreshTokenRevokedError,
    RefreshTokenUnknownError,
    SessionIssuanceError,
)
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
    """Outcome of the begin-or-resume entry, as the PWA renders it (spec #51 §2.1/§2.4).

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
    client input. ``refresh_token`` is the opaque, server-side-hashed refresh
    token the PWA keeps for ``refresh_session`` (ticket #58).
    """

    jwt: str
    jti: str
    scope: str
    identity_id: int
    expires_in_seconds: int
    refresh_token: str


class RefreshSessionResult(BaseModel):
    """The output of one successful ``refresh_session`` rotation (ticket #58).

    Mirrors ``IssueSessionResult`` - a fresh access JWT and a brand-new opaque
    refresh token. The previous refresh token is already invalid by the time
    this is returned (rotation is in the same transaction as the mint).
    """

    jwt: str
    jti: str
    scope: str
    identity_id: int
    expires_in_seconds: int
    refresh_token: str


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


async def _lock_identity_row(
    connection: AsyncConnection, predicate: ColumnElement[bool]
) -> tuple[int, str, int, datetime | None] | None:
    """Row-lock the identity matching ``predicate`` and return its guard state.

    Returns ``(id, status, lockout_failed_attempts, lockout_until)``. The core
    shared by ``_lock_identity`` (by phone) and ``_lock_identity_by_id`` (by
    id); ``FOR UPDATE`` serializes concurrent writers so the failure counter
    cannot race and the identity guards see stable values.
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
                .where(predicate)
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
        refresh_token_ttl_seconds: int = refresh.REFRESH_TOKEN_TTL_SECONDS,
    ) -> None:
        self._engine = engine
        self.delivery_queue = SmsDeliveryQueue(sms_adapter)
        self._clock = clock
        self._access_token_signing_key = access_token_signing_key
        self._access_token_ttl_seconds = access_token_ttl_seconds
        self._refresh_token_ttl_seconds = refresh_token_ttl_seconds

    async def register_patient(self, phone: str) -> RegisterPatientResult:
        """Begin-or-resume: create the identity on first use, else resolve it.

        The phone is normalized server-side to +91 E.164 (the country code is
        never trusted from the client). Concurrency converges via the unique
        ``phone_e164`` index: ``INSERT ... ON CONFLICT DO NOTHING`` then a
        re-read, never SELECT-then-INSERT (spec #51 §2.3). A new identity is
        created ``[Unverified]`` and emits ``patient.registered``; a repeat
        phone resolves to the existing identity (no duplicate).

        The existing-phone login branch enforces the same anti-spam gate as a
        resend (spec #51 §2.4, ADR-0004): while the phone is inside the >= 60 s
        resend cooldown measured from the last issuance, in the brute-force
        lockout, or ``Suspended``, the entry is refused - no fresh challenge is
        issued, no ``otp.sent`` is written, and no SMS is sent - so an attacker
        cannot defeat the cooldown by calling register repeatedly or poke a
        locked phone back into the OTP flow. The identity row is locked
        ``FOR UPDATE`` so the refusal reads stable guard state and concurrent
        writers serialize. First-time registration and out-of-cooldown login
        are unchanged: a hashed challenge is issued, ``otp.sent`` lands in the
        iam outbox in the same transaction as the change, and the EXT-001
        adapter delivers it as a background task afterwards - the request never
        blocks on the provider (PHASE-2 REM T4, #86).
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
                locked = await self._lock_identity(connection, phone_e164)
                if locked is None:
                    raise IamError("existing identity disappeared between the insert and the lock")
                identity_id, identity_status, _failed_attempts, lockout_until = locked
                latest_cooldown_until = await self._latest_cooldown_until(connection, identity_id)
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
            challenge_id = (
                await connection.execute(
                    iam_otp_challenges.insert()
                    .values(
                        identity_id=identity_id,
                        otp_hash=hash_otp(otp),
                        status=CHALLENGE_PENDING,
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

        self.delivery_queue.enqueue(
            SmsSendRequest(phone_e164=phone_e164, params=SmsTemplateParams(otp=otp))
        )

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
        Once the window has fully elapsed the streak resets, so a failure after
        the lockout lifts starts a fresh count instead of re-locking. The
        lockout is a counter, never identity state - ``status`` stays
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

    @staticmethod
    async def _lock_identity(
        connection: AsyncConnection, phone_e164: str
    ) -> tuple[int, str, int, datetime | None] | None:
        """Row-lock the identity for ``phone_e164`` and return its guard state.

        ``FOR UPDATE`` serializes every verification and resend for one phone
        so the challenge can be consumed exactly once, the role grant stays
        unique, and the failure counter cannot race (spec #51 §2.4). The status
        and lockout columns are read under the same lock so the Suspended guard
        and the lockout check see stable values.
        """
        return await _lock_identity_row(connection, iam_identities.c.phone_e164 == phone_e164)

    @staticmethod
    async def _lock_identity_by_id(
        connection: AsyncConnection, identity_id: int
    ) -> tuple[int, str, int, datetime | None] | None:
        """Row-lock an identity by id and return its guard state (ticket #58).

        The refresh path already holds the ``sessions`` row ``FOR UPDATE``, so
        the identity lock here serializes a concurrent role/status change
        against the rotation without creating a lock cycle - no other code ever
        locks a session row.
        """
        return await _lock_identity_row(connection, iam_identities.c.id == identity_id)

    @staticmethod
    async def _session_for_refresh(
        connection: AsyncConnection, token_hash: str
    ) -> RowMapping | None:
        """The session row for a refresh-token hash, locked to serialize rotation.

        ``FOR UPDATE`` on the session row is the rotation guard: two concurrent
        refreshes presenting the same token serialize, and the second re-reads
        the row after the first commits, sees ``revoked_at`` set, and refuses
        as a replay instead of double-rotating (ticket #58).
        """
        return (
            (
                await connection.execute(
                    select(
                        iam_sessions.c.id,
                        iam_sessions.c.identity_id,
                        iam_sessions.c.revoked_at,
                        iam_sessions.c.refresh_expires_at,
                    )
                    .where(iam_sessions.c.refresh_token_hash == token_hash)
                    .with_for_update()
                )
            )
            .mappings()
            .first()
        )

    @staticmethod
    async def _identity_phone(connection: AsyncConnection, identity_id: int) -> str:
        """The ``phone_e164`` for an identity, for the audit event on a replay.

        A session row's FK guarantees the identity exists; the fallback keeps
        the outbox write safe even if a row were ever orphaned.
        """
        return (
            await connection.execute(
                select(iam_identities.c.phone_e164).where(iam_identities.c.id == identity_id)
            )
        ).scalar_one_or_none() or ""

    async def _mint_session_row(
        self,
        connection: AsyncConnection,
        identity_id: int,
        scope: str,
        now: datetime,
    ) -> tuple[str, str, str]:
        """Mint a fresh access JWT + opaque refresh token and record the session row.

        Shared by ``issue_session`` and ``refresh_session`` so both mint the
        same row shape: a random ``jti``, a fresh opaque refresh token (stored
        hashed, never in clear) with its ~30-day sliding ``refresh_expires_at``,
        and an access JWT whose ``exp`` is the access-token TTL out. Returns
        ``(jti, refresh_token, jwt)``.
        """
        jti = uuid.uuid4().hex
        refresh_token = refresh.generate_refresh_token()
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
                refresh_token_hash=refresh.hash_refresh_token(refresh_token),
                refresh_expires_at=now + timedelta(seconds=self._refresh_token_ttl_seconds),
            )
        )
        return jti, refresh_token, token

    async def resend_otp(self, phone: str) -> ResendOtpResult:
        """Request a fresh code: latest-wins over the pending challenge.

        Resend is safe and bounded (spec #51 §2.4): it refuses while the phone
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
                        status=CHALLENGE_PENDING,
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

        self.delivery_queue.enqueue(
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
        refresh rotation (T7) and revocation check against, and the row also
        carries the SHA-256 of a fresh opaque refresh token (never the token
        itself) with its ~30-day sliding ``refresh_expires_at``. An empty signing
        key fails closed rather than minting a token anyone could forge.
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

            jti, refresh_token, token = await self._mint_session_row(
                connection, identity_id, scope, now
            )

        return IssueSessionResult(
            jwt=token,
            jti=jti,
            scope=scope,
            identity_id=identity_id,
            expires_in_seconds=self._access_token_ttl_seconds,
            refresh_token=refresh_token,
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

    async def refresh_session(self, refresh_token: str) -> RefreshSessionResult:
        """Rotate an opaque refresh token into a fresh session (ticket #58).

        The refresh path is fully independent of SMS (NFR-004): it only reads
        the ``sessions`` table and mints tokens, so an EXT-001 outage never
        bricks an existing session. The token is looked up by its SHA-256
        (opaque, never stored or logged in clear); an unknown token, a revoked
        one, and an expired one are each refused with their own
        ``InvalidRefreshTokenError`` subclass (acceptance criterion #3).

        A valid token rotates in the same transaction as the mint: the old
        session row is revoked (``revoked_at``) and a fresh row records the new
        access ``jti`` with a brand-new refresh token whose lifetime slides to
        ~30 days from ``now``. Presenting the already-rotated token afterwards
        finds the revoked row - a replay signal - and is refused while
        ``patient.auth_failed`` is committed to the outbox in the same
        transaction (audit can tell a stolen-session replay from a garbage
        token, which matches nothing). The scope of the fresh JWT is re-derived
        from the identity's current active role grant, never from the old
        token. The identity row is locked ``FOR UPDATE`` (after the session
        row) so a concurrent role change cannot race the refresh, and the
        session-row lock serializes two concurrent refreshes of the same token
        so only one rotation wins. An empty signing key fails closed exactly
        like ``issue_session``.
        """
        if not self._access_token_signing_key:
            raise SessionIssuanceError(
                "access-token signing key is not configured; refusing to refresh a session"
            )
        now = self._clock()
        token_hash = refresh.hash_refresh_token(refresh_token)
        replay_signal = False

        async with self._engine.begin() as connection:
            session_row = await self._session_for_refresh(connection, token_hash)
            if session_row is None:
                raise RefreshTokenUnknownError("no session matches this refresh token")

            decision = refresh.evaluate_refresh(
                revoked_at=session_row["revoked_at"],
                refresh_expires_at=session_row["refresh_expires_at"],
                now=now,
            )

            if decision.reason == "revoked":
                phone = await self._identity_phone(connection, session_row["identity_id"])
                await write_outbox(
                    connection,
                    _IAM_SCHEMA,
                    IAM_OUTBOX_TABLE,
                    events.patient_auth_failed_envelope(
                        identity_id=session_row["identity_id"],
                        phone_e164=phone,
                        reason="replay",
                    ),
                )
                replay_signal = True
            elif decision.reason == "expired":
                raise RefreshTokenExpiredError(
                    "this refresh token has expired; re-authenticate to continue"
                )
            else:
                identity = await self._lock_identity_by_id(connection, session_row["identity_id"])
                if identity is None:
                    raise RefreshTokenRevokedError("the session identity no longer exists")
                identity_id, identity_status, _failed_attempts, _lockout_until = identity
                if identity_status != IDENTITY_ACTIVE:
                    raise RefreshTokenRevokedError(
                        f"identity {identity_id} is {identity_status}; refusing to refresh"
                    )
                scope = await self._resolve_active_role(connection, identity_id, _PATIENT_ROLE)
                if scope is None:
                    raise RefreshTokenRevokedError(
                        f"identity {identity_id} has no active patient role grant; "
                        "refusing to refresh"
                    )

                new_jti, new_refresh_token, token = await self._mint_session_row(
                    connection, identity_id, scope, now
                )
                await connection.execute(
                    iam_sessions.update()
                    .where(iam_sessions.c.id == session_row["id"])
                    .values(revoked_at=now)
                )

        if replay_signal:
            raise RefreshTokenRevokedError(
                "this refresh token was already used or revoked; refusing to refresh"
            )

        return RefreshSessionResult(
            jwt=token,
            jti=new_jti,
            scope=scope,
            identity_id=identity_id,
            expires_in_seconds=self._access_token_ttl_seconds,
            refresh_token=new_refresh_token,
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
                    iam_role_grants.c.status == IDENTITY_ACTIVE,
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
