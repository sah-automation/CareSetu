"""MOD-006 Care planning: typed public sync API (PHASE-8 T04/T05, #420/#421).

The only legal cross-module import target for the ``care`` module
(coding-standards S2, ADR-0003). This module is a **thin compatibility
wrapper** that delegates to:

- :class:`~modules.care.case_facade.CaseConsoleFacade` - case state-machine
  operations (consultation lifecycle, case reads, doctor input, closure)
- :class:`~modules.care.rx_facade.PrescriptionFacade` - prescription
  state-machine operations (AI/manual drafting, revision, approval, rejection,
  read-back)

All state-changing writes commit their ``care_outbox`` event in the SAME
transaction as the domain write (ADR-0002 S1), so a crash between state
change and dispatch cannot lose the event.

The drafting seam is consent-gated (NFR-SEC-006): any use of the patient's
record history for an AI draft goes through ``HealthFacade.read_consented_history``
(which calls ``ConsentFacade.check_consent``), fail-closed - the facade never
performs a raw history read.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from modules.care.care_models import (
    CaseDetailView,
    DoctorInputResult,
    PrescriptionDetailView,
    RxItemInput,
)
from modules.care.case_facade import CaseConsoleFacade

# Re-export the constant so existing test imports stay untouched:
#   from modules.care.facade import RX_DRAFT_HISTORY_SCOPE
from modules.care.rx_facade import (
    RX_DRAFT_HISTORY_SCOPE,  # noqa: F401
    PrescriptionFacade,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

    from modules.health.facade import HealthFacade
    from modules.intake.facade import IntakeFacade


class CareFacade:
    """Typed public facade for the care module (consultation + prescription).

    Thin compatibility wrapper delegating to :class:`CaseConsoleFacade`
    (case state machine) and :class:`PrescriptionFacade` (prescription
    state machine). Preserves the original constructor signature and all
    public method signatures so app wiring, routes, and every existing
    test stay green untouched.
    """

    def __init__(
        self,
        engine: AsyncEngine,
        *,
        intake_facade: IntakeFacade,
        health_facade: HealthFacade | None = None,
    ) -> None:
        self._case = CaseConsoleFacade(engine, intake_facade=intake_facade)
        self._rx = PrescriptionFacade(
            engine, intake_facade=intake_facade, health_facade=health_facade
        )

    # -----------------------------------------------------------------
    # Case state-machine operations (delegate to CaseConsoleFacade)
    # -----------------------------------------------------------------

    async def mark_consult_complete(
        self,
        *,
        doctor_id: int,
        case_id: int,
    ) -> CaseDetailView:
        """Close the off-platform consult on-platform in one action."""
        return await self._case.mark_consult_complete(doctor_id=doctor_id, case_id=case_id)

    async def close_case_without_rx(
        self,
        *,
        doctor_id: int,
        case_id: int,
        close_reason: str,
    ) -> CaseDetailView:
        """Close a visit with no prescription in one deliberate action."""
        return await self._case.close_case_without_rx(
            doctor_id=doctor_id, case_id=case_id, close_reason=close_reason
        )

    async def get_case(
        self,
        *,
        doctor_id: int,
        case_id: int,
    ) -> CaseDetailView:
        """Read the doctor's care case detail."""
        return await self._case.get_case(doctor_id=doctor_id, case_id=case_id)

    async def list_doctor_cases(
        self,
        *,
        doctor_id: int,
    ) -> list[CaseDetailView]:
        """List the doctor's open care cases, oldest first (non-closed only)."""
        return await self._case.list_doctor_cases(doctor_id=doctor_id)

    async def submit_doctor_input(
        self,
        *,
        doctor_id: int,
        case_id: int,
        input_type: Literal["voice", "photo"],
        media_ref: str,
        sensitive_class: Literal["normal", "sensitive", "restricted"] | None = None,
    ) -> DoctorInputResult:
        """Record a voice note or photo as prescribing input for the case."""
        return await self._case.submit_doctor_input(
            doctor_id=doctor_id,
            case_id=case_id,
            input_type=input_type,
            media_ref=media_ref,
            sensitive_class=sensitive_class,
        )

    # -----------------------------------------------------------------
    # Prescription state-machine operations (delegate to PrescriptionFacade)
    # -----------------------------------------------------------------

    async def create_rx_draft(
        self,
        *,
        case_id: int,
        doctor_id: int,
        source: Literal["ai_draft", "manual"],
        items: list[RxItemInput] | None = None,
    ) -> PrescriptionDetailView:
        """Create a prescription draft for the case (AI-drafted or manual)."""
        return await self._rx.create_rx_draft(
            case_id=case_id, doctor_id=doctor_id, source=source, items=items
        )

    async def save_rx_revision(
        self,
        *,
        case_id: int,
        rx_id: int,
        doctor_id: int,
        rx_items: list[RxItemInput],
    ) -> PrescriptionDetailView:
        """Write the doctor's working revision to ``care_rx_items``."""
        return await self._rx.save_rx_revision(
            case_id=case_id, rx_id=rx_id, doctor_id=doctor_id, rx_items=rx_items
        )

    async def approve_prescription(
        self,
        *,
        case_id: int,
        rx_id: int,
        doctor_id: int,
        verification_declaration: bool = False,
    ) -> PrescriptionDetailView:
        """Revision-freeze approval: issue exactly the saved working revision."""
        return await self._rx.approve_prescription(
            case_id=case_id,
            rx_id=rx_id,
            doctor_id=doctor_id,
            verification_declaration=verification_declaration,
        )

    async def reject_prescription(
        self,
        *,
        case_id: int,
        rx_id: int,
        doctor_id: int,
        reason: str,
    ) -> PrescriptionDetailView:
        """Reject a draft; record the reason; never auto-close the case."""
        return await self._rx.reject_prescription(
            case_id=case_id, rx_id=rx_id, doctor_id=doctor_id, reason=reason
        )

    async def get_approved_prescription(
        self, *, rx_id: int, doctor_id: int
    ) -> PrescriptionDetailView:
        """Read an issued e-prescription - the Phase-10 source of truth."""
        return await self._rx.get_approved_prescription(rx_id=rx_id, doctor_id=doctor_id)
