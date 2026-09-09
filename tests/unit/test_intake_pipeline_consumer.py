"""PHASE-7 T10: intake.captured AI pipeline consumer happy path + idempotency (#354).

Drives the ``intake.captured`` self-subscription through the shared delivery
harness with a fake engine/connection and the real mock provider, mirroring the
notify terminal-status consumer suite (``test_notify_partner_terminal_consumer.py``).
Pins the ledger-first pipeline contract:

- Ledger-first ordering: ``record_consumed_event`` runs first; replaying an
  already-recorded ``event_id`` skips the pipeline entirely (exactly one
  pre-summary per captured event, ADR-0002 §3).
- Happy path produces a Draft pre_summary with the provider confidence and
  honesty (``low_confidence``) fields.
- The ``intake_ai_jobs`` row records provider, model, tokens, cost, latency,
  status and attempt count.
- ``pre_summary.ready`` and ``ai_job.completed`` are published on success.
- The handler path never raises a user-visible error to the patient - a
  missing intake degrades to a logged skip.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from pydantic import BaseModel
from sqlalchemy.sql.dml import Insert, Update
from sqlalchemy.sql.selectable import Select

from bus.envelope import Envelope
from bus.events import (
    EVENT_AI_JOB_COMPLETED,
    EVENT_INTAKE_CAPTURED,
    EVENT_INTAKE_RETRY_REQUESTED,
    EVENT_PRE_SUMMARY_READY,
)
from modules.intake.adapters import register_handlers
from modules.intake.adapters.ai_provider_mock import MOCK_CONFIDENCE_CLEAN, MockAiProvider
from modules.intake.domain.events import IntakeCapturedPayload

_PROVIDER = "mock"
_MODEL = "mock-model"


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
    """Records every executed statement and scripts scalar returns.

    Selects answer a row; the ai_jobs and pre_summaries inserts answer a new id
    via ``returning``; the intake_outbox insert records the published event.
    Every statement is tagged by kind in ``self.executed``.
    """

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


def _voice_intake_row(*, intake_id: int = 1) -> SimpleNamespace:
    return SimpleNamespace(
        id=intake_id,
        patient_id=42,
        mode="voice",
        language="hi",
        status="captured",
        record_attempts=1,
        text=None,
        transcript=None,
        transcript_usability=None,
        forced_text=False,
    )


def _media_row(*, object_key: str = "intake/abc-123") -> SimpleNamespace:
    return SimpleNamespace(
        id=11,
        intake_id=1,
        media_type="audio",
        object_key=object_key,
        audio_duration_ms=90_000,
        file_size_bytes=1_024_000,
        record_attempt=1,
    )


def _captured_envelope(intake_id: int = 1) -> Envelope[IntakeCapturedPayload]:
    return Envelope[IntakeCapturedPayload](
        event_id=uuid4(),
        event_type=EVENT_INTAKE_CAPTURED,
        producer="intake",
        payload=IntakeCapturedPayload(intake_id=intake_id),
    )


def _consent_decision(*, allowed: bool = True) -> SimpleNamespace:
    return SimpleNamespace(allowed=allowed, consent_id=3, version=1)


def _fake_egress_gate(
    *,
    allows_ai_call: bool = True,
    consent_allowed: bool = True,
) -> tuple[MagicMock, MagicMock, MagicMock]:
    """A fake consent gate + budget meter standing in for ``_build_egress_gate``.

    ``dispose`` is an AsyncMock so the pipeline's ``finally`` can await it; the
    budget meter and consent facade expose exactly the surfaces the pipeline
    calls - ``allows_ai_call``, ``check_consent``, ``record_egress_disclosure``.
    """
    gate_engine = MagicMock()
    gate_engine.dispose = AsyncMock()
    budget_meter = MagicMock()
    budget_meter.allows_ai_call = AsyncMock(return_value=allows_ai_call)
    consent = MagicMock()
    consent.check_consent = AsyncMock(return_value=_consent_decision(allowed=consent_allowed))
    consent.record_egress_disclosure = AsyncMock()
    return gate_engine, consent, budget_meter


async def _run(handler: object, envelope: Envelope[BaseModel], engine: MagicMock) -> None:
    with (
        patch("bus.handler_harness._delivery_engine", return_value=engine),
        patch(
            "bus.handler_harness.record_consumed_event",
            new_callable=AsyncMock,
            return_value=True,
        ) as record_patch,
        patch("modules.intake.adapters._build_egress_gate", return_value=_fake_egress_gate()),
    ):
        await handler(envelope)
    assert record_patch.await_count == 1


@pytest.mark.asyncio
async def test_handler_is_registered_for_intake_captured() -> None:
    from bus.registry import HandlerRegistry

    registry = HandlerRegistry()
    register_handlers(registry)
    assert len(registry.handlers_for(EVENT_INTAKE_CAPTURED)) == 1  # type: ignore[arg-type]
    assert registry.payload_model_for(EVENT_INTAKE_CAPTURED) is not None


@pytest.mark.asyncio
async def test_happy_path_writes_draft_pre_summary_and_publishes_ready_and_completed() -> None:
    handler = _registered_handler()
    connection = _FakeConnection(intake_row=_text_intake_row())
    engine = _fake_engine(connection)

    await _run(handler, _captured_envelope(), engine)

    kinds = [r.kind for r in connection.executed]
    # ai_job created (running), then updated (completed); pre_summary inserted.
    assert "insert_ai_job" in kinds
    assert "update_ai_job" in kinds
    assert "insert_pre_summary" in kinds

    ai_insert = next(r for r in connection.executed if r.kind == "insert_ai_job")
    assert ai_insert.params["intake_id"] == 1
    assert ai_insert.params["task_type"] == "structure"
    assert ai_insert.params["provider"] == _PROVIDER
    assert ai_insert.params["model"] == _MODEL
    assert ai_insert.params["status"] == "running"
    assert ai_insert.params["attempts"] == 1

    ai_update = next(r for r in connection.executed if r.kind == "update_ai_job")
    assert ai_update.params["status"] == "completed"
    assert float(ai_update.params["confidence"]) == pytest.approx(MOCK_CONFIDENCE_CLEAN)
    assert ai_update.params["input_tokens"] == 0
    assert ai_update.params["output_tokens"] == 0
    assert ai_update.params["cost_paise"] == 0
    assert isinstance(ai_update.params["duration_ms"], int)

    pre_insert = next(r for r in connection.executed if r.kind == "insert_pre_summary")
    assert pre_insert.params["intake_id"] == 1
    assert pre_insert.params["review_state"] == "draft"
    assert float(pre_insert.params["structuring_confidence"]) == pytest.approx(
        MOCK_CONFIDENCE_CLEAN
    )
    assert pre_insert.params["low_confidence"] is False
    assert pre_insert.params["structured_fields"]["chief_complaints"] == ["mock chief complaint"]

    # Both events published on success (publication is ledger-first inside the
    # same transaction as the effects).
    outbox_types = [r.params["event_type"] for r in connection.executed if r.kind == "outbox"]
    assert outbox_types.count(EVENT_PRE_SUMMARY_READY) == 1
    assert outbox_types.count(EVENT_AI_JOB_COMPLETED) == 1

    # Intake moved Captured -> Structuring -> Ready for Review.
    intake_statuses = [r.params["status"] for r in connection.executed if r.kind == "status_update"]
    assert intake_statuses == ["structuring", "ready_for_review"]


@pytest.mark.asyncio
async def test_replay_of_same_event_id_is_a_no_op_no_pipeline_effects() -> None:
    handler = _registered_handler()
    connection = _FakeConnection(intake_row=_text_intake_row())
    engine = _fake_engine(connection)

    with (
        patch("bus.handler_harness._delivery_engine", return_value=engine),
        patch(
            "bus.handler_harness.record_consumed_event",
            new_callable=AsyncMock,
            return_value=False,
        ) as record_consumed,
    ):
        await handler(_captured_envelope())

    record_consumed.assert_awaited_once()
    # No pipeline effects: the ledger returned False (replay) so nothing else ran.
    assert connection.executed == []


@pytest.mark.asyncio
async def test_text_mode_structures_the_text_directly_without_a_transcribe_leg() -> None:
    handler = _registered_handler()
    connection = _FakeConnection(intake_row=_text_intake_row())
    engine = _fake_engine(connection)

    with (
        patch("bus.handler_harness._delivery_engine", return_value=engine),
        patch(
            "bus.handler_harness.record_consumed_event",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch("modules.intake.adapters._build_egress_gate", return_value=_fake_egress_gate()),
        patch.object(
            MockAiProvider,
            "transcribe",
            side_effect=AssertionError("transcribe must not be reached for text mode"),
        ),
    ):
        await handler(_captured_envelope())

    # Text mode never looks up a clip, and never called transcribe.
    assert "select_media" not in [r.kind for r in connection.executed]
    assert "insert_pre_summary" in [r.kind for r in connection.executed]


@pytest.mark.asyncio
async def test_voice_mode_runs_transcribe_then_structure_and_records_transcript() -> None:
    handler = _registered_handler()
    connection = _FakeConnection(intake_row=_voice_intake_row(), media_row=_media_row())
    engine = _fake_engine(connection)

    await _run(handler, _captured_envelope(intake_id=1), engine)

    kinds = [r.kind for r in connection.executed]
    assert "select_media" in kinds
    transcript_updates = [r.params for r in connection.executed if r.kind == "transcript_update"]
    assert any(
        p.get("transcript") == "mock transcript" and p.get("transcript_usability") == "partial"
        for p in transcript_updates
    )
    # The structure leg still produced the pre-summary + events.
    assert "insert_pre_summary" in kinds
    outbox_types = [r.params["event_type"] for r in connection.executed if r.kind == "outbox"]
    assert EVENT_PRE_SUMMARY_READY in outbox_types
    assert EVENT_AI_JOB_COMPLETED in outbox_types


@pytest.mark.asyncio
async def test_voice_mode_without_a_media_ref_skips_pipeline() -> None:
    handler = _registered_handler()
    connection = _FakeConnection(intake_row=_voice_intake_row(), media_row=None)
    engine = _fake_engine(connection)

    await _run(handler, _captured_envelope(intake_id=1), engine)

    # Voice with no clip: lookup + media select only, then a logged skip - no
    # job, no pre-summary, no event, and no error raised to the patient.
    kinds = [r.kind for r in connection.executed]
    assert "select_media" in kinds
    assert "insert_ai_job" not in kinds
    assert "insert_pre_summary" not in kinds
    assert "outbox" not in kinds


@pytest.mark.asyncio
async def test_voice_unusable_below_cap_emits_retry_requested_and_returns() -> None:
    handler = _registered_handler()
    connection = _FakeConnection(intake_row=_voice_intake_row(), media_row=_media_row())
    engine = _fake_engine(connection)

    with (
        patch("bus.handler_harness._delivery_engine", return_value=engine),
        patch(
            "bus.handler_harness.record_consumed_event",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch("modules.intake.adapters._build_egress_gate", return_value=_fake_egress_gate()),
        patch.object(
            MockAiProvider,
            "transcribe",
            new_callable=AsyncMock,
            return_value=SimpleNamespace(transcript="", confidence=0.0, language="hi"),
        ),
    ):
        await handler(_captured_envelope(intake_id=1))

    kinds = [r.kind for r in connection.executed]
    # Re-record: status update to re_record + retry event
    assert any(
        r.kind == "transcript_update" and r.params.get("status") == "re_record"
        for r in connection.executed
    )
    outbox_types = [r.params["event_type"] for r in connection.executed if r.kind == "outbox"]
    assert EVENT_INTAKE_RETRY_REQUESTED in outbox_types
    # No structure / pre-summary produced (pipeline returned early)
    assert "insert_ai_job" not in kinds
    assert "insert_pre_summary" not in kinds


@pytest.mark.asyncio
async def test_voice_unusable_at_cap_forced_text_returns() -> None:
    handler = _registered_handler()
    row = _voice_intake_row()
    row.record_attempts = 3
    connection = _FakeConnection(intake_row=row, media_row=_media_row())
    engine = _fake_engine(connection)

    with (
        patch("bus.handler_harness._delivery_engine", return_value=engine),
        patch(
            "bus.handler_harness.record_consumed_event",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch("modules.intake.adapters._build_egress_gate", return_value=_fake_egress_gate()),
        patch.object(
            MockAiProvider,
            "transcribe",
            new_callable=AsyncMock,
            return_value=SimpleNamespace(transcript="ab", confidence=0.0, language="hi"),
        ),
    ):
        await handler(_captured_envelope(intake_id=1))

    kinds = [r.kind for r in connection.executed]
    # At cap: transitions to ready_for_review with forced_text=True
    intake_updates = [r for r in connection.executed if r.kind == "transcript_update"]
    assert any(
        r.params.get("status") == "ready_for_review" and r.params.get("forced_text") is True
        for r in intake_updates
    )
    # No ai_job or pre_summary created (pipeline returned early)
    assert "insert_ai_job" not in kinds
    assert "insert_pre_summary" not in kinds


@pytest.mark.asyncio
async def test_voice_partial_proceeds_to_structuring_with_warning() -> None:
    handler = _registered_handler()
    connection = _FakeConnection(intake_row=_voice_intake_row(), media_row=_media_row())
    engine = _fake_engine(connection)

    with (
        patch("bus.handler_harness._delivery_engine", return_value=engine),
        patch(
            "bus.handler_harness.record_consumed_event",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch("modules.intake.adapters._build_egress_gate", return_value=_fake_egress_gate()),
        patch.object(
            MockAiProvider,
            "transcribe",
            new_callable=AsyncMock,
            return_value=SimpleNamespace(transcript="short", confidence=0.5, language="hi"),
        ),
    ):
        await handler(_captured_envelope(intake_id=1))

    kinds = [r.kind for r in connection.executed]
    # Partial proceeds to structuring: ai_job + pre_summary created
    assert "insert_ai_job" in kinds
    assert "insert_pre_summary" in kinds
    transcript_updates = [r for r in connection.executed if r.kind == "transcript_update"]
    assert any(r.params.get("transcript_usability") == "partial" for r in transcript_updates)


@pytest.mark.asyncio
async def test_voice_usable_proceeds_to_structuring_normally() -> None:
    handler = _registered_handler()
    connection = _FakeConnection(intake_row=_voice_intake_row(), media_row=_media_row())
    engine = _fake_engine(connection)

    with (
        patch("bus.handler_harness._delivery_engine", return_value=engine),
        patch(
            "bus.handler_harness.record_consumed_event",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch("modules.intake.adapters._build_egress_gate", return_value=_fake_egress_gate()),
        patch.object(
            MockAiProvider,
            "transcribe",
            new_callable=AsyncMock,
            return_value=SimpleNamespace(
                transcript="long enough transcript text here", confidence=0.8, language="hi"
            ),
        ),
    ):
        await handler(_captured_envelope(intake_id=1))

    kinds = [r.kind for r in connection.executed]
    assert "insert_ai_job" in kinds
    assert "insert_pre_summary" in kinds
    transcript_updates = [r for r in connection.executed if r.kind == "transcript_update"]
    assert any(r.params.get("transcript_usability") == "usable" for r in transcript_updates)


@pytest.mark.asyncio
async def test_voice_empty_transcript_treated_as_unusable() -> None:
    handler = _registered_handler()
    connection = _FakeConnection(intake_row=_voice_intake_row(), media_row=_media_row())
    engine = _fake_engine(connection)

    with (
        patch("bus.handler_harness._delivery_engine", return_value=engine),
        patch(
            "bus.handler_harness.record_consumed_event",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch("modules.intake.adapters._build_egress_gate", return_value=_fake_egress_gate()),
        patch.object(
            MockAiProvider,
            "transcribe",
            new_callable=AsyncMock,
            return_value=SimpleNamespace(transcript="   ", confidence=0.0, language="hi"),
        ),
    ):
        await handler(_captured_envelope(intake_id=1))

    kinds = [r.kind for r in connection.executed]
    # Whitespace-only transcript is unusable -> re_record
    assert any(
        r.kind == "transcript_update" and r.params.get("status") == "re_record"
        for r in connection.executed
    )
    outbox_types = [r.params["event_type"] for r in connection.executed if r.kind == "outbox"]
    assert EVENT_INTAKE_RETRY_REQUESTED in outbox_types
    assert "insert_ai_job" not in kinds


@pytest.mark.asyncio
async def test_missing_intake_degrades_to_a_logged_skip_not_an_error() -> None:
    handler = _registered_handler()
    connection = _FakeConnection(intake_row=None)
    engine = _fake_engine(connection)

    await _run(handler, _captured_envelope(intake_id=404), engine)

    # Only the lookup happened; no pipeline effects on a missing intake, and
    # it must never raise to the patient.
    assert [r.kind for r in connection.executed] == ["select_intake"]


@pytest.mark.asyncio
async def test_non_captured_intake_skips_pipeline() -> None:
    handler = _registered_handler()
    connection = _FakeConnection(intake_row=_text_intake_row(status="ready_for_review"))
    engine = _fake_engine(connection)

    await _run(handler, _captured_envelope(), engine)

    # Only the lookup happened - a non-captured intake is skipped, not re-run.
    assert [r.kind for r in connection.executed] == ["select_intake"]
