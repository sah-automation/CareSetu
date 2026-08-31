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
from modules.partner.adapters.artifact_store import CredentialArtifactStore
from modules.partner.domain.credentials import CredentialType
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
from modules.partner.domain.prefilter import evaluate_submission
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
    partner_verifications,
)

PARTNER_SCHEMA = "partner"


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


async def _load_live_credential_types(
    connection: AsyncConnection, partner_id: int
) -> frozenset[str]:
    """The credential types already recorded for a partner (duplicate gate input).

    The Step-1 duplicate check (ADR-0008) rejects a submission re-offering a
    credential type the partner already holds in a live (non-rejected) state; a
    ``Rejected`` partner re-submitting the same type is a new round, not a
    duplicate, so the caller passes an empty set in that case.
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


class PartnerFacade:
    """Typed public facade for the partner lifecycle surface."""

    def __init__(
        self,
        engine: AsyncEngine,
        iam_facade: IamFacade,
        artifact_store: CredentialArtifactStore | None = None,
    ) -> None:
        self._engine = engine
        self._iam = iam_facade
        # Credential documents are encrypted into the ``partner/`` object-storage
        # prefix on a Step-1 pass (ADR-0008, T06). The store must be configured;
        # ``submit_credentials`` refuses to run a passing submission without one
        # rather than silently dropping the documents.
        self._artifact_store = artifact_store

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
        """
        async with self._engine.begin() as connection:
            profile = await _load_profile(connection, partner_id)
            existing_types = await _load_live_credential_types(connection, partner_id)
            outcome = evaluate_submission(
                partner_type=profile.partner_type,
                credential_types=[c.credential_type for c in credentials],
                has_artifacts=any(c.artifacts for c in credentials),
                existing_active_credential_types=(
                    frozenset()
                    if profile.status == PartnerStatus.REJECTED.value
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
