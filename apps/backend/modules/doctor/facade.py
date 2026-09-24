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
    DoctorPatientDetailView,
    DoctorPatientRow,
    PatientsListView,
)
from modules.health.facade import RecordAccessDeniedError as RecordAccessDeniedError
from modules.iam.facade import PhotoContent

if TYPE_CHECKING:
    from modules.care.facade import CaseConsoleFacade, CaseDetailView
    from modules.consent.facade import ConsentFacade, CounterpartyGrantView
    from modules.health.facade import HealthBackgroundView, HealthFacade, RecordTimeline
    from modules.iam.facade import IamFacade, PatientProfile

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

# The access-history marker for the detail's contact/photo block (MOD-012,
# ADR-0019, #540). The block is gated on ANY live grant - it maps to no single
# record scope - so the ledger marker names the surface instead, mirroring the
# list marker the health facade owns for its own surface.
_DETAIL_SCOPE_MARKER = "doctor_patient_detail"

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


class DoctorConsoleFacade:
    """Compose consent/care/iam/health reads into the doctor Patients list.

    The facade seams over the owning modules instead of owning relations:
    Current/Past derives from live grants and assigned care cases alone, so a
    consent revocation or a closed case moves a patient out of "current"
    automatically - there is nothing stored to migrate and nothing retained
    after the relationship ends (ADR-0019).
    """

    def __init__(
        self,
        *,
        consent_facade: ConsentFacade,
        care_facade: CaseConsoleFacade,
        iam_facade: IamFacade,
        health_facade: HealthFacade,
    ) -> None:
        self._consent_facade = consent_facade
        self._care_facade = care_facade
        self._iam_facade = iam_facade
        self._health_facade = health_facade

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
        - ``list_counterparty_grants`` (consent reverse lookup) gives the live
          standing grants this doctor holds across patients; their union with
          the patients of ``list_doctor_all_cases`` is the row set, and the
          ADR-0019 bucket rule splits it into current/past.
        - ``get_patient_profile`` (iam) enriches each row's name/age/photo,
          degrade-safe: a failed or missing profile yields ``None`` fields,
          never a failed list (the review-queue enrichment convention);
        - ``log_doctor_patient_view`` (health) records each served row in the
          access-history ledger plus the ``record.accessed`` outbox envelope -
          MOD-012 owns no ledger, so the record access history is the "every
          read attempt" single source of truth. Only the rows actually in the
          returned page are logged: a search that matches nothing reveals no
          row, so it logs nothing (api-standards §4 bounds the ledger cost at
          the page size).
        """
        grants = await self._consent_facade.list_counterparty_grants(
            counterparty_type=_COUNTERPARTY_TYPE_DOCTOR,
            counterparty_id=str(doctor_id),
        )
        cases = await self._care_facade.list_doctor_all_cases(doctor_id=doctor_id)

        live_patients: set[int] = set()
        scopes_by_patient: dict[int, list[str]] = {}
        for grant in grants:
            live_patients.add(grant.patient_id)
            scopes_by_patient.setdefault(grant.patient_id, []).append(grant.record_scope)

        cases_by_patient: dict[int, list[CaseDetailView]] = {}
        for case in cases:
            cases_by_patient.setdefault(case.patient_id, []).append(case)

        patient_ids = sorted(live_patients | set(cases_by_patient))
        profiles = await self._resolve_patient_profiles(patient_ids)

        rows: list[DoctorPatientRow] = []
        for patient_id in patient_ids:
            scopes = list(dict.fromkeys(scopes_by_patient.get(patient_id, [])))
            patient_cases = cases_by_patient.get(patient_id, [])
            profile = profiles.get(patient_id)
            latest_case = max(patient_cases, key=lambda case: case.updated_at, default=None)
            rows.append(
                DoctorPatientRow(
                    patient_id=patient_id,
                    name=profile.name if profile is not None else None,
                    age=profile.age if profile is not None else None,
                    photo_ref=profile.photo_ref if profile is not None else None,
                    bucket=_bucket_for(patient_id in live_patients, patient_cases),
                    granted_scopes=scopes,
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

        return PatientsListView(items=page_rows, total=total)

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
            logger.warning(
                "doctor-console profile resolution failed; degrading to anonymous rows",
                exc_info=True,
            )
            profiles = {}
        return profiles

    async def get_doctor_patient_detail(
        self, *, doctor_id: int, patient_id: int
    ) -> DoctorPatientDetailView:
        """Section-gated detail read of one patient (US-15..18, ADR-0019, #540).

        Composition order matches the Patients list derivation (live grants
        + assigned care cases), then gates each block on the patient's live
        grants:
        - ``contact`` under ANY live grant, enriched degrade-safe from the iam
          profile and access-logged (the detail surface marker) plus
          egress-disclosed against the most permissive live grant (prefer
          ``full_record``, else the earliest consent id);
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
        grants = await self._consent_facade.list_counterparty_grants(
            counterparty_type=_COUNTERPARTY_TYPE_DOCTOR,
            counterparty_id=str(doctor_id),
        )
        own_grants = [grant for grant in grants if grant.patient_id == patient_id]
        has_live_grant = bool(own_grants)

        cases = await self._care_facade.list_doctor_all_cases(doctor_id=doctor_id)
        patient_cases = [case for case in cases if case.patient_id == patient_id]
        latest_case = max(patient_cases, key=lambda case: case.updated_at, default=None)

        contact = None
        if has_live_grant:
            profile = await self._resolve_patient_profile(patient_id)
            contact = ContactSection(
                name=profile.name if profile is not None else None,
                age=profile.age if profile is not None else None,
                gender=profile.gender if profile is not None else None,
                area=profile.area if profile is not None else None,
                emergency_contact=profile.emergency_contact if profile is not None else None,
                photo_ref=profile.photo_ref if profile is not None else None,
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

        Fail-closed: without a live grant the read raises the same
        ``RecordAccessDeniedError`` the consented record read raises (the
        app-global health handler answers 403) and not a byte is returned.
        With a live grant the fetch is access-logged (the detail surface
        marker) and egress-disclosed against the most permissive live grant,
        then the stored photo is returned when one exists - ``None`` means
        "no photo on file" (the route answers 404), never a denial. A denial
        at the grant gate is a boundary refusal: no byte is read and no ledger
        row is written (it is the RBAC-analogous 403 the health handler
        answers), unlike the consented record reads which self-ledger.
        """
        grants = await self._consent_facade.list_counterparty_grants(
            counterparty_type=_COUNTERPARTY_TYPE_DOCTOR,
            counterparty_id=str(doctor_id),
        )
        own_grants = [grant for grant in grants if grant.patient_id == patient_id]
        if not own_grants:
            raise RecordAccessDeniedError("no live consent grant for this patient")

        photo = await self._iam_facade.get_patient_photo(identity_id=patient_id)
        if photo is None:
            return None

        await self._health_facade.log_doctor_patient_view(
            patient_id=patient_id,
            doctor_id=doctor_id,
            scope=_DETAIL_SCOPE_MARKER,
        )
        await self._disclose_against_grant(own_grants, patient_id, doctor_id)
        return photo

    async def _resolve_patient_profile(self, patient_id: int) -> PatientProfile | None:
        """Resolve one patient's profile, degrade-safe (review-queue convention #489).

        A failed profile must not fail the detail's contact block - the block
        degrades to empty fields with a warning logged, carrying no patient id
        or PHI in the log line (error-handling-observability §2).
        """
        try:
            return await self._iam_facade.get_patient_profile(patient_id)
        except Exception:
            logger.warning(
                "doctor-console profile resolution failed; degrading to empty contact",
                exc_info=True,
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
