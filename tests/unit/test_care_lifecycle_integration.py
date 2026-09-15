"""PHASE-8 T07: full lifecycle integration walks across the care facade
(#423, #426, FEAT-008/FEAT-009).

Drives the consultation + prescription halves of ``CareFacade`` as CHAINED
walks - each step runs the real facade method against a fresh faked engine,
carrying the case/prescription state forward by hand exactly as the DB would.
The different calls in each chain never touch the same transaction, matching
the single-request seam of the routes; what the chain proves is the end-to-end
story (CONTEXT.md glossary: ``revision-freeze approval``, ``drafting cap``,
``close-without-prescription``, ``edited_yn``):

- **Happy path:** finalized pre-summary -> consult complete ->
  AI draft -> doctor edits (save revision) -> approve with declaration ->
  issued, and the read-back e-prescription is EXACTLY the frozen revision.
- **Rejection path:** draft -> reject (reason) -> fresh AI draft (attempt 2)
  -> edit -> approve -> issued; the case stage is never touched by a
  rejection.
- **Close-without-RX:** the case machine chains its terminal close from
  PrescriptionPending only (never mid-handshake, review-close #429), reason
  carried and Closed terminal, and the facade refuses every mutating call on
  a closed case with no writes.
- **Drafting cap:** two rejects -> the 3rd AI draft is blocked while manual
  authoring stays open.
- **edited_yn:** an unchanged revision audits as never-edited; an edited one
  audits as edited - both through the real create -> save -> approve chain.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import ClauseElement
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.sql.dml import Insert

from bus.events import (
    EVENT_CASE_CLOSED,
    EVENT_CASE_CONSULT_COMPLETE,
    EVENT_PRESCRIPTION_APPROVED,
    EVENT_PRESCRIPTION_ISSUED,
    EVENT_PRESCRIPTION_REJECTED,
)
from modules.care.care_models import RxItemInput
from modules.care.domain.events import CaseClosedPayload, case_closed_envelope
from modules.care.domain.exceptions import (
    CareValidationError,
    IllegalCareTransitionError,
    IllegalPrescriptionTransitionError,
)
from modules.care.domain.state_machine import (
    PRE_SUMMARY,
    CaseAction,
    CaseStage,
)
from modules.care.domain.state_machine import (
    transition as case_transition,
)
from modules.care.facade import CareFacade
from modules.care.outbox import CARE_OUTBOX_TABLE
from modules.care.schema.models import care_cases
from modules.health.facade import RecordEntryView, RecordTimeline
from modules.intake.adapters.ai_provider_mock import MockAiProvider
from modules.intake.facade import IntakeFacade

NOW = datetime.now(UTC)

AI_SNAPSHOT = {"rx_items": [{"name": "mock medication", "dose": "1 tablet", "duration": "5 days"}]}

REVISED_ITEMS = [
    RxItemInput(name="Para-500", dose="500mg", duration="3 days"),
    RxItemInput(name="Amoxicillin", dose="250mg", duration="7 days"),
]
REVISED_NAMES = ["Para-500", "Amoxicillin"]


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
    """Never performs a raw read - the consented path for the AI-draft leg."""

    async def read_consented_history(
        self,
        patient_id: int,
        scope: str,
        counterparty_type: str,
        counterparty_id: int,
        settings: Any = None,
    ) -> RecordTimeline:
        return _timeline(entry_types=["rx"])


def _intake_facade(connection: AsyncMock, gateway: MockAiProvider | None = None) -> IntakeFacade:
    return IntakeFacade(engine=_engine(connection), ai_gateway=gateway)


def _care_facade(case_connection: AsyncMock, intake_facade: IntakeFacade) -> CareFacade:
    return CareFacade(
        engine=_engine(case_connection),
        intake_facade=intake_facade,
        health_facade=_FakeHealthFacade(),
    )


def _statements(connection: AsyncMock) -> list[ClauseElement]:
    return [
        call.args[0]
        for call in connection.execute.await_args_list
        if isinstance(call.args[0], ClauseElement)
    ]


def _stmt_params(statements: list[ClauseElement], table_name: str) -> dict[str, Any] | None:
    for stmt in statements:
        table = getattr(stmt, "table", None)
        if table is not None and table.name == table_name:
            return dict(stmt.compile().params)
    return None


def _insert_params(statements: list[ClauseElement], table_name: str) -> list[dict[str, Any]]:
    return [
        dict(stmt.compile().params)
        for stmt in statements
        if isinstance(stmt, Insert) and stmt.table.name == table_name
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


def _rx_item_row(item_id: int, name: str, *, sequence: int | None = None) -> object:
    dose = "500mg" if name == "Para-500" else ("250mg" if name == "Amoxicillin" else "1 tablet")
    return SimpleNamespace(
        id=item_id,
        prescription_id=1,
        sequence=sequence if sequence is not None else item_id,
        name=name,
        dose=dose,
        duration="3 days",
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


def _timeline(*, entry_types: list[str] | None = None) -> RecordTimeline:
    entry_types = entry_types or []
    entries = [
        RecordEntryView(
            entry_id=idx + 1,
            entry_type=entry_type,
            payload={"med": "paracetamol"},
            occurred_at=NOW,
            created_at=NOW,
        )
        for idx, entry_type in enumerate(entry_types)
    ]
    return RecordTimeline(record_id=1, patient_id=7, created_at=NOW, entries=entries)


def _revised_item_rows() -> list[object]:
    return [_rx_item_row(104, "Para-500"), _rx_item_row(105, "Amoxicillin")]


class TestHappyPath:
    """Finalized pre-summary -> consult complete -> AI draft -> edit -> approve -> issued."""

    @pytest.mark.asyncio
    async def test_full_lifecycle_lands_issued_and_reads_back_the_frozen_revision(self) -> None:
        # Step 1: consult completes, moving the case to PrescriptionPending.
        consult_conn = _connection([_FakeResult(row=_case_row()), _FakeResult(), _FakeResult()])
        consult = await _care_facade(
            consult_conn, _intake_facade(_connection([_FakeResult(row=_pre_summary_row())]))
        ).mark_consult_complete(doctor_id=42, case_id=1)
        assert consult.stage == "prescription_pending"
        assert _stmt_params(_statements(consult_conn), CARE_OUTBOX_TABLE)["event_type"] == (
            EVENT_CASE_CONSULT_COMPLETE
        )

        # Step 2: a fresh AI draft (attempt 1, immutable snapshot, no revision).
        draft_conn = _connection(
            [
                _FakeResult(row=_case_row(stage="prescription_pending")),
                _FakeResult(row=None),
                _FakeResult(row=_doctor_input_row()),
                _FakeResult(scalar=201),
                _FakeResult(),
                _FakeResult(),
            ]
        )
        draft = await _care_facade(
            draft_conn,
            _intake_facade(
                _connection([_FakeResult(row=_pre_summary_row()), _FakeResult(row=_intake_row())]),
                MockAiProvider(),
            ),
        ).create_rx_draft(case_id=1, doctor_id=42, source="ai_draft")
        assert draft.status == "draft"
        assert draft.attempt_no == 1
        assert draft.items == []
        assert draft.draft_snapshot == AI_SNAPSHOT

        # Step 3: the doctor edits and saves the working revision.
        review_conn = _connection(
            [
                _FakeResult(row=_rx_row(draft_snapshot=AI_SNAPSHOT)),
                _FakeResult(row=_case_row(stage="prescription_pending")),
                _FakeResult(),
                _FakeResult(scalar=104),
                _FakeResult(scalar=105),
                _FakeResult(),
                _FakeResult(),
            ]
        )
        reviewed = await _care_facade(
            review_conn, _intake_facade(_connection([]))
        ).save_rx_revision(case_id=1, rx_id=1, doctor_id=42, rx_items=REVISED_ITEMS)
        assert reviewed.status == "doctor_reviewed"

        # Step 4: declared approval freezes the revision and issues it.
        approve_conn = _connection(
            [
                _FakeResult(row=_rx_row(status="doctor_reviewed", draft_snapshot=AI_SNAPSHOT)),
                _FakeResult(row=_case_row(stage="prescription_pending")),
                _FakeResult(rows=_revised_item_rows()),
                _FakeResult(),
                _FakeResult(),
                _FakeResult(),
                _FakeResult(),
            ]
        )
        issued = await _care_facade(
            approve_conn, _intake_facade(_connection([]))
        ).approve_prescription(case_id=1, rx_id=1, doctor_id=42, verification_declaration=True)
        assert issued.status == "issued"
        assert issued.attributed_doctor == 42
        assert issued.issued_at is not None
        assert [item.name for item in issued.items] == REVISED_NAMES
        approval = _stmt_params(_statements(approve_conn), "care_rx_approvals")
        assert approval["edited_yn"] is True
        assert [
            p["event_type"] for p in _insert_params(_statements(approve_conn), CARE_OUTBOX_TABLE)
        ] == [
            EVENT_PRESCRIPTION_APPROVED,
            EVENT_PRESCRIPTION_ISSUED,
        ]

        # Step 5: the read-back e-prescription is exactly the frozen revision,
        # never the raw AI snapshot.
        read_conn = _connection(
            [
                _FakeResult(
                    row=_rx_row(
                        status="issued",
                        draft_snapshot=AI_SNAPSHOT,
                        issued_at=NOW,
                        attributed_doctor=42,
                    )
                ),
                _FakeResult(row=_case_row()),
                _FakeResult(rows=_revised_item_rows()),
            ]
        )
        artifact = await _care_facade(
            read_conn, _intake_facade(_connection([]))
        ).get_approved_prescription(rx_id=1, doctor_id=42)
        assert artifact.status == "issued"
        assert [item.name for item in artifact.items] == REVISED_NAMES
        snapshot_names = [item["name"] for item in AI_SNAPSHOT["rx_items"]]
        assert snapshot_names != REVISED_NAMES


class TestRejectionPath:
    """Draft -> reject -> fresh AI draft -> edit -> approve -> issued."""

    @pytest.mark.asyncio
    async def test_reject_retry_lands_issued_without_touching_the_case_stage(self) -> None:
        # Step 1: first AI draft.
        draft_conn = _connection(
            [
                _FakeResult(row=_case_row(stage="prescription_pending")),
                _FakeResult(row=None),
                _FakeResult(row=_doctor_input_row()),
                _FakeResult(scalar=201),
                _FakeResult(),
                _FakeResult(),
            ]
        )
        draft = await _care_facade(
            draft_conn,
            _intake_facade(
                _connection([_FakeResult(row=_pre_summary_row()), _FakeResult(row=_intake_row())]),
                MockAiProvider(),
            ),
        ).create_rx_draft(case_id=1, doctor_id=42, source="ai_draft")
        assert draft.attempt_no == 1

        # Step 2: reject with a reason; the case stage is untouched.
        reject_conn = _connection(
            [
                _FakeResult(row=_rx_row(draft_snapshot=AI_SNAPSHOT)),
                _FakeResult(row=_case_row(stage="prescription_pending")),
                _FakeResult(),
                _FakeResult(),
                _FakeResult(),
                _FakeResult(rows=[]),
            ]
        )
        rejected = await _care_facade(
            reject_conn, _intake_facade(_connection([]))
        ).reject_prescription(case_id=1, rx_id=1, doctor_id=42, reason="wrong_dosage")
        assert rejected.status == "rejected"
        assert _stmt_params(_statements(reject_conn), care_cases.name) is None
        assert _insert_params(_statements(reject_conn), CARE_OUTBOX_TABLE)[0]["event_type"] == (
            EVENT_PRESCRIPTION_REJECTED
        )

        # Step 3: retry redrafts at attempt 2 (cap budget still open at 1).
        redraft_conn = _connection(
            [
                _FakeResult(row=_case_row(stage="prescription_pending")),
                _FakeResult(
                    row=_rx_row(status="rejected", attempt_no=1, draft_snapshot=AI_SNAPSHOT)
                ),
                _FakeResult(scalar=1),
                _FakeResult(row=_doctor_input_row()),
                _FakeResult(),
                _FakeResult(),
                _FakeResult(),
            ]
        )
        redraft = await _care_facade(
            redraft_conn,
            _intake_facade(
                _connection([_FakeResult(row=_pre_summary_row()), _FakeResult(row=_intake_row())]),
                MockAiProvider(),
            ),
        ).create_rx_draft(case_id=1, doctor_id=42, source="ai_draft")
        assert redraft.attempt_no == 2

        # Step 4: doctor edits and saves the working revision (status is back
        # to ``draft`` after the retry redrafted it).
        review_conn = _connection(
            [
                _FakeResult(row=_rx_row(status="draft", attempt_no=2, draft_snapshot=AI_SNAPSHOT)),
                _FakeResult(row=_case_row(stage="prescription_pending")),
                _FakeResult(),
                _FakeResult(scalar=104),
                _FakeResult(scalar=105),
                _FakeResult(),
                _FakeResult(),
            ]
        )
        reviewed = await _care_facade(
            review_conn, _intake_facade(_connection([]))
        ).save_rx_revision(case_id=1, rx_id=1, doctor_id=42, rx_items=REVISED_ITEMS)
        assert reviewed.status == "doctor_reviewed"

        # Step 5: declared approval issues.
        approve_conn = _connection(
            [
                _FakeResult(
                    row=_rx_row(status="doctor_reviewed", attempt_no=2, draft_snapshot=AI_SNAPSHOT)
                ),
                _FakeResult(row=_case_row(stage="prescription_pending")),
                _FakeResult(rows=_revised_item_rows()),
                _FakeResult(),
                _FakeResult(),
                _FakeResult(),
                _FakeResult(),
            ]
        )
        issued = await _care_facade(
            approve_conn, _intake_facade(_connection([]))
        ).approve_prescription(case_id=1, rx_id=1, doctor_id=42, verification_declaration=True)
        assert issued.status == "issued"
        # The case is STILL open after the rejection - it must not auto-close.
        assert _stmt_params(_statements(approve_conn), care_cases.name) is None


class TestCloseWithoutRx:
    """The terminal close-with-prescription-never-issued path."""

    def test_machine_closes_from_prescription_pending_only_and_is_terminal(self) -> None:
        # Close is refused from PreSummary even with a valid reason: the case
        # is never closed mid-handshake (review-close #429).
        with pytest.raises(IllegalCareTransitionError, match="pre_summary"):
            case_transition(
                PRE_SUMMARY, CaseAction.CLOSE_WITHOUT_RX, close_reason="patient_withdrew"
            )

        # PreSummary -> PrescriptionPending (consult complete) -> closed,
        # carrying the reason.
        pending = case_transition(
            PRE_SUMMARY, CaseAction.MARK_CONSULT_COMPLETE, pre_summary_finalized=True
        )
        assert pending.stage is CaseStage.PRESCRIPTION_PENDING
        closed_from_pending = case_transition(
            pending, CaseAction.CLOSE_WITHOUT_RX, close_reason="duplicate_visit"
        )
        assert closed_from_pending.stage is CaseStage.CLOSED
        assert closed_from_pending.close_reason == "duplicate_visit"

        # Closed is terminal for every action.
        with pytest.raises(IllegalCareTransitionError, match="closed"):
            case_transition(
                closed_from_pending, CaseAction.MARK_CONSULT_COMPLETE, pre_summary_finalized=True
            )
        with pytest.raises(IllegalCareTransitionError, match="closed"):
            case_transition(closed_from_pending, CaseAction.CLOSE_WITHOUT_RX, close_reason="again")

    @pytest.mark.asyncio
    async def test_facade_refuses_every_mutating_call_on_a_closed_case(self) -> None:
        """Once the case closes, the whole prescription workflow is refused."""
        # A new prescription draft on a closed case.
        with pytest.raises(CareValidationError, match="closed"):
            await _care_facade(
                _connection([_FakeResult(row=_case_row(stage="closed"))]),
                _intake_facade(_connection([])),
            ).create_rx_draft(
                case_id=1,
                doctor_id=42,
                source="manual",
                items=[RxItemInput(name="Paracetamol")],
            )

        # A new doctor input on a closed case.
        with pytest.raises(CareValidationError, match="closed"):
            await _care_facade(
                _connection([_FakeResult(row=_case_row(stage="closed"))]),
                _intake_facade(_connection([])),
            ).submit_doctor_input(
                doctor_id=42,
                case_id=1,
                input_type="voice",
                media_ref="rx_input/a.webm",
            )

        # The consult-complete milestone is illegal once the case has closed.
        with pytest.raises(IllegalCareTransitionError, match="closed"):
            await _care_facade(
                _connection([_FakeResult(row=_case_row(stage="closed"))]),
                _intake_facade(_connection([_FakeResult(row=_pre_summary_row())])),
            ).mark_consult_complete(doctor_id=42, case_id=1)

    def test_case_closed_envelope_round_trips_into_the_typed_payload(self) -> None:
        """``case.closed`` is published by ``close_case_without_rx`` (review-close #429).
        Spec ref #426, FEAT-008.

        Its event name and payload must round-trip into ``CaseClosedPayload``
        with only ids and a PHI-free close reason - the payload shape the
        facade's same-transaction outbox write stores.
        """
        envelope = case_closed_envelope(
            case_id=1, patient_id=7, doctor_id=42, close_reason="patient_withdrew"
        )
        assert envelope.event_type == EVENT_CASE_CLOSED
        payload = CaseClosedPayload.model_validate(envelope.payload.model_dump())
        assert payload.case_id == 1
        assert payload.patient_id == 7
        assert payload.doctor_id == 42
        assert payload.close_reason == "patient_withdrew"


class TestDraftingCap:
    """Two rejects -> the 3rd AI draft is blocked; manual authoring stays open."""

    @pytest.mark.asyncio
    async def test_cap_blocks_third_ai_draft_but_manual_stays_open(self) -> None:
        async def _reject_step(status: str = "draft", attempt_no: int = 1) -> None:
            reject_conn = _connection(
                [
                    _FakeResult(
                        row=_rx_row(
                            status=status, attempt_no=attempt_no, draft_snapshot=AI_SNAPSHOT
                        )
                    ),
                    _FakeResult(row=_case_row(stage="prescription_pending")),
                    _FakeResult(),
                    _FakeResult(),
                    _FakeResult(),
                    _FakeResult(rows=[]),
                ]
            )
            await _care_facade(reject_conn, _intake_facade(_connection([]))).reject_prescription(
                case_id=1, rx_id=1, doctor_id=42, reason="wrong_dosage"
            )

        # Draft 1 -> reject (1 rejection consumed).
        await _reject_step("draft", 1)

        # Redraft (attempt 2) -> reject that fresh second draft (cap now 2).
        await _reject_step("draft", 2)

        # The 3rd AI draft is blocked by the drafting cap.
        cap_conn = _connection(
            [
                _FakeResult(row=_case_row(stage="prescription_pending")),
                _FakeResult(
                    row=_rx_row(status="rejected", attempt_no=2, draft_snapshot=AI_SNAPSHOT)
                ),
                _FakeResult(scalar=2),
            ]
        )
        with pytest.raises(IllegalPrescriptionTransitionError, match="drafting cap"):
            await _care_facade(cap_conn, _intake_facade(_connection([]))).create_rx_draft(
                case_id=1, doctor_id=42, source="ai_draft"
            )

        # Manual authoring is never capped: the doctor can write the
        # prescription themselves even at the cap.
        manual_conn = _connection(
            [
                _FakeResult(row=_case_row(stage="prescription_pending")),
                _FakeResult(
                    row=_rx_row(status="rejected", attempt_no=2, draft_snapshot=AI_SNAPSHOT)
                ),
                _FakeResult(scalar=2),
                _FakeResult(),
                _FakeResult(scalar=103),
                _FakeResult(),
            ]
        )
        manual = await _care_facade(manual_conn, _intake_facade(_connection([]))).create_rx_draft(
            case_id=1,
            doctor_id=42,
            source="manual",
            items=[RxItemInput(name="Paracetamol", dose="500mg", duration="3 days")],
        )
        assert manual.status == "draft"
        assert manual.source == "manual"
        assert manual.attempt_no == 2


class TestEditedYnLifecycle:
    """``edited_yn`` through the real create -> save -> approve chain."""

    @pytest.mark.asyncio
    async def test_unchanged_revision_audits_as_never_edited(self) -> None:
        unchanged_items = [RxItemInput(name="mock medication", dose="1 tablet", duration="5 days")]
        unchanged_row = SimpleNamespace(
            id=1,
            prescription_id=1,
            sequence=1,
            name="mock medication",
            dose="1 tablet",
            duration="5 days",
        )

        # Save a revision that matches the AI draft snapshot exactly.
        save_conn = _connection(
            [
                _FakeResult(row=_rx_row(draft_snapshot=AI_SNAPSHOT)),
                _FakeResult(row=_case_row(stage="prescription_pending")),
                _FakeResult(),
                _FakeResult(scalar=104),
                _FakeResult(),
                _FakeResult(),
            ]
        )
        await _care_facade(save_conn, _intake_facade(_connection([]))).save_rx_revision(
            case_id=1, rx_id=1, doctor_id=42, rx_items=unchanged_items
        )

        approve_conn = _connection(
            [
                _FakeResult(row=_rx_row(status="doctor_reviewed", draft_snapshot=AI_SNAPSHOT)),
                _FakeResult(row=_case_row(stage="prescription_pending")),
                _FakeResult(rows=[unchanged_row]),
                _FakeResult(),
                _FakeResult(),
                _FakeResult(),
                _FakeResult(),
            ]
        )
        await _care_facade(approve_conn, _intake_facade(_connection([]))).approve_prescription(
            case_id=1, rx_id=1, doctor_id=42, verification_declaration=True
        )
        approval = _stmt_params(_statements(approve_conn), "care_rx_approvals")
        assert approval["edited_yn"] is False
        assert approval["verification_declaration"] is True

    @pytest.mark.asyncio
    async def test_edited_revision_audits_as_edited(self) -> None:
        save_conn = _connection(
            [
                _FakeResult(row=_rx_row(draft_snapshot=AI_SNAPSHOT)),
                _FakeResult(row=_case_row(stage="prescription_pending")),
                _FakeResult(),
                _FakeResult(scalar=104),
                _FakeResult(scalar=105),
                _FakeResult(),
                _FakeResult(),
            ]
        )
        await _care_facade(save_conn, _intake_facade(_connection([]))).save_rx_revision(
            case_id=1, rx_id=1, doctor_id=42, rx_items=REVISED_ITEMS
        )

        approve_conn = _connection(
            [
                _FakeResult(row=_rx_row(status="doctor_reviewed", draft_snapshot=AI_SNAPSHOT)),
                _FakeResult(row=_case_row(stage="prescription_pending")),
                _FakeResult(rows=_revised_item_rows()),
                _FakeResult(),
                _FakeResult(),
                _FakeResult(),
                _FakeResult(),
            ]
        )
        await _care_facade(approve_conn, _intake_facade(_connection([]))).approve_prescription(
            case_id=1, rx_id=1, doctor_id=42, verification_declaration=True
        )
        approval = _stmt_params(_statements(approve_conn), "care_rx_approvals")
        assert approval["edited_yn"] is True
