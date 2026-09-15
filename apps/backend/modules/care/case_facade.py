"""Case-console facade: case state-machine operations for the care module.

Handles the case lifecycle from finalized pre-summary, through the
consult-complete milestone, to case closure - plus the doctor-input
recording. This half of the original ``CareFacade`` covers the case
state machine exclusively; the prescription half lives in
:mod:`modules.care.rx_facade`.

Shared primitives live here (ownership guard, case-detail builder)
and are imported by :mod:`modules.care.rx_facade` - never duplicated.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

from sqlalchemy import Row, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from bus.outbox_writer import write_outbox
from modules.care.care_models import (
    CARE_SCHEMA,
    CaseDetailView,
    DoctorInputResult,
)
from modules.care.domain.events import (
    case_closed_envelope,
    case_consult_complete_envelope,
)
from modules.care.domain.exceptions import CareNotFoundError, CareValidationError
from modules.care.domain.state_machine import CaseAction, CaseStage, CaseState, transition
from modules.care.outbox import CARE_OUTBOX_TABLE
from modules.care.schema.models import (
    care_cases,
    care_doctor_inputs,
)

if TYPE_CHECKING:
    from modules.intake.facade import IntakeFacade

#: The intake pre-summary terminal ``review_state`` that qualifies for the
#: consult-complete handshake. Mirrors the intake seam's canonical
#: ``PreSummaryStatus.FINAL`` value - ``get_finalized_pre_summary`` only
#: returns when ``review_state`` equals this, so comparing against it here
#: keeps the care side free of an intake runtime import (ADR-0003).
FINALIZED_PRE_SUMMARY_STATE = "final"


def _to_case_detail(row: Row[Any]) -> CaseDetailView:
    """Build the typed read projection from a ``care_cases`` row."""
    return CaseDetailView(
        case_id=int(row.id),
        patient_id=int(row.patient_id),
        doctor_id=int(row.doctor_id) if row.doctor_id is not None else None,
        pre_summary_id=int(row.pre_summary_id) if row.pre_summary_id is not None else None,
        stage=row.stage,
        forced_review=bool(row.forced_review),
        closed_at=row.closed_at,
        close_reason=row.close_reason,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


# -----------------------------------------------------------------
# Shared ownership guard (imported by rx_facade)
# -----------------------------------------------------------------


async def check_case_ownership(
    connection: AsyncConnection,
    *,
    doctor_id: int,
    case_id: int,
    allow_unclaimed: bool = False,
) -> Row[Any]:
    """Load a case row and enforce the ownership boundary.

    Every case-scoped operation goes through this single guard; no
    duplicated check remains at call sites. A foreign doctor on any
    case-scoped read or write, including ``get_approved_prescription``,
    gets ``CareNotFoundError`` (the not-found envelope).

    A born case (``doctor_id`` NULL at birth) is claimable by the first
    doctor who completes the ``mark_consult_complete`` handshake, so the
    guard allows an unclaimed case through when ``allow_unclaimed=True``
    and blocks it for every other operation. After claim, ownership is
    enforced normally.

    Returns the loaded row so callers can use ``row.patient_id``,
    ``row.stage`` etc. without a second query.
    """
    row = (await connection.execute(select(care_cases).where(care_cases.c.id == case_id))).first()
    if row is None:
        raise CareNotFoundError(f"case {case_id} not found for doctor {doctor_id}")
    if row.doctor_id is None:
        if not allow_unclaimed:
            raise CareNotFoundError(f"case {case_id} not found for doctor {doctor_id}")
    elif int(row.doctor_id) != doctor_id:
        raise CareNotFoundError(f"case {case_id} not found for doctor {doctor_id}")
    return row


class CaseConsoleFacade:
    """Case state-machine facade: consult lifecycle, case reads, and doctor input.

    Takes the engine in its constructor plus the injected
    :class:`~modules.intake.facade.IntakeFacade` the consult handshake
    resolves finalized pre-summaries against (via ``get_finalized_pre_summary``).
    ``doctor_id`` is the partner's MOD-001 gateway identity (``partner_id``)
    and is recorded on every write for attribution.
    """

    def __init__(self, engine: AsyncEngine, *, intake_facade: IntakeFacade) -> None:
        self._engine = engine
        self._intake_facade = intake_facade

    async def mark_consult_complete(
        self,
        *,
        doctor_id: int,
        case_id: int,
    ) -> CaseDetailView:
        """Close the off-platform consult on-platform in one action.

        Doctor-scoped: the case must belong to ``doctor_id``; an unclaimed
        born case (``doctor_id`` unset) is claimable by the first doctor who
        completes this handshake. Runs the ``PreSummary -> PrescriptionPending``
        transition, records the consult-complete milestone
        (``consult_completed_at`` + ``consult_completed_by`` on ``care_cases``),
        and publishes ``case.consult_complete`` via ``care_outbox`` - the
        UPDATE and the outbox write commit in the SAME transaction (ADR-0002
        S1).

        The handshake resolves the finalized pre-summary FIRST via the
        intake-facade seam ``get_finalized_pre_summary`` and passes its real
        result into the case-machine transition so the machine's own gate
        (``pre_summary_finalized``) is the single boundary - the facade
        verification-declaration gate is the one replaceable CFL-002 seam, with
        the machine's guard as defense-in-depth.

        Raises :class:`CareNotFoundError` when the case does not exist for the
        doctor; :class:`~modules.intake.domain.exceptions.IntakeNotFoundError`
        / :class:`~modules.intake.domain.exceptions.IntakeValidationError`
        when the pre-summary is missing or not yet ``final``;
        :class:`~modules.care.domain.exceptions.IllegalCareTransitionError`
        when the case is not in ``PreSummary`` (e.g. a re-entrant completion).
        """
        async with self._engine.begin() as connection:
            row = await check_case_ownership(
                connection, doctor_id=doctor_id, case_id=case_id, allow_unclaimed=True
            )

            pre_summary = await self._intake_facade.get_finalized_pre_summary(
                pre_summary_id=row.pre_summary_id
            )
            pre_summary_finalized = pre_summary.review_state == FINALIZED_PRE_SUMMARY_STATE

            current = CaseState(stage=CaseStage(row.stage))
            next_state = transition(
                current,
                CaseAction.MARK_CONSULT_COMPLETE,
                pre_summary_finalized=pre_summary_finalized,
            )

            milestone_at = datetime.now(UTC)
            await connection.execute(
                care_cases.update()
                .where(care_cases.c.id == case_id)
                .values(
                    stage=next_state.stage.value,
                    doctor_id=doctor_id,
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
                forced_review=bool(row.forced_review),
                closed_at=row.closed_at,
                close_reason=row.close_reason,
                created_at=row.created_at,
                updated_at=milestone_at,
            )

        return view

    async def close_case_without_rx(
        self,
        *,
        doctor_id: int,
        case_id: int,
        close_reason: str,
    ) -> CaseDetailView:
        """Close a visit with no prescription in one deliberate action.

        Doctor-scoped: the case must belong to ``doctor_id``. Legal only
        from ``PrescriptionPending`` (the consult-complete milestone must
        have landed - a case is never closed mid-handshake, user story 6).
        Runs the case machine's ``CLOSE_WITHOUT_RX`` action, which is the
        single gate: it enforces the PrescriptionPending-only legality, the
        non-empty close reason, and ``Closed`` terminality. Records
        ``closed_at`` and the ``close_reason`` on ``care_cases`` and
        publishes ``case.closed`` through the care outbox in the same
        transaction as the close write (ADR-0002 S1).

        A rejected AI draft never closes the case - closing stays the
        doctor's deliberate action.

        Raises :class:`CareNotFoundError` when the case does not exist for
        the doctor; :class:`~modules.care.domain.exceptions.IllegalCareTransitionError`
        when the case is not in ``PrescriptionPending`` (pre-handshake or
        already closed) or the close reason is empty.
        """
        async with self._engine.begin() as connection:
            row = await check_case_ownership(connection, doctor_id=doctor_id, case_id=case_id)

            current = CaseState(stage=CaseStage(row.stage))
            next_state = transition(current, CaseAction.CLOSE_WITHOUT_RX, close_reason=close_reason)

            now = datetime.now(UTC)
            await connection.execute(
                care_cases.update()
                .where(care_cases.c.id == case_id)
                .values(
                    stage=next_state.stage.value,
                    closed_at=now,
                    close_reason=close_reason,
                    updated_at=now,
                )
            )

            await write_outbox(
                connection,
                CARE_SCHEMA,
                CARE_OUTBOX_TABLE,
                case_closed_envelope(
                    case_id=case_id,
                    patient_id=int(row.patient_id),
                    doctor_id=doctor_id,
                    close_reason=close_reason,
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
                forced_review=bool(row.forced_review),
                closed_at=now,
                close_reason=close_reason,
                created_at=row.created_at,
                updated_at=now,
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
            row = await check_case_ownership(connection, doctor_id=doctor_id, case_id=case_id)

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

        Doctor-scoped (api-standards S6, security-phii-standards S3): the case
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
            row = await check_case_ownership(connection, doctor_id=doctor_id, case_id=case_id)

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
