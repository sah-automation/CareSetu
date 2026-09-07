"""MOD-002 Partner lifecycle: typed public sync API (PHASE-5 T04, ticket #247).

The only legal cross-module import target for the ``partner`` module
(coding-standards §2, ADR-0003). Since the WI-2 deepening pass the facade is a
thin coordinator that delegates to lifecycle sub-facades (ADR-0006, parent
#330): the registration lifecycle (:mod:`modules.partner.registration_facade`,
WI-2 p1a #332), the credential-intake gate
(:mod:`modules.partner.credential_intake_facade`, WI-2 p2c #338), the operator
gate (:mod:`modules.partner.operator_gate_facade`, WI-2 p2a #334), and the
patient-facing directory reads (:mod:`modules.partner.directory_facade`,
WI-2 p2b #337). The close-out family stays on the coordinator after WI-2. The
coordinator re-exports the sub-facades' result models so the public surface and
all routing/cross-module callers stay unchanged.

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

Methods (delegated to the credential-intake sub-facade - WI-2 p2c #338):
- ``submit_credentials`` runs the Step-1 credential pre-filter (ADR-0008) and,
  on pass, encrypts the documents into ``partner/``, opens ``partner_credentials``
  rows and a verification round (``verification_started`` - including
  re-verification of an ``Active`` partner, who stays ``Active`` through the 7-day
  grace window) or, on auto-fail, rejects never queued (``partner.rejected`` with
  the specific pre-filter reason).
- ``get_my_verification`` reads the partner's own credential review status
  (US-7, P3 #271).
- ``get_rejection_reason`` reads the specific failure reason back to a
  ``[Rejected]`` partner so they can re-apply corrected credentials (PHASE-5 T09).
- ``appeal`` files the one-time rejection appeal, re-entering the operator
  queue (PHASE-5 T09).

Remaining coordinator methods:
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
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from modules.audit.facade import AuditFacade
from modules.iam.facade import IamFacade
from modules.partner import credential_validity as credential_validity_module
from modules.partner import directory_cache as directory_cache_module
from modules.partner.adapters.artifact_store import CredentialArtifactStore
from modules.partner.common_models import PartnerView as PartnerView
from modules.partner.credential_intake_facade import (
    CredentialIntakeFacade as CredentialIntakeFacade,
)
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
)

# The intake-facing domain exceptions are re-exported so the coordinator's public
# surface stays unchanged (ADR-0006, #338): the credential-intake sub-facade
# raises these, and prior cross-module callers imported them from the facade.
from modules.partner.domain.exceptions import (
    AppealAlreadyUsedError as AppealAlreadyUsedError,
)
from modules.partner.domain.exceptions import (
    PartnerNotFoundError as PartnerNotFoundError,
)
from modules.partner.domain.exceptions import (
    PartnerNotRejectedError as PartnerNotRejectedError,
)
from modules.partner.domain.exceptions import (
    ReSubmissionThrottledError as ReSubmissionThrottledError,
)
from modules.partner.domain.state_machine import (
    PartnerStatus,
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
    default_clock as _default_clock,
)
from modules.partner.shared import (
    load_profile as _load_profile,
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
        # Credential-intake sub-facade (ADR-0006, WI-2 p2c #338): owns the
        # two-step verification intake gate - Step-1 pre-filter, submission,
        # re-submission throttle, the partner's review-state read, the rejected-
        # partner reason read, and the one-time rejection appeal - and its result
        # models. The coordinator hands it the shared credential-validity deep
        # module (WI-1 #331), the artifact store, and the re-submission throttle
        # config knobs (PHASE-5 T09, ADR-0008; never hardcoded in the domain
        # core - coding-standards §9).
        self._credential_intake = CredentialIntakeFacade(
            engine=engine,
            credential_validity=credential_validity_module,
            artifact_store=artifact_store,
            re_submission_max=re_submission_max,
            re_submission_cooldown_days=re_submission_cooldown_days,
            clock=clock,
        )
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

        A partner-scoped read-only projection resolving the caller's identity to
        their profile and returning the current round's review state.
        Delegated to the credential-intake sub-facade (ADR-0006, WI-2 p2c #338);
        raises :class:`PartnerNotFoundError` when the identity holds no profile.
        """
        return await self._credential_intake.get_my_verification(identity_id)

    async def submit_credentials(
        self,
        partner_id: int,
        *,
        credentials: list[CredentialSubmission],
    ) -> CredentialSubmissionResult:
        """Submit professional credentials and run the Step-1 pre-filter (ADR-0008).

        The first half of the two-step gate, fully automatic and synchronous on
        submission: on a pass the documents are encrypted into ``partner/`` and
        the partner enters ``Under Verification``; on an auto-fail the partner
        returns to ``Rejected`` (never queued). A ``[Rejected]`` partner's
        re-submission is throttled (PHASE-5 T09, ADR-0008).
        Delegated to the credential-intake sub-facade (ADR-0006, WI-2 p2c #338).
        """
        return await self._credential_intake.submit_credentials(
            partner_id=partner_id,
            credentials=credentials,
        )

    async def get_rejection_reason(self, partner_id: int) -> RejectionReasonView:
        """Read the specific failure reason back to a ``[Rejected]`` partner (PHASE-5 T09).

        The partner learns WHY their application failed so they can re-apply with
        corrected credentials (ADR-0008 recovery). Raises
        :class:`PartnerNotRejectedError` when the partner is not currently
        ``[Rejected]``. Delegated to the credential-intake sub-facade
        (ADR-0006, WI-2 p2c #338).
        """
        return await self._credential_intake.get_rejection_reason(partner_id)

    async def appeal(self, partner_id: int) -> PartnerView:
        """File the one-time rejection appeal, re-entering the operator queue (PHASE-5 T09).

        A ``[Rejected]`` partner may contest an operator decision once: the appeal
        re-enters Step 2 and consumes the one-time ``appeal_used`` flag - a second
        appeal is rejected with :class:`AppealAlreadyUsedError`. The appeal does
        not advance the re-submission throttle budget. Delegated to the
        credential-intake sub-facade (ADR-0006, WI-2 p2c #338).
        """
        return await self._credential_intake.appeal(partner_id)

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
