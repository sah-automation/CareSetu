from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from modules.partner.domain.vocabularies import (
    require_consult_languages,
    require_consulting_days,
    require_notification_preferences,
    require_specialties,
)

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


class DoctorProfilePracticeUpdate(BaseModel):
    """The Practice section write (#608) - who the doctor is and where they practise.

    The first of the four section writes that replaced the retired whole-form
    profile write (#611). A section save is the doctor declaring one card's worth
    of fields, so it carries ONLY this card's fields and ``extra="forbid"`` makes
    any other field a 422 rather than a silent write: a client that saves the
    practice card cannot quietly rewrite the address or the notification
    preferences it did not show.

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
    # migration.
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


class DoctorProfileAboutUpdate(BaseModel):
    """The About section write (#610) - who the doctor is, in their own words.

    The third of the four section writes that replaced the retired whole-form
    profile write (#611). The card it saves splits the old ``availability`` blob
    in two, because the two halves want opposite things:

    - **The days become a selection.** A doctor taps the days they consult on, out
      of the closed seven-day list, so the field is filterable and cannot carry a
      spelling nobody can match. That is the same fix the languages field gets,
      and for the same reason: a hand-typed list of days is a doctor guessing at
      our vocabulary.
    - **The hours stay prose.** Deliberately unbounded in shape, and deliberately
      structured in nothing: no weekly template, no per-day ranges, no slots. The
      platform has no booking system, so a shape that invited one would be a lie
      the doctor could act on. The only rule here is a length bound, because the
      column is ``Text`` and an unbounded string is not a thing to store. A
      doctor who writes "Mon-Sat mornings, and Sat evening clinic after 5" gets
      that back, byte for byte.

    **Every field is required.** Not ``extra="forbid"`` alone - required as well,
    which is a stronger statement than its siblings make. A section save declares
    the whole card, so every field here is on screen at the moment of the save,
    and a default would mean that a client which forgot one silently CLEARS the
    column: an omitted ``about`` would erase the doctor's own words about
    themselves and the save would report success. Nullable is still meaningful -
    ``about: null`` is how a doctor clears it deliberately - but it has to be said
    out loud.

    Two of the four fields do not name their column, because the closed-list walk
    returns the resolved members rather than the submitted strings: a doctor who
    submits ``"Hindi"`` gets ``"Hindi"`` stored, which is the point.
    """

    model_config = ConfigDict(extra="forbid")

    about: str | None = Field(max_length=5000)
    # A SELECTION of the closed ``ConsultLanguage`` list (#602), stored as a JSONB
    # array on ``partner_profiles.languages``. NO ``max_length``, for the same
    # reason ``specialties`` has none: a cap is checked first and would refuse an
    # oversized selection as a bare ``too_long`` naming no member, shadowing the
    # one rule the field has. The closed list is the bound - a selection longer
    # than ``ConsultLanguage`` cannot hold that many distinct members.
    languages: list[str]
    # The same shape over the closed seven-day list, on ``consulting_days``. A
    # selection, not a week template: an empty selection is valid and is a state
    # the doctor can hold, exactly as an empty specialty selection is.
    consulting_days: list[str]
    # PROSE. The half of the old ``availability`` blob that is genuinely the
    # doctor's own words, bounded and otherwise unstructured - see the class
    # docstring. The bound matches the column's retired predecessor so a doctor
    # who typed a long availability note into the old field can move it across
    # without losing it.
    consulting_hours: str | None = Field(max_length=1000)

    @field_validator("languages")
    @classmethod
    def validate_languages(cls, value: list[str]) -> list[str]:
        """Delegate the closed-list rule to the domain core (coding-standards §4).

        ``require_consult_languages`` is the ONE place the list is enforced, so
        this validator names no language and re-derives nothing: it walks the
        submission member by member and returns the resolved values in the doctor's
        declared order, which is also the order the stored selection reads back in.

        The domain raises :class:`~modules.partner.domain.exceptions.InvalidConsultLanguageError`,
        which is deliberately NOT a ``ValueError``: a closed-list rejection is an
        expected 4xx with a field-level detail, and the partner adapter's handler
        encodes it as one (``details.errors[].path == "languages"``). Letting it
        escape the validator is what routes it there - a ``ValueError`` would be
        swallowed into Pydantic's own generic 422 and lose the envelope.

        **No strip and no case-folding, and that is #602's decision, not an
        oversight.** The retired ``DoctorProfileUpdate.validate_languages`` trimmed
        each name and de-duplicated case-insensitively, because the field was free
        text and a repair was better than a rejection. A closed list has no repair
        to make: ``"Hindi "`` is not ``ConsultLanguage.HINDI``, so it is refused
        rather than tidied, and ``"hindi"`` alongside ``"Hindi"`` is refused as the
        second member - which is a STRONGER answer to the same-language-twice-in-two
        spellings problem this ticket opens with than case-folding ever was,
        because the list can only produce one spelling in the first place. #611
        retires that free-text validator with the whole-form model it belonged to,
        leaving this as the only rule on languages, so the two cannot disagree.
        """
        return [member.value for member in require_consult_languages(value)]

    @field_validator("consulting_days")
    @classmethod
    def validate_consulting_days(cls, value: list[str]) -> list[str]:
        """Delegate the day rule to ``require_consulting_days``, exactly as above.

        The consulting-day counterpart of :meth:`validate_languages`, over
        :class:`~modules.partner.domain.vocabularies.ConsultingDay`, and refused
        the same way: ``InvalidConsultingDayError`` escapes the validator on
        purpose and the partner adapter's handler turns it into a 422 whose
        ``details.errors[].path`` names ``consulting_days``.
        """
        return [member.value for member in require_consulting_days(value)]


class DoctorProfileNotificationUpdate(BaseModel):
    """The Notification section write (#610) - which of the five things to be told.

    The fourth and last section write, and the smallest: ONE field, because
    notification preferences are one column and one card. The four-field
    ``DoctorProfileAboutUpdate`` above is the opposite extreme, and the two
    together are why the split exists - a doctor toggling one switch must not be
    able to half-save their about text, and a doctor rewriting their about text
    must not be able to flip a switch they never saw.

    **Every field is required**, for the same reason as the about model: the card
    declares its whole contents, and a default would let a client that sent only
    the toggles it cared about silently switch off the rest.

    The dict is validated against the closed ``NotificationPreferenceKey``
    vocabulary by ``require_notification_preferences`` (#602's pattern, on a list
    #610 added), so a save can set one of the five and nothing else. What happens
    to a stored key the five do not name is NOT decided here - the model cannot,
    because it has no row to look at - and is decided by
    :func:`~modules.partner.domain.vocabularies.merge_notification_preferences`
    in the facade, which merges rather than replaces. See that function for why
    preserving is neither dropping nor refusing.

    No entry and no key-length cap, and the reason is the closed list rather than
    a preference for fewer rules: a save contributes at most five known keys, each
    well under the old 50-character cap, so the retired 20-entry and 50-character
    bounds on this field bound nothing that can arrive. Adding them back would
    reintroduce a length failure that arrives as a bare ``too_long`` naming no key,
    which is the exact shadowing the two selection fields above avoid.
    """

    model_config = ConfigDict(extra="forbid")

    notification_preferences: dict[str, bool]

    @field_validator("notification_preferences")
    @classmethod
    def validate_notification_preferences(cls, value: dict[str, bool]) -> dict[str, bool]:
        """Delegate the closed-key rule to the domain core (coding-standards §4).

        ``InvalidNotificationKeyError`` escapes the validator on purpose - a
        ``ValueError`` would be swallowed into Pydantic's generic 422 and lose the
        envelope - and the partner adapter's handler encodes it as a 422 whose
        ``details.errors[].path`` names ``notification_preferences``.

        A key the vocabulary does not know is refused here, at the boundary, so the
        facade is never reached with one. A key the vocabulary DOES know but the
        row already holds under some other name is a different matter entirely and
        is the merge's business, not this validator's.
        """
        return require_notification_preferences(value)


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
    # The bound is #606's realistic 0..60, in lockstep with the database CHECK
    # and the migration. The read side carries it so a row holding a value the
    # write refuses surfaces as an error rather than being silently served.
    experience_years: int | None = Field(default=None, ge=0, le=60)
    about: str | None = None
    consultation_fee: int | None = Field(default=None, ge=0)
    # The declared consulting-language SELECTION, off the profile row - the column
    # the about section write (#610) lands on, and therefore a closed-vocabulary
    # selection rather than the hand-typed free text this field used to carry.
    languages: list[str] = Field(default_factory=list)
    # The days this doctor consults on, off ``consulting_days``. Multi-valued for
    # the same reason as ``languages``, and closed over ``ConsultingDay`` (#602),
    # so a filter on it is a membership match.
    consulting_days: list[str] = Field(default_factory=list)
    # The hours this doctor consults in, off ``consulting_hours``: PROSE, kept
    # that way on the wire as well as in the write. It replaces this view's
    # ``availability`` field (#610), which projected the column ``consulting_hours``
    # supersedes - a single blob mixing days and hours, where the days now have a
    # closed list of their own. The retired ``availability`` COLUMN is now inert
    # too: #611 removed the last writer, and it is kept rather than dropped in a
    # migration of its own (#606 deliberately deferred that). The projection is
    # not replaced by anything, because no reader should render an availability a
    # doctor cannot edit.
    consulting_hours: str | None = None
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
