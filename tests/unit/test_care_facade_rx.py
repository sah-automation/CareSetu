"""PHASE-8 T05: prescription workflow facade (ticket #421, #426, FEAT-009).

Drives ``PrescriptionFacade`` through a mocked engine at the
facade-with-fakes seam, mirroring ``test_care_facade_consult.py``. Pins the
prescription workflow contract (brief acceptance criteria):

- ``request_rx_draft`` delegates to the intake AI gateway and returns a typed
  draft (criterion 1 - the seam lives in the intake facade; exercised here via
  the AI-draft path).
- AI drafts store an immutable ``draft_snapshot`` with NO working revision,
  and the drafting cap blocks the 3rd AI draft while manual authoring stays
  open (criterion 2).
- History reads for drafting go through ``HealthFacade.read_consented_history``
  (criterion 3, NFR-SEC-006 fail-closed - raising ``RuntimeError`` when the
  health facade is not configured).
- ``save_rx_revision`` replaces the working ``care_rx_items`` and rejects a
  stale revision (criterion 4).
- ``approve_prescription`` gates on the verification declaration behind the
  replaceable seam, freezes the revision, derives ``edited_yn`` against the
  snapshot, and blocks approval with no saved revision (criterion 5).
- ``reject_prescription`` requires a reason and never touches the case stage
  (criterion 6).
- ``get_approved_prescription`` reads only issued prescriptions (criterion 7).
- Every state change writes its ``care_outbox`` event in the SAME transaction
  as the domain write (criterion 8, ADR-0002).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import ClauseElement
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.sql.dml import Insert

from bus.events import (
    EVENT_PRESCRIPTION_APPROVED,
    EVENT_PRESCRIPTION_DRAFT_CREATED,
    EVENT_PRESCRIPTION_ISSUED,
    EVENT_PRESCRIPTION_REJECTED,
    EVENT_PRESCRIPTION_REVIEWED,
)
from modules.care.care_models import PrescriptionDetailView, RxItemInput
from modules.care.domain.exceptions import (
    CareNotFoundError,
    CareValidationError,
    IllegalPrescriptionTransitionError,
)
from modules.care.outbox import CARE_OUTBOX_TABLE
from modules.care.rx_facade import RX_DRAFT_HISTORY_SCOPE, PrescriptionFacade
from modules.care.schema.models import (
    care_cases,
    care_prescriptions,
    care_rx_approvals,
    care_rx_items,
)
from modules.health.facade import RecordEntryView, RecordTimeline
from modules.intake.adapters.ai_provider_mock import MockAiProvider
from modules.intake.facade import IntakeFacade

NOW = datetime.now(UTC)

AI_SNAPSHOT = {"rx_items": [{"name": "mock medication", "dose": "1 tablet", "duration": "5 days"}]}


# ---------------------------------------------------------------------------
# Fake-result helpers (mirrors test_care_facade_consult.py)
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


def _intake_facade(connection: AsyncMock, gateway: MockAiProvider | None = None) -> IntakeFacade:
    return IntakeFacade(engine=_engine(connection), ai_gateway=gateway)


class _FakeHealthFacade:
    """Never performs a raw read - it IS the consented path the facade calls.

    Records the consent-gated read contract so tests can pin the fail-closed
    (NFR-SEC-006) call: patient/scope/counterparty, never a raw read.
    """

    def __init__(self, timeline: RecordTimeline) -> None:
        self._timeline = timeline
        self.calls: list[dict[str, Any]] = []

    async def read_consented_history(
        self,
        patient_id: int,
        scope: str,
        counterparty_type: str,
        counterparty_id: int,
        settings: Any = None,
    ) -> RecordTimeline:
        self.calls.append(
            {
                "patient_id": patient_id,
                "scope": scope,
                "counterparty_type": counterparty_type,
                "counterparty_id": counterparty_id,
            }
        )
        return self._timeline


def _care_facade(
    case_connection: AsyncMock,
    intake_facade: IntakeFacade,
    health_facade: _FakeHealthFacade | None = None,
) -> PrescriptionFacade:
    return PrescriptionFacade(
        engine=_engine(case_connection),
        intake_facade=intake_facade,
        health_facade=health_facade,
    )


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


def _insert_params(statements: list[ClauseElement], table_name: str) -> list[dict[str, Any]]:
    """Compiled bind parameters of every INSERT touching ``table_name``."""
    return [
        dict(stmt.compile().params)
        for stmt in statements
        if isinstance(stmt, Insert) and stmt.table.name == table_name
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
    status: str = "draft",
    source: str = "ai_draft",
    attempt_no: int = 1,
    draft_snapshot: dict[str, Any] | None = None,
    issued_at: Any = None,
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


def _doctor_input_row(*, input_id: int = 88, case_id: int = 1) -> object:
    return SimpleNamespace(id=input_id, case_id=case_id)


def _pre_summary_row(*, pre_summary_id: int = 5, intake_id: int = 1) -> object:
    return SimpleNamespace(id=pre_summary_id, intake_id=intake_id)


def _intake_row(*, intake_id: int = 1, language: str = "en") -> object:
    return SimpleNamespace(id=intake_id, language=language)


def _timeline(*, entry_types: list[str] | None = None) -> RecordTimeline:
    entries: list[RecordEntryView] = []
    for entry_type in entry_types or []:
        entries.append(
            RecordEntryView(
                entry_id=len(entries) + 1,
                entry_type=entry_type,
                payload={"med": "paracetamol"},
                occurred_at=NOW,
                created_at=NOW,
            )
        )
    return RecordTimeline(record_id=1, patient_id=7, created_at=NOW, entries=entries)


# ========================================================================
# create_rx_draft - AI draft
# ========================================================================


@pytest.mark.asyncio
async def test_create_ai_draft_stores_immutable_snapshot_and_publishes() -> None:
    care_conn = _connection(
        [
            _FakeResult(row=_case_row()),
            _FakeResult(row=None),
            _FakeResult(row=_doctor_input_row()),
            _FakeResult(scalar=201),
            _FakeResult(),
            _FakeResult(),
        ]
    )
    intake_conn = _connection([_FakeResult(row=_pre_summary_row()), _FakeResult(row=_intake_row())])
    gateway = MockAiProvider()
    health = _FakeHealthFacade(_timeline(entry_types=["rx"]))
    facade = _care_facade(care_conn, _intake_facade(intake_conn, gateway), health)

    result = await facade.create_rx_draft(case_id=1, doctor_id=42, source="ai_draft")

    assert isinstance(result, PrescriptionDetailView)
    assert result.prescription_id == 201
    assert result.case_id == 1
    assert result.status == "draft"
    assert result.source == "ai_draft"
    assert result.attempt_no == 1
    assert result.items == []
    assert result.draft_snapshot == AI_SNAPSHOT

    rx_params = _stmt_params(_statements(care_conn), care_prescriptions.name)
    assert rx_params is not None
    assert rx_params["status"] == "draft"
    assert rx_params["source"] == "ai_draft"
    assert rx_params["attempt_no"] == 1
    assert rx_params["draft_snapshot"] == AI_SNAPSHOT

    outbox_params = _stmt_params(_statements(care_conn), CARE_OUTBOX_TABLE)
    assert outbox_params is not None
    assert outbox_params["event_type"] == EVENT_PRESCRIPTION_DRAFT_CREATED
    assert outbox_params["payload"]["prescription_id"] == 201
    assert outbox_params["payload"]["attempt_no"] == 1


@pytest.mark.asyncio
async def test_create_ai_draft_reads_history_only_via_consented_path() -> None:
    care_conn = _connection(
        [
            _FakeResult(row=_case_row()),
            _FakeResult(row=None),
            _FakeResult(row=_doctor_input_row()),
            _FakeResult(scalar=201),
            _FakeResult(),
            _FakeResult(),
        ]
    )
    intake_conn = _connection([_FakeResult(row=_pre_summary_row()), _FakeResult(row=_intake_row())])
    gateway = MockAiProvider()
    health = _FakeHealthFacade(_timeline(entry_types=["rx", "prescription"]))
    facade = _care_facade(care_conn, _intake_facade(intake_conn, gateway), health)

    await facade.create_rx_draft(case_id=1, doctor_id=42, source="ai_draft")

    assert health.calls == [
        {
            "patient_id": 7,
            "scope": RX_DRAFT_HISTORY_SCOPE,
            "counterparty_type": "doctor",
            "counterparty_id": 42,
        }
    ]
    request = gateway.calls[0]
    expected = "\n".join(
        [
            f"rx {NOW.date().isoformat()}: "
            f"{json.dumps({'med': 'paracetamol'}, ensure_ascii=False)}",
            f"prescription {NOW.date().isoformat()}: "
            f"{json.dumps({'med': 'paracetamol'}, ensure_ascii=False)}",
        ]
    )
    assert request.patient_history_summary == expected


@pytest.mark.asyncio
async def test_create_ai_draft_fails_closed_without_health_facade() -> None:
    care_conn = _connection([_FakeResult(row=_case_row()), _FakeResult(row=None)])
    intake_conn = _connection([])
    facade = _care_facade(care_conn, _intake_facade(intake_conn))

    with pytest.raises(RuntimeError, match="HealthFacade not configured"):
        await facade.create_rx_draft(case_id=1, doctor_id=42, source="ai_draft")


@pytest.mark.asyncio
async def test_create_ai_draft_regenerate_increments_attempt_no() -> None:
    care_conn = _connection(
        [
            _FakeResult(row=_case_row()),
            _FakeResult(row=_rx_row(status="draft", attempt_no=1)),
            _FakeResult(scalar=0),
            _FakeResult(row=_doctor_input_row()),
            _FakeResult(),
            _FakeResult(),
            _FakeResult(),
        ]
    )
    intake_conn = _connection([_FakeResult(row=_pre_summary_row()), _FakeResult(row=_intake_row())])
    facade = _care_facade(
        care_conn,
        _intake_facade(intake_conn, MockAiProvider()),
        _FakeHealthFacade(_timeline()),
    )

    result = await facade.create_rx_draft(case_id=1, doctor_id=42, source="ai_draft")

    assert result.prescription_id == 1
    assert result.attempt_no == 2
    rx_params = _stmt_params(_statements(care_conn), care_prescriptions.name)
    assert rx_params is not None
    assert rx_params["attempt_no"] == 2

    delete_params = _stmt_params(_statements(care_conn), care_rx_items.name)
    assert delete_params is not None


@pytest.mark.asyncio
async def test_create_ai_draft_clears_prior_working_revision() -> None:
    care_conn = _connection(
        [
            _FakeResult(row=_case_row()),
            _FakeResult(row=_rx_row()),
            _FakeResult(scalar=1),
            _FakeResult(row=_doctor_input_row()),
            _FakeResult(),
            _FakeResult(),
            _FakeResult(),
        ]
    )
    intake_conn = _connection([_FakeResult(row=_pre_summary_row()), _FakeResult(row=_intake_row())])
    facade = _care_facade(
        care_conn,
        _intake_facade(intake_conn, MockAiProvider()),
        _FakeHealthFacade(_timeline()),
    )

    result = await facade.create_rx_draft(case_id=1, doctor_id=42, source="ai_draft")

    assert result.items == []


@pytest.mark.asyncio
async def test_create_ai_draft_blocks_third_draft_when_cap_reached() -> None:
    care_conn = _connection(
        [
            _FakeResult(row=_case_row()),
            _FakeResult(row=_rx_row(status="rejected", attempt_no=2)),
            _FakeResult(scalar=2),
        ]
    )
    facade = _care_facade(
        care_conn, _intake_facade(_connection([])), _FakeHealthFacade(_timeline())
    )

    with pytest.raises(IllegalPrescriptionTransitionError, match="drafting cap"):
        await facade.create_rx_draft(case_id=1, doctor_id=42, source="ai_draft")


@pytest.mark.asyncio
async def test_create_ai_draft_rejects_case_without_pre_summary() -> None:
    care_conn = _connection(
        [
            _FakeResult(row=_case_row(pre_summary_id=None)),
            _FakeResult(row=_rx_row()),
            _FakeResult(scalar=0),
        ]
    )
    intake_conn = _connection([])
    facade = _care_facade(care_conn, _intake_facade(intake_conn), _FakeHealthFacade(_timeline()))

    with pytest.raises(CareValidationError, match="no pre-summary"):
        await facade.create_rx_draft(case_id=1, doctor_id=42, source="ai_draft")


@pytest.mark.asyncio
async def test_create_ai_draft_rejects_case_without_doctor_input() -> None:
    care_conn = _connection(
        [
            _FakeResult(row=_case_row()),
            _FakeResult(row=_rx_row()),
            _FakeResult(scalar=0),
            _FakeResult(row=None),
        ]
    )
    intake_conn = _connection([])
    facade = _care_facade(care_conn, _intake_facade(intake_conn), _FakeHealthFacade(_timeline()))

    with pytest.raises(CareValidationError, match="no doctor input"):
        await facade.create_rx_draft(case_id=1, doctor_id=42, source="ai_draft")


# ========================================================================
# create_rx_draft - manual
# ========================================================================


@pytest.mark.asyncio
async def test_create_manual_draft_writes_working_revision_no_snapshot() -> None:
    care_conn = _connection(
        [
            _FakeResult(row=_case_row()),
            _FakeResult(row=None),
            _FakeResult(scalar=202),
            _FakeResult(scalar=101),
            _FakeResult(scalar=102),
            _FakeResult(),
        ]
    )
    facade = _care_facade(care_conn, _intake_facade(_connection([])))

    result = await facade.create_rx_draft(
        case_id=1,
        doctor_id=42,
        source="manual",
        items=[
            RxItemInput(name="Paracetamol", dose="500mg", duration="3 days"),
            RxItemInput(name="Vitamin D", dose=None, duration=None),
        ],
    )

    assert isinstance(result, PrescriptionDetailView)
    assert result.prescription_id == 202
    assert result.status == "draft"
    assert result.source == "manual"
    assert result.attempt_no == 1
    assert result.draft_snapshot == {}
    assert [item.name for item in result.items] == ["Paracetamol", "Vitamin D"]

    item_params = _insert_params(_statements(care_conn), care_rx_items.name)
    assert len(item_params) == 2
    assert item_params[0]["sequence"] == 1
    assert item_params[0]["name"] == "Paracetamol"
    assert item_params[1]["sequence"] == 2
    assert item_params[1]["name"] == "Vitamin D"

    outbox_params = _stmt_params(_statements(care_conn), CARE_OUTBOX_TABLE)
    assert outbox_params is not None
    assert outbox_params["event_type"] == EVENT_PRESCRIPTION_DRAFT_CREATED
    assert outbox_params["payload"]["source"] == "manual"


@pytest.mark.asyncio
async def test_create_manual_draft_stays_open_when_cap_reached() -> None:
    care_conn = _connection(
        [
            _FakeResult(row=_case_row()),
            _FakeResult(row=_rx_row(status="rejected", attempt_no=2)),
            _FakeResult(scalar=2),
            _FakeResult(),
            _FakeResult(scalar=103),
            _FakeResult(),
        ]
    )
    facade = _care_facade(care_conn, _intake_facade(_connection([])))

    result = await facade.create_rx_draft(
        case_id=1,
        doctor_id=42,
        source="manual",
        items=[RxItemInput(name="Paracetamol", dose="500mg", duration="3 days")],
    )

    assert result.status == "draft"
    assert result.source == "manual"
    assert result.attempt_no == 2


@pytest.mark.asyncio
async def test_create_manual_draft_requires_items() -> None:
    care_conn = _connection([_FakeResult(row=_case_row()), _FakeResult(row=None)])
    facade = _care_facade(care_conn, _intake_facade(_connection([])))

    with pytest.raises(CareValidationError, match="at least one rx item"):
        await facade.create_rx_draft(case_id=1, doctor_id=42, source="manual")


@pytest.mark.asyncio
async def test_create_manual_draft_refuses_issued_prescription() -> None:
    care_conn = _connection(
        [
            _FakeResult(row=_case_row()),
            _FakeResult(row=_rx_row(status="issued")),
            _FakeResult(scalar=0),
        ]
    )
    facade = _care_facade(care_conn, _intake_facade(_connection([])))

    with pytest.raises(IllegalPrescriptionTransitionError, match="issued"):
        await facade.create_rx_draft(
            case_id=1,
            doctor_id=42,
            source="manual",
            items=[RxItemInput(name="Paracetamol")],
        )


@pytest.mark.asyncio
async def test_create_rx_draft_rejects_closed_case() -> None:
    care_conn = _connection([_FakeResult(row=_case_row(stage="closed"))])
    facade = _care_facade(care_conn, _intake_facade(_connection([])))

    with pytest.raises(CareValidationError, match="closed"):
        await facade.create_rx_draft(case_id=1, doctor_id=42, source="manual")


@pytest.mark.asyncio
async def test_create_rx_draft_rejects_unowned_case() -> None:
    care_conn = _connection([_FakeResult(row=_case_row(doctor_id=7))])
    facade = _care_facade(care_conn, _intake_facade(_connection([])))

    with pytest.raises(CareNotFoundError):
        await facade.create_rx_draft(case_id=1, doctor_id=42, source="manual")


# ========================================================================
# save_rx_revision
# ========================================================================


@pytest.mark.asyncio
async def test_save_rx_revision_replaces_working_revision_and_publishes() -> None:
    care_conn = _connection(
        [
            _FakeResult(row=_rx_row()),
            _FakeResult(row=_case_row()),
            _FakeResult(),
            _FakeResult(scalar=104),
            _FakeResult(scalar=105),
            _FakeResult(),
            _FakeResult(),
        ]
    )
    facade = _care_facade(care_conn, _intake_facade(_connection([])))

    result = await facade.save_rx_revision(
        case_id=1,
        rx_id=1,
        doctor_id=42,
        rx_items=[
            RxItemInput(name="Paracetamol", dose="500mg", duration="5 days"),
            RxItemInput(name="Amoxicillin", dose=None, duration=None),
        ],
    )

    assert isinstance(result, PrescriptionDetailView)
    assert result.status == "doctor_reviewed"
    assert result.prescription_id == 1
    assert [item.name for item in result.items] == ["Paracetamol", "Amoxicillin"]

    items = _statements(care_conn)
    delete_params = _stmt_params(items, care_rx_items.name)
    assert delete_params is not None
    assert 1 in delete_params.values()
    item_params = _insert_params(items, care_rx_items.name)
    assert len(item_params) == 2
    assert item_params[0]["name"] == "Paracetamol"
    assert item_params[1]["sequence"] == 2

    rx_params = _stmt_params(items, care_prescriptions.name)
    assert rx_params is not None
    assert rx_params["status"] == "doctor_reviewed"

    outbox_params = _stmt_params(items, CARE_OUTBOX_TABLE)
    assert outbox_params is not None
    assert outbox_params["event_type"] == EVENT_PRESCRIPTION_REVIEWED


@pytest.mark.asyncio
async def test_save_rx_revision_rejects_stale_issued_prescription() -> None:
    care_conn = _connection(
        [_FakeResult(row=_rx_row(status="issued")), _FakeResult(row=_case_row())]
    )
    facade = _care_facade(care_conn, _intake_facade(_connection([])))

    with pytest.raises(IllegalPrescriptionTransitionError, match="issued"):
        await facade.save_rx_revision(
            case_id=1,
            rx_id=1,
            doctor_id=42,
            rx_items=[RxItemInput(name="Paracetamol")],
        )

    assert _stmt_params(_statements(care_conn), care_rx_items.name) is None


@pytest.mark.asyncio
async def test_save_rx_revision_rejects_unowned_case() -> None:
    care_conn = _connection([_FakeResult(row=_rx_row()), _FakeResult(row=_case_row(doctor_id=7))])
    facade = _care_facade(care_conn, _intake_facade(_connection([])))

    with pytest.raises(CareNotFoundError):
        await facade.save_rx_revision(
            case_id=1,
            rx_id=1,
            doctor_id=42,
            rx_items=[RxItemInput(name="Paracetamol")],
        )


# ========================================================================
# approve_prescription
# ========================================================================


@pytest.mark.asyncio
async def test_approve_freezes_revision_and_publishes_approved_plus_issued() -> None:
    care_conn = _connection(
        [
            _FakeResult(row=_rx_row(source="ai_draft", draft_snapshot=AI_SNAPSHOT)),
            _FakeResult(row=_case_row()),
            _FakeResult(rows=[_rx_item_row()]),
            _FakeResult(),
            _FakeResult(),
            _FakeResult(),
            _FakeResult(),
        ]
    )
    facade = _care_facade(care_conn, _intake_facade(_connection([])))

    result = await facade.approve_prescription(
        case_id=1, rx_id=1, doctor_id=42, verification_declaration=True
    )

    assert isinstance(result, PrescriptionDetailView)
    assert result.status == "issued"
    assert result.issued_at is not None
    assert result.attributed_doctor == 42

    items = _statements(care_conn)
    rx_params = _stmt_params(items, care_prescriptions.name)
    assert rx_params is not None
    assert rx_params["status"] == "issued"
    assert rx_params["attributed_doctor"] == 42
    assert rx_params["issued_at"] is not None

    approval_params = _stmt_params(items, care_rx_approvals.name)
    assert approval_params is not None
    assert approval_params["decision"] == "approved"
    assert approval_params["doctor_id"] == 42
    assert approval_params["verification_declaration"] is True
    assert approval_params["declared_at"] is not None
    assert approval_params["approved_at"] is not None

    events = [p["event_type"] for p in _insert_params(items, CARE_OUTBOX_TABLE)]
    assert events == [EVENT_PRESCRIPTION_APPROVED, EVENT_PRESCRIPTION_ISSUED]


@pytest.mark.asyncio
async def test_approve_derives_edited_yn_false_when_revision_matches_snapshot() -> None:
    snapshot = {"rx_items": [{"name": "mock medication", "dose": "1 tablet", "duration": "5 days"}]}
    care_conn = _connection(
        [
            _FakeResult(
                row=_rx_row(status="doctor_reviewed", source="ai_draft", draft_snapshot=snapshot)
            ),
            _FakeResult(row=_case_row()),
            _FakeResult(
                rows=[
                    _rx_item_row(
                        name="mock medication",
                        dose="1 tablet",
                        duration="5 days",
                    )
                ]
            ),
            _FakeResult(),
            _FakeResult(),
            _FakeResult(),
            _FakeResult(),
        ]
    )
    facade = _care_facade(care_conn, _intake_facade(_connection([])))

    await facade.approve_prescription(
        case_id=1, rx_id=1, doctor_id=42, verification_declaration=True
    )

    approval_params = _stmt_params(_statements(care_conn), care_rx_approvals.name)
    assert approval_params is not None
    assert approval_params["edited_yn"] is False


@pytest.mark.asyncio
async def test_approve_derives_edited_yn_true_when_revision_differs() -> None:
    care_conn = _connection(
        [
            _FakeResult(row=_rx_row(source="ai_draft", draft_snapshot=AI_SNAPSHOT)),
            _FakeResult(row=_case_row()),
            _FakeResult(rows=[_rx_item_row(name="Edited-Drug", dose="200mg", duration="7 days")]),
            _FakeResult(),
            _FakeResult(),
            _FakeResult(),
            _FakeResult(),
        ]
    )
    facade = _care_facade(care_conn, _intake_facade(_connection([])))

    await facade.approve_prescription(
        case_id=1, rx_id=1, doctor_id=42, verification_declaration=True
    )

    approval_params = _stmt_params(_statements(care_conn), care_rx_approvals.name)
    assert approval_params is not None
    assert approval_params["edited_yn"] is True


@pytest.mark.asyncio
async def test_approve_manual_prescription_is_always_edited() -> None:
    care_conn = _connection(
        [
            _FakeResult(row=_rx_row(source="manual", draft_snapshot={})),
            _FakeResult(row=_case_row()),
            _FakeResult(rows=[_rx_item_row()]),
            _FakeResult(),
            _FakeResult(),
            _FakeResult(),
            _FakeResult(),
        ]
    )
    facade = _care_facade(care_conn, _intake_facade(_connection([])))

    await facade.approve_prescription(
        case_id=1, rx_id=1, doctor_id=42, verification_declaration=True
    )

    approval_params = _stmt_params(_statements(care_conn), care_rx_approvals.name)
    assert approval_params is not None
    assert approval_params["edited_yn"] is True


@pytest.mark.asyncio
async def test_approve_requires_verification_declaration() -> None:
    care_conn = _connection([_FakeResult(row=_rx_row()), _FakeResult(row=_case_row())])
    facade = _care_facade(care_conn, _intake_facade(_connection([])))

    with pytest.raises(CareValidationError, match="verification_declaration"):
        await facade.approve_prescription(
            case_id=1, rx_id=1, doctor_id=42, verification_declaration=False
        )


@pytest.mark.asyncio
async def test_approve_blocks_when_no_saved_revision() -> None:
    care_conn = _connection(
        [
            _FakeResult(row=_rx_row(source="ai_draft", draft_snapshot=AI_SNAPSHOT)),
            _FakeResult(row=_case_row()),
            _FakeResult(rows=[]),
        ]
    )
    facade = _care_facade(care_conn, _intake_facade(_connection([])))

    with pytest.raises(CareValidationError, match="no saved revision"):
        await facade.approve_prescription(
            case_id=1, rx_id=1, doctor_id=42, verification_declaration=True
        )


@pytest.mark.asyncio
async def test_approve_rejects_unowned_case() -> None:
    care_conn = _connection([_FakeResult(row=_rx_row()), _FakeResult(row=_case_row(doctor_id=7))])
    facade = _care_facade(care_conn, _intake_facade(_connection([])))

    with pytest.raises(CareNotFoundError):
        await facade.approve_prescription(
            case_id=1, rx_id=1, doctor_id=42, verification_declaration=True
        )


# ========================================================================
# reject_prescription
# ========================================================================


@pytest.mark.asyncio
async def test_reject_records_reason_and_publishes() -> None:
    care_conn = _connection(
        [
            _FakeResult(row=_rx_row()),
            _FakeResult(row=_case_row()),
            _FakeResult(),
            _FakeResult(),
            _FakeResult(),
            _FakeResult(rows=[_rx_item_row()]),
        ]
    )
    facade = _care_facade(care_conn, _intake_facade(_connection([])))

    result = await facade.reject_prescription(
        case_id=1, rx_id=1, doctor_id=42, reason="wrong_dosage"
    )

    assert isinstance(result, PrescriptionDetailView)
    assert result.status == "rejected"

    items = _statements(care_conn)
    rx_params = _stmt_params(items, care_prescriptions.name)
    assert rx_params is not None
    assert rx_params["status"] == "rejected"

    approval_params = _stmt_params(items, care_rx_approvals.name)
    assert approval_params is not None
    assert approval_params["decision"] == "rejected"
    assert approval_params["doctor_id"] == 42
    assert approval_params["reason"] == "wrong_dosage"

    events = [p["event_type"] for p in _insert_params(items, CARE_OUTBOX_TABLE)]
    assert events == [EVENT_PRESCRIPTION_REJECTED]


@pytest.mark.asyncio
async def test_reject_never_auto_closes_the_case() -> None:
    care_conn = _connection(
        [
            _FakeResult(row=_rx_row()),
            _FakeResult(row=_case_row()),
            _FakeResult(),
            _FakeResult(),
            _FakeResult(),
            _FakeResult(rows=[]),
        ]
    )
    facade = _care_facade(care_conn, _intake_facade(_connection([])))

    await facade.reject_prescription(case_id=1, rx_id=1, doctor_id=42, reason="wrong_dosage")

    write_on_cases = [
        stmt
        for stmt in _statements(care_conn)
        if getattr(stmt, "table", None) is not None and stmt.table.name == care_cases.name
    ]
    assert write_on_cases == []


@pytest.mark.asyncio
async def test_reject_requires_reason() -> None:
    care_conn = _connection([_FakeResult(row=_rx_row()), _FakeResult(row=_case_row())])
    facade = _care_facade(care_conn, _intake_facade(_connection([])))

    with pytest.raises(IllegalPrescriptionTransitionError, match="reason"):
        await facade.reject_prescription(case_id=1, rx_id=1, doctor_id=42, reason="")


@pytest.mark.asyncio
async def test_reject_rejects_unowned_case() -> None:
    care_conn = _connection([_FakeResult(row=_rx_row()), _FakeResult(row=_case_row(doctor_id=7))])
    facade = _care_facade(care_conn, _intake_facade(_connection([])))

    with pytest.raises(CareNotFoundError):
        await facade.reject_prescription(case_id=1, rx_id=1, doctor_id=42, reason="wrong_dosage")


# ========================================================================
# get_approved_prescription
# ========================================================================


@pytest.mark.asyncio
async def test_get_approved_prescription_returns_issued_only() -> None:
    care_conn = _connection(
        [
            _FakeResult(
                row=_rx_row(
                    status="issued",
                    source="ai_draft",
                    draft_snapshot=AI_SNAPSHOT,
                    issued_at=NOW,
                    attributed_doctor=42,
                )
            ),
            _FakeResult(row=_case_row()),
            _FakeResult(rows=[_rx_item_row()]),
        ]
    )
    facade = _care_facade(care_conn, _intake_facade(_connection([])))

    result = await facade.get_approved_prescription(rx_id=1, doctor_id=42)

    assert isinstance(result, PrescriptionDetailView)
    assert result.status == "issued"
    assert result.issued_at == NOW
    assert result.attributed_doctor == 42
    assert len(result.items) == 1

    stmts = _statements(care_conn)
    select_stmt = stmts[0]
    compiled_params = dict(select_stmt.compile().params)
    assert "issued" in compiled_params.values()
    compiled_sql = str(select_stmt.compile())
    assert "issued_at IS NOT NULL" in compiled_sql


@pytest.mark.asyncio
async def test_get_approved_prescription_raises_for_draft() -> None:
    care_conn = _connection([_FakeResult(row=None)])
    facade = _care_facade(care_conn, _intake_facade(_connection([])))

    with pytest.raises(CareNotFoundError, match="approved prescription"):
        await facade.get_approved_prescription(rx_id=1, doctor_id=42)


@pytest.mark.asyncio
async def test_get_approved_prescription_rejects_foreign_doctor() -> None:
    care_conn = _connection(
        [
            _FakeResult(row=_rx_row(status="issued", issued_at=NOW)),
            _FakeResult(row=_case_row(doctor_id=7)),
        ]
    )
    facade = _care_facade(care_conn, _intake_facade(_connection([])))

    with pytest.raises(CareNotFoundError, match="not found for doctor"):
        await facade.get_approved_prescription(rx_id=1, doctor_id=42)


@pytest.mark.asyncio
async def test_get_approved_prescription_rejects_unclaimed_born_case() -> None:
    care_conn = _connection(
        [
            _FakeResult(row=_rx_row(status="issued", issued_at=NOW)),
            _FakeResult(row=_case_row(doctor_id=None)),
        ]
    )
    facade = _care_facade(care_conn, _intake_facade(_connection([])))

    with pytest.raises(CareNotFoundError, match="not found for doctor"):
        await facade.get_approved_prescription(rx_id=1, doctor_id=42)


# ========================================================================
# get_working_prescription
# ========================================================================


@pytest.mark.asyncio
@pytest.mark.parametrize("rx_status", ["draft", "doctor_reviewed", "rejected"])
async def test_get_working_prescription_returns_in_progress_state(rx_status: str) -> None:
    care_conn = _connection(
        [
            _FakeResult(row=_case_row()),
            _FakeResult(row=_rx_row(status=rx_status)),
            _FakeResult(rows=[_rx_item_row()]),
        ]
    )
    facade = _care_facade(care_conn, _intake_facade(_connection([])))

    result = await facade.get_working_prescription(case_id=1, doctor_id=42)

    assert isinstance(result, PrescriptionDetailView)
    assert result.status == rx_status
    assert len(result.items) == 1
    stmts = _statements(care_conn)
    rx_select = stmts[1]
    compiled_params = dict(rx_select.compile().params)
    assert 1 in compiled_params.values()
    assert "care_prescriptions" in str(rx_select.compile())


@pytest.mark.asyncio
async def test_get_working_prescription_draft_without_revision_has_empty_items() -> None:
    care_conn = _connection(
        [
            _FakeResult(row=_case_row()),
            _FakeResult(row=_rx_row(status="draft", draft_snapshot=AI_SNAPSHOT)),
            _FakeResult(rows=[]),
        ]
    )
    facade = _care_facade(care_conn, _intake_facade(_connection([])))

    result = await facade.get_working_prescription(case_id=1, doctor_id=42)

    assert result.status == "draft"
    assert result.items == []
    assert result.draft_snapshot == AI_SNAPSHOT


@pytest.mark.asyncio
async def test_get_working_prescription_raises_when_no_prescription_row() -> None:
    care_conn = _connection(
        [
            _FakeResult(row=_case_row()),
            _FakeResult(row=None),
        ]
    )
    facade = _care_facade(care_conn, _intake_facade(_connection([])))

    with pytest.raises(CareNotFoundError, match="no working prescription for case"):
        await facade.get_working_prescription(case_id=1, doctor_id=42)


@pytest.mark.asyncio
async def test_get_working_prescription_raises_for_issued_prescription() -> None:
    care_conn = _connection(
        [
            _FakeResult(row=_case_row()),
            _FakeResult(row=_rx_row(status="issued", issued_at=NOW, attributed_doctor=42)),
        ]
    )
    facade = _care_facade(care_conn, _intake_facade(_connection([])))

    with pytest.raises(CareNotFoundError, match="no working prescription for case"):
        await facade.get_working_prescription(case_id=1, doctor_id=42)


@pytest.mark.asyncio
async def test_get_working_prescription_rejects_foreign_doctor() -> None:
    care_conn = _connection(
        [
            _FakeResult(row=_case_row(doctor_id=7)),
        ]
    )
    facade = _care_facade(care_conn, _intake_facade(_connection([])))

    with pytest.raises(CareNotFoundError, match="not found for doctor"):
        await facade.get_working_prescription(case_id=1, doctor_id=42)


@pytest.mark.asyncio
async def test_get_working_prescription_rejects_unclaimed_born_case() -> None:
    care_conn = _connection(
        [
            _FakeResult(row=_case_row(doctor_id=None)),
        ]
    )
    facade = _care_facade(care_conn, _intake_facade(_connection([])))

    with pytest.raises(CareNotFoundError, match="not found for doctor"):
        await facade.get_working_prescription(case_id=1, doctor_id=42)
