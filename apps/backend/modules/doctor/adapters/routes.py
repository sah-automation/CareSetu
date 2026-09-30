"""MOD-012: HTTP adapters for the doctor console Patients list (#539).

Thin adapters (api-standards S1): parse the typed query, call the owning
doctor console facade, return the typed result - route-boundary tests use a
stubbed facade. The doctor RBAC guard follows the care/intake routing
convention (``require_partner`` + the resolved partner profile): partner scope
and ``partner_type == "doctor"`` in the ``Active`` lifecycle state, else 403
``AUTH_INSUFFICIENT_SCOPE`` at the edge. ``doctor_id`` returned by the guard
is the partner's MOD-001 gateway identity (``partner_id``), which the
facades use for attribution and the consent reverse lookup - and which the
console facade independently re-checks through MOD-002 before every read
(api-standards §6; the edge guard is convenience, the facade is the boundary).

The module's own domain errors are encoded by ``register_error_handlers``,
wired at the composition root like every other module: the doctor console's
403 envelope must not depend on whichever module happens to register its
handler first.
"""

from __future__ import annotations

import logging
from typing import Annotated, cast

from fastapi import APIRouter, Depends, FastAPI, File, Query, Request, Response, UploadFile, status
from fastapi.responses import JSONResponse

from app.gateway.errors import (
    AuthenticationRequiredError,
    InsufficientScopeError,
    error_response,
)
from app.gateway.idempotency import run_idempotent
from app.gateway.principal import Principal
from app.gateway.rbac import require_partner
from modules.doctor.doctor_models import DoctorPatientDetailView, PatientsListView
from modules.doctor.domain.exceptions import (
    DoctorConsoleAccessDeniedError,
    DoctorConsoleError,
)
from modules.doctor.facade import DoctorConsoleFacade
from modules.partner.facade import (
    DoctorProfilePhotoView,
    DoctorProfilePracticeUpdate,
    DoctorProfileUpdate,
    DoctorProfileView,
    PartnerFacade,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/doctor", tags=["doctor"])

_DEFAULT_PER_PAGE = 25
_MAX_PER_PAGE = 100
# The bound on the name filter (api-standards §4: every filter is an explicit,
# validated query param). One full name is far under this; the cap only stops
# an unbounded needle from being pushed through the facade on every request.
_MAX_SEARCH_LENGTH = 120

_CODE_ACCESS_DENIED = "DOCTOR_CONSOLE_ACCESS_DENIED"
_LOG_TAG = "doctor_console_rejection"


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
    matching the care and intake routes): ``require_partner`` admits any
    partner-scoped caller at the dependency, then the principal is resolved to
    its partner profile and a non-doctor or not-yet-``Active`` partner is
    refused with 403. Only a licensed, active doctor may read the console.
    """
    partner = await cast(PartnerFacade, request.app.state.partner_facade).resolve_partner(
        _resolve_subject_id(account)
    )
    if partner.partner_type != "doctor":
        raise InsufficientScopeError("the doctor role is required for this route")
    if partner.status != "Active":
        raise InsufficientScopeError("an active partner profile is required for this route")
    return partner.partner_id


@router.get(
    "/profile",
    response_model=DoctorProfileView,
    status_code=status.HTTP_200_OK,
    summary="Read the calling active doctor's private profile",
)
async def get_doctor_profile(
    request: Request,
    account: Annotated[Principal, Depends(require_partner)],
) -> DoctorProfileView:
    facade = cast(PartnerFacade, request.app.state.partner_facade)
    doctor_id = await _require_doctor(request, account)
    return await facade.get_doctor_profile(doctor_id)


@router.put(
    "/profile",
    response_model=DoctorProfileView,
    status_code=status.HTTP_200_OK,
    summary="Update the calling active doctor's private profile",
)
async def update_doctor_profile(
    request: Request,
    account: Annotated[Principal, Depends(require_partner)],
    body: DoctorProfileUpdate,
) -> DoctorProfileView:
    facade = cast(PartnerFacade, request.app.state.partner_facade)
    doctor_id = await _require_doctor(request, account)

    async def _call() -> DoctorProfileView:
        return await facade.update_doctor_profile(doctor_id, body)

    return await run_idempotent(request, _call, namespace=f"doctor:{doctor_id}")


@router.put(
    "/profile/practice",
    response_model=DoctorProfileView,
    status_code=status.HTTP_200_OK,
    summary="Save the calling active doctor's practice details",
)
async def update_doctor_profile_practice(
    request: Request,
    account: Annotated[Principal, Depends(require_partner)],
    body: DoctorProfilePracticeUpdate,
) -> DoctorProfileView:
    """Save the Practice card on its own path, not on ``/profile`` (#608).

    The first of the four section writes; #611 retires the whole-form
    ``update_doctor_profile`` above and #609/#610 add the other three. Each gets
    its OWN path under the profile prefix rather than a second verb on
    ``/profile``, because ``run_idempotent`` keys its stored result on the route
    and the namespace: a client replaying an ``Idempotency-Key`` issued against
    the whole-form write would otherwise be served this write's stored response.
    The scoping itself is unchanged - per doctor, as on every other write here.
    """
    facade = cast(PartnerFacade, request.app.state.partner_facade)
    doctor_id = await _require_doctor(request, account)

    async def _call() -> DoctorProfileView:
        return await facade.update_doctor_practice(doctor_id, body)

    return await run_idempotent(request, _call, namespace=f"doctor:{doctor_id}")


@router.put(
    "/profile/photo",
    response_model=DoctorProfilePhotoView,
    status_code=status.HTTP_200_OK,
    summary="Upload or replace the calling active doctor's private profile photo",
)
async def update_doctor_profile_photo(
    request: Request,
    account: Annotated[Principal, Depends(require_partner)],
    file: Annotated[UploadFile, File()],
) -> DoctorProfilePhotoView:
    facade = cast(PartnerFacade, request.app.state.partner_facade)
    doctor_id = await _require_doctor(request, account)
    max_upload_bytes = cast(int, request.app.state.profile_media_max_upload_bytes)
    data = await file.read(max_upload_bytes + 1)

    async def _call() -> DoctorProfilePhotoView:
        return await facade.update_doctor_photo(
            doctor_id,
            media_type=file.content_type,
            data=data,
        )

    return await run_idempotent(request, _call, namespace=f"doctor:{doctor_id}")


@router.get(
    "/profile/photo",
    response_class=Response,
    summary="Stream the calling active doctor's private profile photo",
)
async def get_doctor_profile_photo(
    request: Request,
    account: Annotated[Principal, Depends(require_partner)],
) -> Response:
    facade = cast(PartnerFacade, request.app.state.partner_facade)
    doctor_id = await _require_doctor(request, account)
    photo = await facade.get_doctor_photo(doctor_id)
    return Response(
        content=photo.data,
        media_type=photo.media_type,
        headers={"Cache-Control": "no-store"},
    )


@router.delete(
    "/profile/photo",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove the calling active doctor's private profile photo",
)
async def delete_doctor_profile_photo(
    request: Request,
    account: Annotated[Principal, Depends(require_partner)],
) -> Response:
    facade = cast(PartnerFacade, request.app.state.partner_facade)
    doctor_id = await _require_doctor(request, account)

    async def _call() -> Response:
        await facade.delete_doctor_photo(doctor_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return await run_idempotent(request, _call, namespace=f"doctor:{doctor_id}")


@router.get(
    "/patients",
    response_model=PatientsListView,
    status_code=status.HTTP_200_OK,
    summary="List the calling doctor's current and past patients (doctor only)",
)
async def list_patients(
    request: Request,
    account: Annotated[Principal, Depends(require_partner)],
    search: Annotated[str | None, Query(max_length=_MAX_SEARCH_LENGTH)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1, le=_MAX_PER_PAGE)] = _DEFAULT_PER_PAGE,
) -> PatientsListView:
    """List the doctor's current and past patients (US-13, ADR-0019).

    Thin doctor-scoped adapter: the derived list - patients currently
    consenting this doctor or with an open care case (current) plus patients
    whose relationship has ended (past) - is served from the
    ``doctor_console_facade`` on app state. ``search`` optionally narrows to
    patients whose name contains the query (case-insensitive, bounded to
    ``_MAX_SEARCH_LENGTH`` characters); ``page``/``per_page`` bound the
    returned page (default 25, max 100 per api-standards §4), with ``total``
    carrying the full match count. The record access history and the consent
    egress log are the audit trail of which rows were viewed.
    """
    facade = cast(DoctorConsoleFacade, request.app.state.doctor_console_facade)
    doctor_id = await _require_doctor(request, account)
    return await facade.list_doctor_patients(
        doctor_id=doctor_id,
        search=search,
        page=page,
        per_page=per_page,
    )


@router.get(
    "/patients/{patient_id}",
    response_model=DoctorPatientDetailView,
    status_code=status.HTTP_200_OK,
    summary="Read one consent-gated patient detail (doctor only)",
)
async def get_patient_detail(
    request: Request,
    account: Annotated[Principal, Depends(require_partner)],
    patient_id: int,
) -> DoctorPatientDetailView:
    """Section-gated detail read of one patient (US-15..18, ADR-0019, #540).

    Thin doctor-scoped adapter over ``get_doctor_patient_detail``: each block
    - contact, consultation history, health background - renders only under
    the patient's corresponding live grant and answers the locked (null)
    shape otherwise, so a denial is a "not shared" section, never an error.
    Every granted read is access-logged and egress-disclosed inside the
    facade.
    """
    facade = cast(DoctorConsoleFacade, request.app.state.doctor_console_facade)
    doctor_id = await _require_doctor(request, account)
    return await facade.get_doctor_patient_detail(doctor_id=doctor_id, patient_id=patient_id)


@router.get(
    "/patients/{patient_id}/photo",
    status_code=status.HTTP_200_OK,
    summary="Stream one consent-gated patient's profile photo (doctor only)",
)
async def get_patient_photo(
    request: Request,
    account: Annotated[Principal, Depends(require_partner)],
    patient_id: int,
) -> Response:
    """Consent-gated photo stream for one patient (US-16, ADR-0020, #540).

    The facade refuses without a live grant by raising MOD-012's own
    ``DoctorConsoleAccessDeniedError``, encoded by this module's registered
    handler as the 403 ``DOCTOR_CONSOLE_ACCESS_DENIED`` envelope (fail-closed,
    shared error shape) - the same shape the route used to build inline, now
    bound to the module that owns the error. A patient with no photo answers
    the shared 404 envelope so the app degrades to the photo-picker card. The
    image is streamed through the backend and never exposed as a public object
    URL (ADR-0020).
    """
    facade = cast(DoctorConsoleFacade, request.app.state.doctor_console_facade)
    doctor_id = await _require_doctor(request, account)
    photo = await facade.get_doctor_patient_photo(doctor_id=doctor_id, patient_id=patient_id)
    if photo is None:
        return error_response(
            status.HTTP_404_NOT_FOUND,
            "PROFILE_PHOTO_NOT_FOUND",
            "no profile photo is set for this patient",
            request=request,
            log_tag=_LOG_TAG,
        )
    return Response(content=photo.data, media_type=photo.media_type)


def register_error_handlers(app: FastAPI) -> None:
    """Attach the MOD-012 error envelope to every expected console failure.

    Registered at the composition root like every other module's handlers, so
    the doctor's 403 depends on the module that owns the error rather than on
    whichever handler happened to be wired first. The envelope, code, and log
    tag are exactly what the photo route produced inline before.
    """

    async def _access_denied(request: Request, exc: Exception) -> JSONResponse:
        return error_response(
            status.HTTP_403_FORBIDDEN,
            _CODE_ACCESS_DENIED,
            str(exc),
            request=request,
            log_tag=_LOG_TAG,
        )

    async def _console_failed(request: Request, exc: Exception) -> JSONResponse:
        del exc
        return error_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "DOCTOR_CONSOLE_INTERNAL",
            "Internal doctor console error",
            request=request,
            log_tag=_LOG_TAG,
        )

    app.add_exception_handler(DoctorConsoleAccessDeniedError, _access_denied)
    app.add_exception_handler(DoctorConsoleError, _console_failed)
