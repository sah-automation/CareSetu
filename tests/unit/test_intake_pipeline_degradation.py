"""PHASE-7 T11: AI pipeline degradation paths (#355).

Drives the ``intake.captured`` self-subscription through the shared delivery
harness (same fake engine/connection + mock provider setup as the T10 happy-path
suite) and pins the degradation contract (spec #344 MOD-005):

- Timeout-after-3-retries and malformed provider output mark ``ai_job.failed``,
  leave the intake durable, and publish ``ai_job.failed``.
- NFR-001 budget exhaustion hard-stops new AI calls and degrades the intake to
  raw doctor review (no egress, no job, no pre-summary).
- A missing or revoked consent blocks egress fail-closed (no PHI sent) and
  degrades to raw review.
- Successful egress is PHI-minimized (intake context only, never name/phone/full
  record) and audited via ``record_egress_disclosure``.
- A low-confidence structuring outcome flags the pre-summary, publishes
  ``pre_summary.low_confidence``, and the pre-summary requires doctor review.
"""

from __future__ import annotations

from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from pydantic import BaseModel, ValidationError
from sqlalchemy.sql.dml import Insert, Update
from sqlalchemy.sql.selectable import Select

from bus.envelope import Envelope
from bus.events import (
    EVENT_AI_EGRESS_RECORDED,
    EVENT_AI_JOB_COMPLETED,
    EVENT_AI_JOB_FAILED,
    EVENT_INTAKE_CAPTURED,
    EVENT_PRE_SUMMARY_LOW_CONFIDENCE,
    EVENT_PRE_SUMMARY_READY,
)
from modules.intake.adapters.ai_provider_ext import Ext002CallError
from modules.intake.adapters.ai_provider_mock import (
    MOCK_AI_MODEL,
    MOCK_AI_PROVIDER,
    MOCK_CONFIDENCE_LOW,
    MockAiProvider,
)
from modules.intake.adapters.ai_provider_mock import (
    build_mock_ai_gateway as build_low_confidence_gateway,
)
from modules.intake.domain.events import IntakeCapturedPayload

_EGRESS_COUNTERPARTY_TYPE = "doctor"
_EGRESS_COUNTERPARTY_ID = "intake-ai"
_EGRESS_SCOPE = "consultations"


class _FakeResult:
    def __init__(self, scalar: object | None = None, row: object | None = None) -> None:
        self._scalar = scalar
        self._row = row

    def scalar_one(self) -> object:
        return self._scalar

    def first(self) -> object:
        return self._row

    def all(self) -> list:
        return []


class _Recorded:
    def __init__(self, kind: str, statement: object) -> None:
        self.kind = kind
        self.statement = statement
        self.params = dict(statement.compile().params)
        self.table = getattr(getattr(statement, "table", None), "name", None)


def _statement_table(statement: object) -> str | None:
    if isinstance(statement, Insert):
        return getattr(statement.table, "name", None)
    if isinstance(statement, Update):
        return getattr(statement.table, "name", None)
    if isinstance(statement, Select):
        froms = statement.get_final_froms()
        return getattr(froms[0], "name", None) if froms else None
    return None


class _FakeConnection:
    """Records executed statements; scripts the ai_jobs / pre_summary inserts."""

    def __init__(
        self,
        *,
        intake_row: object | None,
        media_row: object | None = None,
        ai_job_id: int = 9,
        pre_summary_id: int = 5,
    ) -> None:
        self._intake_row = intake_row
        self._media_row = media_row
        self._ai_job_id = ai_job_id
        self._pre_summary_id = pre_summary_id
        self.executed: list[_Recorded] = []

    async def execute(self, statement: object) -> _FakeResult:
        table = _statement_table(statement)
        if isinstance(statement, Insert):
            if table == "intake_ai_jobs" and getattr(statement, "_returning", None):
                self.executed.append(_Recorded("insert_ai_job", statement))
                return _FakeResult(scalar=self._ai_job_id)
            if table == "intake_pre_summaries" and getattr(statement, "_returning", None):
                self.executed.append(_Recorded("insert_pre_summary", statement))
                return _FakeResult(scalar=self._pre_summary_id)
            if table == "intake_ai_jobs":
                self.executed.append(_Recorded("update_ai_job", statement))
                return _FakeResult()
            if table == "intake_outbox":
                self.executed.append(_Recorded("outbox", statement))
                return _FakeResult()
            self.executed.append(_Recorded("insert_other", statement))
            return _FakeResult()
        if isinstance(statement, Update):
            if table == "intake_ai_jobs":
                self.executed.append(_Recorded("update_ai_job", statement))
            elif table == "intake_intakes":
                kind = (
                    "transcript_update"
                    if "transcript" in statement.compile().params
                    else "status_update"
                )
                self.executed.append(_Recorded(kind, statement))
            else:
                self.executed.append(_Recorded("update_other", statement))
            return _FakeResult()
        if table == "intake_intakes":
            self.executed.append(_Recorded("select_intake", statement))
            return _FakeResult(row=self._intake_row)
        if table == "intake_media_refs":
            self.executed.append(_Recorded("select_media", statement))
            return _FakeResult(row=self._media_row)
        self.executed.append(_Recorded("other", statement))
        return _FakeResult()


def _fake_engine(connection: _FakeConnection) -> MagicMock:
    engine = MagicMock()
    engine.begin.return_value.__aenter__ = AsyncMock(return_value=connection)
    engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)
    engine.dispose = AsyncMock()
    return engine


def _registered_handler() -> object:
    from bus.registry import HandlerRegistry
    from modules.intake.adapters import register_handlers

    registry = HandlerRegistry()
    register_handlers(registry)
    handlers = registry.handlers_for(EVENT_INTAKE_CAPTURED)
    assert len(handlers) == 1
    return handlers[0]


def _text_intake_row(*, intake_id: int = 1, status: str = "captured") -> SimpleNamespace:
    return SimpleNamespace(
        id=intake_id,
        patient_id=42,
        mode="text",
        language="hi",
        status=status,
        record_attempts=1,
        text="sir dard hai",
        transcript=None,
        transcript_usability=None,
        forced_text=False,
    )


def _captured_envelope(intake_id: int = 1) -> Envelope[IntakeCapturedPayload]:
    return Envelope[IntakeCapturedPayload](
        event_id=uuid4(),
        event_type=EVENT_INTAKE_CAPTURED,
        producer="intake",
        payload=IntakeCapturedPayload(
            intake_id=intake_id,
            patient_id=42,
            mode="text",
            duration_s=None,
        ),
    )


def _consent_decision(*, allowed: bool = True) -> SimpleNamespace:
    return SimpleNamespace(allowed=allowed, consent_id=3, version=1)


def _fake_egress_gate(
    *,
    allows_ai_call: bool = True,
    consent_allowed: bool = True,
) -> tuple[MagicMock, MagicMock, MagicMock]:
    gate_engine = MagicMock()
    gate_engine.dispose = AsyncMock()
    budget_meter = MagicMock()
    budget_meter.allows_ai_call = AsyncMock(return_value=allows_ai_call)
    consent = MagicMock()
    consent.check_consent = AsyncMock(return_value=_consent_decision(allowed=consent_allowed))
    consent.record_egress_disclosure = AsyncMock()
    return gate_engine, consent, budget_meter


async def _run(
    handler: object,
    envelope: Envelope[BaseModel],
    engine: MagicMock,
    *,
    allows_ai_call: bool = True,
    consent_allowed: bool = True,
    gateway_builder: object | None = None,
) -> tuple[MagicMock, MagicMock, MagicMock]:
    gate = _fake_egress_gate(
        allows_ai_call=allows_ai_call,
        consent_allowed=consent_allowed,
    )
    patches: list[object] = [
        patch("bus.handler_harness._delivery_engine", return_value=engine),
        patch(
            "bus.handler_harness.record_consumed_event",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch("modules.intake.adapters._build_egress_gate", return_value=gate),
    ]
    if gateway_builder is not None:
        patches.append(
            patch(
                "modules.intake.adapters.build_ai_gateway",
                return_value=gateway_builder,
            )
        )
    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        await handler(envelope)
    return gate[1], gate[2], gate[0]


def _outbox_types(connection: _FakeConnection) -> list[str]:
    return [r.params["event_type"] for r in connection.executed if r.kind == "outbox"]


def _statuses(connection: _FakeConnection) -> list[str]:
    return [r.params["status"] for r in connection.executed if r.kind == "status_update"]


@pytest.mark.asyncio
async def test_timeout_after_retries_marks_job_failed_and_publishes_failed() -> None:
    """EXT-002 exhaustion (timeout / retries) marks ai_job.failed, publishes
    ``ai_job.failed``, leaves the intake durable in ready_for_review, and never
    raises to the patient."""
    handler = _registered_handler()
    connection = _FakeConnection(intake_row=_text_intake_row())
    engine = _fake_engine(connection)

    with patch.object(
        MockAiProvider,
        "structure",
        side_effect=Ext002CallError("timeout after 3 attempts", retries_exhausted=True),
    ):
        await _run(handler, _captured_envelope(), engine)

    kinds = [r.kind for r in connection.executed]
    assert "insert_ai_job" in kinds
    failed_update = next(r for r in connection.executed if r.kind == "update_ai_job")
    assert failed_update.params["status"] == "failed"
    assert failed_update.params["error_message"] == "Ext002CallError"
    # ai_job.failed published; no pre-summary, no ready/completed events.
    outbox = _outbox_types(connection)
    assert outbox.count(EVENT_AI_JOB_FAILED) == 1
    assert EVENT_PRE_SUMMARY_READY not in outbox
    assert EVENT_AI_JOB_COMPLETED not in outbox
    assert "insert_pre_summary" not in kinds
    # Intake degraded durably to ready_for_review (raw doctor review).
    assert _statuses(connection) == ["structuring", "ready_for_review"]


@pytest.mark.asyncio
async def test_malformed_output_marks_job_failed_and_degrades() -> None:
    """A malformed/validation-error provider output is a failed job, not a silent
    pass-through (standard A2): ai_job.failed + raw review, no pre-summary."""
    handler = _registered_handler()
    connection = _FakeConnection(intake_row=_text_intake_row())
    engine = _fake_engine(connection)

    malformed = ValidationError.from_exception_data("StructureResult", [])
    with patch.object(
        MockAiProvider,
        "structure",
        side_effect=malformed,
    ):
        await _run(handler, _captured_envelope(), engine)

    exploded = [
        next(
            r
            for r in connection.executed
            if r.kind == "outbox" and r.params["event_type"] == EVENT_AI_JOB_FAILED
        ).params
    ][0]
    assert exploded["payload"]["reason"] == "ValidationError"
    failed_update = next(r for r in connection.executed if r.kind == "update_ai_job")
    assert failed_update.params["status"] == "failed"
    assert "insert_pre_summary" not in [r.kind for r in connection.executed]
    assert EVENT_AI_JOB_FAILED in _outbox_types(connection)
    assert _statuses(connection) == ["structuring", "ready_for_review"]


@pytest.mark.asyncio
async def test_budget_exhaustion_hard_stops_new_ai_calls_and_degrades() -> None:
    """An exhausted NFR-001 meter hard-stops the pipeline BEFORE any egress: no
    consent check, no provider call, no job, no pre-summary - only the durable
    raw-review transition."""
    handler = _registered_handler()
    connection = _FakeConnection(intake_row=_text_intake_row())
    engine = _fake_engine(connection)

    consent, meter, gate_engine = await _run(
        handler,
        _captured_envelope(),
        engine,
        allows_ai_call=False,
    )

    meter.allows_ai_call.assert_awaited_once()
    consent.check_consent.assert_not_awaited()
    kinds = [r.kind for r in connection.executed]
    assert "insert_ai_job" not in kinds
    assert "insert_pre_summary" not in kinds
    assert "outbox" not in kinds
    assert _statuses(connection) == ["structuring", "ready_for_review"]
    gate_engine.dispose.assert_awaited_once()


@pytest.mark.asyncio
async def test_revoked_consent_blocks_egress_and_degrades_without_sending_phi() -> None:
    """A revoked/missing consent denies egress fail-closed: the provider is never
    called (no PHI sent), no job/pre-summary/egress exists, and the intake is
    left durable for raw doctor review."""
    handler = _registered_handler()
    connection = _FakeConnection(intake_row=_text_intake_row())
    engine = _fake_engine(connection)

    consent, _meter, _gate_engine = await _run(
        handler,
        _captured_envelope(),
        engine,
        consent_allowed=False,
    )

    consent.check_consent.assert_awaited_once()
    consent.record_egress_disclosure.assert_not_awaited()
    kinds = [r.kind for r in connection.executed]
    assert "insert_ai_job" not in kinds
    assert "insert_pre_summary" not in kinds
    assert "outbox" not in kinds
    assert _statuses(connection) == ["structuring", "ready_for_review"]


@pytest.mark.asyncio
async def test_successful_egress_is_phi_minimized_and_audited_via_record_egress_disclosure() -> (
    None
):
    """On success the intake context egress is audited with the checked consent
    grant (consultations scope, doctor counterparty) and ``ai_egress.recorded``
    is published alongside the pre_summary events."""
    handler = _registered_handler()
    connection = _FakeConnection(intake_row=_text_intake_row())
    engine = _fake_engine(connection)

    consent, _meter, _gate_engine = await _run(handler, _captured_envelope(), engine)

    assert consent.check_consent.await_count == 1
    consent.record_egress_disclosure.assert_awaited_once_with(
        patient_id=42,
        consent_id=3,
        version=1,
        counterparty_type=_EGRESS_COUNTERPARTY_TYPE,
        counterparty_id=_EGRESS_COUNTERPARTY_ID,
        record_scope=_EGRESS_SCOPE,
        disclosed_entry_ids=[1],
    )
    outbox = _outbox_types(connection)
    assert outbox.count(EVENT_AI_EGRESS_RECORDED) == 1
    egress_envelope = next(
        r
        for r in connection.executed
        if r.kind == "outbox" and r.params["event_type"] == EVENT_AI_EGRESS_RECORDED
    )
    assert egress_envelope.params["payload"]["intake_id"] == 1
    assert egress_envelope.params["payload"]["ai_job_id"] == 9


@pytest.mark.asyncio
async def test_phi_minimized_context_is_all_that_reaches_the_provider() -> None:
    """The provider request carries only intake context - never name/phone/full
    record - pinned by what the gateway actually received."""
    handler = _registered_handler()
    connection = _FakeConnection(intake_row=_text_intake_row())
    engine = _fake_engine(connection)

    provider = build_low_confidence_gateway(confidence_level="clean")
    await _run(handler, _captured_envelope(), engine, gateway_builder=provider)

    assert len(provider.calls) == 1
    structure_request = provider.calls[0]
    assert structure_request.transcript == "sir dard hai"
    assert structure_request.source == "text"
    assert structure_request.context.language == "hi"
    assert structure_request.context.age_range == "30-40"
    assert structure_request.context.sex == "other"


@pytest.mark.asyncio
async def test_low_confidence_flags_and_publishes_low_confidence_event() -> None:
    """Below-AMB-006 structuring flags the pre-summary row and ALSO publishes
    ``pre_summary.low_confidence`` (the honesty cue forcing doctor review)."""
    handler = _registered_handler()
    connection = _FakeConnection(intake_row=_text_intake_row())
    engine = _fake_engine(connection)

    provider = build_low_confidence_gateway(confidence_level="low")
    await _run(handler, _captured_envelope(), engine, gateway_builder=provider)

    pre_insert = next(r for r in connection.executed if r.kind == "insert_pre_summary")
    assert pre_insert.params["low_confidence"] is True
    assert float(pre_insert.params["structuring_confidence"]) == pytest.approx(MOCK_CONFIDENCE_LOW)
    completed_update = next(r for r in connection.executed if r.kind == "update_ai_job")
    assert completed_update.params["status"] == "completed"
    assert completed_update.params["provider"] == MOCK_AI_PROVIDER
    assert completed_update.params["model"] == MOCK_AI_MODEL
    outbox = _outbox_types(connection)
    assert outbox.count(EVENT_PRE_SUMMARY_LOW_CONFIDENCE) == 1
    assert outbox.count(EVENT_PRE_SUMMARY_READY) == 1
    assert outbox.count(EVENT_AI_JOB_COMPLETED) == 1
    assert _statuses(connection) == ["structuring", "ready_for_review"]


@pytest.mark.asyncio
async def test_low_confidence_presummary_structurally_requires_doctor_review() -> None:
    """A low-confidence pre-summary can never reach Final unreviewed: the review
    machine refuses finalize from Draft (ADR-0001 forced-doctor-review gate)."""
    from modules.intake.domain.exceptions import IllegalPreSummaryTransitionError
    from modules.intake.domain.presummary_machine import (
        DRAFT,
        PreSummaryAction,
        transition,
    )

    # A Draft pre-summary structurally cannot be Finalized - the machine refuses
    # the edge, so low-confidence output can never reach Final unreviewed.
    with pytest.raises(IllegalPreSummaryTransitionError):
        transition(DRAFT, PreSummaryAction.FINALIZE)
