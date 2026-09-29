"""MOD-012 doctor console: the typed wire contracts of the Patients list (#539).

The console is a facade-only composition seam (ADR-0003): it owns no schema,
so every DTO here is a read projection over other modules' seams - never a
table-backed model. Naming follows the module convention (``*View``/``*Item``).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from modules.health.facade import HealthBackgroundView, RecordTimeline


class DoctorPatientRow(BaseModel):
    """One patient in the doctor console, derived for this doctor (ADR-0019).

    The row is recomposed at read time from the doctor's live standing grants
    (consent reverse lookup) and their assigned care cases - never stored.
    ``bucket`` is the ADR-0019 derivation: ``"current"`` while a live grant or
    an open case exists, ``"past"`` once only closed cases remain and no
    grant is live. Scope and profile fields degrade to ``None``/empty when
    the source is unavailable (a missing identity profile must not fail the
    list).

    ``has_photo`` is a boolean presence flag, never the private storage object
    key: the console only ever asks "is there a photo to fetch", and the bytes
    come from the consent-gated photo route (security-phii-standards S2 - the
    console never learns where a patient's photo is stored, least of all for a
    Past patient whose consent was revoked).
    """

    patient_id: int
    name: str | None = None
    age: int | None = None
    has_photo: bool = False
    bucket: Literal["current", "past"]
    granted_scopes: list[str] = Field(default_factory=list)
    latest_case_stage: str | None = None


class PatientsListView(BaseModel):
    """One page of the doctor Patients list, sorted for the console.

    Rows are sorted by (name, patient_id); nameless rows trail the named ones
    deterministically so the list never reorders between requests. ``items``
    is the bounded page and ``total`` the full match count (after any search
    filter) so the caller can page through the rest - offset pagination per
    api-standards §4, the same envelope the audit ledger and health metrics
    use.
    """

    items: list[DoctorPatientRow]
    total: int


class ContactSection(BaseModel):
    """The contact block of the patient detail, gated on a record scope (#540).

    Served only when the doctor holds a live standing grant that actually
    authorizes identity contact - ``consultations`` or the subsuming
    ``full_record`` (ADR-0019, security-phii-standards S2 "egress carries the
    minimum context"). A narrower grant (``lab_results``,
    ``health_background``) answers ``None`` for the whole block, so a doctor
    never receives ``gender``/``area``/``emergency_contact`` under a scope that
    was never meant to carry them. Fields mirror the iam ``PatientProfile``
    fields and degrade to ``None`` when the patient has no saved profile - an
    open section with no data, distinct from a ``None`` section (locked / not
    shared) at the detail level. ``has_photo`` is a boolean presence flag, not
    the private storage object key.
    """

    name: str | None = None
    age: int | None = None
    gender: str | None = None
    area: str | None = None
    emergency_contact: str | None = None
    has_photo: bool = False


class CaseWorkspaceLink(BaseModel):
    """The deep link into the care case workspace (US-17, #540).

    The client navigates from the console to the case surface carrying this
    pair; the case id addresses ``GET /v1/care/cases/{case_id}`` and the
    stage restores the workspace tab. Always the doctor's own most recently
    updated case for the patient - never a borrowed view of a patient's other
    doctors' cases.
    """

    case_id: int
    stage: str


class DoctorPatientDetailView(BaseModel):
    """The section-gated detail read of one patient (US-15..18, ADR-0019, #540).

    Recomposed at read time exactly like the list row, then section-gated on
    the patient's live grants: ``contact`` opens under ``consultations`` (or
    the subsuming ``full_record``), ``consultation_history`` only under the
    ``consultations`` scope, and ``health_background`` only under
    ``health_background`` (which ``full_record`` subsumes). A section the
    doctor is not granted answers ``None`` - the client renders it as a locked
    "not shared" state, never an error. The case workspace is not
    consent-gated: it is the doctor's own case and only present when one
    exists.
    """

    patient_id: int
    bucket: Literal["current", "past"]
    granted_scopes: list[str] = Field(default_factory=list)
    latest_case_stage: str | None = None
    case_workspace: CaseWorkspaceLink | None = None
    contact: ContactSection | None = None
    consultation_history: RecordTimeline | None = None
    health_background: HealthBackgroundView | None = None
