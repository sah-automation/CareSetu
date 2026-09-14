"""MOD-006 Care planning: typed public sync API (PHASE-8 T04, #420).

The only legal cross-module import target for the ``care`` module
(coding-standards §2, ADR-0003). The consultation half of ``CareFacade``:
the case lifecycle from a finalized pre-summary, through the consult-complete
milestone, to case closure - plus the intake-facade handshake seam it gates
on. All state-changing writes commit their ``care_outbox`` event in the SAME
transaction as the domain write (ADR-0002 §1), so a crash between state change
and dispatch cannot lose the event.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

from sqlalchemy import Row, select
from sqlalchemy.ext.asyncio import AsyncEngine

from bus.outbox_writer import write_outbox
from modules.care.care_models import CARE_SCHEMA, CaseDetailView, DoctorInputResult
from modules.care.domain.events import case_consult_complete_envelope
from modules.care.domain.exceptions import (
    CareNotFoundError,
    CareValidationError,
)
from modules.care.domain.state_machine import CaseAction, CaseStage, CaseState, transition
from modules.care.outbox import CARE_OUTBOX_TABLE
from modules.care.schema.models import care_cases, care_doctor_inputs

if TYPE_CHECKING:
    from modules.intake.facade import IntakeFacade


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


class CareFacade:
    """Typed public facade for the care module (consultation workflow).

    Takes the engine in its constructor, mirroring the intake facade
    convention, plus the injected :class:`~modules.intake.facade.IntakeFacade`
    the consult handshake gates on. ``doctor_id`` is the partner's MOD-001
    gateway identity (``partner_id``) and is recorded on every write for
    attribution.
    """

    def __init__(
        self,
        engine: AsyncEngine,
        *,
        intake_facade: IntakeFacade,
    ) -> None:
        self._engine = engine
        self._intake_facade = intake_facade

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
