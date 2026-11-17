"""MOD-001: event handlers for the ``iam`` module (coding-standards §2).

``register_handlers`` is the composition-root seam (PHASE-1 T4, #30):
the worker entrypoint calls it to register this module's handlers on
the shared ``HandlerRegistry``. PHASE-5 T03 (#248) registers the
activation-gated role consumers: ``partner.activated`` grants the
``partner`` role to the partner's identity, and ``partner.rejected`` /
``credential.invalidated`` suspend it, so access follows verification
state (ADR-0008). The identity is fixed at registration (ADR-0010) and
rides each event payload, so this consumer never reads the partner
schema (ADR-0003 module isolation).

Every handler is idempotent (ADR-0002 §3): its ``consumed_events`` ledger
row is written in the SAME transaction as the role grant/suspend, so
replaying a delivered ``event_id`` is a no-op and a crash rolls both back
together.
"""

from __future__ import annotations

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncConnection

from bus.envelope import Envelope
from bus.events import (
    EVENT_CREDENTIAL_INVALIDATED,
    EVENT_OPERATOR_ACTIVE_CHANGED,
    EVENT_OPERATOR_INVITED,
    EVENT_OPERATOR_MFA_FAILED,
    EVENT_OPERATOR_TIER_CHANGED,
    EVENT_OTP_FAILED,
    EVENT_OTP_SENT,
    EVENT_PARTNER_ACTIVATED,
    EVENT_PARTNER_REJECTED,
    EVENT_PATIENT_AUTH_FAILED,
    EVENT_PATIENT_REGISTERED,
    EVENT_PATIENT_VERIFIED,
)
from bus.handler_harness import run_handler
from bus.registry import HandlerRegistry
from modules.iam.domain.consumer import (
    CredentialInvalidatedPayload,
    PartnerActivatedPayload,
    PartnerRejectedPayload,
)
from modules.iam.domain.events import (
    OperatorActiveChangedPayload,
    OperatorInvitedPayload,
    OperatorMfaFailedPayload,
    OperatorTierChangedPayload,
    OtpFailedPayload,
    OtpSentPayload,
    PatientAuthFailedPayload,
    PatientRegisteredPayload,
    PatientVerifiedPayload,
)
from modules.iam.session_facade import (
    grant_partner_role,
    suspend_partner_role,
)

_IAM_SCHEMA = "iam"


def register_handlers(registry: HandlerRegistry) -> None:
    """Register the iam module's event handlers + payload models."""
    # MOD-001 owns the payload models for all events it PRODUCES into its
    # outbox (patient.*, otp.*, operator.*) and for credential.invalidated
    # (Audit expects IAM to own this payload model per Audit adapter).
    # The dispatcher reconstructs the claimed outbox row with them before
    # fan-out, so a typed payload - never a raw dict - reaches every handler.
    #
    # NOTE: partner.activated and partner.rejected are PRODUCED by the Partner
    # module (they go into partner.partner_outbox). The producer owns the
    # payload model, so Partner registers them. IAM only registers handlers
    # for these events (consumer pattern).
    for event_type, payload_model in (
        (EVENT_PATIENT_REGISTERED, PatientRegisteredPayload),
        (EVENT_OTP_SENT, OtpSentPayload),
        (EVENT_PATIENT_VERIFIED, PatientVerifiedPayload),
        (EVENT_OTP_FAILED, OtpFailedPayload),
        (EVENT_PATIENT_AUTH_FAILED, PatientAuthFailedPayload),
        (EVENT_OPERATOR_INVITED, OperatorInvitedPayload),
        (EVENT_OPERATOR_MFA_FAILED, OperatorMfaFailedPayload),
        (EVENT_OPERATOR_TIER_CHANGED, OperatorTierChangedPayload),
        (EVENT_OPERATOR_ACTIVE_CHANGED, OperatorActiveChangedPayload),
        (EVENT_CREDENTIAL_INVALIDATED, CredentialInvalidatedPayload),
    ):
        registry.register_payload_model(event_type, payload_model)

    async def grant_or_restore_partner_role(envelope: Envelope[BaseModel]) -> None:
        """Consume ``partner.activated``: grant the ``partner`` role.

        Ledger first, grant second, one transaction: a redelivered
        ``event_id`` finds its ledger row and skips the grant (at-least-once);
        the grant is itself idempotent, so an already-Active row is a no-op.
        """

        async def _impl(connection: AsyncConnection, payload: PartnerActivatedPayload) -> None:
            await grant_partner_role(connection, payload.identity_id)

        await run_handler(
            envelope,
            PartnerActivatedPayload,
            _impl,
            "grant_partner_role",
            _IAM_SCHEMA,
        )

    async def suspend_partner_role_on_rejection(envelope: Envelope[BaseModel]) -> None:
        """Consume ``partner.rejected``: suspend the ``partner`` role.

        Ledger first, suspend second, one transaction: a redelivered
        ``event_id`` skips the suspend; the suspend is idempotent even when no
        grant row exists (a never-activated partner).
        """

        async def _impl(connection: AsyncConnection, payload: PartnerRejectedPayload) -> None:
            await suspend_partner_role(connection, payload.identity_id)

        await run_handler(
            envelope,
            PartnerRejectedPayload,
            _impl,
            "suspend_partner_role",
            _IAM_SCHEMA,
        )

    async def suspend_partner_role_on_invalidated(envelope: Envelope[BaseModel]) -> None:
        """Consume ``credential.invalidated``: suspend the ``partner`` role.

        The deactivation path (spec phase-5 "Deactivation"): an Active
        partner's re-verification failed or the grace window lapsed, so the
        IAM role is suspended to match the credential no longer being valid.
        """

        async def _impl(connection: AsyncConnection, payload: CredentialInvalidatedPayload) -> None:
            await suspend_partner_role(connection, payload.identity_id)

        await run_handler(
            envelope,
            CredentialInvalidatedPayload,
            _impl,
            "suspend_partner_role",
            _IAM_SCHEMA,
        )

    registry.register(EVENT_PARTNER_ACTIVATED, grant_or_restore_partner_role)
    registry.register(EVENT_PARTNER_REJECTED, suspend_partner_role_on_rejection)
    registry.register(EVENT_CREDENTIAL_INVALIDATED, suspend_partner_role_on_invalidated)
