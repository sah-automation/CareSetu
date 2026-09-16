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

from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from modules.iam.facade import IamFacade
from modules.partner.domain.exceptions import ConsultationFeeNotAllowedError
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


class _ProfileRow:
    """Mimics a ``partner_profiles`` SELECT row for the fee update seam."""

    def __init__(
        self,
        *,
        id: int,
        identity_id: int,
        partner_type: str,
        status: str,
        round: int,
    ) -> None:
        self.id = id
        self.identity_id = identity_id
        self.partner_type = partner_type
        self.status = status
        self.round = round
        self.appeal_used = False
        self.re_submission_count = 0
        self.re_submission_blocked_until = None
        self.created_at = None


class _ExecResult:
    """Mimics executed-statement result shapes the fee seam consumes."""

    def __init__(self, *, row: _ProfileRow | None = None, scalar: int | None = None) -> None:
        self._row = row
        self._scalar = scalar

    def first(self) -> _ProfileRow | None:
        return self._row

    def scalar_one(self) -> int:
        assert self._scalar is not None
        return self._scalar


def _fee_connection(*, profile: _ProfileRow | None) -> AsyncMock:
    """A connection where the identity lookup yields ``profile`` (round = 1)."""
    connection = AsyncMock()
    connection.execute = AsyncMock(
        side_effect=[
            _ExecResult(row=profile),  # identity lookup
            _ExecResult(scalar=1),  # verification round
            _ExecResult(),  # UPDATE partner_profiles
        ]
    )
    return connection


def _executed(connection: AsyncMock) -> list[Any]:
    return [call.args[0] for call in connection.execute.await_args_list]


@pytest.mark.asyncio
async def test_update_consultation_fee_doctor_writes_paise_and_flushes_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coordinator, _sub = _coordinator()
    flushed: list[bool] = []

    async def _flush() -> None:
        flushed.append(True)

    monkeypatch.setattr("modules.partner.directory_cache.directory_visibility_changed", _flush)
    connection = _fee_connection(
        profile=_ProfileRow(id=42, identity_id=7, partner_type="doctor", status="Active", round=1)
    )
    coordinator._engine.begin.return_value.__aenter__ = AsyncMock(return_value=connection)

    result = await coordinator.update_consultation_fee(7, fee_paise=50000)

    assert result.partner_id == 42
    assert result.partner_type == "doctor"
    assert result.status == "Active"
    assert result.round == 1
    update = _executed(connection)[2]
    assert update.table.name == "partner_profiles"
    assert update._values["consultation_fee_paise"].value == 50000
    assert "updated_at" in update._values
    assert flushed == [True]


@pytest.mark.asyncio
async def test_update_consultation_fee_non_doctor_is_refused() -> None:
    coordinator, _sub = _coordinator()
    connection = _fee_connection(
        profile=_ProfileRow(id=99, identity_id=7, partner_type="lab", status="Active", round=1)
    )
    coordinator._engine.begin.return_value.__aenter__ = AsyncMock(return_value=connection)

    with pytest.raises(ConsultationFeeNotAllowedError):
        await coordinator.update_consultation_fee(7, fee_paise=50000)

    # The refusal happens before any write: only the identity lookup and the
    # round read ran - the partner_profiles UPDATE never executed.
    assert len(_executed(connection)) == 2


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
