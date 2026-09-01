"""MOD-002: HTTP adapters for the partner module (PHASE-5 T05, ticket #249).

Endpoints are thin adapters (api-standards §1): parse the typed request, call
the module facade, return the typed result. This ticket opens the partner
self-service registration route - a doctor, lab, or chemist registers openly
with their phone + partner type + basic profile (practice location/geo
mandatory, service area optional). It is unauthenticated like the iam auth
surface, sitting behind the gateway middleware stack in ``app.main`` (rate
limited by that stack). Every expected failure answers the shared error
envelope at the top level (api-standards §2); ``register_error_handlers`` maps
partner domain errors to that envelope. An ``InvalidPhoneError`` raised by the
iam seam is handled by the iam module's own registered handler (PHONE_INVALID
422) - the same cross-module error-handling pattern the health<->consent seams
use; this module never imports another module's domain types. The route carries
no business logic - duplicate-phone resolution and the sync account creation
(ADR-0010) live in the facade.
"""

from __future__ import annotations

import base64
import logging
from typing import Annotated, cast

from fastapi import APIRouter, Depends, FastAPI, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.gateway.errors import ErrorEnvelope
from app.gateway.principal import Principal
from app.gateway.rbac import require_operator, require_partner
from app.gateway.trace import resolve_trace_id
from modules.partner.domain.credentials import CredentialType
from modules.partner.domain.events import PartnerType
from modules.partner.domain.exceptions import (
    AppealAlreadyUsedError,
    IllegalPartnerTransitionError,
    InvalidQueueSortError,
    PartnerError,
    PartnerNotRejectedError,
    RejectionReasonRequiredError,
    ReSubmissionThrottledError,
)
from modules.partner.facade import (
    CredentialSubmission,
    CredentialSubmissionResult,
    PartnerFacade,
    PartnerQueue,
    PartnerVerificationDetail,
    PartnerView,
    RegisterPartnerResult,
    RejectionReasonView,
)

router = APIRouter(prefix="/v1/partner", tags=["partner"])

logger = logging.getLogger(__name__)


class RegisterPartnerRequest(BaseModel):
    """Body of ``POST /v1/partner/register``: open registration (FEAT-014).

    ``phone`` is the same 10-digit Indian mobile (or +91-prefixed) form the iam
    auth surface accepts - normalized server-side to +91 E.164, never trusted
    from the client. Practice location/geo is mandatory for every partner type;
    ``service_area_id`` is optional (defaulting to Daltonganj at launch is a
    Phase-6 application-layer concern, not validated here).
    """

    model_config = ConfigDict(extra="forbid")

    phone: str = Field(min_length=1, description="10-digit Indian mobile number, or with 91 prefix")
    partner_type: PartnerType
    practice_address: str = Field(min_length=1, description="Practice location address (mandatory)")
    practice_latitude: float = Field(ge=-90, le=90)
    practice_longitude: float = Field(ge=-180, le=180)
    service_area_id: int | None = None


class CredentialDocumentRequest(BaseModel):
    """One professional credential a partner submits (ADR-0008, T06).

    ``credential_type`` is the closed per-partner-type type; ``artifacts`` are the
    base64-encoded document bytes the route decodes and hands to the facade to
    AES-encrypt into the ``partner/`` object-storage prefix. Refs, never bytes,
    are what gets persisted; the pre-filter rejects a submission with no
    artifacts (``missing_artifacts``).
    """

    model_config = ConfigDict(extra="forbid")

    credential_type: CredentialType
    artifacts: list[str] = Field(
        default_factory=list,
        description="Base64-encoded document bytes to encrypt and file",
    )


class CredentialSubmissionRequest(BaseModel):
    """Body of ``POST /v1/partner/credentials``: the Step-1 submission body."""

    model_config = ConfigDict(extra="forbid")

    credentials: list[CredentialDocumentRequest] = Field(
        min_length=1, description="At least one credential document to submit"
    )


@router.post(
    "/register",
    response_model=RegisterPartnerResult,
    status_code=status.HTTP_200_OK,
    summary="Open partner registration (open, no invite required)",
)
async def open_partner_registration(
    request: Request,
    body: RegisterPartnerRequest,
) -> RegisterPartnerResult:
    """Open a partner registration: create the sync account + open profile.

    Creates the iam credential account synchronously (ADR-0010) so the partner
    can log in the moment they register, opens a ``[Registered]`` profile, and
    emits ``partner.registered``. A duplicate phone resolves to the existing
    partner profile (never a second row) and returns its current onboarding
    status.
    """
    facade = cast(PartnerFacade, request.app.state.partner_facade)
    return await facade.register(
        phone=body.phone,
        partner_type=body.partner_type,
        practice_address=body.practice_address,
        practice_latitude=body.practice_latitude,
        practice_longitude=body.practice_longitude,
        service_area_id=body.service_area_id,
    )


@router.post(
    "/credentials",
    response_model=CredentialSubmissionResult,
    status_code=status.HTTP_200_OK,
    summary="Submit professional credentials (Step-1 pre-filter run here)",
)
async def open_credential_submission(
    request: Request,
    account: Annotated[Principal, Depends(require_partner)],
    body: CredentialSubmissionRequest,
) -> CredentialSubmissionResult:
    """Submit professional credentials and run the Step-1 automated pre-filter.

    The automatic first half of the two-step gate (ADR-0008): the pre-filter
    validates format (credential type appropriate for this partner type,
    documents uploaded) and duplicates, then either opens a verification round
    (``[Under Verification]``, ``partner.verification_started``) or auto-fails
    straight to ``[Rejected]`` with a specific reason - never queued. The route
    is a thin adapter: it decodes the base64 document bytes and hands the typed
    submission to the facade, which encrypts them into ``partner/``. The partner
    acts only on their own identity - the authenticated principal's ``subject_id``
    is resolved to the partner profile, so no cross-partner submission.
    """
    facade = cast(PartnerFacade, request.app.state.partner_facade)
    partner = await facade.resolve_partner(int(account.subject_id))
    credentials = [
        CredentialSubmission(
            credential_type=doc.credential_type,
            artifacts=[_decode_artifact(b64) for b64 in doc.artifacts],
        )
        for doc in body.credentials
    ]
    return await facade.submit_credentials(
        partner.partner_id,
        credentials=credentials,
    )


@router.get(
    "/rejection-reason",
    response_model=RejectionReasonView,
    status_code=status.HTTP_200_OK,
    summary="View the specific rejection reason (partner only, rejected only)",
)
async def rejection_reason(
    request: Request,
    account: Annotated[Principal, Depends(require_partner)],
) -> RejectionReasonView:
    """A ``[Rejected]`` partner reads the reason their application failed.

    A thin partner-scoped adapter (PHASE-5 T09): resolves the authenticated
    partner principal to their profile and reads back the latest rejection
    reason so they can re-apply with corrected credentials. The facade raises
    :class:`PartnerNotRejectedError` for any non-``[Rejected]`` partner, which
    the module error handler maps to a 422.
    """
    facade = cast(PartnerFacade, request.app.state.partner_facade)
    partner = await facade.resolve_partner(int(account.subject_id))
    return await facade.get_rejection_reason(partner.partner_id)


@router.post(
    "/appeal",
    response_model=PartnerView,
    status_code=status.HTTP_200_OK,
    summary="File a one-time appeal that re-enters the operator queue (partner only)",
)
async def partner_appeal(
    request: Request,
    account: Annotated[Principal, Depends(require_partner)],
) -> PartnerView:
    """A ``[Rejected]`` partner contests a decision once via a one-time appeal.

    A thin partner-scoped adapter (PHASE-5 T09): resolves the partner principal
    and files the appeal, which re-enters the operator queue (Step 2) and emits
    ``partner.verification_started``. The ``appeal_used`` flag is consumed on
    first use; a second appeal maps to an ``APPEAL_ALREADY_USED`` 422.
    """
    facade = cast(PartnerFacade, request.app.state.partner_facade)
    partner = await facade.resolve_partner(int(account.subject_id))
    return await facade.appeal(partner.partner_id)


@router.get(
    "/verification-queue",
    response_model=PartnerQueue,
    status_code=status.HTTP_200_OK,
    summary="List the operator verification queue (operator only)",
)
async def list_verification_queue(
    request: Request,
    operator: Annotated[Principal, Depends(require_operator)],
    partner_type: Annotated[PartnerType | None, Query()] = None,
    status: Annotated[str | None, Query()] = "Under Verification",
    sort_by: Annotated[str, Query()] = "registration_age",
) -> PartnerQueue:
    """List the engagement queue an operator gates (FEAT-015, user story 16).

    Operator-scoped (MFA attested - ``require_operator``): a partner/patient/
    anonymous caller is refused 403/401 at the edge. Defaults to the
    ``[Under Verification]`` queue, filterable by ``partner_type`` and
    ``status`` (the status filter also opens the ``[Active]``/``[Rejected]``
    activation-cycle KPI view), and sortable by ``registration_age`` (default,
    oldest first for the <= 48 h KPI-004 median), ``partner_type`` or
    ``status``. No bulk actions - the queue only lists; decisions go through the
    per-partner decision route.
    """
    del operator
    facade = cast(PartnerFacade, request.app.state.partner_facade)
    return await facade.list_verification_queue(
        partner_type=partner_type,
        status=status,
        sort_by=sort_by,
    )


@router.get(
    "/verification/{partner_id}",
    response_model=PartnerVerificationDetail,
    status_code=status.HTTP_200_OK,
    summary="Open a queue item: profile + credentials + verification history (operator only)",
)
async def verification_detail(
    request: Request,
    operator: Annotated[Principal, Depends(require_operator)],
    partner_id: int,
) -> PartnerVerificationDetail:
    """Open a partner's queue item for review (FEAT-015, user story 17).

    Returns the profile, all submitted credentials, and the per-round
    verification history. Every view of the credentials emits
    ``partner.credential_reviewed`` (actor + partner) - the "who saw this
    document" trail (operator audit depth); audit consumption is a later ticket.
    """
    facade = cast(PartnerFacade, request.app.state.partner_facade)
    return await facade.get_verification_detail(int(partner_id), actor_id=int(operator.subject_id))


@router.post(
    "/verification/{partner_id}/decision",
    response_model=PartnerView,
    status_code=status.HTTP_200_OK,
    summary="Approve or reject a partner queue item (operator only, reason required on reject)",
)
async def operator_decision(
    request: Request,
    operator: Annotated[Principal, Depends(require_operator)],
    partner_id: int,
    body: OperatorDecisionRequest,
) -> PartnerView:
    """The Step-2 manual activation gate (FEAT-015, user stories 18-19).

    Approve -> the partner becomes ``[Active]`` and ``partner.activated`` fires
    (the iam consumer grants the ``partner`` role, T03 chain). Reject -> a
    reason is REQUIRED (facade raises 422 when absent) and the partner becomes
    ``[Rejected]`` with ``partner.rejected`` carrying the reason (role denied).
    Individually attributed to the operator principal - there is no bulk path.
    """
    facade = cast(PartnerFacade, request.app.state.partner_facade)
    return await facade.operator_decision(
        int(partner_id),
        decision_by=int(operator.subject_id),
        approve=body.approve,
        reason=body.reason,
    )


class OperatorDecisionRequest(BaseModel):
    """Body of ``POST /v1/partner/verification/{id}/decision`` (FEAT-015).

    ``approve`` is a single, individually-attributed action - no bulk path.
    ``reason`` is REQUIRED on reject (422 when missing/blank) and optional on
    approve; it is recorded on the verification round and carried into the
    ``partner.rejected`` payload so the partner learns the specific failure.
    """

    model_config = ConfigDict(extra="forbid")

    approve: bool
    reason: str | None = Field(
        default=None,
        description="Required on reject; the specific failure surfaced to the partner",
    )


@router.post(
    "/verification/{partner_id}/grace-lapse",
    response_model=PartnerView,
    status_code=status.HTTP_200_OK,
    summary="Drop an Active partner to Under Verification on grace-window lapse (operator only)",
)
async def grace_window_lapse(
    request: Request,
    operator: Annotated[Principal, Depends(require_operator)],
    partner_id: int,
) -> PartnerView:
    """Apply the 7-day grace-window lapse (ticket #254, event-driven reverify path).

    An ``[Active]`` partner who re-submitted credentials (a re-verification
    round opened) stays ``[Active]`` through the 7-day grace window. When that
    deadline runs out without an operator decision, THIS endpoint drops them to
    ``[Under Verification]`` so they re-enter the operator gate - WITHOUT
    deactivating them (no ``credential.invalidated`` fires for a mere lapse, as
    opposed to an operator reject of the re-verification). It is not a
    scheduled scanner (that is Phase 6); it is the explicit, event-driven
    reverify-deadline path. Operator-scoped so only a verified operator can
    trigger it (the timeline seam for the Phase-6 deadline flow). A
    non-``[Active]`` partner - or an ``[Active]`` partner without an open,
    undecided reverification round - is refused with an
    ``ILLEGAL_PARTNER_TRANSITION`` 422.
    """
    del operator
    facade = cast(PartnerFacade, request.app.state.partner_facade)
    return await facade.grace_lapse(int(partner_id))


def _decode_artifact(b64: str) -> bytes:
    """Decode a base64 artifact, rejecting malformed input (never stored raw)."""
    try:
        return base64.b64decode(b64, validate=True)
    except ValueError as exc:
        raise ValueError("artifact is not valid base64") from exc


def _error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    *,
    details: dict[str, object] | None = None,
) -> JSONResponse:
    """One error envelope for every expected partner failure (api-standards §2).

    Records the failure as a structured log line keyed by the same request
    scoped trace id the envelope carries (error-handling-observability §3).
    """
    trace_id = resolve_trace_id(request)
    logger.warning("partner_rejection code=%s status=%d trace_id=%s", code, status_code, trace_id)
    envelope = ErrorEnvelope(
        code=code,
        message=message,
        trace_id=trace_id,
        details=details if details is not None else {},
    )
    return JSONResponse(status_code=status_code, content=envelope.model_dump(mode="json"))


def register_error_handlers(app: FastAPI) -> None:
    """Attach the MOD-002 error envelope to every expected partner failure.

    Only the partner module's own domain errors are mapped here. Validation
    errors (missing/invalid fields) and the iam ``InvalidPhoneError`` raised
    by the sync account seam are handled by the iam module's app-wide
    registered handlers (VALIDATION_ERROR / PHONE_INVALID 422) - the shared
    pattern across modules; registering a second RequestValidationError
    handler here would override iam's app-wide one.
    """

    async def _partner_failed(request: Request, exc: Exception) -> JSONResponse:
        del exc
        return _error_response(
            request,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "PARTNER_INTERNAL",
            "Internal partner error",
        )

    async def _rejection_reason_required(request: Request, exc: Exception) -> JSONResponse:
        del exc
        return _error_response(
            request,
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "REJECTION_REASON_REQUIRED",
            "a reason is required when rejecting a partner",
        )

    async def _invalid_queue_sort(request: Request, exc: Exception) -> JSONResponse:
        del exc
        return _error_response(
            request,
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "INVALID_QUEUE_SORT",
            "unknown verification queue sort key",
        )

    async def _not_rejected(request: Request, exc: Exception) -> JSONResponse:
        partner_not_rejected = cast(PartnerNotRejectedError, exc)
        return _error_response(
            request,
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "PARTNER_NOT_REJECTED",
            "partner must be Rejected for this recovery action",
            details={
                "partner_id": partner_not_rejected.partner_id,
                "current_status": partner_not_rejected.status,
            },
        )

    async def _appeal_already_used(request: Request, exc: Exception) -> JSONResponse:
        del exc
        return _error_response(
            request,
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "APPEAL_ALREADY_USED",
            "the one-time appeal has already been consumed",
        )

    async def _re_submission_throttled(request: Request, exc: Exception) -> JSONResponse:
        throttled = cast(ReSubmissionThrottledError, exc)
        response = _error_response(
            request,
            status.HTTP_429_TOO_MANY_REQUESTS,
            "RE_SUBMISSION_THROTTLED",
            "re-submission limit reached; try again after the cooldown",
            details={"retry_at": throttled.retry_at} if throttled.retry_at else {},
        )
        # api-standards §6: a 429 carries Retry-After so the client knows the
        # cooldown deadline without re-calling.
        if throttled.retry_at:
            response.headers["Retry-After"] = throttled.retry_at
        return response

    async def _illegal_transition(request: Request, exc: Exception) -> JSONResponse:
        del exc
        return _error_response(
            request,
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "ILLEGAL_PARTNER_TRANSITION",
            "the requested lifecycle action is illegal in the partner's current state",
        )

    app.add_exception_handler(RejectionReasonRequiredError, _rejection_reason_required)
    app.add_exception_handler(InvalidQueueSortError, _invalid_queue_sort)
    app.add_exception_handler(PartnerNotRejectedError, _not_rejected)
    app.add_exception_handler(AppealAlreadyUsedError, _appeal_already_used)
    app.add_exception_handler(ReSubmissionThrottledError, _re_submission_throttled)
    app.add_exception_handler(IllegalPartnerTransitionError, _illegal_transition)
    app.add_exception_handler(PartnerError, _partner_failed)
