"""MOD-002 Partner lifecycle: typed public sync API (PHASE-5 T04, ticket #247).

The only legal cross-module import target for the ``partner`` module
(coding-standards §2, ADR-0003). This ticket lands the lifecycle engine that
the two-step verification gate (ADR-0008) drives: every decision comes from the
pure :mod:`modules.partner.domain.state_machine`; this layer only persists and
writes the outbox.

Methods:
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
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from bus.outbox_writer import write_outbox
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

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def register_partner(
        self,
        identity_id: int,
        partner_type: PartnerType,
        practice_address: str,
        practice_latitude: float,
        practice_longitude: float,
        service_area_id: int | None = None,
    ) -> PartnerView:
        """Open a new partner profile in ``Registered``."""
        async with self._engine.begin() as connection:
            result = await connection.execute(
                partner_profiles.insert()
                .values(
                    identity_id=identity_id,
                    partner_type=partner_type,
                    status=REGISTERED.status.value,
                    practice_address=practice_address,
                    practice_latitude=practice_latitude,
                    practice_longitude=practice_longitude,
                    service_area_id=service_area_id,
                )
                .returning(partner_profiles.c.id)
            )
            partner_id = int(result.scalar_one())
            await write_outbox(
                connection,
                PARTNER_SCHEMA,
                PARTNER_OUTBOX_TABLE,
                partner_registered_envelope(partner_id, identity_id, partner_type),
            )
            return PartnerView(partner_id=partner_id, status=REGISTERED.status.value, round=0)

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
