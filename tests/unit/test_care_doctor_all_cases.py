"""PHASE-8.2 T01: CaseConsoleFacade list_doctor_all_cases seam (ticket #539).

The doctor console's raw case feed is ``list_doctor_cases`` WITHOUT the
non-closed filter, so closed relationships stay derivable as Past (ADR-0019).
Drives the new seam through a mocked engine at the facade-with-fakes seam,
mirroring ``test_care_facade_consult.py``:

- Closed cases return alongside open ones - the doctor's claims are restored
  whole, newest activity first.
- Born-but-unclaimed cases merge in when the intake assignment names this
  doctor (the pick seam).
- Assigned-case reachability stays scoped: an unclaimed case assigned to a
  DIFFERENT doctor never leaks into the feed.

#661 adds the mirror seam: ``list_doctor_cases`` (the OPEN grid's feed) must
keep its non-closed filter on both branches, because Past history is derived
through ``list_doctor_all_cases`` and a closed case on /doctor/cases would
present a completed relationship as still open.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import ClauseElement
from sqlalchemy.ext.asyncio import AsyncEngine

from modules.care.care_models import CaseDetailView
from modules.care.case_facade import CaseConsoleFacade
from modules.intake.facade import IntakeFacade

NOW = datetime.now(UTC)

# ---------------------------------------------------------------------------
# Fake-result helpers (mirrors test_care_facade_consult.py)
# ---------------------------------------------------------------------------


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


def _care_facade(case_connection: AsyncMock, intake_facade: IntakeFacade) -> CaseConsoleFacade:
    return CaseConsoleFacade(engine=_engine(case_connection), intake_facade=intake_facade)


def _statements(connection: AsyncMock) -> list[ClauseElement]:
    return [
        call.args[0]
        for call in connection.execute.await_args_list
        if isinstance(call.args[0], ClauseElement)
    ]


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
    updated_at: datetime = NOW,
) -> object:
    return SimpleNamespace(
        id=case_id,
        patient_id=patient_id,
        doctor_id=doctor_id,
        pre_summary_id=pre_summary_id,
        stage=stage,
        forced_review=False,
        closed_at=updated_at if stage == "closed" else None,
        close_reason=None,
        created_at=NOW,
        updated_at=updated_at,
    )


def _assigned_partner_row(*, pre_summary_id: int = 5, assigned_partner_id: int = 42) -> object:
    return SimpleNamespace(
        id=pre_summary_id,
        assigned_partner_id=assigned_partner_id,
    )


# ---------------------------------------------------------------------------
# list_doctor_all_cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_doctor_all_cases_includes_closed_cases() -> None:
    connection = _connection(
        [
            _FakeResult(
                rows=[
                    _case_row(
                        case_id=1, stage="pre_summary", updated_at=datetime(2026, 9, 1, tzinfo=UTC)
                    ),
                    _case_row(
                        case_id=2, stage="closed", updated_at=datetime(2026, 9, 4, tzinfo=UTC)
                    ),
                    _case_row(
                        case_id=3,
                        stage="prescription_pending",
                        updated_at=datetime(2026, 9, 3, tzinfo=UTC),
                    ),
                ]
            ),
            _FakeResult(rows=[]),
            _FakeResult(rows=[SimpleNamespace(case_id=1), SimpleNamespace(case_id=3)]),
        ]
    )
    intake_conn = _connection([])
    facade = _care_facade(connection, _intake_facade(intake_conn))

    results = await facade.list_doctor_all_cases(doctor_id=42)

    assert all(isinstance(v, CaseDetailView) for v in results)
    by_id = {v.case_id: v for v in results}
    assert set(by_id) == {1, 2, 3}
    assert by_id[2].stage == "closed"
    assert by_id[1].has_doctor_input is True
    assert by_id[2].has_doctor_input is False
    # Newest activity (updated_at) leads the feed.
    assert [v.case_id for v in results] == [2, 3, 1]


@pytest.mark.asyncio
async def test_list_doctor_all_cases_merges_assigned_unclaimed_cases() -> None:
    connection = _connection(
        [
            _FakeResult(rows=[_case_row(case_id=1, doctor_id=42, stage="closed")]),
            _FakeResult(
                rows=[
                    _case_row(case_id=10, doctor_id=None, pre_summary_id=51, stage="pre_summary"),
                    _case_row(case_id=11, doctor_id=None, pre_summary_id=52, stage="closed"),
                ]
            ),
            _FakeResult(rows=[]),
        ]
    )
    intake_conn = _connection(
        [
            _FakeResult(
                rows=[
                    _assigned_partner_row(pre_summary_id=51, assigned_partner_id=42),
                    _assigned_partner_row(pre_summary_id=52, assigned_partner_id=7),
                ]
            )
        ]
    )
    facade = _care_facade(connection, _intake_facade(intake_conn))

    results = await facade.list_doctor_all_cases(doctor_id=42)

    # Case 10 is assigned to this doctor and reachable; case 11 belongs to
    # another doctor and stays out of the feed.
    assert [v.case_id for v in results] == [1, 10]
    assert all(v.doctor_id is not None or v.pre_summary_id in (51,) for v in results)


@pytest.mark.asyncio
async def test_list_doctor_all_cases_uses_no_stage_filter() -> None:
    connection = _connection([_FakeResult(rows=[]), _FakeResult(rows=[]), _FakeResult(rows=[])])
    intake_conn = _connection([])
    facade = _care_facade(connection, _intake_facade(intake_conn))

    await facade.list_doctor_all_cases(doctor_id=42)

    stmts = _statements(connection)
    claimed_stmt = stmts[0]
    unclaimed_stmt = stmts[1]

    claimed_params = dict(claimed_stmt.compile().params)

    # The claimed branch is scoped to this doctor, and the all-cases feed
    # carries no stage filter at all.
    assert 42 in claimed_params.values()
    assert "closed" not in claimed_params.values()
    assert "IS NULL" in str(unclaimed_stmt.compile()).upper()
    assert "ORDER BY" in str(unclaimed_stmt.compile()).upper()
    assert not intake_conn.execute.await_args_list


# ---------------------------------------------------------------------------
# list_doctor_cases (the open grid's seam: closed must never appear)
# ---------------------------------------------------------------------------


def _mentions_closed(stmt: ClauseElement) -> bool:
    """Whether the compiled statement carries the non-closed filter.

    Whichever way SQLAlchemy renders ``stage != CaseStage.CLOSED.value`` - a
    bound parameter or an inlined literal - the value has to be in one of the
    two places for the filter to be there at all.
    """
    compiled = stmt.compile()
    return "CLOSED" in str(compiled).upper() or "closed" in dict(compiled.params).values()


@pytest.mark.asyncio
async def test_list_doctor_cases_keeps_the_non_closed_filter_on_both_branches() -> None:
    """FEAT-008 / #661: the open grid's feed drops closed cases on BOTH branches.

    Mirror of ``test_list_doctor_all_cases_uses_no_stage_filter``: Past-case
    history is derived through ``list_doctor_all_cases`` (ADR-0019), so if the
    open seam lost its filter, a completed case would reappear on
    /doctor/cases as if it were still open.
    """
    connection = _connection([_FakeResult(rows=[]), _FakeResult(rows=[]), _FakeResult(rows=[])])
    intake_conn = _connection([])
    facade = _care_facade(connection, _intake_facade(intake_conn))

    await facade.list_doctor_cases(doctor_id=42)

    stmts = _statements(connection)
    claimed_stmt = stmts[0]
    unclaimed_stmt = stmts[1]

    claimed_params = dict(claimed_stmt.compile().params)

    # The claimed branch stays scoped to this doctor AND filters closed rows.
    assert 42 in claimed_params.values()
    assert _mentions_closed(claimed_stmt)
    # The born-but-unclaimed merge filters closed rows the same way.
    assert _mentions_closed(unclaimed_stmt)
    assert "IS NULL" in str(unclaimed_stmt.compile()).upper()
    assert not intake_conn.execute.await_args_list
