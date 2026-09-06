"""MOD-002 partner operator-gate lifecycle: operator-gate sub-facade (WI-2 p2a, #334).

Following the ADR-0006 IAM precedent, the coordinator ``PartnerFacade``
(:mod:`modules.partner.facade`) delegates the operator-gate lifecycle to this
sub-facade while exposing its unchanged public interface. A developer changing
operator behavior reads only this file - no registration, credential-intake, or
directory concerns.

The sub-facade owns the manual activation gate:

- ``operator_decision`` is the Step-2 manual gate: the operator decision
  (approve/reject) recorded on the current round's ``partner_verifications``
  row.
- ``list_verification_queue`` lists the operator's verification queue age-
  prioritised for the activation-cycle KPI.
- ``get_verification_detail`` opens the per-partner review: profile +
  credentials + verification history + audit chain.
- ``grace_lapse`` applies the event-driven 7-day grace-window auto-drop.

When an operator decision rejects an ``[Active]`` partner, the sub-facade routes
the close-out through the credential-validity deep module's single close-out
transition (WI-1, #331) - the deindex + ``credential.invalidated`` + cache-flush
choreography is owned there, never re-implemented here.

It takes the engine, the credential-validity deep module, and the directory-
cache seam in its constructor and owns its result models (``PartnerQueueItem``,
``PartnerQueue``, ``CredentialDetail``, ``VerificationRound``,
``AuditEventDetail``, ``PartnerVerificationDetail``) - the coordinator re-exports
them unchanged.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from bus.outbox_writer import write_outbox
from modules.audit.facade import AuditFacade
from modules.partner.common_models import PartnerView
from modules.partner.credential_validity import CloseOutCredential
from modules.partner.domain.events import (
    credential_reviewed_envelope,
    partner_activated_envelope,
    partner_rejected_envelope,
    verification_started_envelope,
)
from modules.partner.domain.exceptions import (
    IllegalPartnerTransitionError,
    InvalidQueueSortError,
    InvalidQueueStatusError,
    PartnerNotFoundError,
    RejectionReasonRequiredError,
)
from modules.partner.domain.state_machine import (
    PartnerAction,
    PartnerStatus,
)
from modules.partner.operator_gate_models import (
    AuditEventDetail,
    CredentialDetail,
    PartnerQueue,
    PartnerQueueItem,
    PartnerVerificationDetail,
    VerificationRound,
)
from modules.partner.outbox import PARTNER_OUTBOX_TABLE
from modules.partner.schema.models import (
    partner_credentials,
    partner_profiles,
    partner_verifications,
)
from modules.partner.shared import (
    PARTNER_SCHEMA,
    apply_transition,
    default_clock,
)
from modules.partner.shared import (
    load_profile as _load_profile,
)

# The statuses the operator queue may be filtered by (api-standards §4): any
# other value is an explicit error, never a silent empty queue (S15, #268).
_QUEUE_STATUSES: frozenset[str] = frozenset(ps.value for ps in PartnerStatus)

_QUEUE_SORTS: dict[str, Any] = {
    "registration_age": partner_profiles.c.created_at,
    "partner_type": partner_profiles.c.partner_type,
    "status": partner_profiles.c.status,
}


def _row_str(row: Any, name: str) -> str:
    return str(getattr(row, name))


async def _schedule_credential_cleanup(
    connection: AsyncConnection,
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


class OperatorGateFacade:
    """The partner operator verification gate, shortened to one seam (ADR-0006)."""

    def __init__(
        self,
        engine: AsyncEngine,
        credential_validity: Any,
        directory_cache: Any,
        audit_facade: AuditFacade | None = None,
        *,
        credential_cleanup_days: int = 30,
        clock: Callable[[], datetime] = default_clock,
    ) -> None:
        self._engine = engine
        # The credential-validity deep module (WI-1, #331): the coordinator owns
        # the shared instance and hands it to every sub-facade as a seam. The
        # reject-of-an-``[Active]``-partner close-out routes through this
        # module's SINGLE close-out transition - never local choreography.
        self._credential_validity = credential_validity
        # The directory-cache seam (PHASE-6 T02b, #314): the coordinator exposes
        # it once so sub-facades share the same cache without re-importing.
        # Operator approval changes directory visibility, so the approve path
        # flushes the namespace through this seam (best-effort).
        self._directory_cache = directory_cache
        # The audit ledger read seam (S7): the queue/detail views ask MOD-011's
        # facade for audit links and the partner's chain, never duplicating its
        # int->UUID derivation. Optional for testability - views without an
        # audit facade surface no audit chain/links.
        self._audit_facade = audit_facade
        # Credential-document cleanup window after permanent rejection (US-27,
        # ticket #263): the rejection path schedules ``cleanup_due_at`` this many
        # days out. Config-injected from the resolved Settings (app/main.py),
        # the same discipline as the coordinator's throttle knobs.
        self._credential_cleanup_days = credential_cleanup_days
        # The injectable clock that schedules the cleanup window (overridden by
        # ``MutableClock`` in tests to walk the boundary). Mirrors the iam
        # facades' ``clock`` convention.
        self._clock = clock

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
            next_state = await apply_transition(connection, profile, action, verification=False)
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
                # PHASE-6 T02b (#314): activation changes which partners a
                # directory search can return, so every cached search result is
                # now potentially stale. Flush the namespace (best-effort Redis
                # op - failure silently degrades to the lazy-correct read path).
                await self._directory_cache.directory_visibility_changed()
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
                # current round. The close-out routes through the credential-
                # validity deep module's single transition (deindex + event +
                # cache flush) - never local choreography (WI-1, #331).
                if profile.status == PartnerStatus.ACTIVE.value:
                    await self._credential_validity.close_out_credentials(
                        connection,
                        [
                            CloseOutCredential(
                                credential_id=credential_ids[0] if credential_ids else None,
                                partner_id=partner_id,
                                identity_id=profile.identity_id,
                                reason=resolved_reason or "reverification_failed",
                            )
                        ],
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
            next_state = await apply_transition(
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
        :class:`InvalidQueueSortError` and an unknown ``status`` raises
        :class:`InvalidQueueStatusError`.
        """
        sort_column = _QUEUE_SORTS.get(sort_by)
        if sort_column is None:
            raise InvalidQueueSortError(sort_by)
        order: Any = sort_column.asc()

        if status is not None and status not in _QUEUE_STATUSES:
            raise InvalidQueueStatusError(status)

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
        the outbox in the same transaction as the read (ADR-0002 atomic
        outbox). Consumed by the audit module in a later ticket (T13).
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
