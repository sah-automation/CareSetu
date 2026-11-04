"""Unit tests for ARCH-P3 #854: completed module router guards."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def _paths(app: FastAPI) -> set[str]:
    return set(app.openapi()["paths"])


def test_directory_routes_follow_the_partner_flag() -> None:
    off = create_app(settings=Settings(module_partner_enabled=False))
    on = create_app(settings=Settings(module_partner_enabled=True))

    assert "/v1/directory/search" not in _paths(off)
    assert "/v1/directory/search" in _paths(on)


def test_disabled_directory_returns_not_found() -> None:
    client = TestClient(create_app(settings=Settings(module_partner_enabled=False)))

    assert client.get("/v1/directory/search").status_code == 404


def test_doctor_routes_follow_the_doctor_flag() -> None:
    off = create_app(settings=Settings(module_doctor_enabled=False))
    on = create_app(settings=Settings(module_doctor_enabled=True))

    assert "/v1/doctor/profile" not in _paths(off)
    assert "/v1/doctor/profile" in _paths(on)


def test_disabled_doctor_returns_not_found() -> None:
    client = TestClient(create_app(settings=Settings(module_doctor_enabled=False)))

    assert client.get("/v1/doctor/profile").status_code == 404


def test_reserved_module_flags_do_not_change_the_router_surface() -> None:
    baseline = _paths(create_app(settings=Settings()))

    for flag in (
        "module_notify_enabled",
        "module_settlement_enabled",
        "module_fulfillment_enabled",
        "module_diagnostics_enabled",
    ):
        disabled = create_app(settings=Settings(**{flag: False}))
        assert _paths(disabled) == baseline
