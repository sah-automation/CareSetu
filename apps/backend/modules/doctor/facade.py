"""MOD-012 doctor console: facade-only composition seam (ADR-0003, #539).

The doctor console breaks the "one owning module" mold on purpose: it is the
reading order for a doctor's current/past patients, composed entirely from
other modules' legal facade seams. It owns no schema and publishes nothing -
a fan-out list, not a relation. Cross-module imports here are restricted to
``modules.<module>.facade`` (scripts/check_module_boundaries); wiring lives in
the composition root (``app/main.py``).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, TypeVar

from modules.doctor.doctor_models import (
    CaseWorkspaceLink,
    ContactSection,
    DoctorCaseRow,
    DoctorCasesListView,
    DoctorPatientDetailView,
    DoctorPatientRow,
    PatientsListView,
)
from modules.doctor.domain.exceptions import DoctorConsoleAccessDeniedError
from modules.health.facade import RecordAccessDeniedError as RecordAccessDeniedError
from modules.iam.facade import PhotoContent
from modules.partner.facade import DoctorProfileNotAllowedError, PartnerNotFoundError

if TYPE_CHECKING:
    from modules.care.facade import CaseConsoleFacade, CaseDetailView
    from modules.consent.facade import ConsentFacade, CounterpartyGrantView
    from modules.health.facade import HealthBackgroundView, HealthFacade, RecordTimeline
    from modules.iam.facade import IamFacade, PatientProfile
    from modules.partner.facade import PartnerFacade

logger = logging.getLogger(__name__)

# The counterparty type the Patients list derives grants from; matches the
# consent vocabulary ("doctor") that the pick flow records and that the
# health-background auto-grant targets (#534).
_COUNTERPARTY_TYPE_DOCTOR = "doctor"

# ADR-0019 bucket vocabulary exposed on the wire.
_BUCKET_CURRENT = "current"
_BUCKET_PAST = "past"

# The care case stage that ends a relationship: a patient with no live grant
# and nothing but closed cases is "past" (ADR-0019). Any other stage keeps
# the relationship current.
_CASE_STAGE_CLOSED = "closed"

# The consent scopes the detail surface gates its sections on (the consent
# vocabulary; ``full_record`` subsumes every specific scope when gated).
_RECORD_SCOPE_FULL = "full_record"
_CONSENT_SCOPE_CONSULTATIONS = "consultations"

# The scopes that authorize the detail's contact/photo block: the identity
# contact a doctor needs to serve a consultation, and nothing narrower
# (security-phii-standards §2 "egress carries the minimum context" - a
# ``lab_results`` or ``health_background`` grant is not a licence to read
# ``gender``/``area``/``emergency_contact``).
_CONTACT_SCOPES = frozenset({_CONSENT_SCOPE_CONSULTATIONS, _RECORD_SCOPE_FULL})

# The access-history marker for the detail's contact/photo block (MOD-012,
# ADR-0019, #540). The block is gated on a record scope rather than "any
# grant", but the ledger marker names the surface instead, mirroring the list
# marker the health facade owns for its own surface.
_DETAIL_SCOPE_MARKER = "doctor_patient_detail"

# The access-history marker for the console's open-cases list (MOD-012, #646) -
# a third surface marker beside the two the health facade already carries, so
# the trust view can answer *which* console list a patient was read through.
_CASES_SCOPE_MARKER = "doctor_cases_list"

# Payload type of a consented record read funnelled through
# ``_consent_read_or_none``; keeps the fail-closed helper sound under --strict.
_T = TypeVar("_T")


def _bucket_for(has_live_grant: bool, patient_cases: list[CaseDetailView]) -> str:
    """Apply the ADR-0019 bucketing rule to one patient's derived inputs.

    Current: a live standing grant OR any non-closed care case exists. Past:
    neither - only closed cases remain, so the relationship has ended.
    """
    if has_live_grant:
        return _BUCKET_CURRENT
    if any(case.stage != _CASE_STAGE_CLOSED for case in patient_cases):
        return _BUCKET_CURRENT
    return _BUCKET_PAST


def _filter_by_name(rows: list[DoctorPatientRow], search: str) -> list[DoctorPatientRow]:
    """Keep the rows whose name contains the query, case-insensitively.

    Nameless rows never match a search - there is no name to compare - so a
    filtered list only ever surfaces certifiably matching patients.
    """
    needle = search.strip().lower()
    if not needle:
        return rows
    return [row for row in rows if row.name is not None and needle in row.name.lower()]


def _grants_allow_contact(grants: list[CounterpartyGrantView]) -> bool:
    """Whether any live grant authorizes the detail's contact/photo block.

    Fail-closed on an empty list and on a scope outside the module's
    vocabulary: only ``consultations`` (and the subsuming ``full_record``)
    carries identity contact, so a ``lab_results`` or ``health_background``
    grant answers the whole block locked rather than leaking the demographic
    and emergency-contact fields (security-phii-standards §2).
    """
    return any(grant.record_scope in _CONTACT_SCOPES for grant in grants)


class DoctorConsoleFacade:
    """Compose consent/care/iam/health reads into the doctor Patients list.

    The facade seams over the owning modules instead of owning relations:
    Current/Past derives from live grants and assigned care cases alone, so a
    consent revocation or a closed case moves a patient out of "current"
    automatically - there is nothing stored to migrate and nothing retained
    after the relationship ends (ADR-0019).

    Every read re-checks the caller's role here, not only at the edge
    (api-standards §6, security-phii-standards §3): the routes' ``require_partner``
    guard is a convenience refusal, while ``_require_active_doctor`` is the
    boundary that answers "is this id still an active doctor" per read.
    """

    def __init__(
        self,
        *,
        consent_facade: ConsentFacade,
        care_facade: CaseConsoleFacade,
        iam_facade: IamFacade,
        health_facade: HealthFacade,
        partner_facade: PartnerFacade,
    ) -> None:
        self._consent_facade = consent_facade
        self._care_facade = care_facade
        self._iam_facade = iam_facade
        self._health_facade = health_facade
        # The facade-side re-check of the edge's role decision: the console
        # never reads the partner schema itself (module isolation), it asks
        # MOD-002 whether the id it was handed is still an active doctor.
        self._partner_facade = partner_facade

    async def _require_active_doctor(self, *, doctor_id: int) -> None:
        """Re-check in the facade that ``doctor_id`` is an active doctor.

        api-standards §6 and security-phii-standards §3: the edge guard is
        convenience, the facade is the boundary. The decision itself belongs to
        MOD-002 (it owns ``partner_profiles``), so this asks its
        ``require_active_doctor`` seam - the same rule, and the same
        ``DoctorProfileNotAllowedError``, every doctor-profile read runs - and
        translates a refusal into MOD-012's own
        ``DoctorConsoleAccessDeniedError`` so the console's envelope stays
        bound to the module that decided it (coding-standards §3: one error
        family per module) instead of leaking MOD-002's vocabulary to a client
        that only ever called a doctor surface.

        Fail-closed: a partner who is not a doctor, is not ``Active``, or whose
        profile is gone is refused before any consent lookup, profile read, or
        ledger write happens.
        """
        try:
            await self._partner_facade.require_active_doctor(doctor_id)
        except (DoctorProfileNotAllowedError, PartnerNotFoundError) as exc:
            raise DoctorConsoleAccessDeniedError(
                "an active doctor partner profile is required for the console"
            ) from exc

    async def list_doctor_patients(
        self,
        *,
        doctor_id: int,
        search: str | None = None,
        page: int = 1,
        per_page: int = 25,
    ) -> PatientsListView:
        """Return one page of the doctor's derived Patients list (US-13, #539, ADR-0019).

        Composition order:
        - ``require_active_doctor`` (partner) re-checks that the edge-supplied
          id is still an active doctor before anything is read (api-standards
          §6);
        - ``list_counterparty_grants`` (consent reverse lookup) gives the live
          standing grants this doctor holds across patients; their union with
          the patients of ``list_doctor_all_cases`` is the row set, and the
          ADR-0019 bucket rule splits it into current/past.
        - ``get_patient_profile`` (iam) enriches each row's name/age/photo
          presence, degrade-safe: a failed or missing profile yields ``None``
          fields, never a failed list (the review-queue enrichment convention);
        - ``log_doctor_patient_view`` (health) records each served row in the
          access-history ledger plus the ``record.accessed`` outbox envelope -
          MOD-012 owns no ledger, so the record access history is the "every
          read attempt" single source of truth. Only the rows actually in the
          returned page are logged: a search that matches nothing reveals no
          row, so it logs nothing (api-standards §4 bounds the ledger cost at
          the page size);
        - ``record_egress_disclosure`` (consent) pins the same served rows to
          the authorizing live grant, mirroring the detail read's disclosure
          (US-18, #539): a row is PHI egress, so serving it without an egress
          row would leave the patient's egress log short of what the doctor
          actually received. The grant carries no entry ids (the row is not
          entry-keyed), so ``disclosed_entry_ids`` stays empty.
        """
        await self._require_active_doctor(doctor_id=doctor_id)
        grants = await self._live_grants(doctor_id=doctor_id)
        cases = await self._care_facade.list_doctor_all_cases(doctor_id=doctor_id)

        grants_by_patient: dict[int, list[CounterpartyGrantView]] = {}
        for grant in grants:
            grants_by_patient.setdefault(grant.patient_id, []).append(grant)

        cases_by_patient: dict[int, list[CaseDetailView]] = {}
        for case in cases:
            cases_by_patient.setdefault(case.patient_id, []).append(case)

        patient_ids = sorted(set(grants_by_patient) | set(cases_by_patient))
        profiles = await self._resolve_patient_profiles(patient_ids)

        rows: list[DoctorPatientRow] = []
        for patient_id in patient_ids:
            patient_grants = grants_by_patient.get(patient_id, [])
            patient_cases = cases_by_patient.get(patient_id, [])
            profile = profiles.get(patient_id)
            latest_case = max(patient_cases, key=lambda case: case.updated_at, default=None)
            rows.append(
                DoctorPatientRow(
                    patient_id=patient_id,
                    name=profile.name if profile is not None else None,
                    age=profile.age if profile is not None else None,
                    has_photo=bool(profile is not None and profile.photo_ref),
                    bucket=_bucket_for(bool(patient_grants), patient_cases),
                    granted_scopes=list(
                        dict.fromkeys(grant.record_scope for grant in patient_grants)
                    ),
                    latest_case_stage=latest_case.stage if latest_case is not None else None,
                )
            )

        if search:
            rows = _filter_by_name(rows, search)

        rows.sort(key=lambda row: (row.name or "", row.patient_id))
        total = len(rows)
        start = (page - 1) * per_page
        page_rows = rows[start : start + per_page]

        for row in page_rows:
            await self._health_facade.log_doctor_patient_view(
                patient_id=row.patient_id, doctor_id=doctor_id
            )
            # A row the doctor reaches through a care case alone (Past, or
            # Current-by-case) carries no live standing grant, so there is no
            # consent lineage to disclose the egress against: fail closed and
            # leave the egress log untouched rather than citing a consent the
            # patient never granted. The access-history row above still
            # records that the row was served.
            patient_grants = grants_by_patient.get(row.patient_id, [])
            if patient_grants:
                await self._disclose_against_grant(patient_grants, row.patient_id, doctor_id)

        return PatientsListView(items=page_rows, total=total)

    async def _live_grants(
        self, *, doctor_id: int, patient_id: int | None = None
    ) -> list[CounterpartyGrantView]:
        """The doctor's live standing grants, optionally narrowed to one patient.

        The single consent reverse lookup every console read funnels through
        (ADR-0019): ``list_counterparty_grants`` is keyed by counterparty, so
        the per-patient reads filter the same answer instead of issuing a
        second lookup. Pending/revoked lineages never appear - only a standing
        grant counts.
        """
        grants = await self._consent_facade.list_counterparty_grants(
            counterparty_type=_COUNTERPARTY_TYPE_DOCTOR,
            counterparty_id=str(doctor_id),
        )
        if patient_id is None:
            return grants
        return [grant for grant in grants if grant.patient_id == patient_id]

    async def _resolve_patient_profiles(self, patient_ids: list[int]) -> dict[int, PatientProfile]:
        """Resolve identity profiles for the row set, degrading wholesale on failure.

        Cosmetic card enrichment (#539, review-queue convention #489): a
        failed profile resolution must never take the whole list down, so the
        run degrades to anonymous rows with a warning logged and no patient
        ids or PHI in the log line (error-handling-observability §2).
        """
        profiles: dict[int, PatientProfile] = {}
        if not patient_ids:
            return profiles
        try:
            for patient_id in patient_ids:
                profile = await self._iam_facade.get_patient_profile(patient_id)
                if profile is not None:
                    profiles[patient_id] = profile
        except Exception:
            # No ``exc_info``: a traceback frame or exception message can
            # carry the patient id (error-handling-observability §2, the
            # docstring contract above).
            logger.warning(
                "doctor-console profile resolution failed; degrading to anonymous rows",
            )
            profiles = {}
        return profiles

    async def list_doctor_cases(self, *, doctor_id: int) -> DoctorCasesListView:
        """Return the doctor's open care cases as displayable rows (#646).

        The cases list used to answer ``Case #<id>``, so a doctor with several
        open cases could not tell them apart without opening each one. This
        projection adds the patient's name, age, and photo presence to the case
        facts the console already reads.

        Composition order matches ``list_doctor_patients`` exactly:
        - ``require_active_doctor`` (partner) re-checks the edge-supplied id
          before anything else - the edge guard is convenience, this is the
          boundary (api-standards §6);
        - ``list_doctor_cases`` (care) supplies the doctor's open cases.
          Deliberately the care module's *own* open-cases read rather than its
          all-cases feed re-filtered here: the console list and the existing
          ``GET /v1/care/cases`` route must see the same case set, and a second
          copy of MOD-006's non-closed filter is exactly how two reads of the
          same data would come to disagree. ``MOD-006`` still cannot read the
          identity schema, so the enrichment below still has to happen here at
          the seam that composes care and identity reads - the care-scoped
          reads keep their shape and their consumers untouched;
        - ``_resolve_patient_profiles`` (iam) supplies name/age/photo presence -
          the *same* degrade-safe resolver the Patients list uses, not a second
          one, so one failed identity read degrades this batch to anonymous
          rows with a warning and never fails the list;
        - ``log_doctor_patient_view`` (health) records every served row under
          this surface's own marker, and ``record_egress_disclosure``
          (consent) pins each granted row to the authorizing live grant -
          serving a case row reveals a patient's existence to their doctor, so
          it belongs in both ledgers exactly as a Patients row does (ADR-0019
          D3 discipline, extended to this second read surface).

        Rows are ordered ``created_at`` ascending with a ``case_id`` tie-break,
        so the order is this read's own and not the feed's. The read is
        unpaginated and takes no query parameters - which also means, unlike the
        paginated Patients list, nothing bounds this read's per-row ledger
        writes but the size of the doctor's open caseload (ADR-0019 D3).
        """
        await self._require_active_doctor(doctor_id=doctor_id)
        grants = await self._live_grants(doctor_id=doctor_id)
        open_cases = await self._care_facade.list_doctor_cases(doctor_id=doctor_id)

        grants_by_patient: dict[int, list[CounterpartyGrantView]] = {}
        for grant in grants:
            grants_by_patient.setdefault(grant.patient_id, []).append(grant)

        profiles = await self._resolve_patient_profiles(
            sorted({case.patient_id for case in open_cases})
        )

        rows: list[DoctorCaseRow] = []
        for case in open_cases:
            profile = profiles.get(case.patient_id)
            rows.append(
                DoctorCaseRow(
                    case_id=case.case_id,
                    stage=case.stage,
                    forced_review=case.forced_review,
                    created_at=case.created_at,
                    updated_at=case.updated_at,
                    patient_id=case.patient_id,
                    patient_name=profile.name if profile is not None else None,
                    patient_age=profile.age if profile is not None else None,
                    has_photo=bool(profile is not None and profile.photo_ref),
                )
            )
        rows.sort(key=lambda row: (row.created_at, row.case_id))

        for row in rows:
            await self._health_facade.log_doctor_patient_view(
                patient_id=row.patient_id,
                doctor_id=doctor_id,
                scope=_CASES_SCOPE_MARKER,
            )
            # Same fail-closed rule as the Patients list: a case row the doctor
            # reaches without any live standing grant has no consent lineage to
            # disclose against, so no egress row is fabricated for it. The
            # access-history row above still records that the row was served.
            patient_grants = grants_by_patient.get(row.patient_id, [])
            if patient_grants:
                await self._disclose_against_grant(patient_grants, row.patient_id, doctor_id)

        return DoctorCasesListView(items=rows)

    async def get_doctor_patient_detail(
        self, *, doctor_id: int, patient_id: int
    ) -> DoctorPatientDetailView:
        """Section-gated detail read of one patient (US-15..18, ADR-0019, #540).

        Composition order matches the Patients list derivation (active-doctor
        re-check, then live grants + assigned care cases), then gates each block
        on the patient's live grants:
        - ``contact`` under the ``consultations`` scope or the subsuming
          ``full_record`` - the scopes that actually authorize identity
          contact, never a narrower grant (security-phii-standards §2 minimum
          context). It is enriched degrade-safe from the iam profile and
          access-logged (the detail surface marker) plus egress-disclosed
          against the most permissive live grant (prefer ``full_record``, else
          the earliest consent id);
        - ``consultation_history`` only under the ``consultations`` scope via
          ``read_consented_history``, whose own two-ledger discipline applies;
          a denial is caught and the section answers ``None`` (locked - the
          denied row is already in the ledger).
        - ``health_background`` only under ``health_background`` via
          ``read_consented_health_background``, same fail-closed shape.
        - ``case_workspace`` is the doctor's own most recently updated case
          for the patient - present whenever one exists, never consent-gated.
        A patient with no live grant at all answers every section locked and
        the workspace, leaking nothing sensitive.
        """
        await self._require_active_doctor(doctor_id=doctor_id)
        own_grants = await self._live_grants(doctor_id=doctor_id, patient_id=patient_id)
        has_live_grant = bool(own_grants)

        cases = await self._care_facade.list_doctor_all_cases(doctor_id=doctor_id)
        patient_cases = [case for case in cases if case.patient_id == patient_id]
        latest_case = max(patient_cases, key=lambda case: case.updated_at, default=None)

        contact = None
        if _grants_allow_contact(own_grants):
            profile = await self._resolve_patient_profile(patient_id)
            contact = ContactSection(
                name=profile.name if profile is not None else None,
                age=profile.age if profile is not None else None,
                gender=profile.gender if profile is not None else None,
                area=profile.area if profile is not None else None,
                emergency_contact=profile.emergency_contact if profile is not None else None,
                has_photo=bool(profile is not None and profile.photo_ref),
            )
            await self._health_facade.log_doctor_patient_view(
                patient_id=patient_id,
                doctor_id=doctor_id,
                scope=_DETAIL_SCOPE_MARKER,
            )
            await self._disclose_against_grant(own_grants, patient_id, doctor_id)

        consultation_history = await self._read_granted_consultation_history(patient_id, doctor_id)
        health_background = await self._read_granted_health_background(patient_id, doctor_id)

        return DoctorPatientDetailView(
            patient_id=patient_id,
            bucket=_bucket_for(has_live_grant, patient_cases),
            granted_scopes=list(dict.fromkeys(grant.record_scope for grant in own_grants)),
            latest_case_stage=latest_case.stage if latest_case is not None else None,
            case_workspace=(
                CaseWorkspaceLink(case_id=latest_case.case_id, stage=latest_case.stage)
                if latest_case is not None
                else None
            ),
            contact=contact,
            consultation_history=consultation_history,
            health_background=health_background,
        )

    async def get_doctor_patient_photo(
        self, *, doctor_id: int, patient_id: int
    ) -> PhotoContent | None:
        """The consent-gated photo stream read for one doctor-patient pair (US-16, #540).

        Fail-closed: without a live grant the read raises MOD-012's own
        ``DoctorConsoleAccessDeniedError`` (the route answers 403) and not a
        byte is returned. The refusal is still AUDITED first: a consent denial
        is a Security-class event (error-handling-observability §1) and KPI-006
        promises 100% of read attempts, not 100% of served reads, so the
        attempt lands in the health module's access-history ledger
        (``outcome=denied``, the detail surface marker) and the
        ``record.denied`` outbox envelope BEFORE the refusal leaves the facade.
        A doctor with no relationship to the patient at all is ledgered on the
        same path - the absence of a grant is the reason - so the patient's
        trust view can answer who asked.

        Order matters (error-handling-observability §1): the active-doctor
        re-check runs first (a refused role never reaches the consent lookup),
        then the profile is read as a *presence probe* - it carries no photo
        bytes - so a patient with no photo on file still answers ``None`` with
        no ledger row (the route's 404). Only once a photo is known to exist is
        the read access-logged (the detail surface marker) and egress-disclosed
        against the most permissive live grant, and only then are the stored
        bytes fetched: PHI is never materialized ahead of its ledger row.
        """
        await self._require_active_doctor(doctor_id=doctor_id)
        own_grants = await self._live_grants(doctor_id=doctor_id, patient_id=patient_id)
        if not own_grants:
            reason = "no live consent grant for this patient"
            # Committed before the raise, never rolled back with it.
            await self._health_facade.log_doctor_patient_view_denied(
                patient_id=patient_id,
                doctor_id=doctor_id,
                denial_reason=reason,
                scope=_DETAIL_SCOPE_MARKER,
            )
            raise DoctorConsoleAccessDeniedError(reason)

        profile = await self._resolve_patient_profile(patient_id)
        if profile is None or not profile.photo_ref:
            return None

        await self._health_facade.log_doctor_patient_view(
            patient_id=patient_id,
            doctor_id=doctor_id,
            scope=_DETAIL_SCOPE_MARKER,
        )
        await self._disclose_against_grant(own_grants, patient_id, doctor_id)
        return await self._iam_facade.get_patient_photo(identity_id=patient_id)

    async def _resolve_patient_profile(self, patient_id: int) -> PatientProfile | None:
        """Resolve one patient's profile, degrade-safe (review-queue convention #489).

        Two callers, one resolution: the detail's contact block enriches itself
        from it, and the photo read uses it as a presence probe. A failed
        profile must fail neither - the contact block degrades to empty fields
        and the photo read answers "no photo on file", both with a warning
        logged and no patient id or PHI in the log line
        (error-handling-observability §2).
        """
        try:
            return await self._iam_facade.get_patient_profile(patient_id)
        except Exception:
            # No ``exc_info``: the docstring contract forbids a patient id or
            # PHI in the log line, and an exception message can carry either
            # (error-handling-observability §2).
            logger.warning(
                "doctor-console profile resolution failed; degrading to empty contact",
            )
            return None

    def _authorizing_grant(self, grants: list[CounterpartyGrantView]) -> CounterpartyGrantView:
        """The live grant the contact/photo disclosure is cited against.

        ``full_record`` is the most permissive standing scope (it subsumes
        every specific scope), so the disclosure prefers it; otherwise the
        earliest live grant (lowest consent id - the reverse lookup already
        returns rows ordered by patient then id) is the deterministic
        authorizing one the section is disclosed under.
        """
        return next(
            (grant for grant in grants if grant.record_scope == _RECORD_SCOPE_FULL),
            min(grants, key=lambda grant: grant.consent_id),
        )

    async def _disclose_against_grant(
        self,
        grants: list[CounterpartyGrantView],
        patient_id: int,
        doctor_id: int,
    ) -> None:
        """Egress-disclose the contact/photo block against the authorizing grant.

        The block is not entry-keyed, so ``disclosed_entry_ids`` stays empty;
        the egress row still pins patient + consent id + version + scope to
        the consent module's own transaction (FIX-7, ADR-0003).
        """
        grant = self._authorizing_grant(grants)
        await self._consent_facade.record_egress_disclosure(
            patient_id=patient_id,
            consent_id=grant.consent_id,
            version=grant.version,
            counterparty_type=_COUNTERPARTY_TYPE_DOCTOR,
            counterparty_id=str(doctor_id),
            record_scope=grant.record_scope,
            disclosed_entry_ids=[],
        )

    async def _read_granted_consultation_history(
        self, patient_id: int, doctor_id: int
    ) -> RecordTimeline | None:
        """Read the consultation-history block, fail-closed to a locked section.

        ``read_consented_history`` already writes its own ledger rows for the
        allowed and the denied attempt; a denial becomes a ``None`` section
        (the client renders "not shared") instead of propagating an error.
        """
        return await self._consent_read_or_none(
            patient_id=patient_id,
            doctor_id=doctor_id,
            reader=lambda: self._health_facade.read_consented_history(
                patient_id=patient_id,
                scope=_CONSENT_SCOPE_CONSULTATIONS,
                counterparty_type=_COUNTERPARTY_TYPE_DOCTOR,
                counterparty_id=doctor_id,
            ),
        )

    async def _read_granted_health_background(
        self, patient_id: int, doctor_id: int
    ) -> HealthBackgroundView | None:
        """Read the health-background block, fail-closed to a locked section.

        Same two-ledger and raise-after-commit discipline as
        ``read_consented_history``; a denial answers ``None`` (locked), never
        an error (ADR-0019, US-16).
        """
        return await self._consent_read_or_none(
            patient_id=patient_id,
            doctor_id=doctor_id,
            reader=lambda: self._health_facade.read_consented_health_background(
                patient_id=patient_id,
                counterparty_type=_COUNTERPARTY_TYPE_DOCTOR,
                counterparty_id=doctor_id,
            ),
        )

    async def _consent_read_or_none(
        self,
        *,
        patient_id: int,
        doctor_id: int,
        reader: Callable[[], Awaitable[_T]],
    ) -> _T | None:
        """Run a consented record read, converting a denial into ``None``.

        The health facade already ledgers both outcomes; the detail surface
        maps the fail-closed ``RecordAccessDeniedError`` to a locked ``None``
        section rather than surfacing an error (ADR-0019, US-16).
        """
        try:
            return await reader()
        except RecordAccessDeniedError:
            return None
