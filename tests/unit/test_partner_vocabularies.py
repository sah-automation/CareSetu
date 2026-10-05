"""MOD-002: the doctor practice closed vocabularies (FEAT-004/FEAT-005, #602).

Three pick-lists the domain owns - specialty, consulting languages, consulting
days - each with a validation entry point that refuses a value outside its own
list, and a multi-valued selection validated member by member. Every case below
is a pure domain decision over a value, so the whole suite runs without a
database; the SQL side is deferred to the integration tier (see
tests/integration/README.md) and, for the specialty list, to ticket #606, which
replaces the four-value directory-index column and CHECK.

Membership itself is pinned only where it carries meaning: the four legacy
specialties that predate this ticket, the 22 languages of the Eighth Schedule
of the Constitution of India, and the seven days of the week. The remaining
specialties are a judgement call about small-town practice and are deliberately
not enumerated here, so a later addition is not a test failure.
"""

from __future__ import annotations

from enum import StrEnum

import pytest
from sqlalchemy.dialects.postgresql import JSONB

from modules.partner.domain.exceptions import (
    InvalidConsultingDayError,
    InvalidConsultLanguageError,
    InvalidNotificationKeyError,
    InvalidSelectionError,
    InvalidSpecialtyError,
)
from modules.partner.domain.vocabularies import (
    ConsultingDay,
    ConsultLanguage,
    NotificationPreferenceKey,
    Specialty,
    merge_notification_preferences,
    require_consult_languages,
    require_consulting_days,
    require_notification_preferences,
    require_specialties,
    require_specialty,
)
from modules.partner.schema.models import partner_directory_index, partner_profiles

#: The four values the retired ``ck_partner_directory_index_specialty`` CHECK
#: accepted. They stay members so no existing meaning is lost; #606 replaces
#: the column and the constraint once the field becomes writable and multi-valued.
LEGACY_SPECIALTIES = ("General Physician", "Pediatrician", "Gynecologist", "Dentist")

#: The 22 languages of the Eighth Schedule of the Constitution of India (MHA).
SCHEDULED_LANGUAGES = (
    "Assamese",
    "Bengali",
    "Bodo",
    "Dogri",
    "Gujarati",
    "Hindi",
    "Kannada",
    "Kashmiri",
    "Konkani",
    "Maithili",
    "Malayalam",
    "Manipuri",
    "Marathi",
    "Nepali",
    "Odia",
    "Punjabi",
    "Sanskrit",
    "Santali",
    "Sindhi",
    "Tamil",
    "Telugu",
    "Urdu",
)

WEEK = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def test_specialty_is_a_closed_strenum_of_many_values() -> None:
    assert issubclass(Specialty, StrEnum)
    # Roughly twenty values: the four that used to be the whole list plus the
    # specialties that account for most small-town practice. The pick-list is
    # doctors-only and never free-form (glossary), so membership is the rule.
    assert len(Specialty) >= 20
    for legacy in LEGACY_SPECIALTIES:
        assert legacy in {member.value for member in Specialty}


def test_require_specialty_accepts_a_known_value() -> None:
    assert require_specialty("Pediatrician") is Specialty.PEDIATRICIAN
    # A member round-trips: the entry point is safe to call on a value that
    # has already been through it.
    assert require_specialty(Specialty.DENTIST) is Specialty.DENTIST


def test_require_specialty_rejects_an_unknown_value() -> None:
    with pytest.raises(InvalidSpecialtyError) as excinfo:
        require_specialty("Veterinary Surgeon")
    assert excinfo.value.value == "Veterinary Surgeon"


def test_require_specialty_rejects_a_malformed_value() -> None:
    # The member NAME is not the member VALUE, and an empty/whitespace string is
    # not a member either - the field is never free-form, so no trimming or
    # case-folding rescue is offered.
    for malformed in ("PEDIATRICIAN", "pediatrician", "  Pediatrician  ", "", None, 7):
        with pytest.raises(InvalidSpecialtyError):
            require_specialty(malformed)


def test_consult_language_covers_the_scheduled_languages() -> None:
    assert issubclass(ConsultLanguage, StrEnum)
    values = {member.value for member in ConsultLanguage}
    assert set(SCHEDULED_LANGUAGES) <= values
    # English is not scheduled but is a real consulting language here, so it is
    # a member on purpose rather than an omission.
    assert "English" in values


def test_require_consult_languages_accepts_known_values() -> None:
    assert require_consult_languages(["Hindi", "English"]) == (
        ConsultLanguage.HINDI,
        ConsultLanguage.ENGLISH,
    )
    assert require_consult_languages([]) == ()


def test_require_consult_languages_rejects_an_unknown_value() -> None:
    with pytest.raises(InvalidConsultLanguageError) as excinfo:
        require_consult_languages(["Hindi", "Klingon"])
    assert excinfo.value.value == "Klingon"
    assert excinfo.value.position == 1


def test_require_consult_languages_rejects_a_malformed_value() -> None:
    for malformed in ("hindi", "HINDI", "Hindi ", "", None):
        with pytest.raises(InvalidConsultLanguageError):
            require_consult_languages([malformed])


def test_require_consult_languages_rejects_a_repeated_member() -> None:
    with pytest.raises(InvalidConsultLanguageError):
        require_consult_languages(["Hindi", "Hindi"])


def test_consulting_day_holds_the_seven_days_of_the_week() -> None:
    assert issubclass(ConsultingDay, StrEnum)
    assert {member.value for member in ConsultingDay} == set(WEEK)


def test_require_consulting_days_accepts_known_values() -> None:
    assert require_consulting_days(["Monday", "Saturday"]) == (
        ConsultingDay.MONDAY,
        ConsultingDay.SATURDAY,
    )
    assert require_consulting_days([]) == ()


def test_require_consulting_days_rejects_an_unknown_value() -> None:
    with pytest.raises(InvalidConsultingDayError) as excinfo:
        require_consulting_days(["Monday", "Caturday"])
    assert excinfo.value.value == "Caturday"
    assert excinfo.value.position == 1


def test_require_consulting_days_rejects_a_malformed_value() -> None:
    for malformed in ("monday", "MONDAY", "Mon", "", None):
        with pytest.raises(InvalidConsultingDayError):
            require_consulting_days([malformed])


def test_require_consulting_days_rejects_a_repeated_member() -> None:
    with pytest.raises(InvalidConsultingDayError):
        require_consulting_days(["Monday", "Monday"])


def test_directory_index_specialty_holds_a_whole_selection() -> None:
    # #606 widened the directory entry's specialty column to the multi-valued
    # JSONB array the profile's own ``specialties`` uses. The pre-#606 form of
    # this test read ``column.type.length`` to prove the widened pick-list fit
    # the applied VARCHAR(40); that question is now vacuous, because the column
    # is no longer sized per value at all - a selection of all twenty members is
    # exactly what it is for. Pinned so a silent narrowing back to a scalar column
    # cannot reintroduce a width the vocabulary outgrew.
    assert isinstance(partner_directory_index.c.specialty.type, JSONB)
    # The same shape as the profile's own selection, which is what lets #607 copy
    # one into the other with no conversion and what makes one membership rule
    # serve both columns.
    assert isinstance(partner_profiles.c.specialties.type, JSONB)


def test_require_specialties_accepts_known_values() -> None:
    assert require_specialties(["Pediatrician", "Dermatologist"]) == (
        Specialty.PEDIATRICIAN,
        Specialty.DERMATOLOGIST,
    )
    assert require_specialties([]) == ()


def test_require_specialties_rejects_a_member_outside_the_list() -> None:
    with pytest.raises(InvalidSpecialtyError) as excinfo:
        require_specialties(["Pediatrician", "Veterinary Surgeon"])
    assert excinfo.value.value == "Veterinary Surgeon"
    assert excinfo.value.position == 1


def test_require_specialties_rejects_a_repeated_member() -> None:
    with pytest.raises(InvalidSpecialtyError):
        require_specialties(["Dentist", "Dentist"])


def test_a_multi_valued_entry_point_refuses_a_bare_string() -> None:
    # A bare string is itself iterable, so without the guard the walk would read
    # "Monday" one character at a time and reject the letter "M". A single day
    # is a one-member selection.
    with pytest.raises(InvalidSelectionError):
        require_consulting_days("Monday")
    with pytest.raises(InvalidSelectionError):
        require_consult_languages("Hindi")
    with pytest.raises(InvalidSelectionError):
        require_specialties("Pediatrician")


# --------------------------------------------------------------------------
# Notification preference keys (#610)
# --------------------------------------------------------------------------


def test_notification_key_holds_exactly_the_five_the_page_toggles() -> None:
    # #610 moved the canonical key vocabulary off the doctor Profile page and into
    # the domain. Before this, the server held an untyped dict and the ONLY named
    # list of the five anywhere in the repository was the frontend
    # ``NOTIFICATION_KEYS`` tuple - so "accepts the five existing notification
    # keys" had no server-side meaning at all. Pinned member for member, because
    # the whole point of moving ownership is that the five cannot drift: these are
    # the keys stored preferences already use, and #613 carries the same dict to
    # the public profile.
    assert issubclass(NotificationPreferenceKey, StrEnum)
    assert {member.value for member in NotificationPreferenceKey} == {
        "new_consultations",
        "record_shared",
        "pre_summary_ready",
        "case_updates",
        "credential_status",
    }


def test_require_notification_preferences_accepts_known_keys() -> None:
    submitted = {
        "new_consultations": True,
        "record_shared": False,
        "case_updates": True,
    }

    assert require_notification_preferences(submitted) == submitted
    # An empty selection is a real answer: a doctor who has toggled nothing off yet.
    assert require_notification_preferences({}) == {}


def test_require_notification_preferences_rejects_a_key_outside_the_list() -> None:
    # Unlike the three pick-lists above, a preference is a dict rather than an
    # ordered selection, so there is no position to report and no member name to
    # walk: the key itself is the answer.
    with pytest.raises(InvalidNotificationKeyError) as excinfo:
        require_notification_preferences({"sms": True})

    assert excinfo.value.key == "sms"

    # A member spelled differently is not a member: the list is closed, so nothing
    # is case-folded on the way in.
    with pytest.raises(InvalidNotificationKeyError):
        require_notification_preferences({"New_Consultations": True})


def test_merge_keeps_a_stored_key_the_vocabulary_does_not_know() -> None:
    # The doctor's Profile page carries a stored key it does not render through
    # untouched on save, so a save never silently drops a preference. That promise
    # was the CLIENT's, and the page is about to become four independent section
    # writes - so the guarantee has to be the server's or it stops being true for
    # every client that is not the page.
    #
    # Pinning the five keys must not strand a preference stored before the keys
    # were pinned, and must not lose one either. So the merge PRESERVES unknown
    # stored keys and validates only the submitted ones: neither the pre-existing
    # cap (20 entries of 50 characters) nor the free dict survives on the write
    # path, but the promise does.
    stored = {"sms": True, "new_consultations": False, "legacy_opt_in": True}

    merged = merge_notification_preferences(
        submitted={"new_consultations": True},
        stored=stored,
    )

    assert merged == {
        # The submitted key wins, including when it is turned off.
        "new_consultations": True,
        # Both stored keys the five do not name survive the save untouched.
        "sms": True,
        "legacy_opt_in": True,
    }
    # ``stored`` is not mutated: the row it came from is the read projection's
    # input, and a merge that edited it in place would make the read-back depend
    # on write order.
    assert stored == {"sms": True, "new_consultations": False, "legacy_opt_in": True}


def test_merge_refuses_a_submitted_key_outside_the_list() -> None:
    # Preserving unknown STORED keys must not become a way to WRITE one: the whole
    # contract is that a save can only set one of the five.
    with pytest.raises(InvalidNotificationKeyError) as excinfo:
        merge_notification_preferences(
            submitted={"record_shared": True, "whatsapp": True},
            stored={},
        )

    assert excinfo.value.key == "whatsapp"


def test_merge_clears_everything_when_the_submission_is_empty() -> None:
    # The five keys are the doctor's own toggles, so an empty submission really
    # does mean "none of them on" - and only the stored keys the five do not name
    # survive.
    assert merge_notification_preferences(
        submitted={},
        stored={"new_consultations": True, "sms": True},
    ) == {"sms": True}


def test_merge_never_turns_a_stored_string_into_the_opposite_toggle() -> None:
    # The regression this pins: an earlier draft narrowed every carried value with
    # ``bool(value)``, and ``bool("false")`` is ``True``. A save rewrites the whole
    # column, so one hand-repaired row holding the STRING "false" would have come
    # back switched ON - the doctor asked for no notification and got one.
    #
    # A carried value is copied verbatim instead, which is why the merge returns
    # ``dict[str, object]``: the narrowing belongs on the way in (the model's
    # ``dict[str, bool]``), never on the way through.
    merged = merge_notification_preferences(
        submitted={},
        stored={"sms": "false", "pager": 0},
    )

    assert merged == {"sms": "false", "pager": 0}


def test_require_notification_preferences_does_not_coerce_a_value() -> None:
    # The other half of the same rule, on the submitted side. ``require_`` takes
    # ``Mapping[str, bool]`` and checks KEYS only, so there is no coercion left in
    # the domain to turn a sloppy value into a decision. A caller that has a value
    # it is not sure is a bool has to say so in its types, not let truthiness
    # decide - which is why this is a signature guarantee rather than a runtime
    # check.
    submitted: dict[str, bool] = {"new_consultations": True, "record_shared": False}

    assert require_notification_preferences(submitted) == submitted
    # A copy, so a caller mutating the result cannot reach back into the model.
    assert require_notification_preferences(submitted) is not submitted
