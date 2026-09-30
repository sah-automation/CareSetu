from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from modules.partner.domain.vocabularies import require_specialties

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


class DoctorProfilePracticeUpdate(BaseModel):
    """The Practice section write (#608) - who the doctor is and where they practise.

    The first of the four section writes that replace the whole-form
    ``DoctorProfileUpdate`` (#611 retires that one). A section save is the doctor
    declaring one card's worth of fields, so it carries ONLY this card's fields
    and ``extra="forbid"`` makes any other field a 422 rather than a silent
    write: a client that saves the practice card cannot quietly rewrite the
    address or the notification preferences it did not show.

    Two of the four wire fields do not name their column, and both mappings are
    fixed here rather than guessed per call site:

    - ``full_name`` is the doctor's own name, written to ``practice_name``. That
      column is the display name registration fills with the doctor's name, and
      it is what the directory search's free-text ``query`` matches
      (``ilike`` on ``partner_profiles.practice_name``), so a patient can still
      search this doctor by their own name. The wire field says what the field
      MEANS - a doctor names themselves, they do not name a practice - while the
      column keeps its registration-era name so nothing that already reads it
      moves. ``clinic_name`` is the building they practise in and writes the
      column of that name (#606).
    """

    model_config = ConfigDict(extra="forbid")

    full_name: str = Field(min_length=1, max_length=120)
    clinic_name: str | None = Field(default=None, max_length=120)
    # A SELECTION of the closed ``Specialty`` pick-list, stored as a JSONB array
    # on ``partner_profiles.specialties`` (#606). An empty selection is valid and
    # is a state the doctor can hold - "declares no specialty yet" - exactly as
    # for languages.
    #
    # Deliberately NO ``max_length`` here. A length cap is checked before the
    # validator below runs, so an oversized selection would be refused as a plain
    # ``too_long`` with no member named - shadowing the one rule this field
    # actually has. The closed list is already an upper bound: a selection longer
    # than ``Specialty`` cannot hold that many distinct members, so the validator
    # rejects the first repeat or unknown member and says which one.
    specialties: list[str] = Field(default_factory=list)
    # #606's realistic 0..60 bound, in lockstep with the database CHECK and the
    # migration - not the 0..100 the whole-form model carried before it.
    experience_years: int | None = Field(default=None, ge=0, le=60)

    @field_validator("specialties")
    @classmethod
    def validate_specialties(cls, value: list[str]) -> list[str]:
        """Delegate the closed-list rule to the domain core (coding-standards §4).

        ``require_specialties`` is the ONE place the pick-list is enforced, so
        this validator names no specialty and re-derives no list: it walks the
        submission member by member and returns the resolved values in the
        doctor's declared order, which is also the order the stored selection and
        every later membership match (#612) read.

        The domain raises :class:`~modules.partner.domain.exceptions.InvalidSpecialtyError`,
        which is deliberately NOT a ``ValueError``: a closed-list rejection is an
        expected 4xx with a field-level detail, and the partner adapter's handler
        encodes it as one (``details.errors[].path == "specialties"``). Letting it
        escape the validator is what routes it there - a ``ValueError`` would be
        swallowed into Pydantic's own generic 422 and lose the envelope.
        """
        return [member.value for member in require_specialties(value)]


class DoctorProfileAddressUpdate(BaseModel):
    """The Address section write (#609) - where the practice is, declared not pinned.

    A doctor declares an address; the platform derives the one position every
    reader sees. So this model declares **no coordinate field at all**, and
    ``extra="forbid"`` is what makes that a live guarantee rather than a comment: a
    client still sending ``practice_latitude`` or ``practice_longitude`` is a 422,
    and it cannot place its own pin. Accepting and discarding the field instead
    would tell a doctor their coordinates saved when they did not.

    ``pin_code`` is the only required part, because it is the only one the position
    is derived from: without a PIN code this write has nothing to resolve and
    cannot produce a position, so requiring it here states that in the schema
    rather than discovering it as a field-level error after the fact.

    Deliberately **no** length bound and **no** pattern on ``pin_code``. Any bound
    here would be checked before anything else and would refuse the value as a bare
    ``too_short``/``too_long`` with no ``reason`` and no machine value - shadowing
    the one rule the field has, and splitting the malformed case in two on the wire
    for a doctor who cannot tell a length failure from a character-class failure
    anyway. ``resolve_pin_code`` (#603) owns that rule: an Indian PIN code is
    exactly six ASCII digits, and it reports malformed and unknown as two
    machine-readable reasons. So a blank, an over-long and a well-formed but
    unlisted code all arrive in the same PIN-keyed envelope, because they are all
    the same answer to the doctor: this is not a PIN code we can place.
    """

    model_config = ConfigDict(extra="forbid")

    # Column-matched bounds (#606): ``address_line``/``address_landmark`` are
    # String(200), ``address_locality``/``address_city`` String(120). Every part is
    # nullable on the row, so every part is optional here - a doctor who has not
    # finished their address is a state the write can hold.
    address_line: str | None = Field(default=None, max_length=200)
    landmark: str | None = Field(default=None, max_length=200)
    locality: str | None = Field(default=None, max_length=120)
    city: str | None = Field(default=None, max_length=120)
    pin_code: str


class DoctorProfilePhotoView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    photo_ref: str


class DoctorProfileView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    partner_id: int
    photo_ref: str | None = None
    practice_name: str | None = None
    # The building the practice is in, distinct from ``practice_name`` which is
    # the doctor's own name. Nullable: a doctor can declare who they are before
    # they have named the building they see patients in.
    clinic_name: str | None = None
    # The declared specialty SELECTION, sourced from ``partner_profiles.specialties``
    # - the column the practice section write lands on - and therefore multi-valued.
    #
    # #608 changed this field's name AND shape, from a single nullable string to
    # this list. That is a breaking response change for every consumer, and it is
    # intended: the single-value projection was always a lie for a doctor who
    # practises more than one kind of care, and while this field was outer-joined
    # from the directory entry it was always ``None`` anyway, because nothing at
    # runtime wrote that column. Keeping the join would have let the read view
    # disagree with the row just written the moment the profile write and the
    # directory refresh (#607) landed in different transactions.
    #
    # The single-valued projections that remain - the directory browse entry and
    # the public provider profile - still go through
    # ``shared.representative_specialty``, and #612 / #613 own widening those.
    specialties: list[str] = Field(default_factory=list)
    verified: bool
    # A DENORMALISED display projection of the structured address parts (#606),
    # read-only here - it has two writers (registration and the address section
    # write) and this view is neither.
    practice_address: str
    # The structured parts themselves, which are what the address card edits and
    # what it seeds its form from (#609). Served beside the display projection
    # rather than instead of it: the column is assembled from these, so a client
    # that had to parse the display string back into fields would be guessing at a
    # format it is not meant to own.
    #
    # Nullable for the same reason the columns are - a doctor can hold a partly
    # declared address, and registration writes only the display column until the
    # structured parts exist.
    address_line: str | None = None
    landmark: str | None = None
    locality: str | None = None
    city: str | None = None
    pin_code: str | None = None
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


class DoctorProfileAddressView(DoctorProfileView):
    """The Address section write's answer (#609): the profile plus the belt warning.

    A separate response model rather than two nullable fields on
    :class:`DoctorProfileView`, because **only this write evaluates the belt**. The
    decision needs the PIN's resolved centroid, and the only place that resolution
    already exists is the write's own transaction; re-deriving it on every profile
    read would put a centroid lookup on the GET path to answer a question no reader
    asked. So ``outside_peri_urban_belt`` is required here and absent from the read
    projection entirely, rather than being a tri-state field whose value depends on
    which endpoint produced the response - which is exactly the kind of field that
    reads as "known to be in-belt" everywhere else. The card renders no notice before
    the doctor's first address save because there is no field to render, which is the
    honest state rather than a promise or a spinner.

    It is a **warning, never a refusal**: the position is written either way and the
    save succeeds, and only the doctor's own listing surfaces as an outside-your-area
    result (the wider-area fallback, glossary).
    """

    outside_peri_urban_belt: bool
    # The measured great-circle distance from the belt centre, so the warning can
    # say how far out the practice sits rather than only that it is out. Carried
    # because ``PeriUrbanBeltDecision`` produces it for that purpose (#603) and
    # because a doctor told only "outside" cannot tell whether they mistyped or
    # genuinely practise further out.
    distance_from_belt_centre_km: float
