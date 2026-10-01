from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.config import Settings
from app.main import create_app
from modules.iam.domain.jwt import issue_token
from modules.iam.facade import PhotoContent
from modules.partner.doctor_profile_models import (
    DoctorProfileAboutUpdate,
    DoctorProfileAddressUpdate,
    DoctorProfileAddressView,
    DoctorProfileCredential,
    DoctorProfileNotificationUpdate,
    DoctorProfilePhotoView,
    DoctorProfilePracticeUpdate,
    DoctorProfileView,
)
from modules.partner.domain.practice_position import PinResolutionReason
from modules.partner.facade import (
    DoctorProfileNotAllowedError,
    DoctorProfilePhotoNotFoundError,
    DoctorProfilePhotoValidationError,
    PartnerView,
    PracticePinUnresolvedError,
)

_SIGNING_KEY = "test-doctor-profile-route-signing-key"
_PARTNER_ID = 12
_IDENTITY_ID = 30
_OTHER_PARTNER_ID = 13
_OTHER_IDENTITY_ID = 31

# The four section writes, named once: the acceptance sweep over their models and
# the retired-model check both read this, so a fifth section write is added in one
# place rather than being remembered in two.
_SECTION_WRITE_MODELS = (
    DoctorProfilePracticeUpdate,
    DoctorProfileAddressUpdate,
    DoctorProfileAboutUpdate,
    DoctorProfileNotificationUpdate,
)


def _token(*, subject_id: int = _IDENTITY_ID, scope: str = "partner") -> str:
    return issue_token(
        jti=uuid.uuid4().hex,
        subject_id=subject_id,
        scope=scope,
        signing_key=_SIGNING_KEY,
        now=datetime.now(UTC),
    )


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class StubIamFacade:
    def __init__(self) -> None:
        self.access_denials: list[int] = []

    async def emit_access_denied(self, identity_id: int) -> None:
        self.access_denials.append(identity_id)


class StubPartnerFacade:
    def __init__(self) -> None:
        self.profile_calls: list[int] = []
        self.practice_update_calls: list[tuple[int, DoctorProfilePracticeUpdate]] = []
        self.address_update_calls: list[tuple[int, DoctorProfileAddressUpdate]] = []
        self.about_update_calls: list[tuple[int, DoctorProfileAboutUpdate]] = []
        self.notification_update_calls: list[tuple[int, DoctorProfileNotificationUpdate]] = []
        self.photo_update_calls: list[tuple[int, str | None, bytes]] = []
        self.photo_get_calls: list[int] = []
        self.photo_delete_calls: list[int] = []
        self.photo = PhotoContent(data=b"photo-bytes", media_type="image/jpeg")
        self.photo_error: Exception | None = None
        self.profile_error: Exception | None = None
        self.identity_partner_ids = {
            _IDENTITY_ID: _PARTNER_ID,
            _OTHER_IDENTITY_ID: _OTHER_PARTNER_ID,
        }
        self.partner_type = "doctor"
        self.partner_status = "Active"
        self.view = DoctorProfileView(
            partner_id=_PARTNER_ID,
            photo_ref="doctor/12/photo.enc",
            practice_name="Anita Verma",
            clinic_name="Shanti Clinic",
            specialties=["General Physician", "Pediatrician"],
            verified=True,
            practice_address="Main Road, Daltonganj",
            practice_latitude=24.483,
            practice_longitude=87.433,
            area="Daltonganj",
            languages=["English", "Hindi"],
            experience_years=12,
            about="Primary care physician.",
            consultation_fee=50000,
            # #610: the availability split - a closed seven-day selection and the
            # prose that replaces the single ``availability`` blob.
            consulting_days=["Monday", "Tuesday", "Saturday"],
            consulting_hours="Monday to Friday, 9 AM to 5 PM; Saturday morning clinic",
            credentials=[
                DoctorProfileCredential(
                    credential_type="medical_registration",
                    status="verified",
                    expires_at=datetime.now(UTC) + timedelta(days=180),
                )
            ],
            notification_preferences={"appointment_reminders": True, "sms": True},
        )
        # #609: the address write answers with the profile plus its own belt
        # warning. A plain profile read never evaluates the belt, so this is the
        # write's response and not the read projection's.
        self.address_view = DoctorProfileAddressView(
            **self.view.model_dump(),
            outside_peri_urban_belt=False,
            distance_from_belt_centre_km=1.4,
        )

    async def resolve_partner(self, identity_id: int) -> PartnerView:
        return PartnerView(
            partner_id=self.identity_partner_ids[identity_id],
            partner_type=self.partner_type,
            status=self.partner_status,
            round=1,
        )

    async def get_doctor_profile(self, doctor_id: int) -> DoctorProfileView:
        self.profile_calls.append(doctor_id)
        if self.profile_error is not None:
            raise self.profile_error
        return self.view

    async def update_doctor_practice(
        self,
        doctor_id: int,
        update: DoctorProfilePracticeUpdate,
    ) -> DoctorProfileView:
        self.practice_update_calls.append((doctor_id, update))
        if self.profile_error is not None:
            raise self.profile_error
        return self.view

    async def update_doctor_address(
        self,
        doctor_id: int,
        update: DoctorProfileAddressUpdate,
    ) -> DoctorProfileAddressView:
        self.address_update_calls.append((doctor_id, update))
        if self.profile_error is not None:
            raise self.profile_error
        return self.address_view

    async def update_doctor_about(
        self,
        doctor_id: int,
        update: DoctorProfileAboutUpdate,
    ) -> DoctorProfileView:
        self.about_update_calls.append((doctor_id, update))
        if self.profile_error is not None:
            raise self.profile_error
        return self.view

    async def update_doctor_notification(
        self,
        doctor_id: int,
        update: DoctorProfileNotificationUpdate,
    ) -> DoctorProfileView:
        self.notification_update_calls.append((doctor_id, update))
        if self.profile_error is not None:
            raise self.profile_error
        return self.view

    async def update_doctor_photo(
        self,
        doctor_id: int,
        *,
        media_type: str | None,
        data: bytes,
    ) -> DoctorProfilePhotoView:
        self.photo_update_calls.append((doctor_id, media_type, data))
        if self.photo_error is not None:
            raise self.photo_error
        return DoctorProfilePhotoView(photo_ref="doctor/12/photo.enc")

    async def get_doctor_photo(self, doctor_id: int) -> PhotoContent:
        self.photo_get_calls.append(doctor_id)
        if self.photo_error is not None:
            raise self.photo_error
        return self.photo

    async def delete_doctor_photo(self, doctor_id: int) -> None:
        self.photo_delete_calls.append(doctor_id)
        return None


def _client(facade: StubPartnerFacade | None = None) -> TestClient:
    settings = Settings(gateway_jwt_verify_enabled=True, gateway_jwt_signing_key=_SIGNING_KEY)
    app = create_app(settings=settings)
    app.state.partner_facade = facade if facade is not None else StubPartnerFacade()
    app.state.iam_facade = StubIamFacade()
    return TestClient(app)


def _about_body() -> dict[str, object]:
    """A complete About card body - #610 requires every one of its four fields."""
    return {
        "about": "Primary care physician.",
        "languages": ["Hindi", "English"],
        "consulting_days": ["Monday", "Tuesday"],
        "consulting_hours": "Weekday mornings, Saturday morning clinic.",
    }


def test_get_doctor_profile_returns_private_projection_for_active_doctor() -> None:
    facade = StubPartnerFacade()
    client = _client(facade)

    response = client.get("/v1/doctor/profile", headers=_bearer(_token()))

    assert response.status_code == 200
    assert response.json() == facade.view.model_dump(mode="json")
    assert facade.profile_calls == [_PARTNER_ID]


def test_facade_profile_authorization_denial_is_audited() -> None:
    facade = StubPartnerFacade()
    facade.profile_error = DoctorProfileNotAllowedError(
        _PARTNER_ID,
        "doctor",
        "Registered",
    )
    client = _client(facade)
    iam = client.app.state.iam_facade
    assert isinstance(iam, StubIamFacade)

    response = client.get("/v1/doctor/profile", headers=_bearer(_token()))

    assert response.status_code == 403
    assert response.json()["code"] == "DOCTOR_PROFILE_NOT_ALLOWED"
    assert iam.access_denials == [_IDENTITY_ID]


def test_whole_form_profile_write_is_retired_and_the_profile_read_survives() -> None:
    """#611: the single whole-form profile write is gone, and this asserts it.

    Absence, asserted rather than assumed. The suite previously carried three
    whole-form tests and simply stopped carrying them, which proves nothing about
    the route registry - a route can be unregistered and every test still pass.

    The PATH survives, because the private profile read shares it, so this is a
    method-level assertion: the path item carries no ``put`` operation at all. The
    wire behaviour is the second half - a client still sending the old body gets
    405, which is neither the 200 it used to get nor a 422 from a model that no
    longer exists, and the facade is never reached behind it. The read on the same
    path is asserted immediately after, so "retired" cannot be satisfied by
    retiring the wrong thing.

    Only the STATUS is asserted, deliberately: the 405 body is Starlette's
    ``{"detail": ...}``, not the api-standards §2 envelope, because the app
    registers no handler for framework-generated HTTP errors. That gap predates
    this ticket (an unknown path has always answered this way) and is a gateway-wide
    fix rather than a doctor-profile one; pinning the bare body here would freeze
    it, and this test would not own the envelope contract even if it did.
    """
    facade = StubPartnerFacade()
    client = _client(facade)
    body = {"practice_address": "Main Road, Daltonganj", "languages": ["Hindi"]}

    profile_path = client.app.openapi()["paths"]["/v1/doctor/profile"]
    assert set(profile_path) == {"get"}

    retired = client.put("/v1/doctor/profile", json=body, headers=_bearer(_token()))

    assert retired.status_code == 405
    assert facade.profile_calls == []

    read = client.get("/v1/doctor/profile", headers=_bearer(_token()))

    assert read.status_code == 200
    assert facade.profile_calls == [_PARTNER_ID]


def test_retired_whole_form_request_model_is_no_longer_served() -> None:
    """#611: the whole-form body shape is gone from the document, not just unused.

    The model was the last request shape that accepted the full profile in one
    body, and - before #606 dropped its coordinate fields - the last one a client
    could use to place its own practice pin. Its absence from the OpenAPI
    components is the assertion that no route anywhere still accepts it; the
    section models being present is what keeps that from being satisfied by a
    component-cache accident.
    """
    schemas = _client().app.openapi()["components"]["schemas"]

    assert "DoctorProfileUpdate" not in schemas
    assert {model.__name__ for model in _SECTION_WRITE_MODELS} <= set(schemas)


@pytest.mark.parametrize(
    "model",
    _SECTION_WRITE_MODELS,
    ids=[model.__name__ for model in _SECTION_WRITE_MODELS],
)
def test_no_profile_section_write_accepts_a_coordinate_field(
    model: type[BaseModel],
) -> None:
    """#611: no client-facing profile write accepts a position, in any section.

    The whole-form model is retired, and this keeps the guarantee from depending
    on that retirement alone: the practice position is server-written (#606) and
    derived from the declared PIN (#609), so a model that re-declared either
    coordinate would hand a client back the ability to place its own pin.

    ``extra="forbid"`` is asserted alongside the field absence because it is the
    mechanism, not the declaration, that turns "a client cannot send this" into a
    live 422: without it a coordinate would be accepted and silently discarded,
    telling the doctor their position saved when it did not. The 422s themselves
    are covered per route elsewhere in this suite; this is the sweep that keeps
    every section write - present and future - inside the rule.
    """
    assert model.model_config.get("extra") == "forbid"
    assert "practice_latitude" not in model.model_fields
    assert "practice_longitude" not in model.model_fields


def test_put_doctor_profile_practice_saves_the_practice_card_for_active_doctor() -> None:
    """#608: the practice write returns 200 and forwards its body verbatim.

    Verbatim means the router parsed and re-serialized nothing: the model the
    facade receives dumps back to exactly the submitted JSON, so a client cannot
    have a field quietly dropped, renamed or reordered between the wire and the
    write. The section write's own fields only - no address, languages, about or
    notification keys ride along.
    """
    facade = StubPartnerFacade()
    client = _client(facade)
    body = {
        "full_name": "Anita Verma",
        "clinic_name": "Shanti Clinic",
        "specialties": ["Pediatrician", "General Physician"],
        "experience_years": 12,
    }

    response = client.put("/v1/doctor/profile/practice", json=body, headers=_bearer(_token()))

    assert response.status_code == 200
    assert response.json() == facade.view.model_dump(mode="json")
    assert len(facade.practice_update_calls) == 1
    doctor_id, update = facade.practice_update_calls[0]
    assert doctor_id == _PARTNER_ID
    assert update.model_dump(mode="json") == body


@pytest.mark.parametrize(
    "borrowed",
    [
        {"practice_address": "Main Road, Daltonganj"},
        {"notification_preferences": {"sms": True}},
        {"availability": "Monday to Friday"},
        {"practice_latitude": 24.483},
    ],
    ids=["address", "notifications", "availability", "coordinates"],
)
def test_put_doctor_profile_practice_refuses_another_cards_field(
    borrowed: dict[str, object],
) -> None:
    """#608: a section save cannot write a field no card on screen is editing.

    ``extra="forbid"`` on the practice model is what makes the four-way split
    real rather than nominal. Each case is a field owned by another card (or, for
    the coordinates, by no card at all - they are server-written from the declared
    PIN), and every one of them is a 422 with no facade call, so a stale client
    saving the practice card cannot silently move the address.
    """
    facade = StubPartnerFacade()
    client = _client(facade)
    body = {"full_name": "Anita Verma", **borrowed}

    response = client.put("/v1/doctor/profile/practice", json=body, headers=_bearer(_token()))

    assert response.status_code == 422
    assert facade.practice_update_calls == []


def test_put_doctor_profile_practice_rejects_specialty_outside_the_closed_list() -> None:
    """#608: a specialty off the closed pick-list is a 422 with a field-level detail.

    The field is never free-form, so an unknown value is refused rather than
    persisted into a column nothing can filter on later. The detail names the
    ``specialties`` field, which is what the client renders the error under.
    """
    facade = StubPartnerFacade()
    client = _client(facade)
    body = {"full_name": "Anita Verma", "specialties": ["General Physician", "Homeopathy"]}

    response = client.put("/v1/doctor/profile/practice", json=body, headers=_bearer(_token()))

    assert response.status_code == 422
    envelope = response.json()
    assert envelope["code"] == "INVALID_SPECIALTY"
    assert [error["path"] for error in envelope["details"]["errors"]] == ["specialties"]
    assert "Homeopathy" in envelope["details"]["errors"][0]["reason"]
    assert facade.practice_update_calls == []


def test_put_doctor_profile_practice_accepts_an_empty_specialty_selection() -> None:
    """#608: declaring no specialty yet is a state a doctor can hold.

    The counterpart to the closed-list refusal: an empty selection is a real
    answer for a practice that has not decided, so it is saved as the empty array
    rather than refused - the same call ``require_consult_languages`` makes for a
    doctor who consults in no declared language yet.
    """
    facade = StubPartnerFacade()
    client = _client(facade)

    response = client.put(
        "/v1/doctor/profile/practice",
        json={"full_name": "Anita Verma", "specialties": []},
        headers=_bearer(_token()),
    )

    assert response.status_code == 200
    assert facade.practice_update_calls[0][1].specialties == []


def test_practice_idempotency_key_is_scoped_to_the_doctor() -> None:
    """#608: one client's key never answers for another doctor's save.

    The section writes are the only writes that can arrive concurrently from two
    browsers signed in as different doctors, so the per-doctor namespace is what
    stops one doctor's replayed key from being served the other doctor's stored
    result. Same key, same body, two identities, two writes.
    """
    facade = StubPartnerFacade()
    client = _client(facade)
    body = {"full_name": "Anita Verma", "specialties": ["Pediatrician"]}
    first_headers = {
        **_bearer(_token()),
        "Idempotency-Key": "shared-practice-key",
    }
    second_headers = {
        **_bearer(_token(subject_id=_OTHER_IDENTITY_ID)),
        "Idempotency-Key": "shared-practice-key",
    }

    first = client.put("/v1/doctor/profile/practice", json=body, headers=first_headers)
    second = client.put("/v1/doctor/profile/practice", json=body, headers=second_headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert [doctor_id for doctor_id, _ in facade.practice_update_calls] == [
        _PARTNER_ID,
        _OTHER_PARTNER_ID,
    ]


def test_put_doctor_profile_practice_replays_the_same_idempotency_key() -> None:
    """#608: a retry of the same doctor's save does not execute twice."""
    facade = StubPartnerFacade()
    client = _client(facade)
    headers = {
        **_bearer(_token()),
        "Idempotency-Key": "practice-retry-key",
    }
    body = {"full_name": "Anita Verma"}

    first = client.put("/v1/doctor/profile/practice", json=body, headers=headers)
    second = client.put("/v1/doctor/profile/practice", json=body, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert len(facade.practice_update_calls) == 1


def test_put_doctor_profile_practice_refuses_non_active_doctor() -> None:
    """#608: the edge refusal, and no facade call behind it.

    The guard resolves the principal to its partner profile and refuses a
    partner who is not an ``[Active]`` doctor before the section write is reached,
    so an unverified doctor cannot save a practice card at all. The facade
    re-checks the same rule under a row lock; this case is the edge half.
    """
    facade = StubPartnerFacade()
    facade.partner_status = "Registered"
    client = _client(facade)

    response = client.put(
        "/v1/doctor/profile/practice",
        json={"full_name": "Anita Verma"},
        headers=_bearer(_token()),
    )

    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_INSUFFICIENT_SCOPE"
    assert facade.practice_update_calls == []


def test_put_doctor_profile_practice_refuses_non_doctor_partner() -> None:
    """#608: the practice card is a doctor's, not any partner's."""
    facade = StubPartnerFacade()
    facade.partner_type = "lab"
    client = _client(facade)

    response = client.put(
        "/v1/doctor/profile/practice",
        json={"full_name": "Anita Verma"},
        headers=_bearer(_token()),
    )

    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_INSUFFICIENT_SCOPE"
    assert facade.practice_update_calls == []


def test_practice_facade_authorization_denial_is_audited() -> None:
    """#608: the facade half of the refusal is a denial, not a silent 403.

    A doctor deactivated between the edge guard and the write is refused by the
    facade's row-locked recheck, and that refusal is audited through iam - the
    reason the section write is not reachable by a client that only satisfies the
    edge.
    """
    facade = StubPartnerFacade()
    facade.profile_error = DoctorProfileNotAllowedError(
        _PARTNER_ID,
        "doctor",
        "Registered",
    )
    client = _client(facade)
    iam = client.app.state.iam_facade
    assert isinstance(iam, StubIamFacade)

    response = client.put(
        "/v1/doctor/profile/practice",
        json={"full_name": "Anita Verma"},
        headers=_bearer(_token()),
    )

    assert response.status_code == 403
    assert response.json()["code"] == "DOCTOR_PROFILE_NOT_ALLOWED"
    assert iam.access_denials == [_IDENTITY_ID]


def test_put_doctor_profile_address_saves_the_address_card_for_active_doctor() -> None:
    """#609: the address write returns 200 and forwards its body verbatim.

    Verbatim means the router parsed and re-serialized nothing: the model the
    facade receives dumps back to exactly the submitted JSON, so a field cannot
    have been quietly dropped or renamed between the wire and the write.
    """
    facade = StubPartnerFacade()
    client = _client(facade)
    body = {
        "address_line": "12 Main Road",
        "landmark": "Near the water tower",
        "locality": "Daltonganj",
        "city": "Daltonganj",
        "pin_code": "826001",
    }

    response = client.put("/v1/doctor/profile/address", json=body, headers=_bearer(_token()))

    assert response.status_code == 200
    assert response.json() == facade.address_view.model_dump(mode="json")
    assert len(facade.address_update_calls) == 1
    doctor_id, update = facade.address_update_calls[0]
    assert doctor_id == _PARTNER_ID
    assert update.model_dump(mode="json") == body


@pytest.mark.parametrize(
    "borrowed",
    [
        {"practice_latitude": 24.483},
        {"practice_longitude": 87.433},
        {"full_name": "Anita Verma"},
        {"notification_preferences": {"sms": True}},
    ],
    ids=["latitude", "longitude", "practice", "notifications"],
)
def test_put_doctor_profile_address_refuses_a_field_no_card_declares(
    borrowed: dict[str, object],
) -> None:
    """#609: the address card cannot write a coordinate, ever.

    The two coordinate cases are the load-bearing ones. The doctor declares an
    address and the backend derives the position from its PIN, so a client-supplied
    latitude or longitude is refused at the edge by ``extra="forbid"`` - and it is
    asserted here rather than left to the comment, because accepting and discarding
    the field would tell a doctor their coordinates saved when they did not.
    """
    facade = StubPartnerFacade()
    client = _client(facade)
    body = {"address_line": "12 Main Road", "pin_code": "826001", **borrowed}

    response = client.put("/v1/doctor/profile/address", json=body, headers=_bearer(_token()))

    assert response.status_code == 422
    assert facade.address_update_calls == []


@pytest.mark.parametrize(
    ("pin_code", "reason", "reason_text"),
    [
        ("8260", PinResolutionReason.MALFORMED, "must be six digits"),
        ("82 6001", PinResolutionReason.MALFORMED, "must be six digits"),
        ("", PinResolutionReason.MALFORMED, "must be six digits"),
        ("1234567890123456789012345678901234", PinResolutionReason.MALFORMED, "must be six"),
        ("999999", PinResolutionReason.UNKNOWN, "not one we can place yet"),
    ],
    ids=["too-short", "not-digits", "blank", "over-long", "not-in-the-dataset"],
)
def test_put_doctor_profile_address_rejects_an_unresolvable_pin(
    pin_code: str,
    reason: PinResolutionReason,
    reason_text: str,
) -> None:
    """#609: a PIN that cannot be placed fails this card alone, under the PIN input.

    The detail's ``path`` names the PIN field, which is the whole point of the
    shape: the client renders the error under that input instead of guessing which
    one failed. Every shape of unusable code arrives HERE rather than as a Pydantic
    ``too_short``/``too_long``, because the domain owns the rule - which is why the
    blank and the over-long cases are in this list at all: a length bound on the
    request model would have made those two a different envelope with no PIN-keyed
    detail, and the doctor cannot tell a length failure from a character-class one.
    The two reasons differ only in which sentence the same actionable message is,
    which is what ``PinResolutionReason`` says the client is meant to show.

    The refusal itself is the facade's decision (the companion facade test proves
    nothing was written); what this test owns is that the raised domain error
    arrives in the one envelope with a PIN-keyed detail.
    """
    facade = StubPartnerFacade()
    facade.profile_error = PracticePinUnresolvedError(pin_code, reason)
    client = _client(facade)

    response = client.put(
        "/v1/doctor/profile/address",
        json={"address_line": "12 Main Road", "pin_code": pin_code},
        headers=_bearer(_token()),
    )

    assert response.status_code == 422
    envelope = response.json()
    assert envelope["code"] == "DOCTOR_PROFILE_ADDRESS_PIN_UNRESOLVED"
    assert [error["path"] for error in envelope["details"]["errors"]] == ["pin_code"]
    assert reason_text in envelope["details"]["errors"][0]["reason"]
    # The write was reached and refused by the facade's decision - not refused at
    # the edge - which is the split between "the router refused the body" and "the
    # server cannot place this PIN".
    assert len(facade.address_update_calls) == 1


def test_address_write_returns_the_outside_belt_warning_and_still_saves() -> None:
    """#609: an outlying PIN saves and warns - it is never a refusal.

    A doctor who corrects a wrong sign-up PIN must not be blocked by where they
    turned out to be, so the warning rides on the same 200 the save returns.
    """
    facade = StubPartnerFacade()
    facade.address_view = facade.address_view.model_copy(
        update={"outside_peri_urban_belt": True, "distance_from_belt_centre_km": 78.4}
    )
    client = _client(facade)

    response = client.put(
        "/v1/doctor/profile/address",
        json={"pin_code": "826001"},
        headers=_bearer(_token()),
    )

    assert response.status_code == 200
    assert response.json()["outside_peri_urban_belt"] is True
    assert response.json()["distance_from_belt_centre_km"] == pytest.approx(78.4)
    assert len(facade.address_update_calls) == 1


def test_address_idempotency_key_is_scoped_to_the_doctor() -> None:
    """#609: one doctor's replayed address key never answers for another's save."""
    facade = StubPartnerFacade()
    client = _client(facade)
    body = {"address_line": "12 Main Road", "pin_code": "826001"}
    first_headers = {**_bearer(_token()), "Idempotency-Key": "shared-address-key"}
    second_headers = {
        **_bearer(_token(subject_id=_OTHER_IDENTITY_ID)),
        "Idempotency-Key": "shared-address-key",
    }

    first = client.put("/v1/doctor/profile/address", json=body, headers=first_headers)
    second = client.put("/v1/doctor/profile/address", json=body, headers=second_headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert [doctor_id for doctor_id, _ in facade.address_update_calls] == [
        _PARTNER_ID,
        _OTHER_PARTNER_ID,
    ]


def test_put_doctor_profile_address_refuses_non_active_doctor() -> None:
    facade = StubPartnerFacade()
    facade.partner_status = "Registered"
    client = _client(facade)

    response = client.put(
        "/v1/doctor/profile/address",
        json={"pin_code": "826001"},
        headers=_bearer(_token()),
    )

    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_INSUFFICIENT_SCOPE"
    assert facade.address_update_calls == []


def test_address_facade_authorization_denial_is_audited() -> None:
    """#609: the row-locked recheck's refusal is audited, not just refused."""
    facade = StubPartnerFacade()
    facade.profile_error = DoctorProfileNotAllowedError(
        _PARTNER_ID,
        "doctor",
        "Registered",
    )
    client = _client(facade)
    iam = client.app.state.iam_facade
    assert isinstance(iam, StubIamFacade)

    response = client.put(
        "/v1/doctor/profile/address",
        json={"pin_code": "826001"},
        headers=_bearer(_token()),
    )

    assert response.status_code == 403
    assert response.json()["code"] == "DOCTOR_PROFILE_NOT_ALLOWED"
    assert iam.access_denials == [_IDENTITY_ID]


# --------------------------------------------------------------------------
# #610 - the About and Notification section writes
# --------------------------------------------------------------------------


def test_put_doctor_profile_about_saves_the_about_card_for_active_doctor() -> None:
    """#610: the about write returns 200 and forwards its body verbatim.

    Verbatim means the router parsed and re-serialized nothing: the model the
    facade receives dumps back to exactly the submitted JSON, so no field has been
    quietly dropped or renamed between the wire and the write. The card's four
    fields only - no practice, address or notification key rides along.
    """
    facade = StubPartnerFacade()
    client = _client(facade)
    body = {
        "about": "Twenty years of primary care in the block.",
        "languages": ["Hindi", "English", "Maithili"],
        "consulting_days": ["Monday", "Tuesday", "Saturday"],
        "consulting_hours": "Weekdays 9 AM to 5 PM; Saturday morning clinic only.",
    }

    response = client.put("/v1/doctor/profile/about", json=body, headers=_bearer(_token()))

    assert response.status_code == 200
    assert response.json() == facade.view.model_dump(mode="json")
    assert len(facade.about_update_calls) == 1
    doctor_id, update = facade.about_update_calls[0]
    assert doctor_id == _PARTNER_ID
    assert update.model_dump(mode="json") == body


def test_put_doctor_profile_about_keeps_consulting_hours_as_prose() -> None:
    """#610: consulting hours cross the wire as an arbitrary string.

    This is the "no weekly template, no slot structure" criterion, asserted on the
    value rather than on a bound: a sentence no template would produce - mixed case,
    a day-range written with dashes, a parenthetical, and a second clause - arrives
    and is forwarded byte for byte. A model that had grown a weekly template or a
    per-day slot list could not carry this at all, and a bound-only assertion would
    have passed against one that could.
    """
    facade = StubPartnerFacade()
    client = _client(facade)
    hours = (
        "Mon-Sat 10-2 (walk-ins after 12), Sat 5-7 pm only if the registrar is in; "
        "closed the 2nd and 4th Sat of every month"
    )

    response = client.put(
        "/v1/doctor/profile/about",
        json={
            "about": None,
            "languages": [],
            "consulting_days": ["Monday", "Saturday"],
            "consulting_hours": hours,
        },
        headers=_bearer(_token()),
    )

    assert response.status_code == 200
    assert facade.about_update_calls[0][1].consulting_hours == hours


@pytest.mark.parametrize(
    "borrowed",
    [
        {"full_name": "Anita Verma"},
        {"pin_code": "826001"},
        {"notification_preferences": {"new_consultations": True}},
        {"consulting_fee": 50000},
    ],
    ids=["practice", "address", "notifications", "fee"],
)
def test_put_doctor_profile_about_refuses_another_cards_field(
    borrowed: dict[str, object],
) -> None:
    """#610: the about card cannot write a field no card on screen is editing.

    ``extra="forbid"`` on the about model is what makes the four-way split real
    rather than nominal. The consultation fee is here too, and it is the case worth
    naming: it is a real column with its own dedicated PATCH route on the doctor
    landing page, and it is still not a field this card declares.
    """
    facade = StubPartnerFacade()
    client = _client(facade)
    body = {"about": "Primary care.", **borrowed}

    response = client.put("/v1/doctor/profile/about", json=body, headers=_bearer(_token()))

    assert response.status_code == 422
    assert facade.about_update_calls == []


@pytest.mark.parametrize("omitted", ["about", "languages", "consulting_days", "consulting_hours"])
def test_put_doctor_profile_about_requires_the_whole_card(omitted: str) -> None:
    """#610: a section save declares its whole card, so nothing is optional.

    Not just ``extra="forbid"``, but REQUIRED - because the ``UPDATE`` payload is
    the model's dump, and a default would mean a client that forgot one field
    silently CLEARED that column and was told the save succeeded. An omitted
    ``about`` would erase the doctor's own words about themselves; an omitted
    ``consulting_days`` would wipe their availability. ``null`` is still how a
    doctor clears one deliberately, and those two are different things.
    """
    facade = StubPartnerFacade()
    client = _client(facade)
    body = {
        "about": "Primary care.",
        "languages": ["Hindi"],
        "consulting_days": ["Monday"],
        "consulting_hours": "Weekday mornings",
    }
    body.pop(omitted)

    response = client.put("/v1/doctor/profile/about", json=body, headers=_bearer(_token()))

    assert response.status_code == 422
    assert facade.about_update_calls == []


@pytest.mark.parametrize(
    ("field", "submitted", "code", "path", "offender"),
    [
        (
            "languages",
            ["Hindi", "Klingon"],
            "INVALID_CONSULT_LANGUAGE",
            "languages",
            "Klingon",
        ),
        (
            # A member spelled differently is not a member. This is the ticket's
            # opening sentence - "the same language twice in two spellings" - and
            # the answer is stronger than case-folding: the list cannot produce a
            # second spelling at all.
            "languages",
            ["Hindi", "hindi"],
            "INVALID_CONSULT_LANGUAGE",
            "languages",
            "hindi",
        ),
        (
            "consulting_days",
            ["Monday", "Caturday"],
            "INVALID_CONSULTING_DAY",
            "consulting_days",
            "Caturday",
        ),
    ],
    ids=["unknown-language", "two-spellings", "unknown-day"],
)
def test_put_doctor_profile_about_refuses_a_value_off_the_closed_list(
    field: str,
    submitted: list[str],
    code: str,
    path: str,
    offender: str,
) -> None:
    """#610: a value outside a closed list is a 422 naming the offending field.

    Both lists are checked member by member, so the refusal names WHICH member
    broke the rule and not merely that the selection did. The ``path`` is what the
    client renders the error under - the language chips or the day chips - so a
    doctor who tapped four good days and one bad one sees the problem on the one
    chip rather than as a whole-card failure that discards every other unsaved edit.
    """
    facade = StubPartnerFacade()
    client = _client(facade)
    body = {
        "about": "Primary care.",
        "languages": ["Hindi"],
        "consulting_days": ["Monday"],
        "consulting_hours": "Weekday mornings",
        field: submitted,
    }

    response = client.put("/v1/doctor/profile/about", json=body, headers=_bearer(_token()))

    assert response.status_code == 422
    envelope = response.json()
    assert envelope["code"] == code
    assert [error["path"] for error in envelope["details"]["errors"]] == [path]
    assert offender in envelope["details"]["errors"][0]["reason"]
    assert facade.about_update_calls == []


def test_about_idempotency_key_is_scoped_to_the_doctor() -> None:
    """#610: one client's key never answers for another doctor's save."""
    facade = StubPartnerFacade()
    client = _client(facade)
    body = _about_body()
    first_headers = {
        **_bearer(_token()),
        "Idempotency-Key": "shared-about-key",
    }
    second_headers = {
        **_bearer(_token(subject_id=_OTHER_IDENTITY_ID)),
        "Idempotency-Key": "shared-about-key",
    }

    first = client.put("/v1/doctor/profile/about", json=body, headers=first_headers)
    second = client.put("/v1/doctor/profile/about", json=body, headers=second_headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert [doctor_id for doctor_id, _ in facade.about_update_calls] == [
        _PARTNER_ID,
        _OTHER_PARTNER_ID,
    ]


def test_put_doctor_profile_about_refuses_non_active_doctor() -> None:
    """#610: the edge refusal, and no facade call behind it."""
    facade = StubPartnerFacade()
    facade.partner_status = "Registered"
    client = _client(facade)

    response = client.put(
        "/v1/doctor/profile/about",
        json=_about_body(),
        headers=_bearer(_token()),
    )

    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_INSUFFICIENT_SCOPE"
    assert facade.about_update_calls == []


def test_put_doctor_profile_about_facade_authorization_denial_is_audited() -> None:
    """#610: the row-locked recheck's refusal is audited, not just refused."""
    facade = StubPartnerFacade()
    facade.profile_error = DoctorProfileNotAllowedError(
        _PARTNER_ID,
        "doctor",
        "Registered",
    )
    client = _client(facade)
    iam = client.app.state.iam_facade
    assert isinstance(iam, StubIamFacade)

    response = client.put(
        "/v1/doctor/profile/about",
        json=_about_body(),
        headers=_bearer(_token()),
    )

    assert response.status_code == 403
    assert response.json()["code"] == "DOCTOR_PROFILE_NOT_ALLOWED"
    assert iam.access_denials == [_IDENTITY_ID]


def test_put_doctor_profile_notifications_saves_the_card_for_active_doctor() -> None:
    """#610: the notification write returns 200 and forwards its body verbatim."""
    facade = StubPartnerFacade()
    client = _client(facade)
    body = {
        "notification_preferences": {
            "new_consultations": True,
            "record_shared": False,
            "pre_summary_ready": True,
            "case_updates": True,
            "credential_status": False,
        }
    }

    response = client.put(
        "/v1/doctor/profile/notifications",
        json=body,
        headers=_bearer(_token()),
    )

    assert response.status_code == 200
    assert response.json() == facade.view.model_dump(mode="json")
    assert len(facade.notification_update_calls) == 1
    doctor_id, update = facade.notification_update_calls[0]
    assert doctor_id == _PARTNER_ID
    assert update.model_dump(mode="json") == body


def test_put_doctor_profile_notifications_accepts_an_empty_preference_set() -> None:
    """#610: every toggle off is a real answer, not an absent one.

    The counterpart to the closed-list refusals, and the reason the merge drops a
    known stored key the submission omits: a doctor who turns all five switches off
    must be able to say so with an empty selection.
    """
    facade = StubPartnerFacade()
    client = _client(facade)

    response = client.put(
        "/v1/doctor/profile/notifications",
        json={"notification_preferences": {}},
        headers=_bearer(_token()),
    )

    assert response.status_code == 200
    assert facade.notification_update_calls[0][1].notification_preferences == {}


def test_put_doctor_profile_notifications_refuses_a_key_off_the_list() -> None:
    """#610: only the five keys can be written.

    This is what "accepts the five existing notification keys" has to mean on the
    server. The dictionary was an open one - 20 entries, 50-character keys, shape
    only - so before #610 a save could write any key at all and the only named list
    of the five in the repository was a TypeScript tuple on the profile page. The
    refusal names the ``notification_preferences`` field so the card renders it
    against the switches rather than as an opaque page-level failure.
    """
    facade = StubPartnerFacade()
    client = _client(facade)

    response = client.put(
        "/v1/doctor/profile/notifications",
        json={"notification_preferences": {"new_consultations": True, "sms": True}},
        headers=_bearer(_token()),
    )

    assert response.status_code == 422
    envelope = response.json()
    assert envelope["code"] == "INVALID_NOTIFICATION_KEY"
    assert [error["path"] for error in envelope["details"]["errors"]] == [
        "notification_preferences"
    ]
    assert "sms" in envelope["details"]["errors"][0]["reason"]
    assert facade.notification_update_calls == []


@pytest.mark.parametrize(
    "borrowed",
    [
        {"about": "Primary care."},
        {"full_name": "Anita Verma"},
        {"pin_code": "826001"},
    ],
    ids=["about", "practice", "address"],
)
def test_put_doctor_profile_notifications_refuses_another_cards_field(
    borrowed: dict[str, object],
) -> None:
    """#610: the smallest card cannot write a bigger card's field."""
    facade = StubPartnerFacade()
    client = _client(facade)

    response = client.put(
        "/v1/doctor/profile/notifications",
        json={"notification_preferences": {"case_updates": True}, **borrowed},
        headers=_bearer(_token()),
    )

    assert response.status_code == 422
    assert facade.notification_update_calls == []


def test_put_doctor_profile_notifications_requires_the_preference_dict() -> None:
    """#610: required, so an omitted dict cannot clear the doctor's toggles.

    The single-column write is where this bites hardest: with a default, a client
    that sent no preferences at all would have written ``{}`` and reported success,
    switching the doctor off from every notification in one request.
    """
    facade = StubPartnerFacade()
    client = _client(facade)

    response = client.put(
        "/v1/doctor/profile/notifications",
        json={},
        headers=_bearer(_token()),
    )

    assert response.status_code == 422
    assert facade.notification_update_calls == []


def test_notification_idempotency_key_is_scoped_to_the_doctor() -> None:
    """#610: the fourth section write keeps the same per-doctor scoping.

    All four share the ``f"doctor:{doctor_id}"`` namespace, so the property is
    stated per write rather than assumed from its siblings - and it is the
    smallest write where a leaked namespace would be most expensive, since it
    carries a doctor's stored notification preferences in the response.
    """
    facade = StubPartnerFacade()
    client = _client(facade)
    body = {"notification_preferences": {"new_consultations": True}}
    first_headers = {
        **_bearer(_token()),
        "Idempotency-Key": "shared-notification-key",
    }
    second_headers = {
        **_bearer(_token(subject_id=_OTHER_IDENTITY_ID)),
        "Idempotency-Key": "shared-notification-key",
    }

    first = client.put("/v1/doctor/profile/notifications", json=body, headers=first_headers)
    second = client.put("/v1/doctor/profile/notifications", json=body, headers=second_headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert [doctor_id for doctor_id, _ in facade.notification_update_calls] == [
        _PARTNER_ID,
        _OTHER_PARTNER_ID,
    ]


def test_put_doctor_profile_notifications_refuses_non_active_doctor() -> None:
    """#610: the edge refusal, and no facade call behind it."""
    facade = StubPartnerFacade()
    facade.partner_status = "Registered"
    client = _client(facade)

    response = client.put(
        "/v1/doctor/profile/notifications",
        json={"notification_preferences": {}},
        headers=_bearer(_token()),
    )

    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_INSUFFICIENT_SCOPE"
    assert facade.notification_update_calls == []


def test_put_doctor_profile_notifications_facade_authorization_denial_is_audited() -> None:
    """#610: the row-locked recheck's refusal is audited, not just refused."""
    facade = StubPartnerFacade()
    facade.profile_error = DoctorProfileNotAllowedError(
        _PARTNER_ID,
        "doctor",
        "Registered",
    )
    client = _client(facade)
    iam = client.app.state.iam_facade
    assert isinstance(iam, StubIamFacade)

    response = client.put(
        "/v1/doctor/profile/notifications",
        json={"notification_preferences": {}},
        headers=_bearer(_token()),
    )

    assert response.status_code == 403
    assert response.json()["code"] == "DOCTOR_PROFILE_NOT_ALLOWED"
    assert iam.access_denials == [_IDENTITY_ID]


def test_put_doctor_profile_photo_uploads_private_doctor_media() -> None:
    facade = StubPartnerFacade()
    client = _client(facade)

    response = client.put(
        "/v1/doctor/profile/photo",
        files={"file": ("photo.jpg", b"photo-bytes", "image/jpeg")},
        headers=_bearer(_token()),
    )

    assert response.status_code == 200
    assert response.json() == {"photo_ref": "doctor/12/photo.enc"}
    assert facade.photo_update_calls == [(_PARTNER_ID, "image/jpeg", b"photo-bytes")]


def test_photo_idempotency_key_is_scoped_to_the_doctor() -> None:
    facade = StubPartnerFacade()
    client = _client(facade)
    first_headers = {
        **_bearer(_token()),
        "Idempotency-Key": "shared-photo-key",
    }
    second_headers = {
        **_bearer(_token(subject_id=_OTHER_IDENTITY_ID)),
        "Idempotency-Key": "shared-photo-key",
    }

    first = client.put(
        "/v1/doctor/profile/photo",
        files={"file": ("photo.jpg", b"photo-bytes", "image/jpeg")},
        headers=first_headers,
    )
    second = client.put(
        "/v1/doctor/profile/photo",
        files={"file": ("photo.jpg", b"photo-bytes", "image/jpeg")},
        headers=second_headers,
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert [doctor_id for doctor_id, _, _ in facade.photo_update_calls] == [
        _PARTNER_ID,
        _OTHER_PARTNER_ID,
    ]


def test_get_doctor_profile_photo_streams_private_bytes() -> None:
    facade = StubPartnerFacade()
    client = _client(facade)

    response = client.get(
        "/v1/doctor/profile/photo",
        headers=_bearer(_token()),
    )

    assert response.status_code == 200
    assert response.content == b"photo-bytes"
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["cache-control"] == "no-store"
    assert facade.photo_get_calls == [_PARTNER_ID]


def test_get_doctor_profile_photo_returns_404_when_unset() -> None:
    facade = StubPartnerFacade()
    facade.photo_error = DoctorProfilePhotoNotFoundError(_PARTNER_ID)
    client = _client(facade)

    response = client.get(
        "/v1/doctor/profile/photo",
        headers=_bearer(_token()),
    )

    assert response.status_code == 404
    assert response.json()["code"] == "DOCTOR_PROFILE_PHOTO_NOT_FOUND"


def test_put_doctor_profile_photo_maps_validation_failure() -> None:
    facade = StubPartnerFacade()
    facade.photo_error = DoctorProfilePhotoValidationError("invalid photo")
    client = _client(facade)

    response = client.put(
        "/v1/doctor/profile/photo",
        files={"file": ("photo.gif", b"GIF89a", "image/gif")},
        headers=_bearer(_token()),
    )

    assert response.status_code == 422
    assert response.json()["code"] == "DOCTOR_PROFILE_PHOTO_INVALID"
    assert response.json()["details"]["errors"] == [{"path": "file", "reason": "invalid photo"}]


def test_get_doctor_profile_photo_refuses_non_active_doctor() -> None:
    facade = StubPartnerFacade()
    facade.partner_status = "Registered"
    client = _client(facade)

    response = client.get(
        "/v1/doctor/profile/photo",
        headers=_bearer(_token()),
    )

    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_INSUFFICIENT_SCOPE"
    assert facade.photo_get_calls == []


def test_delete_doctor_profile_photo_returns_no_content() -> None:
    facade = StubPartnerFacade()
    client = _client(facade)

    response = client.delete(
        "/v1/doctor/profile/photo",
        headers=_bearer(_token()),
    )

    assert response.status_code == 204
    assert response.content == b""
    assert facade.photo_delete_calls == [_PARTNER_ID]


def test_delete_doctor_profile_photo_replays_the_same_idempotency_key() -> None:
    facade = StubPartnerFacade()
    client = _client(facade)
    headers = {
        **_bearer(_token()),
        "Idempotency-Key": "delete-photo-key",
    }

    first = client.delete("/v1/doctor/profile/photo", headers=headers)
    second = client.delete("/v1/doctor/profile/photo", headers=headers)

    assert first.status_code == 204
    assert second.status_code == 204
    assert facade.photo_delete_calls == [_PARTNER_ID]
