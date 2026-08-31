"""PHASE-5 T03: IAM partner role grant/deny round trip against real PostgreSQL (#248).

The phase-spec event chain: ``partner.activated`` / ``partner.rejected`` /
``credential.invalidated`` envelopes are published into the iam outbox (the iam
consumer owns the payload mirror and handler for each), a single poll pass over
the outbox table claims, fans out and deletes them, and iam mutates
``iam_role_grants`` so the ``partner`` role is granted on activation and
suspended on rejection / credential invalidation - observable through the iam
facade. Replaying the same ``event_id`` through the idempotent consumer leaves
the grant unchanged.

Requires the native PostgreSQL; the suite skips cleanly when it is unreachable,
migrates ``iam`` to head and downgrades afterwards.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from sqlalchemy.pool import NullPool

from bus.dispatch import dispatch
from bus.dispatcher import DEFAULT_DISPATCHER_CONFIG, discover_outbox_tables, process_outbox_table
from bus.envelope import Envelope
from bus.events import (
    EVENT_CREDENTIAL_INVALIDATED,
    EVENT_PARTNER_ACTIVATED,
    EVENT_PARTNER_REJECTED,
)
from bus.outbox_writer import write_outbox
from bus.registry import HandlerRegistry
from modules.iam.adapters import register_handlers as register_iam_handlers
from modules.iam.adapters.sms import MockSmsAdapter, SmsAdapter
from modules.iam.domain.consumer import (
    CredentialInvalidatedPayload,
    PartnerActivatedPayload,
    PartnerRejectedPayload,
)
from modules.iam.facade import IamFacade
from modules.iam.outbox import IAM_OUTBOX_TABLE

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "apps" / "backend" / "alembic.ini"

_PHONE = "+919876543210"
_SECOND_PHONE = "+919876543211"
_T0 = datetime(2026, 8, 31, 12, 0, 0, tzinfo=UTC)


class MutableClock:
    """Clock stand-in that tests advance to walk cooldown windows."""

    def __init__(self, now: datetime) -> None:
        self._now = now

    def __call__(self) -> datetime:
        return self._now


def _alembic_config(database_url: str) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


@pytest.fixture(scope="module")
def migrated_iam(database_url: str) -> Iterator[None]:
    """Migrate the ``iam`` schema to head, restore base after."""
    config = _alembic_config(database_url)
    try:
        command.upgrade(config, "head")
    except Exception as exc:
        pytest.skip(f"PostgreSQL unreachable at {database_url} - {exc}")
    yield
    command.downgrade(config, "base")


@pytest_asyncio.fixture
async def clean_iam(database_url: str, migrated_iam: None) -> Iterator[None]:
    """Empty the iam tables + bus ledgers before every test."""
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "TRUNCATE TABLE iam.iam_identities, iam.iam_otp_challenges, "
                    "iam.iam_role_grants, iam.iam_sessions, iam.consumed_events, "
                    "iam.iam_outbox CASCADE"
                )
            )
    finally:
        await engine.dispose()
    yield


def _facade(database_url: str, sms: SmsAdapter) -> IamFacade:
    engine = create_async_engine(database_url, poolclass=NullPool)
    return IamFacade(engine=engine, sms_adapter=sms, clock=MutableClock(_T0))


def _registry() -> HandlerRegistry:
    registry = HandlerRegistry()
    register_iam_handlers(registry)
    return registry


def _activated_envelope(identity_id: int) -> Envelope[PartnerActivatedPayload]:
    return Envelope[PartnerActivatedPayload](
        event_id=uuid4(),
        event_type=EVENT_PARTNER_ACTIVATED,
        producer="partner",
        payload=PartnerActivatedPayload(partner_id=3, identity_id=identity_id, decision_by=77),
    )


def _rejected_envelope(identity_id: int) -> Envelope[PartnerRejectedPayload]:
    return Envelope[PartnerRejectedPayload](
        event_id=uuid4(),
        event_type=EVENT_PARTNER_REJECTED,
        producer="partner",
        payload=PartnerRejectedPayload(
            partner_id=3,
            identity_id=identity_id,
            reason="doc unreadable",
            round=1,
            decision_by=77,
        ),
    )


def _invalidated_envelope(identity_id: int) -> Envelope[CredentialInvalidatedPayload]:
    return Envelope[CredentialInvalidatedPayload](
        event_id=uuid4(),
        event_type=EVENT_CREDENTIAL_INVALIDATED,
        producer="partner",
        payload=CredentialInvalidatedPayload(
            partner_id=3, identity_id=identity_id, credential_id=5, reason="grace lapsed"
        ),
    )


async def _role_grants(connection: AsyncConnection) -> list[dict[str, Any]]:
    result = await connection.execute(
        text("SELECT identity_id, role, status FROM iam.iam_role_grants ORDER BY identity_id, role")
    )
    return [dict(mapping) for mapping in result.mappings().all()]


async def _publish_and_process(
    database_url: str, registry: HandlerRegistry, envelope: Envelope[BaseModel]
) -> None:
    """Write an envelope to the iam outbox then run one poll pass over it."""
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await write_outbox(connection, "iam", IAM_OUTBOX_TABLE, envelope)
        async with engine.connect() as connection:
            tables = await discover_outbox_tables(connection, ("iam",))
            assert {table.table_name for table in tables} == {IAM_OUTBOX_TABLE}
        for table in tables:
            await process_outbox_table(engine, table, registry, DEFAULT_DISPATCHER_CONFIG)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_activated_grants_then_rejected_suspends_the_partner_role(
    database_url: str, clean_iam: Any
) -> None:
    """AC: partner.activated -> role granted; partner.rejected -> role suspended,
    both observable through the iam facade (never internals)."""
    facade = _facade(database_url, MockSmsAdapter())
    created = await facade.create_credential_account("9876543210")
    identity_id = created.identity_id
    registry = _registry()

    assert await facade.partner_role_status(identity_id) is None

    await _publish_and_process(database_url, registry, _activated_envelope(identity_id))
    assert await facade.partner_role_status(identity_id) == "Active"

    await _publish_and_process(database_url, registry, _rejected_envelope(identity_id))
    assert await facade.partner_role_status(identity_id) == "Suspended"


@pytest.mark.asyncio
async def test_credential_invalidated_suspends_the_partner_role(
    database_url: str, clean_iam: Any
) -> None:
    """AC: the deactivation path credential.invalidated -> role suspended."""
    facade = _facade(database_url, MockSmsAdapter())
    created = await facade.create_credential_account("9876543210")
    identity_id = created.identity_id
    registry = _registry()

    await _publish_and_process(database_url, registry, _activated_envelope(identity_id))
    assert await facade.partner_role_status(identity_id) == "Active"

    await _publish_and_process(database_url, registry, _invalidated_envelope(identity_id))
    assert await facade.partner_role_status(identity_id) == "Suspended"


@pytest.mark.asyncio
async def test_re_activation_restores_a_suspended_partner_role(
    database_url: str, clean_iam: Any
) -> None:
    """A previously-rejected (Suspended) partner who is re-approved through a
    life-cycle change is granted back the Active partner role."""
    facade = _facade(database_url, MockSmsAdapter())
    created = await facade.create_credential_account("9876543210")
    identity_id = created.identity_id
    registry = _registry()

    await _publish_and_process(database_url, registry, _activated_envelope(identity_id))
    assert await facade.partner_role_status(identity_id) == "Active"

    await _publish_and_process(database_url, registry, _rejected_envelope(identity_id))
    assert await facade.partner_role_status(identity_id) == "Suspended"

    await _publish_and_process(database_url, registry, _activated_envelope(identity_id))
    assert await facade.partner_role_status(identity_id) == "Active"

    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            grants = await _role_grants(connection)
    finally:
        await engine.dispose()
    assert len(grants) == 1
    assert grants[0] == {"identity_id": identity_id, "role": "partner", "status": "Active"}


@pytest.mark.asyncio
async def test_role_grant_is_idempotent_on_replay(database_url: str, clean_iam: Any) -> None:
    """AC: replaying the same event_id through the idempotent consumer leaves
    exactly one Active partner grant."""
    facade = _facade(database_url, MockSmsAdapter())
    created = await facade.create_credential_account("9876543210")
    identity_id = created.identity_id
    registry = _registry()
    envelope = _activated_envelope(identity_id)

    await _publish_and_process(database_url, registry, envelope)
    await dispatch(registry, envelope)

    assert await facade.partner_role_status(identity_id) == "Active"

    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            grants = await _role_grants(connection)
    finally:
        await engine.dispose()
    assert len(grants) == 1
    assert grants[0] == {"identity_id": identity_id, "role": "partner", "status": "Active"}
