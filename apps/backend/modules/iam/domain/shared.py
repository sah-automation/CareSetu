"""MOD-001: shared internal helpers for IAM sub-facades (ADR-0006).

``IdentityGuardState`` and ``_lock_identity_row`` are consumed by both
the identity and OTP sub-facades.  ``_invalidate_pending_challenges`` and
``_issue_challenge`` are the latest-wins challenge lifecycle helpers shared
by ``register_patient`` and ``resend_otp``.  ``_latest_cooldown_until`` is
the shared cooldown query used by both ``register_patient`` and ``resend_otp``.
``_identity_phone`` resolves a phone_e164 from an identity id, shared by the
access-denial emitter and the refresh-replay path.  ``OtpSender`` is the port
that decouples sub-facades from the SMS adapter - the coordinator wires the
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
from modules.iam.domain.otp import OTP_TTL_SECONDS, RESEND_COOLDOWN_SECONDS, generate_otp, hash_otp
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
