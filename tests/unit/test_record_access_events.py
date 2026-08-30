"""PHASE-4 T5: record.accessed event publishing (ticket #238, FEAT-003).

Pins the producer contract of MOD-003's record-read audit path without a
database: the ``record.accessed`` / ``record_view_denied`` envelope builders
and payload shape, plus the dual-write behavior of ``_log_access`` - it
appends the health_record_access_history row AND writes the outbox event in
the same call (one transaction). Prior art: test_consent_events, the regulated-
act suite.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from bus.events import EVENT_RECORD_ACCESSED, EVENT_RECORD_VIEW_DENIED
from modules.health.domain.events import (
    PRODUCER_MODULE,
    RecordAccessedPayload,
    record_accessed_envelope,
    record_view_denied_envelope,
)
from modules.health.facade import _log_access

_NOW = datetime(2026, 8, 27, 10, 30, 0, tzinfo=UTC)


def test_accessed_envelope_names_the_read_with_no_phi() -> None:
    envelope = record_accessed_envelope(
        record_id=42,
        actor_id=7,
        actor_type="patient",
        scope="full_record",
        accessed_at=_NOW,
    )

    assert envelope.event_type == EVENT_RECORD_ACCESSED
    assert envelope.producer == PRODUCER_MODULE == "health"
    dumped = envelope.payload.model_dump(mode="json")
    assert dumped["record_id"] == 42
    assert dumped["actor_id"] == 7
    assert dumped["actor_type"] == "patient"
    assert dumped["scope"] == "full_record"
    assert dumped["accessed_at"] == "2026-08-27T10:30:00Z"
    # No clinical content ever rides the audit event (no-PHI).
    assert dumped["metadata"] == {}


def test_denied_envelope_flags_the_denial_with_a_reason() -> None:
    envelope = record_view_denied_envelope(
        record_id=42,
        actor_id=77,
        actor_type="doctor",
        scope="consultations",
        accessed_at=_NOW,
        denial_reason="consent check failed",
    )

    assert envelope.event_type == EVENT_RECORD_VIEW_DENIED
    assert envelope.producer == "health"
    metadata = envelope.payload.model_dump(mode="json")["metadata"]
    assert metadata == {"denied": True, "denial_reason": "consent check failed"}


def test_payload_rejects_absent_required_fields() -> None:
    with pytest.raises(ValueError):
        RecordAccessedPayload(  # type: ignore[call-arg]
            record_id=1,
            actor_id=2,
            actor_type="patient",
            scope="full_record",
        )


def test_both_envelopes_carry_distinct_event_ids() -> None:
    accessed = record_accessed_envelope(1, 7, "patient", "full_record", _NOW)
    denied = record_view_denied_envelope(1, 7, "patient", "full_record", _NOW, "no access")
    assert accessed.event_id != denied.event_id


async def test_log_access_dual_writes_history_row_and_outbox_event() -> None:
    """An allowed read lands BOTH an access-history row and outbox event together."""
    connection = AsyncMock()

    with patch("modules.health.facade.write_outbox", new_callable=AsyncMock) as write_outbox:
        await _log_access(
            connection,
            record_id=42,
            accessor_identity_id=7,
            outcome="allowed",
            actor_type="patient",
            scope="full_record",
        )

    # The history ledger gained one row in this connection's transaction.
    connection.execute.assert_awaited_once()

    # Exactly one outbox event was written, against the same connection/table.
    write_outbox.assert_awaited_once()
    args, _ = write_outbox.await_args
    connection_arg, schema_arg, table_arg, envelope = args
    assert connection_arg is connection
    assert schema_arg == "health"
    assert table_arg == "health_outbox"
    assert envelope.event_type == EVENT_RECORD_ACCESSED
    assert envelope.payload.record_id == 42
    assert envelope.payload.metadata == {}


async def test_log_access_denied_publishes_view_denied_event() -> None:
    connection = AsyncMock()

    with patch("modules.health.facade.write_outbox", new_callable=AsyncMock) as write_outbox:
        await _log_access(
            connection,
            record_id=42,
            accessor_identity_id=77,
            outcome="denied",
            actor_type="doctor",
            scope="consultations",
            denial_reason="consent check failed",
        )

    write_outbox.assert_awaited_once()
    envelope = write_outbox.await_args.args[3]
    assert envelope.event_type == EVENT_RECORD_VIEW_DENIED
    assert envelope.payload.metadata == {
        "denied": True,
        "denial_reason": "consent check failed",
    }
