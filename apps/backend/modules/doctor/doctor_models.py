"""MOD-012 doctor console: the typed wire contracts of the Patients list (#539).

The console is a facade-only composition seam (ADR-0003): it owns no schema,
so every DTO here is a read projection over other modules' seams - never a
table-backed model. Naming follows the module convention (``*View``/``*Item``).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class DoctorPatientRow(BaseModel):
    """One patient in the doctor console, derived for this doctor (ADR-0019).

    The row is recomposed at read time from the doctor's live standing grants
    (consent reverse lookup) and their assigned care cases - never stored.
    ``bucket`` is the ADR-0019 derivation: ``"current"`` while a live grant or
    an open case exists, ``"past"`` once only closed cases remain and no
    grant is live. Scope and profile fields degrade to ``None``/empty when
    the source is unavailable (a missing identity profile must not fail the
    list).
    """

    patient_id: int
    name: str | None = None
    age: int | None = None
    photo_ref: str | None = None
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
