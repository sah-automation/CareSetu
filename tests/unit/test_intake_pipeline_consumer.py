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

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from pydantic import BaseModel
from sqlalchemy.sql.dml import Insert, Update
from sqlalchemy.sql.selectable import Select

from bus.envelope import Envelope
from bus.events import (
    EVENT_AI_EGRESS_RECORDED,
    EVENT_AI_JOB_COMPLETED,
    EVENT_INTAKE_CAPTURED,
    EVENT_INTAKE_RETRY_REQUESTED,
    EVENT_PRE_SUMMARY_READY,
)
from modules.intake.adapters import register_handlers
from modules.intake.adapters.ai_gateway import StructureResult, TranscribeResult
from modules.intake.adapters.ai_provider_mock import MOCK_CONFIDENCE_CLEAN, MockAiProvider
from modules.intake.domain.events import IntakeCapturedPayload, IntakeRetryRequestedPayload
from modules.intake.pricing import ModelPrice

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
                job_id = self._ai_job_id
                self._ai_job_id += 1
                return _FakeResult(scalar=job_id)
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


class _FakeMediaStore:
    """A stub intake media store: ``read`` answers the clip's decrypted bytes."""

    def __init__(self, clip_bytes: bytes = b"fake-voice-clip-bytes") -> None:
        self.read = AsyncMock(return_value=clip_bytes)
        self.close = AsyncMock()


def _media_store_patch() -> patch:
    """Patch the pipeline's per-run media-store seam with the stub (ticket #393)."""
    return patch("modules.intake.adapters._build_media_store", return_value=_FakeMediaStore())


def _registered_handler(event_type: str = EVENT_INTAKE_CAPTURED) -> object:
    from bus.registry import HandlerRegistry

    registry = HandlerRegistry()
    register_handlers(registry)
    handlers = registry.handlers_for(event_type)
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


def _voice_intake_row(
    *, intake_id: int = 1, status: str = "captured", record_attempts: int = 1
) -> SimpleNamespace:
    return SimpleNamespace(
        id=intake_id,
        patient_id=42,
        mode="voice",
        language="hi",
        status=status,
        record_attempts=record_attempts,
        text=None,
        transcript=None,
        transcript_usability=None,
        forced_text=False,
    )


def _media_row(*, object_key: str = "intake/abc-123", record_attempt: int = 1) -> SimpleNamespace:
    return SimpleNamespace(
        id=11,
        intake_id=1,
        media_type="audio",
        object_key=object_key,
        audio_duration_ms=90_000,
        file_size_bytes=1_024_000,
        record_attempt=record_attempt,
    )


def _captured_envelope(intake_id: int = 1) -> Envelope[IntakeCapturedPayload]:
    return Envelope[IntakeCapturedPayload](
        event_id=uuid4(),
        event_type=EVENT_INTAKE_CAPTURED,
        producer="intake",
        payload=IntakeCapturedPayload(
            intake_id=intake_id,
            patient_id=42,
            mode="voice",
            duration_s=90.0,
        ),
    )


def _retry_envelope(
    intake_id: int = 1, record_attempt: int = 2
) -> Envelope[IntakeRetryRequestedPayload]:
    """A facade-emitted re-record trigger (``patient_re_record``) for intake 1."""
    return Envelope[IntakeRetryRequestedPayload](
        event_id=uuid4(),
        event_type=EVENT_INTAKE_RETRY_REQUESTED,
        producer="intake",
        payload=IntakeRetryRequestedPayload(
            intake_id=intake_id,
            record_attempt=record_attempt,
            reason="patient_re_record",
        ),
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
        _media_store_patch(),
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
    # At insert the row carries the configured provider + placeholder model - the
    # effective serving values only land on the completed update (T04 #381).
    assert ai_insert.params["provider"] == _PROVIDER
    assert ai_insert.params["model"] == _MODEL
    assert ai_insert.params["status"] == "running"
    assert ai_insert.params["attempts"] == 1

    ai_update = next(r for r in connection.executed if r.kind == "update_ai_job")
    assert ai_update.params["status"] == "completed"
    # The completed row records the effective (serving) provider/model read off
    # the gateway after the successful call, replacing the placeholder.
    assert ai_update.params["provider"] == _PROVIDER
    assert ai_update.params["model"] == _MODEL
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
async def test_completed_job_carries_real_tokens_and_priced_cost() -> None:
    """A completed structure job row records the real provider/model, the
    provider-reported token usage, and cost priced from them by the per-model
    pricing helper (#399) - never a fabricated constant."""
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
        _media_store_patch(),
        patch.object(
            MockAiProvider,
            "structure",
            new_callable=AsyncMock,
            return_value=StructureResult(
                chief_complaints=["sir dard hai"],
                symptoms=["sir dard"],
                duration="2 din",
                confidence=MOCK_CONFIDENCE_CLEAN,
                input_tokens=900,
                output_tokens=150,
            ),
        ),
        patch(
            "modules.intake.pricing.PRICING_TABLE",
            {
                "mock-model": ModelPrice(
                    price_in_paise=Decimal("0.02"), price_out_paise=Decimal("0.04")
                )
            },
        ),
    ):
        await handler(_captured_envelope(intake_id=1))

    ai_update = next(r for r in connection.executed if r.kind == "update_ai_job")
    assert ai_update.params["status"] == "completed"
    assert ai_update.params["provider"] == _PROVIDER
    assert ai_update.params["model"] == _MODEL
    assert ai_update.params["input_tokens"] == 900
    assert ai_update.params["output_tokens"] == 150
    assert ai_update.params["cost_paise"] == 18 + 6


@pytest.mark.asyncio
async def test_transcribe_success_is_metered_and_audited_as_an_egress() -> None:
    """PS-03: a successful voice transcribe writes a ``transcribe`` ai_jobs row
    with real provider/model/tokens/cost/duration, records the egress disclosure,
    and publishes ``ai_egress.recorded`` - all in the same transaction as the
    ledger dedupe (the structure leg rides along as its own metered row)."""
    handler = _registered_handler()
    connection = _FakeConnection(intake_row=_voice_intake_row(), media_row=_media_row())
    engine = _fake_engine(connection)
    gate_engine, consent, _meter = _fake_egress_gate()

    with (
        patch("bus.handler_harness._delivery_engine", return_value=engine),
        patch(
            "bus.handler_harness.record_consumed_event",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "modules.intake.adapters._build_egress_gate",
            return_value=(gate_engine, consent, _meter),
        ),
        _media_store_patch(),
        patch.object(
            MockAiProvider,
            "transcribe",
            new_callable=AsyncMock,
            return_value=TranscribeResult(
                transcript="long enough transcript text here",
                confidence=0.8,
                language="hi",
                input_tokens=500,
                output_tokens=80,
            ),
        ),
        patch(
            "modules.intake.pricing.PRICING_TABLE",
            {
                "mock-model": ModelPrice(
                    price_in_paise=Decimal("0.02"), price_out_paise=Decimal("0.04")
                )
            },
        ),
    ):
        await handler(_captured_envelope(intake_id=1))

    # The transcribe job was booked pre-call and finalized with the effective
    # serving values + real token usage priced into cost (10 + 3.2 = 13 paise).
    ai_inserts = [r for r in connection.executed if r.kind == "insert_ai_job"]
    assert [r.params["task_type"] for r in ai_inserts] == ["transcribe", "structure"]
    transcribe_completed = next(
        r
        for r in connection.executed
        if r.kind == "update_ai_job" and r.params["status"] == "completed"
    )
    assert transcribe_completed.params["provider"] == "mock"
    assert transcribe_completed.params["model"] == "mock-model"
    assert transcribe_completed.params["input_tokens"] == 500
    assert transcribe_completed.params["output_tokens"] == 80
    assert transcribe_completed.params["cost_paise"] == 13
    assert isinstance(transcribe_completed.params["duration_ms"], int)

    # The clip's departure was disclosed under the checked grant once per leg,
    # and ``ai_egress.recorded`` names the transcribe job (9) + structure (10).
    consent.record_egress_disclosure.assert_awaited()
    outbox = [r.params for r in connection.executed if r.kind == "outbox"]
    egress_events = [p for p in outbox if p["event_type"] == EVENT_AI_EGRESS_RECORDED]
    assert len(egress_events) == 2
    assert {e["payload"]["ai_job_id"] for e in egress_events} == {9, 10}


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
        _media_store_patch(),
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
    # A voice pass is two metered rows (PS-03): a completed transcribe job
    # booked before the call, then the completed structure job.
    ai_inserts = [r for r in connection.executed if r.kind == "insert_ai_job"]
    assert [r.params["task_type"] for r in ai_inserts] == ["transcribe", "structure"]
    completed = [r for r in connection.executed if r.kind == "update_ai_job"]
    assert len(completed) == 2
    assert all(r.params["status"] == "completed" for r in completed)
    # The transcribe job finalized with the effective serving values.
    assert completed[0].params["provider"] == _PROVIDER
    assert completed[0].params["model"] == _MODEL
    assert completed[0].params["input_tokens"] == 0
    assert completed[0].params["output_tokens"] == 0
    assert completed[0].params["cost_paise"] == 0
    assert isinstance(completed[0].params["duration_ms"], int)
    # Both legs' egresses are disclosed and ``ai_egress.recorded`` published.
    outbox_types = [r.params["event_type"] for r in connection.executed if r.kind == "outbox"]
    assert outbox_types.count(EVENT_AI_EGRESS_RECORDED) == 2
    assert outbox_types.count(EVENT_AI_JOB_COMPLETED) == 2
    assert EVENT_PRE_SUMMARY_READY in outbox_types
    # The structure leg still produced the pre-summary.
    assert "insert_pre_summary" in kinds


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
        _media_store_patch(),
        patch.object(
            MockAiProvider,
            "transcribe",
            new_callable=AsyncMock,
            return_value=SimpleNamespace(
                transcript="", confidence=0.0, language="hi", input_tokens=0, output_tokens=0
            ),
        ),
    ):
        await handler(_captured_envelope(intake_id=1))

    kinds = [r.kind for r in connection.executed]
    # The successful transcribe is still metered + disclosed (PS-03): one
    # completed transcribe job row and its ``ai_egress.recorded`` event ride
    # the same transaction before the unusable branch.
    ai_inserts = [r for r in connection.executed if r.kind == "insert_ai_job"]
    assert [r.params["task_type"] for r in ai_inserts] == ["transcribe"]
    completed = next(r for r in connection.executed if r.kind == "update_ai_job")
    assert completed.params["status"] == "completed"
    outbox_types = [r.params["event_type"] for r in connection.executed if r.kind == "outbox"]
    assert EVENT_AI_EGRESS_RECORDED in outbox_types
    assert EVENT_AI_JOB_COMPLETED in outbox_types
    # Re-record: status update to re_record + retry event
    assert any(
        r.kind == "transcript_update" and r.params.get("status") == "re_record"
        for r in connection.executed
    )
    assert EVENT_INTAKE_RETRY_REQUESTED in outbox_types
    # No structure / pre-summary produced (pipeline returned early)
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
        _media_store_patch(),
        patch.object(
            MockAiProvider,
            "transcribe",
            new_callable=AsyncMock,
            return_value=SimpleNamespace(
                transcript="ab", confidence=0.0, language="hi", input_tokens=0, output_tokens=0
            ),
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
    # The transcribe leg is still metered (one completed row); the structure
    # leg and pre_summary never ran (pipeline returned early at the cap).
    ai_inserts = [r for r in connection.executed if r.kind == "insert_ai_job"]
    assert [r.params["task_type"] for r in ai_inserts] == ["transcribe"]
    completed = next(r for r in connection.executed if r.kind == "update_ai_job")
    assert completed.params["status"] == "completed"
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
        _media_store_patch(),
        patch.object(
            MockAiProvider,
            "transcribe",
            new_callable=AsyncMock,
            return_value=SimpleNamespace(
                transcript="short",
                confidence=0.5,
                language="hi",
                input_tokens=0,
                output_tokens=0,
            ),
        ),
    ):
        await handler(_captured_envelope(intake_id=1))

    kinds = [r.kind for r in connection.executed]
    # Partial proceeds to structuring: both legs book metered rows + pre_summary
    ai_inserts = [r for r in connection.executed if r.kind == "insert_ai_job"]
    assert [r.params["task_type"] for r in ai_inserts] == ["transcribe", "structure"]
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
        _media_store_patch(),
        patch.object(
            MockAiProvider,
            "transcribe",
            new_callable=AsyncMock,
            return_value=SimpleNamespace(
                transcript="long enough transcript text here",
                confidence=0.8,
                language="hi",
                input_tokens=0,
                output_tokens=0,
            ),
        ),
    ):
        await handler(_captured_envelope(intake_id=1))

    kinds = [r.kind for r in connection.executed]
    ai_inserts = [r for r in connection.executed if r.kind == "insert_ai_job"]
    assert [r.params["task_type"] for r in ai_inserts] == ["transcribe", "structure"]
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
        _media_store_patch(),
        patch.object(
            MockAiProvider,
            "transcribe",
            new_callable=AsyncMock,
            return_value=SimpleNamespace(
                transcript="   ", confidence=0.0, language="hi", input_tokens=0, output_tokens=0
            ),
        ),
    ):
        await handler(_captured_envelope(intake_id=1))

    # Whitespace-only transcript is unusable -> re_record (the successful
    # transcribe leg is still metered as one completed row, PS-03).
    assert any(
        r.kind == "transcript_update" and r.params.get("status") == "re_record"
        for r in connection.executed
    )
    outbox_types = [r.params["event_type"] for r in connection.executed if r.kind == "outbox"]
    assert EVENT_INTAKE_RETRY_REQUESTED in outbox_types
    ai_inserts = [r for r in connection.executed if r.kind == "insert_ai_job"]
    assert [r.params["task_type"] for r in ai_inserts] == ["transcribe"]


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


# ---------------------------------------------------------------------------
# intake.retry_requested - the re-record pipeline re-trigger (PS-07)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retry_requested_reruns_pipeline_from_structuring_with_new_presummary() -> None:
    """PS-07: a re-recorded intake never stalls in ``structuring``. The
    ``intake.retry_requested`` handler re-runs the structuring pipeline on the
    fresh (attempt-2) clip; the run resumes from ``structuring`` - no
    re-transition - and ties the completed job + new Draft pre-summary to the
    incremented attempt count, ending Ready for Review."""
    handler = _registered_handler(EVENT_INTAKE_RETRY_REQUESTED)
    connection = _FakeConnection(
        intake_row=_voice_intake_row(status="structuring", record_attempts=2),
        media_row=_media_row(object_key="intake/7/clip-2.enc", record_attempt=2),
    )
    engine = _fake_engine(connection)
    media_store = _FakeMediaStore(clip_bytes=b"decrypted-clip-bytes")
    transcribe = AsyncMock(
        return_value=SimpleNamespace(
            transcript="long enough transcript text here",
            confidence=0.8,
            language="hi",
            input_tokens=0,
            output_tokens=0,
        )
    )

    with (
        patch("bus.handler_harness._delivery_engine", return_value=engine),
        patch(
            "bus.handler_harness.record_consumed_event",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch("modules.intake.adapters._build_egress_gate", return_value=_fake_egress_gate()),
        patch("modules.intake.adapters._build_media_store", return_value=media_store),
        patch.object(MockAiProvider, "transcribe", transcribe),
    ):
        await handler(_retry_envelope())

    # The run consumed the NEW clip: the intent-2 media ref (latest by record
    # attempt) is the one read and placed on the transcribe request.
    assert media_store.read.await_args.kwargs["object_key"] == "intake/7/clip-2.enc"
    request = transcribe.await_args.args[0]
    assert request.audio_ref == "intake/7/clip-2.enc"

    kinds = [r.kind for r in connection.executed]
    # Transcribe + structure ran as on a first take, and a NEW pre-summary was
    # produced (never a stall in structuring).
    ai_inserts = [r for r in connection.executed if r.kind == "insert_ai_job"]
    assert [r.params["task_type"] for r in ai_inserts] == ["transcribe", "structure"]
    assert "insert_pre_summary" in kinds
    outbox_types = [r.params["event_type"] for r in connection.executed if r.kind == "outbox"]
    assert EVENT_PRE_SUMMARY_READY in outbox_types
    assert outbox_types.count(EVENT_AI_JOB_COMPLETED) == 2
    assert outbox_types.count(EVENT_AI_EGRESS_RECORDED) == 2

    # Resumed from structuring: the only intake status write is the final
    # ready_for_review (the facade already transitioned Re-record -> Structuring
    # with the attempt incremented - never a START_STRUCTURING re-transition).
    assert [r.params["status"] for r in connection.executed if r.kind == "status_update"] == [
        "ready_for_review"
    ]


@pytest.mark.asyncio
async def test_retry_requested_on_intake_still_in_re_record_skips() -> None:
    """The pipeline's own ``unusable_audio`` retry fires while the intake is
    still ``re_record`` (no fresh clip yet); the re-trigger entry only accepts
    ``structuring``, so that earlier event is a strict skip - the actual re-run
    waits for the facade's ``patient_re_record`` event."""
    handler = _registered_handler(EVENT_INTAKE_RETRY_REQUESTED)
    connection = _FakeConnection(intake_row=_voice_intake_row(status="re_record"))
    engine = _fake_engine(connection)

    await _run(handler, _retry_envelope(), engine)

    # Only the lookup happened - nothing re-ran against a re_record intake.
    assert [r.kind for r in connection.executed] == ["select_intake"]


@pytest.mark.asyncio
async def test_replayed_captured_on_in_flight_structuring_intake_skips() -> None:
    """PS-07: the captured-path guard stays strict. When an ``intake.captured``
    event arrives for an intake already in ``structuring`` (e.g. a post-re-record
    captured event, or any out-of-order delivery), the pipeline skips - only the
    ``intake.retry_requested`` entry may resume it. Pins the pipeline-level guard
    independently of ledger dedupe."""
    handler = _registered_handler()
    connection = _FakeConnection(
        intake_row=_voice_intake_row(status="structuring", record_attempts=2)
    )
    engine = _fake_engine(connection)

    await _run(handler, _captured_envelope(), engine)

    # Only the lookup happened - the structuring intake is not re-structured.
    assert [r.kind for r in connection.executed] == ["select_intake"]


@pytest.mark.asyncio
async def test_retry_requested_replay_of_same_event_id_is_a_no_op() -> None:
    """Coding-standards §6: every outbox consumer has an idempotency test. A
    replayed ``intake.retry_requested`` event_id finds its ledger row and is a
    no-op - the pipeline never re-runs for the same retry delivery."""
    handler = _registered_handler(EVENT_INTAKE_RETRY_REQUESTED)
    connection = _FakeConnection(
        intake_row=_voice_intake_row(status="structuring", record_attempts=2),
        media_row=_media_row(object_key="intake/7/clip-2.enc", record_attempt=2),
    )
    engine = _fake_engine(connection)

    with (
        patch("bus.handler_harness._delivery_engine", return_value=engine),
        patch(
            "bus.handler_harness.record_consumed_event",
            new_callable=AsyncMock,
            return_value=False,
        ) as record_consumed,
    ):
        await handler(_retry_envelope())

    record_consumed.assert_awaited_once()
    # Ledger returned False (replay) so nothing else ran - no re-run effects.
    assert connection.executed == []
