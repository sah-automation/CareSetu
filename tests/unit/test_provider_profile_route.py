"""PHASE-6 T03: GET /v1/directory/providers/{id} HTTP adapter (ticket #309).

The route is a thin PUBLIC adapter: parse the typed path id, call the
directory profile facade, answer the typed view. No auth rides these routes -
patients view a provider's public profile without logging in (FEAT-005), so
the request carries no principal. The facade is stubbed here; the DB-backed
visibility rule (only [Active] partners with a directory_index entry and all
valid credentials resolve; everything else 404s) is the integration suite's
job. The edge maps the facade's ``ProviderProfileNotFoundError`` to the shared
error envelope with 404 - a hidden partner answers 404, never a "hidden" 200.
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
        self.view = ProviderProfileView(
            partner_id=11,
            practice_name="Shanti Clinic",
            partner_type="doctor",
            specialty="General Physician",
            area="Daltonganj",
            verified=True,
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


def test_profile_answers_typed_view_with_safe_fields() -> None:
    """The payload carries only verified-safe fields and always a 200 shape."""
    facade = StubProfileFacade()
    client = _client_with(facade)

    response = client.get("/v1/directory/providers/11")

    assert response.status_code == 200
    body = response.json()
    assert body["partner_id"] == 11
    assert body["practice_name"] == "Shanti Clinic"
    assert body["partner_type"] == "doctor"
    assert body["specialty"] == "General Physician"
    assert body["area"] == "Daltonganj"
    assert body["verified"] is True
    assert body["credentials"] == [facade.view.credentials[0].model_dump(mode="json")]


def test_profile_disallowed_fields_never_serialized() -> None:
    """No artifact refs, emails, phones or PHI keys ever appear in the payload."""
    facade = StubProfileFacade()
    client = _client_with(facade)

    response = client.get("/v1/directory/providers/11")

    assert response.status_code == 200
    raw = response.text
    for forbidden in (
        "artifact_refs",
        "artifact",
        "email",
        "phone",
        "identity_id",
        "practice_address",
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
