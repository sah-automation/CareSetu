"""PHASE-8 T07: REQ-023 hard gate - no prescription is issued without the
doctor's recorded double-check (ticket #423).

Pins the mandatory-approval invariant that sits across the prescription
machine and the facade (CONTEXT.md glossary, ``verification declaration``
/ ``revision-freeze approval``):

- **Machine hard gate (property):** for every ``(status, action)`` pair in
  the closed vocabularies, no transition ever answers ``ApprovedIssued``
  unless the action is ``APPROVE`` with ``verification_declaration=True`` -
  a declaration-less approval is structurally impossible, so zero
  e-prescriptions can be issued without the doctor's double-check.
- **Facade gate:** ``approve_prescription`` refuses a missing declaration
  (via the replaceable gate seam) BEFORE any write, a stale approval on an
  already-issued prescription is blocked, and the issued artifact is exactly
  the doctor's saved working revision - never the raw ``draft_snapshot``
  (revision-freeze: ``care_rx_items`` holds the frozen revision; approval
  only reads it, and ``approve`` with no saved revision is blocked).
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import ClauseElement
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.sql.dml import Insert

from modules.care.domain.exceptions import CareValidationError, IllegalPrescriptionTransitionError
from modules.care.domain.prescription_machine import (
    PrescriptionAction,
    PrescriptionState,
    PrescriptionStatus,
)
from modules.care.domain.prescription_machine import (
    transition as prescription_transition,
)
from modules.care.facade import CareFacade
from modules.care.outbox import CARE_OUTBOX_TABLE
from modules.care.schema.models import (
    care_prescriptions,
    care_rx_approvals,
    care_rx_items,
)
from modules.intake.facade import IntakeFacade

NOW = datetime.now(UTC)

AI_SNAPSHOT = {"rx_items": [{"name": "mock medication", "dose": "1 tablet", "duration": "5 days"}]}

_ALL_STATUSES: list[PrescriptionStatus] = list(PrescriptionStatus)
_ALL_ACTIONS: list[PrescriptionAction] = list(PrescriptionAction)


def _try_transition(
    status: PrescriptionStatus,
    action: PrescriptionAction,
    *,
    declaration: bool,
) -> PrescriptionState | None:
    """Answer the transition result, or ``None`` when the edge raises."""
    state = PrescriptionState(status=status, rejected_count=0)
    try:
        return prescription_transition(
            state,
            action,
            verification_declaration=declaration,
            rejection_reason="reviewer_note",
        )
    except IllegalPrescriptionTransitionError:
        return None


# ---------------------------------------------------------------------------
# Machine-level hard gate (property style - mirrors test_intake_low_confidence)
# ---------------------------------------------------------------------------


class TestApprovalDeclarationHardGate:
    """REQ-023: ``ApprovedIssued`` is reachable only via a declared APPROVE."""

    @pytest.mark.parametrize("status", _ALL_STATUSES)
    @pytest.mark.parametrize("action", _ALL_ACTIONS)
    def test_no_transition_issues_without_declaration(
        self, status: PrescriptionStatus, action: PrescriptionAction
    ) -> None:
        """Zero (status, action) pairs yield ApprovedIssued with declaration=False."""
        result = _try_transition(status, action, declaration=False)
        if result is not None:
            assert result.status is not PrescriptionStatus.APPROVED_ISSUED, (status, action)

    @pytest.mark.parametrize(
        "status", [PrescriptionStatus.DRAFT, PrescriptionStatus.DOCTOR_REVIEWED]
    )
    def test_approve_without_declaration_is_refused_with_gate_message(
        self, status: PrescriptionStatus
    ) -> None:
        """On an approvable state the gate names the missing declaration."""
        with pytest.raises(
            IllegalPrescriptionTransitionError,
            match="verification_declaration=true",
        ):
            prescription_transition(
                PrescriptionState(status=status, rejected_count=0),
                PrescriptionAction.APPROVE,
                verification_declaration=False,
            )

    @pytest.mark.parametrize(
        "status",
        [
            s
            for s in _ALL_STATUSES
            if s not in (PrescriptionStatus.DRAFT, PrescriptionStatus.DOCTOR_REVIEWED)
        ],
    )
    def test_approve_without_declaration_is_refused_from_other_states(
        self, status: PrescriptionStatus
    ) -> None:
        """From issued/rejected/fulfilled a declaration-less APPROVE is still
        refused (the edge itself is illegal) - never issues."""
        with pytest.raises(
            IllegalPrescriptionTransitionError, match="illegal while the prescription"
        ):
            prescription_transition(
                PrescriptionState(status=status, rejected_count=0),
                PrescriptionAction.APPROVE,
                verification_declaration=False,
            )

    @pytest.mark.parametrize("status", _ALL_STATUSES)
    @pytest.mark.parametrize("action", _ALL_ACTIONS)
    def test_declared_approve_is_the_only_route_to_issued(
        self, status: PrescriptionStatus, action: PrescriptionAction
    ) -> None:
        """The ONLY paths to ApprovedIssued are APPROVE-with-declaration on
        Draft/DoctorReviewed - every other edge is blocked even with a
        declaration supplied."""
        result = _try_transition(status, action, declaration=True)
        if result is not None and result.status is PrescriptionStatus.APPROVED_ISSUED:
            assert action is PrescriptionAction.APPROVE
            assert status in (
                PrescriptionStatus.DRAFT,
                PrescriptionStatus.DOCTOR_REVIEWED,
            )

    def test_declared_approve_docs_the_gate_from_both_approvable_states(self) -> None:
        """Draft and DoctorReviewed both approve into issued under declaration."""
        for status in (PrescriptionStatus.DRAFT, PrescriptionStatus.DOCTOR_REVIEWED):
            result = prescription_transition(
                PrescriptionState(status=status, rejected_count=0),
                PrescriptionAction.APPROVE,
                verification_declaration=True,
            )
            assert result.status is PrescriptionStatus.APPROVED_ISSUED


# ---------------------------------------------------------------------------
# Facade-level gate (mirrors test_care_facade_rx.py harness)
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


def _care_facade(case_connection: AsyncMock) -> CareFacade:
    intake = IntakeFacade(engine=_engine(_connection([])))
    return CareFacade(engine=_engine(case_connection), intake_facade=intake)


def _statements(connection: AsyncMock) -> list[ClauseElement]:
    return [
        call.args[0]
        for call in connection.execute.await_args_list
        if isinstance(call.args[0], ClauseElement)
    ]


def _stmt_params(statements: list[ClauseElement], table_name: str) -> dict[str, object] | None:
    for stmt in statements:
        table = getattr(stmt, "table", None)
        if table is not None and table.name == table_name:
            return dict(stmt.compile().params)
    return None


def _touches_table(statements: list[ClauseElement], table_name: str) -> bool:
    return _stmt_params(statements, table_name) is not None


def _insert_tables(statements: list[ClauseElement]) -> list[str]:
    return [stmt.table.name for stmt in statements if isinstance(stmt, Insert)]


def _case_row(
    *,
    case_id: int = 1,
    patient_id: int = 7,
    doctor_id: int | None = 42,
    pre_summary_id: int | None = 5,
    stage: str = "prescription_pending",
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


def _rx_row(
    *,
    rx_id: int = 1,
    case_id: int = 1,
    status: str = "doctor_reviewed",
    source: str = "ai_draft",
    attempt_no: int = 1,
    draft_snapshot: dict[str, object] | None = None,
    issued_at: object = None,
    attributed_doctor: int | None = None,
) -> object:
    return SimpleNamespace(
        id=rx_id,
        case_id=case_id,
        status=status,
        source=source,
        attempt_no=attempt_no,
        draft_snapshot=draft_snapshot if draft_snapshot is not None else {},
        issued_at=issued_at,
        attributed_doctor=attributed_doctor,
        created_at=NOW,
        updated_at=NOW,
    )


def _rx_item_row(
    *,
    item_id: int = 1,
    rx_id: int = 1,
    sequence: int = 1,
    name: str = "Para-500",
    dose: str | None = "500mg",
    duration: str | None = "3 days",
) -> object:
    return SimpleNamespace(
        id=item_id,
        prescription_id=rx_id,
        sequence=sequence,
        name=name,
        dose=dose,
        duration=duration,
    )


class TestFacadeApprovalGate:
    """REQ-023 at the facade boundary: refuse, block, freeze."""

    @pytest.mark.asyncio
    async def test_approval_declaration_missing_is_refused_before_any_write(self) -> None:
        """A doctor_reviewed prescription cannot be approved without the
        declaration - the gate refuses with no write to any care table."""
        care_conn = _connection([_FakeResult(row=_rx_row()), _FakeResult(row=_case_row())])
        facade = _care_facade(care_conn)

        with pytest.raises(CareValidationError, match="verification_declaration"):
            await facade.approve_prescription(
                case_id=1, rx_id=1, doctor_id=42, verification_declaration=False
            )

        assert _touches_table(_statements(care_conn), care_prescriptions.name) is False
        assert _touches_table(_statements(care_conn), care_rx_approvals.name) is False
        assert _touches_table(_statements(care_conn), CARE_OUTBOX_TABLE) is False

    @pytest.mark.asyncio
    async def test_stale_approval_on_issued_revision_is_blocked_without_writes(self) -> None:
        """An already-issued prescription is terminal: a second approval is a
        stale-revision replay and is refused before any write."""
        care_conn = _connection(
            [
                _FakeResult(row=_rx_row(status="issued", issued_at=NOW, attributed_doctor=42)),
                _FakeResult(row=_case_row()),
            ]
        )
        facade = _care_facade(care_conn)

        with pytest.raises(IllegalPrescriptionTransitionError, match="issued"):
            await facade.approve_prescription(
                case_id=1, rx_id=1, doctor_id=42, verification_declaration=True
            )

        assert _touches_table(_statements(care_conn), care_rx_approvals.name) is False
        assert _touches_table(_statements(care_conn), CARE_OUTBOX_TABLE) is False

    @pytest.mark.asyncio
    async def test_no_saved_revision_cannot_be_approved(self) -> None:
        """A raw AI draft has NO working revision: approval is blocked, so the
        draft snapshot itself can never be issued (revision-freeze)."""
        care_conn = _connection(
            [
                _FakeResult(row=_rx_row(source="ai_draft", draft_snapshot=AI_SNAPSHOT)),
                _FakeResult(row=_case_row()),
                _FakeResult(rows=[]),
            ]
        )
        facade = _care_facade(care_conn)

        with pytest.raises(CareValidationError, match="no saved revision"):
            await facade.approve_prescription(
                case_id=1, rx_id=1, doctor_id=42, verification_declaration=True
            )

        assert _insert_tables(_statements(care_conn)) == []

    @pytest.mark.asyncio
    async def test_approval_freezes_the_saved_revision_not_the_snapshot(self) -> None:
        """The issued artifact is the doctor's saved ``care_rx_items`` revision
        - approval reads items and never writes them (freeze), and the frozen
        items differ from the AI snapshot when the revision was edited."""
        care_conn = _connection(
            [
                _FakeResult(row=_rx_row(source="ai_draft", draft_snapshot=AI_SNAPSHOT)),
                _FakeResult(row=_case_row()),
                _FakeResult(
                    rows=[_rx_item_row(name="Edited-Drug", dose="200mg", duration="7 days")]
                ),
                _FakeResult(),
                _FakeResult(),
                _FakeResult(),
                _FakeResult(),
            ]
        )
        facade = _care_facade(care_conn)

        result = await facade.approve_prescription(
            case_id=1, rx_id=1, doctor_id=42, verification_declaration=True
        )

        # The frozen view carries the saved revision.
        assert [item.name for item in result.items] == ["Edited-Drug"]
        assert result.issued_at is not None
        assert result.attributed_doctor == 42

        # Revision-freeze is structural: approval only SELECTed the items
        # (visible in ``result.items``) and never wrote ``care_rx_items``.
        stmts = _statements(care_conn)
        assert care_rx_items.name not in _insert_tables(stmts)

        # The audit row records the edit against the immutable snapshot.
        approval_params = _stmt_params(stmts, care_rx_approvals.name)
        assert approval_params is not None
        assert approval_params["decision"] == "approved"
        assert approval_params["edited_yn"] is True
        assert approval_params["verification_declaration"] is True

    @pytest.mark.asyncio
    async def test_unchanged_revision_is_audited_as_never_edited(self) -> None:
        """A revision that matches the snapshot audits as ``edited_yn=False`` -
        the doctor's sign-off still holds because the declaration was made."""
        care_conn = _connection(
            [
                _FakeResult(
                    row=_rx_row(
                        status="doctor_reviewed",
                        source="ai_draft",
                        draft_snapshot=AI_SNAPSHOT,
                    )
                ),
                _FakeResult(row=_case_row()),
                _FakeResult(
                    rows=[_rx_item_row(name="mock medication", dose="1 tablet", duration="5 days")]
                ),
                _FakeResult(),
                _FakeResult(),
                _FakeResult(),
                _FakeResult(),
            ]
        )
        facade = _care_facade(care_conn)

        await facade.approve_prescription(
            case_id=1, rx_id=1, doctor_id=42, verification_declaration=True
        )

        approval_params = _stmt_params(_statements(care_conn), care_rx_approvals.name)
        assert approval_params is not None
        assert approval_params["edited_yn"] is False
        assert approval_params["verification_declaration"] is True
