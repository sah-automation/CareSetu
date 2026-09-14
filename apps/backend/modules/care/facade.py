"""MOD-006 Care planning: typed public sync API (PHASE-8 T04/T05, #420/#421).

The only legal cross-module import target for the ``care`` module
(coding-standards §2, ADR-0003). The consultation half of ``CareFacade``
(T04, #420): the case lifecycle from a finalized pre-summary, through the
consult-complete milestone, to case closure - plus the intake-facade handshake
seam it gates on. The prescription half (T05, #421): AI-drafted and manual
prescriptions through approval and issuance - ``create_rx_draft``,
``save_rx_revision``, ``approve_prescription``, ``reject_prescription`` and
``get_approved_prescription``. All state-changing writes commit their
``care_outbox`` event in the SAME transaction as the domain write
(ADR-0002 §1), so a crash between state change and dispatch cannot lose the
event.

The drafting seam is consent-gated (NFR-SEC-006): any use of the patient's
record history for an AI draft goes through ``HealthFacade.read_consented_history``
(which calls ``ConsentFacade.check_consent``), fail-closed - the facade never
performs a raw history read.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

from sqlalchemy import Row, delete, func, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from bus.outbox_writer import write_outbox
from modules.care.care_models import (
    CARE_SCHEMA,
    CaseDetailView,
    DoctorInputResult,
    DraftSnapshot,
    PrescriptionDetailView,
    RxItemInput,
    RxItemView,
)
from modules.care.domain.events import (
    case_consult_complete_envelope,
    prescription_approved_envelope,
    prescription_draft_created_envelope,
    prescription_issued_envelope,
    prescription_rejected_envelope,
    prescription_reviewed_envelope,
)
from modules.care.domain.exceptions import (
    CareNotFoundError,
    CareValidationError,
    IllegalPrescriptionTransitionError,
)
from modules.care.domain.prescription_machine import (
    PrescriptionAction,
    PrescriptionState,
    PrescriptionStatus,
)
from modules.care.domain.prescription_machine import (
    transition as prescription_transition,
)
from modules.care.domain.state_machine import CaseAction, CaseStage, CaseState, transition
from modules.care.outbox import CARE_OUTBOX_TABLE
from modules.care.schema.models import (
    care_cases,
    care_doctor_inputs,
    care_prescriptions,
    care_rx_approvals,
    care_rx_items,
)

if TYPE_CHECKING:
    from modules.health.facade import HealthFacade, RecordTimeline
    from modules.intake.facade import IntakeFacade

#: The record scope a doctor's consented history read for rx drafting draws
#: on (the patient's prior prescription history) - matched against the
#: consent grant's scope by ``ConsentFacade.check_consent`` via
#: ``HealthFacade.read_consented_history`` (fail-closed).
RX_DRAFT_HISTORY_SCOPE = "prescriptions"


def _to_case_detail(row: Row[Any]) -> CaseDetailView:
    """Build the typed read projection from a ``care_cases`` row."""
    return CaseDetailView(
        case_id=int(row.id),
        patient_id=int(row.patient_id),
        doctor_id=int(row.doctor_id) if row.doctor_id is not None else None,
        pre_summary_id=int(row.pre_summary_id) if row.pre_summary_id is not None else None,
        stage=row.stage,
        closed_at=row.closed_at,
        close_reason=row.close_reason,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_rx_item_view(row: Row[Any]) -> RxItemView:
    """Build the typed line-item projection from a ``care_rx_items`` row."""
    return RxItemView(
        rx_item_id=int(row.id),
        prescription_id=int(row.prescription_id),
        sequence=int(row.sequence),
        name=row.name,
        dose=row.dose,
        duration=row.duration,
    )


def _derive_edited_yn(snapshot: DraftSnapshot, items: list[RxItemView]) -> bool:
    """Compare the frozen draft snapshot against the issued revision.

    ``edited`` tells an auditor whether the approved prescription differs from
    the AI draft (CONTEXT.md glossary, ``edited_yn``): the snapshot's frozen
    ``rx_items`` (list of ``{name, dose, duration}`` maps) are compared
    positionally against the doctor's working revision. Never set by hand or
    from client input - derived here at approval. A manual prescription
    carries an empty snapshot, so it always reads as edited (there was no AI
    draft to compare against).
    """
    baseline = snapshot.get("rx_items") or []
    issued = [
        {
            "name": item.name,
            "dose": item.dose,
            "duration": item.duration,
        }
        for item in items
    ]
    return baseline != issued


def _assemble_history_summary(timeline: RecordTimeline) -> str:
    """A concise, consent-gated history context for the drafting leg.

    Built ONLY from ``HealthFacade.read_consented_history`` (NFR-SEC-006,
    fail-closed) - never from a raw history read. One line per consented
    entry, JSON-serialized so the AI gateway receives a lossless, typed
    summary the drafting leg can reason over.
    """
    if not timeline.entries:
        return ""
    return "\n".join(
        f"{entry.entry_type} {entry.occurred_at.date().isoformat()}: "
        f"{json.dumps(entry.payload, ensure_ascii=False)}"
        for entry in timeline.entries
    )


class CareFacade:
    """Typed public facade for the care module (consultation + prescription).

    Takes the engine in its constructor, mirroring the intake facade
    convention, plus the injected :class:`~modules.intake.facade.IntakeFacade`
    the consult handshake and rx-drafting gate on, and the injected
    :class:`~modules.health.facade.HealthFacade` the consent-gated history read
    for AI drafting delegates to (NFR-SEC-006, fail-closed).
    ``doctor_id`` is the partner's MOD-001 gateway identity (``partner_id``)
    and is recorded on every write for attribution.
    """

    def __init__(
        self,
        engine: AsyncEngine,
        *,
        intake_facade: IntakeFacade,
        health_facade: HealthFacade | None = None,
    ) -> None:
        self._engine = engine
        self._intake_facade = intake_facade
        self._health_facade = health_facade

    async def mark_consult_complete(
        self,
        *,
        doctor_id: int,
        case_id: int,
    ) -> CaseDetailView:
        """Close the off-platform consult on-platform in one action.

        Doctor-scoped: the case must belong to ``doctor_id``. Runs the
        ``PreSummary -> PrescriptionPending`` transition, records the
        consult-complete milestone (``consult_completed_at`` +
        ``consult_completed_by`` on ``care_cases``), and publishes
        ``case.consult_complete`` via ``care_outbox`` - the UPDATE and the
        outbox write commit in the SAME transaction (ADR-0002 §1).

        The handshake is gated on the finalized pre-summary: the
        intake-facade seam ``get_finalized_pre_summary`` raises unless the
        case's pre-summary is in the terminal ``final`` state, so a
        prescription-stage case can never arise from an unreviewed summary
        (FEAT-008 edge case).

        Raises :class:`CareNotFoundError` when the case does not exist for the
        doctor; :class:`~modules.intake.domain.exceptions.IntakeNotFoundError`
        / :class:`~modules.intake.domain.exceptions.IntakeValidationError`
        when the pre-summary is missing or not yet ``final``;
        :class:`IllegalCareTransitionError` when the case is not in
        ``PreSummary`` (e.g. a re-entrant completion).
        """
        async with self._engine.begin() as connection:
            row = (
                await connection.execute(select(care_cases).where(care_cases.c.id == case_id))
            ).first()
            if row is None or row.doctor_id is None or int(row.doctor_id) != doctor_id:
                raise CareNotFoundError(f"case {case_id} not found for doctor {doctor_id}")

            current = CaseState(stage=CaseStage(row.stage))
            next_state = transition(
                current, CaseAction.MARK_CONSULT_COMPLETE, pre_summary_finalized=True
            )

            # The finalized-pre-summary gate: the sole acceptable input to the
            # handshake. Raises (blocking the transition) while it is missing
            # or not yet final.
            await self._intake_facade.get_finalized_pre_summary(pre_summary_id=row.pre_summary_id)

            milestone_at = datetime.now(UTC)
            await connection.execute(
                care_cases.update()
                .where(care_cases.c.id == case_id)
                .values(
                    stage=next_state.stage.value,
                    consult_completed_at=milestone_at,
                    consult_completed_by=doctor_id,
                    updated_at=milestone_at,
                )
            )

            await write_outbox(
                connection,
                CARE_SCHEMA,
                CARE_OUTBOX_TABLE,
                case_consult_complete_envelope(
                    case_id=case_id,
                    patient_id=int(row.patient_id),
                    doctor_id=doctor_id,
                    pre_summary_id=int(row.pre_summary_id),
                ),
            )

            view = CaseDetailView(
                case_id=case_id,
                patient_id=int(row.patient_id),
                doctor_id=doctor_id,
                pre_summary_id=(
                    int(row.pre_summary_id) if row.pre_summary_id is not None else None
                ),
                stage=next_state.stage.value,
                closed_at=row.closed_at,
                close_reason=row.close_reason,
                created_at=row.created_at,
                updated_at=milestone_at,
            )

        return view

    async def get_case(
        self,
        *,
        doctor_id: int,
        case_id: int,
    ) -> CaseDetailView:
        """Read the doctor's care case detail.

        Doctor-scoped: raises unless the case belongs to ``doctor_id``.

        Raises :class:`CareNotFoundError` when no case exists for the doctor.
        """
        async with self._engine.begin() as connection:
            row = (
                await connection.execute(
                    select(care_cases).where(
                        care_cases.c.id == case_id,
                        care_cases.c.doctor_id == doctor_id,
                    )
                )
            ).first()
            if row is None:
                raise CareNotFoundError(f"case {case_id} not found for doctor {doctor_id}")

        return _to_case_detail(row)

    async def list_doctor_cases(
        self,
        *,
        doctor_id: int,
    ) -> list[CaseDetailView]:
        """List the doctor's open care cases, oldest first (non-closed only).

        Returns typed :class:`CaseDetailView` rows - the pending list the
        doctor works from - ordered by creation time ascending.
        """
        async with self._engine.begin() as connection:
            rows = (
                await connection.execute(
                    select(care_cases)
                    .where(
                        care_cases.c.doctor_id == doctor_id,
                        care_cases.c.stage != CaseStage.CLOSED.value,
                    )
                    .order_by(care_cases.c.created_at.asc())
                )
            ).all()

        return [_to_case_detail(row) for row in rows]

    async def submit_doctor_input(
        self,
        *,
        doctor_id: int,
        case_id: int,
        input_type: Literal["voice", "photo"],
        media_ref: str,
        sensitive_class: Literal["normal", "sensitive", "restricted"] | None = None,
    ) -> DoctorInputResult:
        """Record a voice note or photo as prescribing input for the case.

        Doctor-scoped (api-standards §6, security-phii-standards §3): the case
        must belong to the authenticated ``doctor_id``, so a doctor can never
        attach input to another doctor's case. The input type and sensitive
        class are typed to the canonical vocabulary so an invalid value is
        rejected at the boundary, before any write.

        Validates the case state: a voice/photo input attaches only to an open
        case (``PreSummary`` or ``PrescriptionPending``) - a closed case
        rejects new input.

        Raises :class:`CareNotFoundError` when the case does not exist for the
        doctor; :class:`CareValidationError` when the case is closed.
        """
        async with self._engine.begin() as connection:
            row = (
                await connection.execute(select(care_cases).where(care_cases.c.id == case_id))
            ).first()
            if row is None or row.doctor_id is None or int(row.doctor_id) != doctor_id:
                raise CareNotFoundError(f"case {case_id} not found for doctor {doctor_id}")

            if row.stage == CaseStage.CLOSED.value:
                raise CareValidationError(
                    f"submit_doctor_input is illegal while the case is {row.stage}"
                )

            result = await connection.execute(
                care_doctor_inputs.insert()
                .values(
                    case_id=case_id,
                    input_type=input_type,
                    media_ref=media_ref,
                    sensitive_class=sensitive_class,
                )
                .returning(care_doctor_inputs.c.id)
            )
            input_id = int(result.scalar_one())

        return DoctorInputResult(
            input_id=input_id,
            case_id=case_id,
            input_type=input_type,
            media_ref=media_ref,
            sensitive_class=sensitive_class,
        )

    async def create_rx_draft(
        self,
        *,
        case_id: int,
        doctor_id: int,
        source: Literal["ai_draft", "manual"],
        items: list[RxItemInput] | None = None,
    ) -> PrescriptionDetailView:
        """Create a prescription draft for the case (AI-drafted or manual).

        Doctor-scoped: raises unless the case belongs to ``doctor_id`` and is
        not yet closed (a closed case accepts no new drafts). The drafting cap
        is enforced by the prescription machine (``CREATE_DRAFT``): a new AI
        draft is only generated while the case has fewer than 2 rejected
        drafts, so the 3rd AI draft is blocked. ``attempt_no`` counts AI draft
        attempts for the case so consumers can trace the drafting-cap budget;
        a manual draft never consumes it (CONTEXT.md glossary, ``drafting cap``).

        ``source="ai_draft"`` assembles the consent-gated history context via
        ``HealthFacade.read_consented_history`` (fail-closed, NFR-SEC-006),
        delegates to ``IntakeFacade.request_rx_draft`` against the latest
        doctor input for the case, and stores the AI output as the immutable
        ``draft_snapshot`` JSONB - with NO working ``care_rx_items``, so the
        raw AI draft is never approvable (revision-freeze approval requires a
        saved revision). ``source="manual"`` captures the doctor's
        ``rx_items`` directly as the working revision with no snapshot.

        Publishes ``prescription.draft_created`` in the SAME transaction.

        Raises :class:`CareNotFoundError` when the case does not exist for the
        doctor; :class:`CareValidationError` on a closed case, a manual draft
        without items, an AI draft with no doctor input or pre-summary;
        :class:`~modules.care.domain.exceptions.IllegalPrescriptionTransitionError`
        when the drafting cap blocks the AI draft.
        """
        async with self._engine.begin() as connection:
            case_row = (
                await connection.execute(select(care_cases).where(care_cases.c.id == case_id))
            ).first()
            if (
                case_row is None
                or case_row.doctor_id is None
                or int(case_row.doctor_id) != doctor_id
            ):
                raise CareNotFoundError(f"case {case_id} not found for doctor {doctor_id}")

            if case_row.stage == CaseStage.CLOSED.value:
                raise CareValidationError(
                    f"create_rx_draft is illegal while the case is {case_row.stage}"
                )

            rx_row = (
                await connection.execute(
                    select(care_prescriptions).where(care_prescriptions.c.case_id == case_id)
                )
            ).first()

            rejected_count = 0
            if rx_row is not None:
                rejected_count = int(
                    (
                        await connection.execute(
                            select(func.count())
                            .select_from(care_rx_approvals)
                            .where(
                                care_rx_approvals.c.prescription_id == rx_row.id,
                                care_rx_approvals.c.decision == "rejected",
                            )
                        )
                    ).scalar_one()
                )

            current = PrescriptionState(
                status=(
                    PrescriptionStatus(rx_row.status)
                    if rx_row is not None
                    else PrescriptionStatus.DRAFT
                ),
                rejected_count=rejected_count,
            )

            if source == "ai_draft":
                # The drafting cap is machine-enforced for AI drafts only: a
                # new AI draft is generated while the case has fewer than 2
                # rejected drafts; the 3rd AI draft is blocked here.
                next_state = prescription_transition(current, PrescriptionAction.CREATE_DRAFT)
                return await self._create_ai_draft(
                    connection,
                    case_row,
                    rx_row,
                    next_state,
                    doctor_id=doctor_id,
                )

            if items is None or not items:
                raise CareValidationError("manual draft requires at least one rx item")
            # Manual authoring is a facade path, not a machine action - the
            # drafting cap never blocks it (CONTEXT.md, ``drafting cap``). Only
            # stale drafts are refused: a manually started revision is legal on
            # Draft/Rejected, illegal on an already-issued/fulfilled
            # prescription.
            if current.status not in (
                PrescriptionStatus.DRAFT,
                PrescriptionStatus.REJECTED,
            ):
                raise IllegalPrescriptionTransitionError(
                    f"{PrescriptionAction.CREATE_DRAFT.value} is illegal "
                    f"while the prescription is {current.status.value}"
                )
            next_state = PrescriptionState(
                status=PrescriptionStatus.DRAFT, rejected_count=current.rejected_count
            )
            now = datetime.now(UTC)
            attempt_no = int(rx_row.attempt_no) if rx_row is not None else 1
            if rx_row is None:
                ins = await connection.execute(
                    care_prescriptions.insert()
                    .values(
                        case_id=case_id,
                        status=next_state.status.value,
                        source=source,
                        attempt_no=attempt_no,
                        draft_snapshot={},
                    )
                    .returning(care_prescriptions.c.id)
                )
                prescription_id = int(ins.scalar_one())
            else:
                prescription_id = int(rx_row.id)
                await connection.execute(
                    care_prescriptions.update()
                    .where(care_prescriptions.c.id == prescription_id)
                    .values(
                        status=next_state.status.value,
                        source=source,
                        attempt_no=attempt_no,
                        draft_snapshot={},
                        updated_at=now,
                    )
                )

            item_ids = await self._write_rx_items(connection, prescription_id, list(items))
            item_views = [
                RxItemView(
                    rx_item_id=item_ids[i],
                    prescription_id=prescription_id,
                    sequence=i + 1,
                    name=items[i].name,
                    dose=items[i].dose,
                    duration=items[i].duration,
                )
                for i in range(len(items))
            ]

            await write_outbox(
                connection,
                CARE_SCHEMA,
                CARE_OUTBOX_TABLE,
                prescription_draft_created_envelope(
                    case_id=case_id,
                    prescription_id=prescription_id,
                    patient_id=int(case_row.patient_id),
                    doctor_id=doctor_id,
                    source=source,
                    attempt_no=attempt_no,
                ),
            )

            return PrescriptionDetailView(
                prescription_id=prescription_id,
                case_id=case_id,
                status=next_state.status.value,
                source=source,
                attempt_no=attempt_no,
                draft_snapshot={},
                issued_at=None,
                attributed_doctor=None,
                items=item_views,
                created_at=now,
                updated_at=now,
            )

    async def save_rx_revision(
        self,
        *,
        case_id: int,
        rx_id: int,
        doctor_id: int,
        rx_items: list[RxItemInput],
    ) -> PrescriptionDetailView:
        """Write the doctor's working revision to ``care_rx_items``.

        The doctor's review-and-edit: the current ``Draft``/``DoctorReviewed``
        row's items are replaced (delete + re-insert, so a lost edit can never
        mean a wrong prescription issued - the revision IS what approval
        freezes) and the prescription moves to ``doctor_reviewed``. A stale
        revision is rejected: if the prescription is already ``issued`` or
        ``rejected`` (a competing action landed first), ``SAVE_REVISION`` is
        illegal there and the machine raises.

        Publishes ``prescription.reviewed`` in the SAME transaction.

        Raises :class:`CareNotFoundError` when the case/prescription does not
        exist for the doctor; :class:`CareValidationError` when the
        prescription does not belong to the case;
        :class:`~modules.care.domain.exceptions.IllegalPrescriptionTransitionError`
        when the prescription is not in a saveable state (stale revision).
        """
        async with self._engine.begin() as connection:
            rx_row = (
                await connection.execute(
                    select(care_prescriptions).where(care_prescriptions.c.id == rx_id)
                )
            ).first()
            if rx_row is None:
                raise CareNotFoundError(f"prescription {rx_id} not found")

            case_row = (
                await connection.execute(select(care_cases).where(care_cases.c.id == case_id))
            ).first()
            if (
                case_row is None
                or case_row.doctor_id is None
                or int(case_row.doctor_id) != doctor_id
            ):
                raise CareNotFoundError(f"case {case_id} not found for doctor {doctor_id}")
            if int(rx_row.case_id) != case_id:
                raise CareValidationError(f"prescription {rx_id} does not belong to case {case_id}")

            current = PrescriptionState(status=PrescriptionStatus(rx_row.status), rejected_count=0)
            next_state = prescription_transition(current, PrescriptionAction.SAVE_REVISION)

            now = datetime.now(UTC)
            await connection.execute(
                delete(care_rx_items).where(care_rx_items.c.prescription_id == rx_id)
            )
            item_ids = await self._write_rx_items(connection, rx_id, rx_items)
            await connection.execute(
                care_prescriptions.update()
                .where(care_prescriptions.c.id == rx_id)
                .values(status=next_state.status.value, updated_at=now)
            )

            await write_outbox(
                connection,
                CARE_SCHEMA,
                CARE_OUTBOX_TABLE,
                prescription_reviewed_envelope(
                    case_id=case_id,
                    prescription_id=rx_id,
                    patient_id=int(case_row.patient_id),
                    doctor_id=doctor_id,
                ),
            )

            item_views = [
                RxItemView(
                    rx_item_id=item_ids[i],
                    prescription_id=rx_id,
                    sequence=i + 1,
                    name=rx_items[i].name,
                    dose=rx_items[i].dose,
                    duration=rx_items[i].duration,
                )
                for i in range(len(rx_items))
            ]
            return PrescriptionDetailView(
                prescription_id=rx_id,
                case_id=case_id,
                status=next_state.status.value,
                source=rx_row.source,
                attempt_no=int(rx_row.attempt_no),
                draft_snapshot=rx_row.draft_snapshot,
                issued_at=rx_row.issued_at,
                attributed_doctor=rx_row.attributed_doctor,
                items=item_views,
                created_at=rx_row.created_at,
                updated_at=now,
            )

    async def approve_prescription(
        self,
        *,
        case_id: int,
        rx_id: int,
        doctor_id: int,
        verification_declaration: bool = False,
    ) -> PrescriptionDetailView:
        """Revision-freeze approval: issue exactly the saved working revision.

        Mandatory double-check (CONTEXT.md glossary, ``verification
        declaration``): approval is refused (``CareValidationError``, via the
        replaceable gate seam) unless ``verification_declaration`` is true -
        the declaration is stored on ``care_rx_approvals`` with
        ``declared_at``. The doctor's saved working revision (the current
        ``care_rx_items``) is frozen: ``issued_at`` and ``attributed_doctor``
        are set, ``edited_yn`` is derived by comparing the issued items
        against the immutable ``draft_snapshot`` (never set by hand), and the
        prescription lands in ``issued`` with no dwell between approve and
        issue. Approval is BLOCKED (``CareValidationError``) when no revision
        exists - the raw AI draft is never approvable.

        Publishes ``prescription.approved`` and ``prescription.issued`` in the
        SAME transaction.

        Raises :class:`CareNotFoundError` when the case/prescription does not
        exist for the doctor; :class:`CareValidationError` when the declaration
        is missing or no revision is saved;
        :class:`~modules.care.domain.exceptions.IllegalPrescriptionTransitionError`
        when the prescription is not in an approvable state.
        """
        async with self._engine.begin() as connection:
            rx_row = (
                await connection.execute(
                    select(care_prescriptions).where(care_prescriptions.c.id == rx_id)
                )
            ).first()
            if rx_row is None:
                raise CareNotFoundError(f"prescription {rx_id} not found")

            case_row = (
                await connection.execute(select(care_cases).where(care_cases.c.id == case_id))
            ).first()
            if (
                case_row is None
                or case_row.doctor_id is None
                or int(case_row.doctor_id) != doctor_id
            ):
                raise CareNotFoundError(f"case {case_id} not found for doctor {doctor_id}")
            if int(rx_row.case_id) != case_id:
                raise CareValidationError(f"prescription {rx_id} does not belong to case {case_id}")

            # The approval gate lives behind a replaceable seam so a stricter
            # regulatory rule (CFL-002) can slot in without redesign.
            await self._check_approval_declaration(
                verification_declaration=verification_declaration
            )

            current = PrescriptionState(status=PrescriptionStatus(rx_row.status), rejected_count=0)
            next_state = prescription_transition(
                current,
                PrescriptionAction.APPROVE,
                verification_declaration=verification_declaration,
            )

            item_rows = (
                await connection.execute(
                    select(care_rx_items)
                    .where(care_rx_items.c.prescription_id == rx_id)
                    .order_by(care_rx_items.c.sequence.asc())
                )
            ).all()
            if not item_rows:
                raise CareValidationError(
                    f"approval blocked: prescription {rx_id} has no saved revision"
                )
            items = [_to_rx_item_view(row) for row in item_rows]
            edited_yn = _derive_edited_yn(rx_row.draft_snapshot, items)

            issued_at = datetime.now(UTC)
            await connection.execute(
                care_prescriptions.update()
                .where(care_prescriptions.c.id == rx_id)
                .values(
                    status=next_state.status.value,
                    issued_at=issued_at,
                    attributed_doctor=doctor_id,
                    updated_at=issued_at,
                )
            )
            await connection.execute(
                care_rx_approvals.insert().values(
                    prescription_id=rx_id,
                    doctor_id=doctor_id,
                    decision="approved",
                    edited_yn=edited_yn,
                    verification_declaration="true",
                    declared_at=issued_at,
                    approved_at=issued_at,
                )
            )

            await write_outbox(
                connection,
                CARE_SCHEMA,
                CARE_OUTBOX_TABLE,
                prescription_approved_envelope(
                    case_id=case_id,
                    prescription_id=rx_id,
                    patient_id=int(case_row.patient_id),
                    doctor_id=doctor_id,
                    edited_yn=edited_yn,
                ),
            )
            await write_outbox(
                connection,
                CARE_SCHEMA,
                CARE_OUTBOX_TABLE,
                prescription_issued_envelope(
                    case_id=case_id,
                    prescription_id=rx_id,
                    patient_id=int(case_row.patient_id),
                    doctor_id=doctor_id,
                    occurred_at=issued_at.isoformat(),
                ),
            )

            return PrescriptionDetailView(
                prescription_id=rx_id,
                case_id=case_id,
                status=next_state.status.value,
                source=rx_row.source,
                attempt_no=int(rx_row.attempt_no),
                draft_snapshot=rx_row.draft_snapshot,
                issued_at=issued_at,
                attributed_doctor=doctor_id,
                items=items,
                created_at=rx_row.created_at,
                updated_at=issued_at,
            )

    async def reject_prescription(
        self,
        *,
        case_id: int,
        rx_id: int,
        doctor_id: int,
        reason: str,
    ) -> PrescriptionDetailView:
        """Reject a draft; record the reason; never auto-close the case.

        Requires a non-empty ``reason`` (machine-enforced: ``REJECT`` refuses
        an empty reason). Records the rejection on ``care_rx_approvals`` and
        moves the prescription to ``rejected`` - the branch where the drafting
        assistant may try again (cap-gated) - and publishes
        ``prescription.rejected``. Deliberately does NOT touch
        ``care_cases.stage``: a rejected draft never changes the case stage
        (CONTEXT.md glossary, ``close-without-prescription``), so the visit
        stays open for manual authoring or a fresh AI draft.

        Raises :class:`CareNotFoundError` when the case/prescription does not
        exist for the doctor;
        :class:`~modules.care.domain.exceptions.IllegalPrescriptionTransitionError`
        when the reason is empty or the prescription is not rejectable.
        """
        async with self._engine.begin() as connection:
            rx_row = (
                await connection.execute(
                    select(care_prescriptions).where(care_prescriptions.c.id == rx_id)
                )
            ).first()
            if rx_row is None:
                raise CareNotFoundError(f"prescription {rx_id} not found")

            case_row = (
                await connection.execute(select(care_cases).where(care_cases.c.id == case_id))
            ).first()
            if (
                case_row is None
                or case_row.doctor_id is None
                or int(case_row.doctor_id) != doctor_id
            ):
                raise CareNotFoundError(f"case {case_id} not found for doctor {doctor_id}")
            if int(rx_row.case_id) != case_id:
                raise CareValidationError(f"prescription {rx_id} does not belong to case {case_id}")

            current = PrescriptionState(status=PrescriptionStatus(rx_row.status), rejected_count=0)
            next_state = prescription_transition(
                current, PrescriptionAction.REJECT, rejection_reason=reason
            )

            now = datetime.now(UTC)
            await connection.execute(
                care_prescriptions.update()
                .where(care_prescriptions.c.id == rx_id)
                .values(status=next_state.status.value, updated_at=now)
            )
            await connection.execute(
                care_rx_approvals.insert().values(
                    prescription_id=rx_id,
                    doctor_id=doctor_id,
                    decision="rejected",
                    reason=reason,
                )
            )

            await write_outbox(
                connection,
                CARE_SCHEMA,
                CARE_OUTBOX_TABLE,
                prescription_rejected_envelope(
                    case_id=case_id,
                    prescription_id=rx_id,
                    patient_id=int(case_row.patient_id),
                    doctor_id=doctor_id,
                    reason=reason,
                ),
            )

            item_rows = (
                await connection.execute(
                    select(care_rx_items)
                    .where(care_rx_items.c.prescription_id == rx_id)
                    .order_by(care_rx_items.c.sequence.asc())
                )
            ).all()

            return PrescriptionDetailView(
                prescription_id=rx_id,
                case_id=case_id,
                status=next_state.status.value,
                source=rx_row.source,
                attempt_no=int(rx_row.attempt_no),
                draft_snapshot=rx_row.draft_snapshot,
                issued_at=rx_row.issued_at,
                attributed_doctor=rx_row.attributed_doctor,
                items=[_to_rx_item_view(row) for row in item_rows],
                created_at=rx_row.created_at,
                updated_at=now,
            )

    async def get_approved_prescription(self, *, rx_id: int) -> PrescriptionDetailView:
        """Read an issued e-prescription - the Phase-10 source of truth.

        Serves ONLY approved-and-issued prescriptions (``status = issued`` AND
        ``issued_at`` set - CONTEXT.md glossary, ``e-prescription``): the
        frozen, attributed artifact with no supersede or void path. A draft,
        rejected, or not-yet-issued prescription reads as not found.

        Raises :class:`CareNotFoundError` when no issued prescription exists
        for ``rx_id``.
        """
        async with self._engine.begin() as connection:
            rx_row = (
                await connection.execute(
                    select(care_prescriptions).where(
                        care_prescriptions.c.id == rx_id,
                        care_prescriptions.c.status == PrescriptionStatus.APPROVED_ISSUED.value,
                        care_prescriptions.c.issued_at.is_not(None),
                    )
                )
            ).first()
            if rx_row is None:
                raise CareNotFoundError(f"approved prescription {rx_id} not found")

            item_rows = (
                await connection.execute(
                    select(care_rx_items)
                    .where(care_rx_items.c.prescription_id == rx_id)
                    .order_by(care_rx_items.c.sequence.asc())
                )
            ).all()

        return PrescriptionDetailView(
            prescription_id=int(rx_row.id),
            case_id=int(rx_row.case_id),
            status=rx_row.status,
            source=rx_row.source,
            attempt_no=int(rx_row.attempt_no),
            draft_snapshot=rx_row.draft_snapshot,
            issued_at=rx_row.issued_at,
            attributed_doctor=rx_row.attributed_doctor,
            items=[_to_rx_item_view(row) for row in item_rows],
            created_at=rx_row.created_at,
            updated_at=rx_row.updated_at,
        )

    async def _create_ai_draft(
        self,
        connection: AsyncConnection,
        case_row: Row[Any],
        rx_row: Row[Any] | None,
        next_state: PrescriptionState,
        *,
        doctor_id: int,
    ) -> PrescriptionDetailView:
        """Generate + persist one AI draft (used by ``create_rx_draft``).

        Runs inside the caller's transaction: the consent-gated history read
        (fail-closed, NFR-SEC-006), the intake-facade drafting call, the
        immutable ``draft_snapshot`` write and the ``prescription.draft_created``
        outbox row all ride the SAME transaction as the drafting-cap transition.
        The working ``care_rx_items`` are cleared so the raw AI draft is never
        approvable - the doctor must save a revision first.
        """
        if self._health_facade is None:
            raise RuntimeError("HealthFacade not configured for consented rx drafting")

        case_id = int(case_row.id)
        timeline = await self._health_facade.read_consented_history(
            patient_id=int(case_row.patient_id),
            scope=RX_DRAFT_HISTORY_SCOPE,
            counterparty_type="doctor",
            counterparty_id=doctor_id,
        )
        history_summary = _assemble_history_summary(timeline)

        if case_row.pre_summary_id is None:
            raise CareValidationError(f"case {case_id} has no pre-summary to draft from")
        input_row = (
            await connection.execute(
                select(care_doctor_inputs)
                .where(care_doctor_inputs.c.case_id == case_id)
                .order_by(care_doctor_inputs.c.id.desc())
            )
        ).first()
        if input_row is None:
            raise CareValidationError(f"no doctor input recorded for case {case_id}")

        draft = await self._intake_facade.request_rx_draft(
            doctor_input_ref=int(input_row.id),
            pre_summary_ref=int(case_row.pre_summary_id),
            history_summary=history_summary,
        )

        snapshot: DraftSnapshot = {
            "rx_items": [item.model_dump(mode="json") for item in draft.rx_items]
        }
        attempt_no = int(rx_row.attempt_no) + 1 if rx_row is not None else 1
        now = datetime.now(UTC)
        if rx_row is None:
            ins = await connection.execute(
                care_prescriptions.insert()
                .values(
                    case_id=case_id,
                    status=next_state.status.value,
                    source="ai_draft",
                    attempt_no=attempt_no,
                    draft_snapshot=snapshot,
                )
                .returning(care_prescriptions.c.id)
            )
            prescription_id = int(ins.scalar_one())
        else:
            prescription_id = int(rx_row.id)
            await connection.execute(
                care_prescriptions.update()
                .where(care_prescriptions.c.id == prescription_id)
                .values(
                    status=next_state.status.value,
                    source="ai_draft",
                    attempt_no=attempt_no,
                    draft_snapshot=snapshot,
                    updated_at=now,
                )
            )

        # A fresh AI draft clears the working revision: the raw draft is never
        # approvable, so approval must wait for the doctor's save_rx_revision.
        await connection.execute(
            delete(care_rx_items).where(care_rx_items.c.prescription_id == prescription_id)
        )

        await write_outbox(
            connection,
            CARE_SCHEMA,
            CARE_OUTBOX_TABLE,
            prescription_draft_created_envelope(
                case_id=case_id,
                prescription_id=prescription_id,
                patient_id=int(case_row.patient_id),
                doctor_id=doctor_id,
                source="ai_draft",
                attempt_no=attempt_no,
            ),
        )

        return PrescriptionDetailView(
            prescription_id=prescription_id,
            case_id=case_id,
            status=next_state.status.value,
            source="ai_draft",
            attempt_no=attempt_no,
            draft_snapshot=snapshot,
            issued_at=None,
            attributed_doctor=None,
            items=[],
            created_at=now,
            updated_at=now,
        )

    @staticmethod
    async def _write_rx_items(
        connection: AsyncConnection,
        prescription_id: int,
        rx_items: list[RxItemInput],
    ) -> list[int]:
        """Insert the working-revision item rows, answering their ids."""
        item_ids: list[int] = []
        for sequence, item in enumerate(rx_items, start=1):
            res = await connection.execute(
                care_rx_items.insert()
                .values(
                    prescription_id=prescription_id,
                    sequence=sequence,
                    name=item.name,
                    dose=item.dose,
                    duration=item.duration,
                )
                .returning(care_rx_items.c.id)
            )
            item_ids.append(int(res.scalar_one()))
        return item_ids

    async def _check_approval_declaration(self, *, verification_declaration: bool) -> None:
        """The replaceable approval-gate seam (CFL-002 can slot in here).

        Baseline gate: ``approve_prescription`` refuses a prescription without
        the doctor's recorded double-check (``verification_declaration =
        true``, CONTEXT.md glossary). A stricter regulatory rule (CFL-002) can
        subclass/extend this method with additional checks; the declaration is
        stored on ``care_rx_approvals`` with ``declared_at`` downstream.
        """
        if not verification_declaration:
            raise CareValidationError(
                "approval requires verification_declaration=true (declared_at recorded)"
            )
