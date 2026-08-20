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
from modules.iam.domain import events
from modules.iam.domain.exceptions import (
    InvalidAccessTokenError as InvalidAccessTokenError,
)
from modules.iam.domain.shared import (
    OtpSender as OtpSender,
)
from modules.iam.identity_facade import (
    IdentityFacade as IdentityFacade,
)
from modules.iam.identity_facade import (
    RegisterPatientResult as RegisterPatientResult,
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
        self._sessions = SessionFacade(
            engine,
            clock=clock,
            access_token_signing_key=access_token_signing_key,
            access_token_ttl_seconds=access_token_ttl_seconds,
            refresh_token_ttl_seconds=refresh_token_ttl_seconds,
        )

    # -- Identity delegation (ADR-0006, ticket #169) -----------------------

    async def register_patient(self, phone: str) -> RegisterPatientResult:
        """Begin-or-resume: create the identity on first use, else resolve it."""
        return await self._identity.register_patient(phone)

    # -- OTP delegation (ADR-0006, ticket #168) ----------------------------

    async def verify_otp(self, phone: str, otp: str) -> VerifyOtpResult:
        """Verify a submitted 6-digit code against the identity's latest challenge."""
        return await self._otp.verify_otp(phone, otp)

    async def resend_otp(self, phone: str) -> ResendOtpResult:
        """Request a fresh code: latest-wins over the pending challenge."""
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
