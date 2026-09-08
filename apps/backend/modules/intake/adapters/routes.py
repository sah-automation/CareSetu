"""MOD-005: HTTP adapters for the patient intake module (PHASE-7 T12, #356).

Thin adapters (api-standards S1): parse the typed request, call the intake
facade, return the typed result. Routes read the facade from app state and
contain no business logic - route-boundary tests use a stubbed facade.

Every expected failure answers the shared error envelope at the top level
(api-standards S2); ``register_error_handlers`` maps intake domain errors to
that envelope. The patient RBAC guard (``require_patient``) rejects unauthenticated
callers (401) and non-patient scopes (403) at the edge - partner/doctor-scope
callers cannot hit patient intake routes. The doctor review route (PHASE-7 T13,
#357) is the exception: ``require_partner`` admits any partner-scoped caller,
then the resolved partner profile must be a doctor (partner scope +
``partner_type == "doctor"``) or the caller is refused with 403.
"""

from __future__ import annotations

from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, FastAPI, File, Query, Request, UploadFile, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.gateway.errors import InsufficientScopeError, error_response
from app.gateway.principal import Principal
from app.gateway.rbac import require_partner, require_patient
from modules.intake.domain.exceptions import (
    IllegalIntakeTransitionError,
    IllegalPreSummaryTransitionError,
    IntakeError,
    IntakeNotFoundError,
    IntakeValidationError,
    MediaTransferError,
)
from modules.intake.facade import IntakeFacade
from modules.intake.intake_models import (
    IntakeDetailView,
    IntakeSubmitResult,
    MediaFile,
    MediaUploadRef,
    PatientEditsResult,
    PreSummaryReviewResult,
    PreSummaryView,
    ReRecordResult,
)
from modules.partner.facade import PartnerFacade

router = APIRouter(prefix="/v1/intake", tags=["intake"])


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class SubmitIntakeRequest(BaseModel):
    """Body of ``POST /v1/intake/submit``: capture a symptom intake (PHASE-7 T07).

    Exactly one of ``text`` (text mode) or ``media_ref`` (voice mode, from
    ``upload_media``) must be provided, matching the declared ``mode``.
    The text cap (2000 chars) and one-mode-per-intake enforcement live in the
    facade; the route is a thin adapter.
    """

    model_config = ConfigDict(extra="forbid")

    mode: Literal["voice", "text"] = Field(description="Capture mode: voice or text")
    language: Literal["hi", "en"] = Field(description="Declared language: Hindi or English")
    text: str | None = Field(
        default=None,
        description="Text content for text-mode intake",
    )
    media_ref: MediaUploadRef | None = Field(
        default=None,
        description="Opaque clip ticket from upload_media for voice-mode intake",
    )


class ReRecordRequest(BaseModel):
    """Body of ``POST /v1/intake/{intake_id}/re-record``: re-record a voice intake.

    ``media_ref`` is the fresh clip ticket from ``upload_media``. The facade
    enforces the attempt cap server-side (MAX_RECORD_ATTEMPTS = 3).
    """

    model_config = ConfigDict(extra="forbid")

    media_ref: MediaUploadRef = Field(description="Fresh clip ticket from upload_media")


class PatientEditsRequest(BaseModel):
    """Body of ``POST /v1/intake/{intake_id}/patient-edits``: save patient corrections.

    ``fields`` maps field names to corrected values - informational corrections
    that are advice to the doctor, never mutating the AI structured_fields.
    """

    model_config = ConfigDict(extra="forbid")

    fields: dict[str, object] = Field(
        min_length=1,
        description="Field name -> corrected value mappings",
    )


class PreSummaryReviewRequest(BaseModel):
    """Body of ``POST /v1/intake/{intake_id}/review``: attributed doctor review.

    ``corrections`` maps the fields the doctor edited to their corrected
    values (PHASE-7 T09, #353). The doctor's edits win over the AI extraction
    and overlay the original ``structured_fields`` to produce the reviewed
    copy. An omitted or empty ``corrections`` is a review with no edits - the
    low-confidence gate still moves the draft to ``Reviewed``.
    """

    model_config = ConfigDict(extra="forbid")

    corrections: dict[str, object] | None = Field(
        default=None,
        description="Field name -> corrected value mappings (doctor edits win)",
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/submit",
    response_model=IntakeSubmitResult,
    status_code=status.HTTP_200_OK,
    summary="Submit a symptom intake (text or voice, patient only)",
)
async def submit_intake(
    request: Request,
    _account: Annotated[Principal, Depends(require_patient)],
    body: SubmitIntakeRequest,
) -> IntakeSubmitResult:
    """Capture a symptom intake and emit ``intake.captured``.

    Thin patient-scoped adapter: delegates mode/text/media validation and
    the atomic row + outbox commit to the facade. The patient identity
    (``account.subject_id``) is the owner scope.
    """
    facade = cast(IntakeFacade, request.app.state.intake_facade)
    return await facade.submit_intake(
        patient_id=int(_account.subject_id),
        mode=body.mode,
        language=body.language,
        text=body.text,
        media_ref=body.media_ref,
    )


@router.post(
    "/upload-media",
    response_model=MediaUploadRef,
    status_code=status.HTTP_200_OK,
    summary="Upload an audio clip for a voice intake (patient only)",
)
async def upload_media(
    request: Request,
    account: Annotated[Principal, Depends(require_patient)],
    file: UploadFile = File(description="Audio file to upload"),  # noqa: B008
    audio_duration_ms: Annotated[int | None, Query(ge=0)] = None,
    file_size_bytes: Annotated[int | None, Query(ge=0)] = None,
) -> MediaUploadRef:
    """Upload an audio clip to the object store with upload resilience.

    Thin patient-scoped adapter: reads the uploaded file bytes, wraps them
    in a ``MediaFile``, and delegates to the facade. The facade encrypts
    at rest and retries on transient failure (NFR-PERF-002). Returns the
    opaque clip ticket for use with ``submit_intake`` or ``re_record``.
    """
    data = await file.read()
    facade = cast(IntakeFacade, request.app.state.intake_facade)
    media_file = MediaFile(
        data=data,
        filename=file.filename or "recording.webm",
        media_type=file.content_type or "audio",
        audio_duration_ms=audio_duration_ms,
        file_size_bytes=file_size_bytes or len(data),
        record_attempt=1,
    )
    return await facade.upload_intake_media(
        patient_id=int(account.subject_id),
        file=media_file,
    )


@router.post(
    "/{intake_id}/re-record",
    response_model=ReRecordResult,
    status_code=status.HTTP_200_OK,
    summary="Re-record a voice intake (patient only, capped at 3 attempts)",
)
async def re_record_intake(
    request: Request,
    _account: Annotated[Principal, Depends(require_patient)],
    intake_id: int,
    body: ReRecordRequest,
) -> ReRecordResult:
    """Attach a fresh recording attempt to a re-record intake.

    Thin patient-scoped adapter: the facade enforces ownership and the
    attempt cap server-side. When attempts are exhausted the intake is
    routed to forced text so the patient is never stuck.
    """
    facade = cast(IntakeFacade, request.app.state.intake_facade)
    return await facade.re_record_intake(
        intake_id=intake_id,
        patient_id=int(_account.subject_id),
        media_ref=body.media_ref,
    )


@router.get(
    "/{intake_id}",
    response_model=IntakeDetailView,
    status_code=status.HTTP_200_OK,
    summary="Get intake detail with transcript and media refs (patient only)",
)
async def get_intake(
    request: Request,
    _account: Annotated[Principal, Depends(require_patient)],
    intake_id: int,
) -> IntakeDetailView:
    """Read an intake with transcript, media refs, and status.

    Thin patient-scoped adapter: the facade enforces ownership.
    """
    facade = cast(IntakeFacade, request.app.state.intake_facade)
    return await facade.get_intake(
        intake_id=intake_id,
        patient_id=int(_account.subject_id),
    )


@router.get(
    "/{intake_id}/pre-summary",
    response_model=PreSummaryView,
    status_code=status.HTTP_200_OK,
    summary="Get the AI pre-summary for an intake (patient only)",
)
async def get_pre_summary(
    request: Request,
    _account: Annotated[Principal, Depends(require_patient)],
    intake_id: int,
) -> PreSummaryView:
    """Read the pre-summary with draft fields, confidence, and edits.

    Thin patient-scoped adapter: the facade enforces ownership and returns
    the low_confidence honesty flag so the UI can show the AMB-006 cue.
    """
    facade = cast(IntakeFacade, request.app.state.intake_facade)
    return await facade.get_pre_summary(
        intake_id=intake_id,
        patient_id=int(_account.subject_id),
    )


@router.post(
    "/{intake_id}/patient-edits",
    response_model=PatientEditsResult,
    status_code=status.HTTP_200_OK,
    summary="Save patient corrections to a pre-summary (patient only)",
)
async def save_patient_edits(
    request: Request,
    _account: Annotated[Principal, Depends(require_patient)],
    intake_id: int,
    body: PatientEditsRequest,
) -> PatientEditsResult:
    """Record patient-spotted mistakes as informational corrections.

    Thin patient-scoped adapter: the facade merges the edits onto the
    pre-summary's ``patient_edits`` field. Edits accumulate across saves
    and are advice to the doctor - never mutating the AI structured_fields.
    """
    facade = cast(IntakeFacade, request.app.state.intake_facade)
    return await facade.save_patient_pre_summary_edits(
        intake_id=intake_id,
        patient_id=int(_account.subject_id),
        fields=body.fields,
    )


@router.post(
    "/{intake_id}/review",
    response_model=PreSummaryReviewResult,
    status_code=status.HTTP_200_OK,
    summary="Review-and-edit an intake pre-summary (doctor only)",
)
async def review_pre_summary(
    request: Request,
    account: Annotated[Principal, Depends(require_partner)],
    intake_id: int,
    body: PreSummaryReviewRequest,
) -> PreSummaryReviewResult:
    """Perform the attributed doctor review-and-edit (US-21 through US-24).

    Thin doctor-scoped adapter (PHASE-7 T13, #357): the ``require_partner``
    gate admits any partner-scoped caller, then the principal is resolved to
    their partner profile and a non-doctor partner is refused with 403 - the
    doctor RBAC convention (partner scope + ``partner_type == "doctor"``,
    matching the health routes). The patient and lab/chemist partner scopes
    cannot reach this route. The facade applies the doctor's ``corrections``
    over the AI ``structured_fields`` and returns the reviewed copy with the
    attribution (``reviewed_by`` = the doctor's partner id).
    """
    facade = cast(IntakeFacade, request.app.state.intake_facade)
    partner = await cast(PartnerFacade, request.app.state.partner_facade).resolve_partner(
        int(account.subject_id)
    )
    if partner.partner_type != "doctor":
        raise InsufficientScopeError("the doctor role is required for this route")
    return await facade.mark_pre_summary_reviewed(
        intake_id=intake_id,
        doctor_id=partner.partner_id,
        corrections=body.corrections,
    )


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------


def register_error_handlers(app: FastAPI) -> None:
    """Attach the MOD-005 error envelope to every expected intake failure.

    Only the intake module's own domain errors are mapped here. Validation
    errors (missing/invalid fields) and gateway auth errors are handled by
    the iam and gateway module handlers respectively.
    """

    async def _intake_not_found(request: Request, exc: Exception) -> JSONResponse:
        del exc
        return error_response(
            status.HTTP_404_NOT_FOUND,
            "INTAKE_NOT_FOUND",
            "intake not found or not owned by the caller",
            log_tag="intake_route",
            request=request,
        )

    async def _intake_validation_error(request: Request, exc: Exception) -> JSONResponse:
        intake_exc = cast(IntakeValidationError, exc)
        return error_response(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "INTAKE_VALIDATION_ERROR",
            str(intake_exc),
            log_tag="intake_route",
            request=request,
        )

    async def _illegal_intake_transition(request: Request, exc: Exception) -> JSONResponse:
        del exc
        return error_response(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "ILLEGAL_INTAKE_TRANSITION",
            "the requested intake action is illegal in the current state",
            log_tag="intake_route",
            request=request,
        )

    async def _illegal_pre_summary_transition(request: Request, exc: Exception) -> JSONResponse:
        del exc
        return error_response(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "ILLEGAL_PRE_SUMMARY_TRANSITION",
            "the requested pre-summary action is illegal in the current state",
            log_tag="intake_route",
            request=request,
        )

    async def _media_transfer_error(request: Request, exc: Exception) -> JSONResponse:
        del exc
        return error_response(
            status.HTTP_502_BAD_GATEWAY,
            "MEDIA_TRANSFER_FAILED",
            "media upload failed after all retry attempts",
            log_tag="intake_route",
            request=request,
        )

    async def _intake_error(request: Request, exc: Exception) -> JSONResponse:
        del exc
        return error_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "INTAKE_INTERNAL",
            "Internal intake error",
            log_tag="intake_route",
            request=request,
        )

    app.add_exception_handler(IntakeNotFoundError, _intake_not_found)
    app.add_exception_handler(IntakeValidationError, _intake_validation_error)
    app.add_exception_handler(IllegalIntakeTransitionError, _illegal_intake_transition)
    app.add_exception_handler(IllegalPreSummaryTransitionError, _illegal_pre_summary_transition)
    app.add_exception_handler(MediaTransferError, _media_transfer_error)
    app.add_exception_handler(IntakeError, _intake_error)
