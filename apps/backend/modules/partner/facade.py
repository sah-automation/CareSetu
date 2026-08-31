"""MOD-002 Partner lifecycle: typed public sync API (PHASE-5 T04, ticket #247).

The only legal cross-module import target for the ``partner`` module
(coding-standards §2, ADR-0003). This ticket lands the lifecycle engine that
the two-step verification gate (ADR-0008) drives: every decision comes from the
pure :mod:`modules.partner.domain.state_machine`; this layer only persists and
writes the outbox.

Methods:
- ``register`` opens a ``[Registered]`` profile from an open self-service
  registration (FEAT-014, T05): creates the iam credential account
  synchronously (ADR-0010) and emits ``partner.registered``; a duplicate phone
  resolves to the existing profile.
- ``register_partner`` opens a profile in ``Registered``.
- ``submit_credentials`` runs the Step-1 pre-filter and, on pass, opens a
  verification round (``verification_started`` - including re-verification of an
  ``Active`` partner, who stays ``Active`` through the 7-day grace window) or,
  on fail, rejects never queued (``partner.rejected`` with reason ``step1_fail``).
- ``operator_decision`` is the Step-2 manual gate: explicit operator approval
  reaches ``Active`` (``partner.activated``); operator reject reaches
  ``Rejected`` (``partner.rejected`` with reason + actor). No auto-approve.

Each mutating method writes its envelope into ``partner.partner_outbox`` in the
SAME transaction as the state change (ADR-0002 §1). The operator review /
credential-invalidated / grace-lapse emission paths are later tickets (T08/T10) -
the state transitions and event constants/builders they need already live in
:mod:`modules.partner.domain.state_machine` and
:mod:`modules.partner.domain.events`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from bus.outbox_writer import write_outbox
from modules.iam.facade import IamFacade
from modules.partner.domain.events import (
    PartnerType,
    partner_activated_envelope,
    partner_registered_envelope,
    partner_rejected_envelope,
    verification_started_envelope,
)
from modules.partner.domain.exceptions import (
    PartnerNotFoundError,
)
from modules.partner.domain.state_machine import (
    REGISTERED,
    PartnerAction,
    PartnerState,
    PartnerStatus,
    transition,
)
from modules.partner.outbox import PARTNER_OUTBOX_TABLE
from modules.partner.schema.models import partner_profiles, partner_verifications

PARTNER_SCHEMA = "partner"

#: Step-1 pre-filter outcome of a credentials submission.
_STEP1_REASON = "step1_fail"


@dataclass(frozen=True)
class _Profile:
    """One ``partner_profiles`` row, converted off the driver."""

    partner_id: int
    identity_id: int
    partner_type: str
    status: str
    round: int

    @property
    def state(self) -> PartnerState:
        return PartnerState(status=PartnerStatus(self.status), round=self.round)


_PROFILE_COLUMNS = (
    partner_profiles.c.id,
    partner_profiles.c.identity_id,
    partner_profiles.c.partner_type,
    partner_profiles.c.status,
)


class PartnerView(BaseModel):
    """The typed result of a partner lifecycle mutation."""

    partner_id: int
    status: str
    round: int


class RegisterPartnerResult(BaseModel):
    """The outcome of open partner registration (FEAT-014, T05).

    ``partner_id`` and ``status`` name the partner profile - a freshly opened
    ``[Registered]`` profile on first registration, or the pre-existing
    profile on a duplicate phone (accepted criterion 6: duplicate phone
    resolves to the existing identity). ``identity_id`` is the iam gateway
    principal the account was created/resolved for, and ``created`` tells the
    caller whether this call introduced a new profile (``True``) or resolved
    an existing one (``False``).
    """

    partner_id: int
    identity_id: int
    partner_type: str
    status: str
    round: int
    created: bool


def _to_profile(row: Row[Any], round: int) -> _Profile:
    return _Profile(
        partner_id=int(row.id),
        identity_id=int(row.identity_id),
        partner_type=str(row.partner_type),
        status=str(row.status),
        round=round,
    )


async def _load_profile(connection: AsyncConnection, partner_id: int) -> _Profile:
    row = (
        await connection.execute(
            select(*_PROFILE_COLUMNS).where(partner_profiles.c.id == partner_id).with_for_update()
        )
    ).first()
    if row is None:
        raise PartnerNotFoundError(partner_id)
    current_round = int(
        (
            await connection.execute(
                select(func.coalesce(func.max(partner_verifications.c.round), 0)).where(
                    partner_verifications.c.profile_id == partner_id
                )
            )
        ).scalar_one()
    )
    return _to_profile(row, current_round)


async def _load_profile_by_identity(
    connection: AsyncConnection, identity_id: int
) -> _Profile | None:
    """The profile (with its round) for ``identity_id``, or ``None`` if absent.

    Duplicate-phone resolution (accepted criterion 6): an existing partner
    identity has at most one profile row (``uq_partner_profiles_identity``),
    so this lookup decides between resolving the existing partner and opening
    a new one. Round is computed the same way ``_load_profile`` does it so the
    resolved view reports the partner's true verification round.
    """
    row = (
        await connection.execute(
            select(*_PROFILE_COLUMNS).where(partner_profiles.c.identity_id == identity_id)
        )
    ).first()
    if row is None:
        return None
    current_round = int(
        (
            await connection.execute(
                select(func.coalesce(func.max(partner_verifications.c.round), 0)).where(
                    partner_verifications.c.profile_id == row.id
                )
            )
        ).scalar_one()
    )
    return _to_profile(row, current_round)


async def _insert_registered_profile(
    connection: AsyncConnection,
    *,
    identity_id: int,
    partner_type: PartnerType,
    practice_address: str,
    practice_latitude: float,
    practice_longitude: float,
    service_area_id: int | None,
) -> int | None:
    """Insert a ``[Registered]`` profile and emit ``partner.registered`` atomically.

    Shared by ``register`` and ``register_partner`` (ADR-0002 §1: the outbox
    row lands in the same transaction as the state change). Concurrency
    converges on the ``uq_partner_profiles_identity`` unique constraint (the
    single profile a partner identity may hold): ``INSERT ... ON CONFLICT DO
    NOTHING`` - never SELECT-then-INSERT without a fallback, mirroring the iam
    ``create_credential_account`` pattern. Returns the new profile id, or
    ``None`` when a concurrent registration already opened a profile for the
    same identity (the caller re-reads and returns that existing profile).
    """
    result = await connection.execute(
        postgresql_insert(partner_profiles)
        .values(
            identity_id=identity_id,
            partner_type=partner_type,
            status=REGISTERED.status.value,
            practice_address=practice_address,
            practice_latitude=practice_latitude,
            practice_longitude=practice_longitude,
            service_area_id=service_area_id,
        )
        .on_conflict_do_nothing(index_elements=["identity_id"])
        .returning(partner_profiles.c.id)
    )
    partner_id = result.scalar_one_or_none()
    if partner_id is None:
        return None
    await write_outbox(
        connection,
        PARTNER_SCHEMA,
        PARTNER_OUTBOX_TABLE,
        partner_registered_envelope(int(partner_id), identity_id, partner_type),
    )
    return int(partner_id)


async def _apply_transition(
    connection: AsyncConnection,
    profile: _Profile,
    action: PartnerAction,
    verification: bool,
) -> PartnerState:
    """Decide with the pure machine and persist the status flip."""
    next_state = transition(profile.state, action)
    await connection.execute(
        partner_profiles.update()
        .where(partner_profiles.c.id == profile.partner_id)
        .values(status=next_state.status.value, updated_at=func.now())
    )
    if verification:
        await connection.execute(
            partner_verifications.insert().values(
                profile_id=profile.partner_id,
                round=next_state.round,
                status="queued",
            )
        )
    return next_state


class PartnerFacade:
    """Typed public facade for the partner lifecycle surface."""

    def __init__(self, engine: AsyncEngine, iam_facade: IamFacade) -> None:
        self._engine = engine
        self._iam = iam_facade

    async def register(
        self,
        phone: str,
        partner_type: PartnerType,
        practice_address: str,
        practice_latitude: float,
        practice_longitude: float,
        service_area_id: int | None = None,
    ) -> RegisterPartnerResult:
        """Open partner registration (FEAT-014, ADR-0010): open + sync account.

        A doctor/lab/chemist registers openly with their phone and basic
        profile - no invite required. The iam credential account is created
        synchronously first (ADR-0010) so a login-capable identity exists
        before the partner can authenticate, then the ``[Registered]`` profile
        row opens with ``partner.registered`` emitted. Both happen in the SAME
        transaction (the iam seam runs on this method's connection) so the
        identity and profile commit together as one atomic unit (ADR-0010,
        ADR-0002 §1) - no orphan identity if the profile insert fails.

        A phone that already resolves to a partner identity (duplicate
        registration) returns the existing profile unchanged - never a second
        row. Duplicate identities are resolved by the iam seam (``ON CONFLICT``
        on ``phone_e164``) and duplicate profiles by ``on_conflict_do_nothing``
        on ``uq_partner_profiles_identity``, so concurrent registrations of the
        same phone converge instead of raising (accepted criterion 6).
        """
        async with self._engine.begin() as connection:
            account = await self._iam.create_credential_account(phone, connection=connection)
            identity_id = int(account.identity_id)

            existing = await _load_profile_by_identity(connection, identity_id)
            if existing is not None:
                return RegisterPartnerResult(
                    partner_id=existing.partner_id,
                    identity_id=identity_id,
                    partner_type=existing.partner_type,
                    status=existing.status,
                    round=existing.round,
                    created=False,
                )

            partner_id = await _insert_registered_profile(
                connection,
                identity_id=identity_id,
                partner_type=partner_type,
                practice_address=practice_address,
                practice_latitude=practice_latitude,
                practice_longitude=practice_longitude,
                service_area_id=service_area_id,
            )
            if partner_id is None:
                # A concurrent registration opened the profile first - resolve it.
                existing = await _load_profile_by_identity(connection, identity_id)
                if existing is None:  # pragma: no cover - cannot lose a just-inserted row
                    raise AssertionError("partner profile vanished between insert and conflict")
                return RegisterPartnerResult(
                    partner_id=existing.partner_id,
                    identity_id=identity_id,
                    partner_type=existing.partner_type,
                    status=existing.status,
                    round=existing.round,
                    created=False,
                )
            return RegisterPartnerResult(
                partner_id=partner_id,
                identity_id=identity_id,
                partner_type=partner_type,
                status=REGISTERED.status.value,
                round=0,
                created=True,
            )

    async def register_partner(
        self,
        identity_id: int,
        partner_type: PartnerType,
        practice_address: str,
        practice_latitude: float,
        practice_longitude: float,
        service_area_id: int | None = None,
    ) -> PartnerView:
        """Open a new partner profile in ``Registered`` (low-level seam).

        Used by ``register`` and any caller that already holds an identity id;
        inserts the profile row and emits ``partner.registered`` in the same
        transaction (ADR-0002 §1). A profile that already exists for the
        identity (the ``uq_partner_profiles_identity`` arbiter) is resolved and
        returned unchanged - never a second row.
        """
        async with self._engine.begin() as connection:
            partner_id = await _insert_registered_profile(
                connection,
                identity_id=identity_id,
                partner_type=partner_type,
                practice_address=practice_address,
                practice_latitude=practice_latitude,
                practice_longitude=practice_longitude,
                service_area_id=service_area_id,
            )
            if partner_id is not None:
                return PartnerView(
                    partner_id=partner_id,
                    status=REGISTERED.status.value,
                    round=0,
                )
            existing = await _load_profile_by_identity(connection, identity_id)
            if existing is None:  # pragma: no cover - cannot lose a just-inserted row
                raise AssertionError("partner profile vanished between insert and conflict")
            return PartnerView(
                partner_id=existing.partner_id,
                status=existing.status,
                round=existing.round,
            )

    async def submit_credentials(
        self,
        partner_id: int,
        *,
        pass_step1: bool,
        reason: str | None = None,
    ) -> PartnerView:
        """Run the Step-1 pre-filter then open a round or reject (never queued).

        ``pass_step1`` is the format/duplicate validation outcome computed by
        the caller (T08 wires it from the credentials submitted). On a pass the
        partner enters ``Under Verification`` and a new round opens
        (``partner.verification_started``); on a fail the partner is rejected
        with reason ``step1_fail`` and never enters the operator queue.
        """
        async with self._engine.begin() as connection:
            profile = await _load_profile(connection, partner_id)
            if pass_step1:
                next_state = await _apply_transition(
                    connection, profile, PartnerAction.START_VERIFICATION, verification=True
                )
                await write_outbox(
                    connection,
                    PARTNER_SCHEMA,
                    PARTNER_OUTBOX_TABLE,
                    verification_started_envelope(partner_id, next_state.round),
                )
            else:
                next_state = await _apply_transition(
                    connection, profile, PartnerAction.AUTO_FAIL, verification=False
                )
                await write_outbox(
                    connection,
                    PARTNER_SCHEMA,
                    PARTNER_OUTBOX_TABLE,
                    partner_rejected_envelope(
                        partner_id,
                        identity_id=profile.identity_id,
                        reason=reason or _STEP1_REASON,
                        round=next_state.round,
                        decision_by=None,
                    ),
                )
            return PartnerView(
                partner_id=partner_id,
                status=next_state.status.value,
                round=next_state.round,
            )

    async def operator_decision(
        self,
        partner_id: int,
        decision_by: int,
        *,
        approve: bool,
        reason: str | None = None,
    ) -> PartnerView:
        """Step-2 manual gate: explicit operator approval or rejection.

        Approval is the ONLY path to ``Active`` (no auto-approve). Rejection
        requires no reason at this layer but the route surface (T08) enforces a
        required reason; it is carried into the ``partner.rejected`` payload.
        """
        async with self._engine.begin() as connection:
            profile = await _load_profile(connection, partner_id)
            action = PartnerAction.OPERATOR_APPROVE if approve else PartnerAction.OPERATOR_REJECT
            next_state = await _apply_transition(connection, profile, action, verification=False)
            if approve:
                await write_outbox(
                    connection,
                    PARTNER_SCHEMA,
                    PARTNER_OUTBOX_TABLE,
                    partner_activated_envelope(partner_id, profile.identity_id, decision_by),
                )
            else:
                await write_outbox(
                    connection,
                    PARTNER_SCHEMA,
                    PARTNER_OUTBOX_TABLE,
                    partner_rejected_envelope(
                        partner_id,
                        identity_id=profile.identity_id,
                        reason=reason or "rejected by operator",
                        round=next_state.round,
                        decision_by=decision_by,
                    ),
                )
            return PartnerView(
                partner_id=partner_id,
                status=next_state.status.value,
                round=next_state.round,
            )
