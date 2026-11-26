"""Unit tests for read-replica routing (ARCH-P1 #814)."""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.config import Settings
from app.db.read_replica import (
    ReadReplicaMiddleware,
    ReadReplicaRouter,
    current_engine,
    is_read_replica_eligible,
)


@pytest.mark.parametrize(
    "method,path,expected",
    [
        ("GET", "/v1/directory/search", True),
        ("HEAD", "/v1/directory/search", True),
        ("POST", "/v1/directory/search", False),
        ("GET", "/v1/directory/providers/42", True),
        ("GET", "/v1/directory/providers/", True),
        ("GET", "/v1/care/cases", True),
        ("GET", "/v1/care/cases/7/rx/current", False),
        ("GET", "/v1/me/profile", True),
        ("GET", "/v1/auth/login", False),
        ("GET", "/v1/consents", False),
        ("GET", "/v1/audit/log", False),
        ("GET", "/v1/doctor/patients", False),
        ("GET", "/v1/doctor/cases", False),
        ("GET", "/v1/intake/review-queue", False),
        ("GET", "/v1/care/cases/7", True),
    ],
)
def test_read_replica_eligibility(method: str, path: str, expected: bool) -> None:
    assert is_read_replica_eligible(method, path) is expected


def test_settings_defaults() -> None:
    settings = Settings()
    assert settings.database_read_urls == ()
    assert settings.read_replica_enabled is False
    assert settings.read_replica_lag_tolerance_ms == 1000
    assert settings.read_replica_retry_cooldown_seconds == 30.0


class _Engine:
    def __init__(self, name: str) -> None:
        self.name = name
        self.disposed = False

    @asynccontextmanager
    async def begin(self):
        yield f"txn:{self.name}"

    @asynccontextmanager
    async def connect(self):
        yield f"conn:{self.name}"

    async def dispose(self) -> None:
        self.disposed = True


def test_round_robin_selection() -> None:
    primary = _Engine("primary")
    r0 = _Engine("r0")
    r1 = _Engine("r1")
    router = ReadReplicaRouter(
        primary=primary, replicas=[r0, r1], enabled=True, read_replica_enabled=True
    )
    picks = [router.select_engine("GET", "/v1/directory/search").name for _ in range(4)]
    assert picks == ["r0", "r1", "r0", "r1"]


def test_unhealthy_cooldown_skips_replica() -> None:
    primary = _Engine("primary")
    r0 = _Engine("r0")
    r1 = _Engine("r1")
    router = ReadReplicaRouter(
        primary=primary, replicas=[r0, r1], enabled=True, read_replica_enabled=True
    )
    router.mark_unhealthy(r0)
    picks = [router.select_engine("GET", "/v1/directory/search").name for _ in range(2)]
    assert picks == ["r1", "r1"]


def test_primary_fallback_when_no_healthy_replica() -> None:
    primary = _Engine("primary")
    r0 = _Engine("r0")
    router = ReadReplicaRouter(
        primary=primary, replicas=[r0], enabled=True, read_replica_enabled=True
    )
    router.mark_unhealthy(r0)
    assert router.select_engine("GET", "/v1/directory/search") is primary


@pytest.mark.asyncio
async def test_router_begin_delegates_to_selection() -> None:
    primary = _Engine("primary")
    r0 = _Engine("r0")
    router = ReadReplicaRouter(
        primary=primary, replicas=[r0], enabled=True, read_replica_enabled=True
    )
    from app.db.read_replica import reset_current_engine, set_current_engine

    token = set_current_engine(r0)
    try:
        async with router.begin() as value:
            assert value == "txn:r0"
    finally:
        reset_current_engine(token)


@pytest.mark.asyncio
async def test_dispose_engines() -> None:
    primary = _Engine("primary")
    r0 = _Engine("r0")
    router = ReadReplicaRouter(
        primary=primary, replicas=[r0], enabled=True, read_replica_enabled=True
    )
    await router.dispose()
    assert primary.disposed is True
    assert r0.disposed is True


def test_request_context_resets() -> None:
    primary = _Engine("primary")
    replica = _Engine("replica")
    app = FastAPI()
    app.state.primary_engine = primary
    app.state.replica_engines = [replica]
    app.state.settings = Settings(
        database_read_urls=("postgresql+asyncpg://replica",), read_replica_enabled=True
    )
    app.add_middleware(ReadReplicaMiddleware)

    @app.get("/v1/directory/search")
    def search(request: Request) -> dict[str, bool]:
        return {
            "request_state": request.state.read_replica_engine is replica,
            "context": current_engine() is replica,
        }

    client = TestClient(app)
    response = client.get("/v1/directory/search")
    assert response.status_code == 200
    assert response.json()["request_state"] is True
    assert response.json()["context"] is True
    assert current_engine() is None
