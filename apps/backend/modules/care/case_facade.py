"""Case-console facade: case state-machine operations for the care module.

Handles the case lifecycle from finalized pre-summary, through the
consult-complete milestone, to case closure - plus the doctor-input
recording. This half of the care module's public surface covers the case
state machine exclusively; the prescription half lives in
:mod:`modules.care.rx_facade`.

Shared primitives live here (ownership guard, case-detail builder)
and are imported by :mod:`modules.care.rx_facade` - never duplicated.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Collection
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


def _to_case_detail(row: Row[Any], *, has_doctor_input: bool = False) -> CaseDetailView:
    """Build the typed read projection from a ``care_cases`` row."""
    return CaseDetailView(
        case_id=int(row.id),
        patient_id=int(row.patient_id),
        doctor_id=int(row.doctor_id) if row.doctor_id is not None else None,
        pre_summary_id=int(row.pre_summary_id) if row.pre_summary_id is not None else None,
        stage=row.stage,
        forced_review=bool(row.forced_review),
        has_doctor_input=has_doctor_input,
        closed_at=row.closed_at,
        close_reason=row.close_reason,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def _case_ids_with_doctor_input(
    connection: AsyncConnection, case_ids: Collection[int]
) -> set[int]:
    """Return the subset of ``case_ids`` that already carry a doctor input.

    The AI-draft gate mirrors this (the backend refuses a draft with no
    ``care_doctor_inputs`` row), so the projection exposes it for the
    workspace to hydrate its lock state after a reload (#492 review fix: the
    capture surface was re-shown and the draft button re-locked until the
    doctor re-uploaded an input). One query for any batch size - never a
    per-case N+1.
    """
    if not case_ids:
        return set()
    rows = (
        await connection.execute(
            select(care_doctor_inputs.c.case_id)
            .where(care_doctor_inputs.c.case_id.in_(case_ids))
            .distinct()
        )
    ).all()
    return {int(row.case_id) for row in rows}


# -----------------------------------------------------------------
# Shared ownership guard (imported by rx_facade)
# -----------------------------------------------------------------


def assigned_doctor_of_resolver(
    intake_facade: IntakeFacade,
) -> Callable[[int], Awaitable[int | None]]:
    """Build the assigned-doctor resolver for an intake facade (#478).

    Returns the bound callable :func:`check_case_ownership` needs to open a
    born-but-unclaimed case to the doctor the intake assigned it to (pick,
    #443): given a pre-summary id it resolves to the intake's
    ``assigned_partner_id`` (or ``None`` when not picked) through the
    ``IntakeFacade.assigned_partner_for_pre_summaries`` seam. Shared
    primitive imported by ``rx_facade`` (never duplicated) so the case and
    prescription read paths agree on the same allowance.
    """

    async def _resolve(pre_summary_id: int) -> int | None:
        resolved = await intake_facade.assigned_partner_for_pre_summaries([pre_summary_id])
        return resolved.get(pre_summary_id)

    return _resolve


async def check_case_ownership(
    connection: AsyncConnection,
    *,
    doctor_id: int,
    case_id: int,
    allow_unclaimed: bool = False,
    assigned_doctor_of: Callable[[int], Awaitable[int | None]] | None = None,
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

    ``assigned_doctor_of`` extends legibility to born-but-unclaimed cases
    without changing claim semantics (PHASE-8.1 fix, #478): when provided
    and the row is unclaimed (``doctor_id`` NULL) with ``allow_unclaimed``
    false, the guard resolves the case's pre-summary to its assigned doctor
    (pick, #443) and allows the read only if that doctor is the caller. The
    default ``None`` preserves today's behavior for every other caller, so
    no global ``allow_unclaimed`` flip is needed.

    Returns the loaded row so callers can use ``row.patient_id``,
    ``row.stage`` etc. without a second query.
    """
    row = (await connection.execute(select(care_cases).where(care_cases.c.id == case_id))).first()
    if row is None:
        raise CareNotFoundError(f"case {case_id} not found for doctor {doctor_id}")
    if row.doctor_id is None:
        if not allow_unclaimed:
            pre_summary_id = row.pre_summary_id
            if pre_summary_id is None:
                raise CareNotFoundError(f"case {case_id} not found for doctor {doctor_id}")
            if assigned_doctor_of is not None:
                assigned_doctor = await assigned_doctor_of(int(pre_summary_id))
            else:
                assigned_doctor = None
            if assigned_doctor != doctor_id:
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

            has_input = await _case_ids_with_doctor_input(connection, {case_id})

            view = CaseDetailView(
                case_id=case_id,
                patient_id=int(row.patient_id),
                doctor_id=doctor_id,
                pre_summary_id=(
                    int(row.pre_summary_id) if row.pre_summary_id is not None else None
                ),
                stage=next_state.stage.value,
                forced_review=bool(row.forced_review),
                has_doctor_input=case_id in has_input,
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

            has_input = await _case_ids_with_doctor_input(connection, {case_id})

            view = CaseDetailView(
                case_id=case_id,
                patient_id=int(row.patient_id),
                doctor_id=doctor_id,
                pre_summary_id=(
                    int(row.pre_summary_id) if row.pre_summary_id is not None else None
                ),
                stage=next_state.stage.value,
                forced_review=bool(row.forced_review),
                has_doctor_input=case_id in has_input,
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

        Doctor-scoped: raises unless the case belongs to ``doctor_id`` or is a
        born-but-unclaimed case whose intake assigned it to ``doctor_id``
        (PHASE-8.1 fix, #478) - the assignee opens the workspace before the
        consult-complete handshake claims the case. A foreign or unassigned
        doctor still gets ``CareNotFoundError``.

        Raises :class:`CareNotFoundError` when no case exists for the doctor.
        """
        async with self._engine.begin() as connection:
            row = await check_case_ownership(
                connection,
                doctor_id=doctor_id,
                case_id=case_id,
                assigned_doctor_of=assigned_doctor_of_resolver(self._intake_facade),
            )
            has_input = await _case_ids_with_doctor_input(connection, {case_id})

        return _to_case_detail(row, has_doctor_input=case_id in has_input)

    async def list_doctor_cases(
        self,
        *,
        doctor_id: int,
    ) -> list[CaseDetailView]:
        """List the doctor's open care cases, oldest first (non-closed only).

        Merges the doctor's claimed non-closed cases (``doctor_id == doctor``)
        with born-but-unclaimed non-closed cases (``doctor_id IS NULL``) whose
        pre-summary the intake assigned to this doctor (pick, #443,
        PHASE-8.1 fix #478), so an assigned case is reachable before the
        consult-complete handshake claims it. The merge happens in the facade
        (no cross-schema join - module isolation rule); the intake assignment
        resolves through the legal ``IntakeFacade`` seam. Claim semantics are
        unchanged: ``mark_consult_complete`` stays the single claim path.
        Closed cases and cases assigned to another doctor never appear; the
        merged feed keeps the existing ``created_at`` ascending order.
        """
        async with self._engine.begin() as connection:
            claimed_rows = (
                await connection.execute(
                    select(care_cases)
                    .where(
                        care_cases.c.doctor_id == doctor_id,
                        care_cases.c.stage != CaseStage.CLOSED.value,
                    )
                    .order_by(care_cases.c.created_at.asc())
                )
            ).all()

            unclaimed_rows = (
                await connection.execute(
                    select(care_cases)
                    .where(
                        care_cases.c.doctor_id.is_(None),
                        care_cases.c.stage != CaseStage.CLOSED.value,
                    )
                    .order_by(care_cases.c.created_at.asc())
                )
            ).all()

            declared_ids = {int(row.id) for row in claimed_rows} | {
                int(row.id) for row in unclaimed_rows if row.pre_summary_id is not None
            }
            ids_with_input = await _case_ids_with_doctor_input(connection, declared_ids)

        assigned: dict[int, int | None] = {}
        if unclaimed_rows:
            pre_summary_ids = [
                int(row.pre_summary_id) for row in unclaimed_rows if row.pre_summary_id is not None
            ]
            if pre_summary_ids:
                assigned = await self._intake_facade.assigned_partner_for_pre_summaries(
                    pre_summary_ids
                )

        views = [
            _to_case_detail(row, has_doctor_input=int(row.id) in ids_with_input)
            for row in claimed_rows
        ]
        views.extend(
            _to_case_detail(row, has_doctor_input=int(row.id) in ids_with_input)
            for row in unclaimed_rows
            if row.pre_summary_id is not None and assigned.get(int(row.pre_summary_id)) == doctor_id
        )
        views.sort(key=lambda view: view.created_at)
        return views

    async def submit_doctor_input(
        self,
        *,
        doctor_id: int,
        case_id: int,
        input_type: Literal["voice", "photo", "text"],
        media_ref: str,
        sensitive_class: Literal["normal", "sensitive", "restricted"] | None = None,
    ) -> DoctorInputResult:
        """Record a voice note, photo, or typed addendum as prescribing input.

        Doctor-scoped (api-standards S6, security-phii-standards S3): the case
        must belong to the authenticated ``doctor_id``, so a doctor can never
        attach input to another doctor's case. The input type and sensitive
        class are typed to the canonical vocabulary so an invalid value is
        rejected at the boundary, before any write.

        Validates the case state: an input attaches only to an open
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
