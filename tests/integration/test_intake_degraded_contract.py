"""Contract pin for the degraded-signature API shape (ticket #391, parent #388).

Pins against a real local PostgreSQL (skipping cleanly when unreachable):
a Ready-for-Review intake with no pre-summary row must answer the not-found
envelope from the pre-summary endpoint while the intake-detail endpoint
reports ``ready_for_review``. That pairing is the exact signature the
degraded frontend branch (tickets #389/#390) branches on.

The intake state is built at the DB/fixture level, never by driving the AI
pipeline: the intake row is captured through the real facade, then its status
is moved to ``ready_for_review`` with a direct SQL update and no pre-summary
row is inserted. The HTTP endpoints run through the real routes and the real
facade (the unit stub is swapped for the DB-backed facade on app state), so
this proves the wire contract end to end. No endpoint behavior changes - the
test pins identical signaling that already exists.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import Settings
from app.main import create_app
from modules.iam.domain.jwt import issue_token
from modules.intake.domain.state_machine import IntakeStatus
from modules.intake.facade import IntakeFacade

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "apps" / "backend" / "alembic.ini"

_SIGNING_KEY = "test-contract-pin-signing-key"

_INTAKE_TABLES = (
    "intake.intake_outbox",
    "intake.intake_ai_jobs",
    "intake.intake_pre_summaries",
    "intake.intake_media_refs",
    "intake.intake_intakes",
    "intake.consumed_events",
)


def _alembic_config(database_url: str) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


@pytest.fixture(scope="module")
def migrated_schema(database_url: str) -> Iterator[None]:
    """Migrate to head (intake + shared deltas) for the module."""
    config = _alembic_config(database_url)
    try:
        command.upgrade(config, "head")
    except Exception as exc:
        pytest.skip(f"PostgreSQL unreachable at {database_url} - {exc}")
    yield
    command.downgrade(config, "base")


@pytest_asyncio.fixture
async def clean_intake_tables(database_url: str, migrated_schema: None) -> None:
    """Empty the intake tables under test, leaving no residue for siblings."""
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text("TRUNCATE TABLE " + ", ".join(_INTAKE_TABLES) + " CASCADE")
            )
    finally:
        await engine.dispose()


def _intake_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(database_url, poolclass=NullPool)


async def _update_status(database_url: str, intake_id: int, status: str) -> None:
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text("UPDATE intake.intake_intakes SET status = :status WHERE id = :intake_id"),
                {"status": status, "intake_id": intake_id},
            )
    finally:
        await engine.dispose()


def _token(*, subject_id: int = 7, scope: str = "patient") -> str:
    return issue_token(
        jti=uuid.uuid4().hex,
        subject_id=subject_id,
        scope=scope,
        signing_key=_SIGNING_KEY,
        now=datetime.now(UTC),
    )


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_ready_for_review_intake_without_pre_summary_pins_degraded_signature(
    database_url: str, clean_intake_tables: None
) -> None:
    """#391: the pre-summary 404 envelope + detail ``ready_for_review`` pairing.

    The intake row is created through the real facade and then moved to
    ``ready_for_review`` at the DB level with no pre-summary row - the exact
    state a degraded intake lands in when the AI pipeline cannot produce a
    pre-summary. The HTTP routes run against the real facade, so the wire
    contract the frontend branches on is pinned end to end.
    """
    patient_id = uuid.uuid4().int % (2**53)
    engine = _intake_engine(database_url)
    try:
        facade = IntakeFacade(engine=engine)

        submitted = await facade.submit_intake(
            patient_id=patient_id,
            mode="text",
            language="hi",
            text="sir dard hai aur bukhar bhi",
        )
        intake_id = submitted.intake_id

        # Move the intake to Ready-for-Review without producing a pre-summary
        # row - the pipeline step that normally creates the row is skipped.
        # coding-standards §4 (state machines) normally demands a transition()
        # call, but the #391 brief sanctions constructing this degraded state at
        # the DB/fixture level so the pin never drives the full AI pipeline.
        await _update_status(database_url, intake_id, IntakeStatus.READY_FOR_REVIEW.value)

        app = create_app(
            settings=Settings(
                database_url=database_url,
                gateway_jwt_verify_enabled=True,
                gateway_jwt_signing_key=_SIGNING_KEY,
            )
        )
        app.state.intake_facade = facade
        client = TestClient(app)
        headers = _bearer(_token(subject_id=patient_id))

        detail_response = client.get(f"/v1/intake/{intake_id}", headers=headers)
        pre_summary_response = client.get(f"/v1/intake/{intake_id}/pre-summary", headers=headers)
    finally:
        await engine.dispose()

    assert detail_response.status_code == 200
    assert detail_response.json()["status"] == IntakeStatus.READY_FOR_REVIEW.value

    assert pre_summary_response.status_code == 404
    assert pre_summary_response.json()["code"] == "INTAKE_NOT_FOUND"
