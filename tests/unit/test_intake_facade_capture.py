"""PHASE-7 T07: IntakeFacade capture seam (ticket #351, spec #344).

Drives the intake capture facade through a mocked engine, mirroring the
partner registration sub-facade direct-seam suite
(``test_partner_facade_register.py``). Pins the capture contract at the
facade-with-fakes seam:

- ``submit_intake`` commits the intake row and the ``intake.captured``
  outbox row in the SAME transaction - the outbox write goes through
  ``write_outbox`` on the same connection as the intake insert (ADR-0002
  S1), so a crash between state change and dispatch cannot lose the
  event (accepted criterion 1).
- One-mode-per-intake and the text cap (2000 chars) are enforced
  server-side with typed errors (accepted criterion 2).
- ``get_intake`` / ``get_pre_summary`` return the agreed DTO shapes:
  status from the state machine, honesty (``low_confidence``) fields
  present (accepted criterion 3).
- ``request_rx_draft`` exists as a declared contract stub (accepted
  criterion 4). Capture durability is structural - the row + outbox event
  commit in one local transaction, so a later AI failure never rolls
  back the intake (accepted criterion 5).
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.sql.dml import Insert

from modules.intake.domain.events import (
    EVENT_INTAKE_CAPTURED,
    IntakeCapturedPayload,
)
from modules.intake.domain.exceptions import (
    IntakeNotFoundError,
    IntakeValidationError,
)
from modules.intake.facade import IntakeFacade
from modules.intake.intake_models import IntakeDetailView, PreSummaryView
from modules.intake.schema.models import (
    intake_intakes,
)

NOW = datetime.now(UTC)


class _FakeResult:
    """Mimics ``Insert``/``Select`` result shapes: ``scalar_one``, ``first``, ``all``."""

    def __init__(
        self,
        scalar: object | None = None,
        row: object | None = None,
        rows: list[object] | None = None,
    ) -> None:
        self._scalar = scalar
        self._row = row
        self._rows = rows or []

    def scalar_one(self) -> object:
        return self._scalar

    def scalar_one_or_none(self) -> object:
        return self._scalar

    def first(self) -> object:
        return self._row

    def all(self) -> list:
        return self._rows


def _connection(execute_results: list[object]) -> AsyncMock:
    connection = AsyncMock()
    connection.execute = AsyncMock(side_effect=execute_results)
    return connection


def _engine(connection: AsyncMock) -> AsyncMock:
    engine = AsyncMock(spec=AsyncEngine)
    engine.begin.return_value.__aenter__ = AsyncMock(return_value=connection)
    engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)
    return engine


def _facade(connection: AsyncMock) -> IntakeFacade:
    return IntakeFacade(engine=_engine(connection))


def _inserts(connection: AsyncMock) -> list[Insert]:
    return [
        call.args[0]
        for call in connection.execute.await_args_list
        if isinstance(call.args[0], Insert)
    ]


def _insert_params(inserts: list[Insert], table_name: str) -> dict[str, object] | None:
    for stmt in inserts:
        if stmt.table.name == table_name:
            return dict(stmt.compile().params)
    return None


def _intake_row(*, intake_id: int = 1, patient_id: int = 7, status: str = "captured") -> object:
    return SimpleNamespace(
        id=intake_id,
        patient_id=patient_id,
        mode="text",
        language="en",
        status=status,
        record_attempts=1,
        text="headache for two days",
        transcript=None,
        transcript_usability=None,
        forced_text=False,
        created_at=NOW,
        updated_at=NOW,
    )


def _media_row(*, media_ref_id: int = 11, intake_id: int = 1) -> object:
    return SimpleNamespace(
        id=media_ref_id,
        intake_id=intake_id,
        media_type="audio",
        object_key="intake/abc-123",
        audio_duration_ms=90_000,
        file_size_bytes=1_024_000,
        record_attempt=1,
    )


def _pre_summary_row(*, pre_summary_id: int = 5, intake_id: int = 1) -> object:
    return SimpleNamespace(
        id=pre_summary_id,
        intake_id=intake_id,
        structured_fields={"symptoms": ["headache"], "severity": "mild"},
        structuring_confidence=0.82,
        low_confidence=False,
        review_state="draft",
        patient_edits=None,
        doctor_corrections=None,
        review_attribution=None,
        reviewed_at=None,
        created_at=NOW,
        updated_at=NOW,
    )


def _intake_id_result(intake_id: int = 42) -> _FakeResult:
    return _FakeResult(scalar=intake_id)


def _outbox_result() -> _FakeResult:
    return _FakeResult(scalar=None)


@pytest.mark.asyncio
async def test_submit_intake_commits_row_and_captured_outbox_in_one_transaction() -> None:
    """The intake insert and ``intake.captured`` outbox write share a connection."""
    connection = _connection([_intake_id_result(intake_id=42), _outbox_result()])
    facade = _facade(connection)

    result = await facade.submit_intake(
        patient_id=7,
        mode="text",
        language="hi",
        text="sir dard hai",
    )

    assert result.intake_id == 42
    assert result.status == "captured"
    # Exactly one engine transaction was opened for the whole submit.
    engine = facade._engine
    engine.begin.assert_called_once()
    # The intake row was inserted with the captured lifecycle state.
    intake_params = _insert_params(_inserts(connection), intake_intakes.name)
    assert intake_params is not None
    assert intake_params["mode"] == "text"
    assert intake_params["language"] == "hi"
    assert intake_params["status"] == "captured"
    assert intake_params["record_attempts"] == 1
    assert intake_params["forced_text"] is False


@pytest.mark.asyncio
async def test_submit_intake_writes_the_captured_envelope_through_write_outbox() -> None:
    """The outbox write is a real ``intake.captured`` envelope, not a raw row."""
    connection = _connection([_intake_id_result(intake_id=9), _outbox_result()])
    facade = _facade(connection)

    await facade.submit_intake(
        patient_id=7,
        mode="voice",
        language="en",
        media_ref_id=5,
    )

    # The zero-cost assertion: the write_outbox contract passed the same
    # connection, the intake schema, the outbox table name, and an envelope
    # carrying the captured event type + intake id (accepted criterion 1).
    calls = [
        call for call in connection.execute.await_args_list if isinstance(call.args[0], Insert)
    ]
    # First insert is the intake row, second is the outbox row.
    assert len(calls) == 2
    outbox_write = calls[1]
    assert outbox_write.args[0].table.name == "intake_outbox"
    values = outbox_write.args[0].compile().params
    assert values["event_type"] == EVENT_INTAKE_CAPTURED
    assert values["status"] == "pending"
    payload = IntakeCapturedPayload.model_validate(values["payload"])
    assert payload.intake_id == 9


@pytest.mark.asyncio
async def test_submit_intake_text_mode_demands_text_rejects_media_ref() -> None:
    facade = _facade(_connection([]))

    with pytest.raises(
        IntakeValidationError,
        match="text mode intake must not include a media reference",
    ):
        await facade.submit_intake(
            patient_id=7,
            mode="text",
            language="en",
            media_ref_id=3,
        )

    with pytest.raises(IntakeValidationError, match="requires text content"):
        await facade.submit_intake(patient_id=7, mode="text", language="en")


@pytest.mark.asyncio
async def test_submit_intake_voice_mode_demands_media_ref_rejects_text() -> None:
    facade = _facade(_connection([]))

    with pytest.raises(
        IntakeValidationError,
        match="voice mode intake must not include text content",
    ):
        await facade.submit_intake(
            patient_id=7,
            mode="voice",
            language="en",
            text="pehle record karo",
        )

    with pytest.raises(IntakeValidationError, match="requires a media reference"):
        await facade.submit_intake(patient_id=7, mode="voice", language="en")


@pytest.mark.asyncio
async def test_submit_intake_text_exceeding_2000_chars_is_rejected() -> None:
    """The text cap is enforced server-side with a typed error (criterion 2)."""
    facade = _facade(_connection([]))

    with pytest.raises(IntakeValidationError, match="exceeds 2000 character cap"):
        await facade.submit_intake(
            patient_id=7,
            mode="text",
            language="en",
            text="a" * 2001,
        )


@pytest.mark.asyncio
async def test_submit_intake_text_of_exactly_2000_chars_is_accepted() -> None:
    """The cap is inclusive: exactly 2000 chars is a valid submission."""
    connection = _connection([_intake_id_result(intake_id=8), _outbox_result()])
    facade = _facade(connection)

    result = await facade.submit_intake(
        patient_id=7,
        mode="text",
        language="en",
        text="b" * 2000,
    )

    assert result.intake_id == 8


@pytest.mark.asyncio
async def test_submit_intake_capture_commits_before_any_ai_runs() -> None:
    """A capture commits durably and never touches an AI seam (AC5, durable here).

    The ticket's durability half is structural: the intake row and its
    ``intake.captured`` outbox event are the ONLY writes in the submit
    transaction - no AI gateway call is attempted on this facade at all.
    The AI pipeline runs asynchronously from the captured event; its
    failure handling (``ai_job.failed``, raw-review degrade) is tested at
    the worker/pipeline seam in the later pipeline tickets.
    """
    connection = _connection([_intake_id_result(intake_id=42), _outbox_result()])
    facade = _facade(connection)

    result = await facade.submit_intake(
        patient_id=7,
        mode="text",
        language="en",
        text="draft durable now",
    )

    assert result.status == "captured"
    # Exactly two inserts (row + outbox event) and nothing else touched the
    # connection - no AI gateway seam exists on this facade.
    inserts = _inserts(connection)
    assert [s.table.name for s in inserts] == ["intake_intakes", "intake_outbox"]


@pytest.mark.asyncio
async def test_get_intake_returns_agreed_dto_with_status_and_media_refs() -> None:
    connection = _connection(
        [_FakeResult(row=_intake_row(intake_id=1, patient_id=7)), _FakeResult(rows=[_media_row()])]
    )
    facade = _facade(connection)

    view = await facade.get_intake(intake_id=1, patient_id=7)

    assert isinstance(view, IntakeDetailView)
    assert view.intake_id == 1
    assert view.patient_id == 7
    assert view.status == "captured"
    assert view.record_attempts == 1
    assert view.text == "headache for two days"
    assert len(view.media_refs) == 1
    assert view.media_refs[0].object_key == "intake/abc-123"


@pytest.mark.asyncio
async def test_get_intake_refuses_an_intake_the_patient_does_not_own() -> None:
    facade = _facade(_connection([_FakeResult(row=None)]))

    with pytest.raises(IntakeNotFoundError, match="not found for patient"):
        await facade.get_intake(intake_id=1, patient_id=99)


@pytest.mark.asyncio
async def test_get_pre_summary_returns_draft_confidence_honesty_and_edits() -> None:
    row = _pre_summary_row(pre_summary_id=5, intake_id=1)
    connection = _connection(
        [_FakeResult(row=_intake_row(intake_id=1, patient_id=7)), _FakeResult(row=row)]
    )
    facade = _facade(connection)

    view = await facade.get_pre_summary(intake_id=1, patient_id=7)

    assert isinstance(view, PreSummaryView)
    assert view.pre_summary_id == 5
    assert view.intake_id == 1
    assert view.structured_fields == {"symptoms": ["headache"], "severity": "mild"}
    assert view.structuring_confidence == 0.82
    assert view.low_confidence is False
    assert view.review_state == "draft"
    assert view.patient_edits is None
    assert view.review_attribution is None


@pytest.mark.asyncio
async def test_get_pre_summary_honesty_flag_true_on_low_confidence() -> None:
    row = _pre_summary_row(pre_summary_id=6, intake_id=2)
    row.low_confidence = True
    row.structuring_confidence = 0.55
    connection = _connection(
        [_FakeResult(row=_intake_row(intake_id=2, patient_id=7)), _FakeResult(row=row)]
    )
    facade = _facade(connection)

    view = await facade.get_pre_summary(intake_id=2, patient_id=7)

    assert view.low_confidence is True
    assert view.structuring_confidence == 0.55
    assert view.review_state == "draft"


@pytest.mark.asyncio
async def test_get_pre_summary_refuses_an_intake_the_patient_does_not_own() -> None:
    facade = _facade(_connection([_FakeResult(row=None)]))

    with pytest.raises(IntakeNotFoundError, match="not found for patient"):
        await facade.get_pre_summary(intake_id=1, patient_id=99)


@pytest.mark.asyncio
async def test_get_pre_summary_none_when_no_pre_summary_refs_exist() -> None:
    connection = _connection(
        [_FakeResult(row=_intake_row(intake_id=1, patient_id=7)), _FakeResult(row=None)]
    )
    facade = _facade(connection)

    with pytest.raises(IntakeNotFoundError, match="pre-summary not found"):
        await facade.get_pre_summary(intake_id=1, patient_id=7)


@pytest.mark.asyncio
async def test_request_rx_draft_is_a_contract_stub() -> None:
    facade = _facade(_connection([]))

    with pytest.raises(NotImplementedError, match="contract stub"):
        await facade.request_rx_draft(
            doctor_input_ref=1,
            pre_summary_ref=2,
        )
