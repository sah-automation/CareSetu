"""MOD-010 Notifications: typed public sync API (T11, ticket #246).

The only legal cross-module import target for the ``notify`` module
(coding-standards §2, ADR-0003). This is the transport/channel engine for the
WhatsApp-first / SMS-fallback partner notification channel (ADR-0009): it
exposes the send-with-fallback primitive and owns both channel delivery queues,
so delivery stays backgrounded (non-blocking) and any channel failure routes
through ``notification.failed`` back to a fallback channel.

The facade is a thin coordinator: it does not build or validate message bodies
(those arrive from the calling module, e.g. T12 partner terminal statuses). It
owns the two ``NotificationDeliveryQueue`` instances - WhatsApp attempted
first, SMS as the fallback - and the delivery-failed emission hook that turns an
undeliverable WhatsApp send into a ``notification.failed`` outbox event.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import get_settings
from bus.outbox_writer import write_outbox
from modules.notify.adapters.sms import build_notify_sms_channel
from modules.notify.adapters.transport import (
    ChannelAdapter,
    DeliveryRequest,
    NotificationDeliveryQueue,
)
from modules.notify.adapters.whatsapp import build_whatsapp_channel
from modules.notify.domain.events import (
    NotificationFailedPayload,
    notification_failed_envelope,
)
from modules.notify.outbox import NOTIFY_OUTBOX_TABLE
from modules.notify.schema.models import notify_notifications

NOTIFY_SCHEMA = "notify"

NotificationFailedEmitter = Callable[[NotificationFailedPayload], Awaitable[None]]


class NotifyFacade:
    """Typed public facade for notify: sends with a WhatsApp -> SMS fallback.

    ``wa_failed_emitter`` is injectable so the transport engine is testable
    without a database: it is awaited once a WhatsApp delivery has exhausted
    every retry and must publish ``notification.failed`` (the production wiring
    writes to the notify outbox; tests record the emission).
    """

    def __init__(
        self,
        whatsapp_adapter: ChannelAdapter,
        sms_adapter: ChannelAdapter,
        wa_failed_emitter: NotificationFailedEmitter,
    ) -> None:
        self._whatsapp_queue = NotificationDeliveryQueue(
            whatsapp_adapter, on_delivery_failed=self._on_wa_delivery_failed
        )
        self._sms_queue = NotificationDeliveryQueue(sms_adapter)
        self._wa_failed_emitter = wa_failed_emitter

    @property
    def whatsapp_queue(self) -> NotificationDeliveryQueue:
        """The background WhatsApp delivery queue (read surface for tests)."""
        return self._whatsapp_queue

    @property
    def sms_queue(self) -> NotificationDeliveryQueue:
        """The background SMS delivery queue (read surface for tests)."""
        return self._sms_queue

    async def send_with_fallback(self, request: DeliveryRequest) -> None:
        """Route ``request`` WhatsApp-first: enqueue a background WhatsApp send.

        Non-blocking (third-party-integration-standards §1): the caller receives
        its flow state immediately and the provider call runs in the background.
        If that WhatsApp delivery later exhausts every retry, the
        ``_on_wa_delivery_failed`` hook publishes ``notification.failed`` and the
        subscribed handler re-routes the same request to SMS (ADR-0009).
        """
        self._whatsapp_queue.enqueue(request)

    async def enqueue_sms_fallback(self, request: DeliveryRequest) -> None:
        """Re-route ``request`` to the SMS channel after a WhatsApp failure.

        Called by the ``notification.failed`` consumer (adapters/__init__) only
        for a WhatsApp-leg failure; an SMS-leg failure never re-routes, so the
        fallback chain cannot loop.
        """
        self._sms_queue.enqueue(request)

    async def _on_wa_delivery_failed(self, request: DeliveryRequest) -> None:
        """Publish ``notification.failed`` for an undeliverable WhatsApp send.

        The WhatsApp queue's ``on_delivery_failed`` hook; runs outside the
        request path and awaits the (injectable) emitter that lands the event on
        the notify outbox or, in tests, records it.
        """
        await self._wa_failed_emitter(
            NotificationFailedPayload(
                notification_id=request.notification_id,
                channel="wa",
                recipient_phone_e164=request.recipient_phone_e164,
                message=request.message,
            )
        )

    async def flush(self) -> None:
        """Await every pending delivery on both channels (deterministic test hook)."""
        await self._whatsapp_queue.flush()
        await self._sms_queue.flush()


async def insert_notification(
    connection: AsyncConnection, recipient_phone_e164: str, message: str
) -> int:
    """Persist a terminal-status notification row; return its id.

    T12 (ticket #255): called by the ``partner.activated`` / ``partner.rejected``
    consumers inside their ledger transaction. The row records the WhatsApp-first
    attempt (ADR-0009) as ``channel='wa'``, ``status='pending'``; its id becomes
    ``DeliveryRequest.notification_id`` so a ``notification.failed`` on the
    WhatsApp leg can re-route the same message to SMS.
    """
    result = await connection.execute(
        notify_notifications.insert()
        .values(
            recipient_phone_e164=recipient_phone_e164,
            message=message,
            channel="wa",
            status="pending",
        )
        .returning(notify_notifications.c.id)
    )
    return int(result.scalar_one())


def _emit_notification_failed_to_outbox(payload: NotificationFailedPayload) -> Awaitable[None]:
    """Production ``notification.failed`` emitter: write it to the notify outbox.

    Runs in its own short-lived transaction (the emission happens outside the
    issuing request's transaction, in the background delivery path), mirroring
    the audit module's short-lived-engine handler pattern.
    """

    async def _emit() -> None:
        engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
        try:
            async with engine.begin() as connection:
                await write_outbox(
                    connection,
                    NOTIFY_SCHEMA,
                    NOTIFY_OUTBOX_TABLE,
                    notification_failed_envelope(
                        notification_id=payload.notification_id,
                        channel=payload.channel,
                        recipient_phone_e164=payload.recipient_phone_e164,
                        message=payload.message,
                        error_code=payload.error_code,
                    ),
                )
        finally:
            await engine.dispose()

    return _emit()


def build_notify_facade() -> NotifyFacade:
    """Resolve the notify facade from settings; mock channels are the default."""
    settings = get_settings()
    return NotifyFacade(
        build_whatsapp_channel(settings),
        build_notify_sms_channel(settings),
        wa_failed_emitter=_emit_notification_failed_to_outbox,
    )
