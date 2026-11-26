"""Unit tests for ARCH-P3 #856: inert sharding + multi-region stubs."""

import logging

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from app.config import Settings
from app.gateway.sharding import ShardingMiddleware
from app.main import create_app


def test_sharding_middleware_installed_only_when_enabled() -> None:
    off_app = create_app(settings=Settings(sharding_enabled=False))
    on_app = create_app(settings=Settings(sharding_enabled=True, shard_key="sk", shard_count=2))
    assert ShardingMiddleware not in [entry.cls for entry in off_app.user_middleware]
    assert ShardingMiddleware in [entry.cls for entry in on_app.user_middleware]


def test_sharding_attaches_identity_to_request_state_and_is_inert() -> None:
    settings = Settings(sharding_enabled=True, shard_key="shard-42", shard_count=2)
    app = create_app(settings=settings)
    app.state.settings = settings

    @app.get("/echo")
    def echo(request: Request) -> dict[str, str | None]:
        return {"shard": request.state.shard_key, "shard_id": request.state.shard_id}

    client = TestClient(app)
    response = client.get("/echo")
    assert response.status_code == 200
    assert response.json() == {"shard": "shard-42", "shard_id": "shard-42"}


def test_sharding_warns_once_not_per_request(caplog: pytest.LogCaptureFixture) -> None:
    settings = Settings(sharding_enabled=True, shard_key="shard-42", shard_count=2)
    app = create_app(settings=settings)

    with caplog.at_level(logging.WARNING):
        client = TestClient(app)
        assert client.get("/health").status_code == 200
        assert client.get("/health").status_code == 200

    warnings = [
        record for record in caplog.records if "sharding enabled (inert)" in record.getMessage()
    ]
    assert len(warnings) == 1


def test_multi_region_records_region_and_replication_in_health() -> None:
    settings = Settings(
        multi_region_enabled=True, region="us-east-1", cross_region_replication=True
    )
    app = create_app(settings=settings)
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["region"] == "us-east-1"
    assert body["multi_region_enabled"] is True
    assert body["cross_region_replication"] is True


def test_sharding_disabled_health_unchanged() -> None:
    app = create_app(settings=Settings())
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
