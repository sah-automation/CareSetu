"""MOD-006: HTTP adapters for the care planning module (PHASE-8 T06, #422).

Thin adapters (api-standards S1): parse the typed request, call the owning
``care`` facade, return the typed result. Routes read the facade from app
state and contain no business logic - route-boundary tests use a stubbed
facade.

Every expected failure answers the shared error envelope at the top level
(api-standards S2); ``register_error_handlers`` maps care domain errors to
that envelope. The doctor RBAC guard (``require_partner`` + the resolved
partner profile) admits only an authenticated partner-scoped caller whose
profile is a doctor (partner scope + ``partner_type == "doctor"``) in the
``Active`` lifecycle state - the patient and lab/chemist partner scopes and
inactive partner profiles are refused with 403 at the edge, matching the
intake review route convention. ``doctor_id`` returned from the guard is the
partner's MOD-001 gateway identity (``partner_id``) every facade write
records for attribution.
"""

from __future__ import annotations

import logging
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, FastAPI, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import SQLAlchemyError

from app.gateway.errors import (
    AuthenticationRequiredError,
    InsufficientScopeError,
    error_response,
)
from app.gateway.idempotency import run_idempotent
from app.gateway.principal import Principal
from app.gateway.rbac import require_partner
from app.gateway.trace import resolve_trace_id
from modules.care.care_models import (
    CaseDetailView,
    DoctorInputResult,
    PrescriptionDetailView,
    RxItemInput,
)
from modules.care.case_facade import CaseConsoleFacade
from modules.care.domain.exceptions import (
    CareCaseClosedError,
    CareError,
    CareNotFoundError,
    CareRxDraftCapReachedError,
    CareRxDraftConsentDeniedError,
    CareRxNoDoctorInputError,
    CareValidationError,
    IllegalCareTransitionError,
    IllegalPrescriptionTransitionError,
)
from modules.care.rx_facade import PrescriptionFacade
from modules.partner.facade import PartnerFacade

logger = logging.getLogger(__name__)

MESSAGE_CARE_VALIDATION_ERROR = "care validation failed; check the request and try again"
MESSAGE_CARE_RX_CONSENT_DENIED = (
    "consent for the patient's prescription history is required for AI drafting"
)
MESSAGE_CARE_RX_NO_DOCTOR_INPUT = "AI drafting needs doctor input to draft from"
MESSAGE_CARE_RX_DRAFT_CAP_REACHED = "the AI drafting cap (2 rejected drafts) has been reached"
MESSAGE_CARE_CASE_CLOSED = "the care case is closed"

router = APIRouter(prefix="/v1/care", tags=["care"])


def _resolve_subject_id(principal: Principal) -> int:
    """Extract the numeric subject id from the JWT principal.

    A non-numeric subject id indicates an invalid token; the caller is
    refused with 401 instead of a 500 from the ``int()`` cast.
    """
    try:
        return int(principal.subject_id)
    except (ValueError, TypeError) as err:
        raise AuthenticationRequiredError("invalid subject id in token") from err


async def _require_doctor(request: Request, account: Principal) -> int:
    """Resolve the caller to their doctor partner profile id.

    The partner RBAC convention (partner scope + ``partner_type == "doctor"``,
    matching the intake review route): ``require_partner`` admits any partner-
    scoped caller at the dependency, then the principal is resolved to its
    partner profile and a non-doctor partner is refused with 403. An active-
    partner check refuses a profile not yet ``Active`` with 403 too - only a
    licensed, active doctor may drive the consult-complete handshake and the
    prescription workflow.
    """
    partner = await cast(PartnerFacade, request.app.state.partner_facade).resolve_partner(
        _resolve_subject_id(account)
    )
    if partner.partner_type != "doctor":
        raise InsufficientScopeError("the doctor role is required for this route")
    if partner.status != "Active":
        raise InsufficientScopeError("an active partner profile is required for this route")
    return partner.partner_id


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class DoctorInputRequest(BaseModel):
    """Body of ``POST /v1/care/cases/{case_id}/doctor-input``: doctor intake input.

    ``input_type`` and ``sensitive_class`` are typed to the canonical
    vocabulary (``CANONICAL_INPUT_TYPES`` / ``CANONICAL_SENSITIVE_CLASSES``)
    so an invalid value is rejected at the boundary, before any write. The
    ``media_ref`` is the durable clip ticket for the voice note or photo.
    """

    model_config = ConfigDict(extra="forbid")

    input_type: Literal["voice", "photo"] = Field(description="Input kind: voice note or photo")
    media_ref: str = Field(description="Clip ticket of the uploaded voice note or photo")
    sensitive_class: Literal["normal", "sensitive", "restricted"] | None = Field(
        default=None,
        description="Declared sensitivity of the input content",
    )


class RxDraftRequest(BaseModel):
    """Body of ``POST /v1/care/cases/{case_id}/rx/draft``: create a rx draft.

    ``source="ai_draft"`` requests the consent-gated AI draft from the intake
    drafting leg (no ``items`` - the raw AI draft is never approvable);
    ``source="manual"`` captures the doctor's ``items`` directly as the
    working revision.
    """

    model_config = ConfigDict(extra="forbid")

    source: Literal["ai_draft", "manual"] = Field(description="Draft origin: AI or manual")
    items: list[RxItemInput] | None = Field(
        default=None,
        description="Working-revision line items (required for source=manual)",
    )


class RxRevisionRequest(BaseModel):
    """Body of ``POST /v1/care/cases/{case_id}/rx/{rx_id}/revision``.

    The doctor's full working revision: ``rx_items`` replaces the current
    ``Draft``/``DoctorReviewed`` row's items (delete + re-insert) and ends in
    ``doctor_reviewed``.
    """

    model_config = ConfigDict(extra="forbid")

    rx_items: list[RxItemInput] = Field(description="Line items of the new working revision")


class RxApproveRequest(BaseModel):
    """Body of ``POST /v1/care/cases/{case_id}/rx/{rx_id}/approve``.

    ``verification_declaration`` records the doctor's mandatory double-check
    (CONTEXT.md glossary): approval is refused server-side unless ``true``.
    """

    model_config = ConfigDict(extra="forbid")

    verification_declaration: bool = Field(
        default=False,
        description="Doctor's verification declaration; true is required for approval",
    )


class RxRejectRequest(BaseModel):
    """Body of ``POST /v1/care/cases/{case_id}/rx/{rx_id}/reject``.

    ``reason`` is machine-enforced non-empty by the prescription state
    machine and recorded on ``care_rx_approvals``.
    """

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(description="Why the draft is rejected (recorded for the draft retry)")


class CaseCloseRequest(BaseModel):
    """Body of ``POST /v1/care/cases/{case_id}/close``.

    ``close_reason`` is required and typed to the canonical close-reason
    vocabulary (``CANONICAL_CLOSE_REASONS``), so a missing or invalid value
    is rejected at the boundary before any write.
    """

    model_config = ConfigDict(extra="forbid")

    close_reason: Literal[
        "patient_withdrawn", "doctor_rejected", "no_show", "duplicate", "system"
    ] = Field(description="Why the visit is closed without a prescription")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/cases/{case_id}/consult-complete",
    response_model=CaseDetailView,
    status_code=status.HTTP_200_OK,
    summary="Close the off-platform consult on-platform (doctor only)",
)
async def mark_consult_complete(
    request: Request,
    account: Annotated[Principal, Depends(require_partner)],
    case_id: int,
) -> CaseDetailView:
    """Record the consult-complete milestone and open the prescription stage.

    Thin doctor-scoped adapter: the ``require_partner`` gate admits any
    partner-scoped caller, then ``_require_doctor`` refuses a non-doctor or
    non-active profile with 403. The facade runs the ``PreSummary ->
    PrescriptionPending`` transition (gated on the finalized pre-summary) and
    publishes ``case.consult_complete`` in the same transaction.
    """
    facade = cast(CaseConsoleFacade, request.app.state.care_console_facade)
    doctor_id = await _require_doctor(request, account)
    return await run_idempotent(
        request, lambda: facade.mark_consult_complete(doctor_id=doctor_id, case_id=case_id)
    )


@router.get(
    "/cases",
    response_model=list[CaseDetailView],
    status_code=status.HTTP_200_OK,
    summary="List the doctor's open care cases (doctor only)",
)
async def list_open_cases(
    request: Request,
    account: Annotated[Principal, Depends(require_partner)],
) -> list[CaseDetailView]:
    """List the doctor's open (non-closed) care cases, oldest first (US-26).

    Thin doctor-scoped adapter: the facade returns the typed ``CaseDetailView``
    pending list the doctor works from, ordered by creation time ascending.
    """
    facade = cast(CaseConsoleFacade, request.app.state.care_console_facade)
    doctor_id = await _require_doctor(request, account)
    return await facade.list_doctor_cases(doctor_id=doctor_id)


@router.get(
    "/cases/{case_id}",
    response_model=CaseDetailView,
    status_code=status.HTTP_200_OK,
    summary="Get a doctor's care case detail (doctor only)",
)
async def get_case(
    request: Request,
    account: Annotated[Principal, Depends(require_partner)],
    case_id: int,
) -> CaseDetailView:
    """Read one care case belonging to the doctor.

    Thin doctor-scoped adapter: the facade raises ``CareNotFoundError``
    unless the case belongs to the doctor, so a doctor can never read another
    doctor's case.
    """
    facade = cast(CaseConsoleFacade, request.app.state.care_console_facade)
    doctor_id = await _require_doctor(request, account)
    return await facade.get_case(doctor_id=doctor_id, case_id=case_id)


@router.post(
    "/cases/{case_id}/doctor-input",
    response_model=DoctorInputResult,
    status_code=status.HTTP_200_OK,
    summary="Record a doctor voice note or photo as prescribing input (doctor only)",
)
async def submit_doctor_input(
    request: Request,
    account: Annotated[Principal, Depends(require_partner)],
    case_id: int,
    body: DoctorInputRequest,
) -> DoctorInputResult:
    """Attach a voice note or photo to a case before drafting (US-27).

    Thin doctor-scoped adapter: input type/sensitivity are typed at the
    boundary; the facade enforces case ownership and rejects a closed case.
    """
    facade = cast(CaseConsoleFacade, request.app.state.care_console_facade)
    doctor_id = await _require_doctor(request, account)
    return await run_idempotent(
        request,
        lambda: facade.submit_doctor_input(
            doctor_id=doctor_id,
            case_id=case_id,
            input_type=body.input_type,
            media_ref=body.media_ref,
            sensitive_class=body.sensitive_class,
        ),
    )


@router.post(
    "/cases/{case_id}/rx/draft",
    response_model=PrescriptionDetailView,
    status_code=status.HTTP_200_OK,
    summary="Create an AI or manual prescription draft (doctor only)",
)
async def create_rx_draft(
    request: Request,
    account: Annotated[Principal, Depends(require_partner)],
    case_id: int,
    body: RxDraftRequest,
) -> PrescriptionDetailView:
    """Create a prescription draft for the case (AI-drafted or manual).

    Thin doctor-scoped adapter: ``source`` is typed at the boundary; the
    facade enforces case ownership, the closed-case rule, and the AI drafting
    cap, and runs the consent-gated history read for ``ai_draft``.
    """
    facade = cast(PrescriptionFacade, request.app.state.prescription_facade)
    doctor_id = await _require_doctor(request, account)
    return await run_idempotent(
        request,
        lambda: facade.create_rx_draft(
            case_id=case_id,
            doctor_id=doctor_id,
            source=body.source,
            items=body.items,
        ),
    )


@router.post(
    "/cases/{case_id}/rx/{rx_id}/revision",
    response_model=PrescriptionDetailView,
    status_code=status.HTTP_200_OK,
    summary="Save the doctor's edited prescription revision (doctor only)",
)
async def save_rx_revision(
    request: Request,
    account: Annotated[Principal, Depends(require_partner)],
    case_id: int,
    rx_id: int,
    body: RxRevisionRequest,
) -> PrescriptionDetailView:
    """Write the doctor's working revision (review-and-edit, US-28).

    Thin doctor-scoped adapter: the facade replaces the prescription's items,
    moves it to ``doctor_reviewed``, and publishes ``prescription.reviewed``.
    """
    facade = cast(PrescriptionFacade, request.app.state.prescription_facade)
    doctor_id = await _require_doctor(request, account)
    return await run_idempotent(
        request,
        lambda: facade.save_rx_revision(
            case_id=case_id,
            rx_id=rx_id,
            doctor_id=doctor_id,
            rx_items=body.rx_items,
        ),
    )


@router.post(
    "/cases/{case_id}/rx/{rx_id}/approve",
    response_model=PrescriptionDetailView,
    status_code=status.HTTP_200_OK,
    summary="Approve and issue a prescription with verification declaration (doctor only)",
)
async def approve_prescription(
    request: Request,
    account: Annotated[Principal, Depends(require_partner)],
    case_id: int,
    rx_id: int,
    body: RxApproveRequest,
) -> PrescriptionDetailView:
    """Freeze the saved revision and issue the e-prescription (US-29).

    Thin doctor-scoped adapter: the ``verification_declaration`` gate and the
    no-approval-without-revision rule live in the facade; approval publishes
    ``prescription.approved`` and ``prescription.issued`` in one transaction.
    """
    facade = cast(PrescriptionFacade, request.app.state.prescription_facade)
    doctor_id = await _require_doctor(request, account)
    return await run_idempotent(
        request,
        lambda: facade.approve_prescription(
            case_id=case_id,
            rx_id=rx_id,
            doctor_id=doctor_id,
            verification_declaration=body.verification_declaration,
        ),
    )


@router.post(
    "/cases/{case_id}/rx/{rx_id}/reject",
    response_model=PrescriptionDetailView,
    status_code=status.HTTP_200_OK,
    summary="Reject a prescription draft with a reason (doctor only)",
)
async def reject_prescription(
    request: Request,
    account: Annotated[Principal, Depends(require_partner)],
    case_id: int,
    rx_id: int,
    body: RxRejectRequest,
) -> PrescriptionDetailView:
    """Reject a draft, record the reason, never auto-close the case.

    Thin doctor-scoped adapter: a non-empty ``reason`` is machine-enforced;
    the rejection moves the prescription to ``rejected`` (draft retry allowed,
    cap-gated) and leaves the case stage untouched.
    """
    facade = cast(PrescriptionFacade, request.app.state.prescription_facade)
    doctor_id = await _require_doctor(request, account)
    return await run_idempotent(
        request,
        lambda: facade.reject_prescription(
            case_id=case_id,
            rx_id=rx_id,
            doctor_id=doctor_id,
            reason=body.reason,
        ),
    )


@router.get(
    "/prescriptions/{rx_id}",
    response_model=PrescriptionDetailView,
    status_code=status.HTTP_200_OK,
    summary="Get an approved-and-issued e-prescription (doctor only)",
)
async def get_approved_prescription(
    request: Request,
    account: Annotated[Principal, Depends(require_partner)],
    rx_id: int,
) -> PrescriptionDetailView:
    """Read an issued e-prescription - the Phase-10 source of truth.

    Thin doctor-scoped adapter: serves ONLY approved-and-issued prescriptions
    (status ``issued`` and ``issued_at`` set); a draft, rejected, or not-yet-
    issued prescription reads as ``CARE_NOT_FOUND`` from the facade. The
    authenticated ``doctor_id`` is forwarded so the facade refuses a foreign
    doctor's prescription with the not-found envelope. The issued projection
    already carries the doctor's display name (``attributed_doctor_name``)
    resolved by the care facade's partner seam (#495, T10c).
    """
    facade = cast(PrescriptionFacade, request.app.state.prescription_facade)
    doctor_id = await _require_doctor(request, account)
    return await facade.get_approved_prescription(rx_id=rx_id, doctor_id=doctor_id)


@router.get(
    "/cases/{case_id}/rx/current",
    response_model=PrescriptionDetailView,
    status_code=status.HTTP_200_OK,
    summary="Get the doctor's in-progress prescription revision (doctor only)",
)
async def get_working_prescription(
    request: Request,
    account: Annotated[Principal, Depends(require_partner)],
    case_id: int,
) -> PrescriptionDetailView:
    """Read the in-progress prescription revision for a pending case.

    Thin doctor-scoped adapter: the facade serves ONLY the working revision -
    ``Draft``, ``DoctorReviewed``, or ``Rejected`` - so a pending case's
    in-progress prescription work survives a hard refresh (PHASE-8.1 US-23).
    An issued prescription reads as ``CARE_NOT_FOUND`` from here; the
    approved read (``get_approved_prescription``) remains the single
    issued-artifact path, and a foreign or unassigned doctor's case is
    refused with the not-found envelope.
    """
    facade = cast(PrescriptionFacade, request.app.state.prescription_facade)
    doctor_id = await _require_doctor(request, account)
    return await facade.get_working_prescription(case_id=case_id, doctor_id=doctor_id)


@router.post(
    "/cases/{case_id}/close",
    response_model=CaseDetailView,
    status_code=status.HTTP_200_OK,
    summary="Close a visit without a prescription (doctor only)",
)
async def close_case_without_rx(
    request: Request,
    account: Annotated[Principal, Depends(require_partner)],
    case_id: int,
    body: CaseCloseRequest,
) -> CaseDetailView:
    """Close a visit with no prescription in one deliberate action.

    Thin doctor-scoped adapter: a required ``close_reason`` is validated
    by the request body and the case machine. The transition is legal only
    from ``PrescriptionPending``; any other stage raises
    ``ILLEGAL_CARE_TRANSITION``. Publishes ``case.closed`` in the same
    transaction as the close write.
    """
    facade = cast(CaseConsoleFacade, request.app.state.care_console_facade)
    doctor_id = await _require_doctor(request, account)
    return await run_idempotent(
        request,
        lambda: facade.close_case_without_rx(
            case_id=case_id,
            doctor_id=doctor_id,
            close_reason=body.close_reason,
        ),
    )


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------


def register_error_handlers(app: FastAPI) -> None:
    """Attach the MOD-006 error envelope to every expected care failure.

    Only the care module's own domain errors are mapped here. Validation
    errors (missing/invalid fields) and gateway auth errors are handled by
    the iam and gateway module handlers respectively.
    """

    async def _care_not_found(request: Request, exc: Exception) -> JSONResponse:
        del exc
        return error_response(
            status.HTTP_404_NOT_FOUND,
            "CARE_NOT_FOUND",
            "care record not found or not owned by the caller",
            log_tag="care_route",
            request=request,
        )

    async def _care_validation_error(request: Request, exc: Exception) -> JSONResponse:
        care_exc = cast(CareValidationError, exc)
        logger.warning(
            "care_validation_error trace_id=%s detail=%s",
            resolve_trace_id(request),
            care_exc,
        )
        return error_response(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "CARE_VALIDATION_ERROR",
            MESSAGE_CARE_VALIDATION_ERROR,
            log_tag="care_route",
            request=request,
        )

    async def _illegal_care_transition(request: Request, exc: Exception) -> JSONResponse:
        del exc
        return error_response(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "ILLEGAL_CARE_TRANSITION",
            "the requested care action is illegal in the current state",
            log_tag="care_route",
            request=request,
        )

    async def _illegal_prescription_transition(request: Request, exc: Exception) -> JSONResponse:
        del exc
        return error_response(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "ILLEGAL_PRESCRIPTION_TRANSITION",
            "the requested prescription action is illegal in the current state",
            log_tag="care_route",
            request=request,
        )

    async def _rx_consent_denied(request: Request, exc: Exception) -> JSONResponse:
        del exc
        return error_response(
            status.HTTP_403_FORBIDDEN,
            "CARE_RX_CONSENT_DENIED",
            MESSAGE_CARE_RX_CONSENT_DENIED,
            log_tag="care_route",
            request=request,
        )

    async def _rx_no_doctor_input(request: Request, exc: Exception) -> JSONResponse:
        del exc
        return error_response(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "CARE_RX_NO_DOCTOR_INPUT",
            MESSAGE_CARE_RX_NO_DOCTOR_INPUT,
            log_tag="care_route",
            request=request,
        )

    async def _rx_draft_cap_reached(request: Request, exc: Exception) -> JSONResponse:
        del exc
        return error_response(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "CARE_RX_DRAFT_CAP_REACHED",
            MESSAGE_CARE_RX_DRAFT_CAP_REACHED,
            log_tag="care_route",
            request=request,
        )

    async def _case_closed(request: Request, exc: Exception) -> JSONResponse:
        del exc
        return error_response(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "CARE_CASE_CLOSED",
            MESSAGE_CARE_CASE_CLOSED,
            log_tag="care_route",
            request=request,
        )

    async def _care_error(request: Request, exc: Exception) -> JSONResponse:
        del exc
        return error_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "CARE_INTERNAL",
            "Internal care error",
            log_tag="care_route",
            request=request,
        )

    async def _sqlalchemy_error(request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "care_db_error trace_id=%s path=%s exc=%s",
            resolve_trace_id(request),
            request.url.path,
            exc,
        )
        return error_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "CARE_INTERNAL",
            "Internal care error",
            log_tag="care_route",
            request=request,
        )

    app.add_exception_handler(CareNotFoundError, _care_not_found)
    app.add_exception_handler(CareValidationError, _care_validation_error)
    app.add_exception_handler(CareRxDraftConsentDeniedError, _rx_consent_denied)
    app.add_exception_handler(CareRxNoDoctorInputError, _rx_no_doctor_input)
    app.add_exception_handler(CareRxDraftCapReachedError, _rx_draft_cap_reached)
    app.add_exception_handler(CareCaseClosedError, _case_closed)
    app.add_exception_handler(IllegalCareTransitionError, _illegal_care_transition)
    app.add_exception_handler(IllegalPrescriptionTransitionError, _illegal_prescription_transition)
    app.add_exception_handler(CareError, _care_error)
    app.add_exception_handler(SQLAlchemyError, _sqlalchemy_error)
