"""Shared internal helpers for the partner module.

Consolidates repeated profile-loading and registration race-retry patterns
that were previously duplicated across the facade methods. These functions
are internal to the partner module and not part of the public facade surface.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from bus.outbox_writer import write_outbox
from modules.partner.domain.events import (
    PartnerType,
    partner_registered_envelope,
)
from modules.partner.domain.exceptions import (
    PartnerNotFoundError,
    ServiceAreaNotFoundError,
)
from modules.partner.domain.state_machine import (
    REGISTERED,
    PartnerAction,
    PartnerState,
    PartnerStatus,
    transition,
)
from modules.partner.outbox import PARTNER_OUTBOX_TABLE
from modules.partner.schema.models import (
    partner_profiles,
    partner_service_areas,
    partner_verifications,
)

PARTNER_SCHEMA = "partner"

# The Phase-5 launch service area (REQ-008): a partner that does not declare a
# ``service_area_id`` defaults to this vocabulary row (seeded by migration
# v5.4). An unknown explicitly-declared ``service_area_id`` is rejected at the
# facade (mapped to a 422) so a partner is never attached to a nonexistent area.
DEFAULT_SERVICE_AREA_NAME = "Daltonganj"


@dataclass(frozen=True)
class Profile:
    """One ``partner_profiles`` row, converted off the driver."""

    partner_id: int
    identity_id: int
    partner_type: str
    status: str
    round: int
    # Rejected-partner recovery state (PHASE-5 T09, #253): the one-time appeal
    # flag and the re-submission throttle budget carried by the profile.
    appeal_used: bool = False
    re_submission_count: int = 0
    re_submission_blocked_until: datetime | None = None
    # Registration time (P2/P3 #271): surfaced on the partner self-service
    # status view (US-6), read from the profile row's ``created_at``.
    created_at: datetime | None = None

    @property
    def state(self) -> PartnerState:
        return PartnerState(status=PartnerStatus(self.status), round=self.round)


def default_clock() -> datetime:
    """The wall-clock the lifecycle uses for scheduling windows (US-27, #263).

    A plain UTC now, overridable for tests (the ``MutableClock`` pattern the
    integration suite uses to walk the 30-day cleanup window).
    """
    return datetime.now(UTC)


async def apply_transition(
    connection: AsyncConnection,
    profile: Profile,
    action: PartnerAction,
    verification: bool,
) -> PartnerState:
    """Decide with the pure machine and persist the status flip (shared operator gate).

    Persists the state-machine decision on the profile row and, when
    ``verification`` is set, opens a ``[queued]`` row on the current round of
    ``partner_verifications`` so the operator gate can see the new round. Shared
    by the coordinator's credential-intake methods (``submit_credentials``,
    ``appeal``) and the operator-gate sub-facade (``operator_decision``,
    ``grace_lapse``) - both lifecycle seams flip statuses the same way
    (ADR-0002 §1: the write rides the caller's transaction).
    """
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


_PROFILE_COLUMNS = (
    partner_profiles.c.id,
    partner_profiles.c.identity_id,
    partner_profiles.c.partner_type,
    partner_profiles.c.status,
    partner_profiles.c.appeal_used,
    partner_profiles.c.re_submission_count,
    partner_profiles.c.re_submission_blocked_until,
    partner_profiles.c.created_at,
)


def _to_profile(row: Any, current_round: int) -> Profile:
    """Convert a SQLAlchemy row to a Profile dataclass."""
    return Profile(
        partner_id=int(row.id),
        identity_id=int(row.identity_id),
        partner_type=str(row.partner_type),
        status=str(row.status),
        round=current_round,
        appeal_used=bool(getattr(row, "appeal_used", False)),
        re_submission_count=int(getattr(row, "re_submission_count", 0)),
        re_submission_blocked_until=getattr(row, "re_submission_blocked_until", None),
        created_at=getattr(row, "created_at", None),
    )


async def load_profile(connection: AsyncConnection, partner_id: int) -> Profile:
    """Load a partner profile by partner_id, raising PartnerNotFoundError if absent."""
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


async def load_profile_by_identity(connection: AsyncConnection, identity_id: int) -> Profile | None:
    """The profile (with its round) for ``identity_id``, or ``None`` if absent.

    Duplicate-phone resolution (accepted criterion 6): an existing partner
    identity has at most one profile row (``uq_partner_profiles_identity``),
    so this lookup decides between resolving the existing partner and opening
    a new one. Round is computed the same way ``load_profile`` does it so the
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


async def resolve_service_area(connection: AsyncConnection, service_area_id: int | None) -> int:
    """Resolve the ``service_area_id`` a registration persists (PHASE-5 #265).

    When the partner declares no area, the row resolves to the Daltonganj
    default (the seeded Phase-5 launch geography, REQ-008). When an id is
    declared, it is validated against ``partner_service_areas`` first - an
    unknown id raises :class:`ServiceAreaNotFoundError` (mapped to a 422) so a
    partner can never be attached to a nonexistent area. The resolved id is
    what ``insert_registered_profile`` persists.
    """
    if service_area_id is not None:
        found = (
            await connection.execute(
                select(partner_service_areas.c.id).where(
                    partner_service_areas.c.id == service_area_id
                )
            )
        ).scalar_one_or_none()
        if found is None:
            raise ServiceAreaNotFoundError(service_area_id)
        return int(found)
    resolved = await connection.execute(
        select(partner_service_areas.c.id).where(
            partner_service_areas.c.name == DEFAULT_SERVICE_AREA_NAME
        )
    )
    # The Daltonganj default is guaranteed by migration v5.4; a missing row is
    # a deployment error we want to surface, not an ``int(None)``.
    return int(resolved.scalar_one())


async def insert_registered_profile(
    connection: AsyncConnection,
    *,
    identity_id: int,
    partner_type: PartnerType,
    practice_name: str | None = None,
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
            practice_name=practice_name,
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


async def register_profile_race_retry(
    connection: AsyncConnection,
    *,
    identity_id: int,
    partner_type: PartnerType,
    practice_name: str | None = None,
    practice_address: str,
    practice_latitude: float,
    practice_longitude: float,
    service_area_id: int | None,
) -> tuple[Profile, bool]:
    """Insert a profile and handle race condition: returns (profile, created).

    If a concurrent registration opened the profile first, resolve it.
    This collapses the repeated registration race-retry block.
    """
    resolved_area_id = await resolve_service_area(connection, service_area_id)
    partner_id = await insert_registered_profile(
        connection,
        identity_id=identity_id,
        partner_type=partner_type,
        practice_name=practice_name,
        practice_address=practice_address,
        practice_latitude=practice_latitude,
        practice_longitude=practice_longitude,
        service_area_id=resolved_area_id,
    )
    if partner_id is not None:
        # Created new profile
        return (
            Profile(
                partner_id=partner_id,
                identity_id=identity_id,
                partner_type=partner_type,
                status=REGISTERED.status.value,
                round=0,
            ),
            True,
        )
    # A concurrent registration opened the profile first - resolve it.
    existing = await load_profile_by_identity(connection, identity_id)
    if existing is None:  # pragma: no cover - cannot lose a just-inserted row
        raise AssertionError("partner profile vanished between insert and conflict")
    return existing, False
