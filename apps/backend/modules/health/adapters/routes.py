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

from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, FastAPI, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.gateway.errors import error_response
from app.gateway.idempotency import run_idempotent
from app.gateway.principal import Principal
from app.gateway.rbac import require_partner, require_patient
from modules.health.domain.exceptions import (
    HealthBackgroundAcknowledgmentRequiredError,
    HealthError,
    RecordAccessDeniedError,
    RecordNotFoundError,
)
from modules.health.facade import (
    HealthBackground,
    HealthBackgroundView,
    HealthFacade,
    RecordTimeline,
)

router = APIRouter(tags=["record"])


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


class HealthBackgroundSaveRequest(BaseModel):
    """Input of the patient's health-background save (#534).

    The snapshot fields plus the one-time ``acknowledge_phi`` flag: the first
    save must carry the explicit acknowledgment that the snapshot becomes
    visible to the patient's verified doctors (ADR-0018) - a first save
    without it is rejected; later edits never re-prompt.
    """

    acknowledge_phi: bool
    background: HealthBackground


@router.get(
    "/v1/me/health-background",
    response_model=HealthBackgroundView,
    status_code=status.HTTP_200_OK,
    summary="Read the caller's health background snapshot",
)
async def read_health_background(
    request: Request,
    principal: Annotated[Principal, Depends(require_patient)],
) -> HealthBackgroundView:
    """Owner read resolved from the session subject - zero setup.

    The snapshot is addressed by the token's subject id (never client input):
    a patient who has not saved one yet answers the typed "not recorded" view.
    This surface serves the owning patient only (the ``require_patient`` gate
    plus owner-scoping in the facade); a doctor read is consent-gated on a
    separate doctor-facing surface in later work and never reaches this route.
    """
    facade = cast(HealthFacade, request.app.state.health_facade)
    return await facade.get_health_background(int(principal.subject_id))


@router.put(
    "/v1/me/health-background",
    response_model=HealthBackgroundView,
    status_code=status.HTTP_200_OK,
    summary="Save or update the caller's health background snapshot",
)
async def save_health_background(
    request: Request,
    payload: HealthBackgroundSaveRequest,
    principal: Annotated[Principal, Depends(require_patient)],
) -> HealthBackgroundView:
    """Persist the caller's health-background snapshot idempotently (#534).

    The first save requires ``acknowledge_phi`` and, on that acknowledged save,
    records the ``health_background`` consent grant to every doctor the patient
    has a live relationship with - atomically with the snapshot write. Later
    edits converge on the one row and never re-prompt. The mutation honours the
    ``Idempotency-Key`` replay contract (api-standards §5) like the other
    ``/v1/me`` mutations, namespaced to the principal's subject id.
    """
    facade = cast(HealthFacade, request.app.state.health_facade)
    saved = await run_idempotent(
        request,
        lambda: facade.save_health_background(
            int(principal.subject_id),
            payload.background,
            acknowledge_phi=payload.acknowledge_phi,
        ),
        namespace=f"identity:{principal.subject_id}",
    )
    return saved


def register_error_handlers(app: FastAPI) -> None:
    """Attach the MOD-003 error envelope to every expected health failure."""

    async def _record_not_found(request: Request, exc: Exception) -> JSONResponse:
        return error_response(
            status.HTTP_404_NOT_FOUND,
            "RECORD_NOT_FOUND",
            str(exc),
            log_tag="health_rejection",
            request=request,
        )

    async def _access_denied(request: Request, exc: Exception) -> JSONResponse:
        return error_response(
            status.HTTP_403_FORBIDDEN,
            "RECORD_ACCESS_DENIED",
            str(exc),
            log_tag="health_rejection",
            request=request,
        )

    async def _acknowledgment_required(request: Request, exc: Exception) -> JSONResponse:
        del exc
        return error_response(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "HEALTH_BACKGROUND_ACK_REQUIRED",
            "the first health-background save must acknowledge that the snapshot "
            "becomes visible to your doctors",
            log_tag="health_rejection",
            request=request,
        )

    async def _health_failed(request: Request, exc: Exception) -> JSONResponse:
        del exc
        return error_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "HEALTH_INTERNAL",
            "Internal health record error",
            log_tag="health_rejection",
            request=request,
        )

    app.add_exception_handler(RecordNotFoundError, _record_not_found)
    app.add_exception_handler(RecordAccessDeniedError, _access_denied)
    app.add_exception_handler(HealthBackgroundAcknowledgmentRequiredError, _acknowledgment_required)
    app.add_exception_handler(HealthError, _health_failed)
