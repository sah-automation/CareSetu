"""MOD-002: the doctor's closed practice vocabularies (FEAT-004/005, ticket #602).

Three pick-lists the domain owns, with the validation that refuses a value
outside its own list:

- :class:`Specialty` - the roughly twenty specialties that account for most
  small-town practice. Doctors only; the field is never free-form (glossary).
- :class:`ConsultLanguage` - the languages a doctor consults in, the languages
  of the Eighth Schedule of the Constitution of India plus English.
- :class:`ConsultingDay` - the seven days of the week.

A closed vocabulary is domain language, not a model constant
(coding-standards §2/§3): the values are declared here, the profile model
mirrors them, and the pre-condition is validated in the domain core, never in
the router. One entry point per field that draws on a list -
:func:`require_specialty` and :func:`require_specialties`,
:func:`require_consult_languages`, :func:`require_consulting_days` - each
raising a named :class:`~modules.partner.domain.exceptions.PartnerError`
subclass, so a value outside a list is an explicit rejection rather than
something that persists and can never be filtered on. A multi-valued selection
is validated member by member and names the offending position.

Values are stable, machine-readable keys. Display labels in either locale are
the section writers' job, not this module's.

``Specialty`` moved here from ``domain/credentials.py`` (#602): the practice a
doctor declares is not a credential document, and the two had outgrown one file.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from enum import StrEnum
from typing import TypeVar

from modules.partner.domain.exceptions import (
    InvalidConsultingDayError,
    InvalidConsultLanguageError,
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


_SPECIALTY_BY_VALUE: dict[str, Specialty] = {member.value: member for member in Specialty}
_CONSULT_LANGUAGE_BY_VALUE: dict[str, ConsultLanguage] = {
    member.value: member for member in ConsultLanguage
}
_CONSULTING_DAY_BY_VALUE: dict[str, ConsultingDay] = {
    member.value: member for member in ConsultingDay
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
    ``"Hindi "`` is refused rather than tidied. #611 retires the model validator
    and leaves this as the only rule.
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
