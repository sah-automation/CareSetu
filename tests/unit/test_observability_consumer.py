"""B4a #702, B6 #723, B7 #724: MOD-013 consumer registration + exactly-once effects.

Covers the composition-root seam: the ``ai_job.completed`` / ``ai_job.failed``
consumers register handler seats at the worker without ever owning (or
stealing) the ``ai_job.*`` registry payload models - MOD-005 owns those, and
MOD-013 merely re-validates the dispatched intake payload into its local mirror
(the MOD-011 consumer shape). The replay test drives the registered handler
through the same short-lived engine + ledger seam as the live dispatcher: a
replayed ``event_id`` is a no-op (ledger dedupe), so every effect behind that one
ledger row - the daily accumulation AND the per-job spend row - runs exactly once
per distinct event.

B7 (#724) adds the ``intake.doctor_assigned`` seat on the same shape: one
consumer for the care-attribution edge, with MOD-005 still owning the registry
payload model and MOD-013 holding a three-reference mirror of its own.

B9 (#728) adds the sanitiser for the failure reason kept on the per-job spend
row, so the provider board can name a degradation. The sanitiser is tested HERE,
at the consumer seam, because its whole job is to decide what may be written -
before the value reaches the write, not after.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel

from bus.envelope import Envelope
from bus.events import (
    EVENT_AI_JOB_COMPLETED,
    EVENT_AI_JOB_FAILED,
    EVENT_AI_JOB_QUEUED,
    EVENT_INTAKE_DOCTOR_ASSIGNED,
)
from bus.registry import HandlerRegistry
from modules.intake.adapters import register_handlers as register_intake_handlers
from modules.intake.domain.events import (
    AiJobCompletedPayload,
    AiJobFailedPayload,
    AiJobQueuedPayload,
    IntakeDoctorAssignedPayload,
    ai_job_completed_envelope,
    ai_job_failed_envelope,
    ai_job_queued_envelope,
    intake_doctor_assigned_envelope,
)
from modules.observability.adapters import register_handlers as register_obs_handlers
from modules.observability.domain.consumer import (
    MAX_FAILURE_REASON_CHARS,
    AiJobCompletedUsagePayload,
    AiJobFailedUsagePayload,
    AiJobQueuedTelemetryPayload,
    IntakeDoctorAssignedTelemetryPayload,
    sanitize_failure_reason,
)
from modules.observability.domain.pseudonym import ACTOR_KIND_PATIENT, actor_key


def test_register_handlers_registers_both_consumers_without_owning_the_models() -> None:
    registry = HandlerRegistry()
    register_intake_handlers(registry)
    register_obs_handlers(registry)

    # MOD-013 has exactly one consumer seat per ai_job.* event type.
    assert len(registry.handlers_for(EVENT_AI_JOB_COMPLETED)) == 1
    assert len(registry.handlers_for(EVENT_AI_JOB_FAILED)) == 1
    # The enqueue seat too (#729): without it there is nothing to subtract
    # completed and failed from, so queue depth would have no enqueue term.
    assert len(registry.handlers_for(EVENT_AI_JOB_QUEUED)) == 1

    # MOD-005 still owns the registry payload models; MOD-013 never registered a
    # duplicate (which the registry's one-model-per-type guard would reject).
    assert registry.payload_model_for(EVENT_AI_JOB_COMPLETED) is AiJobCompletedPayload
    assert registry.payload_model_for(EVENT_AI_JOB_FAILED) is AiJobFailedPayload
    assert registry.payload_model_for(EVENT_AI_JOB_QUEUED) is AiJobQueuedPayload


def test_ai_job_queued_payload_revalidates_into_the_observability_mirror() -> None:
    """The queue needs the job, the queue it sits in and the actor - nothing clinical."""
    envelope = ai_job_queued_envelope(
        ai_job_id=11,
        intake_id=42,
        task_type="structure",
        patient_id=7,
        trace_id="e" * 32,
    )
    mirror = AiJobQueuedTelemetryPayload.model_validate(envelope.payload.model_dump())
    assert isinstance(mirror, AiJobQueuedTelemetryPayload)
    assert mirror.ai_job_id == 11
    # ``task_type`` IS the queue name: one queue per pipeline leg.
    assert mirror.task_type == "structure"
    assert mirror.patient_id == 7
    # No doctor reference to mirror: the producer has none to give at enqueue time
    # (ADR-0003 keeps the drafting doctor in the care schema), so a mirrored field
    # would only ever be null - and a null identity reference in a no-PHI store is
    # still an identity column somebody will later be tempted to fill.
    assert not hasattr(mirror, "doctor_id")
    assert mirror.trace_id == "e" * 32
    # The enqueue INSTANT is the envelope's, not a payload field the producer could
    # disagree with - that is what makes the age figure trustworthy.
    assert not hasattr(mirror, "queued_at")


def test_doctor_assigned_registers_one_consumer_without_owning_the_model() -> None:
    """The care-attribution seat exists, and MOD-005 still owns the payload model."""
    registry = HandlerRegistry()
    register_intake_handlers(registry)
    register_obs_handlers(registry)

    assert len(registry.handlers_for(EVENT_INTAKE_DOCTOR_ASSIGNED)) == 1
    assert registry.payload_model_for(EVENT_INTAKE_DOCTOR_ASSIGNED) is IntakeDoctorAssignedPayload


def test_doctor_assigned_payload_revalidates_into_the_observability_mirror() -> None:
    """The three references the edge needs travel, and nothing clinical rides along."""
    envelope = intake_doctor_assigned_envelope(intake_id=42, patient_id=7, doctor_id=8)
    mirror = IntakeDoctorAssignedTelemetryPayload.model_validate(envelope.payload.model_dump())
    assert isinstance(mirror, IntakeDoctorAssignedTelemetryPayload)
    assert mirror.intake_id == 42
    assert mirror.patient_id == 7
    assert mirror.doctor_id == 8


def test_intake_completed_payload_revalidates_into_the_observability_mirror() -> None:
    envelope = ai_job_completed_envelope(
        ai_job_id=9,
        intake_id=42,
        task_type="structure",
        provider="openai",
        model="gpt-4o-mini",
        input_tokens=900,
        output_tokens=150,
        cost_paise=24,
        duration_ms=1200,
        low_confidence=True,
        patient_id=7,
        doctor_id=8,
        trace_id="e" * 32,
    )
    mirror = AiJobCompletedUsagePayload.model_validate(envelope.payload.model_dump())
    assert isinstance(mirror, AiJobCompletedUsagePayload)
    assert mirror.provider == "openai"
    assert mirror.model == "gpt-4o-mini"
    assert mirror.input_tokens == 900
    assert mirror.output_tokens == 150
    assert mirror.cost_paise == 24
    assert mirror.duration_ms == 1200
    assert mirror.low_confidence is True
    # B4c (#719): the widened identity references revalidate into the mirror.
    assert mirror.patient_id == 7
    assert mirror.doctor_id == 8
    assert mirror.trace_id == "e" * 32


def test_intake_failed_payload_revalidates_into_the_observability_mirror() -> None:
    envelope = ai_job_failed_envelope(
        ai_job_id=9,
        intake_id=42,
        task_type="transcribe",
        reason="Ext002CallError",
        provider="openai",
        model="whisper-1",
        timeout=True,
        patient_id=7,
        doctor_id=None,
        trace_id=None,
    )
    mirror = AiJobFailedUsagePayload.model_validate(envelope.payload.model_dump())
    assert isinstance(mirror, AiJobFailedUsagePayload)
    assert mirror.provider == "openai"
    assert mirror.model == "whisper-1"
    assert mirror.reason == "Ext002CallError"
    assert mirror.timeout is True
    # B4c (#719): the transcription leg has no doctor; the reference stays null.
    assert mirror.patient_id == 7
    assert mirror.doctor_id is None
    assert mirror.trace_id is None


@pytest.mark.asyncio
async def test_completed_handler_accumulates_exactly_once_per_event_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Replayed ``event_id`` is a ledger no-op that never touches the aggregate."""
    registry = HandlerRegistry()
    register_intake_handlers(registry)
    register_obs_handlers(registry)
    handler = registry.handlers_for(EVENT_AI_JOB_COMPLETED)[0]

    engine = MagicMock()
    engine.begin.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
    engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)
    engine.dispose = AsyncMock()
    monkeypatch.setattr("bus.handler_harness._delivery_engine", lambda: engine)

    delivered: set[str] = set()
    accumulate = AsyncMock()

    async def fake_ledger(
        conn: object, schema: str, envelope: Envelope[BaseModel], handler_result: object
    ) -> bool:
        del conn, schema, handler_result
        if str(envelope.event_id) in delivered:
            return False
        delivered.add(str(envelope.event_id))
        return True

    monkeypatch.setattr("bus.handler_harness.record_consumed_event", fake_ledger)
    monkeypatch.setattr("modules.observability.adapters.accumulate_ai_usage", accumulate)

    first = ai_job_completed_envelope(
        ai_job_id=9,
        intake_id=42,
        task_type="structure",
        provider="openai",
        model="gpt-4o-mini",
        input_tokens=900,
        output_tokens=150,
        cost_paise=24,
        duration_ms=1200,
        low_confidence=True,
        patient_id=7,
        doctor_id=None,
        trace_id=None,
    )
    second = ai_job_completed_envelope(
        ai_job_id=10,
        intake_id=42,
        task_type="structure",
        provider="openai",
        model="gpt-4o-mini",
        input_tokens=600,
        output_tokens=90,
        cost_paise=14,
        duration_ms=800,
        low_confidence=False,
        patient_id=7,
        doctor_id=None,
        trace_id=None,
    )

    await handler(first)
    assert accumulate.await_count == 1
    assert isinstance(accumulate.await_args.args[2], AiJobCompletedUsagePayload)
    assert accumulate.await_args.args[2].low_confidence is True

    # Replay: the ledger row already exists, so every effect behind it is skipped.
    # What that guarantees for the WHOLE handler - including the per-job spend
    # row of #723, which this file deliberately does not mock - is asserted once,
    # at the real-database seam, in
    # tests/integration/test_observability_consumer_round_trip.py.
    await handler(first)
    assert accumulate.await_count == 1

    await handler(second)
    assert accumulate.await_count == 2
    assert accumulate.await_args.args[2].low_confidence is False


@pytest.mark.asyncio
async def test_failed_handler_accumulates_exactly_once_per_event_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = HandlerRegistry()
    register_intake_handlers(registry)
    register_obs_handlers(registry)
    handler = registry.handlers_for(EVENT_AI_JOB_FAILED)[0]

    engine = MagicMock()
    engine.begin.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
    engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)
    engine.dispose = AsyncMock()
    monkeypatch.setattr("bus.handler_harness._delivery_engine", lambda: engine)

    delivered: set[str] = set()
    accumulate = AsyncMock()

    async def fake_ledger(
        conn: object, schema: str, envelope: Envelope[BaseModel], handler_result: object
    ) -> bool:
        del conn, schema, handler_result
        if str(envelope.event_id) in delivered:
            return False
        delivered.add(str(envelope.event_id))
        return True

    monkeypatch.setattr("bus.handler_harness.record_consumed_event", fake_ledger)
    monkeypatch.setattr("modules.observability.adapters.accumulate_ai_usage", accumulate)

    timeout = ai_job_failed_envelope(
        ai_job_id=9,
        intake_id=42,
        task_type="structure",
        reason="Ext002CallError",
        provider="openai",
        model="gpt-4o-mini",
        timeout=True,
        patient_id=7,
        doctor_id=None,
        trace_id=None,
    )
    malformed = ai_job_failed_envelope(
        ai_job_id=10,
        intake_id=42,
        task_type="structure",
        reason="ValidationError",
        provider="openai",
        model="gpt-4o-mini",
        timeout=False,
        patient_id=7,
        doctor_id=None,
        trace_id=None,
    )

    await handler(timeout)
    assert accumulate.await_count == 1
    assert accumulate.await_args.args[2].timeout is True

    await handler(timeout)
    assert accumulate.await_count == 1

    await handler(malformed)
    assert accumulate.await_count == 2
    assert accumulate.await_args.args[2].timeout is False


@pytest.mark.asyncio
async def test_queued_handler_opens_the_queue_row_once_per_event_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The enqueue reaches the queue table only on a FIRST delivery (#729).

    Same narrow seam as the tests above: the ledger is faked, so what is proven is
    that the registered seat calls the effect behind a first delivery and skips it
    on a replay. The row the effect writes, and the depth it produces, are asserted
    against real PostgreSQL in the consumer round trip.
    """
    registry = HandlerRegistry()
    register_intake_handlers(registry)
    register_obs_handlers(registry)
    handler = registry.handlers_for(EVENT_AI_JOB_QUEUED)[0]

    engine = MagicMock()
    engine.begin.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
    engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)
    engine.dispose = AsyncMock()
    monkeypatch.setattr("bus.handler_harness._delivery_engine", lambda: engine)

    delivered: set[str] = set()
    open_queue = AsyncMock()

    async def fake_ledger(
        conn: object, schema: str, envelope: Envelope[BaseModel], handler_result: object
    ) -> bool:
        del conn, schema, handler_result
        if str(envelope.event_id) in delivered:
            return False
        delivered.add(str(envelope.event_id))
        return True

    monkeypatch.setattr("bus.handler_harness.record_consumed_event", fake_ledger)
    monkeypatch.setattr("modules.observability.adapters.record_ai_queue_open", open_queue)

    enqueued = ai_job_queued_envelope(
        ai_job_id=11,
        intake_id=42,
        task_type="structure",
        patient_id=7,
        trace_id=None,
    )

    await handler(enqueued)
    assert open_queue.await_count == 1
    mirror = open_queue.await_args.args[2]
    assert isinstance(mirror, AiJobQueuedTelemetryPayload)
    assert mirror.ai_job_id == 11
    assert mirror.task_type == "structure"

    await handler(enqueued)
    assert open_queue.await_count == 1


@pytest.mark.asyncio
async def test_both_close_handlers_close_the_queue_row_for_the_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Completed AND failed take the job out of the queue - depth is their arithmetic.

    A failed job left queued is the worst kind of stuck: it never drains, so it
    would hold the queue-age alert open forever. Both closures must therefore reach
    the effect, not just the happy one.
    """
    registry = HandlerRegistry()
    register_intake_handlers(registry)
    register_obs_handlers(registry)

    engine = MagicMock()
    engine.begin.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
    engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)
    engine.dispose = AsyncMock()
    monkeypatch.setattr("bus.handler_harness._delivery_engine", lambda: engine)

    async def always_delivered(
        conn: object, schema: str, envelope: Envelope[BaseModel], handler_result: object
    ) -> bool:
        del conn, schema, envelope, handler_result
        return True

    monkeypatch.setattr("bus.handler_harness.record_consumed_event", always_delivered)
    monkeypatch.setattr("modules.observability.adapters.accumulate_ai_usage", AsyncMock())
    monkeypatch.setattr("modules.observability.adapters.record_ai_job_spend", AsyncMock())
    close = AsyncMock()
    monkeypatch.setattr("modules.observability.adapters.close_ai_queue_item", close)

    await registry.handlers_for(EVENT_AI_JOB_COMPLETED)[0](
        ai_job_completed_envelope(
            ai_job_id=11,
            intake_id=42,
            task_type="structure",
            provider="openai",
            model="gpt-4o-mini",
            input_tokens=10,
            output_tokens=2,
            cost_paise=1,
            duration_ms=90,
            low_confidence=False,
            patient_id=7,
            doctor_id=None,
            trace_id=None,
        )
    )
    await registry.handlers_for(EVENT_AI_JOB_FAILED)[0](
        ai_job_failed_envelope(
            ai_job_id=12,
            intake_id=42,
            task_type="structure",
            reason="Ext002CallError",
            provider="openai",
            model="gpt-4o-mini",
            timeout=True,
            patient_id=7,
            doctor_id=None,
            trace_id=None,
        )
    )

    assert [call.args[1].ai_job_id for call in close.await_args_list] == [11, 12]


@pytest.mark.asyncio
async def test_the_ai_job_ledger_rows_carry_a_pseudonymous_actor_and_nothing_else(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Recent activity is counted from the ledger, so the ledger must carry an actor.

    The figure is ``distinct actors active in the recent past``, which is a count of
    DISTINCT people - so the delivery record has to say who. Two properties are
    asserted together because they fail in the same place: the key is present for an
    actor-bearing handler, and it is the one-way hash rather than the raw
    reference. A raw ``patient_id`` in this column would put an identity reference in
    a table that carries no PHI.
    """
    registry = HandlerRegistry()
    register_intake_handlers(registry)
    register_obs_handlers(registry)

    engine = MagicMock()
    engine.begin.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
    engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)
    engine.dispose = AsyncMock()
    monkeypatch.setattr("bus.handler_harness._delivery_engine", lambda: engine)

    recorded: list[object] = []

    async def fake_ledger(
        conn: object, schema: str, envelope: Envelope[BaseModel], handler_result: object
    ) -> bool:
        del conn, schema, envelope
        recorded.append(handler_result)
        return True

    monkeypatch.setattr("bus.handler_harness.record_consumed_event", fake_ledger)
    monkeypatch.setattr("modules.observability.adapters.record_ai_queue_open", AsyncMock())

    await registry.handlers_for(EVENT_AI_JOB_QUEUED)[0](
        ai_job_queued_envelope(
            ai_job_id=11,
            intake_id=42,
            task_type="structure",
            patient_id=7,
            trace_id=None,
        )
    )

    assert len(recorded) == 1
    handler_result = recorded[0]
    assert isinstance(handler_result, dict)
    assert handler_result["handler"] == "record_ai_queue_open"
    actor = handler_result["actor_key"]
    assert isinstance(actor, str)
    # One-way hash of the reference, never the reference: a raw ``patient_id`` here
    # would put an identity in a table that carries no PHI. (The digest is hex, so
    # its characters are not asserted against - only the shape and its provenance.)
    assert actor == actor_key(ACTOR_KIND_PATIENT, 7)
    assert len(actor) == 64
    assert actor != "7"


@pytest.mark.asyncio
async def test_care_attribution_handler_writes_the_edge_exactly_once_per_event_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A replayed ``event_id`` writes no edge; a genuinely new event does.

    This file fakes the ledger, so what is under test is narrower than it looks:
    that the registered handler reaches the effect only when ``run_handler``
    reports a first delivery. The exactly-once guarantee itself, and the row the
    effect writes - including the monotonic ``assigned_at`` guard - are asserted
    against real PostgreSQL in
    tests/integration/test_observability_consumer_round_trip.py.
    """
    registry = HandlerRegistry()
    register_intake_handlers(registry)
    register_obs_handlers(registry)
    handler = registry.handlers_for(EVENT_INTAKE_DOCTOR_ASSIGNED)[0]

    engine = MagicMock()
    engine.begin.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
    engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)
    engine.dispose = AsyncMock()
    monkeypatch.setattr("bus.handler_harness._delivery_engine", lambda: engine)

    delivered: set[str] = set()
    edge = AsyncMock()

    async def fake_ledger(
        conn: object, schema: str, envelope: Envelope[BaseModel], handler_result: object
    ) -> bool:
        del conn, schema, handler_result
        if str(envelope.event_id) in delivered:
            return False
        delivered.add(str(envelope.event_id))
        return True

    monkeypatch.setattr("bus.handler_harness.record_consumed_event", fake_ledger)
    monkeypatch.setattr("modules.observability.adapters.record_care_attribution_edge", edge)

    first = intake_doctor_assigned_envelope(intake_id=42, patient_id=7, doctor_id=8)
    # A genuinely NEW event about the same intake - a re-pick, not a redelivery.
    # It must reach the effect: "exactly one doctor" is the schema's job to
    # enforce, not a reason to drop an event on the floor.
    repick = intake_doctor_assigned_envelope(intake_id=42, patient_id=7, doctor_id=9)

    await handler(first)
    assert edge.await_count == 1
    mirror = edge.await_args.args[2]
    assert isinstance(mirror, IntakeDoctorAssignedTelemetryPayload)
    assert mirror.intake_id == 42
    assert mirror.doctor_id == 8

    await handler(first)
    assert edge.await_count == 1

    await handler(repick)
    assert edge.await_count == 2
    assert edge.await_args.args[2].doctor_id == 9


# ------------------------------------------- B9 #728: what may be STORED as a reason


def test_a_operational_token_passes_the_sanitiser_unchanged() -> None:
    """The shape the producer actually emits must survive verbatim."""
    assert sanitize_failure_reason("rate_limited") == "rate_limited"
    assert sanitize_failure_reason("Ext002CallError") == "Ext002CallError"


def test_control_characters_and_newlines_are_stripped_rather_than_stored() -> None:
    """A stored reason must be one line, whatever a producer puts in the event.

    A newline would forge a second line in every log the value was ever copied
    into, and a control character corrupts a CSV export and a terminal alike.
    """
    assert sanitize_failure_reason("Ext002CallError\rinjected: row two") == "Ext002CallError"
    assert sanitize_failure_reason("a\x00b\x07c") == "a b c"
    # U+2028 is not a C0 control but is a line separator to several readers.
    assert sanitize_failure_reason("before\u2028after") == "before"


def test_only_the_status_line_of_an_echoed_body_survives() -> None:
    """A provider body echoes the request on the lines AFTER its status line.

    Dropping the continuation is what keeps the guarantee honest if a producer
    ever passes a body through instead of a closed token: the status line names
    the failure, the lines after it can carry what was sent to the provider.
    """
    echoed = (
        "Ext002CallError: provider said 429\n"
        "request echoed: patient complains of fever and cough since three days"
    )

    assert sanitize_failure_reason(echoed) == "Ext002CallError: provider said 429"


def test_a_runaway_reason_is_capped_and_marked_as_cut() -> None:
    """The column is read on a board; a provider body must not become a wall of text."""
    reason = "x" * (MAX_FAILURE_REASON_CHARS * 2)

    stored = sanitize_failure_reason(reason)

    assert stored is not None
    assert len(stored) == MAX_FAILURE_REASON_CHARS
    assert stored.endswith("...")
    assert stored.startswith("x")


def test_a_reason_at_the_cap_is_left_alone() -> None:
    """The cap is a ceiling, not a target: a reason that fits is never cut."""
    reason = "y" * MAX_FAILURE_REASON_CHARS

    assert sanitize_failure_reason(reason) == reason


def test_nothing_to_say_is_a_null_rather_than_a_blank_column() -> None:
    """A column holding "   " would read as a named failure that says nothing."""
    assert sanitize_failure_reason(None) is None
    assert sanitize_failure_reason("") is None
    assert sanitize_failure_reason("   ") is None
    assert sanitize_failure_reason("\r\n\t") is None


def test_whitespace_runs_collapse_so_the_stored_length_means_something() -> None:
    assert sanitize_failure_reason("Ext002CallError \t  failed") == "Ext002CallError failed"
