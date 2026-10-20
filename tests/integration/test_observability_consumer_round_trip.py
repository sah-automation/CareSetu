"""B4a #702, B4 #722, B6 #723, B7 #724, T3.5 #752: MOD-013 consumer round trip vs real PostgreSQL.

The phase-spec integration test: ``ai_job.completed`` / ``ai_job.failed``
events are published into the ``intake.intake_outbox`` exactly as the MOD-005
pipeline publishes them, a single poll pass claims + fans them out, and MOD-013
accumulates each into ``observability.observability_ai_usage_daily`` (one row
per (usage_date, provider, model, task_type) scope) and writes one granular
``observability.observability_ai_job_spend`` row per job, recording each
``event_id`` in ``observability.consumed_events`` FIRST. Replaying the same
``event_id`` values through the idempotent consumers changes nothing and adds no
ledger rows (exactly-once accumulation).

The granular row is what the per-patient and per-doctor numbers are computed FROM
(#723), so the round trip asserts it is complete, attribution-bearing and
PHI-free: every fact the business lens needs is on the row, and the identity it
is attributed to is a one-way hash rather than the reference that arrived on the
event.

B7 (#724) adds the fourth subscription, ``intake.doctor_assigned``: the
care-attribution edge. Its round trip proves the edge exists only because the
event said so, that replaying it writes nothing, and that an intake's spend
resolves to exactly one doctor through it.

T3.5 (#752) adds the annotation queue: a doctor review OUTCOME becomes one
``source = 'human'`` row of ``observability_evaluation_scores``. Its round trip
proves the queue is fed by events (never by a read of MOD-006's tables), that
the rejected outcome's free-text rationale never reaches storage, that the
approval rides its existing funnel-step seat rather than a second one, and that
a delivery nobody traced leaves the queue's trace id NULL.

The ``draft`` case is different in kind: it drives the REAL
``IntakeFacade.request_rx_draft`` so the prescription-drafting leg's metering is
produced by the seam rather than hand-written here, which is what proves
``draft`` is a produced task type rather than a declared-but-empty one (#722).

Requires the native PostgreSQL; the suite skips cleanly when it is
unreachable. The shared integration conftest migrates to head once per file,
empties the observability aggregates and the outboxes before each test, and
downgrades afterwards.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast
from unittest.mock import patch
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

import modules.observability.domain.product as product_module
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
    EVENT_AI_JOB_QUEUED,
    EVENT_AUDIT_TAMPER_DETECTED,
    EVENT_CASE_CONSULT_COMPLETE,
    EVENT_CONSENT_GRANTED,
    EVENT_INTAKE_CAPTURED,
    EVENT_INTAKE_COMPOSER_OPENED,
    EVENT_INTAKE_DOCTOR_ASSIGNED,
    EVENT_INTAKE_RETRY_REQUESTED,
    EVENT_PRESCRIPTION_REVIEWED,
)
from bus.outbox_writer import write_outbox
from bus.registry import HandlerRegistry
from modules.care.adapters import register_handlers as register_care_handlers
from modules.care.domain.events import (
    prescription_approved_envelope,
    prescription_rejected_envelope,
)
from modules.care.outbox import CARE_OUTBOX_TABLE
from modules.intake.adapters import register_handlers as register_intake_handlers
from modules.intake.adapters.ai_gateway import Ext002CallError
from modules.intake.adapters.ai_provider_mock import (
    MOCK_AI_MODEL,
    MOCK_AI_PROVIDER,
    MockAiProvider,
)
from modules.intake.domain.events import (
    AiJobCompletedPayload,
    AiJobFailedPayload,
    AiJobQueuedPayload,
    AiTaskType,
    IntakeDoctorAssignedPayload,
    intake_composer_opened_envelope,
)
from modules.intake.facade import IntakeFacade
from modules.intake.outbox import INTAKE_OUTBOX_TABLE
from modules.observability.adapters import (
    register_handlers as register_observability_handlers,
)
from modules.observability.domain.annotation import (
    ANNOTATION_EVALUATOR_ACCEPTED_EDITED,
    ANNOTATION_EVALUATOR_ACCEPTED_UNCHANGED,
    ANNOTATION_EVALUATOR_REJECTED,
)
from modules.observability.domain.consumer import (
    MAX_FAILURE_REASON_CHARS,
    PRODUCT_EVENT_MIRRORS,
    CaseConsultCompleteTelemetryPayload,
    ConsentLifecycleTelemetryPayload,
    IntakeCapturedTelemetryPayload,
    IntakeComposerOpenedTelemetryPayload,
    IntakeRetryRequestedTelemetryPayload,
    TamperDetectedTelemetryPayload,
)
from modules.observability.domain.product import (
    FUNNEL_INTAKE,
    PRODUCT_OUTCOME_COMPLETED,
    ProductStep,
    ProductStepPayload,
    register_product_step,
)
from modules.observability.domain.pseudonym import (
    ACTOR_KIND_DOCTOR,
    ACTOR_KIND_PATIENT,
    actor_key,
)
from modules.observability.domain.rollup import RollupThresholds
from modules.observability.facade import run_rollup
from observability.logging import reset_trace_id, set_trace_id

_NOW = datetime(2026, 10, 13, 8, 15, 0, tzinfo=UTC)

#: A well-formed W3C trace-id (32 lowercase hex) the widened payloads carry (#719).
_TRACE_ID = "a" * 32

#: The rollup's alert thresholds, at the values plan-phase14 §11 names. Only the
#: budget cap is required; everything else defaults.
_THRESHOLDS = RollupThresholds(monthly_budget_paise=100_000)


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
    patient_id: int = 7,
    doctor_id: int | None = None,
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
            patient_id=patient_id,
            doctor_id=doctor_id,
            trace_id=_TRACE_ID,
        ),
    )


def _failed_envelope(
    *,
    ai_job_id: int,
    reason: str,
    timeout: bool,
    patient_id: int = 7,
    doctor_id: int | None = None,
) -> Envelope[AiJobFailedPayload]:
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
            patient_id=patient_id,
            doctor_id=doctor_id,
            trace_id=_TRACE_ID,
        ),
    )


def _queued_envelope(
    *,
    ai_job_id: int,
    task_type: str = "structure",
    patient_id: int = 7,
    doctor_id: int | None = None,
) -> Envelope[AiJobQueuedPayload]:
    """A MOD-005-style ``ai_job.queued`` envelope as the pipeline publishes (B5 #729)."""
    return Envelope[AiJobQueuedPayload](
        event_id=uuid4(),
        event_type=EVENT_AI_JOB_QUEUED,
        producer="intake",
        occurred_at=_NOW,
        payload=AiJobQueuedPayload(
            ai_job_id=ai_job_id,
            intake_id=1,
            task_type=cast(AiTaskType, task_type),
            patient_id=patient_id,
            doctor_id=doctor_id,
            trace_id=_TRACE_ID,
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


async def _spend_rows(connection: AsyncConnection) -> list[dict[str, object]]:
    result = await connection.execute(
        text(
            "SELECT ai_job_ref, usage_date, intake_ref, patient_key, doctor_key, provider, "
            "model, task_type, input_tokens, output_tokens, cost_paise, status, trace_id, "
            "failure_reason FROM observability.observability_ai_job_spend "
            "ORDER BY status, model, input_tokens"
        )
    )
    return [dict(mapping) for mapping in result.mappings().all()]


def _at(envelope: Envelope[Any], occurred_at: datetime) -> Envelope[Any]:
    """The same delivery, stamped at a different instant (same ``event_id``)."""
    return Envelope[Any](
        event_id=envelope.event_id,
        event_type=envelope.event_type,
        producer=envelope.producer,
        occurred_at=occurred_at,
        payload=envelope.payload,
    )


async def _queue_rows(connection: AsyncConnection) -> list[dict[str, object]]:
    """The still-open AI jobs, as the depth and the oldest-age are derived from."""
    result = await connection.execute(
        text(
            "SELECT ai_job_ref, queue, enqueued_at FROM "
            "observability.observability_ai_queue_open ORDER BY ai_job_ref"
        )
    )
    return [dict(mapping) for mapping in result.mappings().all()]


async def _row_counts(connection: AsyncConnection) -> dict[str, int]:
    """Every table this batch's consumption can write, counted at once."""
    counts = {}
    for table in (
        "observability.observability_ai_usage_daily",
        "observability.observability_ai_job_spend",
        "observability.observability_ai_queue_open",
        "observability.observability_care_attribution_edges",
        "observability.observability_attribution_daily",
        "observability.observability_product_events",
        "observability.observability_product_daily",
        "observability.observability_product_actor_daily",
        "observability.observability_evaluation_scores",
        "observability.consumed_events",
    ):
        counts[table] = int(await connection.scalar(text(f"SELECT COUNT(*) FROM {table}")))
    return counts


async def _attribution_table_text(connection: AsyncConnection) -> str:
    """Every stored value of the attribution table set, flattened to one string.

    Reaching below the seam on purpose: the rule being proven - the observability
    schema carries no raw identity reference and no clinical content - is a
    statement about what is ABSENT from storage, so it has to be asserted over
    the whole table rather than over the columns one read happens to select.
    """
    rows = await connection.execute(
        text(
            "SELECT to_jsonb(spend)::text AS row FROM "
            "observability.observability_ai_job_spend spend "
            "UNION ALL SELECT to_jsonb(edge)::text FROM "
            "observability.observability_care_attribution_edges edge "
            "UNION ALL SELECT to_jsonb(daily)::text FROM "
            "observability.observability_attribution_daily daily"
        )
    )
    return " ".join(str(row[0]) for row in rows)


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

    AC (#723) rides the same pass: the same four jobs also write FOUR granular
    ``observability_ai_job_spend`` rows - one per job, so the per-patient and
    per-doctor numbers have something to be computed from. The completed job
    that names a doctor proves the doctor key is populated and hashed; the three
    that name no doctor prove the column is honestly nullable rather than filled
    with a placeholder. Replay adds no per-job row either, and neither raw
    identity reference survives anywhere in the three new tables.
    """
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        # Distinctive references, so the "no raw identity in the schema" scan
        # below cannot pass by accident on a short number appearing in a digest.
        patient_ref = 700_000_007
        doctor_ref = 900_000_003
        completed_1 = _completed_envelope(
            ai_job_id=9,
            input_tokens=900,
            output_tokens=150,
            cost_paise=24,
            duration_ms=1200,
            low_confidence=True,
            patient_id=patient_ref,
            doctor_id=doctor_ref,
        )
        completed_2 = _completed_envelope(
            ai_job_id=10,
            input_tokens=600,
            output_tokens=90,
            cost_paise=14,
            duration_ms=800,
            low_confidence=False,
            patient_id=patient_ref,
        )
        failed_1 = _failed_envelope(
            ai_job_id=11, reason="Ext002CallError", timeout=True, patient_id=patient_ref
        )
        failed_2 = _failed_envelope(
            ai_job_id=12, reason="ValidationError", timeout=False, patient_id=patient_ref
        )

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
            spend = await _spend_rows(connection)
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

        # B6 (#723): four jobs in, four granular rows out - the granular grain is
        # the JOB, not the scope, which is the whole reason this table exists.
        assert len(spend) == 4

        structure_job = next(row for row in spend if row["input_tokens"] == 900)
        assert structure_job["ai_job_ref"] == 9
        assert structure_job["usage_date"] == _NOW.date()
        assert structure_job["intake_ref"] == 1
        assert structure_job["provider"] == "openai"
        assert structure_job["model"] == "gpt-4o-mini"
        assert structure_job["task_type"] == "structure"
        assert structure_job["output_tokens"] == 150
        assert structure_job["cost_paise"] == 24
        assert structure_job["status"] == "completed"
        assert structure_job["trace_id"] == _TRACE_ID
        # #728: a completed job has no failure to describe, so the column is NULL
        # rather than an empty string that would read as a named failure saying
        # nothing.
        assert structure_job["failure_reason"] is None

        # Attribution is present and is a ONE-WAY HASH of the references that
        # arrived on the event - never the references themselves.
        assert structure_job["patient_key"] == actor_key(ACTOR_KIND_PATIENT, patient_ref)
        assert structure_job["doctor_key"] == actor_key(ACTOR_KIND_DOCTOR, doctor_ref)

        # A failed call reports no usage: it records an attempt at zero, not a
        # fabricated free job. Selected by job reference because both failed jobs
        # sort identically on the helper's ORDER BY.
        failed_job = next(row for row in spend if row["ai_job_ref"] == 11)
        assert failed_job["model"] == "whisper-1"
        assert failed_job["task_type"] == "transcribe"
        assert failed_job["input_tokens"] == 0
        assert failed_job["output_tokens"] == 0
        assert failed_job["cost_paise"] == 0
        # #728: the sanitised reason rides the per-job row, which is what the
        # nightly rollup reads to name the provider's last error.
        assert failed_job["failure_reason"] == "Ext002CallError"
        # The sibling failure keeps its own reason: the two are distinct findings
        # and the board names the newest one, not a merge of them.
        assert next(row for row in spend if row["ai_job_ref"] == 12)["failure_reason"] == (
            "ValidationError"
        )

        # The three jobs that named no doctor (the transcription and structuring
        # legs run before a pick) leave the doctor key NULL - a real gap an
        # operator can see, not a placeholder that looks attributed.
        doctorless = [row for row in spend if row["doctor_key"] is None]
        assert len(doctorless) == 3

        # Neither raw identity reference survives anywhere in the three new
        # tables - not as a column, not as a substring of one.
        async with engine.connect() as connection:
            stored = await _attribution_table_text(connection)
        assert str(patient_ref) not in stored
        assert str(doctor_ref) not in stored

        # Replay the same event_ids through the idempotent consumers: the ledger
        # conflict is recorded and NOTHING accumulates. The count is taken over
        # every table this batch's consumption can write, not just the two the
        # first pass happened to populate, because the AC is written as a blanket
        # claim - "every row count unchanged" - and a later ticket filling the
        # edge or the aggregate must not be able to break the guarantee silently.
        before_replay: dict[str, int] = {}
        async with engine.connect() as connection:
            before_replay = await _row_counts(connection)
        await dispatch(registry, completed_1)
        await dispatch(registry, completed_2)
        await dispatch(registry, failed_1)
        await dispatch(registry, failed_2)
        async with engine.connect() as connection:
            after_replay = await _row_counts(connection)
        assert after_replay == before_replay
        assert after_replay == {
            "observability.observability_ai_usage_daily": 2,
            "observability.observability_ai_job_spend": 4,
            "observability.observability_ai_queue_open": 0,
            "observability.observability_care_attribution_edges": 0,
            "observability.observability_attribution_daily": 0,
            "observability.observability_product_events": 0,
            "observability.observability_product_daily": 0,
            "observability.observability_product_actor_daily": 0,
            "observability.observability_evaluation_scores": 0,
            "observability.consumed_events": 4,
        }
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_queue_depth_is_enqueued_minus_closed_and_the_oldest_row_is_the_aged_one(
    database_url: str, clean_tables: None
) -> None:
    """B5 (#729): the whole queue, derived from events and from nothing else.

    Three jobs enter the pipeline (two ``structure``, one ``transcribe``) and the
    open set holds exactly those three, each stamped with the ENVELOPE's
    ``occurred_at`` - so the age an operator reads comes from the clock the
    delivery carried, not from a second value the producer could disagree with.
    Two of them then close and the depth falls by exactly two: ``completed`` and
    ``failed`` are both closures, and a failed job left queued would never drain.

    The aged row is proved to be the OLDEST still-open one rather than "a row":
    the surviving ``structure`` job is the earlier of the two, so a design that
    kept the first-seen stamp would pass here only by accident.
    """
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        older = _NOW - timedelta(minutes=30)
        newer = _NOW - timedelta(seconds=5)
        enqueued = [
            # The first structure enqueue is the OLD one, so the aged row and the
            # surviving row are different jobs and a "first stamp wins" bug shows.
            _at(_queued_envelope(ai_job_id=21, task_type="structure"), older),
            _queued_envelope(ai_job_id=22, task_type="structure"),
            _at(_queued_envelope(ai_job_id=23, task_type="transcribe"), newer),
        ]

        async with engine.begin() as connection:
            for envelope in enqueued:
                await write_outbox(connection, "intake", INTAKE_OUTBOX_TABLE, envelope)

        registry = _registry()
        async with engine.connect() as connection:
            tables = await discover_outbox_tables(connection, ("intake",))
        for table in tables:
            await process_outbox_table(engine, table, registry, DEFAULT_DISPATCHER_CONFIG)

        async with engine.connect() as connection:
            open_rows = await _queue_rows(connection)

        assert [(row["ai_job_ref"], row["queue"]) for row in open_rows] == [
            (21, "structure"),
            (22, "structure"),
            (23, "transcribe"),
        ]
        oldest = open_rows[0]["enqueued_at"]
        assert oldest.tzinfo is not None
        assert oldest == older
        assert open_rows[1]["enqueued_at"] == _NOW
        assert open_rows[2]["enqueued_at"] == newer

        # Two closures, of different kinds: depth falls by exactly two.
        completed = _completed_envelope(
            ai_job_id=21,
            input_tokens=100,
            output_tokens=10,
            cost_paise=2,
            duration_ms=100,
            low_confidence=False,
        )
        failed = _failed_envelope(ai_job_id=23, reason="Ext002CallError", timeout=True)
        async with engine.begin() as connection:
            await write_outbox(connection, "intake", INTAKE_OUTBOX_TABLE, completed)
            await write_outbox(connection, "intake", INTAKE_OUTBOX_TABLE, failed)
        async with engine.connect() as connection:
            tables = await discover_outbox_tables(connection, ("intake",))
        for table in tables:
            await process_outbox_table(engine, table, registry, DEFAULT_DISPATCHER_CONFIG)

        async with engine.connect() as connection:
            remaining = await _queue_rows(connection)
            counts = await _row_counts(connection)
        assert [(row["ai_job_ref"], row["queue"]) for row in remaining] == [(22, "structure")]
        # The surviving job is the one still open, so an age computed over the whole
        # enqueue history would be wrong by the closed job's age.
        assert remaining[0]["enqueued_at"] == _NOW
        assert counts["observability.observability_ai_queue_open"] == 1

        # A SECOND enqueue event naming a job already queued (a new event_id, so the
        # ledger does not stop it) must not double the depth: the row's identity is
        # the job.
        duplicate = _queued_envelope(ai_job_id=22, task_type="structure")
        await dispatch(registry, duplicate)
        async with engine.connect() as connection:
            after_duplicate = await _queue_rows(connection)
        assert len(after_duplicate) == 1
        assert after_duplicate[0]["ai_job_ref"] == 22

        # Replay the whole pass: no row, no count, nothing moves. The baseline is
        # taken AFTER the duplicate above, because that one was a genuinely new
        # event_id and is supposed to have added its own ledger row.
        async with engine.connect() as connection:
            before_replay = await _row_counts(connection)
        await dispatch(registry, enqueued[0])
        await dispatch(registry, enqueued[1])
        await dispatch(registry, enqueued[2])
        await dispatch(registry, completed)
        await dispatch(registry, failed)
        async with engine.connect() as connection:
            after_replay = await _row_counts(connection)
        assert after_replay == before_replay
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_a_close_for_a_job_never_enqueued_deletes_nothing_and_does_not_fail(
    database_url: str, clean_tables: None
) -> None:
    """A completion with no matching enqueue is a no-op, not a dead letter.

    It is a real case - a deployment that starts mid-flight has no enqueue history,
    and a delivery can arrive after its enqueue was dropped - and treating it as a
    defect would stall the very queue the alert exists to protect. The cost is an
    over-count that the age alert keeps reporting until the queue drains for real;
    the alternative is losing the row permanently.
    """
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        registry = _registry()
        completed = _completed_envelope(
            ai_job_id=31,
            input_tokens=10,
            output_tokens=1,
            cost_paise=1,
            duration_ms=50,
            low_confidence=False,
        )
        await dispatch(registry, completed)

        async with engine.connect() as connection:
            counts = await _row_counts(connection)
            pending = await connection.scalar(text("SELECT COUNT(*) FROM intake.intake_outbox"))
        assert pending == 0
        # The completion is still metered - only the queue row had nothing to close.
        assert counts["observability.observability_ai_job_spend"] == 1
        assert counts["observability.observability_ai_queue_open"] == 0
        assert counts["observability.consumed_events"] == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_a_hostile_provider_reason_is_sanitised_before_it_reaches_the_schema(
    database_url: str, clean_tables: None
) -> None:
    """#728: the sanitiser runs at CONSUME time, so the raw value never lands.

    A provider error body can echo the request content that was sent to it. This
    drives one through the real dispatcher and asserts on the stored row rather
    than on the sanitiser's return value, because the claim is about what the
    schema ends up holding - a correct helper called after the write would pass a
    unit test and still store the raw text.

    The seeded reason also carries a clinical-looking fragment, standing in for an
    echo of the patient's own words on the lines after the provider's status
    line. The schema must NOT end up holding that echo, nor the newline that would
    have forged a second row in any export; it must hold the status line alone.
    """
    hostile = (
        "Ext002CallError: provider said 429\n"
        "request echoed: patient complains of fever and cough since three days. "
        + "the provider repeated its own diagnostics "
        * 20
    )
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        envelope = _failed_envelope(ai_job_id=77, reason=hostile, timeout=False)

        async with engine.begin() as connection:
            await write_outbox(connection, "intake", INTAKE_OUTBOX_TABLE, envelope)
        registry = _registry()
        async with engine.connect() as connection:
            tables = await discover_outbox_tables(connection, ("intake",))
        for table in tables:
            await process_outbox_table(engine, table, registry, DEFAULT_DISPATCHER_CONFIG)

        async with engine.connect() as connection:
            stored = await connection.scalar(
                text(
                    "SELECT failure_reason FROM observability.observability_ai_job_spend "
                    "WHERE ai_job_ref = 77"
                )
            )

        # The provider's status line is what names the failure; everything it
        # echoed after it is gone, newline included.
        assert stored == "Ext002CallError: provider said 429"
        assert "patient" not in stored
        assert len(stored) < MAX_FAILURE_REASON_CHARS
    finally:
        await engine.dispose()


def _doctor_assigned_envelope(
    *,
    intake_id: int,
    patient_id: int,
    doctor_id: int,
    occurred_at: datetime = _NOW,
) -> Envelope[IntakeDoctorAssignedPayload]:
    """A MOD-005-style ``intake.doctor_assigned`` envelope as ``pick_doctor`` publishes."""
    return Envelope[IntakeDoctorAssignedPayload](
        event_id=uuid4(),
        event_type=EVENT_INTAKE_DOCTOR_ASSIGNED,
        producer="intake",
        occurred_at=occurred_at,
        payload=IntakeDoctorAssignedPayload(
            intake_id=intake_id,
            patient_id=patient_id,
            doctor_id=doctor_id,
        ),
    )


async def _edge_rows(connection: AsyncConnection) -> list[dict[str, object]]:
    result = await connection.execute(
        text(
            "SELECT intake_ref, patient_key, doctor_key, event_id, assigned_at "
            "FROM observability.observability_care_attribution_edges ORDER BY intake_ref"
        )
    )
    return [dict(mapping) for mapping in result.mappings().all()]


@pytest.mark.asyncio
async def test_doctor_pick_round_trips_into_one_attribution_edge_per_intake(
    database_url: str, clean_tables: None
) -> None:
    """AC (#724): one edge row per pick, written because the event said so.

    The edge is the only legal record of which doctor an intake belongs to:
    MOD-013 cannot read the care schema (ADR-0003), so the row exists because
    ``intake.doctor_assigned`` was published and nothing else. It carries the
    intake reference plus the two ONE-WAY actor keys, never the raw references
    that arrived on the event.

    Five things are proved here, all at the real-database seam:

    1. One pick writes exactly one edge, ledger-first alongside the effect.
    2. Replaying the same ``event_id`` writes no second edge and no second ledger
       row - the replay proof, over a table the previous batch left empty.
    3. A genuinely NEW event about an already-picked intake - a re-pick - leaves
       exactly one edge pointing at the newest doctor. "Exactly one doctor" is
       the schema's rule, not the producer's, so the effect upserts rather than
       failing a constraint or stacking a second row.
    4. A STALE event arriving late is dropped rather than allowed to roll the
       pairing backwards, so "newest pick wins" holds regardless of the order
       deliveries happen to arrive in.
    5. The edge is what resolves an intake's spend: the transcription and
       structuring rows are written with a NULL doctor key (they run before a
       pick), and after the edge lands they resolve to exactly one doctor.
    """
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        patient_ref = 700_000_007
        doctor_ref = 900_000_003
        other_doctor_ref = 900_000_004

        # Spend written BEFORE the pick, exactly as the pipeline meters it: the
        # transcription and structuring legs run with no doctor involved, so their
        # doctor key is honestly NULL.
        transcribe = _completed_envelope(
            ai_job_id=21,
            input_tokens=800,
            output_tokens=0,
            cost_paise=18,
            duration_ms=1100,
            low_confidence=False,
            patient_id=patient_ref,
        )
        assigned = _doctor_assigned_envelope(
            intake_id=1, patient_id=patient_ref, doctor_id=doctor_ref
        )

        async with engine.begin() as connection:
            await write_outbox(connection, "intake", INTAKE_OUTBOX_TABLE, transcribe)
            await write_outbox(connection, "intake", INTAKE_OUTBOX_TABLE, assigned)

        registry = _registry()
        async with engine.connect() as connection:
            tables = await discover_outbox_tables(connection, ("intake",))
        for table in tables:
            await process_outbox_table(engine, table, registry, DEFAULT_DISPATCHER_CONFIG)

        async with engine.connect() as connection:
            edges = await _edge_rows(connection)
            ledger = await connection.scalar(
                text("SELECT COUNT(*) FROM observability.consumed_events")
            )
        assert ledger == 2
        assert len(edges) == 1

        edge = edges[0]
        assert edge["intake_ref"] == 1
        # Provenance: the row names the delivery that wrote it, so the audit trail
        # says which pick this attribution came from.
        assert edge["event_id"] == assigned.event_id
        assert edge["assigned_at"] == _NOW
        # Both identities are hashed through #723's helper - the SAME helper, so a
        # key minted here joins one minted at rollup time. Two conventions in one
        # schema is how attribution silently stops reconciling.
        assert edge["patient_key"] == actor_key(ACTOR_KIND_PATIENT, patient_ref)
        assert edge["doctor_key"] == actor_key(ACTOR_KIND_DOCTOR, doctor_ref)

        async with engine.connect() as connection:
            stored = await _attribution_table_text(connection)
        assert str(patient_ref) not in stored
        assert str(doctor_ref) not in stored

        # Replay the SAME event_id: no second edge, no second ledger row.
        async with engine.connect() as connection:
            before_replay = await _row_counts(connection)
        await dispatch(registry, assigned)
        async with engine.connect() as connection:
            after_replay = await _row_counts(connection)
            edges = await _edge_rows(connection)
        assert after_replay == before_replay
        assert after_replay["observability.observability_care_attribution_edges"] == 1
        assert len(edges) == 1

        # A genuinely new event about the same intake - a re-pick - must leave ONE
        # edge pointing at the newest doctor, not two edges and not a constraint
        # failure. The uniqueness of ``intake_ref`` is what enforces this; the
        # producer refusing to re-pick is not relied on.
        repick = _doctor_assigned_envelope(
            intake_id=1,
            patient_id=patient_ref,
            doctor_id=other_doctor_ref,
            occurred_at=datetime(2026, 10, 13, 9, 0, 0, tzinfo=UTC),
        )
        await dispatch(registry, repick)
        async with engine.connect() as connection:
            edges = await _edge_rows(connection)
        assert len(edges) == 1
        assert edges[0]["doctor_key"] == actor_key(ACTOR_KIND_DOCTOR, other_doctor_ref)
        assert edges[0]["event_id"] == repick.event_id
        assert edges[0]["assigned_at"] == repick.occurred_at

        # "Newest pick wins" is a property of the code, not an assumption about
        # delivery order: a DIFFERENT event_id that is OLDER than the edge already
        # recorded - a stale pick arriving late, which the ledger lets through
        # because it is not a redelivery - is dropped rather than allowed to roll
        # the pairing, and its timestamp, backwards.
        stale = _doctor_assigned_envelope(
            intake_id=1,
            patient_id=patient_ref,
            doctor_id=doctor_ref,
            occurred_at=datetime(2026, 10, 13, 7, 0, 0, tzinfo=UTC),
        )
        await dispatch(registry, stale)
        async with engine.connect() as connection:
            edges = await _edge_rows(connection)
        assert len(edges) == 1
        assert edges[0]["doctor_key"] == actor_key(ACTOR_KIND_DOCTOR, other_doctor_ref)
        assert edges[0]["event_id"] == repick.event_id
        assert edges[0]["assigned_at"] == repick.occurred_at

        # AC (#724), stated as the operator reads it: one intake's spend resolves
        # to exactly one doctor THROUGH the edge. The transcribing row named no
        # doctor, so its doctor comes from here and only here - never from a read
        # of the care schema.
        async with engine.connect() as connection:
            resolved = await connection.execute(
                text(
                    "SELECT edge.doctor_key AS doctor_key, spend.cost_paise AS cost_paise "
                    "FROM observability.observability_ai_job_spend spend "
                    "JOIN observability.observability_care_attribution_edges edge "
                    "ON edge.intake_ref = spend.intake_ref "
                    "WHERE spend.doctor_key IS NULL"
                )
            )
            rows = resolved.mappings().all()
        assert len(rows) == 1
        assert rows[0]["doctor_key"] == actor_key(ACTOR_KIND_DOCTOR, other_doctor_ref)
        assert rows[0]["cost_paise"] == 18
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def clean_intake_tables(database_url: str, migrated_schema: None) -> AsyncIterator[None]:
    """Empty the intake tables the drafting leg writes, so its row counts are exact."""
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "TRUNCATE TABLE intake.intake_outbox, intake.intake_ai_jobs, "
                    "intake.intake_pre_summaries, intake.intake_intakes CASCADE"
                )
            )
    finally:
        await engine.dispose()
    yield


@pytest.mark.asyncio
async def test_drafting_leg_reaches_the_usage_aggregate_as_a_produced_task_type(
    database_url: str, clean_tables: None, clean_intake_tables: None
) -> None:
    """AC (#722): ``draft`` is a PRODUCED task type, not a declared-but-empty one.

    Nothing here is hand-written: the REAL ``IntakeFacade.request_rx_draft`` runs
    against real PostgreSQL and a real gateway, writing its own ``intake_ai_jobs``
    rows and outbox events, then the real dispatcher with the real registry
    consumes them. ``draft`` landing in ``observability_ai_usage_daily`` beside the
    pipeline's scopes is the proof that the prescription-drafting figure an
    operator reports is the figure the platform spends. A failed draft is metered
    on the same seam and lands in the SAME scope as a counted failure rather than
    as nothing - the two halves of "every draft is metered". #723's granular row
    records the same two attempts, and neither the patient's complaint text nor
    the raw patient reference follows them into telemetry.
    """
    engine = create_async_engine(database_url, poolclass=NullPool)
    facade_engine = create_async_engine(database_url, poolclass=NullPool)
    patient_id = uuid4().int % (2**53)
    try:
        async with engine.begin() as connection:
            intake_id = int(
                await connection.scalar(
                    text(
                        "INSERT INTO intake.intake_intakes "
                        "(patient_id, mode, language, status, text) "
                        "VALUES (:patient_id, 'text', 'hi', 'ready_for_review', 'sir dard hai') "
                        "RETURNING id"
                    ),
                    {"patient_id": patient_id},
                )
            )
            pre_summary_id = int(
                await connection.scalar(
                    text(
                        "INSERT INTO intake.intake_pre_summaries (intake_id, review_state) "
                        "VALUES (:intake_id, 'draft') RETURNING id"
                    ),
                    {"intake_id": intake_id},
                )
            )

        facade = IntakeFacade(engine=facade_engine, ai_gateway=MockAiProvider())
        draft = await facade.request_rx_draft(
            doctor_input_ref=1, pre_summary_ref=pre_summary_id, history_summary="past notes"
        )
        assert draft.rx_items[0].name == "mock medication"

        with (
            patch.object(
                MockAiProvider,
                "draft_rx",
                side_effect=Ext002CallError("provider unavailable", retries_exhausted=True),
            ),
            pytest.raises(Ext002CallError),
        ):
            await facade.request_rx_draft(
                doctor_input_ref=1, pre_summary_ref=pre_summary_id, history_summary="again"
            )

        async with engine.connect() as connection:
            jobs = await connection.execute(
                text(
                    "SELECT task_type, status, provider, model, confidence, duration_ms, "
                    "error_message FROM intake.intake_ai_jobs WHERE intake_id = :intake_id "
                    "ORDER BY id"
                ),
                {"intake_id": intake_id},
            )
            job_rows = [dict(mapping) for mapping in jobs.mappings().all()]
        assert [row["task_type"] for row in job_rows] == ["draft", "draft"]
        assert [row["status"] for row in job_rows] == ["completed", "failed"]
        assert job_rows[0]["duration_ms"] is not None
        # The failed call reports no usage, so it records no token count rather
        # than a fabricated free call.
        assert job_rows[1]["error_message"] == "Ext002CallError"

        registry = _registry()
        async with engine.connect() as connection:
            tables = await discover_outbox_tables(connection, ("intake",))
        for table in tables:
            await process_outbox_table(engine, table, registry, DEFAULT_DISPATCHER_CONFIG)

        async with engine.connect() as connection:
            rows = await _usage_rows(connection)
            spend = await _spend_rows(connection)
            stored = await _attribution_table_text(connection)
        draft_row = next(row for row in rows if str(row["task_type"]) == "draft")
        assert draft_row["provider"] == MOCK_AI_PROVIDER
        assert draft_row["model"] == MOCK_AI_MODEL
        assert draft_row["calls"] == 2
        assert draft_row["success_count"] == 1
        assert draft_row["failure_count"] == 1
        assert draft_row["timeout_count"] == 0
        assert draft_row["cost_paise"] == 0
        # The mock is clean (0.8), so nothing lands in the low-confidence bucket.
        assert draft_row["low_confidence_count"] == 0

        # #723: the metered drafting leg is metered GRANULARLY too, so the spend
        # an operator attributes to this patient's prescription is a row it can
        # point at, not a counter that was averaged away with everyone else's.
        # Counted per status rather than read positionally, so the assertion does
        # not depend on the reader's ORDER BY.
        assert {str(row["status"]) for row in spend} == {"completed", "failed"}
        assert all(row["task_type"] == "draft" for row in spend)
        assert [row["status"] for row in spend].count("completed") == 1
        assert [row["status"] for row in spend].count("failed") == 1
        assert spend[0]["patient_key"] == actor_key(ACTOR_KIND_PATIENT, patient_id)

        # And the drafting leg is the one place clinical content came closest to
        # the boundary - the patient's complaint text is sitting in the intake row
        # this job was produced from. None of it follows the job into telemetry.
        assert "sir dard hai" not in stored
        assert "mock medication" not in stored
        assert str(patient_id) not in stored
    finally:
        await facade_engine.dispose()
        await engine.dispose()


async def _nullable_columns(database_url: str, schema: str, table: str) -> set[str]:
    engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = :schema AND table_name = :table "
                    "AND is_nullable = 'YES'"
                ),
                {"schema": schema, "table": table},
            )
            return {str(row[0]) for row in result}
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_daily_aggregate_ships_empty_revenue_and_tier_dimensions(
    database_url: str, clean_tables: None
) -> None:
    """AC (#723): the daily per-actor aggregate carries nullable revenue and tier.

    Reaches below the seam deliberately, with a comment: the rule is about a
    column being ABSENT of data and PERMITTED to be empty, which no read can
    show because nothing reads the table yet. #717 decision 9 defers the revenue
    model entirely, so the contract this pins is that the two dimensions EXIST,
    are NULLABLE (so a rollup can leave them empty rather than invent a zero),
    and that no writer has written one - turning monetization on is then a data
    write, exactly as the decision claims, not a migration.
    """
    nullable = await _nullable_columns(
        database_url, "observability", "observability_attribution_daily"
    )
    assert {"revenue_paise", "tier_key"} <= nullable

    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            counts = await _row_counts(connection)
    finally:
        await engine.dispose()
    assert counts["observability.observability_attribution_daily"] == 0


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


# ------------------------------------------------------ B4e #739: the product ledger


async def _product_rows(connection: AsyncConnection) -> list[dict[str, object]]:
    result = await connection.execute(
        text(
            "SELECT event_id, occurred_at, actor_kind, actor_key, session_key, trace_id, "
            "funnel, step, outcome, duration_ms "
            "FROM observability.observability_product_events ORDER BY id"
        )
    )
    return [dict(mapping) for mapping in result.mappings().all()]


async def _product_table_text(connection: AsyncConnection) -> str:
    """Every stored value of the product tables, flattened to one string.

    The rule being proven is an ABSENCE - this schema carries no raw identity
    reference and no clinical content - so it has to be asserted over the whole
    tables rather than over the columns one read happens to select.
    """
    rows = await connection.execute(
        text(
            "SELECT to_jsonb(e)::text AS row FROM observability.observability_product_events e "
            "UNION ALL "
            "SELECT to_jsonb(d)::text FROM observability.observability_product_daily d "
            "UNION ALL "
            "SELECT to_jsonb(a)::text FROM observability.observability_product_actor_daily a"
        )
    )
    return " ".join(str(row[0]) for row in rows.all())


@pytest.mark.asyncio
async def test_the_composers_entry_step_lands_in_the_ledger_and_replay_changes_nothing(
    database_url: str, clean_tables: None
) -> None:
    """AC (#739): the funnel's HEAD lands, carries a trace, and is replay-safe.

    The entry step is the whole reason #721 exists: ``intake.started`` rides the
    capture transaction, so a patient who opened the composer and walked away left
    no trace at all and the funnel had no head to drop off from. This drives the REAL
    producer - ``IntakeFacade.record_composer_opened`` writes its own outbox row in
    its own transaction - then the real dispatcher with the real registry, so the
    entry step is PUBLISHED and consumed, not hand-written into the ledger here.

    Proved at the real-database seam:

    1. The composer's opening becomes one ``intake.composer_opened`` product row,
       attributed to the hashed patient and carrying the published trace.
    2. A care step sharing an event type with the business counter writes BOTH rows
       from one seat - they cannot be separated, because the consumed-event ledger
       is keyed by ``event_id`` alone and a second seat would be told it is a replay.
    3. Replaying every ``event_id`` changes no row count anywhere.
    4. Nothing PHI and no raw reference reaches any of the three tables.
    """
    engine = create_async_engine(database_url, poolclass=NullPool)
    facade_engine = create_async_engine(database_url, poolclass=NullPool)
    patient_ref = 700_000_021
    doctor_ref = 900_000_011
    try:
        facade = IntakeFacade(engine=facade_engine, ai_gateway=MockAiProvider())
        await facade.record_composer_opened(patient_id=patient_ref, trace_id=_TRACE_ID)

        # The producer minted the event_id; keep it so the replay below is a genuine
        # redelivery of the same delivery rather than a second event.
        async with engine.connect() as connection:
            composer_event_id = await connection.scalar(
                text(f"SELECT event_id FROM intake.{INTAKE_OUTBOX_TABLE}")
            )
        assert composer_event_id is not None

        registry = _registry()
        async with engine.connect() as connection:
            tables = await discover_outbox_tables(connection, ("intake",))
        for table in tables:
            await process_outbox_table(engine, table, registry, DEFAULT_DISPATCHER_CONFIG)

        consult = Envelope[CaseConsultCompleteTelemetryPayload](
            event_id=uuid4(),
            event_type=EVENT_CASE_CONSULT_COMPLETE,
            producer="care",
            occurred_at=_NOW,
            payload=CaseConsultCompleteTelemetryPayload(
                case_id=1, patient_id=patient_ref, doctor_id=doctor_ref
            ),
        )
        await dispatch(registry, consult)

        async with engine.connect() as connection:
            rows = await _product_rows(connection)
            business = await _business_rows(connection)
        assert [row["step"] for row in rows] == ["composer_opened", "consult_complete"]

        entry = rows[0]
        assert entry["event_id"] == composer_event_id
        assert entry["funnel"] == "intake"
        assert entry["outcome"] == "completed"
        assert entry["trace_id"] == _TRACE_ID
        # #721's convention: the session scope IS the request's trace. Both columns
        # are NOT NULL precisely because an untraceable row is not useful.
        assert entry["session_key"] == _TRACE_ID
        assert entry["actor_kind"] == ACTOR_KIND_PATIENT
        assert entry["actor_key"] == actor_key(ACTOR_KIND_PATIENT, patient_ref)
        # The composer opening is an instant, not a span - NULL, never a zero.
        assert entry["duration_ms"] is None

        consult_row = rows[1]
        assert consult_row["step"] == "consult_complete"
        assert consult_row["actor_kind"] == ACTOR_KIND_DOCTOR
        assert consult_row["actor_key"] == actor_key(ACTOR_KIND_DOCTOR, doctor_ref)
        assert business == {EVENT_CASE_CONSULT_COMPLETE: 1}

        async with engine.connect() as connection:
            stored = await _product_table_text(connection)
        assert str(patient_ref) not in stored
        assert str(doctor_ref) not in stored

        # Replay BOTH event ids - the composer's, redelivered verbatim, and the
        # consult's - and prove no row count moved anywhere.
        async with engine.connect() as connection:
            before_replay = await _row_counts(connection)
        await dispatch(
            registry,
            Envelope[IntakeComposerOpenedTelemetryPayload](
                event_id=composer_event_id,
                event_type=EVENT_INTAKE_COMPOSER_OPENED,
                producer="intake",
                occurred_at=_NOW,
                payload=IntakeComposerOpenedTelemetryPayload(
                    patient_id=patient_ref, session_key=_TRACE_ID, trace_id=_TRACE_ID
                ),
            ),
        )
        await dispatch(registry, consult)

        async with engine.connect() as connection:
            after_replay = await _row_counts(connection)
        assert after_replay == before_replay
        assert after_replay["observability.observability_product_events"] == 2
    finally:
        await facade_engine.dispose()
        await engine.dispose()


@pytest.mark.asyncio
async def test_the_daily_rollup_turns_the_ledger_into_two_grains_and_survives_a_rerun(
    database_url: str, clean_tables: None
) -> None:
    """AC (#739, widened by #742): the daily rollups are what a long window reads.

    The ledger is the append-only record; these daily tables are the answer. They are
    derived from ONE read of the ledger, not from per-grain queries, and there are two
    grains because a cohort cannot be answered by the other:

    * ``observability_product_daily`` - per ``(funnel, step, outcome)``, carrying a
      DISTINCT actor count beside the event count. One actor who opens the composer
      and then captures is two events and one active actor.
    * ``observability_product_actor_daily`` - per ``(actor, day)``, the identity-grain
      companion #742 adds. The step grain stores a distinct COUNT, and distinctness
      does not survive being stored: "of the people new on day D, how many came back
      on D+7" is a question about identities, and the only way back to them from a
      count is to sum - which double-counts precisely the people who got furthest.

    Re-running the pass must land on the identical rows rather than adding to them,
    which is the property a step that arrives after the day's first pass depends on.
    """
    engine = create_async_engine(database_url, poolclass=NullPool)
    patient_ref = 700_000_031
    other_patient_ref = 700_000_032
    doctor_ref = 900_000_021
    try:
        registry = _registry()
        composer = intake_composer_opened_envelope(
            patient_id=patient_ref, session_key=_TRACE_ID, trace_id=_TRACE_ID
        )
        second_composer = intake_composer_opened_envelope(
            patient_id=other_patient_ref, session_key=_TRACE_ID, trace_id=_TRACE_ID
        )
        # #722's re-record: no identity reference behind it, so it must count as an
        # event with NO actor rather than as a placeholder actor.
        retry = Envelope[IntakeRetryRequestedTelemetryPayload](
            event_id=uuid4(),
            event_type=EVENT_INTAKE_RETRY_REQUESTED,
            producer="intake",
            occurred_at=_NOW,
            payload=IntakeRetryRequestedTelemetryPayload(intake_id=1, record_attempt=2),
        )
        captured = Envelope[IntakeCapturedTelemetryPayload](
            event_id=uuid4(),
            event_type=EVENT_INTAKE_CAPTURED,
            producer="intake",
            occurred_at=_NOW,
            payload=IntakeCapturedTelemetryPayload(
                intake_id=1, patient_id=patient_ref, duration_s=12.5
            ),
        )
        consult = Envelope[CaseConsultCompleteTelemetryPayload](
            event_id=uuid4(),
            event_type=EVENT_CASE_CONSULT_COMPLETE,
            producer="care",
            occurred_at=_NOW,
            payload=CaseConsultCompleteTelemetryPayload(
                case_id=1, patient_id=patient_ref, doctor_id=doctor_ref
            ),
        )
        # ``intake_composer_opened_envelope`` stamps ``occurred_at`` at the wall clock,
        # and the rollup is keyed by the day - so the envelopes are re-stamped onto
        # the day under test rather than rolled wherever today happens to be.
        for envelope in (
            _at(composer, _NOW),
            _at(second_composer, _NOW),
            retry,
            captured,
            consult,
        ):
            await dispatch(registry, envelope)

        async with engine.connect() as connection:
            landed = await _product_rows(connection)
        # The ledger itself, before any rollup: five deliveries, five rows, each
        # attributed to the registry entry rather than to a hand-written step name.
        assert [(row["step"], row["actor_key"]) for row in landed] == [
            ("composer_opened", actor_key(ACTOR_KIND_PATIENT, patient_ref)),
            ("composer_opened", actor_key(ACTOR_KIND_PATIENT, other_patient_ref)),
            ("re_recorded", None),
            ("intake_captured", actor_key(ACTOR_KIND_PATIENT, patient_ref)),
            ("consult_complete", actor_key(ACTOR_KIND_DOCTOR, doctor_ref)),
        ]

        first = await run_rollup(engine, _NOW.date(), thresholds=_THRESHOLDS)
        # One row per (funnel, step, outcome) scope: four steps, four scopes.
        assert first.product_rows == 4
        # The actor grain is derived from the SAME read of the SAME day, so it is
        # three rows: the doctor who completed the consult, the patient who opened the
        # composer and captured an intake (two events, one person), and the second
        # patient. The re-record records no actor and so has no row here at all.
        assert first.product_actor_rows == 3

        async with engine.connect() as connection:
            daily = (
                (
                    await connection.execute(
                        text(
                            "SELECT step, outcome, events, actor_count, total_duration_ms, "
                            "duration_samples FROM observability.observability_product_daily "
                            "WHERE event_date = :day ORDER BY step"
                        ),
                        {"day": _NOW.date()},
                    )
                )
                .mappings()
                .all()
            )
            actor_daily = (
                (
                    await connection.execute(
                        text(
                            "SELECT actor_kind, actor_key, events "
                            "FROM observability.observability_product_actor_daily "
                            "WHERE event_date = :day "
                            "ORDER BY actor_kind, actor_key"
                        ),
                        {"day": _NOW.date()},
                    )
                )
                .mappings()
                .all()
            )

        assert [dict(row) for row in actor_daily] == [
            {
                "actor_kind": ACTOR_KIND_DOCTOR,
                "actor_key": actor_key(ACTOR_KIND_DOCTOR, doctor_ref),
                "events": 1,
            },
            {
                "actor_kind": ACTOR_KIND_PATIENT,
                "actor_key": actor_key(ACTOR_KIND_PATIENT, patient_ref),
                # Composer-opened AND captured: two clinical actions, one cohort member.
                # Counting this row twice is how a cohort double-counts everyone who
                # got past the first step.
                "events": 2,
            },
            {
                "actor_kind": ACTOR_KIND_PATIENT,
                "actor_key": actor_key(ACTOR_KIND_PATIENT, other_patient_ref),
                "events": 1,
            },
        ]

        assert [dict(row) for row in daily] == [
            {
                "step": "composer_opened",
                "outcome": "completed",
                "events": 2,
                "actor_count": 2,
                "total_duration_ms": 0,
                "duration_samples": 0,
            },
            {
                "step": "consult_complete",
                "outcome": "completed",
                "events": 1,
                "actor_count": 1,
                "total_duration_ms": 0,
                "duration_samples": 0,
            },
            {
                "step": "intake_captured",
                "outcome": "completed",
                "events": 1,
                "actor_count": 1,
                # The only measured span in the funnel; the composer entry has none.
                "total_duration_ms": 12500,
                "duration_samples": 1,
            },
            {
                "step": "re_recorded",
                "outcome": "re_recorded",
                "events": 1,
                "actor_count": 0,
                "total_duration_ms": 0,
                "duration_samples": 0,
            },
        ]
        # Recompute, never accumulate: a second pass over the same ledger lands on
        # the identical rows, so a step that arrives late is picked up rather than
        # added to.
        second = await run_rollup(engine, _NOW.date(), thresholds=_THRESHOLDS)
        assert second.product_rows == first.product_rows
        assert second.product_actor_rows == first.product_actor_rows
        async with engine.connect() as connection:
            rerun_daily = await connection.scalar(
                text("SELECT COUNT(*) FROM observability.observability_product_daily")
            )
            rerun_actor_daily = await connection.scalar(
                text("SELECT COUNT(*) FROM observability.observability_product_actor_daily")
            )
        assert rerun_daily == 4
        assert rerun_actor_daily == 3
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_a_step_added_to_the_registry_lands_with_no_migration(
    database_url: str, clean_tables: None
) -> None:
    """The criterion that distinguishes #739: adding a step touches NO table.

    ``prescription.reviewed`` is a real MOD-006 event with no MOD-013 subscription
    yet. Registering it as a funnel step - one registry line and one mirror - has to
    be enough for the ledger to record it and for the nightly rollup to aggregate
    it, against a schema that was migrated before the step existed. Nothing here runs
    alembic; if the funnel needed a migration for a new step, this test could not
    pass without one.
    """
    engine = create_async_engine(database_url, poolclass=NullPool)
    doctor_ref = 900_000_041
    try:

        class PrescriptionReviewedMirror(ProductStepPayload):
            case_id: int
            prescription_id: int
            patient_id: int
            doctor_id: int

        step = ProductStep(
            funnel=FUNNEL_INTAKE,
            step="prescription_reviewed",
            event_type=EVENT_PRESCRIPTION_REVIEWED,
            outcome=PRODUCT_OUTCOME_COMPLETED,
            allowed_outcomes=(PRODUCT_OUTCOME_COMPLETED,),
            actor_kind=ACTOR_KIND_DOCTOR,
        )
        register_product_step(step)
        PRODUCT_EVENT_MIRRORS[EVENT_PRESCRIPTION_REVIEWED] = PrescriptionReviewedMirror
        try:
            registry = HandlerRegistry()
            register_observability_handlers(registry)

            envelope = Envelope[PrescriptionReviewedMirror](
                event_id=uuid4(),
                event_type=EVENT_PRESCRIPTION_REVIEWED,
                producer="care",
                occurred_at=_NOW,
                payload=PrescriptionReviewedMirror(
                    case_id=1, prescription_id=2, patient_id=700_000_041, doctor_id=doctor_ref
                ),
            )
            await dispatch(registry, envelope)

            async with engine.connect() as connection:
                rows = await _product_rows(connection)
            assert [row["step"] for row in rows] == ["prescription_reviewed"]
            assert rows[0]["actor_key"] == actor_key(ACTOR_KIND_DOCTOR, doctor_ref)

            report = await run_rollup(engine, _NOW.date(), thresholds=_THRESHOLDS)
            assert report.product_rows == 1
            async with engine.connect() as connection:
                step_name = await connection.scalar(
                    text(
                        "SELECT step FROM observability.observability_product_daily "
                        "WHERE event_date = :day"
                    ),
                    {"day": _NOW.date()},
                )
            assert step_name == "prescription_reviewed"
        finally:
            PRODUCT_EVENT_MIRRORS.pop(EVENT_PRESCRIPTION_REVIEWED, None)
            product_module.PRODUCT_STEP_REGISTRY.pop((FUNNEL_INTAKE, step.step), None)
            product_module._EVENT_STEP_INDEX.pop(EVENT_PRESCRIPTION_REVIEWED, None)
    finally:
        await engine.dispose()


# ------------------------------------------------- T3.5 #752: the annotation queue


async def _annotation_rows(connection: AsyncConnection) -> list[dict[str, object]]:
    result = await connection.execute(
        text(
            "SELECT score_date, source, observation_kind, observation_ref, trace_id, "
            "evaluator, data_type, value FROM "
            "observability.observability_evaluation_scores ORDER BY evaluator"
        )
    )
    return [dict(mapping) for mapping in result.mappings().all()]


async def _annotation_table_text(connection: AsyncConnection) -> str:
    """Every stored value of the queue, flattened to one string.

    The rules being proven are ABSENCES - no free-text rationale, no raw identity
    reference - so they are asserted over the whole table rather than over the
    columns one read happens to select, matching the product-ledger test above.
    """
    rows = await connection.execute(
        text(
            "SELECT to_jsonb(score)::text AS row FROM "
            "observability.observability_evaluation_scores score"
        )
    )
    return " ".join(str(row[0]) for row in rows.all())


@pytest.mark.asyncio
async def test_doctor_review_outcomes_land_in_the_annotation_queue_replay_safe(
    database_url: str, clean_tables: None
) -> None:
    """AC (#752): the queue is fed by review outcomes, PHI-free, carrying the trace.

    1. An approval (unchanged) and a rejection, published through the CARE outbox
       under a bound request trace, become two ``source = 'human'`` score rows -
       the queue is fed by EVENTS, never by a read of MOD-006's tables (ADR-0003).
    2. The approval rides its existing funnel-step seat, so one delivery writes
       the ledger row AND the queue entry; a second seat for it would have been
       told it is a replay and written nothing.
    3. The rejection's free-text rationale never reaches storage.
    4. Replaying both event_ids changes no row count anywhere.
    5. A later outcome delivered with no request trace leaves its queue row's
       trace id NULL rather than substituting a synthetic one.
    """
    engine = create_async_engine(database_url, poolclass=NullPool)
    patient_ref = 700_000_051
    doctor_ref = 900_000_051
    prescription_ref = 800_000_011
    try:
        approved = _at(
            prescription_approved_envelope(
                case_id=1,
                prescription_id=prescription_ref,
                patient_id=patient_ref,
                doctor_id=doctor_ref,
                edited_yn=False,
            ),
            _NOW,
        )
        rejected = _at(
            prescription_rejected_envelope(
                case_id=1,
                prescription_id=prescription_ref,
                patient_id=patient_ref,
                doctor_id=doctor_ref,
                reason="dose looks wrong for this patient",
            ),
            _NOW,
        )

        # Published exactly as the producer publishes: inside the transaction, with
        # the request's trace bound, so the outbox row carries the real traceparent.
        async with engine.begin() as connection:
            token = set_trace_id(_TRACE_ID)
            try:
                await write_outbox(connection, "care", CARE_OUTBOX_TABLE, approved)
                await write_outbox(connection, "care", CARE_OUTBOX_TABLE, rejected)
            finally:
                reset_trace_id(token)

        registry = _registry()
        # The producer owns its payload models, so the care subscriptions have to be
        # registered for the dispatcher to reconstruct a claimed ``care_outbox`` row
        # - exactly as the composition root does in the worker.
        register_care_handlers(registry)
        async with engine.connect() as connection:
            tables = await discover_outbox_tables(connection, ("care",))
        for table in tables:
            await process_outbox_table(engine, table, registry, DEFAULT_DISPATCHER_CONFIG)

        async with engine.connect() as connection:
            queue = await _annotation_rows(connection)
            product = await _product_rows(connection)

        assert [(row["evaluator"], row["observation_ref"]) for row in queue] == [
            (ANNOTATION_EVALUATOR_ACCEPTED_UNCHANGED, str(prescription_ref)),
            (ANNOTATION_EVALUATOR_REJECTED, str(prescription_ref)),
        ]
        for row in queue:
            assert row["source"] == "human"
            assert row["observation_kind"] == "prescription"
            assert row["data_type"] == "BOOLEAN"
            assert row["value"] == Decimal("1")
            assert row["score_date"] == _NOW.date()
            assert row["trace_id"] == _TRACE_ID

        # The approval's funnel step landed from the SAME delivery.
        assert [row["step"] for row in product] == ["prescription_approved"]

        async with engine.connect() as connection:
            stored = await _annotation_table_text(connection)
        assert "dose looks wrong" not in stored
        assert str(patient_ref) not in stored
        assert str(doctor_ref) not in stored

        # Replay BOTH event_ids: the ledger conflict swallows the delivery and no
        # row count anywhere moves.
        before_replay: dict[str, int] = {}
        async with engine.connect() as connection:
            before_replay = await _row_counts(connection)
        await dispatch(registry, approved)
        await dispatch(registry, rejected)
        async with engine.connect() as connection:
            after_replay = await _row_counts(connection)
        assert after_replay == before_replay

        # An outcome nobody traced: the queue still records the verdict, and the
        # trace id is an honest NULL rather than the event's own id.
        untraced = _at(
            prescription_approved_envelope(
                case_id=1,
                prescription_id=prescription_ref + 1,
                patient_id=patient_ref,
                doctor_id=doctor_ref,
                edited_yn=True,
            ),
            _NOW,
        )
        token = set_trace_id(None)
        try:
            await dispatch(registry, untraced)
        finally:
            reset_trace_id(token)

        async with engine.connect() as connection:
            queue = await _annotation_rows(connection)
        assert [(row["evaluator"], row["trace_id"]) for row in queue] == [
            (ANNOTATION_EVALUATOR_ACCEPTED_EDITED, None),
            (ANNOTATION_EVALUATOR_ACCEPTED_UNCHANGED, _TRACE_ID),
            (ANNOTATION_EVALUATOR_REJECTED, _TRACE_ID),
        ]
    finally:
        await engine.dispose()
