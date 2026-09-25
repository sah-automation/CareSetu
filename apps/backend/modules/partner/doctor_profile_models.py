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
    practice_latitude: float = Field(ge=-90, le=90)
    practice_longitude: float = Field(ge=-180, le=180)
    experience_years: int | None = Field(default=None, ge=0, le=100)
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
    specialty: str | None = None
    verified: bool
    practice_address: str
    practice_latitude: float
    practice_longitude: float
    area: str | None = None
    languages: list[str] = Field(default_factory=list)
    experience_years: int | None = Field(default=None, ge=0, le=100)
    about: str | None = None
    consultation_fee: int | None = Field(default=None, ge=0)
    availability: str | None = None
    credentials: list[DoctorProfileCredential] = Field(default_factory=list)
    notification_preferences: dict[str, bool] = Field(default_factory=dict)
