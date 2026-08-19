"""MOD-001 Identity and access management: typed public sync API.

The only legal cross-module import target for the ``iam`` module
(coding-standards section 2, ADR-0003). Phase 2 T3 (#54) implements the begin-or-
resume entry point ``register_patient``; T4 (#55) adds the verification
challenge machine ``verify_otp``; T5 (#56) adds ``resend_otp`` with the
latest-wins resend, cooldown, and brute-force lockout. Both register's out-of-
cooldown login and resend issue through the same latest-wins helpers
(``_invalidate_pending_challenges`` + ``_issue_challenge``), so every re-entry
for a phone shadows its pending code (PHASE-2 REM FIX 1, #101). T6 (#57) adds
the session seam ``issue_session`` (access JWT mint) and the stateless
``validate_token`` the gateway RBAC consumes; T7 (#58) adds the SMS-independent
``refresh_session`` that rotates an opaque refresh token. Session methods are
delegated to ``SessionFacade`` (ADR-0006, ticket #166). The remaining typed
methods arrive with their Phase 2 tickets.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from bus.outbox_writer import write_outbox
from modules.iam.adapters.sms import (
    SmsAdapter,
    SmsDeliveryQueue,
    SmsSendRequest,
    SmsTemplateParams,
)
from modules.iam.domain import events
from modules.iam.domain.exceptions import (
    IamError,
)
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
from modules.iam.otp_facade import (
    OtpFacade as OtpFacade,
)
from modules.iam.otp_facade import (
    ResendOtpResult as ResendOtpResult,
)
from modules.iam.otp_facade import (
    VerifyOtpResult as VerifyOtpResult,
)
from modules.iam.outbox import IAM_OUTBOX_TABLE
from modules.iam.schema.models import (
    iam_identities,
)
from modules.iam.session_facade import (
    SessionFacade as SessionFacade,
)
from modules.iam.session_facade import (
    SessionResult as SessionResult,
)
from modules.iam.session_facade import (
    ValidatedAccessToken as ValidatedAccessToken,
)

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


async def _identity_phone(connection: AsyncConnection, identity_id: int) -> str:
    """The ``phone_e164`` for an identity, for an audit event that names it.

    Used by the refresh-replay path (``patient.auth_failed`` reason
    ``replay``) and by the access-denial emitter (reason
    ``access_denied``, PHASE-2 REM T7 #87). A session row's FK guarantees
    the identity exists; the fallback keeps the outbox write safe even if a
    row were ever orphaned.
    """
    return (
        await connection.execute(
            select(iam_identities.c.phone_e164).where(iam_identities.c.id == identity_id)
        )
    ).scalar_one_or_none() or ""


class IamFacade:
    """Typed public facade for iam (Phase 2: registration + OTP + sessions)."""

    def __init__(
        self,
        engine: AsyncEngine,
        sms_adapter: SmsAdapter,
        clock: Callable[[], datetime] = _default_clock,
        *,
        access_token_signing_key: str = "",
        access_token_ttl_seconds: int = 900,
        refresh_token_ttl_seconds: int = 2_592_000,
    ) -> None:
        self._engine = engine
        self.delivery_queue = SmsDeliveryQueue(
            sms_adapter, on_delivery_failed=self._emit_delivery_failed
        )

        async def _otp_sender(phone_e164: str, otp: str) -> None:
            self.delivery_queue.enqueue(
                SmsSendRequest(
                    phone_e164=phone_e164,
                    params=SmsTemplateParams(otp=otp),
                )
            )

        self._otp_sender: OtpSender = _otp_sender
        self._clock = clock
        self._otp = OtpFacade(engine, clock, self._otp_sender)
        self._sessions = SessionFacade(
            engine,
            clock=clock,
            access_token_signing_key=access_token_signing_key,
            access_token_ttl_seconds=access_token_ttl_seconds,
            refresh_token_ttl_seconds=refresh_token_ttl_seconds,
        )

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
        return await self._otp.verify_otp(phone, otp)

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
        return await self._otp.resend_otp(phone)

    # -- Session delegation (ADR-0006, ticket #166) ------------------------

    async def issue_session(self, phone: str) -> SessionResult:
        """Mint an access JWT for a verified patient (delegated to ``SessionFacade``)."""
        return await self._sessions.issue_session(phone)

    async def validate_token(self, token: str) -> ValidatedAccessToken:
        """Resolve a valid access JWT to its scope (delegated to ``SessionFacade``)."""
        return await self._sessions.validate_token(token)

    async def refresh_session(self, refresh_token: str) -> SessionResult:
        """Rotate an opaque refresh token into a fresh session (delegated to ``SessionFacade``)."""
        return await self._sessions.refresh_session(refresh_token)

    # -- Audit --------------------------------------------------------------

    async def emit_access_denied(self, identity_id: int) -> None:
        """Publish ``patient.auth_failed`` (reason ``access_denied``) for an identity.

        PHASE-2 REM T7 (#87): the gateway answers an authenticated 403 on a
        protected route (insufficient scope / missing role) with this call so
        the access-denial attempt reaches the audit event stream (spec #51 user
        story 44, Implementation Decision 6). The event runs in its own
        transaction - the gateway holds no open transaction - and names the
        identity and its phone (resolved here, in the iam module; the gateway
        stays a thin adapter and never touches the database). Anonymous 401s
        carry no identity to attribute and never reach this call.
        """
        async with self._engine.begin() as connection:
            phone = await _identity_phone(connection, identity_id)
            await write_outbox(
                connection,
                _IAM_SCHEMA,
                IAM_OUTBOX_TABLE,
                events.patient_auth_failed_envelope(
                    identity_id=identity_id,
                    phone_e164=phone,
                    reason="access_denied",
                ),
            )

    async def _emit_delivery_failed(self, request: SmsSendRequest) -> None:
        """Publish ``otp.failed`` (reason ``delivery``) for an undeliverable send.

        PHASE-2 REM T5 (#81): when the background EXT-001 delivery has
        exhausted every retry, audit needs to track phones that never received
        their code - not just the lockout case already emitted. The identity
        for the phone is resolved in a fresh transaction (the delivery runs
        outside the issuing request's transaction) and the event lands in the
        iam outbox on its own commit. A phone with no identity row (nothing to
        name) is skipped silently - the queue has already logged the failure.
        """
        async with self._engine.begin() as connection:
            identity_id = (
                await connection.execute(
                    select(iam_identities.c.id).where(
                        iam_identities.c.phone_e164 == request.phone_e164
                    )
                )
            ).scalar_one_or_none()
            if identity_id is None:
                return
            await write_outbox(
                connection,
                _IAM_SCHEMA,
                IAM_OUTBOX_TABLE,
                events.otp_failed_envelope(
                    identity_id=identity_id,
                    phone_e164=request.phone_e164,
                    reason="delivery",
                ),
            )
