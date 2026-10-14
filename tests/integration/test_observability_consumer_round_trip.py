"""B4a #702: MOD-013 consumer round trip against real PostgreSQL.

The phase-spec integration test: ``ai_job.completed`` / ``ai_job.failed``
events are published into the ``intake.intake_outbox`` exactly as the MOD-005
pipeline publishes them, a single poll pass claims + fans them out, and MOD-013
accumulates each into ``observability.observability_ai_usage_daily`` (one row
per (usage_date, provider, model, task_type) scope) while recording each
``event_id`` in ``observability.consumed_events`` FIRST. Replaying the same two
``event_id`` values through the idempotent consumers changes nothing and adds
no ledger rows (exactly-once accumulation).

Requires the native PostgreSQL; the suite skips cleanly when it is
unreachable. The shared integration conftest migrates to head once per file,
empties the observability aggregates and the outboxes before each test, and
downgrades afterwards.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from sqlalchemy.pool import NullPool

from bus.dispatch import dispatch
from bus.dispatcher import (
    DEFAULT_DISPATCHER_CONFIG,
    discover_outbox_tables,
    process_outbox_table,
)
from bus.envelope import Envelope
from bus.events import (
    EVENT_AI_JOB_COMPLETED,
    EVENT_AI_JOB_FAILED,
    EVENT_AUDIT_TAMPER_DETECTED,
    EVENT_CASE_CONSULT_COMPLETE,
    EVENT_CONSENT_GRANTED,
)
from bus.outbox_writer import write_outbox
from bus.registry import HandlerRegistry
from modules.intake.adapters import register_handlers as register_intake_handlers
from modules.intake.domain.events import AiJobCompletedPayload, AiJobFailedPayload
from modules.intake.outbox import INTAKE_OUTBOX_TABLE
from modules.observability.adapters import (
    register_handlers as register_observability_handlers,
)
from modules.observability.domain.consumer import (
    CaseConsultCompleteTelemetryPayload,
    ConsentLifecycleTelemetryPayload,
    TamperDetectedTelemetryPayload,
)

_NOW = datetime(2026, 10, 13, 8, 15, 0, tzinfo=UTC)


def _registry() -> HandlerRegistry:
    registry = HandlerRegistry()
    register_intake_handlers(registry)
    register_observability_handlers(registry)
    return registry


def _completed_envelope(
    *,
    ai_job_id: int,
    input_tokens: int,
    output_tokens: int,
    cost_paise: int,
    duration_ms: int,
    low_confidence: bool,
) -> Envelope[AiJobCompletedPayload]:
    """A MOD-005-style ``ai_job.completed`` envelope as the pipeline publishes."""
    return Envelope[AiJobCompletedPayload](
        event_id=uuid4(),
        event_type=EVENT_AI_JOB_COMPLETED,
        producer="intake",
        occurred_at=_NOW,
        payload=AiJobCompletedPayload(
            ai_job_id=ai_job_id,
            intake_id=1,
            task_type="structure",
            provider="openai",
            model="gpt-4o-mini",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_paise=cost_paise,
            duration_ms=duration_ms,
            low_confidence=low_confidence,
        ),
    )


def _failed_envelope(*, ai_job_id: int, reason: str, timeout: bool) -> Envelope[AiJobFailedPayload]:
    """A MOD-005-style ``ai_job.failed`` envelope as the pipeline publishes."""
    return Envelope[AiJobFailedPayload](
        event_id=uuid4(),
        event_type=EVENT_AI_JOB_FAILED,
        producer="intake",
        occurred_at=_NOW,
        payload=AiJobFailedPayload(
            ai_job_id=ai_job_id,
            intake_id=1,
            task_type="transcribe",
            reason=reason,
            provider="openai",
            model="whisper-1",
            timeout=timeout,
        ),
    )


async def _usage_rows(connection: AsyncConnection) -> list[dict[str, object]]:
    result = await connection.execute(
        text(
            "SELECT usage_date, provider, model, task_type, calls, success_count, "
            "failure_count, timeout_count, low_confidence_count, input_tokens, "
            "output_tokens, cost_paise, avg_duration_ms, p95_duration_ms "
            "FROM observability.observability_ai_usage_daily ORDER BY task_type"
        )
    )
    return [dict(mapping) for mapping in result.mappings().all()]


@pytest.mark.asyncio
async def test_ai_job_events_round_trip_accumulate_and_dedupe_on_replay(
    database_url: str, clean_tables: None
) -> None:
    """AC (#702): one aggregate row per scope, ledger-first; replay adds nothing.

    Two ``ai_job.completed`` events share one (provider, model, task_type) scope
    and collapse into a single accumulated row (counters summed, average
    duration recomputed as the running mean, low-confidence counted, p95 left
    NULL for the B5 rollup). Two ``ai_job.failed`` events share another scope
    and collapse into a row with timeout and plain-failure bucketed separately
    (calls == success + failure + timeout). Replaying the same event_ids through
    the consumers changes no row and adds no ledger row.
    """
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        completed_1 = _completed_envelope(
            ai_job_id=9,
            input_tokens=900,
            output_tokens=150,
            cost_paise=24,
            duration_ms=1200,
            low_confidence=True,
        )
        completed_2 = _completed_envelope(
            ai_job_id=10,
            input_tokens=600,
            output_tokens=90,
            cost_paise=14,
            duration_ms=800,
            low_confidence=False,
        )
        failed_1 = _failed_envelope(ai_job_id=11, reason="Ext002CallError", timeout=True)
        failed_2 = _failed_envelope(ai_job_id=12, reason="ValidationError", timeout=False)

        async with engine.begin() as connection:
            await write_outbox(connection, "intake", INTAKE_OUTBOX_TABLE, completed_1)
            await write_outbox(connection, "intake", INTAKE_OUTBOX_TABLE, completed_2)
            await write_outbox(connection, "intake", INTAKE_OUTBOX_TABLE, failed_1)
            await write_outbox(connection, "intake", INTAKE_OUTBOX_TABLE, failed_2)

        registry = _registry()
        async with engine.connect() as connection:
            tables = await discover_outbox_tables(connection, ("intake",))
        assert [table.table_name for table in tables] == [INTAKE_OUTBOX_TABLE]

        for table in tables:
            await process_outbox_table(engine, table, registry, DEFAULT_DISPATCHER_CONFIG)

        async with engine.connect() as connection:
            rows = await _usage_rows(connection)
            ledger = await connection.scalar(
                text("SELECT COUNT(*) FROM observability.consumed_events")
            )
            pending = await connection.scalar(text("SELECT COUNT(*) FROM intake.intake_outbox"))
        assert pending == 0
        assert ledger == 4
        assert len(rows) == 2

        structure = next(row for row in rows if str(row["task_type"]) == "structure")
        transcribe = next(row for row in rows if str(row["task_type"]) == "transcribe")

        assert structure["provider"] == "openai"
        assert structure["model"] == "gpt-4o-mini"
        assert structure["usage_date"] == _NOW.date()
        assert structure["calls"] == 2
        assert structure["success_count"] == 2
        assert structure["failure_count"] == 0
        assert structure["timeout_count"] == 0
        assert structure["low_confidence_count"] == 1
        assert structure["input_tokens"] == 1500
        assert structure["output_tokens"] == 240
        assert structure["cost_paise"] == 38
        # Running mean over the two completed durations: (1200 + 800) / 2.
        assert structure["avg_duration_ms"] == Decimal("1000.00")
        # Percentiles are recomputed by the nightly B5 rollup (#704), never here.
        assert structure["p95_duration_ms"] is None

        assert transcribe["provider"] == "openai"
        assert transcribe["model"] == "whisper-1"
        assert transcribe["calls"] == 2
        assert transcribe["success_count"] == 0
        assert transcribe["failure_count"] == 1
        assert transcribe["timeout_count"] == 1
        assert transcribe["low_confidence_count"] == 0
        assert transcribe["input_tokens"] == 0
        assert transcribe["output_tokens"] == 0
        assert transcribe["cost_paise"] == 0
        assert transcribe["avg_duration_ms"] is None

        # Replay the same event_ids through the idempotent consumers: the
        # ledger conflict is recorded and nothing accumulates - still two rows,
        # still four ledger rows.
        await dispatch(registry, completed_1)
        await dispatch(registry, completed_2)
        await dispatch(registry, failed_1)
        await dispatch(registry, failed_2)
        async with engine.connect() as connection:
            rows = await _usage_rows(connection)
            ledger = await connection.scalar(
                text("SELECT COUNT(*) FROM observability.consumed_events")
            )
        assert len(rows) == 2
        assert ledger == 4
    finally:
        await engine.dispose()


async def _business_rows(connection: AsyncConnection) -> dict[str, int]:
    result = await connection.execute(
        text(
            "SELECT metric_key, (value->>'count')::int AS count "
            "FROM observability.observability_business_daily"
        )
    )
    return {str(mapping["metric_key"]): int(mapping["count"]) for mapping in result.mappings()}


@pytest.mark.asyncio
async def test_business_counts_and_tamper_alert_round_trip_replay_safe(
    database_url: str, clean_tables: None
) -> None:
    """AC (#703): counts keyed by ``metric_key``+date; tamper -> one alert; replay no-op.

    Two ``case.consult_complete`` and one ``consent.granted`` business events roll
    into ``observability_business_daily`` keyed by ``metric_key`` + the envelope's
    occurrence date, accumulating their ``value.count``. A ``audit.tamper_detected``
    event (plus an ``ai_egress.recorded`` guardrail signal) writes one PHI-free
    ``observability_alert_events`` row each. Replaying every ``event_id`` through
    the idempotent consumers adds no rows and no effects.
    """
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        registry = _registry()

        consult_1 = Envelope[CaseConsultCompleteTelemetryPayload](
            event_id=uuid4(),
            event_type=EVENT_CASE_CONSULT_COMPLETE,
            producer="care",
            occurred_at=_NOW,
            payload=CaseConsultCompleteTelemetryPayload(
                case_id=1, patient_id=2, doctor_id=3, pre_summary_id=4
            ),
        )
        consult_2 = Envelope[CaseConsultCompleteTelemetryPayload](
            event_id=uuid4(),
            event_type=EVENT_CASE_CONSULT_COMPLETE,
            producer="care",
            occurred_at=_NOW,
            payload=CaseConsultCompleteTelemetryPayload(
                case_id=5, patient_id=6, doctor_id=3, pre_summary_id=None
            ),
        )
        granted = Envelope[ConsentLifecycleTelemetryPayload](
            event_id=uuid4(),
            event_type=EVENT_CONSENT_GRANTED,
            producer="consent",
            occurred_at=_NOW,
            payload=ConsentLifecycleTelemetryPayload(
                consent_id=7,
                lineage_ref="lineage-7",
                patient_id=2,
                counterparty_type="doctor",
                counterparty_id="3",
                record_scope="consultations",
                version=1,
            ),
        )
        tamper = Envelope[TamperDetectedTelemetryPayload](
            event_id=uuid4(),
            event_type=EVENT_AUDIT_TAMPER_DETECTED,
            producer="audit",
            occurred_at=_NOW,
            payload=TamperDetectedTelemetryPayload(
                attempted_operation="UPDATE",
                target_event_id="11111111-1111-1111-1111-111111111111",
                attempted_at=_NOW,
            ),
        )

        for envelope in (consult_1, consult_2, granted, tamper):
            await dispatch(registry, envelope)

        async with engine.connect() as connection:
            business = await _business_rows(connection)
            alerts = await connection.execute(
                text("SELECT severity, kind, payload FROM observability.observability_alert_events")
            )
            alert_rows = [dict(mapping) for mapping in alerts.mappings().all()]

        assert business == {EVENT_CASE_CONSULT_COMPLETE: 2, EVENT_CONSENT_GRANTED: 1}
        assert len(alert_rows) == 1
        assert alert_rows[0]["severity"] == "critical"
        assert alert_rows[0]["kind"] == "audit_tamper"
        # PHI-free: the producer's row-data ``details`` blob never reaches the alert.
        assert "details" not in alert_rows[0]["payload"]
        assert alert_rows[0]["payload"]["attempted_operation"] == "UPDATE"

        # Replay every event_id: idempotent no-op, one ledger row per event.
        for envelope in (consult_1, consult_2, granted, tamper):
            await dispatch(registry, envelope)
        async with engine.connect() as connection:
            business = await _business_rows(connection)
            alert_count = await connection.scalar(
                text("SELECT COUNT(*) FROM observability.observability_alert_events")
            )
            ledger = await connection.scalar(
                text("SELECT COUNT(*) FROM observability.consumed_events")
            )
        assert business == {EVENT_CASE_CONSULT_COMPLETE: 2, EVENT_CONSENT_GRANTED: 1}
        assert alert_count == 1
        assert ledger == 4
    finally:
        await engine.dispose()
