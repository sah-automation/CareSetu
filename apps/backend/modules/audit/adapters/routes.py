"""MOD-011: HTTP adapter for the audit query surfaces (PHASE-4 T6, #240; T7, #241).

The endpoints are thin adapters (api-standards A1): resolve the gateway
``Principal``, call the audit facade, return the typed view/page. They sit
behind the gateway middleware stack in ``app.main``; the ``require_operator``
dependency (NFR-SEC-003) admits only an authenticated operator scope for the
ledger query and ``require_patient`` admits only a patient for the access
history, so a caller of the wrong role - or an anonymous one - is refused at
the edge with the shared gateway error envelope. Every input is a validated
query param and the responses are Pydantic shapes (api-standards A3). The
query paths raise no module-level domain exceptions, so they need no module
error handler of their own - RBAC rejections answer through the gateway
handlers and anything unexpected falls to the app catch-all.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status

from app.gateway.errors import InsufficientScopeError
from app.gateway.principal import Principal
from app.gateway.rbac import require_operator, require_patient
from modules.audit.facade import AuditFacade, AuditPage
from modules.health.facade import AccessHistoryView

router = APIRouter(tags=["audit"])

#: Default and ceiling for one page of audit results (ticket #240: default
#: 20, max 100).
_DEFAULT_PAGE_SIZE = 20
_MAX_PAGE_SIZE = 100


@router.get(
    "/v1/audit/events",
    response_model=AuditPage,
    status_code=status.HTTP_200_OK,
    summary="Query the audit ledger (operator only)",
)
async def query_audit_events(
    request: Request,
    principal: Annotated[Principal, Depends(require_operator)],
    actor_id: Annotated[UUID | None, Query()] = None,
    event_type: Annotated[str | None, Query()] = None,
    target_id: Annotated[UUID | None, Query()] = None,
    scope: Annotated[str | None, Query()] = None,
    from_ts: Annotated[datetime | None, Query()] = None,
    to_ts: Annotated[datetime | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=_MAX_PAGE_SIZE)] = _DEFAULT_PAGE_SIZE,
) -> AuditPage:
    """Query the hash-chained ``audit_events`` ledger as an operator.

    Any non-null filter narrows the SELECT; with no filters the whole ledger
    is returned, newest first, one page at a time. ``total_count`` is the
    full match count (not just the page), so the caller can page through the
    complete result set.
    """
    del principal
    facade = cast(AuditFacade, request.app.state.audit_facade)
    return await facade.query_audit(
        actor_id=actor_id,
        event_type=event_type,
        target_id=target_id,
        scope=scope,
        from_ts=from_ts,
        to_ts=to_ts,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/v1/audit/access-history",
    response_model=AccessHistoryView,
    status_code=status.HTTP_200_OK,
    summary="Read the caller's own record access history (patient only)",
)
async def read_access_history(
    request: Request,
    principal: Annotated[Principal, Depends(require_patient)],
    patient_id: Annotated[int, Query(ge=1)],
) -> AccessHistoryView:
    """Patient access-history read: own record only (FEAT-003, T7).

    ``patient_id`` must equal the authenticated caller's subject id; any other
    value is a cross-patient probe and answers the gateway's 403 envelope -
    and, being an access denial, is audited through the gateway's
    ``_emit_access_denial`` path (security-phii-standards KPI-006). The typed
    view is delegated to MOD-003's ``get_access_history`` through the audit
    facade seam.
    """
    if patient_id != int(principal.subject_id):
        raise InsufficientScopeError("patients may only view their own access history")
    facade = cast(AuditFacade, request.app.state.audit_facade)
    # Identity comes from the token, never the client (own-record rules);
    # the query param only exists to be cross-checked above.
    return await facade.get_access_history(int(principal.subject_id))
