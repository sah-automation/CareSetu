"""MOD-002 partner registration lifecycle: registration sub-facade (WI-2 p1a, #332).

Following the ADR-0006 IAM precedent, the coordinator ``PartnerFacade``
(:mod:`modules.partner.facade`) delegates the registration lifecycle to this
sub-facade while exposing its unchanged public interface. A developer changing
registration behavior reads only this file - no credential-intake, operator-gate,
or directory concerns.

The sub-facade owns the full registration lifecycle:

- ``register`` opens a ``[Registered]`` profile from an open self-service
  registration (FEAT-014, T05): creates the iam credential account
  synchronously (ADR-0010) and emits ``partner.registered``; a duplicate phone
  resolves to the existing profile.
- ``register_partner`` opens a profile in ``Registered``.
- ``resolve_partner`` resolves an iam identity to the partner profile.
- ``resolve_partner_id_by_identity`` is the non-throwing resolve-for-session
  seam used by iam's partner-session gate.
- ``get_my_status`` reads the partner's own onboarding status.

It takes the engine, the credential-validity deep module (WI-1, #331), and the
iam facade in its constructor. The iam seam is OPTIONAL (WI-3, #336): it is
genuinely needed only by ``register``, which creates the sync credential
account (ADR-0010). A facade composed without it - e.g. the daily
credential-expiry sweep, which only closes out credentials - fails loudly with
:class:`PartnerIamUnavailableError` if ``register`` is ever called. It owns its
result models (``PartnerView``, ``RegisterPartnerResult``, ``PartnerMeView``) -
the coordinator re-exports them unchanged.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine

from modules.iam.facade import IamFacade
from modules.partner.domain.events import PartnerType
from modules.partner.domain.exceptions import (
    PartnerIamUnavailableError,
    PartnerNotFoundError,
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
from modules.partner.shared import (
    CredentialValidityPort,
    load_profile_by_identity,
    register_profile_race_retry,
)


class RegistrationFacade:
    """The partner registration lifecycle, shortened to one seam (ADR-0006)."""

    def __init__(
        self,
        engine: AsyncEngine,
        credential_validity: CredentialValidityPort,
        iam_facade: IamFacade | None = None,
    ) -> None:
        self._engine = engine
        # The credential-validity deep module (WI-1, #331): the coordinator owns
        # the shared instance and hands it to every sub-facade as a seam. The
        # registration lifecycle defines no eligibility predicate of its own, so
        # it keeps the reference for seam parity without calling into it.
        self._credential_validity = credential_validity
        # The iam facade seam for the synchronous credential account (ADR-0010).
        # Optional (WI-3, #336): only ``register`` consumes it, and a facade
        # built without iam (the daily sweep) raises the typed
        # ``PartnerIamUnavailableError`` when misuse requires it.
        self._iam = iam_facade

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

        When the facade was composed without the iam seam (WI-3, #336 - the
        daily sweep builds no iam facade), this fails loudly with
        :class:`PartnerIamUnavailableError` rather than silently dropping the
        sync credential account.
        """
        iam = self._iam
        if iam is None:
            raise PartnerIamUnavailableError(
                "partner registration requires the iam facade to create the "
                "sync credential account (ADR-0010), but none was composed"
            )
        async with self._engine.begin() as connection:
            account = await iam.create_credential_account(phone, connection=connection)
            identity_id = int(account.identity_id)

            existing = await load_profile_by_identity(connection, identity_id)
            if existing is not None:
                return RegisterPartnerResult(
                    partner_id=existing.partner_id,
                    identity_id=identity_id,
                    partner_type=existing.partner_type,
                    status=existing.status,
                    round=existing.round,
                    created=False,
                )

            profile, created = await register_profile_race_retry(
                connection,
                identity_id=identity_id,
                partner_type=partner_type,
                practice_name=practice_name,
                practice_address=practice_address,
                practice_latitude=practice_latitude,
                practice_longitude=practice_longitude,
                service_area_id=service_area_id,
            )
            return RegisterPartnerResult(
                partner_id=profile.partner_id,
                identity_id=identity_id,
                partner_type=profile.partner_type,
                status=profile.status,
                round=profile.round,
                created=created,
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
            profile, _created = await register_profile_race_retry(
                connection,
                identity_id=identity_id,
                partner_type=partner_type,
                practice_address=practice_address,
                practice_latitude=practice_latitude,
                practice_longitude=practice_longitude,
                service_area_id=service_area_id,
            )
            return PartnerView(
                partner_id=profile.partner_id,
                status=profile.status,
                round=profile.round,
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
            profile = await load_profile_by_identity(connection, identity_id)
            if profile is None:
                raise PartnerNotFoundError(identity_id)
            return PartnerView(
                partner_id=profile.partner_id,
                status=profile.status,
                round=profile.round,
            )

    async def resolve_partner_id_by_identity(self, identity_id: int) -> int | None:
        """The partner profile id for an iam identity, or None if absent (T05, #298).

        Non-throwing companion to ``resolve_partner``: returns the partner
        profile id when one exists, or ``None`` when the identity holds no
        partner profile (a patient-only phone). Used by the session facade's
        partner-session gate to distinguish a registered partner from a patient
        without crossing the module isolation boundary.
        """
        async with self._engine.begin() as connection:
            profile = await load_profile_by_identity(connection, identity_id)
            if profile is None:
                return None
            return profile.partner_id

    async def get_my_status(self, identity_id: int) -> PartnerMeView:
        """Read the authenticated partner's own onboarding status (US-6, P2 #271).

        A partner-scoped read-only projection resolving the caller's identity to
        their partner profile and returning status/type/round/registration time.
        Reuses the identity lookup ``load_profile_by_identity``; raises
        :class:`PartnerNotFoundError` when the identity holds no profile. Unlike
        the operator ``get_verification_detail`` it emits no audit event and
        exposes no credentials - the restricted pre-activation scope (spec).
        """
        async with self._engine.begin() as connection:
            profile = await load_profile_by_identity(connection, identity_id)
            if profile is None:
                raise PartnerNotFoundError(identity_id)
            return PartnerMeView(
                partner_id=profile.partner_id,
                status=profile.status,
                partner_type=profile.partner_type,
                round=profile.round,
                created_at=profile.created_at,
            )
