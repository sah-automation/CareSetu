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
- ``submit_credentials`` runs the Step-1 credential pre-filter (ADR-0008) and,
  on pass, encrypts the documents into ``partner/``, opens ``partner_credentials``
  rows and a verification round (``verification_started`` - including
  re-verification of an ``Active`` partner, who stays ``Active`` through the 7-day
  grace window) or, on auto-fail, rejects never queued (``partner.rejected`` with
  the specific pre-filter reason).
- ``operator_decision`` is the Step-2 manual gate: explicit operator approval
  reaches ``Active`` (``partner.activated``); operator reject reaches
  ``Rejected`` (``partner.rejected`` with reason + actor). No auto-approve.
- ``grace_lapse`` (T10) applies the event-driven 7-day grace-window lapse that
  drops an ``[Active]`` re-verifying partner to ``[Under Verification]``; the
  opposite (deactivation) is ``operator_decision`` rejecting an ``[Active]``
  partner, which emits ``credential.invalidated`` alongside ``partner.rejected``.
- ``purge_expired_credentials`` (US-27, #263) is the deterministic credential-
  cleanup trigger: it deletes credential rows whose permanent-rejection 30-day
  cleanup window has lapsed (still ``[Rejected]``), removes their artifacts, and
  emits ``credential.invalidated`` per credential - one transaction. It is
  invoked by the Phase-6 periodic job; no background scanner lives here.

Each mutating method writes its envelope into ``partner.partner_outbox`` in the
SAME transaction as the state change (ADR-0002 §1). The operator review /
credential-invalidated / grace-lapse emission paths are later tickets (T08/T10) -
the state transitions and event constants/builders they need already live in
:mod:`modules.partner.domain.state_machine` and
:mod:`modules.partner.domain.events`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from bus.outbox_writer import write_outbox
from modules.audit.facade import AuditFacade
from modules.iam.facade import IamFacade
from modules.partner.adapters.artifact_store import CredentialArtifactStore
from modules.partner.domain.credentials import CredentialType
from modules.partner.domain.events import (
    PartnerType,
    credential_invalidated_envelope,
    credential_reviewed_envelope,
    partner_activated_envelope,
    partner_registered_envelope,
    partner_rejected_envelope,
    verification_started_envelope,
)
from modules.partner.domain.exceptions import (
    AppealAlreadyUsedError,
    IllegalPartnerTransitionError,
    InvalidQueueSortError,
    PartnerNotFoundError,
    PartnerNotRejectedError,
    RejectionReasonRequiredError,
    ReSubmissionThrottledError,
    ServiceAreaNotFoundError,
)
from modules.partner.domain.prefilter import evaluate_submission
from modules.partner.domain.rejection import (
    evaluate_re_submission,
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
    partner_credentials,
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

# The re-submission throttle policy lives in the domain core
# (:mod:`modules.partner.domain.rejection`): a rejected partner may open at most
# ``MAX_RE_SUBMISSIONS`` re-submission rounds before a cooldown protects the
# operator queue (NFR-001 headcount, ADR-0008, PHASE-5 T09). Business rule -
# never enforced via an iam/Redis limiter, which is not this module's seam.


@dataclass(frozen=True)
class _Profile:
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

    @property
    def state(self) -> PartnerState:
        return PartnerState(status=PartnerStatus(self.status), round=self.round)


_PROFILE_COLUMNS = (
    partner_profiles.c.id,
    partner_profiles.c.identity_id,
    partner_profiles.c.partner_type,
    partner_profiles.c.status,
    partner_profiles.c.appeal_used,
    partner_profiles.c.re_submission_count,
    partner_profiles.c.re_submission_blocked_until,
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


class CredentialSubmission(BaseModel):
    """One credential a partner submits for Step-1 review (ADR-0008).

    ``credential_type`` is the closed per-partner-type type (a doctor's medical
    registration, a lab's lab license, a chemist's drug license, or a supporting
    document). ``artifacts`` are the encrypted-document source bytes the facade
    AES-encrypts into the ``partner/`` object-storage prefix; the refs, not the
    bytes, are persisted in ``partner_credentials.artifact_refs``.
    """

    credential_type: CredentialType
    artifacts: list[bytes] = []


class CredentialSubmissionResult(BaseModel):
    """The typed outcome of a credential submission.

    ``status`` is ``Under Verification`` on a Step-1 pass (a round opened,
    ``partner.verification_started``); ``Rejected`` on a Step-1 auto-fail with
    ``reason`` naming the specific pre-filter failure (never queued - ADR-0008).
    ``reason`` is present only on the auto-fail path.
    """

    partner_id: int
    status: str
    round: int
    reason: str | None = None


class RejectionReasonView(BaseModel):
    """The specific failure reason surfaced to a rejected partner (PHASE-5 T09).

    Read back from the latest ``[Rejected]`` round's ``decision_reason`` (the
    operator's reason or the Step-1 pre-filter auto-fail reason recorded by
    T08/T06). Meaningful only for a ``[Rejected]`` partner - the facade raises
    :class:`PartnerNotRejectedError` otherwise so the partner is never asked to
    re-apply against a status they are not in.
    """

    partner_id: int
    rejection_reason: str
    round: int


class PartnerQueueItem(BaseModel):
    """One partner on the operator verification queue (FEAT-015, T08).

    ``created_at`` is the registration time the age-prioritized default sort
    orders by (KPI-004: oldest registrations first so the activation-cycle
    median stays within 48 h). ``round`` is the partner's latest verification
    round (0 = never entered a round).
    """

    partner_id: int
    identity_id: int
    partner_type: str
    status: str
    practice_name: str | None
    practice_address: str
    created_at: datetime
    round: int
    audit_link: str | None = None


class PartnerQueue(BaseModel):
    """The operator's verification queue view."""

    items: list[PartnerQueueItem]


class CredentialDetail(BaseModel):
    """One submitted credential in the operator's per-partner detail view."""

    credential_id: int
    credential_type: str
    verified: bool
    expires_at: datetime | None
    artifact_refs: dict[str, str]


class VerificationRound(BaseModel):
    """One verification round in the operator's history view."""

    round: int
    status: str
    decision: str | None
    decision_reason: str | None
    decision_by: int | None
    decided_at: datetime | None
    created_at: datetime


class AuditEventDetail(BaseModel):
    """One ``audit_events`` row in the partner's verification detail view (S7).

    A typed, read-only projection of a ledger row surfaced alongside the
    profile/credentials/history so the operator can see the partner's full
    audit chain (who-what-when + hash links) while making a decision. This is
    the primary-schema read of the existing audit seam - no new write path.
    """

    id: UUID
    event_type: str
    actor_id: UUID | None
    target_id: UUID | None
    scope: str | None
    metadata: dict[str, object]
    timestamp: datetime
    prev_hash: str
    hash: str


class PartnerVerificationDetail(BaseModel):
    """The full per-partner review: profile + credentials + verification history.

    What the operator sees when they open a queue item (FEAT-015 user story 17)
    to make a defensible approve/reject decision. ``credentials`` are the
    submitted documents (artifact refs, never bytes); ``verification_history``
    is the per-round queue/decision trail; ``audit_events`` is the partner's
    ledger chain (S7 read-only augmentation).
    """

    partner_id: int
    identity_id: int
    partner_type: str
    status: str
    practice_name: str | None
    practice_address: str
    service_area_id: int | None
    created_at: datetime
    credentials: list[CredentialDetail]
    verification_history: list[VerificationRound]
    audit_events: list[AuditEventDetail] = Field(default_factory=list)
    audit_link: str | None = None


_QUEUE_SORTS: dict[str, Any] = {
    "registration_age": partner_profiles.c.created_at,
    "partner_type": partner_profiles.c.partner_type,
    "status": partner_profiles.c.status,
}


def _row_str(row: Any, name: str) -> str:
    return str(getattr(row, name))


def _default_clock() -> datetime:
    """The wall-clock the lifecycle uses for scheduling windows (US-27, #263).

    A plain UTC now, overridable for tests (the ``MutableClock`` pattern the
    integration suite uses to walk the 30-day cleanup window).
    """
    return datetime.now(UTC)


def _to_profile(row: Row[Any], round: int) -> _Profile:
    appeal_used = getattr(row, "appeal_used", False)
    blocked_until = getattr(row, "re_submission_blocked_until", None)
    return _Profile(
        partner_id=int(row.id),
        identity_id=int(row.identity_id),
        partner_type=str(row.partner_type),
        status=str(row.status),
        round=round,
        appeal_used=bool(appeal_used),
        re_submission_count=int(getattr(row, "re_submission_count", 0)),
        re_submission_blocked_until=blocked_until,
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


async def _resolve_service_area(connection: AsyncConnection, service_area_id: int | None) -> int:
    """Resolve the ``service_area_id`` a registration persists (PHASE-5 #265).

    When the partner declares no area, the row resolves to the Daltonganj
    default (the seeded Phase-5 launch geography, REQ-008). When an id is
    declared, it is validated against ``partner_service_areas`` first - an
    unknown id raises :class:`ServiceAreaNotFoundError` (mapped to a 422) so a
    partner can never be attached to a nonexistent area. The resolved id is
    what ``_insert_registered_profile`` persists.
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


async def _load_live_credential_types(
    connection: AsyncConnection, partner_id: int
) -> frozenset[str]:
    """The credential types already recorded for a partner (duplicate gate input).

    The Step-1 duplicate check (ADR-0008) rejects a submission re-offering a
    credential type the partner already holds in a live (non-rejected) state; a
    ``Rejected`` partner re-submitting the same type is a new round, not a
    duplicate, and an ``Active`` partner re-submitting the same type is a
    renewal/re-verification (PHASE-5 T10), so the caller passes an empty set
    in those two cases.
    """
    rows = (
        await connection.execute(
            select(partner_credentials.c.credential_type).where(
                partner_credentials.c.profile_id == partner_id
            )
        )
    ).all()
    return frozenset(str(row.credential_type) for row in rows)


async def _ingest_credentials(
    connection: AsyncConnection,
    partner_id: int,
    credentials: list[CredentialSubmission],
    artifact_store: CredentialArtifactStore,
) -> None:
    """Encrypt documents into ``partner/`` and open ``partner_credentials`` rows.

    Called only on a Step-1 pass with a configured store (the facade refuses to
    run without one - see ``submit_credentials``), inside the submission
    transaction (ADR-0002 §1). Each credential's artifact bytes are AES-encrypted
    by the given store (refs persisted, never plaintext).
    """
    for submission in credentials:
        refs: dict[str, object] = {}
        for artifact_index, data in enumerate(submission.artifacts):
            refs[f"{submission.credential_type.value}_{artifact_index}"] = (
                artifact_store.save_artifact(
                    partner_id,
                    submission.credential_type.value,
                    artifact_index,
                    data,
                )
            )
        await connection.execute(
            partner_credentials.insert().values(
                profile_id=partner_id,
                credential_type=submission.credential_type.value,
                verified=False,
                artifact_refs=refs,
            )
        )


async def _schedule_credential_cleanup(
    connection: AsyncConnection,
    artifact_store: CredentialArtifactStore | None,
    partner_id: int,
    *,
    due_at: datetime,
) -> list[int]:
    """Schedule a permanently-rejected partner's credential rows for cleanup (US-27).

    Sets ``cleanup_due_at`` on every credential the partner submitted this
    round - so the 30-day retention window starts at rejection - and answers
    their ids in ``created_at`` order (the current round's credential on an
    ``[Active]`` deactivation is the first). Runs in the caller's transaction so
    the schedule commits with the state change (ADR-0002 §1). A partner with no
    credential rows (e.g. a Step-1 auto-fail or a rejection before submitting)
    schedules nothing.
    """
    rows = (
        await connection.execute(
            select(
                partner_credentials.c.id,
                partner_credentials.c.artifact_refs,
            )
            .where(
                partner_credentials.c.profile_id == partner_id,
                partner_credentials.c.cleanup_due_at.is_(None),
            )
            .order_by(partner_credentials.c.created_at)
        )
    ).all()
    if not rows:
        return []
    await connection.execute(
        partner_credentials.update()
        .where(
            partner_credentials.c.profile_id == partner_id,
            partner_credentials.c.cleanup_due_at.is_(None),
        )
        .values(
            cleanup_due_at=due_at,
            updated_at=func.now(),
        )
    )
    return [int(row.id) for row in rows]


class PartnerFacade:
    """Typed public facade for the partner lifecycle surface."""

    def __init__(
        self,
        engine: AsyncEngine,
        iam_facade: IamFacade,
        artifact_store: CredentialArtifactStore | None = None,
        audit_facade: AuditFacade | None = None,
        *,
        re_submission_max: int = 3,
        re_submission_cooldown_days: int = 30,
        credential_cleanup_days: int = 30,
        clock: Callable[[], datetime] = _default_clock,
    ) -> None:
        self._engine = engine
        self._iam = iam_facade
        # Credential documents are encrypted into the ``partner/`` object-storage
        # prefix on a Step-1 pass (ADR-0008, T06). The store must be configured;
        # ``submit_credentials`` refuses to run a passing submission without one
        # rather than silently dropping the documents.
        self._artifact_store = artifact_store
        # The audit ledger read seam (S7): the detail view surfaces the partner's
        # audit chain by asking MOD-011's facade for the rows, not by duplicating
        # its int->UUID derivation. Optional for testability - detail views without
        # an audit facade default to an empty ``audit_events`` list.
        self._audit_facade = audit_facade
        # Rejected-partner re-submission throttle (PHASE-5 T09, #253): the queue-
        # protection budget and cooldown come from configuration (coding-standards
        # §9), injected here from the resolved Settings (see app/main.py), never
        # hardcoded in the domain core.
        self._re_submission_max = re_submission_max
        self._re_submission_cooldown_days = re_submission_cooldown_days
        # Credential-document cleanup window after permanent rejection (US-27,
        # ticket #263): the rejection path schedules ``cleanup_due_at`` this many
        # days out, and ``purge_expired_credentials`` deletes the documents after
        # it lapses. Config-injected like the throttle above (spec-pinned at 30).
        self._credential_cleanup_days = credential_cleanup_days
        # The injectable clock that schedules the 30-day window (overridden by
        # ``MutableClock`` in tests to walk the boundary). Mirrors the iam
        # facades' ``clock`` convention.
        self._clock = clock

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

            resolved_area_id = await _resolve_service_area(connection, service_area_id)
            partner_id = await _insert_registered_profile(
                connection,
                identity_id=identity_id,
                partner_type=partner_type,
                practice_address=practice_address,
                practice_latitude=practice_latitude,
                practice_longitude=practice_longitude,
                service_area_id=resolved_area_id,
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
            resolved_area_id = await _resolve_service_area(connection, service_area_id)
            partner_id = await _insert_registered_profile(
                connection,
                identity_id=identity_id,
                partner_type=partner_type,
                practice_address=practice_address,
                practice_latitude=practice_latitude,
                practice_longitude=practice_longitude,
                service_area_id=resolved_area_id,
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

    async def resolve_partner(self, identity_id: int) -> PartnerView:
        """Resolve the partner profile for an iam identity (credential route).

        The self-service credential route is partner-scoped: the gateway hands
        the authenticated partner principal carrying ``identity_id``, and this
        seam resolves it to the partner profile id so the caller can only submit
        against their own identity (no cross-partner submission/idor). Raises
        :class:`PartnerNotFoundError` when the identity holds no profile.
        """
        async with self._engine.begin() as connection:
            profile = await _load_profile_by_identity(connection, identity_id)
            if profile is None:
                raise PartnerNotFoundError(identity_id)
            return PartnerView(
                partner_id=profile.partner_id,
                status=profile.status,
                round=profile.round,
            )

    async def _persist_re_submission_throttle(
        self, partner_id: int
    ) -> ReSubmissionThrottledError | None:
        """Persist the cooldown deadline for an exhausted re-submission budget.

        A ``[Rejected]`` partner at the re-submission budget boundary is throttled
        (PHASE-5 T09, ADR-0008): the cooldown deadline is written to the profile in
        its OWN committed transaction so it is durable - the caller then raises the
        returned error. This must not share the caller's (soon-aborting) transaction,
        otherwise the deadline write would roll back with the error.
        """
        async with self._engine.begin() as connection:
            profile = await _load_profile(connection, partner_id)
            if profile.status != PartnerStatus.REJECTED.value:
                return None
            policy = evaluate_re_submission(
                re_submission_count=profile.re_submission_count,
                re_submission_blocked_until=profile.re_submission_blocked_until,
                now=datetime.now(UTC),
                max_re_submissions=self._re_submission_max,
                cooldown=timedelta(days=self._re_submission_cooldown_days),
            )
            if policy.allowed:
                return None
            if policy.blocked_until is None:
                raise AssertionError(
                    "blocked re-submission policy did not carry a cooldown deadline"
                )
            await connection.execute(
                partner_profiles.update()
                .where(partner_profiles.c.id == partner_id)
                .values(
                    re_submission_blocked_until=policy.blocked_until,
                    updated_at=func.now(),
                )
            )
            return ReSubmissionThrottledError(partner_id, retry_at=policy.blocked_until.isoformat())

    async def submit_credentials(
        self,
        partner_id: int,
        *,
        credentials: list[CredentialSubmission],
    ) -> CredentialSubmissionResult:
        """Submit professional credentials and run the Step-1 pre-filter (ADR-0008).

        The first half of the two-step gate, fully automatic and synchronous on
        submission. The pre-filter (:func:`modules.partner.domain.prefilter`)
        validates format (a known credential type appropriate for this partner
        type, with documents uploaded) and duplicates (a like credential type is
        not already live):

        - On a **pass**: the documents are AES-encrypted into the ``partner/``
          object-storage prefix (refs stored, never bytes), ``partner_credentials``
          rows open, and the partner enters ``Under Verification`` with a new
          round emitted as ``partner.verification_started``. This is NOT approval
          - the submission then waits for the Step-2 operator gate.
        - On an **auto-fail**: the partner returns to ``Rejected`` (never queued)
          and ``partner.rejected`` fires with the specific pre-filter reason
          (``invalid_credential_type`` / ``missing_artifacts`` / ``duplicate_credential``).

        A previously-``Rejected`` partner re-submitting is a NEW round, not a
        duplicate; an ``Under Verification``/``Active`` partner re-submitting
        opens the next round (re-verification) with the round incremented.

        A ``[Rejected]`` partner's re-submission is throttled (PHASE-5 T09,
        ADR-0008): they may open at most ``MAX_RE_SUBMISSIONS`` re-submission
        rounds before a cooldown, protecting the operator queue (NFR-001). Once
        the budget is exhausted the next re-submission raises
        :class:`ReSubmissionThrottledError` (with the cooldown's ``retry_at``).
        The first submission from a fresh ``[Registered]`` profile is not a
        re-submission and does not count against the budget.
        """
        throttle_error = await self._persist_re_submission_throttle(partner_id)
        if throttle_error is not None:
            raise throttle_error

        async with self._engine.begin() as connection:
            profile = await _load_profile(connection, partner_id)

            is_re_submission = profile.status == PartnerStatus.REJECTED.value

            existing_types = await _load_live_credential_types(connection, partner_id)
            outcome = evaluate_submission(
                partner_type=profile.partner_type,
                credential_types=[c.credential_type for c in credentials],
                has_artifacts=any(c.artifacts for c in credentials),
                existing_active_credential_types=(
                    frozenset()
                    if profile.status in (PartnerStatus.REJECTED.value, PartnerStatus.ACTIVE.value)
                    else existing_types
                ),
            )

            if not outcome.passed:
                if outcome.reason is None:
                    raise AssertionError("pre-filter failure did not carry a reason")
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
                        reason=outcome.reason.value,
                        round=next_state.round,
                        decision_by=None,
                    ),
                )
                return CredentialSubmissionResult(
                    partner_id=partner_id,
                    status=next_state.status.value,
                    round=next_state.round,
                    reason=outcome.reason.value,
                )

            if self._artifact_store is None:
                # The Step-1 gate passed, so documents were submitted, yet no
                # store is wired. Silently ingesting the credential with empty
                # artifact references would queue the operator with nothing to
                # review - fail loud rather than swallow the documents
                # (coding-standards §8 "no silent swallowing").
                raise RuntimeError("credential submission requires a configured artifact store")

            await _ingest_credentials(
                connection,
                partner_id,
                credentials,
                self._artifact_store,
            )
            next_state = await _apply_transition(
                connection, profile, PartnerAction.START_VERIFICATION, verification=True
            )
            if is_re_submission:
                # A rejected partner's accepted re-submission opens a fresh round
                # and advances the throttle budget. A lapsed cooldown (a
                # previously-persisted ``blocked_until`` that has now passed)
                # refreshes the budget, so the new window starts at 1; otherwise
                # the counter simply advances.
                new_count = (
                    1
                    if profile.re_submission_blocked_until is not None
                    else profile.re_submission_count + 1
                )
                await connection.execute(
                    partner_profiles.update()
                    .where(partner_profiles.c.id == partner_id)
                    .values(
                        re_submission_count=new_count,
                        re_submission_blocked_until=None,
                        updated_at=func.now(),
                    )
                )
            await write_outbox(
                connection,
                PARTNER_SCHEMA,
                PARTNER_OUTBOX_TABLE,
                verification_started_envelope(partner_id, next_state.round),
            )
            return CredentialSubmissionResult(
                partner_id=partner_id,
                status=next_state.status.value,
                round=next_state.round,
            )

    async def get_rejection_reason(self, partner_id: int) -> RejectionReasonView:
        """Read the specific failure reason back to a ``[Rejected]`` partner (PHASE-5 T09).

        The partner learns WHY their application failed so they can re-apply with
        corrected credentials (ADR-0008 recovery). The reason is the latest
        ``[Rejected]`` round's ``decision_reason`` - the operator's reason or the
        Step-1 pre-filter auto-fail reason recorded by T08/T06. Raises
        :class:`PartnerNotRejectedError` when the partner is not currently
        ``[Rejected]``: the reason is only meaningful (and only revealed) for a
        rejected partner.
        """
        async with self._engine.begin() as connection:
            profile = await _load_profile(connection, partner_id)
            if profile.status != PartnerStatus.REJECTED.value:
                raise PartnerNotRejectedError(partner_id, profile.status)
            row = (
                await connection.execute(
                    select(
                        partner_verifications.c.round,
                        partner_verifications.c.decision_reason,
                    )
                    .where(
                        partner_verifications.c.profile_id == partner_id,
                        partner_verifications.c.decision == "rejected",
                    )
                    .order_by(partner_verifications.c.round.desc())
                    .limit(1)
                )
            ).first()
            reason = str(row.decision_reason) if row is not None and row.decision_reason else None
            rejected_round = int(row.round) if row is not None else 0
            if reason is None:
                raise PartnerNotRejectedError(partner_id, profile.status)
            return RejectionReasonView(
                partner_id=partner_id,
                rejection_reason=reason,
                round=rejected_round,
            )

    async def appeal(self, partner_id: int) -> PartnerView:
        """File the one-time rejection appeal, re-entering the operator queue (PHASE-5 T09).

        A ``[Rejected]`` partner may contest an operator decision once: the appeal
        re-enters Step 2 (opens a fresh verification round and emits
        ``partner.verification_started``) and consumes the one-time ``appeal_used``
        flag - a second appeal is rejected with :class:`AppealAlreadyUsedError`.
        The appeal DOES NOT advance the re-submission throttle budget; it is a
        distinct recovery path from re-submitting corrected credentials. Raising
        :class:`PartnerNotRejectedError` keeps the action legal only for a
        ``[Rejected]`` partner.
        """
        async with self._engine.begin() as connection:
            profile = await _load_profile(connection, partner_id)
            if profile.status != PartnerStatus.REJECTED.value:
                raise PartnerNotRejectedError(partner_id, profile.status)
            if profile.appeal_used:
                raise AppealAlreadyUsedError()
            next_state = await _apply_transition(
                connection, profile, PartnerAction.START_VERIFICATION, verification=True
            )
            await connection.execute(
                partner_profiles.update()
                .where(partner_profiles.c.id == partner_id)
                .values(appeal_used=True, updated_at=func.now())
            )
            await write_outbox(
                connection,
                PARTNER_SCHEMA,
                PARTNER_OUTBOX_TABLE,
                verification_started_envelope(partner_id, next_state.round),
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
        REQUIRES a reason (raises :class:`RejectionReasonRequiredError` when
        blank); it is carried into the ``partner.rejected`` payload. The
        decision is recorded on the current round's ``partner_verifications``
        row - status/decision flipped to ``approved`` or ``rejected`` with the
        actor and ``decided_at`` - so the per-partner detail's verification
        history and the rejection reason are queryable, then the terminal event
        is emitted in the same transaction (ADR-0002 §1). Every decision is a
        single, individually attributed action - there is no bulk path.
        """
        if not approve and (reason is None or not reason.strip()):
            raise RejectionReasonRequiredError()
        async with self._engine.begin() as connection:
            profile = await _load_profile(connection, partner_id)
            action = PartnerAction.OPERATOR_APPROVE if approve else PartnerAction.OPERATOR_REJECT
            next_state = await _apply_transition(connection, profile, action, verification=False)
            decision = "approved" if approve else "rejected"
            resolved_reason = None if approve else (reason or "rejected by operator")
            await connection.execute(
                partner_verifications.update()
                .where(
                    partner_verifications.c.profile_id == partner_id,
                    partner_verifications.c.round == next_state.round,
                )
                .values(
                    status=decision,
                    decision=decision,
                    decision_reason=resolved_reason,
                    decision_by=decision_by,
                    decided_at=func.now(),
                )
            )
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
                        reason=resolved_reason or "rejected by operator",
                        round=next_state.round,
                        decision_by=decision_by,
                    ),
                )
                # Permanent-rejection cleanup (US-27, ticket #263): rejecting a
                # partner that held credentials schedules their documents for
                # deletion after the 30-day retention window. ``cleanup_due_at``
                # is written on the credential rows now (same transaction), and a
                # Phase-6 ``purge_expired_credentials`` seam deletes them once the
                # deadline lapses - no background scanner lives here (the
                # "deliberately no scanner" doctrine). The window still runs when
                # the partner had been ``[Active]`` (a deactivation) or was merely
                # ``[Under Verification]`` (a first-time rejection); a partner
                # rejected before submitting holds no rows to schedule.
                credential_ids = await _schedule_credential_cleanup(
                    connection,
                    self._artifact_store,
                    partner_id,
                    due_at=self._clock() + timedelta(days=self._credential_cleanup_days),
                )
                # A re-verification failure on an ACTIVE partner is a clean
                # deactivation (spec phase-5 "Deactivation on failed
                # re-verification", ticket #254): besides ``partner.rejected``
                # (role deny via the T03 chain) the credential is invalidated so
                # the partner is deindexed from any directory AND the iam role
                # denied again through ``credential.invalidated`` (MOD-001
                # consumer suspends the grant). The mere grace-window lapse to
                # ``[Under Verification]`` is NOT a deactivation and emits this
                # only via the operator reject on an Active partner. The envelope
                # carries the round's real ``credential_id`` (not ``None``) so the
                # audit/iam consumers can act on the specific credential - the
                # ``Active`` rejection always has the live credentials of the
                # current round.
                if profile.status == PartnerStatus.ACTIVE.value:
                    first_credential_id = credential_ids[0] if credential_ids else None
                    await write_outbox(
                        connection,
                        PARTNER_SCHEMA,
                        PARTNER_OUTBOX_TABLE,
                        credential_invalidated_envelope(
                            partner_id,
                            identity_id=profile.identity_id,
                            credential_id=first_credential_id,
                            reason=resolved_reason or "reverification_failed",
                        ),
                    )
            return PartnerView(
                partner_id=partner_id,
                status=next_state.status.value,
                round=next_state.round,
            )

    async def grace_lapse(self, partner_id: int) -> PartnerView:
        """Auto-drop an ``[Active]`` partner to ``[Under Verification]`` on grace-window lapse.

        PHASE-5 T10 (ticket #254), the event-driven reverify-grace path: an
        ``[Active]`` partner who re-submitted credentials (a re-verification
        round opened, ``partner.verification_started``) stays ``[Active]``
        through the 7-day grace window. When that deadline lapses without an
        operator decision, THIS seam applies the ``GRACE_LAPSE`` transition -
        the partner drops to ``[Under Verification]`` (round unchanged) and is
        queued for the operator gate again, but is NOT deactivated: no
        ``credential.invalidated`` fires, because the mere lapse is not a
        rejection (brief handoff #254). A deactivation only happens on an
        explicit operator reject of the re-verification (see
        ``operator_decision``), which emits ``credential.invalidated``.

        There is deliberately NO background scanner here - the caller (the
        reverify flow's deadline check, Phase 6) invokes this when the window is
        known to have lapsed; automated expiry-scanning is out of Phase-5 scope.

        Two preconditions gate the lapse (both raise
        :class:`IllegalPartnerTransitionError`, mapped to a 422): the partner
        must be ``[Active]`` (the state machine edge) AND the current round must
        be an open, undecided reverification round - that is the ``[Active]``
        partner has re-submitted (``partner.verification_started`` queued them)
        and the operator has not yet decided. A freshly-approved round-1
        ``[Active]`` partner has an already-decided round and is NOT lapse-able:
        AC2 ("window lapses without a decision") only covers a round that is
        still undecided.
        """
        async with self._engine.begin() as connection:
            profile = await _load_profile(connection, partner_id)
            latest = (
                await connection.execute(
                    select(partner_verifications.c.status).where(
                        partner_verifications.c.profile_id == partner_id,
                        partner_verifications.c.round == profile.round,
                    )
                )
            ).first()
            if latest is None or str(latest.status) != "queued":
                raise IllegalPartnerTransitionError(
                    "grace_lapse requires an open, undecided reverification round"
                )
            next_state = await _apply_transition(
                connection, profile, PartnerAction.GRACE_LAPSE, verification=False
            )
            # The lapse drops ``[Active]`` back to ``[Under Verification]`` and
            # re-queues the still-open round for the operator gate, so the same
            # state change writes its event to the outbox in the same transaction
            # as every other transition (coding-standards §4). ``partner.verification_started``
            # (round unchanged) is what re-queues downstream consumers.
            await write_outbox(
                connection,
                PARTNER_SCHEMA,
                PARTNER_OUTBOX_TABLE,
                verification_started_envelope(partner_id, next_state.round),
            )
            return PartnerView(
                partner_id=partner_id,
                status=next_state.status.value,
                round=next_state.round,
            )

    async def list_verification_queue(
        self,
        *,
        partner_type: str | None = None,
        status: str | None = "Under Verification",
        sort_by: str = "registration_age",
    ) -> PartnerQueue:
        """The operator verification queue (FEAT-015, user story 16).

        Lists partner profiles with their latest verification round, defaulting
        to the ``[Under Verification]`` queue the operator gates (Step 2,
        ADR-0008). ``status`` filters on the profile lifecycle status - the
        default ``Under Verification`` shows the active queue; a broader value
        (``Active``/``Rejected``) drives the activation-cycle KPI view. Sortable
        by registration age (default, ``created_at`` ascending so the oldest /
        longest-waiting registrations surface first for the <= 48 h median,
        KPI-004), partner type, or status. An unknown ``sort_by`` raises
        :class:`InvalidQueueSortError`.
        """
        sort_column = _QUEUE_SORTS.get(sort_by)
        if sort_column is None:
            raise InvalidQueueSortError(sort_by)
        order: Any = sort_column.asc()

        async with self._engine.begin() as connection:
            stmt = (
                select(
                    partner_profiles.c.id,
                    partner_profiles.c.identity_id,
                    partner_profiles.c.partner_type,
                    partner_profiles.c.status,
                    partner_profiles.c.practice_name,
                    partner_profiles.c.practice_address,
                    partner_profiles.c.created_at,
                    func.coalesce(func.max(partner_verifications.c.round), 0).label("round"),
                )
                .outerjoin(
                    partner_verifications,
                    partner_verifications.c.profile_id == partner_profiles.c.id,
                )
                .group_by(partner_profiles.c.id)
                .order_by(order)
            )
            if status is not None:
                stmt = stmt.where(partner_profiles.c.status == status)
            if partner_type is not None:
                stmt = stmt.where(partner_profiles.c.partner_type == partner_type)
            rows = (await connection.execute(stmt)).all()

            audit_links: dict[int, str] = {}
            if self._audit_facade is not None and rows:
                audit_links = self._audit_facade.get_partner_audit_links(
                    [int(row.id) for row in rows]
                )

            return PartnerQueue(
                items=[
                    PartnerQueueItem(
                        partner_id=int(row.id),
                        identity_id=int(row.identity_id),
                        partner_type=_row_str(row, "partner_type"),
                        status=_row_str(row, "status"),
                        practice_name=(
                            str(row.practice_name) if row.practice_name is not None else None
                        ),
                        practice_address=str(row.practice_address),
                        created_at=row.created_at,
                        round=int(row.round),
                        audit_link=audit_links.get(int(row.id)),
                    )
                    for row in rows
                ]
            )

    async def get_verification_detail(
        self, partner_id: int, actor_id: int
    ) -> PartnerVerificationDetail:
        """Open a queue item: the full per-partner review (FEAT-015, story 17).

        Returns the profile, all submitted credentials, and the verification
        history so the operator can make a defensible decision. Emits
        ``partner.credential_reviewed`` (with ``actor_id``) for this view - the
        "who saw this document" trail (spec: operator audit depth) - written to
        the outbox in its own transaction after the read. Consumed by the audit
        module in a later ticket (T13); the event is emitted here.
        """
        async with self._engine.begin() as connection:
            row = (
                await connection.execute(
                    select(
                        partner_profiles.c.id,
                        partner_profiles.c.identity_id,
                        partner_profiles.c.partner_type,
                        partner_profiles.c.status,
                        partner_profiles.c.practice_name,
                        partner_profiles.c.practice_address,
                        partner_profiles.c.service_area_id,
                        partner_profiles.c.created_at,
                    ).where(partner_profiles.c.id == partner_id)
                )
            ).first()
            if row is None:
                raise PartnerNotFoundError(partner_id)

            credential_rows = (
                await connection.execute(
                    select(
                        partner_credentials.c.id,
                        partner_credentials.c.credential_type,
                        partner_credentials.c.verified,
                        partner_credentials.c.expires_at,
                        partner_credentials.c.artifact_refs,
                    ).where(partner_credentials.c.profile_id == partner_id)
                )
            ).all()

            history_rows = (
                await connection.execute(
                    select(
                        partner_verifications.c.round,
                        partner_verifications.c.status,
                        partner_verifications.c.decision,
                        partner_verifications.c.decision_reason,
                        partner_verifications.c.decision_by,
                        partner_verifications.c.decided_at,
                        partner_verifications.c.created_at,
                    )
                    .where(partner_verifications.c.profile_id == partner_id)
                    .order_by(partner_verifications.c.round)
                )
            ).all()

        async with self._engine.begin() as connection:
            await write_outbox(
                connection,
                PARTNER_SCHEMA,
                PARTNER_OUTBOX_TABLE,
                credential_reviewed_envelope(partner_id, actor_id),
            )

        audit_page = None
        audit_link: str | None = None
        if self._audit_facade is not None:
            audit_page = await self._audit_facade.query_partner_audit(partner_id)
            audit_link = self._audit_facade.get_partner_audit_link(partner_id)

        return PartnerVerificationDetail(
            partner_id=int(row.id),
            identity_id=int(row.identity_id),
            partner_type=_row_str(row, "partner_type"),
            status=_row_str(row, "status"),
            practice_name=str(row.practice_name) if row.practice_name is not None else None,
            practice_address=str(row.practice_address),
            service_area_id=int(row.service_area_id) if row.service_area_id is not None else None,
            created_at=row.created_at,
            credentials=[
                CredentialDetail(
                    credential_id=int(c.id),
                    credential_type=str(c.credential_type),
                    verified=bool(c.verified),
                    expires_at=c.expires_at,
                    artifact_refs=dict(c.artifact_refs or {}),
                )
                for c in credential_rows
            ],
            verification_history=[
                VerificationRound(
                    round=int(h.round),
                    status=str(h.status),
                    decision=str(h.decision) if h.decision is not None else None,
                    decision_reason=(
                        str(h.decision_reason) if h.decision_reason is not None else None
                    ),
                    decision_by=int(h.decision_by) if h.decision_by is not None else None,
                    decided_at=h.decided_at,
                    created_at=h.created_at,
                )
                for h in history_rows
            ],
            audit_events=[
                AuditEventDetail(
                    id=e.id,
                    event_type=e.event_type,
                    actor_id=e.actor_id,
                    target_id=e.target_id,
                    scope=e.scope,
                    metadata=e.metadata,
                    timestamp=e.timestamp,
                    prev_hash=e.prev_hash,
                    hash=e.hash,
                )
                for e in (audit_page.events if audit_page is not None else [])
            ],
            audit_link=audit_link,
        )

    async def purge_expired_credentials(self) -> list[int]:
        """Delete credentials past the 30-day cleanup window of a permanent rejection (US-27).

        The event-driven cleanup seam (ticket #263): finds every
        ``partner_credentials`` row whose ``cleanup_due_at`` has lapsed and whose
        partner profile is still ``[Rejected]`` - i.e. the permanent-rejection
        retention window has passed and the partner has not recovered to a live
        status. For each it deletes the row, removes the underlying encrypted
        artifact files via the artifact store, and emits ``credential.invalidated``
        (with the real ``credential_id``) - ALL in one DB transaction (ADR-0002 §1),
        so a crash cannot leave an event without its row deletion or vice versa.

        A partner who was rejected but later recovered (re-submit / appeal, so the
        profile is no longer ``[Rejected]``) is NOT purged: their documents stay
        until that recovery round's own terminal decision. Inside the 30-day
        window nothing is scheduled-eligible yet, so it is a no-op.

        There is deliberately NO background scanner built here - this seam is
        invoked by the periodic job the roadmap schedules in Phase 6 (the
        "deliberately no scanner" doctrine from ``grace_lapse``); this ticket only
        provides the deterministic, transactional trigger.

        Returns the ids of the credentials deleted.
        """
        now = self._clock()
        async with self._engine.begin() as connection:
            rows = (
                await connection.execute(
                    select(
                        partner_credentials.c.id,
                        partner_credentials.c.profile_id,
                        partner_profiles.c.identity_id,
                        partner_credentials.c.artifact_refs,
                    )
                    .join(
                        partner_profiles,
                        partner_profiles.c.id == partner_credentials.c.profile_id,
                    )
                    .where(
                        partner_credentials.c.cleanup_due_at.is_not(None),
                        partner_credentials.c.cleanup_due_at <= now,
                        partner_profiles.c.status == PartnerStatus.REJECTED.value,
                    )
                    .order_by(partner_credentials.c.id)
                )
            ).all()
            deleted: list[int] = []
            for row in rows:
                credential_id = int(row.id)
                partner_id = int(row.profile_id)
                identity_id = int(row.identity_id)
                refs = dict(row.artifact_refs or {})
                await connection.execute(
                    partner_credentials.delete().where(partner_credentials.c.id == credential_id)
                )
                if self._artifact_store is not None:
                    self._artifact_store.delete_artifacts(refs)
                await write_outbox(
                    connection,
                    PARTNER_SCHEMA,
                    PARTNER_OUTBOX_TABLE,
                    credential_invalidated_envelope(
                        partner_id,
                        identity_id=identity_id,
                        credential_id=credential_id,
                        reason="permanent_rejection_cleanup",
                    ),
                )
                deleted.append(credential_id)
            return deleted
