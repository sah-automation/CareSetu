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
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.config import get_settings
from bus.envelope import Envelope
from bus.events import EVENT_NOTIFICATION_FAILED
from bus.ledger import record_consumed_event
from bus.registry import HandlerRegistry
from modules.notify.adapters.transport import DeliveryRequest
from modules.notify.domain.events import NotificationFailedPayload
from modules.notify.facade import NOTIFY_SCHEMA, build_notify_facade

logger = logging.getLogger(__name__)


def register_handlers(registry: HandlerRegistry) -> None:
    """Register the notify module's event handlers + payload models.

    MOD-010 owns the payload model for its own ``notification.failed`` event:
    the dispatcher reconstructs a claimed ``notify_outbox`` row with it before
    fan-out.
    """
    registry.register_payload_model(EVENT_NOTIFICATION_FAILED, NotificationFailedPayload)
    registry.register(EVENT_NOTIFICATION_FAILED, _on_notification_failed)


async def _on_notification_failed(envelope: Envelope[BaseModel]) -> None:
    """Consume ``notification.failed``: re-route a WhatsApp failure to SMS.

    Ledger first, re-route second, one transaction boundary for the ledger; a
    redelivered ``event_id`` finds its ledger row and skips (at-least-once).
    Only a WhatsApp-leg failure re-routes to SMS (ADR-0009); an SMS-leg failure
    is terminal - the fallback chain never loops. The SMS re-route is a
    background enqueue, so the facade is resolved from settings at delivery time
    (mock channels in CI/local, configured providers in staging/prod).
    """
    payload = envelope.payload
    if not isinstance(payload, NotificationFailedPayload):
        payload = NotificationFailedPayload.model_validate(payload.model_dump())

    facade = build_notify_facade()
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            delivered = await record_consumed_event(
                connection,
                NOTIFY_SCHEMA,
                envelope,
                handler_result={"handler": "on_notification_failed"},
            )
            if not delivered:
                return
            if payload.channel == "wa":
                await facade.enqueue_sms_fallback(
                    DeliveryRequest(
                        notification_id=payload.notification_id,
                        recipient_phone_e164=payload.recipient_phone_e164,
                        message=payload.message,
                    )
                )
    finally:
        await engine.dispose()
