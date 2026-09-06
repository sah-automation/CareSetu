"""PHASE-6 T4: POST /v1/directory/select HTTP adapter (ticket #326).

The route is a thin PUBLIC adapter: parse the typed body, call the directory
pick facade, answer 204. No auth rides it - patients pick a provider without
logging in (FEAT-004), so the request carries no principal and the recorded
``partner.selected`` event has no actor. The facade is stubbed here; the
DB-backed outbox write is the integration suite's job. Validation is strict
(api-standards §3): an unknown ``partner_type`` or an extra field answers the
error envelope with 422, never reaching the facade.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app


class StubSelectFacade:
    """Minimal facade stand-in recording call kwargs."""

    def __init__(self) -> None:
        self.called_with: list[dict] = []

    async def record_partner_selected(self, **kwargs: object) -> None:
        self.called_with.append(kwargs)


def _client_with(facade: StubSelectFacade) -> TestClient:
    app = create_app()
    app.state.partner_facade = facade
    return TestClient(app)


def test_select_records_one_pick_without_login() -> None:
    """Open route: no Authorization header, one outbox-less facade call."""
    facade = StubSelectFacade()
    client = _client_with(facade)

    response = client.post(
        "/v1/directory/select",
        json={"partner_id": 11, "partner_type": "doctor", "source": "search-card"},
    )

    assert response.status_code == 204
    assert response.content == b""
    assert facade.called_with == [
        {"partner_id": 11, "partner_type": "doctor", "source": "search-card"}
    ]


def test_select_minimal_pick_is_legal() -> None:
    """Only ``partner_id`` is mandatory - type/source stay optional."""
    facade = StubSelectFacade()
    client = _client_with(facade)

    response = client.post("/v1/directory/select", json={"partner_id": 11})

    assert response.status_code == 204
    assert facade.called_with == [{"partner_id": 11, "partner_type": None, "source": None}]


def test_select_rejects_unknown_partner_type_with_422() -> None:
    facade = StubSelectFacade()
    client = _client_with(facade)

    response = client.post(
        "/v1/directory/select", json={"partner_id": 11, "partner_type": "hospital"}
    )

    assert response.status_code == 422
    assert facade.called_with == []


def test_select_rejects_non_positive_partner_id_with_422() -> None:
    facade = StubSelectFacade()
    client = _client_with(facade)

    assert client.post("/v1/directory/select", json={"partner_id": 0}).status_code == 422
    assert client.post("/v1/directory/select", json={"partner_id": -3}).status_code == 422
    assert facade.called_with == []


def test_select_rejects_extra_fields_with_422() -> None:
    """Strict body (api-standards §3): an unknown field is rejected, never
    silently carried into the analytics payload."""
    facade = StubSelectFacade()
    client = _client_with(facade)

    response = client.post(
        "/v1/directory/select",
        json={"partner_id": 11, "patient_id": 999},
    )

    assert response.status_code == 422
    assert facade.called_with == []
