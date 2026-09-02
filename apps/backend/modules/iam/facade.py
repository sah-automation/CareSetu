"""MOD-001 Identity and access management: typed public sync API.

The only legal cross-module import target for the ``iam`` module
(coding-standards section 2, ADR-0003).  The coordinator ``IamFacade``
delegates to three sub-facades (ADR-0006): ``IdentityFacade`` (register),
``OtpFacade`` (verify, resend), and ``SessionFacade`` (mint, validate,
refresh).  Result models live with their sub-facade and are re-exported
here for backward compatibility.  ``emit_access_denied`` and
``_emit_delivery_failed`` remain on the coordinator as audit hooks.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from bus.outbox_writer import write_outbox
from modules.iam.adapters.sms import (
    SmsAdapter,
    SmsDeliveryQueue,
    SmsSendRequest,
    SmsTemplateParams,
)
from modules.iam.adapters.sms import (
    build_sms_adapter as build_sms_adapter,
)
from modules.iam.domain import events
from modules.iam.domain.exceptions import (
    InvalidAccessTokenError as InvalidAccessTokenError,
)
from modules.iam.domain.shared import (
    OtpSender as OtpSender,
)
from modules.iam.domain.shared import (
    _identity_phone as _identity_phone,
)
from modules.iam.identity_facade import (
    IdentityFacade as IdentityFacade,
)
from modules.iam.identity_facade import (
    OperatorInvitedResult as OperatorInvitedResult,
)
from modules.iam.identity_facade import (
    PartnerCredentialCreatedResult as PartnerCredentialCreatedResult,
)
from modules.iam.identity_facade import (
    RegisterPatientResult as RegisterPatientResult,
)
from modules.iam.mfa_facade import (
    EnrollMfaResult as EnrollMfaResult,
)
from modules.iam.mfa_facade import (
    MfaFacade as MfaFacade,
)
from modules.iam.mfa_facade import (
    VerifyMfaResult as VerifyMfaResult,
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
from modules.iam.session_facade import (
    _partner_role_status as _partner_role_status,
)

_IAM_SCHEMA = "iam"


def _default_clock() -> datetime:
    return datetime.now(UTC)


class IamFacade:
    """Thin coordinator for iam, delegating to sub-facades (ADR-0006)."""

    def __init__(
        self,
        engine: AsyncEngine,
        sms_adapter: SmsAdapter,
        clock: Callable[[], datetime] = _default_clock,
        *,
        access_token_signing_key: str = "",
        access_token_ttl_seconds: int = 900,
        refresh_token_ttl_seconds: int = 2_592_000,
        mfa_secret_key: str = "",
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
        self._identity = IdentityFacade(engine, self._otp_sender, clock)
        self._otp = OtpFacade(engine, clock, self._otp_sender)
        self._mfa = MfaFacade(engine, clock, mfa_secret_key=mfa_secret_key)
        self._sessions = SessionFacade(
            engine,
            clock=clock,
            access_token_signing_key=access_token_signing_key,
            access_token_ttl_seconds=access_token_ttl_seconds,
            refresh_token_ttl_seconds=refresh_token_ttl_seconds,
            mfa_secret_key=mfa_secret_key,
        )

    # -- Identity delegation (ADR-0006, ticket #169) -----------------------

    async def register_patient(self, phone: str) -> RegisterPatientResult:
        """Begin-or-resume: create the identity on first use, else resolve it."""
        return await self._identity.register_patient(phone)

    async def create_credential_account(
        self, phone: str, connection: AsyncConnection | None = None
    ) -> PartnerCredentialCreatedResult:
        """Create a login-capable identity for a newly registered partner (ADR-0010).

        Synchronous, in one transaction boundary, with no role grant - the
        ``partner`` role is granted later at activation (T03, #246). ``connection``
        lets the caller share an open transaction so the identity and the partner
        profile commit atomically (ADR-0010); when omitted the seam opens its own.
        """
        return await self._identity.create_credential_account(phone, connection=connection)

    async def create_operator_account(
        self,
        phone: str,
        invited_by_identity_id: int,
        connection: AsyncConnection | None = None,
    ) -> OperatorInvitedResult:
        """Invite a new operator (T07, #250): credentialed, MFA-bound at first login.

        Delegated to ``IdentityFacade``. The invited identity is created with an
        ``Active`` ``operator`` role grant, so an operator-scoped session is
        minted only after MFA completes.
        """
        return await self._identity.create_operator_account(
            phone, invited_by_identity_id=invited_by_identity_id, connection=connection
        )

    # -- OTP delegation (ADR-0006, ticket #168) ----------------------------

    async def verify_otp(self, phone: str, otp: str) -> VerifyOtpResult:
        """Verify a submitted 6-digit code against the identity's latest challenge."""
        return await self._otp.verify_otp(phone, otp)

    async def resend_otp(self, phone: str) -> ResendOtpResult:
        """Request a fresh code: latest-wins over the pending challenge."""
        return await self._otp.resend_otp(phone)

    # -- MFA delegation (ADR-0006, T07 ticket #250) ------------------------

    async def enroll_mfa(self, identity_id: int) -> EnrollMfaResult:
        """Enroll an operator's TOTP MFA factor (P1, #272).

        Delegated to ``MfaFacade``. Generates a fresh secret, encrypts it at
        rest, and stores the ciphertext in ``iam_operator_mfa.secret``; the
        returned plaintext secret + provisioning URI are shown to the operator
        exactly once to add the factor to their authenticator. After this call
        the operator satisfies ``issue_operator_session``'s MFA gate and can
        complete their first login.
        """
        return await self._mfa.enroll_mfa(identity_id)

    async def record_mfa_verified(self, phone: str) -> VerifyMfaResult:
        """Record a successful operator MFA second factor (T07, #250).

        Delegated to ``MfaFacade``. After this call the operator satisfies
        ``issue_operator_session``'s MFA gate (``iam_operator_mfa`` enrolled
        with ``last_verified_at`` stamped); a session is minted only once MFA
        has been completed.
        """
        return await self._mfa.record_mfa_verified(phone)

    # -- Session delegation (ADR-0006, ticket #166) ------------------------

    async def issue_session(self, phone: str) -> SessionResult:
        """Mint an access JWT for a verified patient (delegated to ``SessionFacade``)."""
        return await self._sessions.issue_session(phone)

    async def issue_operator_session(self, phone: str, code: str) -> SessionResult:
        """Mint an operator-scoped access JWT after MFA (T07, #250; S8, #261).

        Delegated to ``SessionFacade``; the session's ``scope`` resolves to
        ``operator`` so the gateway's ``require_operator`` admits the caller.
        The ``code`` is an RFC-6238 TOTP code verified against the operator's
        enrolled MFA secret (S8).
        """
        return await self._sessions.issue_operator_session(phone, code)

    async def validate_token(self, token: str) -> ValidatedAccessToken:
        """Resolve a valid access JWT to its scope (delegated to ``SessionFacade``)."""
        return await self._sessions.validate_token(token)

    async def refresh_session(self, refresh_token: str) -> SessionResult:
        """Rotate an opaque refresh token into a fresh session (delegated to ``SessionFacade``)."""
        return await self._sessions.refresh_session(refresh_token)

    # -- Protected-route reads (PHASE-2.6 T05, #196) -----------------------

    async def identity_phone(self, identity_id: int) -> str:
        """The E.164 phone for an identity id (one-column lookup).

        PHASE-2.6 T05 (#196, decision D4): the protected ``/v1/me`` route
        resolves the caller's phone through this seam so its response can
        name a truthful identity while the gateway-side principal stays free
        of database reads. Read-only, in its own transaction - the route
        holds no open transaction - and an id with no row (a stale token's
        subject) degrades to ``""`` exactly like the audit emitter's lookup.
        """
        async with self._engine.begin() as connection:
            return await _identity_phone(connection, identity_id)

    async def partner_role_status(self, identity_id: int) -> str | None:
        """The lifecycle status of the ``partner`` role grant for ``identity_id``.

        T03 (#248) observability seam: ``None`` when the identity holds no
        ``partner`` grant, otherwise the grant status (``Active`` or
        ``Suspended``). Lets the event-chain tests and any consumer-facing
        surface read the role outcome through the facade, never the internals.
        """
        async with self._engine.begin() as connection:
            return await _partner_role_status(connection, identity_id)

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
