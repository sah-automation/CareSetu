"""Shared internal helpers for the partner module.

Consolidates repeated profile-loading and registration race-retry patterns
that were previously duplicated across the facade methods. These functions
are internal to the partner module and not part of the public facade surface.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol

from sqlalchemy import ColumnElement, func, select
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

if TYPE_CHECKING:
    from modules.partner.credential_validity import CloseOutCredential

PARTNER_SCHEMA = "partner"


class CredentialValidityPort(Protocol):
    """Surface the credential-validity deep module exposes to sub-facades.

    Captures the 3 SQL predicates, the single close-out transition, the single
    activate transition and the shared directory-entry refresh so sub-facades
    depend on a typed seam rather than ``Any`` or ``ModuleType``
    (coding-standards S3).

    ``refresh_directory_entry`` sits here rather than in a second one-method
    port, and the reason is worth stating because the fit is imperfect: it is a
    read-side projection write owned by the same module as the predicates that
    read it, and the doctor's own address save (#609) reaches it through this
    seam even though the write is not about credential validity. A second port
    with one method would be a thinner abstraction, not a clearer one - and
    whoever opens this file next is exactly the person who must not read a
    doctor-triggered call as a privilege escalation, so the operation's name and
    this note carry that.
    """

    def provider_visible(self, column: ColumnElement[Any]) -> ColumnElement[bool]: ...
    def has_any_credential(self, column: ColumnElement[Any]) -> ColumnElement[bool]: ...
    def has_invalid_credential(self, column: ColumnElement[Any]) -> ColumnElement[bool]: ...
    async def close_out_credentials(
        self,
        connection: AsyncConnection,
        credentials: list[CloseOutCredential],
    ) -> list[int]: ...
    async def activate_partner(
        self,
        connection: AsyncConnection,
        partner_id: int,
        *,
        round: int,
    ) -> None: ...
    async def refresh_directory_entry(
        self,
        connection: AsyncConnection,
        partner_id: int,
    ) -> None: ...


class DirectoryCachePort(Protocol):
    """Surface the directory-cache seam exposed to sub-facades.

    Captures the 3 async cache methods the directory and operator-gate
    sub-facades call (coding-standards S3).
    """

    async def get_cached_search(
        self,
        *,
        query: str | None,
        partner_type: str | None,
        specialty: str | None,
        latitude: float,
        longitude: float,
        expanded: bool,
    ) -> tuple[list[dict[str, Any]], bool] | None: ...
    async def set_cached_search(
        self,
        *,
        query: str | None,
        partner_type: str | None,
        specialty: str | None,
        latitude: float,
        longitude: float,
        expanded: bool,
        raw_items: list[dict[str, Any]],
        fell_back: bool,
        ttl_seconds: int,
    ) -> None: ...
    async def directory_visibility_changed(self) -> None: ...


# The Phase-5 launch service area (REQ-008): a partner that does not declare a
# ``service_area_id`` defaults to this vocabulary row (seeded by migration
# v5.4). An unknown explicitly-declared ``service_area_id`` is rejected at the
# facade (mapped to a 422) so a partner is never attached to a nonexistent area.
DEFAULT_SERVICE_AREA_NAME = "Daltonganj"


def representative_specialty(raw: object) -> str | None:
    """Project a multi-valued specialty selection onto one representative value.

    The directory entry's ``specialty`` column became a multi-valued selection in
    #606, because a doctor practises more than one kind of care and the overlap
    search (#612) matches on membership. Two projections still declare the field
    as a single nullable string - the directory browse entry and, through it, the
    public provider profile - and each is owned by a later ticket that widens it
    deliberately: #612 decides whether the browse projection widens, #613 owns
    the public one. The private doctor profile view is no longer one of them -
    # #608 sources it from the profile row and returns the whole selection, which
    is :func:`selection_members` below.

    Until then this is the one place those readers agree on what a selection
    projects to: the FIRST member, or ``None`` for an empty selection
    and for a lab or chemist row, whose directory entry carries no specialty at
    all. Order is the selection's own, so the value is the doctor's first
    declared specialty rather than an alphabetical or arbitrary one.

    Defensive by design, because the value arrives off the driver as whatever
    asyncpg decoded: a JSONB array arrives as a list, ``NULL`` as ``None``, and a
    non-array JSONB scalar - which nothing writes, but a hand-repaired row might -
    is not silently rendered as its own text repr. The first member that is a
    non-empty string wins, so a junk member cannot swallow a real one and hide a
    doctor from their own specialty search; a value that is not a list or tuple,
    or a list with no usable member, projects to ``None``, so a malformed row
    reads as "no specialty" rather than leaking a Python ``repr`` into a response
    field.
    """
    members = selection_members(raw)
    return members[0] if members else None


def selection_members(raw: object) -> list[str]:
    """Project a stored multi-valued selection column onto the strings it holds.

    The read-side counterpart of the domain's ``require_*`` walks
    (``domain/vocabularies.py``): a write is checked member by member against a
    closed list, and this is what the reader gets back off the column. The private
    doctor profile view returns the doctor's declared selection rather than one of
    its members, because that is what the row holds and what the doctor just
    wrote - it now serves three such columns, ``specialties``, ``languages`` and
    ``consulting_days``, which is why the name is about the shape rather than the
    one field that landed it (#608, then #610).

    Equally defensive, for the same reason and with the same driver-shaped inputs
    - a JSONB array arrives as a list, ``NULL`` as ``None``, and a hand-repaired
    row could hold a scalar: a non-list reads as the empty selection rather than
    as a Python ``repr``. Non-string and empty-string members are DROPPED rather
    than rendered, because the view is declared ``extra="forbid"`` with a
    ``list[str]`` field and a junk member would otherwise surface as a 500 from
    the response model instead of a readable profile. Order is the stored
    selection's own, so the doctor sees their declared order, which is what the
    overlap search (#612) matches against.
    """
    if isinstance(raw, (str, bytes)) or not isinstance(raw, (list, tuple)):
        return []
    return [member for member in raw if isinstance(member, str) and member]


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
