from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

DoctorCredentialStatus = Literal[
    "pending",
    "verified",
    "expired",
    "revoked",
    "reverification_failed",
]


class DoctorProfileCredential(BaseModel):
    model_config = ConfigDict(extra="forbid")

    credential_type: str
    status: DoctorCredentialStatus
    expires_at: datetime | None


class DoctorProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    practice_name: str | None = Field(default=None, max_length=120)
    practice_address: str = Field(min_length=1, max_length=1000)
    # ``practice_latitude`` / ``practice_longitude`` are GONE (#606) and this is
    # what makes that a live guarantee rather than a documentation note: with
    # ``extra="forbid"``, a request still sending either field is a 422, so a
    # client can no longer place its own pin. The columns stay NOT NULL in the
    # database because registration writes them and #609 derives them from the
    # declared PIN; until the whole-form write is retired by #611 the shipped
    # profile page still sends both, so every save from the real client is
    # rejected until then. That is the intended loud failure - the alternative,
    # accepting and discarding the field, would tell a doctor their coordinates
    # saved when they did not.
    experience_years: int | None = Field(default=None, ge=0, le=60)
    languages: list[str] = Field(default_factory=list, max_length=20)
    about: str | None = Field(default=None, max_length=5000)
    availability: str | None = Field(default=None, max_length=1000)
    notification_preferences: dict[str, bool] = Field(default_factory=dict)

    @field_validator("languages")
    @classmethod
    def validate_languages(cls, value: list[str]) -> list[str]:
        normalized = [language.strip() for language in value]
        if any(not language or len(language) > 50 for language in normalized):
            raise ValueError("languages must contain 1 to 50 character names")
        if len({language.casefold() for language in normalized}) != len(normalized):
            raise ValueError("languages must be unique")
        return normalized

    @field_validator("notification_preferences")
    @classmethod
    def validate_notification_preferences(cls, value: dict[str, bool]) -> dict[str, bool]:
        if len(value) > 20:
            raise ValueError("notification_preferences may contain at most 20 entries")
        if any(not key or len(key) > 50 for key in value):
            raise ValueError("notification preference names must contain 1 to 50 characters")
        return value


class DoctorProfilePhotoView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    photo_ref: str


class DoctorProfileView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    partner_id: int
    photo_ref: str | None = None
    practice_name: str | None = None
    # The declared specialty, still projected as a SINGLE representative value
    # while the source column is a multi-valued selection (#606). The column is
    # copied from ``partner_profiles.specialties`` into the directory entry, so
    # this is the first member of that selection, or ``None`` for an empty one
    # and for the lab/chemist rows that carry no specialty at all.
    # ``None`` in practice until the shared refresh (#607) makes something a
    # runtime writer. #608 sources this from the profile row and widens it to a
    # selection; #612 and #613 widen the public projections.
    specialty: str | None = None
    verified: bool
    # A DENORMALISED display projection of the structured address parts (#606),
    # read-only here - it has two writers (registration and the address section
    # write) and this view is neither.
    practice_address: str
    # Server-written, never client-written (#606); #609 derives them from the
    # declared PIN. Still served here because the profile header shows the
    # practice's own position while the address section is the only editor.
    practice_latitude: float
    practice_longitude: float
    area: str | None = None
    languages: list[str] = Field(default_factory=list)
    # The bound is #606's realistic 0..60, in lockstep with the database CHECK
    # and the migration. The read side carries it so a row holding a value the
    # write refuses surfaces as an error rather than being silently served.
    experience_years: int | None = Field(default=None, ge=0, le=60)
    about: str | None = None
    consultation_fee: int | None = Field(default=None, ge=0)
    availability: str | None = None
    credentials: list[DoctorProfileCredential] = Field(default_factory=list)
    notification_preferences: dict[str, bool] = Field(default_factory=dict)
