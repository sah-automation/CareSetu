"""MOD-002: the doctor's closed practice vocabularies (FEAT-004/005, ticket #602).

Four pick-lists the domain owns, with the validation that refuses a value
outside its own list:

- :class:`Specialty` - the roughly twenty specialties that account for most
  small-town practice. Doctors only; the field is never free-form (glossary).
- :class:`ConsultLanguage` - the languages a doctor consults in, the languages
  of the Eighth Schedule of the Constitution of India plus English.
- :class:`ConsultingDay` - the seven days of the week.
- :class:`NotificationPreferenceKey` - the five things a doctor can be notified
  about (#610).

A closed vocabulary is domain language, not a model constant
(coding-standards §2/§3): the values are declared here, the profile model
mirrors them, and the pre-condition is validated in the domain core, never in
the router. One entry point per field that draws on a list -
:func:`require_specialty` and :func:`require_specialties`,
:func:`require_consult_languages`, :func:`require_consulting_days`,
:func:`require_notification_preferences` - each raising a named
:class:`~modules.partner.domain.exceptions.PartnerError` subclass, so a value
outside a list is an explicit rejection rather than something that persists and
can never be filtered on. A multi-valued selection is validated member by member
and names the offending position.

The one entry point that is not a bare list-membership check is
:func:`merge_notification_preferences`, which is what a notification save
actually decides: which of the five the doctor submitted, and what happens to a
stored key the five do not name.

Values are stable, machine-readable keys. Display labels in either locale are
the section writers' job, not this module's.

``Specialty`` moved here from ``domain/credentials.py`` (#602): the practice a
doctor declares is not a credential document, and the two had outgrown one file.
``NotificationPreferenceKey`` joined them for the opposite reason (#610): until
then the ONLY named list of the five keys anywhere in the repository was the
frontend ``NOTIFICATION_KEYS`` tuple on the doctor Profile page, so the server's
"preferences" were an untyped dict no vocabulary, and no pre-condition, existed
for. See :func:`merge_notification_preferences` for what that cost and what the
merge keeps.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from enum import StrEnum
from typing import TypeVar

from modules.partner.domain.exceptions import (
    InvalidConsultingDayError,
    InvalidConsultLanguageError,
    InvalidNotificationKeyError,
    InvalidSelectionError,
    InvalidSpecialtyError,
    PartnerError,
    VocabularyRejectionReason,
)

_MemberT = TypeVar("_MemberT")


#: The closed pick-list of the kind of care an [Active] doctor offers
#: (FEAT-004, glossary). Doctors only - labs and chemists carry no specialty,
#: and the field is never free-form. Sized to the specialties that account for
#: most small-town practice, so a district doctor finds their own entry instead
#: of falling back to "General Physician"; every value fits the
#: ``directory_index.specialty`` VARCHAR(40) column.
#:
#: LOCKSTEP BROKEN ON PURPOSE (#602). The house rule is that the domain never
#: names a value the schema cannot hold. The
#: ``ck_partner_directory_index_specialty`` CHECK still names the original four
#: and cannot be edited - it is baked into an already-applied revision, and a
#: migration is immutable (ADR-0003). **#606** replaces the column and retires
#: the constraint, and carries the migration and ADR for it. The sixteen newer
#: values cannot reach the database in the meantime because no runtime writer
#: ever sets the column: it is always NULL. Do not skip the constraint
#: replacement in #606.
class Specialty(StrEnum):
    GENERAL_PHYSICIAN = "General Physician"
    PEDIATRICIAN = "Pediatrician"
    GYNECOLOGIST = "Gynecologist"
    DENTIST = "Dentist"
    GENERAL_SURGEON = "General Surgeon"
    ORTHOPEDIC_SURGEON = "Orthopedic Surgeon"
    OPHTHALMOLOGIST = "Ophthalmologist"
    ENT_SPECIALIST = "ENT Specialist"
    DERMATOLOGIST = "Dermatologist"
    PSYCHIATRIST = "Psychiatrist"
    CARDIOLOGIST = "Cardiologist"
    NEUROLOGIST = "Neurologist"
    GASTROENTEROLOGIST = "Gastroenterologist"
    UROLOGIST = "Urologist"
    NEPHROLOGIST = "Nephrologist"
    PULMONOLOGIST = "Pulmonologist"
    ENDOCRINOLOGIST = "Endocrinologist"
    ONCOLOGIST = "Oncologist"
    AYURVEDIC_PRACTITIONER = "Ayurvedic Practitioner"
    HOMEOPATHY_PRACTITIONER = "Homeopathy Practitioner"


#: The closed list of languages a doctor consults in (FEAT-005, doctor profile).
#: The 22 languages of the Eighth Schedule of the Constitution of India, plus
#: English: not scheduled, but the Union's link language and a real consulting
#: language here, so excluding it would leave a doctor unable to declare it.
#:
#: NOT ``modules.intake.domain.events.IntakeLanguage``. That is a two-value
#: literal for the *interface* language of a patient intake session; this is
#: what a doctor speaks with patients. Different concept, different consumer -
#: do not extend one from the other.
class ConsultLanguage(StrEnum):
    ASSAMESE = "Assamese"
    BENGALI = "Bengali"
    BODO = "Bodo"
    DOGRI = "Dogri"
    ENGLISH = "English"
    GUJARATI = "Gujarati"
    HINDI = "Hindi"
    KANNADA = "Kannada"
    KASHMIRI = "Kashmiri"
    KONKANI = "Konkani"
    MAITHILI = "Maithili"
    MALAYALAM = "Malayalam"
    MANIPURI = "Manipuri"
    MARATHI = "Marathi"
    NEPALI = "Nepali"
    ODIA = "Odia"
    PUNJABI = "Punjabi"
    SANSKRIT = "Sanskrit"
    SANTALI = "Santali"
    SINDHI = "Sindhi"
    TAMIL = "Tamil"
    TELUGU = "Telugu"
    URDU = "Urdu"


#: The closed list of the seven days a doctor may consult on (FEAT-005, doctor
#: profile availability). A week, not a working week: a Saturday or Sunday
#: clinic is ordinary in small-town practice and a closed list that omitted them
#: would be a rule the practice cannot express.
class ConsultingDay(StrEnum):
    MONDAY = "Monday"
    TUESDAY = "Tuesday"
    WEDNESDAY = "Wednesday"
    THURSDAY = "Thursday"
    FRIDAY = "Friday"
    SATURDAY = "Saturday"
    SUNDAY = "Sunday"


class NotificationPreferenceKey(StrEnum):
    #: The five things a doctor can be notified about, and the ONLY five a save
    #: may set (#610).
    #:
    #: :attr:`~modules.intake.domain.events.IntakeLanguage` has no say in this,
    #: and neither has the patient's own ``NOTIFICATION_KEYS`` list on their
    #: profile page: those are a different vocabulary for a different reader, and
    #: neither list extends this one. These five are the doctor's, and they are
    #: the keys the stored preferences on every profile row already use.
    #:
    #: This enum is the reason the write is a closed list at all. Before #610 the
    #: server stored an untyped ``dict[str, bool]`` with a 20-entry cap and a
    #: 50-character key cap, validated for shape only - so the only named list of
    #: the five in the entire repository was a TypeScript tuple in the doctor
    #: Profile page, and "accepts the five existing notification keys" had no
    #: server-side meaning to enforce. Ownership of a vocabulary belongs with the
    #: domain that also refuses values outside it (coding-standards §4).
    NEW_CONSULTATIONS = "new_consultations"
    RECORD_SHARED = "record_shared"
    PRE_SUMMARY_READY = "pre_summary_ready"
    CASE_UPDATES = "case_updates"
    CREDENTIAL_STATUS = "credential_status"


_SPECIALTY_BY_VALUE: dict[str, Specialty] = {member.value: member for member in Specialty}
_CONSULT_LANGUAGE_BY_VALUE: dict[str, ConsultLanguage] = {
    member.value: member for member in ConsultLanguage
}
_CONSULTING_DAY_BY_VALUE: dict[str, ConsultingDay] = {
    member.value: member for member in ConsultingDay
}
_NOTIFICATION_KEY_BY_VALUE: dict[str, NotificationPreferenceKey] = {
    member.value: member for member in NotificationPreferenceKey
}


def require_specialty(raw: object) -> Specialty:
    """Resolve a submitted specialty to its member of the closed pick-list.

    The entry point for the single-valued specialty field - the one on a
    directory entry, and therefore the one the ``FEAT-004`` search filter reads.
    Raises :class:`~modules.partner.domain.exceptions.InvalidSpecialtyError` for
    a value that is not a member, which includes a non-string, an empty or
    whitespace-only string, a differently-cased spelling, and the member *name*
    rather than its value: the field is never free-form, so nothing is trimmed
    or case-folded on the way in. A member passed back in is returned unchanged,
    so the entry point is safe to apply twice.
    """
    member = _SPECIALTY_BY_VALUE.get(raw) if isinstance(raw, str) else None
    if member is None:
        raise InvalidSpecialtyError(raw)
    return member


def require_specialties(raw: Iterable[object]) -> tuple[Specialty, ...]:
    """Resolve a submitted multi-valued specialty selection member by member.

    A doctor offers more than one kind of care, so the profile declares a
    selection of them and the overlap search (#612) matches on membership. The
    first value that breaks a rule raises
    :class:`~modules.partner.domain.exceptions.InvalidSpecialtyError` carrying
    its position, exactly as the language and day walks do.
    """
    return _require_members(raw, _SPECIALTY_BY_VALUE, InvalidSpecialtyError)


def require_consult_languages(raw: Iterable[object]) -> tuple[ConsultLanguage, ...]:
    """Resolve a submitted consulting-language selection member by member.

    A doctor consults in several languages, so the field is multi-valued. Every
    member is validated against :class:`ConsultLanguage` and the first value
    that breaks a rule raises
    :class:`~modules.partner.domain.exceptions.InvalidConsultLanguageError`
    carrying its position: either it is not a member, or the selection already
    carries it. A repeated language is a data-entry slip, not a second language -
    carried over deliberately from the retired whole-form write, so narrowing the
    write does not quietly drop the rule. An empty selection is valid and returns
    an empty tuple: "declares no languages" is a state the doctor can hold.

    Stricter than the retired ``DoctorProfileUpdate.validate_languages`` on
    purpose. That validator trimmed each name and bounded it at 50 characters
    because the field was free text; a closed list has no such repair, so
    ``"Hindi "`` is refused rather than tidied. #611 retired the model validator
    with the whole-form model it belonged to, leaving this as the only rule.
    """
    return _require_members(raw, _CONSULT_LANGUAGE_BY_VALUE, InvalidConsultLanguageError)


def require_consulting_days(raw: Iterable[object]) -> tuple[ConsultingDay, ...]:
    """Resolve a submitted consulting-day selection member by member.

    The multi-valued counterpart of :func:`require_consult_languages`, over
    :class:`ConsultingDay`. The first value that breaks a rule raises
    :class:`~modules.partner.domain.exceptions.InvalidConsultingDayError`
    carrying its position; an empty selection and a repeated day are handled as
    in :func:`require_consult_languages`.
    """
    return _require_members(raw, _CONSULTING_DAY_BY_VALUE, InvalidConsultingDayError)


def require_notification_preferences(raw: Mapping[str, bool]) -> dict[str, bool]:
    """Resolve a submitted notification preference dict against the five keys (#610).

    The write-side entry point for the notification section save, and the
    notification counterpart of :func:`require_consult_languages`: every submitted
    key must be a member of :class:`NotificationPreferenceKey`, and the first one
    that is not raises :class:`~modules.partner.domain.exceptions.InvalidNotificationKeyError`
    carrying the key.

    ``bool`` values are **carried through, not coerced**. The wire is JSON, where
    ``true``/``false`` arrive as Python ``bool``, and a Pydantic model asked for
    ``dict[str, bool]`` has already normalised them by the time this runs - which is
    why the parameter is typed ``Mapping[str, bool]`` and mypy holds every call site
    to it.

    Coercing here would be worse than useless: ``bool("false")`` is ``True``, so a
    truthiness cast does not merely tolerate a sloppy value, it stores the exact
    opposite of what the caller wrote. Declaring the type keeps that decision out of
    the domain entirely - there is no coercion left here to get wrong.

    Unlike the three pick-lists there is no ``position`` and no ``reason``: a
    preference is a **dict**, so it has no member order to point into and only one
    member-level rule to break. The key is the answer.
    """
    for key in raw:
        if key not in _NOTIFICATION_KEY_BY_VALUE:
            raise InvalidNotificationKeyError(key)
    return dict(raw)


def merge_notification_preferences(
    *,
    submitted: Mapping[str, bool],
    stored: Mapping[str, object],
) -> dict[str, object]:
    """Decide what a notification save writes: the five, plus what it already held.

    The whole decision a notification section write makes, kept in the domain
    because it is the one place that can enforce it (coding-standards §4). Two
    answers had to be decided together, and neither is obvious:

    **1. Pin the five, or keep the open dict?** The dict was validated for shape
    only - 20 entries, 50-character keys - so a save could write any key at all
    and "accepts the five existing notification keys" was not something the server
    could mean. Pinned. The trade is explicit: a preference stored under some
    other key can no longer be *set*, only carried (see below).

    **2. What happens to a stored key outside the five?** Refusing the write
    strands a doctor behind a preference they cannot turn off or replace;
    dropping it silently loses a preference the doctor had set. Both are worse
    than preserving it. The doctor's Profile page already promised the third
    behaviour - "a key the server already holds that this list does not know is
    carried through untouched on save" - and that promise was the CLIENT's to
    keep. The page is now four independent section writes, so the promise is the
    server's, or it stops being true for every client that is not the page. So
    unknown STORED keys are preserved verbatim, and only the submitted ones are
    validated.

    The asymmetry is deliberate and is the whole rule: **preserving a stored key
    is not the same as being able to write one.** A caller cannot introduce an
    unknown key through the save (:func:`require_notification_preferences` still
    refuses it) - it can only decline to drop one that was already there, which
    is the difference between a save and a migration.

    A KNOWN stored key the submission omits is dropped, which is what makes a save
    mean "these are my five toggles" rather than "here is one more change". A
    doctor who turns every switch off submits five falses, or an empty selection,
    and ends up with no toggles - an empty submission is a real answer, not an
    absent one.

    ``stored`` is not mutated. It is the read projection's input, and a merge
    that edited it in place would make the row a function of write order. A copy
    is the price of that, and it is cheap: the result is at most five keys plus
    whatever the row already held.

    This also retires the 20-entry / 50-character caps on this field, and the
    reason is the pinning rather than a preference for fewer rules: a save can
    now contribute at most five keys, every one of them a known identifier well
    under 50 characters, so both caps bound nothing that can arrive. What
    survives them - a hand-repaired row carrying junk - is carried, not refused,
    because refusing the save over a key the doctor did not touch would be the
    stranding case above.

    A carried value is copied **verbatim**, not narrowed to a bool, which is why the
    result is typed ``dict[str, object]``. Truthiness is not a reading: a
    hand-repaired row holding ``{"sms": "false"}`` would ``bool()`` to the exact
    opposite of what it says, and a save is the one moment that rewrites the whole
    column - so the narrowing has to happen on the way IN (the model's
    ``dict[str, bool]``) and never on the way through.
    """
    merged: dict[str, object] = {
        key: value for key, value in stored.items() if key not in _NOTIFICATION_KEY_BY_VALUE
    }
    merged.update(require_notification_preferences(submitted))
    return merged


def _selection(raw: Iterable[object]) -> Iterable[object]:
    """Refuse a bare string where a multi-valued selection is required.

    A ``str`` is itself an ``Iterable``, so without this the walk would read
    ``"Monday"`` one character at a time and reject the letter ``M``. One day is
    a one-member selection, so the caller sends a list - and says so here, once,
    instead of leaving every caller to discover the trap.
    """
    if isinstance(raw, (str, bytes)):
        raise InvalidSelectionError(raw)
    return raw


def _require_members(
    raw: Iterable[object],
    by_value: dict[str, _MemberT],
    error: Callable[[object, int, VocabularyRejectionReason], PartnerError],
) -> tuple[_MemberT, ...]:
    """Walk a multi-valued selection member by member, preserving its order.

    One place the member-by-member rule lives, so every multi-valued vocabulary
    reports an offence identically: ``error`` is the vocabulary's own error type,
    constructed with the offending value, its position, and the reason.
    """
    resolved: list[_MemberT] = []
    seen: set[_MemberT] = set()
    for position, value in enumerate(_selection(raw)):
        member = by_value.get(value) if isinstance(value, str) else None
        if member is None:
            raise error(value, position, VocabularyRejectionReason.UNKNOWN)
        if member in seen:
            raise error(value, position, VocabularyRejectionReason.REPEATED)
        seen.add(member)
        resolved.append(member)
    return tuple(resolved)
