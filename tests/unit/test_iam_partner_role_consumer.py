"""PHASE-5 T03: iam partner role grant/deny consumer (ticket #248).

Pins the MOD-001 consumer contract without a database: the handler wiring
(ledger-first idempotency, replay skip), plus the facade grant/suspend
mutations. Prior art: the audit consumer handler tests
(``test_audit_consumer.py``) and the iam role-grant helpers.
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from pydantic import BaseModel

from bus.envelope import Envelope
from bus.events import (
    EVENT_CREDENTIAL_INVALIDATED,
    EVENT_PARTNER_ACTIVATED,
    EVENT_PARTNER_REJECTED,
)
from bus.registry import HandlerRegistry
from modules.iam.adapters import register_handlers
from modules.iam.domain.consumer import (
    CredentialInvalidatedPayload,
    PartnerActivatedPayload,
    PartnerRejectedPayload,
)
from modules.iam.schema.models import iam_role_grants
from modules.iam.session_facade import (
    _IAM_SCHEMA,
    grant_partner_role,
    suspend_partner_role,
)


@dataclass(frozen=True)
class _GrantRow:
    id: int


def _activated_payload() -> PartnerActivatedPayload:
    return PartnerActivatedPayload(partner_id=3, identity_id=9, decision_by=77)


def _rejected_payload() -> PartnerRejectedPayload:
    return PartnerRejectedPayload(
        partner_id=3, identity_id=9, reason="doc unreadable", round=1, decision_by=77
    )


def _invalidated_payload() -> CredentialInvalidatedPayload:
    return CredentialInvalidatedPayload(
        partner_id=3, identity_id=9, credential_id=5, reason="grace lapsed"
    )


def _envelope(payload: BaseModel, event_type: str) -> Envelope[BaseModel]:
    return Envelope[BaseModel](
        event_id=uuid4(),
        event_type=event_type,  # type: ignore[arg-type]
        producer="partner",
        payload=payload,
    )


def _registered_handler(
    event_type: str, payload_model: type[BaseModel]
) -> tuple[HandlerRegistry, object, object]:
    registry = HandlerRegistry()
    register_handlers(registry)
    assert registry.payload_model_for(event_type) is payload_model
    handlers = registry.handlers_for(event_type)  # type: ignore[arg-type]
    assert len(handlers) == 1
    return registry, handlers[0], registry.payload_model_for(event_type)


def _fake_engine():
    engine = MagicMock()
    connection = AsyncMock()
    engine.begin.return_value.__aenter__ = AsyncMock(return_value=connection)
    engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)
    engine.dispose = AsyncMock()
    return engine, connection


def _insert_values(statement) -> dict[str, object]:
    return {key: parameter.value for key, parameter in statement._values.items()}


def test_partner_activated_registers_model_and_a_single_consumer() -> None:
    registry = HandlerRegistry()
    register_handlers(registry)
    assert registry.payload_model_for(EVENT_PARTNER_ACTIVATED) is PartnerActivatedPayload
    assert len(registry.handlers_for(EVENT_PARTNER_ACTIVATED)) == 1  # type: ignore[arg-type]
    assert registry.payload_model_for(EVENT_PARTNER_REJECTED) is PartnerRejectedPayload
    assert len(registry.handlers_for(EVENT_PARTNER_REJECTED)) == 1  # type: ignore[arg-type]
    assert registry.payload_model_for(EVENT_CREDENTIAL_INVALIDATED) is CredentialInvalidatedPayload
    assert len(registry.handlers_for(EVENT_CREDENTIAL_INVALIDATED)) == 1  # type: ignore[arg-type]


async def test_activated_handler_records_ledger_then_grants_role() -> None:
    _, handler, _ = _registered_handler(EVENT_PARTNER_ACTIVATED, PartnerActivatedPayload)
    envelope = _envelope(_activated_payload(), EVENT_PARTNER_ACTIVATED)
    engine, connection = _fake_engine()

    with (
        patch("bus.handler_harness._delivery_engine", return_value=engine),
        patch(
            "bus.handler_harness.record_consumed_event",
            new_callable=AsyncMock,
            return_value=True,
        ) as record_consumed,
        patch(
            "modules.iam.adapters.grant_partner_role",
            new_callable=AsyncMock,
        ) as grant,
    ):
        await handler(envelope)

    record_consumed.assert_awaited_once()
    assert record_consumed.await_args.args[1] == _IAM_SCHEMA
    assert record_consumed.await_args.args[2].event_id == envelope.event_id
    grant.assert_awaited_once()
    assert grant.await_args.args[0] is connection
    assert grant.await_args.args[1] == 9


async def test_activated_handler_skips_replay_when_ledger_already_has_event_id() -> None:
    _, handler, _ = _registered_handler(EVENT_PARTNER_ACTIVATED, PartnerActivatedPayload)
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
            "modules.iam.adapters.grant_partner_role",
            new_callable=AsyncMock,
        ) as grant,
    ):
        await handler(envelope)

    record_consumed.assert_awaited_once()
    grant.assert_not_awaited()


@pytest.mark.parametrize(
    "event_type,payload_factory,fn_name",
    [
        (EVENT_PARTNER_REJECTED, _rejected_payload, "suspend_partner_role"),
        (EVENT_CREDENTIAL_INVALIDATED, _invalidated_payload, "suspend_partner_role"),
    ],
)
async def test_rejection_and_invalidated_handlers_suspend_the_role(
    event_type: str, payload_factory, fn_name: str
) -> None:
    payload_model = (
        PartnerRejectedPayload
        if event_type == EVENT_PARTNER_REJECTED
        else CredentialInvalidatedPayload
    )
    _, handler, _ = _registered_handler(event_type, payload_model)
    envelope = _envelope(payload_factory(), event_type)
    engine, connection = _fake_engine()

    with (
        patch("bus.handler_harness._delivery_engine", return_value=engine),
        patch(
            "bus.handler_harness.record_consumed_event",
            new_callable=AsyncMock,
            return_value=True,
        ) as record_consumed,
        patch(
            f"modules.iam.adapters.{fn_name}",
            new_callable=AsyncMock,
        ) as suspend,
    ):
        await handler(envelope)

    record_consumed.assert_awaited_once()
    assert record_consumed.await_args.args[1] == _IAM_SCHEMA
    suspend.assert_awaited_once()
    assert suspend.await_args.args[0] is connection
    assert suspend.await_args.args[1] == 9


@pytest.mark.parametrize(
    "event_type,payload_factory,fn_name",
    [
        (EVENT_PARTNER_REJECTED, _rejected_payload, "suspend_partner_role"),
        (EVENT_CREDENTIAL_INVALIDATED, _invalidated_payload, "suspend_partner_role"),
    ],
)
async def test_suspend_handlers_skip_replay(event_type: str, payload_factory, fn_name: str) -> None:
    payload_model = (
        PartnerRejectedPayload
        if event_type == EVENT_PARTNER_REJECTED
        else CredentialInvalidatedPayload
    )
    _, handler, _ = _registered_handler(event_type, payload_model)
    envelope = _envelope(payload_factory(), event_type)
    engine, _connection = _fake_engine()

    with (
        patch("bus.handler_harness._delivery_engine", return_value=engine),
        patch(
            "bus.handler_harness.record_consumed_event",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch(
            f"modules.iam.adapters.{fn_name}",
            new_callable=AsyncMock,
        ) as suspend,
    ):
        await handler(envelope)

    suspend.assert_not_awaited()


def _grant_select_result(existing_grant: _GrantRow | None) -> AsyncMock:
    result = AsyncMock()
    result.first = MagicMock(return_value=existing_grant)
    return result


async def test_grant_partner_role_inserts_when_no_active_grant() -> None:
    connection = AsyncMock()
    insert_result = AsyncMock()
    connection.execute = AsyncMock(
        side_effect=[AsyncMock(), _grant_select_result(None), insert_result]
    )

    await grant_partner_role(connection, 9)

    assert connection.execute.await_count == 3
    insert_stmt = connection.execute.await_args_list[2].args[0]
    values = _insert_values(insert_stmt)
    assert values["identity_id"] == 9
    assert values["role"] == "partner"
    assert values["status"] == "Active"


async def test_grant_partner_role_is_noop_when_active_grant_exists() -> None:
    connection = AsyncMock()
    connection.execute = AsyncMock(side_effect=[AsyncMock(), _grant_select_result(_GrantRow(id=1))])

    await grant_partner_role(connection, 9)

    # The restore UPDATE + existence SELECT ran; no insert.
    assert connection.execute.await_count == 2


async def test_grant_partner_role_restores_a_suspended_grant() -> None:
    connection = AsyncMock()
    connection.execute = AsyncMock(side_effect=[AsyncMock(), _grant_select_result(_GrantRow(id=1))])

    await grant_partner_role(connection, 9)

    # A previously-Suspended grant is flipped back to Active (re-approval).
    update_stmt = connection.execute.await_args_list[0].args[0]
    assert update_stmt.table is iam_role_grants
    assert update_stmt._values["status"].value == "Active"
    assert connection.execute.await_count == 2


async def test_suspend_partner_role_flips_active_grant() -> None:
    connection = AsyncMock()

    await suspend_partner_role(connection, 9)

    assert connection.execute.await_count == 1
    update_stmt = connection.execute.await_args.args[0]
    assert update_stmt.table is iam_role_grants
    assert update_stmt._values["status"].value == "Suspended"
