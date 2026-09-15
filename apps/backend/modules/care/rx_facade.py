"""Prescription facade: prescription state-machine operations for the care module.

Handles AI-drafted and manual prescriptions through approval and issuance -
``create_rx_draft``, ``save_rx_revision``, ``approve_prescription``,
``reject_prescription`` and ``get_approved_prescription``. This half of the
care module's public surface covers the prescription state machine
exclusively; the case-console half lives in :mod:`modules.care.case_facade`.

All state-changing writes commit their ``care_outbox`` event in the SAME
transaction as the domain write (ADR-0002 S1), so a crash between state
change and dispatch cannot lose the event.

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
    DraftSnapshot,
    PrescriptionDetailView,
    RxItemInput,
    RxItemView,
)
from modules.care.case_facade import check_case_ownership
from modules.care.domain.events import (
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
from modules.care.domain.state_machine import CaseStage
from modules.care.outbox import CARE_OUTBOX_TABLE
from modules.care.schema.models import (
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


class PrescriptionFacade:
    """Prescription state-machine facade: AI-drafted and manual rx lifecycle.

    Takes the engine in its constructor, the injected
    :class:`~modules.intake.facade.IntakeFacade` the drafting gate delegates to,
    and the injected :class:`~modules.health.facade.HealthFacade` the
    consent-gated history read for AI drafting delegates to (NFR-SEC-006,
    fail-closed). ``doctor_id`` is the partner's MOD-001 gateway identity
    (``partner_id``) and is recorded on every write for attribution.
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
            case_row = await check_case_ownership(connection, doctor_id=doctor_id, case_id=case_id)

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

            case_row = await check_case_ownership(connection, doctor_id=doctor_id, case_id=case_id)
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

        The approval-gate seam (``_check_approval_declaration``) is the one
        replaceable CFL-002 compliance seam (ADR-0014/0015); the machine's
        declaration guard is defense-in-depth.

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

            case_row = await check_case_ownership(connection, doctor_id=doctor_id, case_id=case_id)
            if int(rx_row.case_id) != case_id:
                raise CareValidationError(f"prescription {rx_id} does not belong to case {case_id}")

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
                    verification_declaration=True,
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

            case_row = await check_case_ownership(connection, doctor_id=doctor_id, case_id=case_id)
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

    async def get_approved_prescription(
        self, *, rx_id: int, doctor_id: int
    ) -> PrescriptionDetailView:
        """Read an issued e-prescription - the Phase-10 source of truth.

        Doctor-scoped: the prescription's owning case must belong to
        ``doctor_id``; a foreign doctor reads as not found.

        Serves ONLY approved-and-issued prescriptions (``status = issued`` AND
        ``issued_at`` set - CONTEXT.md glossary, ``e-prescription``): the
        frozen, attributed artifact with no supersede or void path. A draft,
        rejected, or not-yet-issued prescription reads as not found.

        Raises :class:`CareNotFoundError` when no issued prescription exists
        for ``rx_id`` or the doctor does not own the case.
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

            await check_case_ownership(connection, doctor_id=doctor_id, case_id=int(rx_row.case_id))

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

    # -----------------------------------------------------------------
    # AI-draft generation (private)
    # -----------------------------------------------------------------

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

        CFL-002 seam: this facade gate is the ONE replaceable compliance seam
        (ADR-0014/0015). The prescription machine's ``APPROVE`` declaration
        guard is deliberate defense-in-depth - the facade gate is what a
        stricter rule slots into.
        """
        if not verification_declaration:
            raise CareValidationError(
                "approval requires verification_declaration=true (declared_at recorded)"
            )
