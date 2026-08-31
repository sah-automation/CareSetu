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

import logging
from typing import cast

from fastapi import APIRouter, FastAPI, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.gateway.errors import ErrorEnvelope
from app.gateway.trace import resolve_trace_id
from modules.partner.domain.events import PartnerType
from modules.partner.domain.exceptions import PartnerError
from modules.partner.facade import PartnerFacade, RegisterPartnerResult

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

    app.add_exception_handler(PartnerError, _partner_failed)
