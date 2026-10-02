"""MOD-002 partner directory reads: directory sub-facade (WI-2 p2b, #337).

Following the ADR-0006 IAM precedent, the coordinator ``PartnerFacade``
(:mod:`modules.partner.facade`) delegates the patient-facing directory read
lifecycle to this sub-facade while exposing its unchanged public interface. A
developer changing a directory read reads only this file - no registration,
credential-intake, or operator-gate concerns.

The sub-facade owns the patient-facing read surface:

- ``search_directory`` is the public directory search (MOD-002, FEAT-004,
  PHASE-6 T02a #313): only ``[Active]`` partners whose credentials are all
  verified, unexpired and unrevoked, nearest-first by great-circle distance,
  with the wider-area fallback and the ``directory.search`` analytics event.
- ``get_provider_profile`` is the public provider profile (FEAT-005, PHASE-6
  T03 #309, widened by #613 with the doctor's declared fields): the verified
  credential band plus the band the doctor declared, hidden exactly when
  search hides the card.
- ``record_partner_selected`` records one ``partner.selected`` analytics pick
  (PHASE-6 T4 #326).
- ``_cached_search_view`` / ``_cached_ids_still_valid`` are the cached-search
  accelerator (PHASE-6 T02b, #314): Redis read/write plus visibility
  re-derivation on hit - an accelerator only, never a correctness surface
  (ADR-0011 lazy correctness).

It takes the engine, the credential-validity deep module (WI-1, #331), and the
directory-cache seam in its constructor and owns its result models
(``DirectoryEntry``, ``DirectorySearchView``, ``ProviderCredential``,
``ProviderProfileView``) - the coordinator re-exports them unchanged. Search,
profile and the cache-hit re-derivation all read directory visibility from the
deep module's ``provider_visible`` predicate - the same derivation search and
the "tick gone = card gone" indicator share (ADR-0011).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Text, cast, func, literal, or_, select
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from bus.outbox_writer import write_outbox
from modules.partner.directory_models import (
    DirectoryEntry as DirectoryEntry,
)
from modules.partner.directory_models import (
    DirectorySearchView as DirectorySearchView,
)
from modules.partner.directory_models import (
    ProviderCredential as ProviderCredential,
)
from modules.partner.directory_models import (
    ProviderProfileView as ProviderProfileView,
)
from modules.partner.domain.events import (
    directory_search_envelope,
    partner_selected_envelope,
)
from modules.partner.domain.exceptions import ProviderProfileNotFoundError
from modules.partner.domain.practice_position import EARTH_MEAN_RADIUS_KM
from modules.partner.domain.vocabularies import (
    ConsultingDay,
    ConsultLanguage,
    Specialty,
)
from modules.partner.outbox import PARTNER_OUTBOX_TABLE
from modules.partner.schema.models import (
    partner_credentials,
    partner_directory_index,
    partner_profiles,
)
from modules.partner.shared import (
    PARTNER_SCHEMA,
    CredentialValidityPort,
    DirectoryCachePort,
    known_selection,
    representative_specialty,
)

# The peri-urban scope of the Phase-6 launch directory (FEAT-004, REQ-008):
# Daltonganj plus its surrounding peri-urban belt. Search clamps results to this
# many km from the patient's geo point; when nothing matches inside it, the
# wider-area fallback relaxes only the location constraint (filters kept) and
# labels the results "outside your area". A single km constant - no PostGIS -
# is the cost-floor SQL range (MOD-002 §4).
PERI_URBAN_RADIUS_KM = 25.0

# The launch directory's default origin (parent #306, FEAT-004): when the
# anonymous patient does not supply a geo point, distance sort anchors on the
# Daltonganj centre (the beachhead city, REQ-008). Single test-visible source
# for the centre coordinates - the directory test suites import these rather
# than duplicating the literals.
DALTONGANJ_LATITUDE = 24.04
DALTONGANJ_LONGITUDE = 84.07


def _row_fee_paise(row: Any) -> int | None:
    """The projected ``consultation_fee`` column, or ``None`` when absent.

    The search and profile SELECTs always carry the fee as an integer-paise
    column, but rows read from the Redis accelerator's older payloads (or the
    mocked seams) may lack it - exactly like ``appeal_used`` in
    ``shared._to_profile``, a defensive attribute read keeps those surfaces
    ``None`` instead of raising (PHASE-8.1 T06, #444).
    """
    value = getattr(row, "consultation_fee", None)
    return None if value is None else int(value)


def _haversine_km(latitude: float, longitude: float) -> Any:
    """Haversine great-circle distance in km from the caller point to a row.

    Computed in SQL over ``practice_latitude``/``practice_longitude`` so the
    peri-urban range clamp and the nearest-first sort both stay in the
    database (FEAT-004 geo via SQL range; PostGIS optional at the cost floor,
    MOD-002 §4). Returns the SQL expression - 6371 km mean Earth radius, the
    same ``EARTH_MEAN_RADIUS_KM`` the pure ``great_circle_km`` decision uses, so
    the expression and the Python calculation cannot drift apart (#603).
    """
    rad_lat_me = func.radians(latitude)
    rad_lng_me = func.radians(longitude)
    rad_lat_row = func.radians(partner_directory_index.c.practice_latitude)
    rad_lng_row = func.radians(partner_directory_index.c.practice_longitude)
    dlat = rad_lat_row - rad_lat_me
    dlon = rad_lng_row - rad_lng_me
    a = func.power(func.sin(dlat / 2), 2) + func.cos(rad_lat_me) * func.cos(
        rad_lat_row
    ) * func.power(func.sin(dlon / 2), 2)
    return EARTH_MEAN_RADIUS_KM * 2.0 * func.asin(func.sqrt(a))


class DirectoryFacade:
    """The patient-facing directory read surface, shortened to one seam (ADR-0006)."""

    def __init__(
        self,
        engine: AsyncEngine,
        credential_validity: CredentialValidityPort,
        directory_cache: DirectoryCachePort,
        *,
        directory_ttl_seconds: int = 0,
        directory_max_results: int = 50,
    ) -> None:
        self._engine = engine
        # The credential-validity deep module (WI-1, #331): the coordinator owns
        # the shared instance and hands it to every sub-facade as a seam.
        # Search, profile and the cache-hit re-derivation derive directory
        # visibility from this module's ``provider_visible`` predicate - the one
        # source of truth for "tick gone = card gone" (ADR-0011).
        self._credential_validity = credential_validity
        # The directory-cache seam (PHASE-6 T02b, #314): the coordinator exposes
        # it once so sub-facades share the same cache without re-importing.
        # This sub-facade reads/writes the accelerator; visibility mutations that
        # flush the namespace live in the other sub-facades / coordinator.
        self._directory_cache = directory_cache
        # Directory-search result cache TTL (PHASE-6 T02b, #314): the accelerator
        # only gates on Redis being available; ``0`` (the boot default when no
        # Settings-level TTL is injected) disables caching entirely so the unit
        # tier and callers that never set it stay SQL-only.
        self._directory_ttl_seconds = directory_ttl_seconds
        # Directory result cap (PHASE-6 T2, #324): the top-N bound applied after
        # distance ordering so a search never returns an unbounded nearest-first
        # list. Config-injected from the resolved Settings (app/main.py), the
        # same discipline as the throttle and TTL knobs (coding-standards §9).
        self._directory_max_results = directory_max_results

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

        Returns only ``[Active]`` partners whose credentials are all verified,
        unexpired and unrevoked (the "provider" visibility rule - REQ-028 +
        ADR-0011, both derived on read, never cached), nearest-first by
        great-circle distance from the caller's geo point. ``partner_type``
        filters on the closed doctor/lab/chemist enum; ``specialty`` names ONE
        closed-pick-list value and OVERLAPS it against the doctor's whole declared
        selection (#606), and is doctors-only, so a lab matches nothing when one is
        asked for; ``query`` is free-text over the practice name. A missing geo point
        anchors the sort on the Daltonganj centre - the launch-geography default the
        callers rely on (REQ-008 decision record; the adapters stay
        geography-agnostic and let the domain own its default).

        ``area`` on each entry is the doctor's own DECLARED locality and is ``None``
        when they declared none (#612). It is not the service-area vocabulary, which
        is a registration default rather than something a patient should read as
        where the practice is.

        The wider-area fallback (glossary): when no entry matches within the
        peri-urban scope, the location constraint alone is relaxed (type,
        specialty and name filters are kept), the run is re-executed
        nearest-first, and the view is flagged ``fell_back`` so the client
        labels the results honestly as "outside your area". ``fell_back`` is
        never silently served - the patient's other filters hold.

        Emits the ``directory.search`` analytics event (one per search) into
        the partner outbox in the SAME transaction as the read, carrying the
        filters/query, the result count and the fallback flag (telemetry, not a
        regulated act; anonymous patients have a ``None`` actor). Lab/chemist
        entries always return ``specialty=None``.
        """
        latitude = DALTONGANJ_LATITUDE if latitude is None else latitude
        longitude = DALTONGANJ_LONGITUDE if longitude is None else longitude

        # PHASE-6 T02b (#314): the Redis accelerator, layered on top of the
        # working SQL core. Redis is never a correctness surface (ADR-0011 lazy
        # correctness) - on a cache hit we re-derive validity of the cached
        # partner ids against the recorded dates; any invalidation/expiry drops
        # the hit and recomputes SQL, so a stale row for a deactivated or
        # expired partner never surfaces.
        cached = await self._cached_search_view(
            query=query,
            partner_type=partner_type,
            specialty=specialty,
            latitude=latitude,
            longitude=longitude,
            patient_id=patient_id,
        )
        if cached is not None:
            return cached

        distance_km = _haversine_km(latitude, longitude)

        def _conditions(peri_urban_only: bool) -> list[Any]:
            conditions: list[Any] = [
                self._credential_validity.provider_visible(partner_directory_index.c.partner_id)
            ]
            if partner_type is not None:
                conditions.append(partner_directory_index.c.partner_type == partner_type)
            if specialty is not None:
                # Specialty is doctors-only (closed pick-list, glossary), so the type
                # is pinned too. The pin is load-bearing rather than a nicety: since
                # #606 the column is a multi-valued selection with no CHECK
                # constraint, so a lab or chemist row could physically carry an
                # array, and "non-doctors carry no specialty" is no longer a database
                # guarantee. This explicit condition is the mechanism, and it is an
                # AND with ``partner_type`` above rather than a replacement for it -
                # a request naming a lab AND a specialty matches nothing either way.
                conditions.append(partner_directory_index.c.partner_type == "doctor")
                # The column is a multi-valued selection (#606), so an equality
                # comparison against a JSONB column would ask PostgreSQL an operator
                # question it answers "no operator". ``?|`` is the JSONB membership
                # test, so the OVERLAP is on the STORED side: the requested value is
                # one member, the column holds the doctor's whole declared set, and
                # the row matches when the requested value is one of them. NULL and
                # ``[]`` both fail, which is the same answer the pre-#606 equality
                # gave for an unset column - and it fails only the specialty FILTER,
                # so a doctor who declared none is still found by an unfiltered search.
                #
                # #612 decided the request side stays a SCALAR. The caller asks for
                # one specialty (the route adapter types it as one closed-list
                # ``Specialty``; the homepage chips, the browse facets and the
                # wider-area fallback all speak in one value), which is why the
                # predicate casts a one-element array rather than using the value
                # directly. Widening the request to a list is NOT free: ``literal``
                # would wrap a list inside the array and match nothing, so a caller
                # that sent several values would need this cast and the route adapter
                # widened together - a deliberate change, not a no-op.
                conditions.append(
                    partner_directory_index.c.specialty.op("?|")(
                        cast(literal([specialty]), ARRAY(Text))
                    )
                )
            if query and query.strip():
                conditions.append(partner_profiles.c.practice_name.ilike(f"%{query.strip()}%"))
            if peri_urban_only:
                conditions.append(distance_km <= PERI_URBAN_RADIUS_KM)
            return conditions

        async with self._engine.begin() as connection:
            base = select(
                partner_directory_index.c.partner_id,
                partner_directory_index.c.partner_type,
                partner_directory_index.c.specialty,
                partner_profiles.c.practice_name,
                # #612: the area a patient reads is the locality the doctor
                # DECLARED, which is a column on the profile this query already
                # joins. It used to come from ``partner_service_areas`` - the
                # platform's service-area vocabulary, which every profile resolves
                # into at registration whether or not the doctor lives there - so
                # every result in the launch directory rendered as Daltonganj. The
                # vocabulary, its seeded row and ``partner_profiles.service_area_id``
                # all STAY (AC4): registration still resolves them, and the private
                # doctor profile and the operator views still read them. Only the
                # patient-facing search result stops rendering it, so the join goes
                # with it (ADR-0003: two same-schema tables, so dropping a join is a
                # read change, not a schema one).
                #
                # KNOWN, DELIBERATE: ``get_provider_profile`` is also patient-facing
                # (no login) and still projects the vocabulary default with its
                # Daltonganj fallback, so for now a card reads the doctor's locality
                # and the public profile behind it reads the service area. #613 owns
                # the public profile and is where the two are reconciled; this ticket
                # does not widen it.
                partner_profiles.c.address_locality.label("declared_locality"),
                partner_profiles.c.consultation_fee_paise.label("consultation_fee"),
                distance_km.label("distance_km"),
            ).join(
                partner_profiles,
                partner_profiles.c.id == partner_directory_index.c.partner_id,
            )

            async def _rows(peri_urban_only: bool) -> list[Any]:
                stmt = (
                    base.where(*_conditions(peri_urban_only=peri_urban_only))
                    .order_by(distance_km.asc())
                    # PHASE-6 T2 (#324): the result list is bounded at the
                    # configuration-driven top-N after distance ordering, on
                    # both the in-scope and wider-area fallback paths. A cap,
                    # not a filter/ordering/fallback change (MOD-002).
                    .limit(self._directory_max_results)
                )
                return list((await connection.execute(stmt)).all())

            rows = await _rows(peri_urban_only=True)
            fell_back = len(rows) == 0
            if fell_back:
                rows = await _rows(peri_urban_only=False)

            await write_outbox(
                connection,
                PARTNER_SCHEMA,
                PARTNER_OUTBOX_TABLE,
                directory_search_envelope(
                    patient_id=patient_id,
                    query=query,
                    partner_type=partner_type,
                    specialty=specialty,
                    result_count=len(rows),
                    fell_back=fell_back,
                ),
            )

        view = DirectorySearchView(
            fell_back=fell_back,
            items=[
                DirectoryEntry(
                    partner_id=int(row.partner_id),
                    practice_name=(
                        str(row.practice_name) if row.practice_name is not None else None
                    ),
                    partner_type=str(row.partner_type),
                    specialty=representative_specialty(row.specialty),
                    # #612: a doctor who declared no locality gets NO area, not a
                    # substituted vocabulary row. A null area is already a shape the
                    # frontend card handles (its ``DirectoryEntry.area`` is
                    # ``string | null`` and the card joins non-null meta only), and
                    # inventing a locality the doctor never declared is the same
                    # dishonesty as the Daltonganj default this replaces, just with
                    # a different string. Until the address-section save (#609) has
                    # run, ``address_locality`` is NULL for a freshly registered
                    # doctor - so this is the DEFAULT a new practice renders, and it
                    # is an honest one.
                    area=(
                        str(row.declared_locality) if row.declared_locality is not None else None
                    ),
                    distance_km=float(row.distance_km),
                    verified=True,
                    consultation_fee=_row_fee_paise(row),
                )
                for row in rows
            ],
        )
        if self._directory_ttl_seconds > 0:
            await self._directory_cache.set_cached_search(
                query=query,
                partner_type=partner_type,
                specialty=specialty,
                latitude=latitude,
                longitude=longitude,
                expanded=fell_back,
                raw_items=[entry.model_dump() for entry in view.items],
                fell_back=fell_back,
                ttl_seconds=self._directory_ttl_seconds,
            )
        return view

    async def record_partner_selected(
        self,
        *,
        partner_id: int,
        partner_type: str | None = None,
        source: str | None = None,
    ) -> None:
        """Record one ``partner.selected`` analytics pick into the partner outbox.

        Client-initiated product analytics (FEAT-004 telemetry, PHASE-6 T4
        #326): ``POST /v1/directory/select`` reports that a patient picked a
        provider from the directory, and this facade writes one
        ``partner.selected`` outbox row in its own transaction. The payload
        carries only the pick facts - the picked partner id + partner type and
        the source surface - never a patient identity (the public route is
        anonymous), never PHI or credential data. Deliberately NOT a regulated
        act: the event stays out of ``REGULATED_ACT_TYPES``, mirroring the
        ``directory.search`` analytics seam. The adapter calls only this
        method; there is no business logic in the route.
        """
        async with self._engine.begin() as connection:
            await write_outbox(
                connection,
                PARTNER_SCHEMA,
                PARTNER_OUTBOX_TABLE,
                partner_selected_envelope(
                    partner_id=partner_id,
                    partner_type=partner_type,
                    source=source,
                ),
            )

    async def get_provider_profile(self, partner_id: int) -> ProviderProfileView:
        """Public provider profile (MOD-002, FEAT-005, PHASE-6 T03 #309, #613).

        Returns the profile of an ``[Active]`` partner that has a
        ``directory_index`` entry and valid (verified, unexpired, unrevoked)
        credentials. The four-condition visibility gate matches search exactly
        (ADR-0011 "tick gone = card gone"): not ``[Active]``, no index row, no
        credentials, or any invalid credential raises
        :class:`ProviderProfileNotFoundError` (mapped to a 404) - the profile
        is hidden exactly when search hides the card, so the indicator can
        never drift.

        The payload carries two bands, and the gate above is what separates them
        for a reader. The **verified** band - display name
        (``practice_name``), partner type, the ``verified`` indicator (always
        True for a reachable profile) and the per-credential type + status label
        + expiry date - is what the platform checked. The **declared** band -
        ``clinic_name``, the ``specialties`` SELECTION and the singular
        ``specialty`` label derived from it, ``languages``, ``consulting_days``,
        ``consulting_hours``, ``about``, ``experience_years``, the structured
        address parts and the ``area`` label - is what the doctor wrote, and
        widening it to those does not widen ``verified``: reaching the profile
        still proves exactly the four gate conditions and not one declared field
        among them.

        Never exposed, before or after the widening: artifact refs (photo and
        credential bytes stay in private object storage, ADR-0020), the
        practice's coordinates, emails, phones, the partner's identity id,
        notification preferences, and PHI.
        """
        async with self._engine.begin() as connection:
            row = (
                await connection.execute(
                    select(
                        partner_directory_index.c.partner_id,
                        partner_directory_index.c.partner_type,
                        partner_directory_index.c.specialty,
                        partner_profiles.c.practice_name,
                        partner_profiles.c.consultation_fee_paise.label("consultation_fee"),
                        # The declared band (#613), all off the PROFILE ROW. The
                        # profile row is the source of truth for every one of
                        # these - it is what the four section writes land on -
                        # so reading them here cannot disagree with what the
                        # doctor last saved the way a directory-entry copy could.
                        partner_profiles.c.clinic_name,
                        partner_profiles.c.specialties,
                        partner_profiles.c.languages,
                        partner_profiles.c.consulting_days,
                        partner_profiles.c.consulting_hours,
                        partner_profiles.c.about,
                        partner_profiles.c.experience_years,
                        # The structured address parts rather than the
                        # ``practice_address`` display string, which is a
                        # denormalised registration-era projection of these
                        # (#606) and stays private to the console and the
                        # operator queue.
                        partner_profiles.c.address_line,
                        partner_profiles.c.address_landmark,
                        partner_profiles.c.address_locality,
                        partner_profiles.c.address_city,
                        partner_profiles.c.address_pin,
                    )
                    .join(
                        partner_profiles,
                        partner_profiles.c.id == partner_directory_index.c.partner_id,
                    )
                    .where(
                        partner_directory_index.c.partner_id == partner_id,
                        self._credential_validity.provider_visible(
                            partner_directory_index.c.partner_id
                        ),
                    )
                )
            ).first()
            if row is None:
                raise ProviderProfileNotFoundError(partner_id)

            credential_rows = (
                await connection.execute(
                    select(
                        partner_credentials.c.credential_type,
                        partner_credentials.c.expires_at,
                    )
                    .where(
                        partner_credentials.c.profile_id == partner_id,
                        # #623 (B3): the label below is the literal "verified",
                        # so this query has to make it true rather than assume it.
                        # The reachability gate that got us here does NOT cover
                        # every row: `has_invalid_credential` is scoped to
                        # `verified IS TRUE`, which is what keeps a pending
                        # re-verification round from de-listing an [Active]
                        # partner (ADR-0011's grace window). A partner mid-round is
                        # therefore reachable WITH their pending rows, and those
                        # rows were being labelled "verified" on a patient-facing
                        # profile - the one field that can drive the trust cue the
                        # whole band exists to carry.
                        #
                        # The same scoping the gate uses is applied here, so the
                        # set that survives is exactly the set the gate called
                        # valid. Revoked and expired approved-round rows cannot
                        # reach this query at all (the gate already excluded the
                        # partner), and pending rows are now excluded rather than
                        # mislabelled - the same choice `has_invalid_credential`
                        # makes, so the two agree by construction.
                        partner_credentials.c.verified.is_(True),
                        partner_credentials.c.revoked_at.is_(None),
                        or_(
                            partner_credentials.c.expires_at.is_(None),
                            partner_credentials.c.expires_at > func.now(),
                        ),
                    )
                    .order_by(partner_credentials.c.credential_type)
                )
            ).all()

        # The three selections go through the closed vocabularies that own them
        # (#602), not through a copy of a list restated here: a value outside
        # ``Specialty`` / ``ConsultLanguage`` / ``ConsultingDay`` cannot reach a
        # patient even off a hand-repaired row.
        specialties = known_selection(row.specialties, Specialty)
        return ProviderProfileView(
            partner_id=int(row.partner_id),
            practice_name=(str(row.practice_name) if row.practice_name is not None else None),
            partner_type=str(row.partner_type),
            # The representative label is the FIRST member of the same filtered
            # selection that ``specialties`` publishes, so one payload cannot
            # report a label the list does not contain. That is also why it reads
            # the profile row rather than the directory entry's copy (#606 kept
            # both in step; the profile row is the one that is written).
            specialty=(specialties[0] if specialties else None),
            # The DECLARED locality, which is what search now reads for the
            # card (#612), rather than the ``partner_service_areas`` vocabulary
            # with its launch-default fallback - #612 named this the half it
            # left, and a patient who compares the card with the profile behind
            # it was reading two different places. Undeclared locality stays
            # ``None``, the honest answer and the DEFAULT for a practice whose
            # address section has not been saved yet.
            area=row.address_locality,
            # Reachability already proved all four gate conditions, so this is a
            # derivation rather than a stored flag - and it stays that narrow: it
            # covers the credential band, never a declared field.
            verified=True,
            consultation_fee=_row_fee_paise(row),
            specialties=specialties,
            languages=known_selection(row.languages, ConsultLanguage),
            consulting_days=known_selection(row.consulting_days, ConsultingDay),
            clinic_name=(str(row.clinic_name) if row.clinic_name is not None else None),
            consulting_hours=row.consulting_hours,
            about=row.about,
            experience_years=(
                int(row.experience_years) if row.experience_years is not None else None
            ),
            address_line=row.address_line,
            landmark=row.address_landmark,
            locality=row.address_locality,
            city=row.address_city,
            pin_code=row.address_pin,
            credentials=[
                ProviderCredential(
                    credential_type=str(c.credential_type),
                    status="verified",
                    expires_at=c.expires_at,
                )
                for c in credential_rows
            ],
        )

    async def _cached_search_view(
        self,
        *,
        query: str | None,
        partner_type: str | None,
        specialty: str | None,
        latitude: float,
        longitude: float,
        patient_id: int | None,
    ) -> DirectorySearchView | None:
        """Try the Redis accelerator for one search, re-deriving validity first.

        PHASE-6 T02b (#314): the cache is an accelerator ONLY, never a
        correctness surface (ADR-0011 lazy correctness). On a hit we re-derive
        the visibility tick for the cached partner ids from the recorded dates
        (``is_active``, ``Active`` status, verified/unexpired/unrevoked
        credentials); if ANY cached partner no longer passes - deactivated,
        revoked, expired, or unverified since the row was written - the hit is
        rejected and the caller recomputes fresh SQL, so a stale row for a
        deactivated/expired partner never surfaces. On a clean hit the cached
        items are served as-is (their geo/distance already match the cached
        key) and the ``directory.search`` analytics event still fires (one per
        search - a cached search is still a real search).

        Returns ``None`` when caching is disabled, the cache missed for both
        expanded variants, or the cached ids no longer all pass validity.
        """
        if self._directory_ttl_seconds <= 0:
            return None
        cached = await self._directory_cache.get_cached_search(
            query=query,
            partner_type=partner_type,
            specialty=specialty,
            latitude=latitude,
            longitude=longitude,
            expanded=False,
        )
        raw_items: list[dict[str, Any]]
        fell_back: bool
        if cached is not None:
            raw_items, fell_back = cached
        else:
            cached = await self._directory_cache.get_cached_search(
                query=query,
                partner_type=partner_type,
                specialty=specialty,
                latitude=latitude,
                longitude=longitude,
                expanded=True,
            )
            if cached is None:
                return None
            raw_items, fell_back = cached

        partner_ids = sorted({int(item["partner_id"]) for item in raw_items})
        async with self._engine.begin() as connection:
            if not await self._cached_ids_still_valid(connection, partner_ids):
                return None
            await write_outbox(
                connection,
                PARTNER_SCHEMA,
                PARTNER_OUTBOX_TABLE,
                directory_search_envelope(
                    patient_id=patient_id,
                    query=query,
                    partner_type=partner_type,
                    specialty=specialty,
                    result_count=len(raw_items),
                    fell_back=fell_back,
                ),
            )
        return DirectorySearchView(
            fell_back=fell_back,
            items=[DirectoryEntry(**item) for item in raw_items],
        )

    async def _cached_ids_still_valid(
        self, connection: AsyncConnection, partner_ids: list[int]
    ) -> bool:
        """Whether every cached partner id still passes the visibility tick.

        The one re-derivation the cache hit is allowed to skip is the distance
        scan - the validity of each id is ALWAYS re-checked against the recorded
        dates (ADR-0011), so a cached row can never surface a deactivated or
        expired partner.
        """
        if not partner_ids:
            return True
        valid_count = int(
            (
                await connection.execute(
                    select(func.count(partner_directory_index.c.partner_id))
                    .join(
                        partner_profiles,
                        partner_profiles.c.id == partner_directory_index.c.partner_id,
                    )
                    .where(
                        partner_directory_index.c.partner_id.in_(partner_ids),
                        self._credential_validity.provider_visible(
                            partner_directory_index.c.partner_id
                        ),
                    )
                )
            ).scalar_one()
        )
        return valid_count == len(partner_ids)
