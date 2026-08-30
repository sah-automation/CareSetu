"""MOD-011: HTTP adapter for the operator audit query surface (PHASE-4 T6, #240).

The endpoint is a thin adapter (api-standards A1): resolve the gateway
``Principal``, call the audit facade, return the typed page. It sits behind
the gateway middleware stack in ``app.main``; the ``require_operator`` RBAC
dependency (NFR-SEC-003) admits only an authenticated operator scope, so a
patient or partner caller - or an anonymous one - is refused at the edge with
the shared gateway error envelope. Every input filter is a validated query
param and the response is a Pydantic shape (api-standards A3). The query
path raises no module-level domain exceptions, so it needs no module error
handler of its own - RBAC rejections answer through the gateway handlers and
anything unexpected falls to the app catch-all.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status

from app.gateway.principal import Principal
from app.gateway.rbac import require_operator
from modules.audit.facade import AuditFacade, AuditPage

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
