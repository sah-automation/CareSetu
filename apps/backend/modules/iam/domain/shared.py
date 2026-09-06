"""MOD-001: shared internal helpers for IAM sub-facades (ADR-0006).

``IdentityGuardState`` and ``_lock_identity_row`` are consumed by both
the identity and OTP sub-facades.  ``_invalidate_pending_challenges`` and
``_issue_challenge`` are the latest-wins challenge lifecycle helpers shared
by ``register_patient`` and ``resend_otp``.  ``_latest_cooldown_until`` is
the shared cooldown query used by both ``register_patient`` and ``resend_otp``.
``_reissue_otp_challenge`` composes those primitives into the one shared OTP
challenge re-issue choreography (ticket #335, WI-4).  ``_identity_phone``
resolves a phone_e164 from an identity id, shared by the access-denial
emitter and the refresh-replay path.  ``OtpSender`` is the port that decouples
sub-facades from the SMS adapter - the coordinator wires the
``SmsDeliveryQueue`` behind it.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import cast

from sqlalchemy import ColumnElement, select
from sqlalchemy.ext.asyncio import AsyncConnection

from bus.outbox_writer import write_outbox
from modules.iam.domain import events
from modules.iam.domain.exceptions import IamError
from modules.iam.domain.otp import OTP_TTL_SECONDS, RESEND_COOLDOWN_SECONDS, generate_otp, hash_otp
from modules.iam.domain.resend import evaluate_resend
from modules.iam.domain.verify import CHALLENGE_EXPIRED, CHALLENGE_PENDING
from modules.iam.outbox import IAM_OUTBOX_TABLE
from modules.iam.schema.models import iam_identities, iam_otp_challenges

_IAM_SCHEMA = "iam"
_PATIENT_ROLE = "patient"

OtpSender = Callable[[str, str], Awaitable[None]]
"""Port: ``(phone_e164, otp) -> None``.  The coordinator wires
``SmsDeliveryQueue.enqueue`` behind this so sub-facades never touch adapter
types."""


@dataclass(frozen=True)
class IdentityGuardState:
    """The identity row's guard columns, read under the ``FOR UPDATE`` row lock.

    ``status`` drives the Suspended/Active guards, ``lockout_until`` the
    brute-force lockout check, and ``lockout_failed_attempts`` seeds the
    streak evaluation for the next rejection. Every row-lock call site reads
    these four columns through this one typed object.
    """

    identity_id: int
    status: str
    lockout_failed_attempts: int
    lockout_until: datetime | None


async def _lock_identity_row(
    connection: AsyncConnection, predicate: ColumnElement[bool]
) -> IdentityGuardState | None:
    """Row-lock the identity matching ``predicate`` and return its guard state.

    The core shared by ``_lock_identity`` (by phone) and ``_lock_identity_by_id``
    (by id); ``FOR UPDATE`` serializes concurrent writers so the failure counter
    cannot race and the identity guards see stable values.
    """
    row = (
        (
            await connection.execute(
                select(
                    iam_identities.c.id,
                    iam_identities.c.status,
                    iam_identities.c.lockout_failed_attempts,
                    iam_identities.c.lockout_until,
                )
                .where(predicate)
                .with_for_update()
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    return IdentityGuardState(
        identity_id=row["id"],
        status=row["status"],
        lockout_failed_attempts=row["lockout_failed_attempts"],
        lockout_until=row["lockout_until"],
    )


async def _invalidate_pending_challenges(connection: AsyncConnection, identity_id: int) -> None:
    """Expire every Pending challenge for the identity (latest-wins).

    Reissuing a code for a phone shadows the prior pending one (spec #51
    section 2.4): the expired challenge can no longer verify. Runs in the same
    transaction as the fresh insert, so the invalidation and the issuance
    commit as one change and a verification can never interleave between
    them (the caller holds the identity row ``FOR UPDATE``).
    """
    await connection.execute(
        iam_otp_challenges.update()
        .where(
            iam_otp_challenges.c.identity_id == identity_id,
            iam_otp_challenges.c.status == CHALLENGE_PENDING,
        )
        .values(status=CHALLENGE_EXPIRED)
    )


async def _issue_challenge(
    connection: AsyncConnection,
    *,
    identity_id: int,
    phone_e164: str,
    now: datetime,
) -> tuple[int, str]:
    """Issue a fresh Pending challenge and publish ``otp.sent``.

    The single place a challenge is born, shared by ``register_patient``
    and ``resend_otp``: inserts the hashed OTP row and lands ``otp.sent``
    in the iam outbox in the same transaction as the invalidation. Returns
    ``(challenge_id, otp)`` so the caller can schedule exactly one EXT-001
    delivery after the transaction commits - one issuance, one SMS cost
    (SMS-cost rule, FIX 2) - and never before commit, so a rollback can
    never leave a sent code with no persisted challenge.
    """
    otp = generate_otp()
    expires_at = now + timedelta(seconds=OTP_TTL_SECONDS)
    cooldown_until = now + timedelta(seconds=RESEND_COOLDOWN_SECONDS)
    challenge_id = cast(
        int,
        (
            await connection.execute(
                iam_otp_challenges.insert()
                .values(
                    identity_id=identity_id,
                    otp_hash=hash_otp(otp),
                    status=CHALLENGE_PENDING,
                    attempts=0,
                    expires_at=expires_at,
                    cooldown_until=cooldown_until,
                )
                .returning(iam_otp_challenges.c.id)
            )
        ).scalar_one(),
    )
    await write_outbox(
        connection,
        _IAM_SCHEMA,
        IAM_OUTBOX_TABLE,
        events.otp_sent_envelope(identity_id, challenge_id, expires_at),
    )
    return challenge_id, otp


async def _latest_cooldown_until(connection: AsyncConnection, identity_id: int) -> datetime | None:
    """The latest challenge's ``cooldown_until`` for the identity, or None.

    The resend cooldown is measured per phone from the last issuance (spec
    #51 section 2.4), and challenges are issued per identity - so the newest
    challenge row carries the cooldown boundary.  Shared by ``register_patient``
    and ``resend_otp``.
    """
    return (
        await connection.execute(
            select(iam_otp_challenges.c.cooldown_until)
            .where(iam_otp_challenges.c.identity_id == identity_id)
            .order_by(iam_otp_challenges.c.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


@dataclass(frozen=True)
class OtpReissueResult:
    """Outcome of an OTP challenge re-issue attempt.

    Composes the shared primitives (lock, cooldown check, invalidate, issue)
    into a single call so both the registration and resend flows share identical
    cooldown/lockout semantics. Each flow maps this outcome to its own result
    type, preserving the distinct registration and resend responses.
    """

    outcome: str
    identity_id: int
    phone_e164: str
    challenge_id: int | None = None
    otp: str | None = None
    cooldown_remaining_seconds: int | None = None
    lockout_remaining_seconds: int | None = None

    def sent_challenge(self) -> tuple[int, str]:
        """The fresh challenge for a ``sent`` outcome, raising if absent.

        Defines the ``sent`` implies bound-challenge invariant once, here, so
        each flow collapses to plain tuple unpacking instead of re-guarding
        the optional fields (WI-4, #335).
        """
        if self.outcome != "sent" or self.challenge_id is None or self.otp is None:
            raise IamError("reissue sent without a challenge")
        return self.challenge_id, self.otp


async def _reissue_otp_challenge(
    connection: AsyncConnection,
    *,
    identity_id: int,
    phone_e164: str,
    identity_status: str,
    lockout_until: datetime | None,
    now: datetime,
) -> OtpReissueResult:
    """Shared OTP challenge re-issue primitive (WI-4, ticket #335).

    Composes the shared challenge primitives: evaluate the resend decision
    against the guard state, and if allowed, invalidate pending challenges
    and issue a fresh challenge. The registration and resend flows both use
    this primitive, so cooldown and lockout semantics are defined once. Each
    flow maps the shared outcome to its own result type, preserving the
    distinct registration and resend responses.

    The caller must hold the identity row ``FOR UPDATE`` (via
    ``_lock_identity_row``) in the same transaction, so the guard state is
    stable and the invalidation + issuance commit as one change.
    """
    cooldown_until = await _latest_cooldown_until(connection, identity_id)
    decision = evaluate_resend(
        identity_status=identity_status,
        lockout_until=lockout_until,
        cooldown_until=cooldown_until,
        now=now,
    )

    if decision.outcome != "sent":
        return OtpReissueResult(
            outcome=decision.outcome,
            identity_id=identity_id,
            phone_e164=phone_e164,
            cooldown_remaining_seconds=decision.cooldown_remaining_seconds,
            lockout_remaining_seconds=decision.lockout_remaining_seconds,
        )

    await _invalidate_pending_challenges(connection, identity_id)
    challenge_id, otp = await _issue_challenge(
        connection,
        identity_id=identity_id,
        phone_e164=phone_e164,
        now=now,
    )

    return OtpReissueResult(
        outcome="sent",
        identity_id=identity_id,
        phone_e164=phone_e164,
        challenge_id=challenge_id,
        otp=otp,
    )


async def _identity_phone(connection: AsyncConnection, identity_id: int) -> str:
    """The ``phone_e164`` for an identity, for an audit event that names it.

    Used by the refresh-replay path (``patient.auth_failed`` reason
    ``replay``) and by the access-denial emitter (reason
    ``access_denied``, PHASE-2 REM T7 #87). A session row's FK guarantees
    the identity exists; the fallback keeps the outbox write safe even if a
    row were ever orphaned.
    """
    return (
        await connection.execute(
            select(iam_identities.c.phone_e164).where(iam_identities.c.id == identity_id)
        )
    ).scalar_one_or_none() or ""
