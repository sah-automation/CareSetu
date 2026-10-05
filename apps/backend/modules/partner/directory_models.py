"""Result models for partner directory sub-facade."""

from datetime import datetime

from pydantic import BaseModel, Field


class DirectoryEntry(BaseModel):
    """One public directory search result (FEAT-004, user story 7).

    A verified-safe projection of an ``[Active]`` partner with valid
    credentials: display name (``practice_name``), partner type, the
    representative ``specialty`` (doctors only, one member of the doctor's
    declared selection - ``shared.representative_specialty``), the partner's
    ``area`` (its DECLARED locality, ``None`` when it declared none, since #612
    - the platform's service-area vocabulary is a registration default and must
    not be rendered as where the practice is), the derived ``verified``
    indicator plus its great-circle ``distance_km`` from the caller's geo
    point, and the nullable ``consultation_fee`` (integer paise, null until
    the doctor sets one). The tick is always True for a returned row - search
    visibility and the tick share one derivation, so a separate visibility flag
    could never drift (ADR-0011 "tick gone = card gone"). Named
    ``practice_name`` to stay on the partner schema vocabulary; patient-facing
    clients may render it as the provider's name.
    """

    partner_id: int
    practice_name: str | None
    partner_type: str
    specialty: str | None
    area: str | None
    distance_km: float
    verified: bool
    consultation_fee: int | None = None


class DirectorySearchView(BaseModel):
    """The public directory search response (MOD-002, FEAT-004).

    ``items`` are active-only, distance-sorted entries after the caller's
    filters (partner type, specialty for doctors, free-text over name);
    ``fell_back`` marks the wider-area fallback: nothing matched within the
    peri-urban scope, so the location constraint was relaxed (filters kept) and
    the results must be labeled "outside your area" (glossary). The patient is
    never silently served results that dropped a filter.
    """

    items: list[DirectoryEntry]
    fell_back: bool


class ProviderCredential(BaseModel):
    """One credential on the public provider profile (FEAT-005, PHASE-6 T03).

    The **verified** band of the profile, one credential at a time: the closed
    ``credential_type``, the derived ``status`` label and the recorded
    ``expires_at`` - never the artifact refs, never the document bytes (they
    stay in encrypted object storage). Every credential on a returned profile is
    labelled ``verified`` because the profile gate matches search visibility
    (ADR-0011): an unverified, expired or revoked credential makes the whole
    profile unreachable, so no invalid label can ever surface here.
    """

    credential_type: str
    status: str
    expires_at: datetime | None


class ProviderProfileView(BaseModel):
    """The public provider profile (MOD-002, FEAT-005, PHASE-6 T03 #309, #613).

    The projection of an ``[Active]`` partner that has a ``directory_index``
    entry and valid (verified, unexpired, unrevoked) credentials. It carries two
    bands, and a patient tells them apart by WHICH FIELD they are reading
    rather than by a flag's value (#613):

    - **Verified - the platform checked this.** ``verified``, the per-credential
      ``status`` labels, and their recorded expiry dates. ``verified`` is derived
      on every read from the same predicate search visibility uses, never
      stored, and it is always True for a reachable profile because
      reachability uses that same derivation - so it can never drift from the
      card tick (ADR-0011 "tick gone = card gone").
    - **Declared - the doctor says this.** ``clinic_name``, the ``specialties``
      SELECTION and the singular ``specialty`` label taken from it, ``languages``,
      ``consulting_days``, ``consulting_hours``, ``about``,
      ``experience_years``, the structured address parts, and the ``area`` label -
      which is the DECLARED locality, the same source ``DirectoryEntry.area``
      reads since #612, not the platform's service-area vocabulary. Widening the
      payload to these does NOT widen ``verified``: a declared field is not
      checked by anyone, and there is deliberately no second indicator for the
      band, because a patient must be able to tell "we checked this" from "the
      doctor wrote this" by the field itself.

    A declared field is as nullable as the doctor's profile is unfinished:
    ``None`` or an empty list is a state a doctor can hold, not a gap. The three
    selections are validated against the closed vocabularies that own them
    (``domain/vocabularies.py``), so no value outside ``Specialty`` /
    ``ConsultLanguage`` / ``ConsultingDay`` can reach a patient even off a
    hand-repaired row.

    ``specialty`` (singular) stays beside ``specialties`` deliberately: it is the
    one representative label the narrow surfaces already render, kept here so
    widening the band is purely additive for them - #618 extracts the shared
    renderer and #619 renders the declared band on it. It is the first member of
    the same validated ``specialties`` list rather than a second copy read from
    another column, so one payload cannot report a label its own selection does
    not contain.

    The structured address parts are served instead of the ``practice_address``
    display string, which is a denormalised registration-era projection of them
    (#606): a client is never asked to parse an assembled string back into the
    fields the doctor declared. Never exposed, before or after this widening:
    artifact refs (photo and credential bytes stay in private object storage,
    ADR-0020), the practice's coordinates, emails, phones, the partner's
    identity id, notification preferences, and PHI of any kind.
    """

    partner_id: int
    practice_name: str | None
    partner_type: str
    specialty: str | None
    area: str | None
    verified: bool
    credentials: list[ProviderCredential]
    consultation_fee: int | None = None
    # --- the declared band (#613) -------------------------------------------
    # The building the practice is in, distinct from ``practice_name`` which is
    # the doctor's own name and the only patient-searchable name.
    clinic_name: str | None = None
    # The declared specialty SELECTION off the profile row, multi-valued because
    # a district practice spans more than one kind of care. Closed over
    # ``Specialty``; empty means "declares none yet".
    specialties: list[str] = Field(default_factory=list)
    # The languages the doctor consults in, closed over ``ConsultLanguage``.
    languages: list[str] = Field(default_factory=list)
    # The days they consult on, closed over ``ConsultingDay`` - a week, not a
    # working week, so Saturday and Sunday are members.
    consulting_days: list[str] = Field(default_factory=list)
    # The hours they consult in, as PROSE on the wire as well as in the write:
    # no weekly template, no slots, nothing implying a booking system the
    # platform does not have.
    consulting_hours: str | None = None
    # The doctor's own words about their practice, verbatim.
    about: str | None = None
    # #606's realistic 0..60 bound, in lockstep with the database CHECK. The
    # CHECK is what enforces it; the bound here keeps the sibling private view's
    # contract rather than restating a second rule.
    experience_years: int | None = Field(default=None, ge=0, le=60)
    # The structured address the doctor declared (#609), as its five parts. Each
    # is nullable because a half-finished address is a state a doctor can hold -
    # registration writes only the display column until the parts exist.
    address_line: str | None = None
    landmark: str | None = None
    locality: str | None = None
    city: str | None = None
    pin_code: str | None = None
