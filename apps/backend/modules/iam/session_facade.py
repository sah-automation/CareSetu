"""MOD-001: Session sub-facade (ADR-0006, ticket #166).

Owns session JWT issuance, access-token validation, and refresh-token
rotation.  The coordinator ``IamFacade`` delegates to this class; routes
and tests see the same public surface as before (ADR-0006 decision 2).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from modules.iam.domain import events, jwt, refresh
from modules.iam.domain.exceptions import (
    RefreshTokenExpiredError,
    RefreshTokenRevokedError,
    RefreshTokenUnknownError,
    SessionIssuanceError,
)
from modules.iam.domain.verify import IDENTITY_ACTIVE
from modules.iam.outbox import IAM_OUTBOX_TABLE
from modules.iam.schema.models import (
    iam_identities,
    iam_role_grants,
    iam_sessions,
)

if TYPE_CHECKING:
    from modules.iam.facade import IdentityGuardState

_IAM_SCHEMA = "iam"
_PATIENT_ROLE = "patient"


class SessionResult(BaseModel):
    """A session, whether freshly issued or rotated (spec #51 section 2.5, tickets #57, #58).

    One model for both paths: ``issue_session`` mints the first session for a
    verified patient, and ``refresh_session`` rotates an opaque refresh token
    into the same shape.  ``jwt`` is the HS256 access JWT the PWA stores;
    ``jti``/``expires_in_seconds`` mirror its claims so the client can show a
    session indicator, and ``scope`` is the resolved RBAC scope - always from
    the patient role grant, never from client input.  ``refresh_token`` is the
    opaque, server-side-hashed refresh token the PWA keeps for the next
    ``refresh_session``; on a rotation the previous refresh token is already
    invalid by the time the result is returned.
    """

    jwt: str
    jti: str
    scope: str
    identity_id: int
    expires_in_seconds: int
    refresh_token: str


class ValidatedAccessToken(BaseModel):
    """Claims of a verified access JWT, as the gateway attaches them (ticket #57, T8).

    ``subject_id`` is the identity id the gateway scopes to the patient's own
    record; ``scope`` is the RBAC scope resolved from the token claim.
    """

    subject_id: int
    scope: str
    jti: str


def _default_clock() -> datetime:
    return datetime.now(UTC)


class SessionFacade:
    """Sub-facade for session JWT issuance, validation, and refresh (ADR-0006)."""

    def __init__(
        self,
        engine: AsyncEngine,
        clock: Callable[[], datetime] = _default_clock,
        *,
        access_token_signing_key: str = "",
        access_token_ttl_seconds: int = jwt.ACCESS_TOKEN_TTL_SECONDS,
        refresh_token_ttl_seconds: int = refresh.REFRESH_TOKEN_TTL_SECONDS,
    ) -> None:
        self._engine = engine
        self._clock = clock
        self._access_token_signing_key = access_token_signing_key
        self._access_token_ttl_seconds = access_token_ttl_seconds
        self._refresh_token_ttl_seconds = refresh_token_ttl_seconds

    async def issue_session(self, phone: str) -> SessionResult:
        """Mint an access JWT for a verified patient (spec #51 section 2.5, ticket #57).

        The scope claim is always derived from the patient's active role grant,
        never from the client (acceptance criterion #3): the identity must be
        ``Active`` (OTP-verified) and hold an ``Active`` patient grant, else a
        ``SessionIssuanceError`` names the missing precondition.  A fresh ``jti``
        is generated per token, ``exp`` is ~15 minutes out so a stolen token has
        limited value, and the session row is recorded in the ``iam``
        ``sessions`` table in the same transaction - the jti is the anchor the
        refresh rotation (T7) and revocation check against, and the row also
        carries the SHA-256 of a fresh opaque refresh token (never the token
        itself) with its ~30-day sliding ``refresh_expires_at``.  An empty signing
        key fails closed rather than minting a token anyone could forge.
        """
        from modules.iam.domain.phone import normalize_phone

        phone_e164 = normalize_phone(phone)
        if not self._access_token_signing_key:
            raise SessionIssuanceError(
                "access-token signing key is not configured; refusing to issue a session"
            )
        now = self._clock()

        async with self._engine.begin() as connection:
            locked = await _lock_identity_by_phone(connection, phone_e164)
            if locked is None:
                raise SessionIssuanceError(
                    f"no identity for {phone_e164}; register the phone before issuing a session"
                )
            identity_id = locked.identity_id
            identity_status = locked.status
            if identity_status != IDENTITY_ACTIVE:
                raise SessionIssuanceError(
                    f"identity {identity_id} is {identity_status}, not Active; "
                    "verify the OTP before issuing a session"
                )
            scope = await _resolve_active_role(connection, identity_id, _PATIENT_ROLE)
            if scope is None:
                raise SessionIssuanceError(
                    f"identity {identity_id} has no active patient role grant"
                )

            jti, refresh_token, token = await self._mint_session_row(
                connection, identity_id, scope, now
            )

        return SessionResult(
            jwt=token,
            jti=jti,
            scope=scope,
            identity_id=identity_id,
            expires_in_seconds=self._access_token_ttl_seconds,
            refresh_token=refresh_token,
        )

    async def validate_token(self, token: str) -> ValidatedAccessToken:
        """Resolve a valid access JWT to its scope for the gateway (ticket #57).

        A pure signature + expiry check with no database round-trip (acceptance
        criterion #4), so the edge hot path stays far under the 100 ms p95
        (MOD-001 section 3.1): the signing key and the clock are all it needs.  Every
        rejection raises the matching ``InvalidAccessTokenError`` subclass -
        expired, malformed, or wrong signature - for the gateway to deny with a
        single 401.
        """
        claims = jwt.verify_token(token, self._access_token_signing_key, now=self._clock())
        return ValidatedAccessToken(
            subject_id=claims.subject_id, scope=claims.scope, jti=claims.jti
        )

    async def refresh_session(self, refresh_token: str) -> SessionResult:
        """Rotate an opaque refresh token into a fresh session (ticket #58).

        The refresh path is fully independent of SMS (NFR-004): it only reads
        the ``sessions`` table and mints tokens, so an EXT-001 outage never
        bricks an existing session.  The token is looked up by its SHA-256
        (opaque, never stored or logged in clear); an unknown token, a revoked
        one, and an expired one are each refused with their own
        ``InvalidRefreshTokenError`` subclass (acceptance criterion #3).

        The seam is backend-only: an internal rotation path with no HTTP route,
        no frontend consumer, and no lifecycle outbox event.  Clients reach a
        session only through ``issue_session`` and call ``refresh_session``
        when the access JWT expires; its only outbox write is the
        ``patient.auth_failed`` replay audit on a refused rotation.

        A valid token rotates in the same transaction as the mint: the old
        session row is revoked (``revoked_at``) and a fresh row records the new
        access ``jti`` with a brand-new refresh token whose lifetime slides to
        ~30 days from ``now``.  Presenting the already-rotated token afterwards
        finds the revoked row - a replay signal - and is refused while
        ``patient.auth_failed`` is committed to the outbox in the same
        transaction (audit can tell a stolen-session replay from a garbage
        token, which matches nothing).  The scope of the fresh JWT is re-derived
        from the identity's current active role grant, never from the old
        token.  The identity row is locked ``FOR UPDATE`` (after the session
        row) so a concurrent role change cannot race the refresh, and the
        session-row lock serializes two concurrent refreshes of the same token
        so only one rotation wins.  An empty signing key fails closed exactly
        like ``issue_session``.
        """
        if not self._access_token_signing_key:
            raise SessionIssuanceError(
                "access-token signing key is not configured; refusing to refresh a session"
            )
        now = self._clock()
        token_hash = refresh.hash_refresh_token(refresh_token)
        replay_signal = False

        async with self._engine.begin() as connection:
            session_row = await _session_for_refresh(connection, token_hash)
            if session_row is None:
                raise RefreshTokenUnknownError("no session matches this refresh token")

            decision = refresh.evaluate_refresh(
                revoked_at=session_row["revoked_at"],
                refresh_expires_at=session_row["refresh_expires_at"],
                now=now,
            )

            if decision.reason == "revoked":
                from modules.iam.facade import _identity_phone

                phone = await _identity_phone(connection, session_row["identity_id"])
                await bus_outbox_write(
                    connection,
                    _IAM_SCHEMA,
                    IAM_OUTBOX_TABLE,
                    events.patient_auth_failed_envelope(
                        identity_id=session_row["identity_id"],
                        phone_e164=phone,
                        reason="replay",
                    ),
                )
                replay_signal = True
            elif decision.reason == "expired":
                raise RefreshTokenExpiredError(
                    "this refresh token has expired; re-authenticate to continue"
                )
            else:
                identity = await _lock_identity_by_id(connection, session_row["identity_id"])
                if identity is None:
                    raise RefreshTokenRevokedError("the session identity no longer exists")
                identity_id = identity.identity_id
                identity_status = identity.status
                if identity_status != IDENTITY_ACTIVE:
                    raise RefreshTokenRevokedError(
                        f"identity {identity_id} is {identity_status}; refusing to refresh"
                    )
                scope = await _resolve_active_role(connection, identity_id, _PATIENT_ROLE)
                if scope is None:
                    raise RefreshTokenRevokedError(
                        f"identity {identity_id} has no active patient role grant; "
                        "refusing to refresh"
                    )

                new_jti, new_refresh_token, token = await self._mint_session_row(
                    connection, identity_id, scope, now
                )
                await connection.execute(
                    iam_sessions.update()
                    .where(iam_sessions.c.id == session_row["id"])
                    .values(revoked_at=now)
                )

        if replay_signal:
            raise RefreshTokenRevokedError(
                "this refresh token was already used or revoked; refusing to refresh"
            )

        return SessionResult(
            jwt=token,
            jti=new_jti,
            scope=scope,
            identity_id=identity_id,
            expires_in_seconds=self._access_token_ttl_seconds,
            refresh_token=new_refresh_token,
        )

    async def _mint_session_row(
        self,
        connection: AsyncConnection,
        identity_id: int,
        scope: str,
        now: datetime,
    ) -> tuple[str, str, str]:
        """Mint a fresh access JWT + opaque refresh token and record the session row.

        Shared by ``issue_session`` and ``refresh_session`` so both mint the
        same row shape: a random ``jti``, a fresh opaque refresh token (stored
        hashed, never in clear) with its ~30-day sliding ``refresh_expires_at``,
        and an access JWT whose ``exp`` is the access-token TTL out.  Returns
        ``(jti, refresh_token, jwt)``.
        """
        jti = uuid.uuid4().hex
        refresh_token = refresh.generate_refresh_token()
        token = jwt.issue_token(
            jti=jti,
            subject_id=identity_id,
            scope=scope,
            signing_key=self._access_token_signing_key,
            now=now,
            ttl_seconds=self._access_token_ttl_seconds,
        )
        await connection.execute(
            iam_sessions.insert().values(
                jti=jti,
                identity_id=identity_id,
                scope=scope,
                issued_at=now,
                expires_at=now + timedelta(seconds=self._access_token_ttl_seconds),
                refresh_token_hash=refresh.hash_refresh_token(refresh_token),
                refresh_expires_at=now + timedelta(seconds=self._refresh_token_ttl_seconds),
            )
        )
        return jti, refresh_token, token


# ---------------------------------------------------------------------------
# Module-level helpers (thin wrappers, no ``self``)
# ---------------------------------------------------------------------------

from bus.outbox_writer import write_outbox as bus_outbox_write  # noqa: E402


async def _lock_identity_by_phone(
    connection: AsyncConnection, phone_e164: str
) -> IdentityGuardState | None:
    """Row-lock the identity for ``phone_e164`` and return its guard state."""
    from modules.iam.facade import _lock_identity_row

    return await _lock_identity_row(connection, iam_identities.c.phone_e164 == phone_e164)


async def _lock_identity_by_id(
    connection: AsyncConnection, identity_id: int
) -> IdentityGuardState | None:
    """Row-lock an identity by id and return its guard state (ticket #58)."""
    from modules.iam.facade import _lock_identity_row

    return await _lock_identity_row(connection, iam_identities.c.id == identity_id)


async def _session_for_refresh(connection: AsyncConnection, token_hash: str) -> RowMapping | None:
    """The session row for a refresh-token hash, locked to serialize rotation."""
    return (
        (
            await connection.execute(
                select(
                    iam_sessions.c.id,
                    iam_sessions.c.identity_id,
                    iam_sessions.c.revoked_at,
                    iam_sessions.c.refresh_expires_at,
                )
                .where(iam_sessions.c.refresh_token_hash == token_hash)
                .with_for_update()
            )
        )
        .mappings()
        .first()
    )


async def _resolve_active_role(
    connection: AsyncConnection, identity_id: int, role: str
) -> str | None:
    """The role name if ``identity_id`` holds an Active grant for ``role``."""
    return (
        await connection.execute(
            select(iam_role_grants.c.role)
            .where(
                iam_role_grants.c.identity_id == identity_id,
                iam_role_grants.c.role == role,
                iam_role_grants.c.status == IDENTITY_ACTIVE,
            )
            .limit(1)
        )
    ).scalar_one_or_none()
