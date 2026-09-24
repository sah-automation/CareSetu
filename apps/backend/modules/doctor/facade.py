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
from typing import TYPE_CHECKING

from modules.doctor.doctor_models import DoctorPatientRow, PatientsListView

if TYPE_CHECKING:
    from modules.care.facade import CaseConsoleFacade, CaseDetailView
    from modules.consent.facade import ConsentFacade
    from modules.health.facade import HealthFacade
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
