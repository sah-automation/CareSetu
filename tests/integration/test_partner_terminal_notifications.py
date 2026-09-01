"""PHASE-5 T12: notify partner terminal-status round trip against real PostgreSQL (#255).

The phase-spec event chain: ``partner.activated`` / ``partner.rejected``
envelopes are published into the notify outbox, a single poll pass over the
FULL production registry (``worker.main.build_registry``, the composition root)
fans them out to the iam role consumer AND the notify terminal-status consumer,
and notify persists a WhatsApp-first row in ``notify.notify_notifications`` -
the fixed activated body for ``partner.activated`` and the reason-carrying
refusal body for ``partner.rejected`` (ADR-0009). The recipient phone is
resolved through the notify -> iam contact seam (``IamFacade.identity_phone``),
so the identity is seeded exactly as production partner registration does
(``create_credential_account``, ADR-0010).

Replaying the same ``event_id`` through the idempotent consumer leaves exactly
one notification row (ADR-0002 §3); a non-terminal ``partner.verification_started``
has no payload model or consumer (in-app only) and mints no notification.

Requires the native PostgreSQL; the suite skips cleanly when it is unreachable,
migrates ``notify`` to head and downgrades afterwards.
"""

from __future__ import annotations

from collections.abc import Iterator
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

from bus.dispatcher import DEFAULT_DISPATCHER_CONFIG, discover_outbox_tables, process_outbox_table
from bus.envelope import Envelope
from bus.events import (
    EVENT_PARTNER_ACTIVATED,
    EVENT_PARTNER_REJECTED,
    EVENT_PARTNER_VERIFICATION_STARTED,
)
from bus.outbox_writer import write_outbox
from modules.iam.adapters.sms import MockSmsAdapter
from modules.iam.domain.consumer import (
    PartnerActivatedPayload,
    PartnerRejectedPayload,
)
from modules.iam.facade import IamFacade
from modules.notify.domain.consumer import (
    PARTNER_ACTIVATED_MESSAGE,
    build_partner_rejected_message,
)
from modules.notify.outbox import NOTIFY_OUTBOX_TABLE
from worker.main import build_registry

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "apps" / "backend" / "alembic.ini"

_PHONE = "+919876543210"


def _alembic_config(database_url: str) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


@pytest.fixture(scope="module")
def migrated_notify(database_url: str) -> Iterator[None]:
    """Migrate to head, restore base after (covers notify + iam + bus tables)."""
    config = _alembic_config(database_url)
    try:
        command.upgrade(config, "head")
    except Exception as exc:
        pytest.skip(f"PostgreSQL unreachable at {database_url} - {exc}")
    yield
    command.downgrade(config, "base")


@pytest_asyncio.fixture
async def clean_tables(database_url: str, migrated_notify: None) -> Iterator[None]:
    """Empty the notify + iam + bus tables before every test."""
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "TRUNCATE TABLE notify.notify_notifications, notify.consumed_events, "
                    "notify.notify_outbox, iam.iam_identities, iam.iam_role_grants, "
                    "iam.consumed_events, iam.iam_outbox CASCADE"
                )
            )
    finally:
        await engine.dispose()
    yield


def _iam_facade(database_url: str) -> IamFacade:
    engine = create_async_engine(database_url, poolclass=NullPool)
    return IamFacade(engine=engine, sms_adapter=MockSmsAdapter())


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


async def _write_rows_to_notify_outbox(
    database_url: str, envelopes: list[Envelope[BaseModel]]
) -> None:
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            for envelope in envelopes:
                await write_outbox(connection, "notify", NOTIFY_OUTBOX_TABLE, envelope)
    finally:
        await engine.dispose()


async def _publish_and_process(database_url: str, envelopes: list[Envelope[BaseModel]]) -> None:
    """Seed the notify outbox then run one poll pass over it with the composition root."""
    await _write_rows_to_notify_outbox(database_url, envelopes)
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            tables = await discover_outbox_tables(connection, ("notify",))
            assert {table.table_name for table in tables} == {NOTIFY_OUTBOX_TABLE}
        registry = build_registry()
        for table in tables:
            await process_outbox_table(engine, table, registry, DEFAULT_DISPATCHER_CONFIG)
    finally:
        await engine.dispose()


async def _notification_rows(connection: AsyncConnection) -> list[dict[str, Any]]:
    result = await connection.execute(
        text(
            "SELECT recipient_phone_e164, message, channel, status "
            "FROM notify.notify_notifications ORDER BY id"
        )
    )
    return [dict(mapping) for mapping in result.mappings().all()]


async def _consumed_events(connection: AsyncConnection) -> list[dict[str, Any]]:
    result = await connection.execute(
        text(
            "SELECT event_type, handler_result->>'handler' AS handler "
            "FROM notify.consumed_events ORDER BY event_id"
        )
    )
    return [dict(mapping) for mapping in result.mappings().all()]


@pytest.mark.asyncio
async def test_partner_activated_mints_a_whatsapp_first_notification(
    database_url: str, clean_tables: Any
) -> None:
    """AC: partner.activated -> a WhatsApp-first notification row, and the iam
    consumer in the same fan-out still grants the partner role."""
    facade = _iam_facade(database_url)
    created = await facade.create_credential_account("9876543210")
    identity_id = created.identity_id
    assert await facade.identity_phone(identity_id) == _PHONE

    await _publish_and_process(database_url, [_activated_envelope(identity_id)])

    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            rows = await _notification_rows(connection)
            ledger = await _consumed_events(connection)
    finally:
        await engine.dispose()
    assert rows == [
        {
            "recipient_phone_e164": _PHONE,
            "message": PARTNER_ACTIVATED_MESSAGE,
            "channel": "wa",
            "status": "pending",
        }
    ]
    assert ledger == [
        {"event_type": EVENT_PARTNER_ACTIVATED, "handler": "send_partner_activated_notification"}
    ]
    assert await facade.partner_role_status(identity_id) == "Active"


@pytest.mark.asyncio
async def test_partner_rejected_carries_the_specific_reason(
    database_url: str, clean_tables: Any
) -> None:
    """AC: partner.rejected -> the refusal notification carries the reason."""
    facade = _iam_facade(database_url)
    created = await facade.create_credential_account("9876543210")
    identity_id = created.identity_id

    await _publish_and_process(database_url, [_rejected_envelope(identity_id)])

    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            rows = await _notification_rows(connection)
            ledger = await _consumed_events(connection)
    finally:
        await engine.dispose()
    expected_message = build_partner_rejected_message("doc unreadable")
    assert "doc unreadable" in expected_message
    assert rows == [
        {
            "recipient_phone_e164": _PHONE,
            "message": expected_message,
            "channel": "wa",
            "status": "pending",
        }
    ]
    assert ledger == [
        {"event_type": EVENT_PARTNER_REJECTED, "handler": "send_partner_rejected_notification"}
    ]


@pytest.mark.asyncio
async def test_terminal_notification_is_idempotent_on_replay(
    database_url: str, clean_tables: Any
) -> None:
    """AC: replaying the same event_id mints exactly one notification row."""
    facade = _iam_facade(database_url)
    created = await facade.create_credential_account("9876543210")
    identity_id = created.identity_id
    envelope = _activated_envelope(identity_id)

    await _publish_and_process(database_url, [envelope, envelope])

    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            rows = await _notification_rows(connection)
            ledger = await _consumed_events(connection)
    finally:
        await engine.dispose()
    assert len(rows) == 1
    assert len(ledger) == 1


@pytest.mark.asyncio
async def test_non_terminal_verification_started_mints_no_notification(
    database_url: str, clean_tables: Any
) -> None:
    """AC: Under Verification / re-submission stays in-app - no notification."""
    facade = _iam_facade(database_url)
    created = await facade.create_credential_account("9876543210")
    identity_id = created.identity_id
    envelope = Envelope[BaseModel](
        event_id=uuid4(),
        event_type=EVENT_PARTNER_VERIFICATION_STARTED,  # type: ignore[arg-type]
        producer="partner",
        payload=PartnerActivatedPayload(  # shape only; no registered model for this event
            partner_id=3, identity_id=identity_id, decision_by=77
        ),
    )

    await _publish_and_process(database_url, [envelope])

    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            rows = await _notification_rows(connection)
            ledger = await _consumed_events(connection)
            remaining = (
                await connection.execute(text("SELECT count(*) FROM notify.notify_outbox"))
            ).scalar_one()
    finally:
        await engine.dispose()
    assert rows == []
    assert ledger == []
    # No notify consumer for a non-terminal event: the outbox row is never
    # deleted - it stays in the table for the dispatcher to reclaim next pass.
    assert remaining == 1
