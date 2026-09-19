"""Result models for care facade (PHASE-8 T01, ticket #417)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, field_validator

from modules.care.schema.models import (
    CANONICAL_CLOSE_REASONS,
    CANONICAL_INPUT_TYPES,
    CANONICAL_RX_SOURCES,
    CANONICAL_RX_STATUSES,
    CANONICAL_SENSITIVE_CLASSES,
    CANONICAL_STAGES,
)

#: The MOD-006 database schema. Kept here (a leaf module free of facade
#: imports) so the facade, adapters, and pipeline all import it without
#: the circular-import hazard that importing from ``facade.py`` caused.
CARE_SCHEMA = "care"

#: Typed alias for the JSONB prescription draft snapshot payload. The JSONB
#: column stores arbitrary JSON (the AI drafting leg's frozen baseline, e.g.
#: ``{"rx_items": [{"name", "dose", "duration", "frequency"}, ...]}``);
#: ``Any`` values keep the typed boundary honest about a JSONB artifact
#: (CONTEXT.md glossary, ``draft snapshot``). ``edited_yn`` derivation reads
#: this frozen shape.
DraftSnapshot = dict[str, Any]


class CaseDetailView(BaseModel):
    """The read projection returned by get_case.

    Carries the case lifecycle fields, associated patient/doctor/pre_summary
    IDs, stage, and close information. The facade enforces that the caller
    has access to the case (doctor-scoped or patient-scoped depending on
    the endpoint).
    """

    case_id: int
    patient_id: int
    doctor_id: int | None
    pre_summary_id: int | None
    stage: str
    forced_review: bool = False
    closed_at: datetime | None
    close_reason: str | None
    created_at: datetime
    updated_at: datetime

    @field_validator("stage")
    @classmethod
    def _stage_must_be_canonical(cls, value: str) -> str:
        """Reject a non-canonical stage at the typed boundary.

        The DB CHECK constraint ``ck_care_cases_stage`` only admits the
        values in :data:`modules.care.schema.models.CANONICAL_STAGES`; a hand-
        built ``CaseDetailView`` with anything else otherwise surfaces as an
        IntegrityError (a 500) later. A 422 here is the honest early answer.
        """
        if value not in CANONICAL_STAGES:
            raise ValueError(f"stage must be one of {sorted(CANONICAL_STAGES)}; got {value!r}")
        return value

    @field_validator("close_reason")
    @classmethod
    def _close_reason_must_be_canonical(cls, value: str | None) -> str | None:
        """Reject a non-canonical close_reason at the typed boundary."""
        if value is not None and value not in CANONICAL_CLOSE_REASONS:
            raise ValueError(
                f"close_reason must be one of {sorted(CANONICAL_CLOSE_REASONS)}; got {value!r}"
            )
        return value


class RxItemView(BaseModel):
    """A single medication line item within a prescription."""

    rx_item_id: int
    prescription_id: int
    sequence: int
    name: str
    dose: str | None
    duration: str | None
    frequency: str | None = None


class RxItemInput(BaseModel):
    """A medication line a doctor authors or edits in the working revision.

    The typed input shape for ``create_rx_draft(source="manual")`` and
    ``save_rx_revision``: ``name`` is required, ``dose``/``duration``/
    ``frequency`` optional (a doctor may leave a dosage or frequency open for
    the pharmacist). It deliberately carries no ids - the facade assigns
    ``sequence`` and the row ids when the working revision is persisted to
    ``care_rx_items``.
    """

    name: str
    dose: str | None = None
    duration: str | None = None
    frequency: str | None = None


class PrescriptionDetailView(BaseModel):
    """The read projection returned by get_approved_prescription.

    Carries the prescription lifecycle fields, source, draft snapshot,
    issued timestamp, attributed doctor, and the list of medication items.
    """

    prescription_id: int
    case_id: int
    status: str
    source: str
    attempt_no: int
    draft_snapshot: DraftSnapshot
    issued_at: datetime | None
    attributed_doctor: int | None
    items: list[RxItemView]
    created_at: datetime
    updated_at: datetime

    @field_validator("status")
    @classmethod
    def _status_must_be_canonical(cls, value: str) -> str:
        """Reject a non-canonical status at the typed boundary."""
        if value not in CANONICAL_RX_STATUSES:
            raise ValueError(
                f"status must be one of {sorted(CANONICAL_RX_STATUSES)}; got {value!r}"
            )
        return value

    @field_validator("source")
    @classmethod
    def _source_must_be_canonical(cls, value: str) -> str:
        """Reject a non-canonical source at the typed boundary."""
        if value not in CANONICAL_RX_SOURCES:
            raise ValueError(f"source must be one of {sorted(CANONICAL_RX_SOURCES)}; got {value!r}")
        return value


class DoctorInputResult(BaseModel):
    """The outcome of submit_doctor_input.

    Records a voice or photo input attached to a case. The input is
    stored durably at upload time; the input_type and media_ref are
    persisted on the ``care_doctor_inputs`` row.
    """

    input_id: int
    case_id: int
    input_type: str
    media_ref: str
    sensitive_class: str | None

    @field_validator("input_type")
    @classmethod
    def _input_type_must_be_canonical(cls, value: str) -> str:
        """Reject a non-canonical input_type at the typed boundary."""
        if value not in CANONICAL_INPUT_TYPES:
            raise ValueError(
                f"input_type must be one of {sorted(CANONICAL_INPUT_TYPES)}; got {value!r}"
            )
        return value

    @field_validator("sensitive_class")
    @classmethod
    def _sensitive_class_must_be_canonical(cls, value: str | None) -> str | None:
        """Reject a non-canonical sensitive_class at the typed boundary."""
        if value is not None and value not in CANONICAL_SENSITIVE_CLASSES:
            raise ValueError(
                f"sensitive_class must be one of "
                f"{sorted(CANONICAL_SENSITIVE_CLASSES)}; got {value!r}"
            )
        return value
