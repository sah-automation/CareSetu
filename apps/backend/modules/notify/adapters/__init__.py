"""MOD-010: event handlers for the ``notify`` module (coding-standards §2).

``register_handlers`` is the composition-root seam (PHASE-1 T4, #30):
the worker entrypoint calls it to register this module's handlers on
the shared ``HandlerRegistry``. T11 (#246) adds the notify module's first
consumer: ``notification.failed``. When the EXT-003 delivery webhook reports a
WhatsApp message failed/undeliverable, this consumer re-routes the
terminal-status message to the SMS fallback channel (ADR-0009). An SMS-leg
failure is terminal - the fallback chain is WhatsApp -> SMS, never loops.

The handler is ledger-idempotent (ADR-0002 §3): its ``consumed_events`` row is
written in the same transaction as the effect, so replaying a delivered
``event_id`` is a no-op.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import get_settings
from bus.envelope import Envelope
from bus.events import (
    EVENT_NOTIFICATION_FAILED,
    EVENT_PARTNER_ACTIVATED,
    EVENT_PARTNER_REJECTED,
)
from bus.handler_harness import run_handler
from bus.registry import HandlerRegistry
from modules.iam.facade import IamFacade, build_sms_adapter
from modules.notify.adapters.transport import DeliveryRequest
from modules.notify.domain.consumer import (
    PARTNER_ACTIVATED_MESSAGE,
    PartnerActivatedPayload,
    PartnerRejectedPayload,
    build_partner_rejected_message,
)
from modules.notify.domain.events import NotificationFailedPayload
from modules.notify.facade import (
    NOTIFY_SCHEMA,
    build_notify_facade,
    insert_notification,
)

logger = logging.getLogger(__name__)


async def _resolve_recipient_phone(identity_id: int) -> str:
    """Resolve the partner's E.164 phone through the notify -> iam contact seam.

    T12 (ticket #255): the terminal-status payloads carry only ``identity_id``,
    never a phone. The documented contact seam (internal-modules §4.1,
    MOD-010 -> MOD-001 ``resolve_contact``) is ``IamFacade.identity_phone``;
    ``iam.facade`` re-exports ``build_sms_adapter`` so notify can construct the
    facade without crossing a module boundary. A missing identity degrades to
    ``""`` and the consumer skips the send (see ``_deliver_terminal_status``).
    """
    settings = get_settings()
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        facade = IamFacade(
            engine=engine,
            sms_adapter=build_sms_adapter(settings),
            access_token_signing_key=settings.gateway_jwt_signing_key,
            access_token_ttl_seconds=settings.gateway_access_token_ttl_seconds,
            refresh_token_ttl_seconds=settings.gateway_refresh_token_ttl_seconds,
        )
        return await facade.identity_phone(identity_id)
    finally:
        await engine.dispose()


async def _deliver_terminal_status(
    connection: AsyncConnection, identity_id: int, message: str
) -> None:
    """Send a terminal-status message WhatsApp-first (ADR-0009, T12).

    Resolves the recipient phone through the iam seam, records the
    ``notify_notifications`` row in the same transaction as the ledger, and
    enqueues the WhatsApp-first delivery with the row id as
    ``DeliveryRequest.notification_id`` (so a WhatsApp failure re-routes the
    SAME message to SMS via ``notification.failed``). An identity with no
    resolvable phone degrades to a logged skip - the notification cannot be
    sent for a recipient we cannot address, but the ledger still advances.
    """
    phone = await _resolve_recipient_phone(identity_id)
    if not phone:
        logger.warning(
            "terminal-status notification skipped: identity has no resolvable phone; "
            "identity_id=%s",
            identity_id,
        )
        return
    notification_id = await insert_notification(connection, phone, message)
    facade = build_notify_facade()
    await facade.send_with_fallback(
        DeliveryRequest(
            notification_id=notification_id,
            recipient_phone_e164=phone,
            message=message,
        )
    )


def register_handlers(registry: HandlerRegistry) -> None:
    """Register the notify module's event handlers + payload models.

    MOD-010 owns the payload model for its own ``notification.failed`` event:
    the dispatcher reconstructs a claimed ``notify_outbox`` row with it before
    fan-out. For the partner terminal events it registers handlers ONLY - the
    payload model is owned once by MOD-001's iam adapter (``register_payload_model``
    raises on a duplicate), and each handler revalidates the registry-carried
    model into its own mirror inside ``run_handler``.
    """
    registry.register_payload_model(EVENT_NOTIFICATION_FAILED, NotificationFailedPayload)
    registry.register(EVENT_NOTIFICATION_FAILED, _on_notification_failed)

    # T12 (ticket #255): partner terminal-status notification subscribers. The
    # rejected handler's body carries the refusal reason; non-terminal phases
    # (``partner.verification_started``, re-submission confirms) register NO
    # consumer here - they stay in-app only (ADR-0009).
    registry.register(EVENT_PARTNER_ACTIVATED, _on_partner_activated)
    registry.register(EVENT_PARTNER_REJECTED, _on_partner_rejected)


async def _on_partner_activated(envelope: Envelope[BaseModel]) -> None:
    """Consume ``partner.activated``: WhatsApp the partner their account is live."""

    async def _impl(connection: AsyncConnection, payload: PartnerActivatedPayload) -> None:
        await _deliver_terminal_status(connection, payload.identity_id, PARTNER_ACTIVATED_MESSAGE)

    await run_handler(
        envelope,
        PartnerActivatedPayload,
        _impl,
        "send_partner_activated_notification",
        NOTIFY_SCHEMA,
    )


async def _on_partner_rejected(envelope: Envelope[BaseModel]) -> None:
    """Consume ``partner.rejected``: WhatsApp the partner the refusal + reason."""

    async def _impl(connection: AsyncConnection, payload: PartnerRejectedPayload) -> None:
        await _deliver_terminal_status(
            connection,
            payload.identity_id,
            build_partner_rejected_message(payload.reason),
        )

    await run_handler(
        envelope,
        PartnerRejectedPayload,
        _impl,
        "send_partner_rejected_notification",
        NOTIFY_SCHEMA,
    )


async def _on_notification_failed(envelope: Envelope[BaseModel]) -> None:
    """Consume ``notification.failed``: re-route a WhatsApp failure to SMS.

    Ledger first, re-route second, one transaction boundary for the ledger; a
    redelivered ``event_id`` finds its ledger row and skips (at-least-once).
    Only a WhatsApp-leg failure re-routes to SMS (ADR-0009); an SMS-leg failure
    is terminal - the fallback chain never loops. The SMS re-route is a
    background enqueue, so the facade is resolved from settings at delivery time
    (mock channels in CI/local, configured providers in staging/prod). The
    facade is closed over by the handler callback, so ``run_handler`` can carry
    the resolved facade without touching the ledger engine lifecycle.
    """
    facade = build_notify_facade()

    async def _impl(connection: AsyncConnection, payload: NotificationFailedPayload) -> None:
        del connection
        if payload.channel == "wa":
            await facade.enqueue_sms_fallback(
                DeliveryRequest(
                    notification_id=payload.notification_id,
                    recipient_phone_e164=payload.recipient_phone_e164,
                    message=payload.message,
                )
            )

    await run_handler(
        envelope,
        NotificationFailedPayload,
        _impl,
        "on_notification_failed",
        NOTIFY_SCHEMA,
    )
