"""Result models for partner directory sub-facade."""

from datetime import datetime

from pydantic import BaseModel


class DirectoryEntry(BaseModel):
    """One public directory search result (FEAT-004, user story 7).

    A verified-safe projection of an ``[Active]`` partner with valid
    credentials: display name (``practice_name``), partner type, specialty
    (doctors only), the partner's ``area`` (its recorded service area, with the
    Daltonganj fallback when none is recorded - the same optionality and
    derivation the provider profile uses), and the derived ``verified``
    indicator plus its great-circle ``distance_km`` from the caller's geo
    point. The tick is always True for a returned row - search visibility and
    the tick share one derivation, so a separate visibility flag could never
    drift (ADR-0011 "tick gone = card gone"). Named ``practice_name`` to stay
    on the partner schema vocabulary; patient-facing clients may render it as
    the provider's name.
    """

    partner_id: int
    practice_name: str | None
    partner_type: str
    specialty: str | None
    area: str | None
    distance_km: float
    verified: bool


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

    Verified-safe projection: only the closed ``credential_type``, the derived
    ``status`` label and the recorded ``expires_at`` - never the artifact refs,
    never the document bytes (they stay in encrypted object storage). Every
    credential on a returned profile is labelled ``verified`` because the
    profile gate matches search visibility (ADR-0011): an unverified, expired
    or revoked credential makes the whole profile unreachable, so no invalid
    label can ever surface here.
    """

    credential_type: str
    status: str
    expires_at: datetime | None


class ProviderProfileView(BaseModel):
    """The public provider profile (MOD-002, FEAT-005, PHASE-6 T03 #309).

    A verified-safe projection of an ``[Active]`` partner that has a
    ``directory_index`` entry and valid (verified, unexpired, unrevoked)
    credentials: display name (``practice_name``), partner type, specialty
    (doctors only), the partner's service area, the derived ``verified``
    indicator and per-credential type + status labels. ``verified`` is always
    True for a reachable profile because reachability uses the same derivation
    as search visibility - it can never drift from the card tick (ADR-0011
    "tick gone = card gone"). Never exposed: artifact refs, emails, phones, PHI.
    """

    partner_id: int
    practice_name: str | None
    partner_type: str
    specialty: str | None
    area: str | None
    verified: bool
    credentials: list[ProviderCredential]
