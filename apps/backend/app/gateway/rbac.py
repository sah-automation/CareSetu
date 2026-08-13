"""RBAC scope resolution and protected-route dependency (PHASE-2 T8, ticket #59).

The gateway maps a verified access JWT to the caller's allowed RBAC scope
(api-standards §6, ``NFR-SEC-003``). A token's ``scope`` claim is a role name
resolved from the iam role grant at issuance (never client input), so the
resolver turns that claim into the ``Principal.roles`` tuple the route guards
check. ``require_patient`` is the dependency protected routes declare: it
denies anonymous callers (401) and non-patient scopes (403) at the edge.
"""

from __future__ import annotations

from fastapi import Request

from app.gateway.errors import AuthenticationRequiredError, InsufficientScopeError
from app.gateway.principal import Principal

# api-standards §6: role scopes - patient (own record), partner (own scope),
# operator (all records). Only ``patient`` is granted today; the others reserve
# the vocabulary so an unknown signed scope fails closed instead of silently
# widening access.
KNOWN_SCOPE_ROLES = ("patient", "partner", "operator")


def resolve_scope_roles(scope: str) -> tuple[str, ...]:
    """Map a token's ``scope`` claim to the ``Principal`` roles.

    Today the scope claim and the role name are the same string, so a known
    scope becomes its singleton role tuple. An unknown scope resolves to no
    roles - the principal is still authenticated but matches no route guard,
    which is the fail-closed direction for a scope this gateway does not know.
    """
    if scope in KNOWN_SCOPE_ROLES:
        return (scope,)
    return ()


async def require_patient(request: Request) -> Principal:
    """FastAPI dependency: admit only an authenticated patient-scoped caller.

    Reads the ``Principal`` the gateway's ``jwt_verify`` middleware attached to
    the request state. Anonymous or missing principals are refused with 401;
    an authenticated caller without the patient role is refused with 403
    (api-standards §6: patient = own record only).
    """
    principal: Principal | None = getattr(request.state, "principal", None)
    if principal is None or not principal.is_authenticated:
        raise AuthenticationRequiredError("no valid session on a protected route")
    if "patient" not in principal.roles:
        raise InsufficientScopeError("the patient role is required for this route")
    return principal
