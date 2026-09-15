"""PHASE-7 T09: review facade seam (ticket #353, spec #344).

Drives ``save_patient_pre_summary_edits`` and ``mark_pre_summary_reviewed``
through a mocked engine at the facade-with-fakes seam, mirroring
``test_intake_facade_capture.py``. Pins the review-and-edit contract:

- Patient edits are saved as informational corrections and returned through
  the facade (never mutating structured fields, never triggering a review
  transition) (acceptance criterion 1).
- ``mark_pre_summary_reviewed`` transitions Draft -> Reviewed with a changed-
  fields record, attribution and timestamp for a low_confidence pre-summary
  (acceptance criterion 2).
- Doctor edits win over the AI-extracted values in the resulting reviewed
  copy (acceptance criterion 3).
- A low_confidence pre-summary cannot reach Reviewed without the attributed
  review action, and never reaches Final unreviewed (acceptance criterion 4).
- A high-confidence pre-summary is finalized by a single attributed review
  action (acceptance criterion 5).
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.sql.dml import Insert

from modules.intake.domain.exceptions import (
    IllegalPreSummaryTransitionError,
    IntakeNotFoundError,
    IntakeValidationError,
)
from modules.intake.facade import IntakeFacade
from modules.intake.intake_models import (
    PatientEditsResult,
    PreSummaryReviewResult,
    StructuredFields,
)
from modules.intake.schema.models import (
    intake_pre_summaries,
)

NOW = datetime.now(UTC)


class _FakeResult:
    """Mimics ``Insert``/``Select`` result shapes: ``first``, ``all``."""

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


def _facade(connection: AsyncMock) -> IntakeFacade:
    return IntakeFacade(engine=_engine(connection))


def _statements(connection: AsyncMock) -> list[Insert]:
    """All SQLAlchemy statement objects (inserts/updates) executed on the connection."""
    from sqlalchemy import ClauseElement

    return [
        call.args[0]
        for call in connection.execute.await_args_list
        if isinstance(call.args[0], ClauseElement)
    ]


def _update_params(statements: list, table_name: str) -> dict[str, object] | None:
    for stmt in statements:
        table = getattr(stmt, "table", None)
        if table is not None and table.name == table_name:
            return dict(stmt.compile().params)
    return None


def _intake_row(*, intake_id: int = 1, patient_id: int = 7) -> object:
    return SimpleNamespace(id=intake_id, patient_id=patient_id)


def _pre_summary_row(
    *,
    pre_summary_id: int = 5,
    intake_id: int = 1,
    confidence: object = 0.82,
    low_confidence: bool = False,
    review_state: str = "draft",
    structured_fields: dict | None = None,
) -> object:
    return SimpleNamespace(
        id=pre_summary_id,
        intake_id=intake_id,
        structured_fields=structured_fields or {"symptoms": ["headache"], "severity": "mild"},
        structuring_confidence=confidence,
        low_confidence=low_confidence,
        review_state=review_state,
        patient_edits=None,
        doctor_corrections=None,
        review_attribution=None,
        reviewed_by=None,
        reviewed_at=None,
        created_at=NOW,
        updated_at=NOW,
    )


@pytest.mark.asyncio
async def test_save_patient_pre_summary_edits_persists_informational_corrections() -> None:
    """Patient edits are saved as informational corrections (criterion 1)."""
    connection = _connection(
        [
            _FakeResult(row=_intake_row(intake_id=1, patient_id=7)),
            _FakeResult(row=_pre_summary_row(pre_summary_id=5, intake_id=1)),
            _FakeResult(row=None),
        ]
    )
    facade = _facade(connection)
    edits = {"severity": "worse than stated", "symptoms": ["headache", "nausea"]}

    result = await facade.save_patient_pre_summary_edits(intake_id=1, patient_id=7, fields=edits)

    assert isinstance(result, PatientEditsResult)
    assert result.intake_id == 1
    assert result.pre_summary_id == 5
    assert result.patient_edits == edits
    # The update only touches patient_edits (informational), never the review
    # state, structured fields, or attribution.
    params = _update_params(_statements(connection), intake_pre_summaries.name)
    assert params is not None
    assert params["patient_edits"] == edits
    assert "review_state" not in params
    assert "structured_fields" not in params
    assert "review_attribution" not in params


@pytest.mark.asyncio
async def test_save_patient_pre_summary_edits_refuses_intake_not_owned() -> None:
    connection = _connection([_FakeResult(row=None)])
    facade = _facade(connection)

    with pytest.raises(IntakeNotFoundError, match="not found for patient"):
        await facade.save_patient_pre_summary_edits(
            intake_id=1, patient_id=99, fields={"severity": "high"}
        )


@pytest.mark.asyncio
async def test_save_patient_pre_summary_edits_accumulates_across_saves() -> None:
    """Patient corrections accumulate - a later save never loses earlier ones."""
    row = _pre_summary_row()
    row.patient_edits = {"severity": "worse than stated"}
    connection = _connection(
        [
            _FakeResult(row=_intake_row(intake_id=1, patient_id=7)),
            _FakeResult(row=row),
            _FakeResult(row=None),
        ]
    )
    facade = _facade(connection)

    result = await facade.save_patient_pre_summary_edits(
        intake_id=1, patient_id=7, fields={"symptoms": ["headache", "nausea"]}
    )

    assert result.patient_edits == {
        "severity": "worse than stated",
        "symptoms": ["headache", "nausea"],
    }
    params = _update_params(_statements(connection), intake_pre_summaries.name)
    assert params is not None
    assert params["patient_edits"] == {
        "severity": "worse than stated",
        "symptoms": ["headache", "nausea"],
    }


@pytest.mark.asyncio
async def test_get_pre_summary_surfaces_patient_edits_for_the_doctor() -> None:
    """Patient edits are returned through get_pre_summary (acceptance criterion 1)."""
    row = _pre_summary_row()
    row.patient_edits = {"severity": "worse than stated"}
    connection = _connection(
        [_FakeResult(row=_intake_row(intake_id=1, patient_id=7)), _FakeResult(row=row)]
    )
    facade = _facade(connection)

    view = await facade.get_pre_summary(intake_id=1, patient_id=7)

    assert view.patient_edits == {"severity": "worse than stated"}
    # The informational corrections never leak into the AI structured fields.
    assert view.structured_fields == StructuredFields(symptoms=["headache"], severity="mild")
    assert view.review_state == "draft"


@pytest.mark.asyncio
async def test_mark_pre_summary_reviewed_low_confidence_gates_into_reviewed() -> None:
    """A low_confidence pre-summary reaches Reviewed only via the review (AC-2/4)."""
    row = _pre_summary_row(
        confidence=0.55,
        low_confidence=True,
        review_state="draft",
    )
    connection = _connection([_FakeResult(row=row), _FakeResult(row=None)])
    facade = _facade(connection)

    result = await facade.mark_pre_summary_reviewed(
        intake_id=1,
        doctor_id=12,
        corrections={"severity": "moderate"},
    )

    assert isinstance(result, PreSummaryReviewResult)
    # Hard gate: the low-confidence pre-summary can only reach Reviewed, never
    # Final, through this attributed review action.
    assert result.review_state == "reviewed"
    assert result.review_attribution == "doctor"
    assert result.reviewed_by == 12
    assert result.reviewed_at is not None
    # Edits win over the AI extraction in the reviewed copy.
    assert result.reviewed_copy == {"symptoms": ["headache"], "severity": "moderate"}
    assert result.changed_fields == ["severity"]

    params = _update_params(_statements(connection), intake_pre_summaries.name)
    assert params is not None
    assert params["review_state"] == "reviewed"
    assert params["review_attribution"] == "doctor"
    assert params["reviewed_by"] == 12
    assert params["reviewed_at"] is not None
    assert params["doctor_corrections"] == {"severity": "moderate"}
    # A review that only reaches Reviewed publishes no outbox event: there is
    # no "reviewed" event in the registry, and the pre-summary is not yet ready
    # for downstream use. No intake_outbox insert happened.
    inserts = [
        call.args[0]
        for call in connection.execute.await_args_list
        if isinstance(call.args[0], Insert) and call.args[0].table.name == "intake_outbox"
    ]
    assert inserts == []


@pytest.mark.asyncio
async def test_mark_pre_summary_reviewed_high_confidence_finalizes_single_action() -> None:
    """A high-confidence pre-summary is finalized in one attributed review (AC-5)."""
    row = _pre_summary_row(
        confidence=0.82,
        low_confidence=False,
        review_state="draft",
    )
    connection = _connection(
        [
            _FakeResult(row=row),
            _FakeResult(row=None),
            _FakeResult(scalar=7),
            _FakeResult(row=None),
        ]
    )
    facade = _facade(connection)

    result = await facade.mark_pre_summary_reviewed(
        intake_id=1,
        doctor_id=12,
        corrections={"history": "no prior surgeries"},
    )

    assert result.review_state == "final"
    assert result.review_attribution == "doctor"
    assert result.reviewed_by == 12
    assert result.reviewed_copy == {
        "symptoms": ["headache"],
        "severity": "mild",
        "history": "no prior surgeries",
    }
    assert result.changed_fields == ["history"]

    params = _update_params(_statements(connection), intake_pre_summaries.name)
    assert params is not None
    assert params["review_state"] == "final"
    assert params["review_attribution"] == "doctor"
    assert params["reviewed_by"] == 12

    # Reaching Final publishes pre_summary.ready in the SAME transaction
    # (ADR-0002 S1) so MOD-006/MOD-010 can attach and notify. The payload
    # carries the owning patient identity so the care module can birth the case
    # (PHASE-8 T2, #428).
    outbox = [
        call.args[0]
        for call in connection.execute.await_args_list
        if isinstance(call.args[0], Insert) and call.args[0].table.name == "intake_outbox"
    ]
    assert len(outbox) == 1
    outbox_values = outbox[0].compile().params
    assert outbox_values["status"] == "pending"
    assert outbox_values["payload"]["intake_id"] == 1
    assert outbox_values["payload"]["pre_summary_id"] == 5
    assert outbox_values["payload"]["patient_id"] == 7


@pytest.mark.asyncio
async def test_mark_pre_summary_low_confidence_unchanged_edits_are_not_changed() -> None:
    """Unchanged correction values are not counted as changed fields (AC-2)."""
    row = _pre_summary_row(
        confidence=0.40,
        low_confidence=True,
        review_state="draft",
    )
    connection = _connection([_FakeResult(row=row), _FakeResult(row=None)])
    facade = _facade(connection)

    result = await facade.mark_pre_summary_reviewed(
        intake_id=1,
        doctor_id=12,
        corrections={"severity": "mild"},  # matches extraction -> no change
    )

    assert result.review_state == "reviewed"
    assert result.changed_fields == []
    assert result.reviewed_copy["severity"] == "mild"


@pytest.mark.asyncio
async def test_mark_pre_summary_reviewed_requires_doctor_attribution() -> None:
    facade = _facade(_connection([]))

    with pytest.raises(IntakeValidationError, match="doctor identity is required"):
        await facade.mark_pre_summary_reviewed(
            intake_id=1,
            doctor_id=0,
            corrections={},
        )


@pytest.mark.asyncio
async def test_mark_pre_summary_reviewed_refuses_missing_pre_summary() -> None:
    facade = _facade(_connection([_FakeResult(row=None)]))

    with pytest.raises(IntakeNotFoundError, match="pre-summary not found"):
        await facade.mark_pre_summary_reviewed(
            intake_id=1,
            doctor_id=12,
            corrections={},
        )


@pytest.mark.asyncio
async def test_mark_pre_summary_reviewed_reviewing_already_final_is_illegal() -> None:
    """A finalized pre-summary cannot be re-reviewed (binding machine, AC-4)."""
    row = _pre_summary_row(
        confidence=0.82,
        low_confidence=False,
        review_state="final",
    )
    connection = _connection([_FakeResult(row=row)])
    facade = _facade(connection)

    with pytest.raises(IllegalPreSummaryTransitionError):
        await facade.mark_pre_summary_reviewed(
            intake_id=1,
            doctor_id=12,
            corrections={},
        )
