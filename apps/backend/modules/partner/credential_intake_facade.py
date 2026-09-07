"""MOD-002 partner credential intake lifecycle: credential-intake sub-facade (WI-2 p2c, #338).

Following the ADR-0006 IAM precedent, the coordinator ``PartnerFacade``
(:mod:`modules.partner.facade`) delegates the two-step credential-intake
lifecycle to this sub-facade while exposing its unchanged public interface. A
developer changing how credentials are submitted or how rejection recovery
works reads only this file - no registration, operator-gate, or directory
concerns.

The sub-facade owns the Step-1 intake gate:

- ``submit_credentials`` runs the Step-1 pre-filter (ADR-0008) and, on pass,
  encrypts the documents into ``partner/``, opens ``partner_credentials`` rows
  and a verification round (``verification_started`` - including re-verification
  of an ``[Active]`` partner) or, on auto-fail, rejects never queued
  (``partner.rejected`` with the specific pre-filter reason).
- ``get_my_verification`` reads the partner's own review status for the current
  round.
- ``get_rejection_reason`` reads the specific failure reason back to a
  ``[Rejected]`` partner so they can re-apply corrected credentials.
- ``appeal`` files the one-time rejection appeal, re-entering the operator
  queue.

It takes the engine, the credential-validity deep module (WI-1, #331), and the
artifact store in its constructor, plus the re-submission throttle config
knobs. The Step-1 auto-reject and the admission gate stay pure-domain in
:mod:`modules.partner.domain.prefilter` and
:mod:`modules.partner.domain.rejection`. It owns its result models
(``CredentialSubmission``, ``CredentialSubmissionResult``,
``RejectionReasonView``, ``PartnerVerificationStatusView``) - the coordinator
re-exports them unchanged.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from bus.outbox_writer import write_outbox
from modules.partner.adapters.artifact_store import CredentialArtifactStore
from modules.partner.credential_intake_models import (
    CredentialSubmission,
    CredentialSubmissionResult,
    PartnerVerificationStatusView,
    RejectionReasonView,
)
from modules.partner.domain.events import (
    partner_rejected_envelope,
    verification_started_envelope,
)
from modules.partner.domain.exceptions import (
    AppealAlreadyUsedError,
    PartnerNotFoundError,
    PartnerNotRejectedError,
    ReSubmissionThrottledError,
)
from modules.partner.domain.prefilter import evaluate_submission
from modules.partner.domain.rejection import evaluate_re_submission
from modules.partner.domain.state_machine import (
    PartnerAction,
    PartnerStatus,
    transition,
)
from modules.partner.outbox import PARTNER_OUTBOX_TABLE
from modules.partner.registration_models import PartnerView
from modules.partner.schema.models import (
    partner_credentials,
    partner_profiles,
    partner_verifications,
)
from modules.partner.shared import (
    PARTNER_SCHEMA,
    CredentialValidityPort,
    default_clock,
)
from modules.partner.shared import (
    apply_transition as _apply_transition,
)
from modules.partner.shared import (
    load_profile as _load_profile,
)
from modules.partner.shared import (
    load_profile_by_identity as _load_profile_by_identity,
)


async def _load_live_credential_types(
    connection: AsyncConnection, partner_id: int, current_round: int
) -> frozenset[str]:
    """Credential types submitted in the current round (duplicate gate input).

    Only credential types from the *current* verification round that are still
    live count as active for the duplicate gate (S13, #266; S14, #267).
    "Live" means ``cleanup_due_at IS NULL`` (not yet purged/rejected).
    Credentials from earlier rounds (including rejected rounds) are excluded
    and a partner who was rejected for type X can re-offer type X in a fresh
    round without tripping the gate.

    The caller still passes ``frozenset()`` for ``Rejected`` / ``Active``
    statuses (renewal / new-round bypass), so this loader is only reached for
    ``Registered`` / ``Under Verification`` profiles.
    """
    rows = (
        await connection.execute(
            select(partner_credentials.c.credential_type).where(
                partner_credentials.c.profile_id == partner_id,
                partner_credentials.c.round == current_round,
                partner_credentials.c.cleanup_due_at.is_(None),
            )
        )
    ).all()
    return frozenset(str(row.credential_type) for row in rows)


async def _ingest_credentials(
    connection: AsyncConnection,
    partner_id: int,
    credentials: list[CredentialSubmission],
    artifact_store: CredentialArtifactStore,
    round_value: int,
) -> None:
    """Encrypt documents into ``partner/`` and open ``partner_credentials`` rows.

    Called only on a Step-1 pass with a configured store (the sub-facade refuses
    to run without one - see ``submit_credentials``), inside the submission
    transaction (ADR-0002 §1). Each credential's artifact bytes are AES-encrypted
    by the given store (refs persisted, never plaintext). ``round_value`` is the
    verification round the submission opens - stamped on every credential so the
    duplicate gate can scope to the current round (S13, #266).
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
                round=round_value,
                verified=False,
                artifact_refs=refs,
            )
        )


class CredentialIntakeFacade:
    """The partner credential-intake (two-step verification) gate (ADR-0006)."""

    def __init__(
        self,
        engine: AsyncEngine,
        credential_validity: CredentialValidityPort,
        artifact_store: CredentialArtifactStore | None = None,
        *,
        re_submission_max: int = 3,
        re_submission_cooldown_days: int = 30,
        clock: Callable[[], datetime] = default_clock,
    ) -> None:
        self._engine = engine
        # The credential-validity deep module (WI-1, #331): the coordinator owns
        # the shared instance and hands it to every sub-facade as a seam. The
        # intake lifecycle defines no eligibility predicate of its own, so it
        # keeps the reference for seam parity without calling into it.
        self._credential_validity = credential_validity
        # Credential documents are encrypted into the ``partner/`` object-storage
        # prefix on a Step-1 pass (ADR-0008, T06). The store must be configured;
        # ``submit_credentials`` refuses to run a passing submission without one
        # rather than silently dropping the documents.
        self._artifact_store = artifact_store
        # Rejected-partner re-submission throttle (PHASE-5 T09, #253): the queue-
        # protection budget and cooldown come from configuration (coding-standards
        # §9), injected here from the resolved Settings (see app/main.py), never
        # hardcoded in the domain core.
        self._re_submission_max = re_submission_max
        self._re_submission_cooldown_days = re_submission_cooldown_days
        # The injectable clock that schedules the cooldown window (overridden by
        # ``MutableClock`` in tests to walk the boundary). Mirrors the iam
        # facades' ``clock`` convention.
        self._clock = clock

    async def get_my_verification(self, identity_id: int) -> PartnerVerificationStatusView:
        """Read the partner's own credential review status (US-7, P3 #271).

        Resolves the caller's identity to their profile, then projects the
        current verification round's review state (``queued``/``in_review`` or,
        once decided, ``approved``/``rejected`` with reason + timestamp). A
        ``[Registered]`` partner with no round answers ``round`` 0 and ``None``
        review fields - a meaningful "not submitted yet" without exposing the
        operator's detail surface. Raises :class:`PartnerNotFoundError` when the
        identity holds no profile.
        """
        async with self._engine.begin() as connection:
            profile = await _load_profile_by_identity(connection, identity_id)
            if profile is None:
                raise PartnerNotFoundError(identity_id)
            if profile.round == 0:
                return PartnerVerificationStatusView(
                    partner_id=profile.partner_id,
                    round=0,
                    status=None,
                    decision=None,
                    decision_reason=None,
                    decided_at=None,
                )
            row = (
                await connection.execute(
                    select(
                        partner_verifications.c.status,
                        partner_verifications.c.decision,
                        partner_verifications.c.decision_reason,
                        partner_verifications.c.decided_at,
                    )
                    .where(partner_verifications.c.profile_id == profile.partner_id)
                    .where(partner_verifications.c.round == profile.round)
                )
            ).first()
            if row is None:  # pragma: no cover - a round implies a verification row
                raise AssertionError("current round has no verification row")
            return PartnerVerificationStatusView(
                partner_id=profile.partner_id,
                round=profile.round,
                status=str(row.status),
                decision=str(row.decision) if row.decision is not None else None,
                decision_reason=str(row.decision_reason)
                if row.decision_reason is not None
                else None,
                decided_at=row.decided_at,
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
                now=self._clock(),
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

            existing_types = await _load_live_credential_types(
                connection, partner_id, profile.round
            )
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

            # The round this submission opens (every START_VERIFICATION edge
            # increments by one - state_machine). Stamped on the credentials so
            # the duplicate gate can scope to the current round (S13, #266).
            next_round = transition(profile.state, PartnerAction.START_VERIFICATION).round

            await _ingest_credentials(
                connection,
                partner_id,
                credentials,
                self._artifact_store,
                round_value=next_round,
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
