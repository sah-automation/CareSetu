"""MOD-004: HTTP adapters for the consent module's lifecycle surface (PHASE-3 T3, #212).

Endpoints are thin adapters (api-standards §1): resolve the gateway
``Principal``, call the module facade, return the typed view. The routes sit
behind the gateway middleware stack in ``app.main``; the RBAC dependency
(``require_patient``) admits only an authenticated patient scope - Phase 3's
lifecycle is entirely patient-driven - and the facade re-checks lineage
ownership as the real boundary (api-standards §6, security-phii-standards §3).
Revocation is ONE explicit ``POST`` (the "one confirm" of spec #209 story 16
is the PWA's inline confirm on T10's sheet); every expected failure answers
the shared error envelope at the top level (api-standards §2).
"""

from __future__ import annotations

import logging
from typing import Annotated, cast

from fastapi import APIRouter, Depends, FastAPI, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.gateway.errors import ErrorEnvelope
from app.gateway.principal import Principal
from app.gateway.rbac import require_patient
from app.gateway.trace import resolve_trace_id
from modules.consent.domain.events import CounterpartyType, RecordScope
from modules.consent.domain.exceptions import (
    ConsentAccessDeniedError,
    ConsentError,
    ConsentNotFoundError,
    IllegalConsentTransitionError,
)
from modules.consent.facade import ConsentFacade, ConsentLog, ConsentView, EgressLog

router = APIRouter(tags=["consent"])

logger = logging.getLogger(__name__)


class ConsentTargetRequest(BaseModel):
    """Body naming WHO gets access to WHAT scope - the lineage triple.

    ``counterparty_id`` is whatever caller-supplied reference Phase 3
    carries; directory resolution replaces free text in later phases.
    """

    model_config = ConfigDict(extra="forbid")

    counterparty_type: CounterpartyType
    counterparty_id: str = Field(min_length=1, max_length=200)
    record_scope: RecordScope


@router.post(
    "/v1/consents",
    response_model=ConsentView,
    status_code=status.HTTP_201_CREATED,
    summary="Grant a standing consent without waiting for a request",
)
async def grant_consent(
    request: Request,
    body: ConsentTargetRequest,
    principal: Annotated[Principal, Depends(require_patient)],
) -> ConsentView:
    """Patient-initiated grant: v1 on a fresh triple, vN+1 on a known one."""
    facade = cast(ConsentFacade, request.app.state.consent_facade)
    return await facade.grant_consent(
        int(principal.subject_id),
        body.counterparty_type,
        body.counterparty_id,
        body.record_scope,
    )


@router.post(
    "/v1/consents/requests",
    response_model=ConsentView,
    status_code=status.HTTP_201_CREATED,
    summary="Record a consent ask (Requested); provider channels arrive in Phases 8/9",
)
async def request_consent(
    request: Request,
    body: ConsentTargetRequest,
    principal: Annotated[Principal, Depends(require_patient)],
) -> ConsentView:
    """Open the ask: the lineage enters ``Requested`` with no grant minted."""
    facade = cast(ConsentFacade, request.app.state.consent_facade)
    return await facade.request_consent(
        int(principal.subject_id),
        body.counterparty_type,
        body.counterparty_id,
        body.record_scope,
    )


@router.get(
    "/v1/consents",
    response_model=ConsentLog,
    status_code=status.HTTP_200_OK,
    summary="List the caller's consent log",
)
async def list_consents(
    request: Request,
    principal: Annotated[Principal, Depends(require_patient)],
) -> ConsentLog:
    """Pending asks first; revoked grants stay listed with their full history."""
    facade = cast(ConsentFacade, request.app.state.consent_facade)
    return await facade.list_consents(int(principal.subject_id))


@router.get(
    "/v1/consents/egress-log",
    response_model=EgressLog,
    status_code=status.HTTP_200_OK,
    summary="List the caller's egress log (what left their record)",
)
async def list_egress_log(
    request: Request,
    principal: Annotated[Principal, Depends(require_patient)],
) -> EgressLog:
    """Every consent-gated disclosure from this patient's record.

    Returns what was disclosed (entry IDs), when, to which counterparty,
    and under which consent version/lineage. Owner-only - partners cannot
    see the egress log.
    """
    facade = cast(ConsentFacade, request.app.state.consent_facade)
    return await facade.list_egress_log(int(principal.subject_id))


@router.post(
    "/v1/consents/{consent_id}/grant",
    response_model=ConsentView,
    status_code=status.HTTP_200_OK,
    summary="Grant an existing request",
)
async def grant_requested(
    request: Request,
    consent_id: int,
    principal: Annotated[Principal, Depends(require_patient)],
) -> ConsentView:
    """Promote a ``Requested`` lineage to its first live grant."""
    facade = cast(ConsentFacade, request.app.state.consent_facade)
    return await facade.grant_requested(int(principal.subject_id), consent_id)


@router.post(
    "/v1/consents/{consent_id}/revoke",
    response_model=ConsentView,
    status_code=status.HTTP_200_OK,
    summary="Revoke the live grant (one confirm)",
)
async def revoke_consent(
    request: Request,
    consent_id: int,
    principal: Annotated[Principal, Depends(require_patient)],
) -> ConsentView:
    """Terminal for that version; durable-before-inactive in the same commit."""
    facade = cast(ConsentFacade, request.app.state.consent_facade)
    return await facade.revoke_consent(int(principal.subject_id), consent_id)


@router.post(
    "/v1/consents/{consent_id}/decline",
    response_model=ConsentView,
    status_code=status.HTTP_200_OK,
    summary="Decline a pending request (no grant is created)",
)
async def decline_consent(
    request: Request,
    consent_id: int,
    principal: Annotated[Principal, Depends(require_patient)],
) -> ConsentView:
    """Close the ask; only the audit event records that it happened."""
    facade = cast(ConsentFacade, request.app.state.consent_facade)
    return await facade.decline_consent(int(principal.subject_id), consent_id)


def _error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
) -> JSONResponse:
    """One error envelope for every expected consent failure (api-standards §2).

    Records the failure as a structured log line keyed by the request-scoped
    trace id the envelope carries (error-handling-observability §3); never
    logs lineage content or counterparty detail.
    """
    trace_id = resolve_trace_id(request)
    logger.warning("consent_rejection code=%s status=%d trace_id=%s", code, status_code, trace_id)
    envelope = ErrorEnvelope(code=code, message=message, trace_id=trace_id, details={})
    return JSONResponse(status_code=status_code, content=envelope.model_dump(mode="json"))


def register_error_handlers(app: FastAPI) -> None:
    """Attach the MOD-004 error envelope to every expected consent failure."""

    async def _not_found(request: Request, exc: Exception) -> JSONResponse:
        del exc
        return _error_response(
            request,
            status.HTTP_404_NOT_FOUND,
            "CONSENT_NOT_FOUND",
            "no such consent for this patient",
        )

    async def _access_denied(request: Request, exc: Exception) -> JSONResponse:
        del exc
        return _error_response(
            request,
            status.HTTP_403_FORBIDDEN,
            "CONSENT_ACCESS_DENIED",
            "only the owning patient may act on this consent",
        )

    async def _illegal_transition(request: Request, exc: Exception) -> JSONResponse:
        return _error_response(
            request,
            status.HTTP_409_CONFLICT,
            "CONSENT_INVALID_TRANSITION",
            str(exc),
        )

    async def _consent_failed(request: Request, exc: Exception) -> JSONResponse:
        del exc
        return _error_response(
            request,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "CONSENT_INTERNAL",
            "Internal consent error",
        )

    app.add_exception_handler(ConsentNotFoundError, _not_found)
    app.add_exception_handler(ConsentAccessDeniedError, _access_denied)
    app.add_exception_handler(IllegalConsentTransitionError, _illegal_transition)
    app.add_exception_handler(ConsentError, _consent_failed)
