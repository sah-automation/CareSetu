"""PHASE-8 T07: care outbox events - typed envelopes in one transaction.
(#423, #426, FEAT-008/FEAT-009)

Validates every ``care_outbox`` write the ``CareFacade`` publishes against its
typed Pydantic payload model (coding-standards §3, MOD-006 §4.2 event names):

- Each publishing facade method ("consult_complete", "closed", draft_created
  (AI and manual), reviewed, approved, issued, rejected) writes its event
  through ``write_outbox`` on the SAME connection/transaction as the domain
  write (ADR-0002 §1), and the stored ``payload`` round-trips into the
  matching typed model.
- ``approve_prescription`` publishes ``approved`` then ``issued`` - both in
  one transaction, in order.
- Every stored payload round-trips through ``model_validate`` against its typed
  model; the payload models themselves are PHI-free by construction (only ids
  and lifecycle facts: patient/doctor/case ids, ``edited_yn``, ``source``,
  ``attempt_no``, ``reason``).
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import ClauseElement
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.sql.dml import Insert

from bus.events import (
    EVENT_CASE_CLOSED,
    EVENT_CASE_CONSULT_COMPLETE,
    EVENT_PRESCRIPTION_APPROVED,
    EVENT_PRESCRIPTION_DRAFT_CREATED,
    EVENT_PRESCRIPTION_ISSUED,
    EVENT_PRESCRIPTION_REJECTED,
    EVENT_PRESCRIPTION_REVIEWED,
)
from modules.care.care_models import RxItemInput
from modules.care.domain.events import (
    CaseClosedPayload,
    CaseConsultCompletePayload,
    PrescriptionApprovedPayload,
    PrescriptionDraftCreatedPayload,
    PrescriptionIssuedPayload,
    PrescriptionRejectedPayload,
    PrescriptionReviewedPayload,
)
from modules.care.facade import CareFacade
from modules.care.outbox import CARE_OUTBOX_TABLE
from modules.intake.adapters.ai_provider_mock import MockAiProvider
from modules.intake.facade import IntakeFacade

NOW = datetime.now(UTC)

AI_SNAPSHOT = {"rx_items": [{"name": "mock medication", "dose": "1 tablet", "duration": "5 days"}]}


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


class _FakeHealthFacade:
    """Returns an empty consented timeline for the AI-draft leg."""

    async def read_consented_history(
        self,
        patient_id: int,
        scope: str,
        counterparty_type: str,
        counterparty_id: int,
        settings: object = None,
    ) -> object:
        return SimpleNamespace(entries=[])


def _intake_facade(connection: AsyncMock, gateway: MockAiProvider | None = None) -> IntakeFacade:
    return IntakeFacade(engine=_engine(connection), ai_gateway=gateway)


def _care_facade(
    case_connection: AsyncMock,
    intake_facade: IntakeFacade,
    health_facade: _FakeHealthFacade | None = None,
    engine: AsyncMock | None = None,
) -> CareFacade:
    return CareFacade(
        engine=engine or _engine(case_connection),
        intake_facade=intake_facade,
        health_facade=health_facade,
    )


def _statements(connection: AsyncMock) -> list[ClauseElement]:
    return [
        call.args[0]
        for call in connection.execute.await_args_list
        if isinstance(call.args[0], ClauseElement)
    ]


def _outbox_inserts(statements: list[ClauseElement]) -> list[Insert]:
    return [
        stmt
        for stmt in statements
        if isinstance(stmt, Insert) and stmt.table.name == CARE_OUTBOX_TABLE
    ]


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


def _rx_row(
    *,
    rx_id: int = 1,
    case_id: int = 1,
    status: str = "draft",
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
    rx_id: int = 1,
    sequence: int = 1,
    name: str = "mock medication",
    dose: str | None = "1 tablet",
    duration: str | None = "5 days",
) -> object:
    return SimpleNamespace(
        id=sequence,
        prescription_id=rx_id,
        sequence=sequence,
        name=name,
        dose=dose,
        duration=duration,
    )


def _doctor_input_row(*, input_id: int = 88, case_id: int = 1) -> object:
    return SimpleNamespace(id=input_id, case_id=case_id)


def _pre_summary_row(*, pre_summary_id: int = 5, intake_id: int = 1) -> object:
    return SimpleNamespace(
        id=pre_summary_id,
        intake_id=intake_id,
        structured_fields={"symptoms": ["headache"], "severity": "mild"},
        structuring_confidence=0.82,
        low_confidence=False,
        review_state="final",
        patient_edits=None,
        doctor_corrections=None,
        review_attribution="doctor",
        reviewed_by=42,
        reviewed_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )


def _intake_row(*, intake_id: int = 1, language: str = "en") -> object:
    return SimpleNamespace(id=intake_id, language=language)


def _single_outbox(connection: AsyncMock) -> Insert:
    outboxes = _outbox_inserts(_statements(connection))
    assert len(outboxes) == 1
    return outboxes[0]


class TestCaseConsultCompleteOutbox:
    @pytest.mark.asyncio
    async def test_consult_complete_payload_round_trips_in_one_transaction(self) -> None:
        case_conn = _connection([_FakeResult(row=_case_row()), _FakeResult(), _FakeResult()])
        intake_conn = _connection([_FakeResult(row=_pre_summary_row())])
        engine = _engine(case_conn)
        facade = _care_facade(case_conn, _intake_facade(intake_conn), engine=engine)

        result = await facade.mark_consult_complete(doctor_id=42, case_id=1)

        assert result.stage == "prescription_pending"
        outbox = _single_outbox(case_conn)
        params = outbox.compile().params
        assert params["event_type"] == EVENT_CASE_CONSULT_COMPLETE
        payload = CaseConsultCompletePayload.model_validate(params["payload"])
        assert payload.case_id == 1
        assert payload.patient_id == 7
        assert payload.doctor_id == 42
        assert payload.pre_summary_id == 5
        # One transaction: the update and the outbox write share the connection.
        engine.begin.assert_called_once()


class TestCaseClosedOutbox:
    @pytest.mark.asyncio
    async def test_case_closed_payload_round_trips_in_one_transaction(self) -> None:
        case_conn = _connection(
            [
                _FakeResult(row=_case_row(stage="prescription_pending")),
                _FakeResult(),
                _FakeResult(),
            ]
        )
        engine = _engine(case_conn)
        facade = _care_facade(case_conn, _intake_facade(_connection([])), engine=engine)

        result = await facade.close_case_without_rx(doctor_id=42, case_id=1, close_reason="no_show")

        assert result.stage == "closed"
        outbox = _single_outbox(case_conn)
        params = outbox.compile().params
        assert params["event_type"] == EVENT_CASE_CLOSED
        payload = CaseClosedPayload.model_validate(params["payload"])
        assert payload.case_id == 1
        assert payload.patient_id == 7
        assert payload.doctor_id == 42
        assert payload.close_reason == "no_show"
        # One transaction: the close write and the outbox write share the connection.
        engine.begin.assert_called_once()


class TestDraftCreatedOutbox:
    @pytest.mark.asyncio
    async def test_ai_draft_payload_carries_source_and_attempt(self) -> None:
        care_conn = _connection(
            [
                _FakeResult(row=_case_row(stage="prescription_pending")),
                _FakeResult(row=None),
                _FakeResult(row=_doctor_input_row()),
                _FakeResult(scalar=201),
                _FakeResult(),
                _FakeResult(),
            ]
        )
        intake_conn = _connection(
            [_FakeResult(row=_pre_summary_row()), _FakeResult(row=_intake_row())]
        )
        engine = _engine(care_conn)
        facade = _care_facade(
            care_conn,
            _intake_facade(intake_conn, MockAiProvider()),
            _FakeHealthFacade(),
            engine=engine,
        )

        result = await facade.create_rx_draft(case_id=1, doctor_id=42, source="ai_draft")

        assert result.prescription_id == 201
        params = _single_outbox(care_conn).compile().params
        assert params["event_type"] == EVENT_PRESCRIPTION_DRAFT_CREATED
        payload = PrescriptionDraftCreatedPayload.model_validate(params["payload"])
        assert payload.prescription_id == 201
        assert payload.case_id == 1
        assert payload.patient_id == 7
        assert payload.doctor_id == 42
        assert payload.source == "ai_draft"
        assert payload.attempt_no == 1
        engine.begin.assert_called_once()

    @pytest.mark.asyncio
    async def test_manual_draft_payload_carries_manual_source(self) -> None:
        care_conn = _connection(
            [
                _FakeResult(row=_case_row(stage="prescription_pending")),
                _FakeResult(row=None),
                _FakeResult(scalar=202),
                _FakeResult(scalar=101),
                _FakeResult(),
            ]
        )
        engine = _engine(care_conn)
        facade = _care_facade(care_conn, _intake_facade(_connection([])), engine=engine)

        result = await facade.create_rx_draft(
            case_id=1,
            doctor_id=42,
            source="manual",
            items=[RxItemInput(name="Paracetamol", dose="500mg", duration="3 days")],
        )

        assert result.prescription_id == 202
        params = _single_outbox(care_conn).compile().params
        assert params["event_type"] == EVENT_PRESCRIPTION_DRAFT_CREATED
        payload = PrescriptionDraftCreatedPayload.model_validate(params["payload"])
        assert payload.prescription_id == 202
        assert payload.source == "manual"
        assert payload.doctor_id == 42
        engine.begin.assert_called_once()


class TestReviewedOutbox:
    @pytest.mark.asyncio
    async def test_save_revision_publishes_reviewed_payload(self) -> None:
        care_conn = _connection(
            [
                _FakeResult(row=_rx_row()),
                _FakeResult(row=_case_row(stage="prescription_pending")),
                _FakeResult(),
                _FakeResult(scalar=104),
                _FakeResult(scalar=105),
                _FakeResult(),
                _FakeResult(),
            ]
        )
        engine = _engine(care_conn)
        facade = _care_facade(care_conn, _intake_facade(_connection([])), engine=engine)

        result = await facade.save_rx_revision(
            case_id=1,
            rx_id=1,
            doctor_id=42,
            rx_items=[
                RxItemInput(name="Paracetamol", dose="500mg", duration="5 days"),
                RxItemInput(name="Amoxicillin", dose=None, duration=None),
            ],
        )

        assert result.status == "doctor_reviewed"
        params = _single_outbox(care_conn).compile().params
        assert params["event_type"] == EVENT_PRESCRIPTION_REVIEWED
        payload = PrescriptionReviewedPayload.model_validate(params["payload"])
        assert payload.prescription_id == 1
        assert payload.case_id == 1
        assert payload.patient_id == 7
        assert payload.doctor_id == 42
        engine.begin.assert_called_once()


class TestApprovedAndIssuedOutbox:
    @pytest.mark.asyncio
    async def test_approve_publishes_approved_then_issued_in_one_transaction(self) -> None:
        care_conn = _connection(
            [
                _FakeResult(
                    row=_rx_row(
                        status="doctor_reviewed", source="ai_draft", draft_snapshot=AI_SNAPSHOT
                    )
                ),
                _FakeResult(row=_case_row(stage="prescription_pending")),
                _FakeResult(
                    rows=[_rx_item_row(name="Edited-Drug", dose="200mg", duration="7 days")]
                ),
                _FakeResult(),
                _FakeResult(),
                _FakeResult(),
                _FakeResult(),
            ]
        )
        engine = _engine(care_conn)
        facade = _care_facade(care_conn, _intake_facade(_connection([])), engine=engine)

        result = await facade.approve_prescription(
            case_id=1, rx_id=1, doctor_id=42, verification_declaration=True
        )

        assert result.status == "issued"
        outboxes = _outbox_inserts(_statements(care_conn))
        assert [o.compile().params["event_type"] for o in outboxes] == [
            EVENT_PRESCRIPTION_APPROVED,
            EVENT_PRESCRIPTION_ISSUED,
        ]
        approved = PrescriptionApprovedPayload.model_validate(
            outboxes[0].compile().params["payload"]
        )
        assert approved.prescription_id == 1
        assert approved.case_id == 1
        assert approved.doctor_id == 42
        assert approved.edited_yn is True
        issued = PrescriptionIssuedPayload.model_validate(outboxes[1].compile().params["payload"])
        assert issued.prescription_id == 1
        assert issued.patient_id == 7
        assert issued.doctor_id == 42
        # Both events ride the same single transaction.
        engine.begin.assert_called_once()


class TestRejectedOutbox:
    @pytest.mark.asyncio
    async def test_reject_publishes_rejected_payload_with_reason(self) -> None:
        care_conn = _connection(
            [
                _FakeResult(row=_rx_row()),
                _FakeResult(row=_case_row(stage="prescription_pending")),
                _FakeResult(),
                _FakeResult(),
                _FakeResult(),
                _FakeResult(rows=[_rx_item_row()]),
            ]
        )
        engine = _engine(care_conn)
        facade = _care_facade(care_conn, _intake_facade(_connection([])), engine=engine)

        result = await facade.reject_prescription(
            case_id=1, rx_id=1, doctor_id=42, reason="wrong_dosage"
        )

        assert result.status == "rejected"
        params = _single_outbox(care_conn).compile().params
        assert params["event_type"] == EVENT_PRESCRIPTION_REJECTED
        payload = PrescriptionRejectedPayload.model_validate(params["payload"])
        assert payload.prescription_id == 1
        assert payload.patient_id == 7
        assert payload.doctor_id == 42
        assert payload.reason == "wrong_dosage"
        engine.begin.assert_called_once()
