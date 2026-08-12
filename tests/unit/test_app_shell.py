"""PHASE-1 T7a: FastAPI app shell boots (ticket #28).

Boot contract from the brief: the app builds from the shared env-driven
``Settings``, serves ``/health`` with 200, and (from PHASE-2 T3, #54) mounts
exactly one business route - the iam register endpoint.
"""

import pytest
from fastapi.testclient import TestClient

from app.config import DEFAULT_DATABASE_URL, Settings
from app.main import create_app


def test_app_boots_from_default_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    app = create_app()

    assert app.state.settings.database_url == DEFAULT_DATABASE_URL


def test_app_reads_database_url_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    custom_url = "postgresql+asyncpg://env-db.internal:5432/envdb"
    monkeypatch.setenv("DATABASE_URL", custom_url)

    app = create_app()

    assert app.state.settings.database_url == custom_url


def test_app_accepts_explicit_settings() -> None:
    settings = Settings(database_url="postgresql+asyncpg://override-db.internal:5432/override")

    app = create_app(settings=settings)

    assert app.state.settings == settings


def test_health_returns_200() -> None:
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_register_route_is_the_only_business_route() -> None:
    app = create_app()

    assert set(app.openapi()["paths"]) == {"/health", "/v1/auth/register"}
