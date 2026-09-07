"""MOD-002 Partner lifecycle: typed public sync API (PHASE-5 T04, ticket #247).

The only legal cross-module import target for the ``partner`` module
(coding-standards §2, ADR-0003). Since the WI-2 deepening pass the facade is a
thin coordinator that delegates to lifecycle sub-facades (ADR-0006, parent
#330): the registration lifecycle (:mod:`modules.partner.registration_facade`,
WI-2 p1a #332), the operator gate (:mod:`modules.partner.operator_gate_facade`,
WI-2 p2a #334), and the patient-facing directory reads
(:mod:`modules.partner.directory_facade`, WI-2 p2b #337). A credential-intake
sub-facade (WI-2 p2c #338) and the close-out family stay on the coordinator
after WI-2. The coordinator re-exports the sub-facades' result models so the
public surface and all routing/cross-module callers stay unchanged.

Methods (delegated to the registration sub-facade - WI-2 p1a #332):
- ``register`` opens a ``[Registered]`` profile from an open self-service
  registration (FEAT-014, T05): creates the iam credential account
  synchronously (ADR-0010) and emits ``partner.registered``; a duplicate phone
  resolves to the existing profile.
- ``register_partner`` opens a profile in ``Registered``.
- ``resolve_partner`` / ``resolve_partner_id_by_identity`` resolve an identity
  to the partner profile (the latter non-throwing, for the session gate).
- ``get_my_status`` reads the partner's own onboarding status.

Methods (delegated to the operator-gate sub-facade - WI-2 p2a #334):
- ``operator_decision`` is the Step-2 manual gate: explicit operator approval
  reaches ``Active`` (``partner.activated``); operator reject reaches
  ``Rejected`` (``partner.rejected`` with reason + actor). No auto-approve.
- ``grace_lapse`` (T10) applies the event-driven 7-day grace-window lapse that
  drops an ``[Active]`` re-verifying partner to ``[Under Verification]``; the
  opposite (deactivation) is ``operator_decision`` rejecting an ``[Active]``
  partner, which routes through the credential-validity deep module's single
  close-out transition (WI-1, #331).
- ``list_verification_queue`` lists the operator's verification queue,
  age-prioritised for the activation-cycle KPI.
- ``get_verification_detail`` opens the per-partner review: profile +
  credentials + verification history + audit chain.

Methods (delegated to the directory sub-facade - WI-2 p2b #337):
- ``search_directory`` is the public directory search (FEAT-004): only
  ``[Active]`` partners with all-verified, unexpired, unrevoked credentials,
  nearest-first, with the wider-area fallback and the ``directory.search``
  analytics event; Redis-accelerated with lazy validity re-derivation
  (PHASE-6 T02b, #314).
- ``get_provider_profile`` is the public provider profile (FEAT-005): the
  verified-safe profile, hidden exactly when search hides the card.
- ``record_partner_selected`` records one ``partner.selected`` analytics pick.

Remaining coordinator methods:
- ``submit_credentials`` runs the Step-1 credential pre-filter (ADR-0008) and,
  on pass, encrypts the documents into ``partner/``, opens ``partner_credentials``
  rows and a verification round (``verification_started`` - including
  re-verification of an ``Active`` partner, who stays ``Active`` through the 7-day
  grace window) or, on auto-fail, rejects never queued (``partner.rejected`` with
  the specific pre-filter reason).
- ``purge_expired_credentials`` (US-27, #263) is the deterministic credential-
  cleanup trigger: it deletes credential rows whose permanent-rejection 30-day
  cleanup window has lapsed (still ``[Rejected]``), removes their artifacts, and
  emits ``credential.invalidated`` per credential - one transaction. It is
  invoked by the Phase-6 periodic job; no background scanner lives here.
- ``invalidate_credential`` (PHASE-6 T04a, #315) is the immediate revocation
  reach: it records the close-out on the partner's live credential rows
  (``revoked_at``/``invalidation_reason``), deindexes the directory entry
  (``is_active = False``), and emits ``credential.invalidated`` - one
  transaction, mirroring ``purge_expired_credentials`` (ADR-0011). No new
  lifecycle state: the partner recovers through a fresh verification round.
- ``close_out_expired_credentials`` (PHASE-6 T04b, #316) is the daily expiry
  close-out pass (ADR-0011's second, non-scanner mechanism): it finds an
  ``[Active]`` partner's verified credentials whose recorded ``expires_at`` has
  passed but have no close-out yet, stamps ``invalidation_reason = 'expired'``
  (the idempotency marker a replay skips), deindexes the directory entry, and
  emits ``credential.invalidated`` (reason ``expired``) once per credential -
  one transaction. Lazy read-hide (``_has_invalid_credential``) is already
  correct without it; this pass only performs the official event/audit
  close-out.

Each mutating method writes its envelope into ``partner.partner_outbox`` in the
SAME transaction as the state change (ADR-0002 §1). The operator review /
credential-invalidated / grace-lapse emission paths are later tickets (T08/T10) -
the state transitions and event constants/builders they need already live in
:mod:`modules.partner.domain.state_machine` and
:mod:`modules.partner.domain.events`.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from bus.outbox_writer import write_outbox
from modules.audit.facade import AuditFacade
from modules.iam.facade import IamFacade
from modules.partner import credential_validity as credential_validity_module
from modules.partner import directory_cache as directory_cache_module
from modules.partner.adapters.artifact_store import CredentialArtifactStore
from modules.partner.common_models import PartnerView as PartnerView
from modules.partner.credential_intake_models import (
    CredentialSubmission as CredentialSubmission,
)
from modules.partner.credential_intake_models import (
    CredentialSubmissionResult as CredentialSubmissionResult,
)
from modules.partner.credential_intake_models import (
    PartnerVerificationStatusView as PartnerVerificationStatusView,
)
from modules.partner.credential_intake_models import (
    RejectionReasonView as RejectionReasonView,
)
from modules.partner.credential_validity import (
    CloseOutCredential,
)
from modules.partner.directory_facade import (
    DALTONGANJ_LATITUDE as DALTONGANJ_LATITUDE,
)
from modules.partner.directory_facade import (
    DALTONGANJ_LONGITUDE as DALTONGANJ_LONGITUDE,
)
from modules.partner.directory_facade import (
    DirectoryEntry as DirectoryEntry,
)
from modules.partner.directory_facade import (
    DirectoryFacade as DirectoryFacade,
)
from modules.partner.directory_facade import (
    DirectorySearchView as DirectorySearchView,
)
from modules.partner.directory_facade import (
    ProviderCredential as ProviderCredential,
)
from modules.partner.directory_facade import (
    ProviderProfileView as ProviderProfileView,
)
from modules.partner.domain.credentials import CredentialInvalidatedReason
from modules.partner.domain.events import (
    PartnerType,
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
from modules.partner.domain.rejection import (
    evaluate_re_submission,
)
from modules.partner.domain.state_machine import (
    PartnerAction,
    PartnerStatus,
    transition,
)
from modules.partner.operator_gate_facade import (
    OperatorGateFacade as OperatorGateFacade,
)
from modules.partner.operator_gate_models import (
    AuditEventDetail as AuditEventDetail,
)
from modules.partner.operator_gate_models import (
    CredentialDetail as CredentialDetail,
)
from modules.partner.operator_gate_models import (
    PartnerQueue as PartnerQueue,
)
from modules.partner.operator_gate_models import (
    PartnerQueueItem as PartnerQueueItem,
)
from modules.partner.operator_gate_models import (
    PartnerVerificationDetail as PartnerVerificationDetail,
)
from modules.partner.operator_gate_models import (
    VerificationRound as VerificationRound,
)
from modules.partner.outbox import PARTNER_OUTBOX_TABLE
from modules.partner.registration_facade import (
    RegistrationFacade as RegistrationFacade,
)
from modules.partner.registration_models import (
    PartnerMeView as PartnerMeView,
)
from modules.partner.registration_models import (
    RegisterPartnerResult as RegisterPartnerResult,
)
from modules.partner.schema.models import (
    partner_credentials,
    partner_profiles,
    partner_verifications,
)
from modules.partner.shared import (
    DEFAULT_SERVICE_AREA_NAME as DEFAULT_SERVICE_AREA_NAME,
)
from modules.partner.shared import (
    PARTNER_SCHEMA as PARTNER_SCHEMA,
)
from modules.partner.shared import (
    Profile as Profile,
)
from modules.partner.shared import (
    apply_transition as _apply_transition,
)
from modules.partner.shared import (
    default_clock as _default_clock,
)
from modules.partner.shared import (
    load_profile as _load_profile,
)
from modules.partner.shared import (
    load_profile_by_identity as _load_profile_by_identity,
)

# The Phase-5 launch service area (REQ-008): a partner that does not declare a
# ``service_area_id`` defaults to this vocabulary row (seeded by migration
# v5.4). An unknown explicitly-declared ``service_area_id`` is rejected at the
# facade (mapped to a 422) so a partner is never attached to a nonexistent area.

# The re-submission throttle policy lives in the domain core
# (:mod:`modules.partner.domain.rejection`): a rejected partner may open at most
# ``MAX_RE_SUBMISSIONS`` re-submission rounds before a cooldown protects the
# operator queue (NFR-001 headcount, ADR-0008, PHASE-5 T09). Business rule -
# never enforced via an iam/Redis limiter, which is not this module's seam.


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

    Called only on a Step-1 pass with a configured store (the facade refuses to
    run without one - see ``submit_credentials``), inside the submission
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


class PartnerFacade:
    """Typed public facade for the partner lifecycle surface."""

    def __init__(
        self,
        engine: AsyncEngine,
        iam_facade: IamFacade | None = None,
        artifact_store: CredentialArtifactStore | None = None,
        audit_facade: AuditFacade | None = None,
        *,
        re_submission_max: int = 3,
        re_submission_cooldown_days: int = 30,
        credential_cleanup_days: int = 30,
        directory_ttl_seconds: int = 0,
        directory_max_results: int = 50,
        clock: Callable[[], datetime] = _default_clock,
    ) -> None:
        self._engine = engine
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
        # Directory-search result cache TTL (PHASE-6 T02b, #314): the accelerator
        # only gates on Redis being available; ``0`` (the boot default when no
        # Settings-level TTL is injected) disables caching entirely so the unit
        # tier and callers that never set it stay SQL-only.
        self._directory_ttl_seconds = directory_ttl_seconds
        # Directory result cap (PHASE-6 T2, #324): the top-N bound applied after
        # distance ordering so a search never returns an unbounded nearest-first
        # list. Config-injected from the resolved Settings (app/main.py), the
        # same discipline as the throttle and TTL knobs above (coding-standards §9).
        self._directory_max_results = directory_max_results
        # The injectable clock that schedules the 30-day window (overridden by
        # ``MutableClock`` in tests to walk the boundary). Mirrors the iam
        # facades' ``clock`` convention.
        self._clock = clock
        # The credential-validity deep module (WI-1, #331): the coordinator
        # owns the shared instance so sub-facades later receive it as a seam,
        # never reconstructing it.
        self._credential_validity = credential_validity_module
        # Registration sub-facade (ADR-0006, WI-2 p1a #332): owns the open /
        # resolve-your-partner lifecycle and the synchronous iam credential
        # account (ADR-0010). The iam seam is OPTIONAL (WI-3, #336): only
        # ``register`` consumes it; facades composed without it (the daily
        # credential-expiry sweep) fail loudly if registration is ever attempted.
        self._registration = RegistrationFacade(engine, credential_validity_module, iam_facade)
        # Directory-cache seam (PHASE-6 T02b, #314): the Redis accelerator
        # functions. The coordinator exposes the seam once so sub-facades
        # share the same cache without re-importing.
        self._directory_cache = directory_cache_module
        # Operator-gate sub-facade (ADR-0006, WI-2 p2a #334): owns the manual
        # activation gate (operator decision, verification queue, per-partner
        # detail, grace-window lapse) and its result models. The coordinator
        # hands it the shared credential-validity deep module (WI-1 #331), the
        # directory-cache seam, and the audit read seam, plus its config knobs.
        self._operator_gate = OperatorGateFacade(
            engine=engine,
            credential_validity=credential_validity_module,
            directory_cache=directory_cache_module,
            audit_facade=audit_facade,
            credential_cleanup_days=credential_cleanup_days,
            clock=clock,
        )
        # Directory sub-facade (ADR-0006, WI-2 p2b #337): owns the patient-
        # facing directory read lifecycle - search, provider profile, partner-
        # selected analytics, and the cached-search accelerator - and its result
        # models. The coordinator hands it the shared credential-validity deep
        # module (WI-1 #331) and the directory-cache seam, plus its config
        # knobs. The close-out family stays on this coordinator.
        self._directory = DirectoryFacade(
            engine=engine,
            credential_validity=credential_validity_module,
            directory_cache=directory_cache_module,
            directory_ttl_seconds=directory_ttl_seconds,
            directory_max_results=directory_max_results,
        )

    async def register(
        self,
        phone: str,
        partner_type: PartnerType,
        practice_address: str,
        practice_latitude: float,
        practice_longitude: float,
        service_area_id: int | None = None,
        practice_name: str | None = None,
    ) -> RegisterPartnerResult:
        """Open partner registration (FEAT-014, ADR-0010): open + sync account.

        Delegated to the registration sub-facade (ADR-0006, WI-2 p1a #332):
        the iam credential account is created synchronously first (ADR-0010),
        then the ``[Registered]`` profile opens with ``partner.registered``
        emitted - both in the same transaction. A duplicate phone resolves to
        the existing profile; concurrent registrations converge (accepted
        criterion 6). When the facade was composed without the iam seam (WI-3,
        #336 - the daily sweep builds no iam facade), this fails loudly with
        ``PartnerIamUnavailableError`` rather than opening a profile that can
        never authenticate.
        """
        return await self._registration.register(
            phone=phone,
            partner_type=partner_type,
            practice_address=practice_address,
            practice_latitude=practice_latitude,
            practice_longitude=practice_longitude,
            service_area_id=service_area_id,
            practice_name=practice_name,
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

        Delegated to the registration sub-facade (ADR-0006, WI-2 p1a #332).
        """
        return await self._registration.register_partner(
            identity_id=identity_id,
            partner_type=partner_type,
            practice_address=practice_address,
            practice_latitude=practice_latitude,
            practice_longitude=practice_longitude,
            service_area_id=service_area_id,
        )

    async def resolve_partner(self, identity_id: int) -> PartnerView:
        """Resolve the partner profile for an iam identity (credential route).

        Delegated to the registration sub-facade (ADR-0006, WI-2 p1a #332).
        Raises :class:`PartnerNotFoundError` when the identity holds no profile.
        """
        return await self._registration.resolve_partner(identity_id)

    async def resolve_partner_id_by_identity(self, identity_id: int) -> int | None:
        """The partner profile id for an iam identity, or None if absent (T05, #298).

        Non-throwing companion to ``resolve_partner``, delegated to the
        registration sub-facade (ADR-0006, WI-2 p1a #332). Used by the session
        facade's partner-session gate.
        """
        return await self._registration.resolve_partner_id_by_identity(identity_id)

    async def get_my_status(self, identity_id: int) -> PartnerMeView:
        """Read the authenticated partner's own onboarding status (US-6, P2 #271).

        A partner-scoped read-only projection resolving the caller's identity to
        their partner profile and returning status/type/round/registration time.
        Delegated to the registration sub-facade (ADR-0006, WI-2 p1a #332);
        raises :class:`PartnerNotFoundError` when the identity holds no profile.
        """
        return await self._registration.get_my_status(identity_id)

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

    async def operator_decision(
        self,
        partner_id: int,
        decision_by: int,
        *,
        approve: bool,
        reason: str | None = None,
    ) -> PartnerView:
        """Step-2 manual gate: explicit operator approval or rejection.

        Delegated to the operator-gate sub-facade (ADR-0006, WI-2 p2a #334).
        Approval is the ONLY path to ``Active`` (no auto-approve). Rejection
        REQUIRES a reason (raises :class:`RejectionReasonRequiredError` when
        blank); it is carried into the ``partner.rejected`` payload. The reject
        of an ``[Active]`` partner routes the close-out through the credential-
        validity deep module's single close-out transition (WI-1, #331) - not
        local choreography. Every decision is a single, individually attributed
        action - there is no bulk path.
        """
        return await self._operator_gate.operator_decision(
            partner_id=partner_id,
            decision_by=decision_by,
            approve=approve,
            reason=reason,
        )

    async def grace_lapse(self, partner_id: int) -> PartnerView:
        """Auto-drop an ``[Active]`` partner to ``[Under Verification]`` on grace-window lapse.

        Delegated to the operator-gate sub-facade (ADR-0006, WI-2 p2a #334):
        the event-driven 7-day grace-window auto-drop. Requires an open,
        undecided reverification round; the mere lapse is NOT a deactivation,
        so no ``credential.invalidated`` fires.
        """
        return await self._operator_gate.grace_lapse(partner_id)

    async def invalidate_credential(
        self,
        partner_id: int,
        reason: CredentialInvalidatedReason = CredentialInvalidatedReason.REVOKED,
        *,
        revoked_by: UUID | None = None,
    ) -> PartnerView:
        """Immediately revoke a partner's credentials (PHASE-6 T04a, #315; ADR-0011).

        The immediate close-out leg of ADR-0011: a credential taken away by
        authority or operator decision is revoked NOW - never left for the daily
        expiry sweep. Every live (``revoked_at IS NULL``) credential row of the
        partner is stamped ``revoked_at`` + ``invalidation_reason`` (``revoked``
        by default, ``revoked_by`` the acting principal when named), the
        ``partner_directory_index`` entry is deindexed (``is_active = False`` -
        ADR-0012 one-entry-per-partner read-side cache), and ``credential.invalidated``
        (with the reason carried onto the envelope) is written to the outbox in
        the SAME transaction as those writes - mirroring
        ``purge_expired_credentials`` (ADR-0002 §1, coding-standards §4). The
        directory-search cache is flushed after the commit (best-effort, silent
        on failure; the lazy read-hide is correct regardless).

        Identity, profile row and verification history are untouched - there is
        deliberately NO new lifecycle state (ADR-0008, brief handoff #315): the
        partner stays ``[Active]`` and recovers by submitting a fresh
        verification round through the Phase-5 flow, never by re-registering.
        ``has_invalid_credential`` (credential-validity module) derives the lazy
        read-hide against the recorded ``revoked_at`` on every search/profile
        read, so the revoked
        partner disappears from directory reads instantly.
        """
        async with self._engine.begin() as connection:
            profile = await _load_profile(connection, partner_id)
            closed = (
                await connection.execute(
                    partner_credentials.update()
                    .where(
                        partner_credentials.c.profile_id == partner_id,
                        partner_credentials.c.revoked_at.is_(None),
                    )
                    .values(
                        revoked_at=self._clock(),
                        revoked_by=revoked_by,
                        invalidation_reason=reason,
                        updated_at=func.now(),
                    )
                    .returning(partner_credentials.c.id)
                )
            ).all()
            first_credential_id = int(closed[0].id) if closed else None
            await self._credential_validity.close_out_credentials(
                connection,
                [
                    CloseOutCredential(
                        credential_id=first_credential_id,
                        partner_id=partner_id,
                        identity_id=profile.identity_id,
                        reason=reason,
                    )
                ],
            )
            return PartnerView(
                partner_id=partner_id,
                status=profile.status,
                round=profile.round,
            )

    async def close_out_expired_credentials(self) -> list[int]:
        """The daily credential-expiry close-out pass (ADR-0011, PHASE-6 T04b, #316).

        The daily sweep is ADR-0011's second, non-scanner mechanism: lazy read-
        hide already suppresses an expired partner on every directory read (via
        ``has_invalid_credential`` (credential-validity module) against the
        recorded ``expires_at``), so this pass performs ONLY the official
        close-out - the recorded event/audit that
        the event-triggered chain (role denial, partner notification, audit
        ledger) fires exactly once on. It is invoked by the worker's daily
        APScheduler job (``worker.main`` ``_run_credential_sweep``), never by a
        read.

        It finds every ``partner_credentials`` row whose recorded ``expires_at``
        has passed since the last pass and records the close-out - ``revoked_at``
        (the close-out instant) + ``invalidation_reason = 'expired'`` (the
        marker; ``revoked_by`` stays NULL - the sweep is a system actor), sets the
        ``partner_directory_index`` entry ``is_active = False`` once per affected
        partner, and writes exactly one ``credential.invalidated`` (reason
        ``expired``) per credential - ALL in one DB transaction (ADR-0002 §1), so
        a crash cannot leave an event without its close-out or vice versa.

        The close-out marker is the idempotency key: candidates are only rows with
        ``invalidation_reason IS NULL``, so replaying the pass (a re-run of the
        daily job, at-least-once) selects nothing and emits nothing. A row closed
        by the immediate revocation reach (``invalidate_credential``) or the
        permanent-rejection cleanup path is never revisited - the sweep does not
        disturb either seam.

        Only an ``[Active]`` partner's *verified* credential is a candidate: an
        unverified submission is an undecided operator-gate round (its expiry is
        that gate's decision, not the sweep's) and a ``[Rejected]`` partner was
        already closed out by ``operator_decision`` / will be purged by
        ``purge_expired_credentials`` - sweeping them would double-fire the
        event.

        Returns the ids of the credentials closed out.
        """
        now = self._clock()
        async with self._engine.begin() as connection:
            rows = (
                await connection.execute(
                    select(
                        partner_credentials.c.id,
                        partner_credentials.c.profile_id,
                        partner_profiles.c.identity_id,
                    )
                    .join(
                        partner_profiles,
                        partner_profiles.c.id == partner_credentials.c.profile_id,
                    )
                    .where(
                        partner_credentials.c.expires_at.is_not(None),
                        partner_credentials.c.expires_at <= now,
                        partner_credentials.c.invalidation_reason.is_(None),
                        partner_credentials.c.verified.is_(True),
                        partner_profiles.c.status == PartnerStatus.ACTIVE.value,
                    )
                    .order_by(partner_credentials.c.id)
                )
            ).all()
            if not rows:
                return []
            closed_status = CredentialInvalidatedReason.EXPIRED.value
            await connection.execute(
                partner_credentials.update()
                .where(partner_credentials.c.id.in_([int(row.id) for row in rows]))
                .values(
                    revoked_at=now,
                    invalidation_reason=closed_status,
                    updated_at=func.now(),
                )
            )
            return await self._credential_validity.close_out_credentials(
                connection,
                [
                    CloseOutCredential(
                        credential_id=int(row.id),
                        partner_id=int(row.profile_id),
                        identity_id=int(row.identity_id),
                        reason=closed_status,
                    )
                    for row in rows
                ],
            )

    async def list_verification_queue(
        self,
        *,
        partner_type: str | None = None,
        status: str | None = "Under Verification",
        sort_by: str = "registration_age",
    ) -> PartnerQueue:
        """The operator verification queue (FEAT-015, user story 16).

        Delegated to the operator-gate sub-facade (ADR-0006, WI-2 p2a #334):
        lists partner profiles with their latest verification round, age-
        prioritised for the activation-cycle KPI. An unknown ``sort_by`` raises
        :class:`InvalidQueueSortError` and an unknown ``status`` raises
        :class:`InvalidQueueStatusError`.
        """
        return await self._operator_gate.list_verification_queue(
            partner_type=partner_type,
            status=status,
            sort_by=sort_by,
        )

    async def search_directory(
        self,
        *,
        query: str | None = None,
        partner_type: str | None = None,
        specialty: str | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
        patient_id: int | None = None,
    ) -> DirectorySearchView:
        """Public directory search (MOD-002, FEAT-004, PHASE-6 T02a #313).

        Delegated to the directory sub-facade (ADR-0006, WI-2 p2b #337).
        Returns only ``[Active]`` partners with all-verified, unexpired,
        unrevoked credentials, nearest-first, with the wider-area fallback and
        the ``directory.search`` analytics event; Redis-accelerated with lazy
        validity re-derivation (PHASE-6 T02b, #314) - never a correctness
        surface.
        """
        return await self._directory.search_directory(
            query=query,
            partner_type=partner_type,
            specialty=specialty,
            latitude=latitude,
            longitude=longitude,
            patient_id=patient_id,
        )

    async def record_partner_selected(
        self,
        *,
        partner_id: int,
        partner_type: str | None = None,
        source: str | None = None,
    ) -> None:
        """Record one ``partner.selected`` analytics pick into the partner outbox.

        Delegated to the directory sub-facade (ADR-0006, WI-2 p2b #337): the
        client-initiated pick (``POST /v1/directory/select``, PHASE-6 T4 #326)
        is written as a single ``partner.selected`` outbox row in its own
        transaction - telemetry, never a regulated act, never patient identity,
        PHI or credential data.
        """
        return await self._directory.record_partner_selected(
            partner_id=partner_id,
            partner_type=partner_type,
            source=source,
        )

    async def get_provider_profile(self, partner_id: int) -> ProviderProfileView:
        """Public provider profile (MOD-002, FEAT-005, PHASE-6 T03 #309).

        Delegated to the directory sub-facade (ADR-0006, WI-2 p2b #337): the
        verified-safe profile of an ``[Active]`` partner with a
        ``directory_index`` entry and valid (verified, unexpired, unrevoked)
        credentials. The visibility gate matches search exactly - the profile
        is hidden (``ProviderProfileNotFoundError``, mapped to a 404) exactly
        when search hides the card (ADR-0011 "tick gone = card gone"). Never
        exposed: artifact refs, emails, phones, PHI.
        """
        return await self._directory.get_provider_profile(partner_id)

    async def get_verification_detail(
        self, partner_id: int, actor_id: int
    ) -> PartnerVerificationDetail:
        """Open a queue item: the full per-partner review (FEAT-015, story 17).

        Delegated to the operator-gate sub-facade (ADR-0006, WI-2 p2a #334):
        returns the profile, all submitted credentials, the verification history
        and the partner's audit chain so the operator can make a defensible
        decision, and emits ``partner.credential_reviewed`` (with ``actor_id``)
        for the "who saw this document" trail.
        """
        return await self._operator_gate.get_verification_detail(partner_id, actor_id)

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
            if not rows:
                return []
            deleted: list[int] = []
            for row in rows:
                credential_id = int(row.id)
                refs = dict(row.artifact_refs or {})
                await connection.execute(
                    partner_credentials.delete().where(
                        partner_credentials.c.id == credential_id,
                    )
                )
                if self._artifact_store is not None:
                    self._artifact_store.delete_artifacts(refs)
                deleted.append(credential_id)
            await self._credential_validity.close_out_credentials(
                connection,
                [
                    CloseOutCredential(
                        credential_id=int(row.id),
                        partner_id=int(row.profile_id),
                        identity_id=int(row.identity_id),
                        reason="permanent_rejection_cleanup",
                    )
                    for row in rows
                ],
            )
            return deleted
