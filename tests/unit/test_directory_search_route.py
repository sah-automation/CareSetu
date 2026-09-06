"""PHASE-6 T02a: GET /v1/directory/search HTTP adapter (ticket #313).

The route is a thin PUBLIC adapter: parse the typed query params, call the
directory facade, answer the typed view. No auth rides these routes - patients
browse the directory without logging in (FEAT-004), so the request carries no
principal and the facade call carries no ``patient_id``. The facade is stubbed
here; the DB-backed behavior (Active-with-valid-credentials visibility rule,
filters, wider-area fallback, nearest-first ordering) is the integration
suite's job. The edge enforces the closed pick-lists: an unknown
``partner_type`` or ``specialty`` answers the shared error envelope with 422,
never reaching the facade; ``lat``/``lng`` range-clamp too.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app
from modules.partner.facade import (
    DALTONGANJ_LATITUDE,
    DALTONGANJ_LONGITUDE,
    DEFAULT_SERVICE_AREA_NAME,
    DirectoryEntry,
    DirectorySearchView,
)


class StubDirectoryFacade:
    """Minimal facade stand-in recording call kwargs and replaying a view."""

    def __init__(self) -> None:
        self.called_with: list[dict] = []
        self.view = DirectorySearchView(items=[], fell_back=False)

    async def search_directory(self, **kwargs: object) -> DirectorySearchView:
        self.called_with.append(kwargs)
        return self.view


def _client_with(facade: StubDirectoryFacade) -> TestClient:
    app = create_app()
    app.state.partner_facade = facade
    return TestClient(app)


def test_search_answers_200_without_login_and_passes_geo_through() -> None:
    """Open route: no Authorization header, no geo - the facade owns the default."""
    facade = StubDirectoryFacade()
    client = _client_with(facade)

    response = client.get("/v1/directory/search")

    assert response.status_code == 200
    assert response.json() == {"items": [], "fell_back": False}
    assert facade.called_with == [
        {
            "query": None,
            "partner_type": None,
            "specialty": None,
            "latitude": None,
            "longitude": None,
        }
    ]


def test_search_forwards_typed_filters_and_geo() -> None:
    facade = StubDirectoryFacade()
    client = _client_with(facade)

    response = client.get(
        "/v1/directory/search",
        params={
            "q": "Sharma",
            "partner_type": "doctor",
            "specialty": "General Physician",
            "lat": DALTONGANJ_LATITUDE,
            "lng": DALTONGANJ_LONGITUDE,
        },
    )

    assert response.status_code == 200
    assert facade.called_with == [
        {
            "query": "Sharma",
            "partner_type": "doctor",
            "specialty": "General Physician",
            "latitude": DALTONGANJ_LATITUDE,
            "longitude": DALTONGANJ_LONGITUDE,
        }
    ]


def test_search_answers_typed_view_with_items() -> None:
    facade = StubDirectoryFacade()
    facade.view = DirectorySearchView(
        items=[
            DirectoryEntry(
                partner_id=11,
                practice_name="Shanti Clinic",
                partner_type="doctor",
                specialty="General Physician",
                area=DEFAULT_SERVICE_AREA_NAME,
                distance_km=1.2,
                verified=True,
            )
        ],
        fell_back=True,
    )
    client = _client_with(facade)

    response = client.get("/v1/directory/search", params={"partner_type": "doctor"})

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "partner_id": 11,
                "practice_name": "Shanti Clinic",
                "partner_type": "doctor",
                "specialty": "General Physician",
                "area": DEFAULT_SERVICE_AREA_NAME,
                "distance_km": 1.2,
                "verified": True,
            }
        ],
        "fell_back": True,
    }
    assert facade.called_with[0]["partner_type"] == "doctor"


def test_search_disallowed_fields_never_serialized() -> None:
    """The public search response stays verified-safe: no artifacts, emails,
    phones, PHI or identity keys ever appear in the payload."""

    facade = StubDirectoryFacade()
    facade.view = DirectorySearchView(
        items=[
            DirectoryEntry(
                partner_id=11,
                practice_name="Shanti Clinic",
                partner_type="doctor",
                specialty="General Physician",
                area=DEFAULT_SERVICE_AREA_NAME,
                distance_km=1.2,
                verified=True,
            )
        ],
        fell_back=False,
    )
    client = _client_with(facade)

    response = client.get("/v1/directory/search")

    assert response.status_code == 200
    assert response.json()["items"][0]["area"] == DEFAULT_SERVICE_AREA_NAME
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


def test_search_rejects_unknown_specialty_with_422() -> None:
    facade = StubDirectoryFacade()
    client = _client_with(facade)

    response = client.get("/v1/directory/search", params={"specialty": "Ent Doctor"})

    assert response.status_code == 422
    assert facade.called_with == []


def test_search_rejects_unknown_partner_type_with_422() -> None:
    facade = StubDirectoryFacade()
    client = _client_with(facade)

    response = client.get("/v1/directory/search", params={"partner_type": "hospital"})

    assert response.status_code == 422
    assert facade.called_with == []


def test_search_rejects_out_of_range_lat_lng_with_422() -> None:
    facade = StubDirectoryFacade()
    client = _client_with(facade)

    assert client.get("/v1/directory/search", params={"lat": -91}).status_code == 422
    assert client.get("/v1/directory/search", params={"lng": 181}).status_code == 422
    assert facade.called_with == []
