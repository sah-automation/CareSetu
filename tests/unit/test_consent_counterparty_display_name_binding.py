"""#649: the composition root's counterparty-name resolver for the consent log.

``ConsentFacade`` owns a seam, not the rules (#648): this file pins the rules
the composition root binds into it, and the ORDER they run in.

The order is load-bearing. ``intake-ai`` is recorded under the DOCTOR
counterparty type by the AI egress path, so an id check reached after the
doctor-type parse either fails to parse or - worse - answers a partner profile
for a machine's disclosure. Every failure path answers null, and both warnings
name the counterparty type only: never the id, never PHI, never the exception's
payload.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from types import SimpleNamespace

import pytest

from app.main import (
    AI_INTAKE_COUNTERPARTY_DISPLAY_NAME,
    _build_counterparty_display_name_resolver,
)
from modules.intake.adapters import AI_EGRESS_COUNTERPARTY_ID
from modules.partner.facade import ProviderProfileNotFoundError

_PARTNER_ID = 777
_PRACTICE_NAME = "Sunrise Clinic"

Resolver = Callable[[str, str], Awaitable[str | None]]


class _StubPartnerFacade:
    """The provider-profile seam, replaying a name and recording its calls."""

    def __init__(
        self,
        *,
        practice_name: str | None = _PRACTICE_NAME,
        error: Exception | None = None,
    ) -> None:
        self.practice_name = practice_name
        self.error = error
        self.requested: list[int] = []

    async def get_provider_profile(self, partner_id: int) -> SimpleNamespace:
        self.requested.append(partner_id)
        if self.error is not None:
            raise self.error
        return SimpleNamespace(practice_name=self.practice_name)


def _resolver(partner_facade: object) -> Resolver:
    """The resolver the composition root would bind, over a fake app state."""
    app = SimpleNamespace(state=SimpleNamespace(partner_facade=partner_facade))
    return _build_counterparty_display_name_resolver(app)


def _warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.WARNING and record.name == "app.main"
    ]


# ---------------------------------------------------------------------------
# The id check precedes the doctor-type parse
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_ai_pseudo_counterparty_names_a_service_before_any_type_parse() -> None:
    stub = _StubPartnerFacade(error=AssertionError("the partner seam must not be reached"))
    resolve = _resolver(stub)

    name = await resolve("doctor", AI_EGRESS_COUNTERPARTY_ID)

    assert name == AI_INTAKE_COUNTERPARTY_DISPLAY_NAME
    assert stub.requested == []


# ---------------------------------------------------------------------------
# A doctor counterparty resolves through the provider-profile seam
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_doctor_id_that_parses_answers_the_practice_name() -> None:
    stub = _StubPartnerFacade()
    resolve = _resolver(stub)

    name = await resolve("doctor", str(_PARTNER_ID))

    assert name == _PRACTICE_NAME
    # The id was parsed into the partner id the seam addresses.
    assert stub.requested == [_PARTNER_ID]


@pytest.mark.asyncio
async def test_a_doctor_id_that_does_not_parse_answers_no_name() -> None:
    stub = _StubPartnerFacade()
    resolve = _resolver(stub)

    name = await resolve("doctor", "not-a-partner-id")

    assert name is None
    assert stub.requested == []


@pytest.mark.asyncio
async def test_a_practice_name_that_is_absent_stays_null() -> None:
    stub = _StubPartnerFacade(practice_name=None)
    resolve = _resolver(stub)

    name = await resolve("doctor", str(_PARTNER_ID))

    assert name is None


# ---------------------------------------------------------------------------
# Lab and chemist resolve to null: those partner phases have not landed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lab_and_chemist_counterparties_answer_no_name_without_a_profile_read() -> None:
    stub = _StubPartnerFacade()
    resolve = _resolver(stub)

    lab = await resolve("lab", str(_PARTNER_ID))
    chemist = await resolve("chemist", str(_PARTNER_ID))

    assert lab is None
    assert chemist is None
    assert stub.requested == []


# ---------------------------------------------------------------------------
# Every failure degrades to null and warns with the type only
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_partner_profile_miss_degrades_to_null_and_warns_the_type_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    stub = _StubPartnerFacade(error=ProviderProfileNotFoundError(_PARTNER_ID))
    resolve = _resolver(stub)

    with caplog.at_level(logging.WARNING, logger="app.main"):
        name = await resolve("doctor", str(_PARTNER_ID))

    assert name is None
    warnings = _warnings(caplog)
    assert warnings
    assert all("doctor" in message for message in warnings)
    # The not-found message carries the partner id; the log line must not.
    assert all(str(_PARTNER_ID) not in message for message in warnings)


@pytest.mark.asyncio
async def test_a_resolver_exception_degrades_to_null_and_warns_the_type_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    stub = _StubPartnerFacade(
        error=RuntimeError(f"partner schema unreachable for partner {_PARTNER_ID}")
    )
    resolve = _resolver(stub)

    with caplog.at_level(logging.WARNING, logger="app.main"):
        name = await resolve("doctor", str(_PARTNER_ID))

    assert name is None
    warnings = _warnings(caplog)
    assert len(warnings) == 1
    assert "doctor" in warnings[0]
    # The warning names the type only - not the exception class, not the id,
    # not the payload.
    assert "RuntimeError" not in warnings[0]
    assert str(_PARTNER_ID) not in warnings[0]
    assert "partner schema unreachable" not in warnings[0]
