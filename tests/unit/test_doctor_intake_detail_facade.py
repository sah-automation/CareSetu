"""PHASE-8.1 T09: IntakeFacade get_doctor_intake_detail seam (ticket #484, US-14).

Drives the get_doctor_intake_detail facade through a mocked engine at the
facade-with-fakes seam (mirrors test_doctor_pre_summary_facade.py):

- Returns the intake's ORIGINAL transcript text + media refs (latest attempt
  ordering handled client-side) for the doctor to whom the intake is assigned.
- A different doctor (or an intake with no assignment) matches no JOIN row and
  is refused with IntakeNotFoundError (data minimization, security standards
  section 2) - the same 404 an unassigned doctor gets, never revealing that a
  matching pre-summary exists.
- The SQL keys off ``pre_summary_id`` (the handle the care case carries),
  joins to the intake via ``intake_id``, and predicates the intake's
  ``assigned_partner_id`` against the calling doctor - the same scoping seam
  as get_doctor_pre_summary (#448) and the media reads (#443).
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import ClauseElement
from sqlalchemy.ext.asyncio import AsyncEngine

from modules.intake.domain.exceptions import IntakeNotFoundError
from modules.intake.facade import IntakeFacade
from modules.intake.intake_models import IntakeDetailView

NOW = datetime.now(UTC)


class _FakeResult:
    """Mimics asyncpg ``CursorResult`` shapes used by the facade."""

    def __init__(
        self,
        row: object | None = None,
        rows: list[object] | None = None,
    ) -> None:
        self._row = row
        self._rows = rows or []

    def scalar_one(self) -> object:
        return self._row  # type: ignore[return-value]

    def first(self) -> object:
        return self._row

    def all(self) -> list[object]:
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


def _intake_row(
    *,
    intake_id: int = 42,
    patient_id: int = 7,
    transcript: str | None = "मुझे लगातार सिरदर्द रहता है।",
    text: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=intake_id,
        patient_id=patient_id,
        mode="voice",
        language="hi",
        status="ready_for_review",
        record_attempts=2,
        text=text,
        transcript=transcript,
        transcript_usability="ok",
        forced_text=False,
        created_at=NOW,
        updated_at=NOW,
    )


def _media_row(
    *,
    media_ref_id: int = 302,
    record_attempt: int = 2,
    audio_duration_ms: int = 17090,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=media_ref_id,
        media_type="audio/mpeg",
        object_key="in/42/302.mp3",
        audio_duration_ms=audio_duration_ms,
        file_size_bytes=132096,
        record_attempt=record_attempt,
    )


def _statements(connection: AsyncMock) -> list[ClauseElement]:
    """All SQLAlchemy statement objects executed on the connection."""
    return [
        call.args[0]
        for call in connection.execute.await_args_list
        if isinstance(call.args[0], ClauseElement)
    ]


@pytest.mark.asyncio
async def test_get_doctor_intake_detail_returns_transcript_and_media_refs() -> None:
    connection = _connection(
        [
            _FakeResult(row=_intake_row()),
            _FakeResult(
                rows=[_media_row(record_attempt=1), _media_row(record_attempt=2)],
            ),
        ]
    )
    facade = _facade(connection)

    result = await facade.get_doctor_intake_detail(
        pre_summary_id=101,
        doctor_id=12,
    )

    assert isinstance(result, IntakeDetailView)
    assert result.intake_id == 42
    assert result.patient_id == 7
    assert result.transcript == "मुझे लगातार सिरदर्द रहता है।"
    assert result.text is None
    assert result.media_refs[0].record_attempt == 1
    assert result.media_refs[1].record_attempt == 2
    assert result.media_refs[1].media_type == "audio/mpeg"


@pytest.mark.asyncio
async def test_get_doctor_intake_detail_refuses_different_doctor() -> None:
    connection = _connection([_FakeResult(row=None)])
    facade = _facade(connection)

    with pytest.raises(
        IntakeNotFoundError,
        match="intake detail not found for pre-summary 101 assigned to doctor 12",
    ):
        await facade.get_doctor_intake_detail(pre_summary_id=101, doctor_id=12)


@pytest.mark.asyncio
async def test_get_doctor_intake_detail_joins_and_scopes_to_assigned_doctor() -> None:
    connection = _connection([_FakeResult(row=_intake_row()), _FakeResult(rows=[_media_row()])])
    facade = _facade(connection)

    await facade.get_doctor_intake_detail(pre_summary_id=99, doctor_id=12)

    select_stmt = _statements(connection)[0]
    compiled = str(select_stmt.compile())
    params = dict(select_stmt.compile().params)

    # Keys off the pre-summary id (the care case's handle), joins to the
    # intake via the pre-summary's intake link, and predicates the intake's
    # ASSIGNED partner to the calling doctor - a swapped/missing predicate
    # would leak or cross-scope an intake assigned to a different doctor.
    assert "intake.intake_intakes.id = intake.intake_pre_summaries.intake_id" in compiled
    assert "intake.intake_pre_summaries.id = :id_1" in compiled
    assert "intake.intake_intakes.assigned_partner_id = :assigned_partner_id_1" in compiled
    assert int(params["id_1"]) == 99
    assert int(params["assigned_partner_id_1"]) == 12
