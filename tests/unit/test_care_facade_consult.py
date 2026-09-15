"""PHASE-8 T04: consultation workflow facade (ticket #420).

Drives ``mark_consult_complete``, ``get_case``, ``list_doctor_cases``,
``submit_doctor_input``, ``close_case_without_rx`` and the new
``IntakeFacade.get_finalized_pre_summary`` handshake seam through a mocked
engine at the facade-with-fakes seam, mirroring ``test_intake_review_facade.py``.
Pins the consult workflow contract:

- ``get_finalized_pre_summary`` returns only ``final``-state summaries and
  raises otherwise (intake seam, acceptance criterion 1).
- ``mark_consult_complete`` rejects when the pre-summary is not finalized
  (acceptance criterion 2).
- ``mark_consult_complete`` transitions the case to PrescriptionPending and
  publishes ``case.consult_complete`` in the same transaction (acceptance
  criterion 3).
- ``get_case`` returns a typed ``CaseDetailView``; ``list_doctor_cases``
  returns only open cases (acceptance criterion 4).
- ``submit_doctor_input`` records a voice/photo input and validates the case
  state (acceptance criterion 5).
- ``close_case_without_rx`` closes from PrescriptionPending only, records
  ``closed_at``/``close_reason``, and publishes ``case.closed`` in the same
  transaction (PHASE-8 review-close T3, ticket #429).
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import ClauseElement
from sqlalchemy.ext.asyncio import AsyncEngine

from bus.events import EVENT_CASE_CLOSED, EVENT_CASE_CONSULT_COMPLETE
from modules.care.care_models import CaseDetailView, DoctorInputResult
from modules.care.domain.exceptions import (
    CareNotFoundError,
    CareValidationError,
    IllegalCareTransitionError,
)
from modules.care.facade import CareFacade
from modules.care.outbox import CARE_OUTBOX_TABLE
from modules.care.schema.models import care_cases, care_doctor_inputs
from modules.intake.domain.exceptions import IntakeNotFoundError, IntakeValidationError
from modules.intake.facade import IntakeFacade
from modules.intake.intake_models import PreSummaryView

NOW = datetime.now(UTC)


# ---------------------------------------------------------------------------
# Fake-result helpers (mirrors test_intake_review_facade.py)
# ---------------------------------------------------------------------------


class _FakeResult:
    """Mimics ``Insert``/``Select`` result shapes: ``first``, ``scalar_one``, ``all``."""

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


def _intake_facade(connection: AsyncMock) -> IntakeFacade:
    return IntakeFacade(engine=_engine(connection))


def _care_facade(case_connection: AsyncMock, intake_facade: IntakeFacade) -> CareFacade:
    return CareFacade(engine=_engine(case_connection), intake_facade=intake_facade)


def _statements(connection: AsyncMock) -> list[ClauseElement]:
    """All SQLAlchemy statement objects executed on the connection."""
    return [
        call.args[0]
        for call in connection.execute.await_args_list
        if isinstance(call.args[0], ClauseElement)
    ]


def _stmt_params(statements: list[ClauseElement], table_name: str) -> dict[str, Any] | None:
    """Compiled bind parameters for the first statement touching ``table_name``."""
    for stmt in statements:
        table = getattr(stmt, "table", None)
        if table is not None and table.name == table_name:
            return dict(stmt.compile().params)
    return None


# ---------------------------------------------------------------------------
# Row builders
# ---------------------------------------------------------------------------


def _case_row(
    *,
    case_id: int = 1,
    patient_id: int = 7,
    doctor_id: int | None = 42,
    pre_summary_id: int | None = 5,
    stage: str = "pre_summary",
    forced_review: bool = False,
) -> object:
    return SimpleNamespace(
        id=case_id,
        patient_id=patient_id,
        doctor_id=doctor_id,
        pre_summary_id=pre_summary_id,
        stage=stage,
        forced_review=forced_review,
        closed_at=None,
        close_reason=None,
        created_at=NOW,
        updated_at=NOW,
    )


def _pre_summary_row(
    *,
    pre_summary_id: int = 5,
    intake_id: int = 1,
    review_state: str = "final",
) -> object:
    return SimpleNamespace(
        id=pre_summary_id,
        intake_id=intake_id,
        structured_fields={"symptoms": ["headache"], "severity": "mild"},
        structuring_confidence=0.82,
        low_confidence=False,
        review_state=review_state,
        patient_edits=None,
        doctor_corrections=None,
        review_attribution="doctor",
        reviewed_by=42,
        reviewed_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )


# ========================================================================
# Intake seam: get_finalized_pre_summary
# ========================================================================


@pytest.mark.asyncio
async def test_get_finalized_pre_summary_returns_final_summary() -> None:
    connection = _connection([_FakeResult(row=_pre_summary_row())])
    facade = _intake_facade(connection)

    result = await facade.get_finalized_pre_summary(pre_summary_id=5)

    assert isinstance(result, PreSummaryView)
    assert result.pre_summary_id == 5
    assert result.review_state == "final"


@pytest.mark.asyncio
async def test_get_finalized_pre_summary_raises_when_missing() -> None:
    connection = _connection([_FakeResult(row=None)])
    facade = _intake_facade(connection)

    with pytest.raises(IntakeNotFoundError, match="pre-summary 5 not found"):
        await facade.get_finalized_pre_summary(pre_summary_id=5)


@pytest.mark.parametrize("state", ["draft", "reviewed"])
@pytest.mark.asyncio
async def test_get_finalized_pre_summary_raises_at_every_non_final_state(
    state: str,
) -> None:
    connection = _connection([_FakeResult(row=_pre_summary_row(review_state=state))])
    facade = _intake_facade(connection)

    with pytest.raises(IntakeValidationError, match="not finalized"):
        await facade.get_finalized_pre_summary(pre_summary_id=5)


# ========================================================================
# mark_consult_complete
# ========================================================================


@pytest.mark.asyncio
async def test_mark_consult_complete_transitions_and_publishes() -> None:
    case_conn = _connection([_FakeResult(row=_case_row()), _FakeResult(), _FakeResult()])
    intake_conn = _connection([_FakeResult(row=_pre_summary_row())])
    facade = _care_facade(case_conn, _intake_facade(intake_conn))

    result = await facade.mark_consult_complete(doctor_id=42, case_id=1)

    assert isinstance(result, CaseDetailView)
    assert result.case_id == 1
    assert result.stage == "prescription_pending"
    assert result.doctor_id == 42

    update_params = _stmt_params(_statements(case_conn), care_cases.name)
    assert update_params is not None
    assert update_params["stage"] == "prescription_pending"
    assert update_params["consult_completed_by"] == 42

    outbox_params = _stmt_params(_statements(case_conn), CARE_OUTBOX_TABLE)
    assert outbox_params is not None
    assert outbox_params["event_type"] == EVENT_CASE_CONSULT_COMPLETE


@pytest.mark.asyncio
async def test_mark_consult_complete_rejects_when_pre_summary_not_finalized() -> None:
    case_conn = _connection([_FakeResult(row=_case_row())])
    intake_conn = _connection([_FakeResult(row=_pre_summary_row(review_state="draft"))])
    facade = _care_facade(case_conn, _intake_facade(intake_conn))

    with pytest.raises(IntakeValidationError, match="not finalized"):
        await facade.mark_consult_complete(doctor_id=42, case_id=1)

    assert _stmt_params(_statements(case_conn), care_cases.name) is None
    assert _stmt_params(_statements(case_conn), CARE_OUTBOX_TABLE) is None


@pytest.mark.asyncio
async def test_mark_consult_complete_rejects_when_pre_summary_missing() -> None:
    case_conn = _connection([_FakeResult(row=_case_row())])
    intake_conn = _connection([_FakeResult(row=None)])
    facade = _care_facade(case_conn, _intake_facade(intake_conn))

    with pytest.raises(IntakeNotFoundError):
        await facade.mark_consult_complete(doctor_id=42, case_id=1)


@pytest.mark.asyncio
async def test_mark_consult_complete_rejects_when_case_lacks_pre_summary() -> None:
    case_conn = _connection([_FakeResult(row=_case_row(pre_summary_id=None))])
    intake_conn = _connection([_FakeResult(row=None)])
    facade = _care_facade(case_conn, _intake_facade(intake_conn))

    with pytest.raises(IntakeNotFoundError):
        await facade.mark_consult_complete(doctor_id=42, case_id=1)


@pytest.mark.asyncio
async def test_mark_consult_complete_raises_for_missing_case() -> None:
    case_conn = _connection([_FakeResult(row=None)])
    facade = _care_facade(case_conn, _intake_facade(_connection([])))

    with pytest.raises(CareNotFoundError):
        await facade.mark_consult_complete(doctor_id=42, case_id=99)


@pytest.mark.asyncio
async def test_mark_consult_complete_raises_for_unowned_case() -> None:
    case_conn = _connection([_FakeResult(row=_case_row(doctor_id=7))])
    facade = _care_facade(case_conn, _intake_facade(_connection([])))

    with pytest.raises(CareNotFoundError):
        await facade.mark_consult_complete(doctor_id=42, case_id=1)


@pytest.mark.asyncio
async def test_mark_consult_complete_rejects_reentrant_completion() -> None:
    case_conn = _connection([_FakeResult(row=_case_row(stage="prescription_pending"))])
    facade = _care_facade(case_conn, _intake_facade(_connection([])))

    with pytest.raises(IllegalCareTransitionError, match="prescription_pending"):
        await facade.mark_consult_complete(doctor_id=42, case_id=1)


# ========================================================================
# get_case
# ========================================================================


@pytest.mark.asyncio
async def test_get_case_returns_typed_view() -> None:
    connection = _connection([_FakeResult(row=_case_row())])
    facade = _care_facade(connection, _intake_facade(_connection([])))

    result = await facade.get_case(doctor_id=42, case_id=1)

    assert isinstance(result, CaseDetailView)
    assert result.case_id == 1
    assert result.patient_id == 7
    assert result.doctor_id == 42
    assert result.pre_summary_id == 5
    assert result.stage == "pre_summary"


@pytest.mark.asyncio
async def test_get_case_raises_for_unowned_case() -> None:
    connection = _connection([_FakeResult(row=None)])
    facade = _care_facade(connection, _intake_facade(_connection([])))

    with pytest.raises(CareNotFoundError, match="not found for doctor"):
        await facade.get_case(doctor_id=42, case_id=1)


# ========================================================================
# list_doctor_cases
# ========================================================================


@pytest.mark.asyncio
async def test_list_doctor_cases_returns_only_open_cases() -> None:
    connection = _connection(
        [
            _FakeResult(
                rows=[
                    _case_row(case_id=1, stage="pre_summary"),
                    _case_row(case_id=2, stage="closed"),
                    _case_row(case_id=3, stage="prescription_pending"),
                ]
            )
        ]
    )
    facade = _care_facade(connection, _intake_facade(_connection([])))

    results = await facade.list_doctor_cases(doctor_id=42)

    assert all(isinstance(v, CaseDetailView) for v in results)
    open_ids = [v.case_id for v in results if v.stage != "closed"]
    assert len(open_ids) == 2


@pytest.mark.asyncio
async def test_list_doctor_cases_uses_doctor_filter_and_ascending_order() -> None:
    connection = _connection([_FakeResult(rows=[])])
    facade = _care_facade(connection, _intake_facade(_connection([])))

    await facade.list_doctor_cases(doctor_id=42)

    stmts = _statements(connection)
    select_stmt = stmts[0]
    compiled_sql = str(select_stmt.compile())
    compiled_params = dict(select_stmt.compile().params)

    assert 42 in compiled_params.values()
    assert "closed" in compiled_params.values()
    assert "ORDER BY" in compiled_sql.upper()


# ========================================================================
# submit_doctor_input
# ========================================================================


@pytest.mark.asyncio
async def test_submit_doctor_input_records_voice_input() -> None:
    connection = _connection([_FakeResult(row=_case_row()), _FakeResult(scalar=10)])
    facade = _care_facade(connection, _intake_facade(_connection([])))

    result = await facade.submit_doctor_input(
        doctor_id=42,
        case_id=1,
        input_type="voice",
        media_ref="rx_input/audio-1.webm",
        sensitive_class="sensitive",
    )

    assert isinstance(result, DoctorInputResult)
    assert result.input_id == 10
    assert result.case_id == 1
    assert result.input_type == "voice"
    assert result.media_ref == "rx_input/audio-1.webm"
    assert result.sensitive_class == "sensitive"

    insert_params = _stmt_params(_statements(connection), care_doctor_inputs.name)
    assert insert_params is not None
    assert insert_params["case_id"] == 1
    assert insert_params["input_type"] == "voice"


@pytest.mark.asyncio
async def test_submit_doctor_input_records_photo_input() -> None:
    connection = _connection([_FakeResult(row=_case_row()), _FakeResult(scalar=11)])
    facade = _care_facade(connection, _intake_facade(_connection([])))

    result = await facade.submit_doctor_input(
        doctor_id=42,
        case_id=1,
        input_type="photo",
        media_ref="rx_input/photo-1.jpg",
        sensitive_class="restricted",
    )

    assert result.input_id == 11
    assert result.input_type == "photo"


@pytest.mark.asyncio
async def test_submit_doctor_input_rejects_when_case_closed() -> None:
    connection = _connection([_FakeResult(row=_case_row(stage="closed"))])
    facade = _care_facade(connection, _intake_facade(_connection([])))

    with pytest.raises(CareValidationError, match="closed"):
        await facade.submit_doctor_input(
            doctor_id=42,
            case_id=1,
            input_type="voice",
            media_ref="rx_input/a.webm",
        )


@pytest.mark.asyncio
async def test_submit_doctor_input_rejects_missing_case() -> None:
    connection = _connection([_FakeResult(row=None)])
    facade = _care_facade(connection, _intake_facade(_connection([])))

    with pytest.raises(CareNotFoundError):
        await facade.submit_doctor_input(
            doctor_id=42,
            case_id=99,
            input_type="voice",
            media_ref="rx_input/a.webm",
        )


@pytest.mark.asyncio
async def test_submit_doctor_input_rejects_unowned_case() -> None:
    connection = _connection([_FakeResult(row=_case_row(doctor_id=7))])
    facade = _care_facade(connection, _intake_facade(_connection([])))

    with pytest.raises(CareNotFoundError):
        await facade.submit_doctor_input(
            doctor_id=42,
            case_id=1,
            input_type="voice",
            media_ref="rx_input/a.webm",
        )


# ========================================================================
# close_case_without_rx
# ========================================================================


@pytest.mark.asyncio
async def test_close_case_without_rx_transitions_and_publishes() -> None:
    case_conn = _connection(
        [
            _FakeResult(row=_case_row(stage="prescription_pending")),
            _FakeResult(),
            _FakeResult(),
        ]
    )
    facade = _care_facade(case_conn, _intake_facade(_connection([])))

    result = await facade.close_case_without_rx(doctor_id=42, case_id=1, close_reason="no_show")

    assert isinstance(result, CaseDetailView)
    assert result.case_id == 1
    assert result.stage == "closed"
    assert result.close_reason == "no_show"
    assert result.closed_at is not None
    assert result.doctor_id == 42

    update_params = _stmt_params(_statements(case_conn), care_cases.name)
    assert update_params is not None
    assert update_params["stage"] == "closed"
    assert update_params["close_reason"] == "no_show"
    assert update_params["closed_at"] is not None

    outbox_params = _stmt_params(_statements(case_conn), CARE_OUTBOX_TABLE)
    assert outbox_params is not None
    assert outbox_params["event_type"] == EVENT_CASE_CLOSED


@pytest.mark.asyncio
async def test_close_case_without_rx_raises_from_pre_summary() -> None:
    case_conn = _connection([_FakeResult(row=_case_row(stage="pre_summary"))])
    facade = _care_facade(case_conn, _intake_facade(_connection([])))

    with pytest.raises(IllegalCareTransitionError, match="pre_summary"):
        await facade.close_case_without_rx(doctor_id=42, case_id=1, close_reason="no_show")

    assert _stmt_params(_statements(case_conn), care_cases.name) is None
    assert _stmt_params(_statements(case_conn), CARE_OUTBOX_TABLE) is None


@pytest.mark.asyncio
async def test_close_case_without_rx_raises_from_closed() -> None:
    case_conn = _connection([_FakeResult(row=_case_row(stage="closed"))])
    facade = _care_facade(case_conn, _intake_facade(_connection([])))

    with pytest.raises(IllegalCareTransitionError, match="closed"):
        await facade.close_case_without_rx(doctor_id=42, case_id=1, close_reason="no_show")


@pytest.mark.asyncio
async def test_close_case_without_rx_raises_for_missing_case() -> None:
    case_conn = _connection([_FakeResult(row=None)])
    facade = _care_facade(case_conn, _intake_facade(_connection([])))

    with pytest.raises(CareNotFoundError):
        await facade.close_case_without_rx(doctor_id=42, case_id=99, close_reason="no_show")


@pytest.mark.asyncio
async def test_close_case_without_rx_raises_for_unowned_case() -> None:
    case_conn = _connection([_FakeResult(row=_case_row(doctor_id=7))])
    facade = _care_facade(case_conn, _intake_facade(_connection([])))

    with pytest.raises(CareNotFoundError):
        await facade.close_case_without_rx(doctor_id=42, case_id=1, close_reason="no_show")
