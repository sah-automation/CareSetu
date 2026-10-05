from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from modules.partner.directory_facade import PERI_URBAN_RADIUS_KM
from modules.partner.doctor_profile_models import (
    DoctorProfileAboutUpdate,
    DoctorProfileAddressUpdate,
    DoctorProfileNotificationUpdate,
    DoctorProfilePracticeUpdate,
)
from modules.partner.domain.exceptions import (
    InvalidConsultingDayError,
    InvalidConsultLanguageError,
    InvalidNotificationKeyError,
    InvalidSpecialtyError,
    PracticePinUnresolvedError,
)
from modules.partner.domain.practice_position import PinResolutionReason
from modules.partner.domain.vocabularies import (
    ConsultingDay,
    ConsultLanguage,
    Specialty,
)
from modules.partner.facade import (
    DoctorProfileNotAllowedError,
    DoctorProfilePhotoNotFoundError,
    DoctorProfilePhotoStoreUnavailableError,
    DoctorProfilePhotoValidationError,
    PartnerFacade,
)
from modules.profile_media.facade import ProfileMediaStoreError

_JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 64
_WEBP_BYTES = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 64

_NOW = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)


class _Row:
    def __init__(self, **values: object) -> None:
        self.__dict__.update(values)


class _Result:
    def __init__(self, *, row: object = None, rows: list[object] | None = None) -> None:
        self._row = row
        self._rows = rows or []

    def first(self) -> object:
        return self._row

    def all(self) -> list[object]:
        return self._rows


class _Cache:
    def __init__(self) -> None:
        self.visibility_changes = 0

    async def directory_visibility_changed(self) -> None:
        self.visibility_changes += 1


class _MediaStore:
    def __init__(self) -> None:
        self.saved: list[tuple[bytes, int, str]] = []
        self.save_attempts = 0
        self.save_error: Exception | None = None
        self.read_keys: list[str] = []
        self.deleted: list[str] = []
        self.stored: dict[str, bytes] = {}
        self.read_error: Exception | None = None

    async def save(self, *, data: bytes, subject_id: int, prefix: str) -> str:
        self.save_attempts += 1
        if self.save_error is not None:
            raise self.save_error
        self.saved.append((data, subject_id, prefix))
        key = f"{prefix}/{subject_id}/new-photo.enc"
        self.stored[key] = data
        return key

    async def read(self, *, object_key: str) -> bytes:
        self.read_keys.append(object_key)
        if self.read_error is not None:
            raise self.read_error
        return self.stored[object_key]

    async def delete(self, *, object_key: str) -> None:
        self.deleted.append(object_key)
        self.stored.pop(object_key, None)

    async def close(self) -> None:
        return None


def _connection(results: list[object]) -> AsyncMock:
    connection = AsyncMock()
    connection.execute = AsyncMock(side_effect=results)
    return connection


def _facade(
    connection: AsyncMock,
    *,
    media_store: _MediaStore | None = None,
) -> PartnerFacade:
    engine = MagicMock(spec=AsyncEngine)
    engine.begin.return_value.__aenter__.return_value = connection
    engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)
    return PartnerFacade(
        engine=engine,
        clock=lambda: _NOW,
        profile_media_store=media_store,
        doctor_profile_photo_max_bytes=5 * 1024 * 1024,
    )


@pytest.mark.asyncio
async def test_get_doctor_profile_projects_private_fields_and_derived_status() -> None:
    expires_at = _NOW + timedelta(days=180)
    connection = _connection(
        [
            _Result(
                row=_Row(
                    partner_id=12,
                    partner_type="doctor",
                    status="Active",
                    photo_ref="doctor/12/photo.enc",
                    practice_name="Anita Verma",
                    clinic_name="Shanti Clinic",
                    # #608: read off the PROFILE ROW, multi-valued, in the
                    # doctor's declared order - not a single representative value
                    # outer-joined from the directory entry.
                    specialties=["Pediatrician", "General Physician"],
                    practice_address="Main Road, Daltonganj",
                    # #609: a registration-era row carries only the display column.
                    # The structured parts read empty rather than being parsed back
                    # out of the assembled string, which is what makes the projection
                    # honest about what was actually declared.
                    address_line=None,
                    address_landmark=None,
                    address_locality=None,
                    address_city=None,
                    address_pin=None,
                    practice_latitude=24.483,
                    practice_longitude=87.433,
                    area_name="Daltonganj",
                    languages=["English", "Hindi"],
                    experience_years=12,
                    about="Primary care physician.",
                    consultation_fee_paise=50000,
                    consulting_days=["Monday", "Tuesday", "Saturday"],
                    consulting_hours="Monday to Friday, 9 AM to 5 PM",
                    notification_preferences={"appointment_reminders": True, "sms": True},
                )
            ),
            _Result(
                rows=[
                    _Row(
                        credential_type="medical_registration",
                        verified=True,
                        expires_at=expires_at,
                        revoked_at=None,
                        invalidation_reason=None,
                    ),
                    _Row(
                        credential_type="qualification_certificate",
                        verified=False,
                        expires_at=None,
                        revoked_at=None,
                        invalidation_reason=None,
                    ),
                ]
            ),
        ]
    )
    facade = _facade(connection)

    profile = await facade.get_doctor_profile(12)

    assert profile.partner_id == 12
    assert profile.photo_ref == "doctor/12/photo.enc"
    assert profile.practice_name == "Anita Verma"
    assert profile.clinic_name == "Shanti Clinic"
    assert profile.specialties == ["Pediatrician", "General Physician"]
    assert profile.verified is True
    assert profile.practice_address == "Main Road, Daltonganj"
    assert profile.practice_latitude == pytest.approx(24.483)
    assert profile.practice_longitude == pytest.approx(87.433)
    assert profile.area == "Daltonganj"
    assert profile.languages == ["English", "Hindi"]
    assert profile.experience_years == 12
    assert profile.about == "Primary care physician."
    assert profile.consultation_fee == 50000
    assert profile.consulting_days == ["Monday", "Tuesday", "Saturday"]
    assert profile.consulting_hours == "Monday to Friday, 9 AM to 5 PM"
    assert profile.notification_preferences == {"appointment_reminders": True, "sms": True}
    assert [credential.model_dump(mode="json") for credential in profile.credentials] == [
        {
            "credential_type": "medical_registration",
            "status": "verified",
            "expires_at": "2027-03-24T12:00:00Z",
        },
        {
            "credential_type": "qualification_certificate",
            "status": "pending",
            "expires_at": None,
        },
    ]


def _projected_profile_values() -> dict[str, object]:
    """

    Trace: FEAT-005 (Provider Profiles and Credential Display).
    Every column ``get_doctor_profile`` reads, at neutral values.

        A full projection row so a test about ONE field does not have to restate the
        other thirty, and so a column added to the projection later fails these tests
        loudly rather than silently reading ``None``.
    """
    return {
        "partner_id": 12,
        "partner_type": "doctor",
        "status": "Active",
        "photo_ref": None,
        "practice_name": "Anita Verma",
        "clinic_name": "Shanti Clinic",
        "specialties": ["Pediatrician", "General Physician"],
        "practice_address": "Main Road, Daltonganj",
        "address_line": None,
        "address_landmark": None,
        "address_locality": None,
        "address_city": None,
        "address_pin": None,
        "practice_latitude": 24.483,
        "practice_longitude": 87.433,
        "area_name": "Daltonganj",
        "languages": ["English", "Hindi"],
        "experience_years": 12,
        "about": "Primary care physician.",
        "consultation_fee_paise": 50000,
        "consulting_days": ["Monday", "Tuesday", "Saturday"],
        "consulting_hours": "Monday to Friday, 9 AM to 5 PM",
        "notification_preferences": {"appointment_reminders": True, "sms": True},
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        # A stored key the closed five do not name is still a real preference the
        # doctor set, and the merge carries it on every save - so the read shows it
        # rather than hiding a switch the doctor can act on.
        pytest.param(
            {"legacy_whatsapp": True},
            {"legacy_whatsapp": True},
            id="unknown-key-real-bool",
        ),
        # ``{"sms": "false"}`` is a hand-repaired row meaning OFF. Truthiness is
        # not a reading - bool("false") is True - so it reads as the OFF the
        # doctor wrote.
        pytest.param({"sms": "false"}, {"sms": False}, id="string-false-reads-off"),
        pytest.param({"n": 0}, {"n": False}, id="integer-zero-reads-off"),
        # An unrenderable value is dropped from the VIEW ONLY: the row still holds
        # it and the merge still carries it on the next save.
        pytest.param(
            {"sms": "banana", "record_shared": True},
            {"record_shared": True},
            id="unreadable-dropped-not-raised",
        ),
        pytest.param({"sms": None}, {}, id="null-dropped"),
        pytest.param("not-a-mapping", {}, id="non-mapping-column"),
    ],
)
async def test_get_doctor_profile_survives_a_stored_preference_it_cannot_render(
    stored: object,
    expected: dict[str, bool],
) -> None:
    """#623: one unrenderable entry must not take down the doctor's whole profile.

    ``notification_preferences`` is a JSON blob whose stored keys the merge
    deliberately carries verbatim, so a hand-repaired row is a supported state,
    not an impossible one. Projecting it straight into the view's
    ``dict[str, bool]`` made ``bool_parsing`` raise inside the view's own
    validation - and the doctor's name, address, credentials and all four cards
    stopped rendering because one notification entry was not a bool. The entry
    is dropped from the view instead; nothing is lost from the row and no save
    is refused.
    """
    connection = _connection(
        [
            _Result(
                row=_Row(
                    **{**_projected_profile_values(), "notification_preferences": stored},
                )
            ),
            _Result(rows=[]),
        ]
    )
    facade = _facade(connection)

    profile = await facade.get_doctor_profile(12)

    assert profile.notification_preferences == expected
    # The rest of the profile is unaffected, which is the whole point: the failure
    # this fixes was never about the notification dict.
    assert profile.practice_name == "Anita Verma"
    assert profile.partner_id == 12


def _practice_read_back_row() -> _Row:
    """The row ``get_doctor_profile`` returns after the practice write commits."""
    return _Row(
        partner_id=12,
        partner_type="doctor",
        status="Active",
        photo_ref=None,
        practice_name="Anita Verma",
        clinic_name="Shanti Clinic",
        specialties=["Pediatrician", "General Physician"],
        practice_address="Main Road, Daltonganj",
        address_line=None,
        address_landmark=None,
        address_locality=None,
        address_city=None,
        address_pin=None,
        practice_latitude=24.483,
        practice_longitude=87.433,
        area_name="Daltonganj",
        languages=["English", "Hindi"],
        experience_years=12,
        about="Primary care physician.",
        consultation_fee_paise=50000,
        consulting_days=["Monday", "Tuesday"],
        consulting_hours="Monday to Friday, 9 AM to 5 PM",
        notification_preferences={"appointment_reminders": True, "sms": True},
    )


@pytest.mark.asyncio
async def test_update_doctor_practice_writes_only_its_own_columns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#608: the practice write touches its own columns and no one else's.

    Three assertions, and the third is the one that matters beyond the four-way
    split. The written COLUMN set proves the save stays inside its own card: the
    address, the languages, the about text, the consulting days, the consulting
    hours and the notification preferences are all absent, so a doctor editing
    their practice card cannot move a field the card they are looking at does not
    show. The written TABLE set then proves the save stays on the doctor's own
    private row plus the ONE shared projection write - the directory entry - which
    carries the selection onto the column ``search_directory`` filters on. The
    third assertion is that the refresh is the only thing that touched the entry,
    and specifically that it never carried a listed flag or a verified derivation.
    """
    update = DoctorProfilePracticeUpdate(
        full_name="Anita Verma",
        clinic_name="Shanti Clinic",
        specialties=["Pediatrician", "General Physician"],
        experience_years=12,
    )
    connection = _connection(
        [
            _Result(row=_Row(partner_type="doctor", status="Active")),
            _Result(),
            _Result(),
            _Result(row=_practice_read_back_row()),
            _Result(
                rows=[
                    _Row(
                        credential_type="medical_registration",
                        verified=True,
                        expires_at=_NOW + timedelta(days=180),
                        revoked_at=None,
                        invalidation_reason=None,
                    )
                ]
            ),
        ]
    )
    facade = _facade(connection)
    cache = _Cache()
    facade._directory_cache = cache
    # The refresh owns its own namespace flush (ADR-0011) rather than each caller
    # remembering it, so the flush is asserted HERE, at the shared operation, and
    # the two callers are free to be added later without anyone re-deriving it.
    flushes: list[int] = []

    async def _record_flush() -> None:
        flushes.append(1)

    monkeypatch.setattr(
        "modules.partner.credential_validity.directory_visibility_changed",
        _record_flush,
    )

    profile = await facade.update_doctor_practice(12, update)

    # The read-back is what the doctor next GET would serve, straight off the row
    # the write just landed - the selection whole, not one representative member.
    assert profile.practice_name == "Anita Verma"
    assert profile.clinic_name == "Shanti Clinic"
    assert profile.specialties == ["Pediatrician", "General Physician"]
    assert profile.experience_years == 12

    statements = [call.args[0] for call in connection.execute.await_args_list]
    recheck, profile_update, refresh = statements[0], statements[1], statements[2]
    # The active-doctor recheck is a row lock, not a bare read: a concurrent
    # deactivation between the edge guard and this write must not slip past it.
    assert "FOR UPDATE" in str(recheck)
    written_tables = {
        statement.table.name
        for statement in statements
        if getattr(statement, "table", None) is not None
    }
    assert written_tables == {"partner_profiles", "partner_directory_index"}
    assert profile_update.table.name == "partner_profiles"
    # ``full_name`` is the wire name for the ``practice_name`` column; every other
    # field is name-for-name. ``updated_at`` is the server-written touch.
    assert set(profile_update._values) == {
        "practice_name",
        "clinic_name",
        "specialties",
        "experience_years",
        "updated_at",
    }
    assert profile_update._values["practice_name"].value == "Anita Verma"
    assert profile_update._values["clinic_name"].value == "Shanti Clinic"
    assert profile_update._values["specialties"].value == ["Pediatrician", "General Physician"]
    assert profile_update._values["experience_years"].value == 12
    for another_cards_column in (
        "practice_address",
        "practice_latitude",
        "practice_longitude",
        "languages",
        "about",
        "consulting_days",
        "consulting_hours",
        "availability",
        "notification_preferences",
        "consultation_fee_paise",
    ):
        assert another_cards_column not in profile_update._values
    # The one write the save makes outside its own card is the shared refresh
    # (#607), and it writes the position and the selection. Without it the doctor's
    # public profile would carry the selection (it reads the profile row) while
    # directory search kept filtering on the stale index value - two public
    # surfaces disagreeing about one doctor, which is the defect #612 fixed the
    # read path for.
    assert refresh.table.name == "partner_directory_index"
    # The refresh's whole job on this path is the selection: the upsert carries the
    # ``specialty`` column on insert AND on conflict, so an entry written by an
    # earlier save is brought forward rather than left on its old value.
    assert "specialty = excluded.specialty" in str(refresh)
    # The safety property the operator approval path depends on: the refresh is
    # reachable from a doctor's own save, so it must never move the listed flag or
    # any verified derivation. A doctor editing their practice card cannot make
    # themselves listed.
    assert "is_active" not in str(refresh)
    # The refresh owns its own cache flush, so the entry a patient searches is
    # rebuilt from the row this save just wrote rather than from the pre-save one.
    # Without it a specialty change would keep serving the previous selection out
    # of Redis for a whole TTL, which is the exact staleness ADR-0011 permits and
    # the reason the flush lives inside the shared operation.
    assert len(flushes) == 1
    assert cache.visibility_changes == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("partner_type", "status"),
    [("doctor", "Registered"), ("lab", "Active")],
    ids=["not-active", "not-a-doctor"],
)
async def test_update_doctor_practice_refuses_a_partner_that_is_not_an_active_doctor(
    partner_type: str,
    status: str,
) -> None:
    """#608: the refusal happens before any write, under the row lock.

    ``execute.await_count == 1`` is the whole assertion: the locked recheck ran,
    the rule refused, and the ``UPDATE`` was never issued - so a partner who is not
    an ``[Active]`` doctor cannot have written a single practice column.
    """
    connection = _connection(
        [
            _Result(row=_Row(partner_type=partner_type, status=status)),
        ]
    )
    facade = _facade(connection)

    with pytest.raises(DoctorProfileNotAllowedError):
        await facade.update_doctor_practice(
            12,
            DoctorProfilePracticeUpdate(full_name="Anita Verma"),
        )

    assert connection.execute.await_count == 1
    recheck = connection.execute.await_args_list[0].args[0]
    assert "FOR UPDATE" in str(recheck)


def test_practice_update_rejects_a_specialty_off_the_closed_list() -> None:
    """#608: the closed pick-list is enforced before the write is even constructible.

    The model's validator delegates to the domain's ``require_specialties``, so a
    value outside the list cannot reach the facade at all - the write is refused
    at the boundary, naming the offending member and its position. #602 owns the
    list and the error type; this is the proof the practice card is wired to them
    rather than carrying its own copy of either.
    """
    with pytest.raises(InvalidSpecialtyError) as rejected:
        DoctorProfilePracticeUpdate(
            full_name="Anita Verma",
            specialties=["General Physician", "Homeopathy"],
        )

    assert rejected.value.value == "Homeopathy"
    assert rejected.value.position == 1

    # A member spelled differently is not a member: the list is closed, so nothing
    # is case-folded or tidied on the way in.
    with pytest.raises(InvalidSpecialtyError):
        DoctorProfilePracticeUpdate(
            full_name="Anita Verma",
            specialties=["general physician"],
        )

    # A repeated selection entry is a data-entry slip, not a second specialty.
    with pytest.raises(InvalidSpecialtyError):
        DoctorProfilePracticeUpdate(
            full_name="Anita Verma",
            specialties=["Pediatrician", "Pediatrician"],
        )


def test_practice_update_names_the_member_an_oversized_selection_broke() -> None:
    """#608: the closed-list rule reports the member, not a bare length failure.

    A ``max_length`` on the field would be checked first and would refuse an
    oversized selection as a ``too_long`` naming no member - shadowing the only
    rule this field has. So the field carries no cap and the closed list is the
    bound: a selection longer than the whole pick-list is caught as the repeat it
    necessarily contains, with the position reported.
    """
    every_member = [member.value for member in Specialty]

    with pytest.raises(InvalidSpecialtyError) as rejected:
        DoctorProfilePracticeUpdate(
            full_name="Anita Verma",
            specialties=[*every_member, "Pediatrician"],
        )

    assert rejected.value.value == "Pediatrician"
    assert rejected.value.position == len(every_member)

    # Every member at once is the longest legal selection, and it is accepted -
    # the cap is the vocabulary's own size, never smaller.
    assert (
        DoctorProfilePracticeUpdate(
            full_name="Anita Verma",
            specialties=every_member,
        ).specialties
        == every_member
    )


@pytest.mark.asyncio
async def test_update_doctor_address_resolves_the_pin_and_writes_the_derived_position() -> None:
    """#609: the position is DERIVED from the declared PIN, never supplied.

    The four statements are the write's whole contract, in order:

    1. the row-locked active-doctor recheck, so a deactivation landing after the
       edge guard cannot slip past it;
    2. the one indexed primary-key hit on the bundled centroid table;
    3. the profile write - the declared parts, the assembled display string and
       the resolved coordinates;
    4. the shared directory-entry refresh, INSIDE this transaction, so the entry
       reads the position this statement just wrote (it reads the profile row by
       ``INSERT ... FROM SELECT``, which is the whole correctness argument for
       doing both in one transaction).

    ``written_tables`` naming both tables is the assertion that the listing
    actually moved: a profile-only write would leave ``search_directory``
    returning the old position until the entry's next refresh.
    """
    update = DoctorProfileAddressUpdate(
        address_line="12 Main Road",
        landmark="Near the water tower",
        locality="Daltonganj",
        city="Daltonganj",
        pin_code="826001",
    )
    connection = _connection(
        [
            _Result(row=_Row(partner_type="doctor", status="Active")),
            _Result(row=_centroid_row("826001", 24.05, 84.09)),
            _Result(),
            _Result(),
            _Result(row=_address_read_back_row()),
            _Result(rows=[]),
        ]
    )
    facade = _facade(connection)

    profile = await facade.update_doctor_address(12, update)

    assert profile.address_line == "12 Main Road"
    assert profile.pin_code == "826001"
    assert profile.practice_address == (
        "12 Main Road, Near the water tower, Daltonganj, Daltonganj, 826001"
    )
    assert profile.practice_latitude == pytest.approx(24.05)
    assert profile.practice_longitude == pytest.approx(84.09)

    statements = [call.args[0] for call in connection.execute.await_args_list]
    recheck, centroid_lookup, profile_update, refresh = statements[:4]
    assert "FOR UPDATE" in str(recheck)
    # The lookup is an exact primary-key hit bound to the code the doctor declared,
    # and it asks for the three columns the decision needs - nothing else off the
    # reference row.
    assert "partner.partner_pin_centroids.pin = :" in str(centroid_lookup)
    assert next(iter(centroid_lookup.compile().params.values())) == "826001"
    written_tables = {
        statement.table.name
        for statement in statements
        if getattr(statement, "table", None) is not None
    }
    assert written_tables == {"partner_profiles", "partner_directory_index"}
    assert profile_update.table.name == "partner_profiles"
    assert refresh.table.name == "partner_directory_index"
    assert set(profile_update._values) == {
        "address_line",
        "address_landmark",
        "address_locality",
        "address_city",
        "address_pin",
        "practice_address",
        "practice_latitude",
        "practice_longitude",
        "updated_at",
    }
    assert profile_update._values["address_pin"].value == "826001"
    assert profile_update._values["practice_address"].value == profile.practice_address
    # The derived position is the centroid's own point, in the columns' own
    # precision - not rounded, snapped or re-geocoded.
    assert float(profile_update._values["practice_latitude"].value) == pytest.approx(24.05)
    assert float(profile_update._values["practice_longitude"].value) == pytest.approx(84.09)
    # Nothing outside this card moves: no name, no clinic, no selection, no fee.
    for another_cards_column in (
        "practice_name",
        "clinic_name",
        "specialties",
        "experience_years",
        "languages",
        "about",
        "consulting_days",
        "consulting_hours",
        "availability",
        "notification_preferences",
        "consultation_fee_paise",
        "service_area_id",
    ):
        assert another_cards_column not in profile_update._values


def _centroid_row(pin_code: str, latitude: float, longitude: float) -> _Row:
    """One ``partner_pin_centroids`` row, as the driver hands it over.

    The coordinates arrive as ``Decimal`` off a ``Numeric`` column, which is why
    ``PinCentroid`` is typed ``float``: the conversion happens here, at the
    boundary the caller owns.
    """
    return _Row(pin=pin_code, latitude=Decimal(str(latitude)), longitude=Decimal(str(longitude)))


def _address_read_back_row() -> _Row:
    """The row ``get_doctor_profile`` returns after the address write commits."""
    return _Row(
        partner_id=12,
        partner_type="doctor",
        status="Active",
        photo_ref=None,
        practice_name="Anita Verma",
        clinic_name="Shanti Clinic",
        specialties=["Pediatrician"],
        practice_address="12 Main Road, Near the water tower, Daltonganj, Daltonganj, 826001",
        address_line="12 Main Road",
        address_landmark="Near the water tower",
        address_locality="Daltonganj",
        address_city="Daltonganj",
        address_pin="826001",
        practice_latitude=24.05,
        practice_longitude=84.09,
        area_name="Daltonganj",
        languages=["English", "Hindi"],
        experience_years=12,
        about="Primary care physician.",
        consultation_fee_paise=50000,
        consulting_days=["Monday", "Tuesday"],
        consulting_hours="Monday to Friday, 9 AM to 5 PM",
        notification_preferences={"appointment_reminders": True},
    )


@pytest.mark.asyncio
async def test_update_doctor_address_rejects_a_pin_absent_from_the_dataset() -> None:
    """#609: an unlisted PIN refuses this write and writes nothing at all.

    ``execute.await_count == 2`` is the whole assertion: the locked recheck ran,
    the lookup ran, the decision refused - and no ``UPDATE`` and no directory
    refresh were ever issued. Acceptance criterion 6 is explicit that the data gap
    is a follow-up rather than something to work around, so there is no fallback
    position and no row written anywhere to compensate.
    """
    connection = _connection(
        [
            _Result(row=_Row(partner_type="doctor", status="Active")),
            _Result(row=None),
        ]
    )
    facade = _facade(connection)

    with pytest.raises(PracticePinUnresolvedError) as refused:
        await facade.update_doctor_address(12, DoctorProfileAddressUpdate(pin_code="999999"))

    assert refused.value.reason is PinResolutionReason.UNKNOWN
    assert connection.execute.await_count == 2


@pytest.mark.asyncio
async def test_update_doctor_address_rejects_a_pin_that_is_not_a_pin_code() -> None:
    """#609: the format rule is the domain's, and it refuses before any write too.

    No length or pattern bound sits on the request model, deliberately: a bound
    there would be checked first and would refuse an over-long value as a bare
    ``too_long``, shadowing the one rule the field actually has and splitting the
    malformed case in two on the wire. ``resolve_pin_code`` owns both the length
    and the character-class failure, and neither can be told from the other by the
    caller - which is why the field-level detail says the PIN is not a PIN code
    rather than guessing which rule was broken.
    """
    connection = _connection(
        [
            _Result(row=_Row(partner_type="doctor", status="Active")),
            _Result(row=None),
        ]
    )
    facade = _facade(connection)

    with pytest.raises(PracticePinUnresolvedError) as refused:
        await facade.update_doctor_address(12, DoctorProfileAddressUpdate(pin_code="82 6001"))

    assert refused.value.reason is PinResolutionReason.MALFORMED
    assert connection.execute.await_count == 2


@pytest.mark.asyncio
async def test_update_doctor_address_refuses_a_centroid_keyed_to_another_pin() -> None:
    """#609: a centroid for a different code is not a resolution of the declared one.

    The lookup is exact, so this can only happen if a caller supplies a mismatched
    row - and the refusal is what keeps the possibility of attaching a doctor's
    practice to someone else's neighbourhood from ever becoming a misplaced
    doctor. ``await_count == 2`` proves it refuses rather than writing the point.
    """
    connection = _connection(
        [
            _Result(row=_Row(partner_type="doctor", status="Active")),
            _Result(row=_centroid_row("826002", 24.05, 84.09)),
        ]
    )
    facade = _facade(connection)

    with pytest.raises(PracticePinUnresolvedError) as refused:
        await facade.update_doctor_address(12, DoctorProfileAddressUpdate(pin_code="826001"))

    assert refused.value.reason is PinResolutionReason.UNKNOWN
    assert connection.execute.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("latitude", "longitude", "expected_outside"),
    [
        (24.05, 84.09, False),
        (24.46, 87.44, True),
    ],
    ids=["inside-the-belt", "far-outside-the-belt"],
)
async def test_update_doctor_address_warns_outside_the_belt_and_saves_anyway(
    latitude: float,
    longitude: float,
    expected_outside: bool,
) -> None:
    """#609: the belt is a WARNING, never a refusal, on both sides of the boundary.

    A doctor who corrects a wrong sign-up PIN must not be blocked by where they
    turned out to be, so both cases take the same four statements and return 200 -
    the far one differing only in the flag and the distance it reports. The
    boundary is passed in from the directory sub-facade's own constant, which is
    what keeps the belt one boundary rather than two (#603).
    """
    connection = _connection(
        [
            _Result(row=_Row(partner_type="doctor", status="Active")),
            _Result(row=_centroid_row("826001", latitude, longitude)),
            _Result(),
            _Result(),
            _Result(row=_address_read_back_row()),
            _Result(rows=[]),
        ]
    )
    facade = _facade(connection)

    profile = await facade.update_doctor_address(12, DoctorProfileAddressUpdate(pin_code="826001"))

    assert profile.outside_peri_urban_belt is expected_outside
    assert profile.distance_from_belt_centre_km is not None
    if expected_outside:
        assert profile.distance_from_belt_centre_km > PERI_URBAN_RADIUS_KM
    else:
        assert profile.distance_from_belt_centre_km <= PERI_URBAN_RADIUS_KM
    # Saved either way: the position landed on the row regardless of the warning.
    assert connection.execute.await_count == 6


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("partner_type", "status"),
    [("doctor", "Registered"), ("lab", "Active")],
    ids=["not-active", "not-a-doctor"],
)
async def test_update_doctor_address_refuses_a_partner_that_is_not_an_active_doctor(
    partner_type: str,
    status: str,
) -> None:
    """#609: the refusal happens before the PIN is even looked up.

    ``await_count == 1`` proves the order: the locked recheck refused, so the
    centroid table was never read and no column was written. A partner who is not
    an ``[Active]`` doctor learns nothing about the centroid dataset either.
    """
    connection = _connection(
        [
            _Result(row=_Row(partner_type=partner_type, status=status)),
        ]
    )
    facade = _facade(connection)

    with pytest.raises(DoctorProfileNotAllowedError):
        await facade.update_doctor_address(12, DoctorProfileAddressUpdate(pin_code="826001"))

    assert connection.execute.await_count == 1


# --------------------------------------------------------------------------
# #610 - the About and Notification section writes
# --------------------------------------------------------------------------


def _about_read_back_row() -> _Row:
    """The row ``get_doctor_profile`` returns after the about write commits."""
    return _Row(
        partner_id=12,
        partner_type="doctor",
        status="Active",
        photo_ref=None,
        practice_name="Anita Verma",
        clinic_name="Shanti Clinic",
        specialties=["Pediatrician", "General Physician"],
        practice_address="Main Road, Daltonganj",
        address_line=None,
        address_landmark=None,
        address_locality=None,
        address_city=None,
        address_pin=None,
        practice_latitude=24.483,
        practice_longitude=87.433,
        area_name="Daltonganj",
        languages=["Hindi", "English"],
        experience_years=12,
        about="Twenty years of primary care in the block.",
        consultation_fee_paise=50000,
        consulting_days=["Monday", "Tuesday", "Saturday"],
        consulting_hours="Weekdays 9 AM to 5 PM; Saturday morning clinic only.",
        notification_preferences={},
    )


@pytest.mark.asyncio
async def test_update_doctor_about_writes_only_its_own_columns() -> None:
    """#610: the about write touches its own columns and no one else's.

    The same two assertions as its siblings, on the card that splits a field
    rather than moving one. The written TABLE set proves the save stays on the
    doctor's own private row. The written COLUMN set then proves it stays inside
    the about card - and the shape of that set is the availability SPLIT: the new
    ``consulting_days`` and ``consulting_hours`` columns are present, and the
    ``availability`` column they supersede is not written at all, because nothing
    new addresses it and #611 retires the write that still does.
    """
    update = DoctorProfileAboutUpdate(
        about="Twenty years of primary care in the block.",
        languages=["Hindi", "English"],
        consulting_days=["Monday", "Tuesday", "Saturday"],
        consulting_hours="Weekdays 9 AM to 5 PM; Saturday morning clinic only.",
    )
    connection = _connection(
        [
            _Result(row=_Row(partner_type="doctor", status="Active")),
            _Result(),
            _Result(row=_about_read_back_row()),
            _Result(rows=[]),
        ]
    )
    facade = _facade(connection)
    cache = _Cache()
    facade._directory_cache = cache

    profile = await facade.update_doctor_about(12, update)

    # The read-back is what the doctor's next GET would serve, straight off the row
    # the write just landed.
    assert profile.about == "Twenty years of primary care in the block."
    assert profile.languages == ["Hindi", "English"]
    assert profile.consulting_days == ["Monday", "Tuesday", "Saturday"]
    assert profile.consulting_hours == "Weekdays 9 AM to 5 PM; Saturday morning clinic only."

    statements = [call.args[0] for call in connection.execute.await_args_list]
    recheck, profile_update = statements[0], statements[1]
    # The active-doctor recheck is a row lock, not a bare read.
    assert "FOR UPDATE" in str(recheck)
    written_tables = {
        statement.table.name
        for statement in statements
        if getattr(statement, "table", None) is not None
    }
    assert written_tables == {"partner_profiles"}
    # Every wire field is name-for-name with its column, so ``model_dump()`` is the
    # whole payload - there is no mapping to get wrong.
    assert set(profile_update._values) == {
        "about",
        "languages",
        "consulting_days",
        "consulting_hours",
        "updated_at",
    }
    assert profile_update._values["about"].value == "Twenty years of primary care in the block."
    # The closed lists reach the column as their resolved members, in the doctor's
    # declared order - the same order the read-back and every later match use.
    assert profile_update._values["languages"].value == ["Hindi", "English"]
    assert profile_update._values["consulting_days"].value == [
        "Monday",
        "Tuesday",
        "Saturday",
    ]
    # The superseded column is absent, not written alongside its replacement.
    assert "availability" not in profile_update._values
    for another_cards_column in (
        "practice_name",
        "clinic_name",
        "specialties",
        "experience_years",
        "practice_address",
        "practice_latitude",
        "practice_longitude",
        "notification_preferences",
        "consultation_fee_paise",
        "service_area_id",
    ):
        assert another_cards_column not in profile_update._values
    # Nothing here is a search filter or a positioning input, so no directory entry
    # is refreshed and no search cache is flushed. The one filterable field a doctor
    # might expect to move here - the specialty - belongs to the practice card.
            _Result(
                row=_Row(
                    partner_type="doctor",
                    status="Registered",
                    photo_ref=None,
                )
            ),
        ]
    )
    facade = _facade(connection)

    with pytest.raises(DoctorProfileNotAllowedError):
        await facade.get_doctor_profile(12)

    assert connection.execute.await_count == 1


@pytest.mark.asyncio
async def test_registered_doctor_cannot_upload_or_read_photo() -> None:
    connection = _connection(
        [
            _Result(
                row=_Row(
                    partner_type="doctor",
                    status="Registered",
                    photo_ref=None,
                )
            ),
            _Result(
                row=_Row(
                    partner_type="doctor",
                    status="Registered",
                    photo_ref=None,
                )
            ),
        ]
    )
    store = _MediaStore()
    facade = _facade(connection, media_store=store)

    with pytest.raises(DoctorProfileNotAllowedError):
        await facade.update_doctor_photo(
            12,
            media_type="image/jpeg",
            data=_JPEG_BYTES,
        )
    with pytest.raises(DoctorProfileNotAllowedError):
        await facade.get_doctor_photo(12)

    assert store.saved == []
    assert store.read_keys == []


@pytest.mark.asyncio
async def test_registered_doctor_cannot_delete_photo() -> None:
    connection = _connection(
        [
            _Result(
                row=_Row(
                    partner_type="doctor",
                    status="Registered",
                    photo_ref="doctor/12/photo.enc",
                )
            )
        ]
    )
    store = _MediaStore()
    facade = _facade(connection, media_store=store)

    with pytest.raises(DoctorProfileNotAllowedError):
        await facade.delete_doctor_photo(12)

    assert store.deleted == []


@pytest.mark.asyncio
async def test_update_doctor_photo_maps_permanent_storage_error() -> None:
    connection = _connection(
        [
            _Result(
                row=_Row(
                    partner_type="doctor",
                    status="Active",
                    photo_ref=None,
                )
            )
        ]
    )
    store = _MediaStore()
    store.save_error = ProfileMediaStoreError(
        "storage rejected object",
        retryable=False,
    )
    facade = _facade(connection, media_store=store)

    with pytest.raises(DoctorProfilePhotoStoreUnavailableError):
        await facade.update_doctor_photo(
            12,
            media_type="image/jpeg",
            data=_JPEG_BYTES,
        )

    assert store.save_attempts == 1


@pytest.mark.asyncio
async def test_update_doctor_photo_rejects_configured_size_limit() -> None:
    connection = _connection(
        [
            _Result(
                row=_Row(
                    partner_type="doctor",
                    status="Active",
                    photo_ref=None,
                )
            )
        ]
    )
    facade = _facade(connection, media_store=_MediaStore())

    with pytest.raises(DoctorProfilePhotoValidationError):
        await facade.update_doctor_photo(
            12,
            media_type="image/jpeg",
            data=b"x" * (5 * 1024 * 1024 + 1),
        )


@pytest.mark.asyncio
async def test_update_doctor_photo_persists_doctor_prefix_key_and_retires_old_object() -> None:
    store = _MediaStore()
    store.stored["doctor/12/observed-photo.enc"] = b"old"
    store.stored["doctor/12/latest-photo.enc"] = b"latest"
    connection = _connection(
        [
            _Result(
                row=_Row(
                    partner_type="doctor",
                    status="Active",
                    photo_ref="doctor/12/observed-photo.enc",
                )
            ),
            _Result(
                row=_Row(
                    partner_type="doctor",
                    status="Active",
                    photo_ref="doctor/12/latest-photo.enc",
                )
            ),
            _Result(),
        ]
    )
    facade = _facade(connection, media_store=store)

    result = await facade.update_doctor_photo(
        12,
        media_type="image/jpeg",
        data=_JPEG_BYTES,
    )

    assert result.photo_ref == "doctor/12/new-photo.enc"
    assert store.saved == [(_JPEG_BYTES, 12, "doctor")]
    locked_swap = connection.execute.await_args_list[1].args[0]
    assert "FOR UPDATE" in str(locked_swap)
    update = connection.execute.await_args_list[2].args[0]
    assert update.table.name == "partner_profiles"
    assert update._values["photo_ref"].value == "doctor/12/new-photo.enc"
    assert store.deleted == ["doctor/12/latest-photo.enc"]


@pytest.mark.asyncio
async def test_update_doctor_photo_rechecks_active_doctor_before_ref_swap() -> None:
    store = _MediaStore()
    connection = _connection(
        [
            _Result(
                row=_Row(
                    partner_type="doctor",
                    status="Active",
                    photo_ref=None,
                )
            ),
            _Result(
                row=_Row(
                    partner_type="doctor",
                    status="Registered",
                    photo_ref=None,
                )
            ),
        ]
    )
    facade = _facade(connection, media_store=store)

    with pytest.raises(DoctorProfileNotAllowedError):
        await facade.update_doctor_photo(
            12,
            media_type="image/jpeg",
            data=_JPEG_BYTES,
        )

    assert store.deleted == ["doctor/12/new-photo.enc"]


@pytest.mark.asyncio
async def test_get_doctor_photo_streams_private_bytes_from_canonical_ref() -> None:
    store = _MediaStore()
    store.stored["doctor/12/photo.enc"] = _JPEG_BYTES
    connection = _connection(
        [
            _Result(
                row=_Row(
                    partner_type="doctor",
                    status="Active",
                    photo_ref="doctor/12/photo.enc",
                )
            )
        ]
    )
    facade = _facade(connection, media_store=store)

    result = await facade.get_doctor_photo(12)

    assert result is not None
    assert result.data == _JPEG_BYTES
    assert result.media_type == "image/jpeg"
    assert store.read_keys == ["doctor/12/photo.enc"]


@pytest.mark.asyncio
async def test_get_doctor_photo_returns_not_found_without_ref() -> None:
    connection = _connection(
        [
            _Result(
                row=_Row(
                    partner_type="doctor",
                    status="Active",
                    photo_ref=None,
                )
            )
        ]
    )
    facade = _facade(connection, media_store=_MediaStore())

    with pytest.raises(DoctorProfilePhotoNotFoundError):
        await facade.get_doctor_photo(12)


@pytest.mark.asyncio
async def test_get_doctor_photo_recognizes_webp_content() -> None:
    store = _MediaStore()
    store.stored["doctor/12/photo.webp"] = _WEBP_BYTES
    connection = _connection(
        [
            _Result(
                row=_Row(
                    partner_type="doctor",
                    status="Active",
                    photo_ref="doctor/12/photo.webp",
                )
            )
        ]
    )
    facade = _facade(connection, media_store=store)

    result = await facade.get_doctor_photo(12)

    assert result is not None
    assert result.media_type == "image/webp"


@pytest.mark.asyncio
async def test_get_doctor_photo_maps_storage_failure_to_typed_error() -> None:
    store = _MediaStore()
    store.read_error = OSError("storage offline")
    connection = _connection(
        [
            _Result(
                row=_Row(
                    partner_type="doctor",
                    status="Active",
                    photo_ref="doctor/12/photo.enc",
                )
            )
        ]
    )
    facade = _facade(connection, media_store=store)

    with pytest.raises(DoctorProfilePhotoStoreUnavailableError):
        await facade.get_doctor_photo(12)


@pytest.mark.asyncio
async def test_delete_doctor_photo_clears_ref_before_deleting_object() -> None:
    store = _MediaStore()
    store.stored["doctor/12/photo.enc"] = _JPEG_BYTES
    connection = _connection(
        [
            _Result(
                row=_Row(
                    partner_type="doctor",
                    status="Active",
                    photo_ref="doctor/12/photo.enc",
                )
            ),
            _Result(),
        ]
    )
    facade = _facade(connection, media_store=store)

    assert await facade.delete_doctor_photo(12) is None

    locked_delete = connection.execute.await_args_list[0].args[0]
    assert "FOR UPDATE" in str(locked_delete)
    update = connection.execute.await_args_list[1].args[0]
    assert update.table.name == "partner_profiles"
    assert update._values["photo_ref"].value is None
    assert store.deleted == ["doctor/12/photo.enc"]
