"""MOD-012: HTTP adapters for the doctor console Patients list (#539).

Thin adapters (api-standards S1): parse the typed query, call the owning
doctor console facade, return the typed result - route-boundary tests use a
stubbed facade. The doctor RBAC guard follows the care/intake routing
convention (``require_partner`` + the resolved partner profile): partner scope
and ``partner_type == "doctor"`` in the ``Active`` lifecycle state, else 403
``AUTH_INSUFFICIENT_SCOPE`` at the edge. ``doctor_id`` returned by the guard
is the partner's MOD-001 gateway identity (``partner_id``), which the
facades use for attribution and the consent reverse lookup.
"""

from __future__ import annotations

import logging
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Query, Request, status

from app.gateway.errors import AuthenticationRequiredError, InsufficientScopeError
from app.gateway.principal import Principal
from app.gateway.rbac import require_partner
from modules.doctor.doctor_models import PatientsListView
from modules.doctor.facade import DoctorConsoleFacade
from modules.partner.facade import PartnerFacade

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/doctor", tags=["doctor"])

_DEFAULT_PER_PAGE = 25
_MAX_PER_PAGE = 100


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
    "/patients",
    response_model=PatientsListView,
    status_code=status.HTTP_200_OK,
    summary="List the calling doctor's current and past patients (doctor only)",
)
async def list_patients(
    request: Request,
    account: Annotated[Principal, Depends(require_partner)],
    search: str | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1, le=_MAX_PER_PAGE)] = _DEFAULT_PER_PAGE,
) -> PatientsListView:
    """List the doctor's current and past patients (US-13, ADR-0019).

    Thin doctor-scoped adapter: the derived list - patients currently
    consenting this doctor or with an open care case (current) plus patients
    whose relationship has ended (past) - is served from the
    ``doctor_console_facade`` on app state. ``search`` optionally narrows to
    patients whose name contains the query (case-insensitive); ``page``/
    ``per_page`` bound the returned page (default 25, max 100 per
    api-standards §4), with ``total`` carrying the full match count. The
    record access history is the audit trail of which rows were viewed.
    """
    facade = cast(DoctorConsoleFacade, request.app.state.doctor_console_facade)
    doctor_id = await _require_doctor(request, account)
    return await facade.list_doctor_patients(
        doctor_id=doctor_id,
        search=search,
        page=page,
        per_page=per_page,
    )
