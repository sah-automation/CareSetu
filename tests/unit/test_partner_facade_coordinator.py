"""Coordinator delegation test for the partner facade (ADR-0006, WI-2 p1a #332).

The coordinator ``PartnerFacade`` keeps its exact public surface and routes the
five registration methods to ``RegistrationFacade`` (ADR-0006 consequence: the
coordinator is a thin delegation layer "tested with a simple mock"). These tests
pin that delegation - the public signatures and the sub-facade hand-off - so a
change to the coordinator wiring is caught at unit level without touching the
DB-backed behavior (which the integration suites own). The sub-facade's own
direct-seam behavior is pinned in ``test_partner_facade_register.py``.
"""

from __future__ import annotations

from typing import cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from modules.iam.facade import IamFacade
from modules.partner.facade import PartnerFacade
from modules.partner.registration_facade import RegistrationFacade


def _engine() -> AsyncMock:
    engine = AsyncMock(spec=AsyncEngine)
    engine.begin.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
    engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)
    return engine


def _coordinator() -> tuple[PartnerFacade, RegistrationFacade]:
    coordinator = PartnerFacade(
        engine=_engine(),
        iam_facade=AsyncMock(spec=IamFacade),
    )
    sub_facade = cast(RegistrationFacade, AsyncMock(spec=RegistrationFacade))
    coordinator._registration = sub_facade
    return coordinator, sub_facade


@pytest.mark.asyncio
async def test_register_delegates_to_the_sub_facade_unchanged() -> None:
    coordinator, sub_facade = _coordinator()

    await coordinator.register(
        phone="9876543210",
        partner_type="doctor",
        practice_address="Station Road, Daltonganj",
        practice_latitude=24.04,
        practice_longitude=84.07,
    )

    sub_facade.register.assert_awaited_once_with(
        phone="9876543210",
        partner_type="doctor",
        practice_address="Station Road, Daltonganj",
        practice_latitude=24.04,
        practice_longitude=84.07,
        service_area_id=None,
        practice_name=None,
    )


@pytest.mark.asyncio
async def test_register_partner_delegates_to_the_sub_facade() -> None:
    coordinator, sub_facade = _coordinator()

    await coordinator.register_partner(
        identity_id=7,
        partner_type="chemist",
        practice_address="Jubilee Road",
        practice_latitude=24.04,
        practice_longitude=84.07,
    )

    sub_facade.register_partner.assert_awaited_once_with(
        identity_id=7,
        partner_type="chemist",
        practice_address="Jubilee Road",
        practice_latitude=24.04,
        practice_longitude=84.07,
        service_area_id=None,
    )


@pytest.mark.asyncio
async def test_resolve_partner_delegates_to_the_sub_facade() -> None:
    coordinator, sub_facade = _coordinator()

    await coordinator.resolve_partner(7)

    sub_facade.resolve_partner.assert_awaited_once_with(7)


@pytest.mark.asyncio
async def test_resolve_partner_id_by_identity_delegates_to_the_sub_facade() -> None:
    coordinator, sub_facade = _coordinator()

    await coordinator.resolve_partner_id_by_identity(7)

    sub_facade.resolve_partner_id_by_identity.assert_awaited_once_with(7)


@pytest.mark.asyncio
async def test_get_my_status_delegates_to_the_sub_facade() -> None:
    coordinator, sub_facade = _coordinator()

    await coordinator.get_my_status(7)

    sub_facade.get_my_status.assert_awaited_once_with(7)
