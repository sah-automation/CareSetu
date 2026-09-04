"""PHASE-5 T12: notify partner terminal-status consumer (ticket #255).

Pins the MOD-010 consumer contract without a database:
- ``partner.activated`` sends the fixed activated body; ``partner.rejected``
  sends the refusal body with the specific reason (ADR-0009),
- each goes out WhatsApp-first via ``facade.send_with_fallback`` with the
  ``notify_notifications`` row id, in the same transaction as the ledger
  (replay = no-op, ADR-0002 §3),
- an identity with no resolvable phone skips the send but still advances the
  ledger,
- notify registers handlers ONLY for the terminal events - the payload model is
  owned by MOD-001 (``register_payload_model`` raises on duplicates) and
  non-terminal phases register nothing (in-app only).

Prior art: ``test_iam_partner_role_consumer.py`` and ``test_audit_consumer.py``.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from pydantic import BaseModel

from bus.envelope import Envelope
from bus.events import (
    EVENT_PARTNER_ACTIVATED,
    EVENT_PARTNER_REJECTED,
    EVENT_PARTNER_VERIFICATION_STARTED,
)
from bus.registry import HandlerRegistry
from modules.notify.adapters import register_handlers
from modules.notify.adapters.transport import DeliveryRequest
from modules.notify.domain.consumer import (
    PARTNER_ACTIVATED_MESSAGE,
    PartnerActivatedPayload,
    PartnerRejectedPayload,
    build_partner_rejected_message,
)
from modules.notify.facade import NOTIFY_SCHEMA

_PHONE = "+919876543210"


def _activated_payload() -> PartnerActivatedPayload:
    return PartnerActivatedPayload(partner_id=3, identity_id=9, decision_by=77)


def _rejected_payload() -> PartnerRejectedPayload:
    return PartnerRejectedPayload(
        partner_id=3, identity_id=9, reason="doc unreadable", round=1, decision_by=77
    )


def _envelope(payload: BaseModel, event_type: str) -> Envelope[BaseModel]:
    return Envelope[BaseModel](
        event_id=uuid4(),
        event_type=event_type,  # type: ignore[arg-type]
        producer="partner",
        payload=payload,
    )


def _registered_handler(event_type: str) -> tuple[HandlerRegistry, object]:
    registry = HandlerRegistry()
    register_handlers(registry)
    handlers = registry.handlers_for(event_type)  # type: ignore[arg-type]
    assert len(handlers) == 1
    return registry, handlers[0]


def _fake_engine():
    engine = MagicMock()
    connection = AsyncMock()
    engine.begin.return_value.__aenter__ = AsyncMock(return_value=connection)
    engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)
    engine.dispose = AsyncMock()
    return engine, connection


class _RecordingFacade:
    def __init__(self) -> None:
        self.requests: list[DeliveryRequest] = []

    async def send_with_fallback(self, request: DeliveryRequest) -> None:
        self.requests.append(request)


def test_partner_terminal_events_register_a_single_consumer_but_no_payload_model() -> None:
    registry = HandlerRegistry()
    register_handlers(registry)
    assert len(registry.handlers_for(EVENT_PARTNER_ACTIVATED)) == 1  # type: ignore[arg-type]
    assert len(registry.handlers_for(EVENT_PARTNER_REJECTED)) == 1  # type: ignore[arg-type]
    # MOD-001 owns the payload model for both terminal events; notify must not
    # register it again (HandlerRegistry raises on a duplicate) and revalidates
    # the registry-carried model into its own mirror at delivery time.
    assert registry.payload_model_for(EVENT_PARTNER_ACTIVATED) is None
    assert registry.payload_model_for(EVENT_PARTNER_REJECTED) is None
    # Non-terminal phases stay in-app only: no notify consumer, no model.
    assert registry.handlers_for(EVENT_PARTNER_VERIFICATION_STARTED) == ()  # type: ignore[arg-type]
    assert registry.payload_model_for(EVENT_PARTNER_VERIFICATION_STARTED) is None


async def test_activated_handler_records_ledger_then_sends_whatsapp_first() -> None:
    _, handler = _registered_handler(EVENT_PARTNER_ACTIVATED)
    envelope = _envelope(_activated_payload(), EVENT_PARTNER_ACTIVATED)
    engine, connection = _fake_engine()
    recorder = _RecordingFacade()

    with (
        patch("bus.handler_harness._delivery_engine", return_value=engine),
        patch(
            "bus.handler_harness.record_consumed_event",
            new_callable=AsyncMock,
            return_value=True,
        ) as record_consumed,
        patch(
            "modules.notify.adapters._resolve_recipient_phone",
            new_callable=AsyncMock,
            return_value=_PHONE,
        ) as resolve_phone,
        patch(
            "modules.notify.adapters.insert_notification",
            new_callable=AsyncMock,
            return_value=42,
        ) as insert_notification,
        patch(
            "modules.notify.adapters.build_notify_facade",
            return_value=recorder,
        ),
    ):
        await handler(envelope)

    record_consumed.assert_awaited_once()
    assert record_consumed.await_args.args[1] == NOTIFY_SCHEMA
    assert record_consumed.await_args.args[2].event_id == envelope.event_id
    resolve_phone.assert_awaited_once_with(9)
    insert_notification.assert_awaited_once_with(connection, _PHONE, PARTNER_ACTIVATED_MESSAGE)
    assert recorder.requests == [
        DeliveryRequest(
            notification_id=42,
            recipient_phone_e164=_PHONE,
            message=PARTNER_ACTIVATED_MESSAGE,
        )
    ]


async def test_rejected_handler_carries_the_specific_reason_into_the_body() -> None:
    _, handler = _registered_handler(EVENT_PARTNER_REJECTED)
    envelope = _envelope(_rejected_payload(), EVENT_PARTNER_REJECTED)
    engine, connection = _fake_engine()
    recorder = _RecordingFacade()

    with (
        patch("bus.handler_harness._delivery_engine", return_value=engine),
        patch(
            "bus.handler_harness.record_consumed_event",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "modules.notify.adapters._resolve_recipient_phone",
            new_callable=AsyncMock,
            return_value=_PHONE,
        ),
        patch(
            "modules.notify.adapters.insert_notification",
            new_callable=AsyncMock,
            return_value=42,
        ) as insert_notification,
        patch(
            "modules.notify.adapters.build_notify_facade",
            return_value=recorder,
        ),
    ):
        await handler(envelope)

    message = build_partner_rejected_message("doc unreadable")
    assert "doc unreadable" in message
    insert_notification.assert_awaited_once_with(connection, _PHONE, message)
    assert recorder.requests == [
        DeliveryRequest(notification_id=42, recipient_phone_e164=_PHONE, message=message)
    ]


async def test_terminal_handlers_skip_replay_when_ledger_already_has_event_id() -> None:
    _, handler = _registered_handler(EVENT_PARTNER_ACTIVATED)
    envelope = _envelope(_activated_payload(), EVENT_PARTNER_ACTIVATED)
    engine, _connection = _fake_engine()

    with (
        patch("bus.handler_harness._delivery_engine", return_value=engine),
        patch(
            "bus.handler_harness.record_consumed_event",
            new_callable=AsyncMock,
            return_value=False,
        ) as record_consumed,
        patch(
            "modules.notify.adapters._resolve_recipient_phone",
            new_callable=AsyncMock,
        ) as resolve_phone,
        patch(
            "modules.notify.adapters.insert_notification",
            new_callable=AsyncMock,
        ) as insert_notification,
        patch(
            "modules.notify.adapters.build_notify_facade",
        ),
    ):
        await handler(envelope)

    record_consumed.assert_awaited_once()
    resolve_phone.assert_not_awaited()
    insert_notification.assert_not_awaited()


async def test_terminal_handler_skips_send_when_identity_has_no_resolvable_phone() -> None:
    _, handler = _registered_handler(EVENT_PARTNER_ACTIVATED)
    envelope = _envelope(_activated_payload(), EVENT_PARTNER_ACTIVATED)
    engine, _connection = _fake_engine()

    with (
        patch("bus.handler_harness._delivery_engine", return_value=engine),
        patch(
            "bus.handler_harness.record_consumed_event",
            new_callable=AsyncMock,
            return_value=True,
        ) as record_consumed,
        patch(
            "modules.notify.adapters._resolve_recipient_phone",
            new_callable=AsyncMock,
            return_value="",
        ),
        patch(
            "modules.notify.adapters.insert_notification",
            new_callable=AsyncMock,
        ) as insert_notification,
        patch(
            "modules.notify.adapters.build_notify_facade",
        ),
    ):
        await handler(envelope)

    record_consumed.assert_awaited_once()
    insert_notification.assert_not_awaited()


class _AlienPartnerActivatedPayload(BaseModel):
    parent_partner_id: int = 3
    partner_id: int
    identity_id: int
    decision_by: int


async def test_handler_revalidates_a_registry_carried_partner_model() -> None:
    """The handler works on whatever model MOD-001 registered, not just its mirror.

    In the composition root the outbox row is reconstructed with iam's payload
    class (the registry stores only one model per event type); the notify
    handler revalidates that registry-carried model into its own mirror inside
    ``_run_handler``. The alien class carries the same fields plus one extra,
    which is ignored by the mirror.
    """
    _, handler = _registered_handler(EVENT_PARTNER_ACTIVATED)
    payload = _AlienPartnerActivatedPayload(partner_id=3, identity_id=9, decision_by=77)
    # Simulate the iam-registered model: a different class, same fields.
    assert not isinstance(payload, PartnerActivatedPayload)
    envelope = _envelope(payload, EVENT_PARTNER_ACTIVATED)
    engine, _connection = _fake_engine()
    recorder = _RecordingFacade()

    with (
        patch("bus.handler_harness._delivery_engine", return_value=engine),
        patch(
            "bus.handler_harness.record_consumed_event",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "modules.notify.adapters._resolve_recipient_phone",
            new_callable=AsyncMock,
            return_value=_PHONE,
        ) as resolve_phone,
        patch(
            "modules.notify.adapters.insert_notification",
            new_callable=AsyncMock,
            return_value=42,
        ),
        patch(
            "modules.notify.adapters.build_notify_facade",
            return_value=recorder,
        ),
    ):
        await handler(envelope)

    resolve_phone.assert_awaited_once_with(9)
    assert recorder.requests == [
        DeliveryRequest(
            notification_id=42,
            recipient_phone_e164=_PHONE,
            message=PARTNER_ACTIVATED_MESSAGE,
        )
    ]


def test_activated_message_is_the_fixed_terminal_template() -> None:
    assert PARTNER_ACTIVATED_MESSAGE
    assert "{" not in PARTNER_ACTIVATED_MESSAGE and "}" not in PARTNER_ACTIVATED_MESSAGE


@pytest.mark.parametrize(
    "reason", ["doc unreadable", "step1_fail", "re-submitted documents unclear"]
)
def test_rejected_message_embeds_the_reason_verbatim(reason: str) -> None:
    message = build_partner_rejected_message(reason)
    assert reason in message
    assert not message.startswith(reason)
