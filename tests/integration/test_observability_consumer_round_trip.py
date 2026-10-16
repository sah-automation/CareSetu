"""B4a #702, B4 #722, B6 #723, B7 #724: MOD-013 consumer round trip vs real PostgreSQL.

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
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
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
    EVENT_INTAKE_DOCTOR_ASSIGNED,
)
from bus.outbox_writer import write_outbox
from bus.registry import HandlerRegistry
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
    IntakeDoctorAssignedPayload,
)
from modules.intake.facade import IntakeFacade
from modules.intake.outbox import INTAKE_OUTBOX_TABLE
from modules.observability.adapters import (
    register_handlers as register_observability_handlers,
)
from modules.observability.domain.consumer import (
    MAX_FAILURE_REASON_CHARS,
    CaseConsultCompleteTelemetryPayload,
    ConsentLifecycleTelemetryPayload,
    TamperDetectedTelemetryPayload,
)
from modules.observability.domain.pseudonym import (
    ACTOR_KIND_DOCTOR,
    ACTOR_KIND_PATIENT,
    actor_key,
)

_NOW = datetime(2026, 10, 13, 8, 15, 0, tzinfo=UTC)

#: A well-formed W3C trace-id (32 lowercase hex) the widened payloads carry (#719).
_TRACE_ID = "a" * 32


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


async def _row_counts(connection: AsyncConnection) -> dict[str, int]:
    """Every table this batch's consumption can write, counted at once."""
    counts = {}
    for table in (
        "observability.observability_ai_usage_daily",
        "observability.observability_ai_job_spend",
        "observability.observability_care_attribution_edges",
        "observability.observability_attribution_daily",
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
            "observability.observability_care_attribution_edges": 0,
            "observability.observability_attribution_daily": 0,
            "observability.consumed_events": 4,
        }
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
