"""MOD-003: HTTP adapters for the health module's record surface (PHASE-3 T2, #211).

Endpoints are thin adapters (api-standards §1): resolve the gateway
``Principal``, call the module facade, return the typed timeline. The routes
sit behind the gateway middleware stack in ``app.main``; the RBAC dependency
(``require_patient``) admits only an authenticated patient scope, and the
facade re-checks ownership as the real boundary (api-standards §6, security-
phii-standards §3) - a non-owner read is refused with the shared error
envelope AND recorded by the facade before the error leaves the transaction.
Every expected failure answers the shared error envelope at the top level
(api-standards §2).
"""

from __future__ import annotations

import logging
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, FastAPI, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.gateway.errors import ErrorEnvelope
from app.gateway.principal import Principal
from app.gateway.rbac import require_partner, require_patient
from app.gateway.trace import resolve_trace_id
from modules.health.domain.exceptions import (
    HealthError,
    RecordAccessDeniedError,
    RecordNotFoundError,
)
from modules.health.facade import HealthFacade, RecordTimeline

router = APIRouter(tags=["record"])

logger = logging.getLogger(__name__)


@router.get(
    "/v1/records",
    response_model=RecordTimeline,
    status_code=status.HTTP_200_OK,
    summary="Read the caller's own longitudinal record",
)
async def read_own_record(
    request: Request,
    principal: Annotated[Principal, Depends(require_patient)],
) -> RecordTimeline:
    """Own-record read resolved from the session subject - zero setup.

    The shell is addressed by the token's subject id (never client input), so
    the caller always gets their own - initially empty, reverse-chronological
    when entries arrive - timeline.
    """
    facade = cast(HealthFacade, request.app.state.health_facade)
    return await facade.get_own_record(int(principal.subject_id))


@router.get(
    "/v1/records/{record_id}",
    response_model=RecordTimeline,
    status_code=status.HTTP_200_OK,
    summary="Read one record by id (owner only)",
)
async def read_record_by_id(
    request: Request,
    record_id: int,
    principal: Annotated[Principal, Depends(require_patient)],
) -> RecordTimeline:
    """Addressed owner-only read.

    Ownership is re-checked in the facade against the session subject; a
    mismatch answers ``403 RECORD_ACCESS_DENIED`` and lands in the access
    history ledger naming the attempted accessor.
    """
    facade = cast(HealthFacade, request.app.state.health_facade)
    return await facade.get_record_as_owner(int(principal.subject_id), record_id)


class ConsentedReadRequest(BaseModel):
    """Input for partner consent-gated record read (PHASE-3 T5, #214).

    The partner identifies the patient (subject), the scope they need, and
    their own identity. The facade checks consent via MOD-004 before any
    data is disclosed.
    """

    patient_id: int
    scope: str
    counterparty_id: int
    counterparty_type: Literal["doctor", "lab", "chemist"]


@router.post(
    "/v1/records/consented-read",
    response_model=RecordTimeline,
    status_code=status.HTTP_200_OK,
    summary="Read a patient's record scope with consent",
)
async def read_consented_record(
    request: Request,
    payload: ConsentedReadRequest,
    principal: Annotated[Principal, Depends(require_partner)],
) -> RecordTimeline:
    """Partner consent-gated read: gate via MOD-004, write dual ledgers.

    The partner's session subject is the counterparty_id. The facade calls
    ``check_consent`` with (patient_id, scope, partner_type, partner_id).
    If allowed, returns scoped entries and writes ONE row to EACH ledger:
    health_record_access_history (outcome=allowed) AND consent_egress_log
    (with consent_id, version, lineage_ref, disclosed_entry_ids).
    If denied, writes ONLY to access history (outcome=denied).
    """
    facade = cast(HealthFacade, request.app.state.health_facade)
    return await facade.read_consented_history(
        patient_id=payload.patient_id,
        scope=payload.scope,
        counterparty_type=payload.counterparty_type,
        counterparty_id=payload.counterparty_id,
    )


def _error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
) -> JSONResponse:
    """One error envelope for every expected health failure (api-standards §2).

    Records the failure as a structured log line keyed by the request-scoped
    trace id the envelope carries (error-handling-observability §3); never
    logs record content or payload detail.
    """
    trace_id = resolve_trace_id(request)
    logger.warning("health_rejection code=%s status=%d trace_id=%s", code, status_code, trace_id)
    envelope = ErrorEnvelope(code=code, message=message, trace_id=trace_id, details={})
    return JSONResponse(status_code=status_code, content=envelope.model_dump(mode="json"))


def register_error_handlers(app: FastAPI) -> None:
    """Attach the MOD-003 error envelope to every expected health failure."""

    async def _record_not_found(request: Request, exc: Exception) -> JSONResponse:
        return _error_response(request, status.HTTP_404_NOT_FOUND, "RECORD_NOT_FOUND", str(exc))

    async def _access_denied(request: Request, exc: Exception) -> JSONResponse:
        return _error_response(
            request,
            status.HTTP_403_FORBIDDEN,
            "RECORD_ACCESS_DENIED",
            str(exc),
        )

    async def _health_failed(request: Request, exc: Exception) -> JSONResponse:
        del exc
        return _error_response(
            request,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "HEALTH_INTERNAL",
            "Internal health record error",
        )

    app.add_exception_handler(RecordNotFoundError, _record_not_found)
    app.add_exception_handler(RecordAccessDeniedError, _access_denied)
    app.add_exception_handler(HealthError, _health_failed)
