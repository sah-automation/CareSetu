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
  verified credential band plus the practice details the doctor declared
  (#613), hidden exactly when search hides the card.
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

import logging
from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from cryptography.exceptions import InvalidTag
from pydantic import TypeAdapter, ValidationError

from modules.partner.doctor_profile_models import (
    DoctorProfileView as DoctorProfileView,
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
    ConsultationFeeNotAllowedError as ConsultationFeeNotAllowedError,
)
from modules.partner.domain.exceptions import (
    DoctorProfileNotAllowedError as DoctorProfileNotAllowedError,
)
from modules.partner.domain.exceptions import (
    DoctorProfilePhotoNotFoundError as DoctorProfilePhotoNotFoundError,
)
from modules.partner.domain.exceptions import (
    DoctorProfilePhotoStoreUnavailableError as DoctorProfilePhotoStoreUnavailableError,
)
from modules.partner.domain.exceptions import (
    DoctorProfilePhotoTransferError as DoctorProfilePhotoTransferError,
)
from modules.partner.domain.exceptions import (
    DoctorProfilePhotoValidationError as DoctorProfilePhotoValidationError,
)
from modules.partner.domain.exceptions import (
    PartnerNotActiveError as PartnerNotActiveError,
)
from modules.partner.domain.exceptions import (
    PartnerNotFoundError as PartnerNotFoundError,
)
from modules.partner.domain.exceptions import (
    PartnerNotRejectedError as PartnerNotRejectedError,
)
from modules.partner.domain.exceptions import (
    PartnerSuspendedError as PartnerSuspendedError,
)
from modules.partner.domain.exceptions import (
    PracticePinUnresolvedError as PracticePinUnresolvedError,
)
from modules.partner.domain.exceptions import (
    ProviderProfileNotFoundError as ProviderProfileNotFoundError,
)
from modules.partner.domain.exceptions import (
    ReSubmissionThrottledError as ReSubmissionThrottledError,
)
from modules.partner.domain.practice_position import (
    AddressParts,
    PinCentroid,
    PracticePosition,
    evaluate_peri_urban_belt,
    format_display_address,
    resolve_pin_code,
)
from modules.partner.domain.state_machine import (
    PartnerStatus,
)
from modules.partner.domain.vocabularies import (
    merge_notification_preferences,
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
    PartnerView as PartnerView,
)
from modules.partner.registration_models import (
    RegisterPartnerResult as RegisterPartnerResult,
)
from modules.partner.schema.models import (
    partner_credentials,
    partner_pin_centroids,

    partner_profiles,
    partner_service_areas,
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
from modules.partner.shared import (
    load_profile_by_identity as _load_profile_by_identity,
)
from modules.partner.shared import (
    selection_members as _selection_members,
)

async def _delete_doctor_profile_media(
    media_store: ProfileMediaStore,
    object_key: str,
) -> None:
    try:
        await media_store.delete(object_key=object_key)
    except Exception as exc:
        logger.warning(
            "doctor_profile_photo_cleanup_failed",
            extra={"error_type": type(exc).__name__},
        )


def _doctor_credential_status(
    record: credential_validity_module.CredentialRecord,
    *,
    now: datetime,
) -> DoctorCredentialStatus:
    reason = record.invalidation_reason
    if reason == CredentialInvalidatedReason.EXPIRED:
        return "expired"
    if reason == CredentialInvalidatedReason.REVOKED:
        return "revoked"
    if reason == CredentialInvalidatedReason.REVERIFICATION_FAILED:
        return "reverification_failed"
    if not record.verified:
        return "pending"
    if record.revoked_at is not None:
        return "revoked"
    if record.expires_at is not None and record.expires_at <= now:
        return "expired"
    return "verified"


class PartnerFacade:
    """Typed public facade for the partner lifecycle surface."""

    def __init__(
        self,
        engine: AsyncEngine,
        iam_facade: IamFacade | None = None,
        artifact_store: CredentialArtifactStore | None = None,
        audit_facade: AuditFacade | None = None,
        *,
        profile_media_store: ProfileMediaStore | None = None,
        doctor_profile_photo_max_bytes: int | None = None,
        re_submission_max: int = 3,
        re_submission_cooldown_days: int = 30,
        credential_cleanup_days: int = 30,
        directory_ttl_seconds: int = 0,
        directory_max_results: int = 50,
        clock: Callable[[], datetime] = _default_clock,
    ) -> None:
        self._engine = engine
        self._profile_media_store = profile_media_store
        self._doctor_profile_photo_max_bytes = doctor_profile_photo_max_bytes
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
        # The iam suspension read seam (F014-T06 #466): the self-service gates ask
        # iam's ``partner_role_status`` - never the partner schema - whether the
        # identity's partner role grant is ``Suspended``. Optional, same as every
        # other seam: facades composed without iam (the daily credential-expiry
        # sweep) never serve the self-service routes, so the gate is a no-op there
        # (see ``_assert_partner_not_suspended``).
        self._iam = iam_facade
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

    async def verify_partner_exists(self, connection: AsyncConnection, partner_id: int) -> bool:
        """Confirm a partner profile still exists on the given open connection (#342).

        Atomic safety-net mirror of ``resolve_partner_id_by_identity``, delegated
        to the registration sub-facade (ADR-0006, WI-2 p1a #332). Runs against a
        caller-provided connection (iam's identity-row-locked transaction) rather
        than opening its own, so the existence check is atomic with the session
        mint. Returns ``True`` when the profile exists, ``False`` when deleted.
        """
        return await self._registration.verify_partner_exists(connection, partner_id)

    async def resolve_partner_id_on_connection(
        self, connection: AsyncConnection, identity_id: int
    ) -> int | None:
        """The partner profile id for an iam identity, on a caller connection (T05, #465).

        Connection-bound companion to ``resolve_partner_id_by_identity``,
        delegated to the registration sub-facade (ADR-0006, WI-2 p1a #332). Used
        by the iam refresh route to re-confirm the partner profile at the
        composition boundary on its lock-held transaction connection.
        """
        return await self._registration.resolve_partner_id_on_connection(connection, identity_id)

    async def _assert_partner_not_suspended(self, identity_id: int) -> None:
        """Refuse a self-service action for a suspended partner (F014-T06 #466).

        The suspension signal is the iam-side one read through the existing
        ``partner_role_status`` facade seam (never by reading the iam schema):
        ``Suspended`` is not a ``PartnerStatus`` and never appears on the partner
        profile, so a profile-state check could never see it. A facade composed
        without the iam seam (e.g. the daily close-out sweep) does not serve the
        self-service routes, so the check is a no-op; every self-service
        composition passes the seam (app/main.py).
        """
        iam = self._iam
        if iam is None:
            return
        if await iam.partner_role_status(identity_id) == _IAM_SUSPENDED:
            raise PartnerSuspendedError(identity_id)

    async def get_my_status(self, identity_id: int) -> PartnerMeView:
        """Read the authenticated partner's own onboarding status (US-6, P2 #271).

        A partner-scoped read-only projection resolving the caller's identity to
        their partner profile and returning status/type/round/registration time.
        Delegated to the registration sub-facade (ADR-0006, WI-2 p1a #332);
        raises :class:`PartnerNotFoundError` when the identity holds no profile.
        Raises :class:`PartnerSuspendedError` first when the identity's partner
        role grant is suspended (F014-T06 #466) - the self-service surface is
        contact-support-only for a suspended partner (ADR-0016).
        """
        await self._assert_partner_not_suspended(identity_id)
        return await self._registration.get_my_status(identity_id)

    async def get_my_verification(self, identity_id: int) -> PartnerVerificationStatusView:
        """Read the partner's own credential review status (US-7, P3 #271).

        A partner-scoped read-only projection resolving the caller's identity to
        their profile and returning the current round's review state.
        Delegated to the credential-intake sub-facade (ADR-0006, WI-2 p2c #338);
        raises :class:`PartnerNotFoundError` when the identity holds no profile.
        Raises :class:`PartnerSuspendedError` first when the identity's partner
        role grant is suspended (F014-T06 #466).
        """
        await self._assert_partner_not_suspended(identity_id)
        return await self._credential_intake.get_my_verification(identity_id)

    async def submit_credentials(
        self,
        partner_id: int,
        *,
        credentials: list[CredentialSubmission],
        identity_id: int | None = None,
    ) -> CredentialSubmissionResult:
        """Submit professional credentials and run the Step-1 pre-filter (ADR-0008).

        The first half of the two-step gate, fully automatic and synchronous on
        submission: on a pass the documents are encrypted into ``partner/`` and
        the partner enters ``Under Verification``; on an auto-fail the partner
        returns to ``Rejected`` (never queued). A ``[Rejected]`` partner's
        re-submission is throttled (PHASE-5 T09, ADR-0008).
        Delegated to the credential-intake sub-facade (ADR-0006, WI-2 p2c #338).
        Raised ``identity_id`` (the self-service routes always pass it) is gated
        against the iam suspension seam first (F014-T06 #466): submission is
        refused with :class:`PartnerSuspendedError` while the identity's partner
        role grant is suspended; callers without an authenticated principal
        (facade-level integration callers) skip the gate.
        """
        if identity_id is not None:
            await self._assert_partner_not_suspended(identity_id)
        return await self._credential_intake.submit_credentials(
            partner_id=partner_id,
            credentials=credentials,
        )

    async def get_rejection_reason(
        self, partner_id: int, *, identity_id: int | None = None
    ) -> RejectionReasonView:
        """Read the specific failure reason back to a ``[Rejected]`` partner (PHASE-5 T09).

        The partner learns WHY their application failed so they can re-apply with
        corrected credentials (ADR-0008 recovery). Raises
        :class:`PartnerNotRejectedError` when the partner is not currently
        ``[Rejected]``. Delegated to the credential-intake sub-facade
        (ADR-0006, WI-2 p2c #338). An authenticated ``identity_id`` (the
        self-service route always passes it) is gated against the iam suspension
        seam first (F014-T06 #466).
        """
        if identity_id is not None:
            await self._assert_partner_not_suspended(identity_id)
        return await self._credential_intake.get_rejection_reason(partner_id)

    async def appeal(self, partner_id: int, *, identity_id: int | None = None) -> PartnerView:
        """File the one-time rejection appeal, re-entering the operator queue (PHASE-5 T09).

        A ``[Rejected]`` partner may contest an operator decision once: the appeal
        re-enters Step 2 and consumes the one-time ``appeal_used`` flag - a second
        appeal is rejected with :class:`AppealAlreadyUsedError`. The appeal does
        not advance the re-submission throttle budget. Delegated to the
        credential-intake sub-facade (ADR-0006, WI-2 p2c #338). An authenticated
        ``identity_id`` (the self-service route always passes it) is gated
        against the iam suspension seam first (F014-T06 #466).
        """
        if identity_id is not None:
            await self._assert_partner_not_suspended(identity_id)
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
                partner_type=profile.partner_type,
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
        """Public provider profile (MOD-002, FEAT-005, PHASE-6 T03 #309, #613).

        Delegated to the directory sub-facade (ADR-0006, WI-2 p2b #337): the
        profile of an ``[Active]`` partner with a ``directory_index`` entry and
        valid (verified, unexpired, unrevoked) credentials - the credential band
        the platform checked plus the practice details the doctor declared. The
        visibility gate matches search exactly - the profile is hidden
        (``ProviderProfileNotFoundError``, mapped to a 404) exactly when search
        hides the card (ADR-0011 "tick gone = card gone"), and widening the
        payload to the declared fields widened nothing about it. Never exposed:
        artifact refs, the practice's coordinates, emails, phones, the partner's
        identity id, notification preferences, PHI.
        """
        return await self._directory.get_provider_profile(partner_id)

    async def require_active_doctor(self, doctor_id: int) -> None:
        """Re-check that this partner profile is an active doctor, and refuse if not.

        The MOD-002 answer to "is this an active doctor?", published as its own
        narrow seam because the doctor console (MOD-012) must re-check the edge's
        role decision rather than trust it (api-standards §6,
        security-phii-standards §3: edge checks are convenience, not the
        boundary) - and module isolation means it can only ask through this
        facade, never read ``partner_profiles`` itself.

        Runs the SAME ``_require_active_doctor`` rule every doctor-profile
        method here runs, so "active doctor" has exactly one definition, and
        reads only the three columns the decision needs (id-keyed lookup, no
        profile/credential/directory load) so a re-check is cheap enough to sit
        in front of every console read. Raises ``PartnerNotFoundError`` when the
        id holds no profile and ``DoctorProfileNotAllowedError`` when the
        profile is not a ``doctor`` in the ``Active`` state - both mapped by
        this module's registered handlers.
        """
        async with self._engine.begin() as connection:
            row = (
                await connection.execute(
                    select(
                        partner_profiles.c.partner_type,
                        partner_profiles.c.status,
                    ).where(partner_profiles.c.id == doctor_id)
                )
            ).first()
            if row is None:
                raise PartnerNotFoundError(doctor_id)
            _require_active_doctor(
                partner_id=doctor_id,
                partner_type=row.partner_type,
                status=row.status,
            )

    async def get_doctor_profile(self, doctor_id: int) -> DoctorProfileView:
        async with self._engine.begin() as connection:
            row = (
                await connection.execute(
                    select(
                        partner_profiles.c.id.label("partner_id"),
                        partner_profiles.c.partner_type,
                        partner_profiles.c.status,
                        partner_profiles.c.photo_ref,
                        partner_profiles.c.practice_name,
                        partner_profiles.c.clinic_name,
                        # The specialty selection comes from the PROFILE ROW, not
                        # from the directory entry this read used to outer-join
                        # (#608). The profile row is the source of truth - it is
                        # the column the practice section write lands on - and the
                        # directory entry only receives a copy from the shared
                        # refresh (#607). Joining instead would let this read
                        # disagree with the row that was just written whenever the
                        # write and the refresh are not in one transaction, which
                        # is the normal case.
                        partner_profiles.c.specialties,
                        partner_profiles.c.practice_address,
                        # The structured address parts, which is what the address
                        # card edits and seeds from (#609). Read here beside the
                        # display projection so a client never has to parse an
                        # assembled string back into the fields it declared.
                        partner_profiles.c.address_line,
                        partner_profiles.c.address_landmark,
                        partner_profiles.c.address_locality,
                        partner_profiles.c.address_city,
                        partner_profiles.c.address_pin,

                        partner_profiles.c.practice_latitude,
                        partner_profiles.c.practice_longitude,
                        partner_service_areas.c.name.label("area_name"),
                        partner_profiles.c.languages,
                        partner_profiles.c.experience_years,
                        partner_profiles.c.about,
                        partner_profiles.c.consultation_fee_paise,
                        # #610: the availability split. ``consulting_days`` is the
                        # closed seven-day selection the about write lands on, and
                        # ``consulting_hours`` is the prose that replaces the
                        # ``availability`` blob this projection used to serve. The
                        # retired column is no longer selected: it is inert (#606)
                        # and rendering an availability no card can edit is worse
                        # than not rendering one.
                        partner_profiles.c.consulting_days,
                        partner_profiles.c.consulting_hours,

                        partner_profiles.c.notification_preferences,
                    )
                    .select_from(partner_profiles)
                    .outerjoin(
=======
                        partner_directory_index,
                        partner_directory_index.c.partner_id == partner_profiles.c.id,
                    )
                    .outerjoin(
>>>>>>> origin/main
                        partner_service_areas,
                        partner_service_areas.c.id == partner_profiles.c.service_area_id,
                    )
                    .where(partner_profiles.c.id == doctor_id)
                )
            ).first()
            if row is None:
                raise PartnerNotFoundError(doctor_id)
            _require_active_doctor(
                partner_id=doctor_id,
                partner_type=row.partner_type,
                status=row.status,
            )
            credential_rows = (
                await connection.execute(
                    select(
                        partner_credentials.c.credential_type,
                        partner_credentials.c.verified,
                        partner_credentials.c.expires_at,
                        partner_credentials.c.revoked_at,
                        partner_credentials.c.invalidation_reason,
                    )
                    .where(partner_credentials.c.profile_id == doctor_id)
                    .order_by(partner_credentials.c.round.desc(), partner_credentials.c.id)
                )
            ).all()

        now = self._clock()
        credential_records = [
            credential_validity_module.CredentialRecord(
                id=index,
                verified=bool(credential.verified),
                expires_at=credential.expires_at,
                revoked_at=credential.revoked_at,
                invalidation_reason=credential.invalidation_reason,
            )
            for index, credential in enumerate(credential_rows, start=1)
        ]
        eligibility = credential_validity_module.evaluate_eligibility(
            credential_records,
            now=now,
        )
        return DoctorProfileView(
            partner_id=int(row.partner_id),
            photo_ref=row.photo_ref,
            practice_name=row.practice_name,
            clinic_name=row.clinic_name,
            verified=eligibility.has_any and not eligibility.has_invalid,
            practice_address=str(row.practice_address),
            address_line=row.address_line,
            landmark=row.address_landmark,
            locality=row.address_locality,
            city=row.address_city,
            pin_code=row.address_pin,
            practice_latitude=float(row.practice_latitude),
            practice_longitude=float(row.practice_longitude),
            area=str(row.area_name) if row.area_name is not None else DEFAULT_SERVICE_AREA_NAME,

            experience_years=(
                int(row.experience_years) if row.experience_years is not None else None
            ),
            about=row.about,
            consultation_fee=(
                int(row.consultation_fee_paise) if row.consultation_fee_paise is not None else None
            ),
            # All THREE selections this view serves, through one defensive
            # projection: a junk member reads as an absent one rather than failing
            # the response model. The two the about write owns join the specialty
            # selection #608 landed, so the three cannot drift apart on how a
            # stored JSONB array becomes a wire list.
            specialties=_selection_members(row.specialties),
            languages=_selection_members(row.languages),
            consulting_days=_selection_members(row.consulting_days),
            consulting_hours=row.consulting_hours,

            credentials=[
                DoctorProfileCredential(
                    credential_type=str(credential.credential_type),
                    status=_doctor_credential_status(record, now=now),
                    expires_at=credential.expires_at,
                )
                for credential, record in zip(
                    credential_rows,
                    credential_records,
                    strict=True,
                )
            ],
            notification_preferences=_renderable_notification_preferences(
                row.notification_preferences,
            ),
        )

    async def update_doctor_practice(
        self,
        doctor_id: int,
        update: DoctorProfilePracticeUpdate,
    ) -> DoctorProfileView:
        """Save the Practice card: the doctor's name, clinic, specialties, experience (#608).

        The first of the four section writes that replaced the retired whole-form
        profile write (#611). It touches ONLY this card's columns - the doctor's
        ``practice_name``, the ``clinic_name`` building, the ``specialties``
        selection and ``experience_years`` - and never the address, the languages,
        the about text, the availability or the notification preferences. That is
        the whole point of the split: a save of one card cannot move a field no
        card on the screen is editing, so two doctors editing their profile
        concurrently lose nothing but the field they were both typing in.

        The refusal and the lock are the retired whole-form write's, deliberately
        unchanged and now shared rather than copied:
        ``_update_active_doctor_profile`` owns the ``SELECT ... FOR UPDATE``
        recheck, the ``[Active]``-doctor refusal and the update itself
        (api-standards §6: every authorization is re-checked in the facade, not
        only at the edge). #609 and #610 call the same helper, so all four section
        writes share one lock shape rather than four.

        The wire field ``full_name`` maps to the ``practice_name`` column here -
        see ``DoctorProfilePracticeUpdate`` for why the rename is on the wire and
        not the column. Everything else is name-for-name, so this write's
        ``.values()`` payload is the model's ``model_dump()`` with that one key
        moved.

        Nothing about credentials is touched: profile fields are DECLARED,
        credentials are VERIFIED (ADR-0011), so the derived ``verified`` flag in
        the read-back is unaffected by what this writes. Nor is the directory
        entry's listed flag: this write reaches the entry only through the shared
        refresh (#607), which copies the position and the specialties and never a
        listed flag or any verified derivation, so a doctor cannot list themselves
        by editing their own practice card (ADR-0008).
        """
        values = update.model_dump()
        # The one wire-to-column rename, applied once here rather than by every
        # caller - see the model docstring. ``pop`` so the dictionary never holds
        # both keys and the column set cannot drift with the field name.
        values["practice_name"] = values.pop("full_name")
        async with self._engine.begin() as connection:
            await _update_active_doctor_profile(connection, doctor_id, values)
            # This card is one of the two writers of the ``specialties`` selection,
            # so it is one of the two callers of the shared refresh (#607). Without
            # it a doctor who saved only the Practice card would carry their
            # specialties on their public profile (which reads the profile row)
            # while directory search kept filtering on the stale index value - two
            # public surfaces disagreeing about the same doctor. The refresh writes
            # only the entry's position and specialties, so the caller's row lock
            # and the [Active] recheck already decided everything it touches.
            await self._credential_validity.refresh_directory_entry(connection, doctor_id)
        # Every section write answers with the profile the doctor's next GET would
        # serve, so the card re-renders from one call.
        return await self.get_doctor_profile(doctor_id)

    async def update_doctor_address(
        self,
        doctor_id: int,
        update: DoctorProfileAddressUpdate,
    ) -> DoctorProfileAddressView:
        """Save the Address card: where the practice is (#609).

        The heart of the defect fix. The doctor declares an address and the backend
        DERIVES the practice position from the declared PIN code - never from a
        coordinate the client sent, which this write's model does not declare at
        all. That is what lets a doctor who signed up with a wrong PIN actually
        correct it, and it is why the position columns stay ``NOT NULL`` while no
        update schema carries them (#606).

        **The order inside one transaction is the correctness argument.**

        1. Lock the row and re-check the partner is an ``[Active]`` doctor
           (:func:`_lock_active_doctor_profile`) - before the centroid table is
           read, so a refused partner learns nothing and nothing is written.
        2. Look the declared code up (:func:`_load_pin_centroid`) and hand the row
           to the pure decision. A PIN that cannot be placed raises
           ``PracticePinUnresolvedError`` here, which is a 422 keyed to the PIN
           field - and it raises BEFORE the ``UPDATE``, so an unresolvable PIN
           leaves every column and the directory entry untouched. There is no
           fallback position and no queue row to compensate: the unlisted-PIN data
           gap is a follow-up, not something to work around.
        3. Evaluate the peri-urban belt against the resolved point. This is a
           WARNING, never a refusal: the belt boundary is passed in from the
           directory sub-facade's own ``PERI_URBAN_RADIUS_KM`` so the warning and
           the search clamp are one boundary rather than two (#603), and a doctor in
           a real but outlying town is never blocked from correcting their address.
        4. Write the declared parts, the assembled display string and the derived
           position.
        5. Re-derive the directory entry through the shared refresh (#607), in this
           same transaction. The refresh is an ``INSERT ... FROM SELECT`` that reads
           the profile row, so the position written in step 4 is what lands in the
           entry - that is why the two cannot be separate transactions, and why
           ``search_directory`` returns the doctor at the new position immediately
           afterwards. The refresh also flushes the directory-search namespace
           itself, so this method does not: exactly one flush, inside the operation
           that owns it.

        Nothing about credentials is touched. Profile fields are DECLARED,
        credentials are VERIFIED (ADR-0011), and the refresh cannot write the
        listed flag - so a doctor cannot activate themselves by editing their
        address, which is the invariant #607 already asserts for the operator path.

        Returns :class:`DoctorProfileAddressView`, not the plain read projection:
        the belt warning is this write's answer and no other read's, so it is a
        field on this response rather than a nullable one every GET would carry.
        """
        # One strip, applied where the database needs it: the ``address_pin`` CHECK
        # is ``^[0-9]{6}$`` and the column is ``String(6)``, so the stored form has
        # to be the six digits themselves and the declared value is stripped once
        # here for that reason. It is the SAME normalisation
        # ``resolve_pin_code`` applies - the point is not a second copy of the rule
        # but that the value written is the value the decision accepted.
        # ``AddressParts`` keeps the raw declared value and lets
        # ``format_display_address`` normalise it for display, exactly as it does
        # for every other absent-or-blank part.
        declared_pin = update.pin_code.strip()
        parts = AddressParts(
            address_line=update.address_line,
            landmark=update.landmark,
            locality=update.locality,
            city=update.city,
            pin_code=update.pin_code,
        )
        async with self._engine.begin() as connection:
            await _lock_active_doctor_profile(connection, doctor_id)
            resolution = resolve_pin_code(
                declared_pin,
                await _load_pin_centroid(connection, declared_pin),
            )
            position = resolution.position
            if position is None:
                raise PracticePinUnresolvedError(declared_pin, resolution.reason)
            belt = evaluate_peri_urban_belt(
                position,
                centre=PracticePosition(
                    latitude=DALTONGANJ_LATITUDE,
                    longitude=DALTONGANJ_LONGITUDE,
                ),
                radius_km=PERI_URBAN_RADIUS_KM,
            )
            await _write_active_doctor_profile(
                connection,
                doctor_id,
                {
                    # The declared parts and the derived position, in one dictionary
                    # built from ``parts`` so the display string and the columns
                    # cannot be assembled from two different readings of the body.
                    # Four of the five wire-to-column moves are a rename onto the
                    # ``address_`` prefix the columns carry, because the wire field
                    # says what the field MEANS and the column keeps the name its
                    # other readers already use.
                    "address_line": parts.address_line,
                    "address_landmark": parts.landmark,
                    "address_locality": parts.locality,
                    "address_city": parts.city,
                    "address_pin": declared_pin,
                    # The retained display column is a backend-assembled projection
                    # of exactly these parts (#603), rewritten here so the column,
                    # the write and every renderer cannot disagree.
                    "practice_address": format_display_address(parts),
                    "practice_latitude": position.latitude,
                    "practice_longitude": position.longitude,
                },
            )
            await self._credential_validity.refresh_directory_entry(connection, doctor_id)
        profile = await self.get_doctor_profile(doctor_id)
        return DoctorProfileAddressView(
            **profile.model_dump(),
            outside_peri_urban_belt=not belt.within_belt,
            distance_from_belt_centre_km=belt.distance_km,
        )

    async def update_doctor_about(
        self,
        doctor_id: int,
        update: DoctorProfileAboutUpdate,
    ) -> DoctorProfileView:
        """Save the About card: about text, languages, consulting days, hours (#610).

        The third of the four section writes, and the one that splits a field
        rather than moving it: the old ``availability`` blob becomes a closed
        seven-day SELECTION plus a free-prose hours string. The two halves go to
        two columns (``consulting_days``, ``consulting_hours``) and the old column
        is not written at all - it has been inert since #606, and #611 retired the
        whole-form write that last addressed it, so nothing writes it at all now.
        Nothing parses an existing ``availability`` value into the two new
        columns: recovering chips from hand-typed free text is guesswork, and a
        wrong guess is worse than an empty prompt.

        It touches ONLY this card's columns - ``about``, the ``languages``
        selection, ``consulting_days`` and ``consulting_hours`` - and never the
        doctor's name, the specialties, the address or the notification
        preferences. The ``.values()`` payload is the model's ``model_dump()``
        verbatim: every field is name-for-name with its column, and the two closed
        lists arrive as the resolved members rather than the submitted strings,
        because the model's validators ran before this was reached.

        The refusal and the lock are the other section writes', unchanged and
        shared rather than copied: :func:`_update_active_doctor_profile` owns the
        ``SELECT ... FOR UPDATE`` recheck, the ``[Active]``-doctor refusal and the
        update itself (api-standards §6).

        **No directory entry is refreshed and no cache is flushed**, and that is
        the point: these four columns are DECLARED prose and selections, none of
        them a search filter or a positioning input. The one filterable field a
        doctor would expect to move here - the specialty - is the practice card's
        (#608), and the address write (#609) is the only one that calls the shared
        refresh.

        Nothing about credentials is touched: profile fields are DECLARED,
        credentials are VERIFIED (ADR-0011), so the derived ``verified`` flag in
        the read-back is unaffected by what this writes.
        """
        values = update.model_dump()
        async with self._engine.begin() as connection:
            await _update_active_doctor_profile(connection, doctor_id, values)
        return await self.get_doctor_profile(doctor_id)

    async def update_doctor_notification(
        self,
        doctor_id: int,
        update: DoctorProfileNotificationUpdate,
    ) -> DoctorProfileView:
        """Save the Notification card: which of the five things to be told about (#610).

        The fourth and last section write, and the only **single-column** write in
        the module outside the consultation-fee editor. The acceptance criterion
        that it touches only its own column is therefore cheap to state and cheap
        to hold: the ``.values()`` payload is exactly one key plus the
        ``updated_at`` touch, so no other field on this profile can move because of
        a switch the doctor flipped.

        The payload is NOT the submitted dict, though, and that is the only thing
        worth reading here. The row is read under the lock the other section writes
        take, its stored preferences are merged with the submission through
        :func:`~modules.partner.domain.vocabularies.merge_notification_preferences`,
        and the merge is what gets written. So:

        - a key the five do not name and the row already holds is **carried
          through untouched**, which is the promise the doctor Profile page used to
          keep client-side and the server now keeps for every client;
        - a key the five do not name and the row does not hold is **refused**,
          because carrying is not the same as being able to write one;
        - a key the five DO name and the submission omits is **dropped**, so a save
          means "these are my five toggles" and a doctor can turn them all off.

        That read is a third statement inside the write's transaction, not a fourth
        card's worth of work: the row is already locked by the recheck, so the
        stored preferences come off the SAME row rather than from a second query
        that could see a different state than the one being written over.

        The refusal and the lock are the other section writes', unchanged and
        shared: :func:`_lock_active_doctor_profile` then
        :func:`_write_active_doctor_profile`, which is #609's split - the lock is
        taken and the partner refused before the stored preferences are read, so a
        partner who is not an ``[Active]`` doctor writes nothing and learns nothing
        about their own row.

        Nothing about credentials is touched (ADR-0011), and no notification is
        actually sent: this records which of the five a doctor wants, and the
        delivery side is a separate concern from a preference a doctor declared.
        """
        async with self._engine.begin() as connection:
            await _lock_active_doctor_profile(connection, doctor_id)
            # The row is locked, so this is the row the write is about to replace -
            # not a second look that could disagree with it. ``notification_preferences``
            # is NOT NULL with a ``{}`` default, so a legacy row is a dict here and
            # a hand-repaired non-dict degrades to nothing stored rather than 500ing
            # a doctor's save - an ``isinstance`` check, not a truthiness test, since
            # a truthy non-dict would still reach ``.items()`` and raise.
            stored = (
                await connection.execute(
                    select(partner_profiles.c.notification_preferences).where(
                        partner_profiles.c.id == doctor_id
                    )
                )
            ).first()
            stored_preferences = getattr(stored, "notification_preferences", None)
            await _write_active_doctor_profile(
                connection,
                doctor_id,
                {
                    "notification_preferences": merge_notification_preferences(
                        submitted=update.notification_preferences,
                        stored=(stored_preferences if isinstance(stored_preferences, dict) else {}),
                    )
                },
            )

        return await self.get_doctor_profile(doctor_id)

    async def update_doctor_photo(
        self,
        doctor_id: int,
        *,
        media_type: str | None,
        data: bytes,
    ) -> DoctorProfilePhotoView:
        media_store = self._profile_media_store
        max_bytes = self._doctor_profile_photo_max_bytes
        if media_store is None or max_bytes is None:
            raise DoctorProfilePhotoStoreUnavailableError(
                "doctor profile media store is not configured"
            )
        _canonical_doctor_profile_media_type(
            media_type,
            data,
            max_bytes=max_bytes,
        )
        async with self._engine.begin() as connection:
            row = (
                await connection.execute(
                    select(
                        partner_profiles.c.partner_type,
                        partner_profiles.c.status,
                    ).where(partner_profiles.c.id == doctor_id)
                )
            ).first()
        if row is None:
            raise PartnerNotFoundError(doctor_id)
        _require_active_doctor(
            partner_id=doctor_id,
            partner_type=row.partner_type,
            status=row.status,
        )
        try:
            new_key = await media_store.save(
                data=data,
                subject_id=doctor_id,
                prefix=DOCTOR_PREFIX,
            )
        except ProfileMediaStoreError as exc:
            if exc.retries_exhausted:
                raise DoctorProfilePhotoTransferError("doctor profile photo upload failed") from exc
            raise DoctorProfilePhotoStoreUnavailableError(
                "doctor profile media store is unavailable"
            ) from exc
        except InvalidTag as exc:
            logger.critical("profile media integrity failure")
            raise DoctorProfilePhotoStoreUnavailableError(
                "doctor profile media store returned unreadable data"
            ) from exc
        except OSError as exc:
            raise DoctorProfilePhotoTransferError("doctor profile photo upload failed") from exc

        previous_key: str | None = None
        try:
            async with self._engine.begin() as connection:
                locked_row = (
                    await connection.execute(
                        select(
                            partner_profiles.c.partner_type,
                            partner_profiles.c.status,
                            partner_profiles.c.photo_ref,
                        )
                        .where(partner_profiles.c.id == doctor_id)
                        .with_for_update()
                    )
                ).first()
                if locked_row is None:
                    raise PartnerNotFoundError(doctor_id)
                _require_active_doctor(
                    partner_id=doctor_id,
                    partner_type=locked_row.partner_type,
                    status=locked_row.status,
                )
                previous_key = locked_row.photo_ref
                await connection.execute(
                    partner_profiles.update()
                    .where(partner_profiles.c.id == doctor_id)
                    .values(photo_ref=new_key, updated_at=func.now())
                )
        except Exception:
            await _delete_doctor_profile_media(media_store, new_key)
            raise

        if previous_key is not None and previous_key != new_key:
            await _delete_doctor_profile_media(media_store, previous_key)
        return DoctorProfilePhotoView(photo_ref=new_key)

    async def get_doctor_photo(self, doctor_id: int) -> PhotoContent:
        media_store = self._profile_media_store
        if media_store is None:
            raise DoctorProfilePhotoStoreUnavailableError(
                "doctor profile media store is not configured"
            )
        async with self._engine.begin() as connection:
            row = (
                await connection.execute(
                    select(
                        partner_profiles.c.partner_type,
                        partner_profiles.c.status,
                        partner_profiles.c.photo_ref,
                    ).where(partner_profiles.c.id == doctor_id)
                )
            ).first()
        if row is None:
            raise PartnerNotFoundError(doctor_id)
        _require_active_doctor(
            partner_id=doctor_id,
            partner_type=row.partner_type,
            status=row.status,
        )
        if row.photo_ref is None:
            raise DoctorProfilePhotoNotFoundError(doctor_id)
        try:
            data = await media_store.read(object_key=row.photo_ref)
        except FileNotFoundError as exc:
            raise DoctorProfilePhotoNotFoundError(doctor_id) from exc
        except InvalidTag as exc:
            logger.critical("profile media integrity failure")
            raise DoctorProfilePhotoStoreUnavailableError(
                "doctor profile media store returned unreadable data"
            ) from exc
        except OSError as exc:
            raise DoctorProfilePhotoStoreUnavailableError(
                "doctor profile photo storage read failed"
            ) from exc
        return PhotoContent(
            data=data,
            media_type=_sniff_doctor_profile_media_type(data),
        )

    async def delete_doctor_photo(self, doctor_id: int) -> None:
        media_store = self._profile_media_store
        if media_store is None:
            raise DoctorProfilePhotoStoreUnavailableError(
                "doctor profile media store is not configured"
            )
        old_key: str
        async with self._engine.begin() as connection:
            row = (
                await connection.execute(
                    select(
                        partner_profiles.c.partner_type,
                        partner_profiles.c.status,
                        partner_profiles.c.photo_ref,
                    )
                    .where(partner_profiles.c.id == doctor_id)
                    .with_for_update()
                )
            ).first()
            if row is None:
                raise PartnerNotFoundError(doctor_id)
            _require_active_doctor(
                partner_id=doctor_id,
                partner_type=row.partner_type,
                status=row.status,
            )
            if row.photo_ref is None:
                return
            old_key = row.photo_ref
            await connection.execute(
                partner_profiles.update()
                .where(partner_profiles.c.id == doctor_id)
                .values(photo_ref=None, updated_at=func.now())
            )
        await _delete_doctor_profile_media(media_store, old_key)

    async def update_consultation_fee(
        self,
        identity_id: int,
        *,
        fee_paise: int | None,
    ) -> PartnerView:
        """Set or clear the calling doctor's consultation fee (PHASE-8.1 T06, #444).

        Partner-scoped profile mutation: resolves the authenticated partner
        principal (``identity_id``) to their own profile and writes the nullable
        ``consultation_fee_paise`` (integer paise). Only a doctor partner may
        set a fee - a lab or chemist (or any other principal) is refused with
        :class:`ConsultationFeeNotAllowedError` (mapped to a 403); the check
        lives here in the facade, never just the router (coding-standards §4
        pre-conditions in the domain core). The fee is additionally gated to the
        ``[Active]`` state (F014-T06 #466): a partner that is not yet active (or
        no longer, via deactivation) is refused with
        :class:`PartnerNotActiveError` (mapped to a 403) - a fee only makes
        sense once the partner is live in the directory. A suspended identity is
        refused first with :class:`PartnerSuspendedError`, matching every other
        self-service route (contact-support-only surface, ADR-0016).

        ``fee_paise`` is the integer-paise amount the doctor charges, or ``None``
        to clear the fee back to unset (null). No credential gate rides the fee -
        it is NOT PHI and never blocks a pick: an unset fee stays null on the
        directory entry and provider profile projection and the client renders
        "fee not set" (the pick never requires a fee).

        The fee surfaces on the directory search cache, so after the commit the
        directory-search namespace is flushed (best-effort Redis op). A failed
        flush leaves the accelerator serving the previous fee until its TTL -
        never a correctness surface, since the fee is non-PHI and never gates a
        pick; a later fee change or the accelerated item's expiry reconciles it.
        This is the same best-effort pattern the operator gate uses on
        activation.
        """
        await self._assert_partner_not_suspended(identity_id)
        async with self._engine.begin() as connection:
            profile = await _load_profile_by_identity(connection, identity_id)
            if profile is None:
                raise PartnerNotFoundError(identity_id)
            if profile.partner_type != "doctor":
                raise ConsultationFeeNotAllowedError()
            if profile.status != PartnerStatus.ACTIVE.value:
                raise PartnerNotActiveError(profile.partner_id, profile.status)
            await connection.execute(
                partner_profiles.update()
                .where(partner_profiles.c.id == profile.partner_id)
                .values(
                    consultation_fee_paise=fee_paise,
                    updated_at=func.now(),
                )
            )
        # A fee change makes every cached search result potentially stale (the
        # cached items serialize the fee). Flush the namespace best-effort; a
        # failed flush serves the previous fee until TTL - acceptable for a
        # non-PHI, never-gating display field (ADR-0011 keeps SQL authoritative
        # and the accelerator purely a freshness accelerator).
        await self._directory_cache.directory_visibility_changed()
        return PartnerView(
            partner_id=profile.partner_id,
            partner_type=profile.partner_type,
            status=profile.status,
            round=profile.round,
        )

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
