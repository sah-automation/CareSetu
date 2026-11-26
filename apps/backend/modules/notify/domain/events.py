"""MOD-010: canonical notify event payloads (T11, ticket #246).

The ``notification.failed`` event names the channel delivery that failed and the
owning notification row, so the consumer can re-route the terminal-status
message to the fallback channel (ADR-0009). Event names follow the registry
dot-notation in ``internal-modules.md`` §4.2; payloads are typed Pydantic models
(coding-standards §3) and never carry the API key or raw provider payload.
"""

from __future__ import annotations

from typing import Literal
from uuid import uuid4

from pydantic import BaseModel

from bus.envelope import Envelope
from bus.events import EVENT_NOTIFICATION_FAILED

PRODUCER_MODULE = "notify"


class NotificationFailedPayload(BaseModel):
    """Subject of ``notification.failed``: a channel delivery that failed.

    Emitted when a delivery has exhausted every retry on ``channel``. The
    consumer re-routes to SMS when the failed channel was WhatsApp (the only
    first-hop channel, ADR-0009); an SMS failure is terminal - there is no
    further fallback, so re-routing would loop. ``notification_id`` names the
    row in ``notify.notifications``; ``recipient_phone_e164`` and ``message``
    carry the re-route payload.
    """

    notification_id: int
    channel: Literal["wa", "sms"]
    recipient_phone_e164: str
    message: str
    error_code: str | None = None


def notification_failed_envelope(
    notification_id: int,
    channel: Literal["wa", "sms"],
    recipient_phone_e164: str,
    message: str,
    error_code: str | None = None,
) -> Envelope[NotificationFailedPayload]:
    """Build the ``notification.failed`` envelope for the notify outbox."""
    return Envelope[NotificationFailedPayload](
        event_id=uuid4(),
        event_type=EVENT_NOTIFICATION_FAILED,
        producer=PRODUCER_MODULE,
        payload=NotificationFailedPayload(
            notification_id=notification_id,
            channel=channel,
            recipient_phone_e164=recipient_phone_e164,
            message=message,
            error_code=error_code,
        ),
    )
