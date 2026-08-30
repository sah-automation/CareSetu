"""PHASE-4 T4: audit.event consumer handler (ticket #239, FEAT-020/NFR-D01).

Pins the MOD-011 consumer contract without a database: the pure decision and
row build (derived act type, regulated-act filter, deterministic int->UUID,
hash-chained row), plus the handler wiring (ledger-first idempotency, replay
skip, regulated append, operational skip). Prior art: the pure-logic
parametrized suites (test_audit_chain, test_regulated_acts) and the mocked-
connection handler tests (test_record_access_events).
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import NAMESPACE_DNS, uuid4, uuid5

import pytest
from pydantic import BaseModel

from bus.envelope import Envelope
from bus.events import EVENT_AUDIT_EVENT
from bus.registry import HandlerRegistry
from modules.audit.adapters import register_handlers
from modules.audit.domain.chain import GENESIS_HASH, compute_audit_hash
from modules.audit.domain.consumer import (
    AuditEventPayload,
    audit_act_type,
    build_audit_row,
    is_appended_act,
)
from modules.audit.facade import AUDIT_SCHEMA, append_audit_event, compute_event_hash

_NOW = datetime(2026, 8, 27, 10, 30, 0, tzinfo=UTC)
_AUDIT_NS = uuid5(NAMESPACE_DNS, "caresetu.audit")


def _audit_payload(
    action: str = "granted",
    actor_patient_id: int = 7,
    consent_id: int = 1,
    version: int = 1,
) -> AuditEventPayload:
    return AuditEventPayload(
        action=action,  # type: ignore[arg-type]
        actor_patient_id=actor_patient_id,
        consent_id=consent_id,
        lineage_ref="C-2026-001",
        record_scope="consultations",
        version=version,
    )


def _envelope(
    payload: AuditEventPayload,
    producer: str = "consent",
    event_id=None,
) -> Envelope[AuditEventPayload]:
    return Envelope[AuditEventPayload](
        event_id=event_id or uuid4(),
        event_type=EVENT_AUDIT_EVENT,
        producer=producer,
        payload=payload,
    )


def test_audit_act_type_derives_consent_domain_name() -> None:
    for action, expected in (
        ("requested", "consent.requested"),
        ("granted", "consent.granted"),
        ("revoked", "consent.revoked"),
        ("declined", "consent.declined"),
    ):
        assert audit_act_type(action) == expected  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "action",
    ["requested", "granted", "revoked"],
)
def test_is_appended_act_true_for_regulated_consent_acts(action: str) -> None:
    assert is_appended_act(_audit_payload(action=action))


def test_is_appended_act_false_for_declined() -> None:
    # A decline is a null grant: no consent.* bus event, not a regulated act.
    assert not is_appended_act(_audit_payload(action="declined"))


def test_build_audit_row_populates_every_column() -> None:
    row = build_audit_row(_audit_payload(), "consent", _NOW, GENESIS_HASH)

    assert row.event_type == "consent.granted"
    assert row.actor_id == str(uuid5(_AUDIT_NS, "actor:7"))
    assert row.target_id == str(uuid5(_AUDIT_NS, "consent:1"))
    assert row.scope == "consultations"
    assert row.timestamp == _NOW
    assert row.prev_hash == GENESIS_HASH
    assert row.metadata == {
        "producer": "consent",
        "consent_id": 1,
        "lineage_ref": "C-2026-001",
        "version": 1,
    }
    expected = compute_audit_hash(
        row.event_type,
        row.actor_id,
        row.target_id,
        row.scope,
        row.metadata,
        row.timestamp,
        row.prev_hash,
    )
    assert row.hash == expected
    assert len(row.hash) == 64


def test_build_audit_row_chains_from_provided_prev_hash() -> None:
    head = build_audit_row(_audit_payload(version=1), "consent", _NOW, GENESIS_HASH)
    second = build_audit_row(
        _audit_payload(actor_patient_id=9, consent_id=2), "consent", _NOW, head.hash
    )

    assert second.prev_hash == head.hash
    assert second.hash != head.hash


def test_build_audit_row_maps_int_ids_deterministically() -> None:
    kwargs = {"actor_patient_id": 7, "consent_id": 1}
    first = build_audit_row(_audit_payload(**kwargs), "consent", _NOW, GENESIS_HASH)
    second = build_audit_row(_audit_payload(**kwargs), "consent", _NOW, GENESIS_HASH)

    assert first.actor_id == second.actor_id
    assert first.target_id == second.target_id


def test_build_audit_row_keeps_no_phi_out_of_metadata() -> None:
    row = build_audit_row(_audit_payload(), "consent", _NOW, GENESIS_HASH)
    # Only lineage facts ride the chain - never clinical content.
    assert "record_scope" not in row.metadata
    assert "action" not in row.metadata


def _registered_handler() -> tuple[HandlerRegistry, object]:
    registry = HandlerRegistry()
    register_handlers(registry)
    handlers = registry.handlers_for(EVENT_AUDIT_EVENT)
    assert len(handlers) == 1
    return registry, handlers[0]


def _insert_values(statement) -> dict[str, object]:
    """Extract the literal values of an ``insert(...).values(...)`` statement.

    SQLAlchemy wraps each value in a ``BindParameter``; ``.value`` unwraps it
    so the test asserts against the concrete row values, not the wrapper.
    """
    return {key: parameter.value for key, parameter in statement._values.items()}


def _fake_engine():
    engine = MagicMock()
    connection = AsyncMock()
    engine.begin.return_value.__aenter__ = AsyncMock(return_value=connection)
    engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)
    engine.dispose = AsyncMock()
    return engine, connection


async def test_handler_records_ledger_then_appends_regulated_act() -> None:
    _, handler = _registered_handler()
    envelope = _envelope(_audit_payload(action="granted"))
    engine, connection = _fake_engine()

    with (
        patch("modules.audit.adapters._delivery_engine", return_value=engine),
        patch(
            "modules.audit.adapters.record_consumed_event",
            new_callable=AsyncMock,
            return_value=True,
        ) as record_consumed,
        patch(
            "modules.audit.adapters.append_audit_event",
            new_callable=AsyncMock,
        ) as append,
    ):
        await handler(envelope)

    # Ledger written first, then the append - same transaction/connection.
    record_consumed.assert_awaited_once()
    assert record_consumed.await_args.args[1] == AUDIT_SCHEMA
    assert record_consumed.await_args.args[2].event_id == envelope.event_id
    append.assert_awaited_once()
    assert append.await_args.args[0] is connection
    assert append.await_args.args[1].action == "granted"
    assert append.await_args.args[2] == "consent"
    assert append.await_args.args[3] == envelope.occurred_at


async def test_handler_skips_replay_when_ledger_already_has_event_id() -> None:
    _, handler = _registered_handler()
    fixed_event_id = uuid4()
    envelope = _envelope(_audit_payload(action="granted"), event_id=fixed_event_id)
    engine, _connection = _fake_engine()

    with (
        patch("modules.audit.adapters._delivery_engine", return_value=engine),
        patch(
            "modules.audit.adapters.record_consumed_event",
            new_callable=AsyncMock,
            return_value=False,
        ) as record_consumed,
        patch(
            "modules.audit.adapters.append_audit_event",
            new_callable=AsyncMock,
        ) as append,
    ):
        await handler(envelope)

    # delivered=False -> the append never runs: one event_id = one audit row.
    record_consumed.assert_awaited_once()
    append.assert_not_awaited()


async def test_handler_skips_operational_act_without_appending() -> None:
    _, handler = _registered_handler()
    envelope = _envelope(_audit_payload(action="declined"))
    engine, _connection = _fake_engine()

    with (
        patch("modules.audit.adapters._delivery_engine", return_value=engine),
        patch(
            "modules.audit.adapters.record_consumed_event",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch("modules.audit.adapters.append_audit_event", new_callable=AsyncMock) as append,
    ):
        await handler(envelope)

    # The event was consumed (ledger row) but the operational act is silent.
    append.assert_not_awaited()


async def test_append_audit_event_reads_latest_hash_and_inserts_every_column() -> None:
    connection = AsyncMock()
    connection.scalar = AsyncMock(return_value=None)
    payload = _audit_payload(action="revoked")

    row = await append_audit_event(connection, payload, "consent", _NOW)

    # First row chains from genesis.
    connection.scalar.assert_awaited_once()
    assert row.prev_hash == GENESIS_HASH
    connection.execute.assert_awaited_once()
    values = _insert_values(connection.execute.await_args.args[0])
    assert values["event_type"] == "consent.revoked"
    assert values["actor_id"] == row.actor_id
    assert values["target_id"] == row.target_id
    assert values["scope"] == "consultations"
    assert values["metadata"] == row.metadata
    assert values["timestamp"] == _NOW
    assert values["prev_hash"] == GENESIS_HASH
    assert values["hash"] == row.hash


async def test_append_audit_event_chains_from_nonempty_ledger_head() -> None:
    connection = AsyncMock()
    head_hash = "a" * 64
    connection.scalar = AsyncMock(return_value=head_hash)

    await append_audit_event(connection, _audit_payload(), "consent", _NOW)

    values = _insert_values(connection.execute.await_args.args[0])
    assert values["prev_hash"] == head_hash


def test_audit_payload_is_a_pydantic_model() -> None:
    assert issubclass(AuditEventPayload, BaseModel)


def test_compute_event_hash_helper_links_to_prev_hash() -> None:
    """The facade's hash helper mirrors a chained row build (internal seam)."""
    first = compute_event_hash(
        "consent.granted",
        str(uuid5(_AUDIT_NS, "actor:7")),
        str(uuid5(_AUDIT_NS, "consent:1")),
        "consultations",
        {"producer": "consent"},
        _NOW,
        GENESIS_HASH,
    )
    second = compute_event_hash(
        "consent.granted",
        str(uuid5(_AUDIT_NS, "actor:7")),
        str(uuid5(_AUDIT_NS, "consent:1")),
        "consultations",
        {"producer": "consent"},
        _NOW,
        first,
    )

    assert len(first) == 64
    assert second != first
    assert (
        compute_event_hash(
            "consent.granted",
            str(uuid5(_AUDIT_NS, "actor:7")),
            str(uuid5(_AUDIT_NS, "consent:1")),
            "consultations",
            {"producer": "consent"},
            _NOW,
            GENESIS_HASH,
        )
        == first
    )
