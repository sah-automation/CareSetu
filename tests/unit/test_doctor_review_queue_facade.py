"""PHASE-8.1 T07: IntakeFacade list_review_queue seam (ticket #447).

Drives the list_review_queue facade through a mocked engine at the
facade-with-fakes seam:

- Returns only draft-state pre-summaries assigned to the calling doctor
  (data minimization, security standards §2).
- Low-confidence pre-summaries surface first (US-12), newest-created first
  within each confidence class.
- Each item carries the low_confidence honesty flag (AMB-006).
- Empty result returns an empty list, never an error.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import ClauseElement
from sqlalchemy.ext.asyncio import AsyncEngine

from modules.iam.facade import PatientProfile
from modules.intake.facade import IntakeFacade
from modules.intake.intake_models import ReviewQueueItem

NOW = datetime.now(UTC)


# ---------------------------------------------------------------------------
# Fake-result helpers (mirrors test_pick_doctor_facade.py)
# ---------------------------------------------------------------------------


class _FakeResult:
    """Mimics asyncpg ``CursorResult`` shapes used by the facade."""

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


def _facade(connection: AsyncMock, iam_facade: object | None = None) -> IntakeFacade:
    return IntakeFacade(engine=_engine(connection), iam_facade=iam_facade)


class _StubIamFacade:
    """Minimal iam facade stand-in: per-identity profile or None (missing)."""

    def __init__(self, profiles: dict[int, PatientProfile | None]) -> None:
        self._profiles = profiles
        self.reads: list[int] = []

    async def get_patient_profile(self, identity_id: int) -> PatientProfile | None:
        self.reads.append(identity_id)
        return self._profiles.get(identity_id)


def _profile(name: str = "Ravi Kumar", age: int = 32) -> PatientProfile:
    return PatientProfile(
        name=name,
        age=age,
        gender="male",
        preferred_language="en",
        area=None,
        emergency_contact=None,
        photo_ref=None,
    )


def _queue_row(
    *,
    ps_id: int = 1,
    intake_id: int = 10,
    patient_id: int = 30,
    structured_fields: dict | None = None,
    structuring_confidence: float | None = 0.80,
    low_confidence: bool = False,
    review_state: str = "draft",
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=ps_id,
        intake_id=intake_id,
        patient_id=patient_id,
        structured_fields=structured_fields,
        structuring_confidence=structuring_confidence,
        low_confidence=low_confidence,
        review_state=review_state,
        created_at=created_at or NOW,
        updated_at=updated_at or NOW,
    )


def _statements(connection: AsyncMock) -> list[ClauseElement]:
    """All SQLAlchemy statement objects executed on the connection."""
    return [
        call.args[0]
        for call in connection.execute.await_args_list
        if isinstance(call.args[0], ClauseElement)
    ]


# ---------------------------------------------------------------------------
# list_review_queue: happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_review_queue_returns_review_queue_items() -> None:
    rows = [
        _queue_row(
            ps_id=2,
            intake_id=20,
            patient_id=30,
            low_confidence=True,
            structuring_confidence=0.55,
            structured_fields={
                "chief_complaints": ["Fever"],
                "symptoms": ["Cough"],
                "duration": "3 days",
            },
        ),
        _queue_row(
            ps_id=1,
            intake_id=10,
            patient_id=31,
            low_confidence=False,
            structuring_confidence=0.82,
            structured_fields={},
        ),
    ]
    connection = _connection([_FakeResult(rows=rows)])
    facade = _facade(connection)

    results = await facade.list_review_queue(doctor_id=42)

    assert len(results) == 2
    assert all(isinstance(r, ReviewQueueItem) for r in results)
    assert results[0].pre_summary_id == 2
    assert results[0].intake_id == 20
    assert results[0].low_confidence is True
    assert results[0].structuring_confidence == 0.55
    assert results[0].snippet == "Fever, Cough, 3 days"
    assert results[0].section_count == 3
    assert results[1].pre_summary_id == 1
    assert results[1].low_confidence is False
    assert results[1].structuring_confidence == 0.82
    assert results[1].snippet is None
    assert results[1].section_count == 0


@pytest.mark.asyncio
async def test_list_review_queue_resolves_patient_profiles_via_iam_seam() -> None:
    rows = [
        _queue_row(ps_id=2, intake_id=20, patient_id=30),
        _queue_row(ps_id=1, intake_id=10, patient_id=31),
        _queue_row(ps_id=3, intake_id=30, patient_id=30),
    ]
    connection = _connection([_FakeResult(rows=rows)])
    iam = _StubIamFacade({30: _profile()})
    facade = _facade(connection, iam_facade=iam)

    results = await facade.list_review_queue(doctor_id=42)

    assert [r.patient_name for r in results] == [
        "Ravi Kumar",
        None,
        "Ravi Kumar",
    ]
    assert [r.patient_age for r in results] == [32, None, 32]
    # One profile read per unique patient, never a per-row N+1 surprise.
    assert sorted(iam.reads) == [30, 31]


@pytest.mark.asyncio
async def test_list_review_queue_without_iam_facade_degrades_gracefully() -> None:
    connection = _connection([_FakeResult(rows=[_queue_row(patient_id=30)])])
    facade = _facade(connection)

    results = await facade.list_review_queue(doctor_id=42)

    assert results[0].patient_name is None
    assert results[0].patient_age is None


@pytest.mark.asyncio
async def test_list_review_queue_degrades_when_profile_resolution_fails() -> None:
    rows = [_queue_row(patient_id=30)]
    connection = _connection([_FakeResult(rows=rows)])

    class _RaisingIamFacade:
        async def get_patient_profile(self, identity_id: int) -> PatientProfile | None:
            raise RuntimeError("iam seam down")

    facade = _facade(connection, iam_facade=_RaisingIamFacade())

    results = await facade.list_review_queue(doctor_id=42)

    assert len(results) == 1
    assert results[0].patient_name is None
    assert results[0].patient_age is None


@pytest.mark.asyncio
async def test_list_review_queue_empty_when_no_rows() -> None:
    connection = _connection([_FakeResult(rows=[])])
    facade = _facade(connection)

    results = await facade.list_review_queue(doctor_id=42)

    assert results == []


# ---------------------------------------------------------------------------
# list_review_queue: SQL shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_review_queue_uses_doctor_filter_and_low_confidence_first() -> None:
    connection = _connection([_FakeResult(rows=[])])
    facade = _facade(connection)

    await facade.list_review_queue(doctor_id=42)

    stmts = _statements(connection)
    select_stmt = stmts[0]
    compiled_sql = str(select_stmt.compile()).upper()
    compiled_params = dict(select_stmt.compile().params)

    assert 42 in compiled_params.values()
    assert "draft" in compiled_params.values()
    assert "ORDER BY" in compiled_sql
    assert "CASE" in compiled_sql
    assert "INTAKE_INTAKES" in compiled_sql


@pytest.mark.asyncio
async def test_list_review_queue_joins_assigned_partner_and_filters_draft() -> None:
    connection = _connection([_FakeResult(rows=[])])
    facade = _facade(connection)

    await facade.list_review_queue(doctor_id=99)

    stmts = _statements(connection)
    select_stmt = stmts[0]
    compiled = str(select_stmt.compile())
    params = dict(select_stmt.compile().params)

    assert "intake_intakes" in compiled
    assert "intake_pre_summaries" in compiled
    assert 99 in params.values()
    assert "draft" in params.values()
