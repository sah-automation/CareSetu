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

from modules.iam.adapters.sms import mask_phone
from modules.iam.domain import events, jwt, refresh
from modules.iam.domain.exceptions import (
    OperatorMfaError,
    RefreshTokenExpiredError,
    RefreshTokenRevokedError,
    RefreshTokenUnknownError,
    SessionIssuanceError,
)
from modules.iam.domain.shared import _identity_phone
from modules.iam.domain.verify import IDENTITY_ACTIVE, IDENTITY_SUSPENDED
from modules.iam.outbox import IAM_OUTBOX_TABLE
from modules.iam.schema.models import (
    iam_identities,
    iam_operator_mfa,
    iam_role_grants,
    iam_sessions,
)

if TYPE_CHECKING:
    from modules.iam.domain.shared import IdentityGuardState

_IAM_SCHEMA = "iam"
_PATIENT_ROLE = "patient"
_PARTNER_ROLE = "partner"
_OPERATOR_ROLE = "operator"


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
        mfa_secret_key: str = "",
    ) -> None:
        self._engine = engine
        self._clock = clock
        self._access_token_signing_key = access_token_signing_key
        self._access_token_ttl_seconds = access_token_ttl_seconds
        self._refresh_token_ttl_seconds = refresh_token_ttl_seconds
        self._mfa_secret_key = mfa_secret_key

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
                    f"no identity for {mask_phone(phone_e164)}; "
                    "register the phone before issuing a session"
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

    async def issue_operator_session(self, phone: str, code: str) -> SessionResult:
        """Mint an operator-scoped access JWT (T07, ticket #250; S8, #261).

        Operators are a trusted closed group that never self-registers; a
        session is minted only after the MFA second factor has been completed
        at login. Mirror of ``issue_session`` for the ``operator`` role with an
        extra gate: the identity must be ``Active``, hold an ``Active``
        ``operator`` role grant, AND have an enrolled, verified MFA factor
        (``iam_operator_mfa.mfa_enabled`` with a recorded ``last_verified_at``).
        If MFA is not enrolled or not yet verified, an ``OperatorMfaError``
        names the missing precondition - an operator can never land an
        operator-scoped session on the phone-OTP factor alone. The minted
        ``scope`` resolves to ``operator`` so the gateway's ``require_operator``
        admits the caller.

        The ``code`` parameter is an RFC-6238 TOTP code derived from the
        operator's enrolled MFA secret.  It is verified against the decrypted
        ``iam_operator_mfa.secret`` at the current clock time with a small drift
        window (S8, #261).  A wrong or expired code is rejected with
        ``OperatorMfaError`` (a ``SessionIssuanceError`` subclass the edge
        answers 401, ticket #262).
        """
        from modules.iam.domain.phone import normalize_phone
        from modules.iam.domain.secret_encryption import decrypt_secret
        from modules.iam.domain.totp import (
            TotpSecretEmptyError,
            TotpVerificationError,
            verify_totp,
        )

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
                    f"no identity for {mask_phone(phone_e164)}; "
                    "invite the operator before issuing a session"
                )
            identity_id = locked.identity_id
            identity_status = locked.status
            if identity_status != IDENTITY_ACTIVE:
                raise SessionIssuanceError(
                    f"identity {identity_id} is {identity_status}, not Active; "
                    "verify the phone before issuing a session"
                )
            if not await _mfa_verified(connection, identity_id):
                raise OperatorMfaError(
                    f"identity {identity_id} has not completed the MFA second factor; "
                    "enroll and verify MFA before issuing an operator session"
                )

            # S8: genuine TOTP verification - decrypt the stored secret and
            # verify the presented code at the current clock time.  The MFA
            # row is guaranteed non-None by the ``_mfa_verified`` gate above.
            if not self._mfa_secret_key:
                raise SessionIssuanceError(
                    f"identity {identity_id} cannot complete MFA: encryption key "
                    "is not configured (set IAM_MFA_SECRET_KEY)"
                )
            secret_ciphertext = (
                await connection.execute(
                    select(iam_operator_mfa.c.secret).where(
                        iam_operator_mfa.c.identity_id == identity_id
                    )
                )
            ).scalar_one_or_none()
            if not secret_ciphertext:
                raise OperatorMfaError(
                    f"identity {identity_id} has no enrolled TOTP secret; "
                    "complete MFA enrollment before issuing an operator session"
                )
            try:
                decrypted_secret = decrypt_secret(secret_ciphertext, self._mfa_secret_key)
                verify_totp(decrypted_secret, code, clock=self._clock)
            except (TotpSecretEmptyError, TotpVerificationError, ValueError) as exc:
                raise OperatorMfaError(
                    f"TOTP verification failed for identity {identity_id}: {exc}"
                ) from exc

            scope = await _resolve_active_role(connection, identity_id, _OPERATOR_ROLE)
            if scope is None:
                raise SessionIssuanceError(
                    f"identity {identity_id} has no active operator role grant"
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
                scope_name = session_row["scope"]
                scope = await _resolve_active_role(connection, identity_id, scope_name)
                if scope is None:
                    raise RefreshTokenRevokedError(
                        f"identity {identity_id} has no active {scope_name} role grant; "
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
    from modules.iam.domain.shared import _lock_identity_row

    return await _lock_identity_row(connection, iam_identities.c.phone_e164 == phone_e164)


async def _lock_identity_by_id(
    connection: AsyncConnection, identity_id: int
) -> IdentityGuardState | None:
    """Row-lock an identity by id and return its guard state (ticket #58)."""
    from modules.iam.domain.shared import _lock_identity_row

    return await _lock_identity_row(connection, iam_identities.c.id == identity_id)


async def _session_for_refresh(connection: AsyncConnection, token_hash: str) -> RowMapping | None:
    """The session row for a refresh-token hash, locked to serialize rotation."""
    return (
        (
            await connection.execute(
                select(
                    iam_sessions.c.id,
                    iam_sessions.c.identity_id,
                    iam_sessions.c.scope,
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


async def _mfa_verified(connection: AsyncConnection, identity_id: int) -> bool:
    """Whether ``identity_id`` has completed the MFA second factor (T07, #250).

    The operator MFA gate reads the ``iam_operator_mfa`` row (seeded by T01,
    #244): the factor must be enrolled (``mfa_enabled``) and a successful
    verification must have been recorded (``last_verified_at`` set). Both are
    required - an enrolled-but-never-verified factor, or a row with no
    enrollment at all, refuses the operator session (fail-closed). The phone
    OTP factor alone never admits an operator-scoped session.
    """
    row = (
        (
            await connection.execute(
                select(
                    iam_operator_mfa.c.mfa_enabled,
                    iam_operator_mfa.c.last_verified_at,
                )
                .where(iam_operator_mfa.c.identity_id == identity_id)
                .limit(1)
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        return False
    return bool(row["mfa_enabled"]) and row["last_verified_at"] is not None


async def _grant_or_reactivate_role(
    connection: AsyncConnection, identity_id: int, role: str
) -> None:
    """Grant (or restore) a role on ``identity_id`` (T03 #248, T07 #250).

    Idempotent: an existing ``Active`` grant is left untouched, a missing one is
    inserted, and a ``Suspended`` one is flipped back to ``Active``.  Runs on
    the consumer's delivery connection inside the same transaction as the
    ``consumed_events`` ledger row (ADR-0002 §3).
    """
    await connection.execute(
        iam_role_grants.update()
        .where(
            iam_role_grants.c.identity_id == identity_id,
            iam_role_grants.c.role == role,
            iam_role_grants.c.status == IDENTITY_SUSPENDED,
        )
        .values(status=IDENTITY_ACTIVE)
    )
    existing = (
        await connection.execute(
            select(iam_role_grants.c.id).where(
                iam_role_grants.c.identity_id == identity_id,
                iam_role_grants.c.role == role,
                iam_role_grants.c.status == IDENTITY_ACTIVE,
            )
        )
    ).first()
    if existing is None:
        await connection.execute(
            iam_role_grants.insert().values(
                identity_id=identity_id, role=role, status=IDENTITY_ACTIVE
            )
        )


async def grant_partner_role(connection: AsyncConnection, identity_id: int) -> None:
    """Grant (or restore) the ``partner`` role on ``identity_id`` (T03, #248)."""
    await _grant_or_reactivate_role(connection, identity_id, _PARTNER_ROLE)


async def suspend_partner_role(connection: AsyncConnection, identity_id: int) -> None:
    """Suspend the ``partner`` role on ``identity_id`` (T03, #248).

    Flips an ``Active`` partner grant to ``Suspended``; a missing grant (never
    activated) or one already suspended is left alone, so the deny is idempotent
    even when no grant row exists. Runs on the consumer's delivery connection in
    the same transaction as the ``consumed_events`` ledger row.
    """

    await connection.execute(
        iam_role_grants.update()
        .where(
            iam_role_grants.c.identity_id == identity_id,
            iam_role_grants.c.role == _PARTNER_ROLE,
            iam_role_grants.c.status == IDENTITY_ACTIVE,
        )
        .values(status=IDENTITY_SUSPENDED)
    )


async def grant_operator_role(connection: AsyncConnection, identity_id: int) -> None:
    """Grant (or restore) the ``operator`` role on ``identity_id`` (T07, #250)."""
    await _grant_or_reactivate_role(connection, identity_id, _OPERATOR_ROLE)


async def _partner_role_status(connection: AsyncConnection, identity_id: int) -> str | None:
    """The ``partner`` role grant status for ``identity_id`` (None if none)."""
    return (
        await connection.execute(
            select(iam_role_grants.c.status)
            .where(
                iam_role_grants.c.identity_id == identity_id,
                iam_role_grants.c.role == _PARTNER_ROLE,
            )
            .limit(1)
        )
    ).scalar_one_or_none()
