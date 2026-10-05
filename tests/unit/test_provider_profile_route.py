"""PHASE-6 T03: GET /v1/directory/providers/{id} HTTP adapter (ticket #309, #613).

The route is a thin PUBLIC adapter: parse the typed path id, call the
directory profile facade, answer the typed view. No auth rides these routes -
patients view a provider's public profile without logging in (FEAT-005), so
the request carries no principal. The facade is stubbed here; the DB-backed
visibility rule (only [Active] partners with a directory_index entry and all
valid credentials resolve; everything else 404s) is the integration suite's
job. The edge maps the facade's ``ProviderProfileNotFoundError`` to the shared
error envelope with 404 - a hidden partner answers 404, never a "hidden" 200.

Since #613 the payload carries two bands: the credential band the platform
checked and the practice details the doctor declared. Both are asserted here,
because the widening is only safe while the second one still cannot widen the
first - so the ``verified`` assertion is kept exactly as it was, and the
disallowed-fields scan gained the fields that would be a leak if the widening
were careless.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.main import create_app
from modules.partner.domain.exceptions import ProviderProfileNotFoundError
from modules.partner.facade import ProviderCredential, ProviderProfileView


class StubProfileFacade:
    """Minimal facade stand-in recording path ids and replaying a view."""

    def __init__(self) -> None:
        self.called_with: list[int] = []
        # A doctor who has filled their profile in completely, so the declared
        # band is carrying values rather than nulls - a widening that only ever
        # served empties would pass this suite while shipping nothing.
        self.view = ProviderProfileView(
            partner_id=11,
            practice_name="Dr. Asha Verma",
            partner_type="doctor",
            specialty="General Physician",
            specialties=["General Physician", "Pediatrician"],
            area="Daltonganj",
            verified=True,
            clinic_name="Shanti Clinic",
            languages=["Hindi", "English"],
            consulting_days=["Monday", "Tuesday", "Saturday"],
            consulting_hours="Mon-Sat, 9am-1pm",
            about="Twenty years of neighbourhood practice, children first.",
            experience_years=20,
            address_line="12, Nehru Road",
            landmark="Near the water tank",
            locality="Sadar",
            city="Daltonganj",
            pin_code="827101",
            consultation_fee=50000,
            credentials=[
                ProviderCredential(
                    credential_type="medical_registration",
                    status="verified",
                    expires_at=datetime.now(UTC) + timedelta(days=180),
                )
            ],
        )

    async def get_provider_profile(self, partner_id: int) -> ProviderProfileView:
        self.called_with.append(partner_id)
        return self.view


def _client_with(facade: StubProfileFacade) -> TestClient:
    app = create_app()
    app.state.partner_facade = facade
    return TestClient(app)


def test_profile_answers_200_without_login_and_forwards_partner_id() -> None:
    """Open route: no Authorization header, the path id reaches the facade."""
    facade = StubProfileFacade()
    client = _client_with(facade)

    response = client.get("/v1/directory/providers/11")

    assert response.status_code == 200
    assert facade.called_with == [11]


def test_profile_answers_the_verified_band_and_a_200_shape() -> None:
    """The credential band is unchanged by the widening: same fields, same values."""
    facade = StubProfileFacade()
    client = _client_with(facade)

    response = client.get("/v1/directory/providers/11")

    assert response.status_code == 200
    body = response.json()
    assert body["partner_id"] == 11
    assert body["practice_name"] == "Dr. Asha Verma"
    assert body["partner_type"] == "doctor"
    assert body["specialty"] == "General Physician"
    assert body["area"] == "Daltonganj"
    # The whole point of AC 4: reaching the profile proved the gate and nothing
    # else, so the indicator is still True and still says nothing about a
    # declared field.
    assert body["verified"] is True
    assert body["consultation_fee"] == 50000
    assert body["credentials"] == [facade.view.credentials[0].model_dump(mode="json")]


def test_profile_carries_the_declared_fields_the_doctor_wrote() -> None:
    """#613: clinic, specialties, languages, days, hours, about, years, address."""
    facade = StubProfileFacade()
    client = _client_with(facade)

    response = client.get("/v1/directory/providers/11")

    assert response.status_code == 200
    body = response.json()
    assert body["clinic_name"] == "Shanti Clinic"
    assert body["specialties"] == ["General Physician", "Pediatrician"]
    assert body["languages"] == ["Hindi", "English"]
    assert body["consulting_days"] == ["Monday", "Tuesday", "Saturday"]
    assert body["consulting_hours"] == "Mon-Sat, 9am-1pm"
    assert body["about"] == "Twenty years of neighbourhood practice, children first."
    assert body["experience_years"] == 20
    assert body["address_line"] == "12, Nehru Road"
    assert body["landmark"] == "Near the water tank"
    assert body["locality"] == "Sadar"
    assert body["city"] == "Daltonganj"
    assert body["pin_code"] == "827101"


def test_profile_serializes_an_undeclared_band_as_nulls_and_empty_lists() -> None:
    """An unfinished profile is a state a doctor can hold: null, never a 0 or a ""."""
    facade = StubProfileFacade()
    facade.view = facade.view.model_copy(
        update={
            "clinic_name": None,
            "specialties": [],
            "languages": [],
            "consulting_days": [],
            "consulting_hours": None,
            "about": None,
            "experience_years": None,
            "address_line": None,
            "landmark": None,
            "locality": None,
            "city": None,
            "pin_code": None,
        }
    )
    client = _client_with(facade)

    response = client.get("/v1/directory/providers/11")

    assert response.status_code == 200
    body = response.json()
    assert body["clinic_name"] is None
    assert body["specialties"] == []
    assert body["about"] is None
    assert body["experience_years"] is None
    assert body["pin_code"] is None
    assert body["verified"] is True


def test_profile_serializes_unset_fee_as_null() -> None:
    """An unset consultation fee stays null on the profile projection - never a 0."""
    facade = StubProfileFacade()
    facade.view = facade.view.model_copy(update={"consultation_fee": None})
    client = _client_with(facade)

    response = client.get("/v1/directory/providers/11")

    assert response.status_code == 200
    assert response.json()["consultation_fee"] is None


def test_profile_disallowed_fields_never_serialized() -> None:
    """No artifact refs, contact details, coordinates or PHI anywhere in the payload.

    A whole-response substring scan rather than a key allowlist, so a field
    RENAMED into something forbidden still fails here. Deliberate contents for
    #613:

    - ``photo_ref`` is new to this list because the declared band is where a
      photo reference would most plausibly creep in, and the ``artifact``
      substring cannot catch it (ADR-0020: the bytes live in a private prefix,
      only the ref is ever in SQL, and a ref is exactly what must not widen in).
    - ``practice_address`` STAYS, even though #613 replaced the field with the
      structured parts. It is a forbidden substring, not a forbidden field: the
      assertion is that the registration-era display string never reaches a
      patient, which is a stronger claim than "that key is gone" and holds
      whichever way the projection is spelled.
    """
    facade = StubProfileFacade()
    client = _client_with(facade)

    response = client.get("/v1/directory/providers/11")

    assert response.status_code == 200
    raw = response.text
    for forbidden in (
        "artifact_refs",
        "artifact",
        "photo_ref",
        "email",
        "phone",
        "identity_id",
        "practice_address",
        "practice_latitude",
        "practice_longitude",
        "notification_preferences",
        "revoked_at",
    ):
        assert forbidden.lower() not in raw.lower()


def test_profile_missing_partner_maps_to_404_envelope() -> None:
    """A hidden partner answers the shared envelope with 404, never a 200."""
    facade = StubProfileFacade()

    async def raise_profile_not_found(partner_id: int) -> ProviderProfileView:
        facade.called_with.append(partner_id)
        raise ProviderProfileNotFoundError(partner_id)

    facade.get_provider_profile = raise_profile_not_found  # type: ignore[method-assign]
    client = _client_with(facade)

    response = client.get("/v1/directory/providers/999")

    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "PROVIDER_PROFILE_NOT_FOUND"
    assert "no public provider profile exists" in body["message"]
    assert "trace_id" in body
    assert "details" in body
    assert facade.called_with == [999]


def test_profile_route_sits_behind_the_gateway_stack() -> None:
    app = create_app()
    paths = app.openapi()["paths"]
    assert "/v1/directory/providers/{partner_id}" in paths
