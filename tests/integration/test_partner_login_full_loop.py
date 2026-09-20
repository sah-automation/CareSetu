"""F014-T10: the full partner login loop on live Postgres, at the HTTP seam (#470).

Drives one doctor's journey through the PUBLIC routes against a real
PostgreSQL: open partner registration -> phone-OTP login -> partner session
mint -> credential submission -> own-status reads -> operator activation
decision -> partner home, all asserted at the HTTP boundary (the backend routes
under #462-#466). The loop also pins the two lifecycle guarantees the plan
engineers decided (ADR-0016):

- AC-2  the ``partner`` role grant exists only after the ``partner.activated``
        event from the operator decision - never at login/verify/session time;
- AC-3  a shared phone's partner login/verify/session mints no patient role
        grant and no ``patient.verified`` outbox event, and the patient session
        for that phone requires the separate patient verify act.

The activation chain is async (partner outbox -> iam consumer), so the loop
drives the real operator decision route (which writes ``partner.activated`` to
the partner outbox) and then fans the emitted envelope to the iam consumer
exactly as the existing role-chain suites do (``test_partner_verification_queue``);
the grant timing is read back from the iam role-grant ledger. Every flow step
goes through the public routes of a real ``create_app`` against the shared
PostgreSQL - no shortcut seeds.

Requires the native PostgreSQL; the suite skips cleanly when unreachable.
"""

from __future__ import annotations

import base64
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from conftest import seed_daltonganj_service_area
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import Settings
from app.main import create_app
from bus.dispatch import dispatch
from bus.registry import HandlerRegistry
from modules.iam.adapters import register_handlers as register_iam_handlers
from modules.iam.domain.jwt import issue_token
from modules.partner.domain.events import partner_activated_envelope

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "apps" / "backend" / "alembic.ini"

_PHONE = "9876543210"
_PHONE_E164 = "+919876543210"
_OPERATOR_ID = 77
_KEY = "integration-test-signing-key"
_DOC_BYTES = b"medical registration certificate image"
_DOC_B64 = base64.b64encode(_DOC_BYTES).decode("ascii")


def _alembic_config(database_url: str) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


@pytest.fixture(scope="module")
def migration(database_url: str) -> Iterator[None]:
    """Migrate all schemas to head for the module, restore base after."""
    config = _alembic_config(database_url)
    try:
        command.upgrade(config, "head")
    except Exception as exc:
        pytest.skip(f"PostgreSQL unreachable at {database_url} - {exc}")
    yield
    command.downgrade(config, "base")


@pytest_asyncio.fixture
async def clean_loop_state(database_url: str, migration: None) -> Iterator[None]:
    """Empty the iam + partner tables before every test, re-seed Daltonganj."""
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "TRUNCATE TABLE partner.partner_verifications, "
                    "partner.partner_credentials, partner.partner_profiles, "
                    "partner.partner_directory_index, partner.partner_outbox, "
                    "partner.partner_service_areas, iam.iam_role_grants, "
                    "iam.iam_sessions, iam.iam_otp_challenges, iam.iam_outbox, "
                    "iam.consumed_events, iam.iam_identities CASCADE"
                )
            )
            await seed_daltonganj_service_area(connection)
    finally:
        await engine.dispose()
    yield


async def _query(database_url: str, sql: str) -> list[dict[str, Any]]:
    engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(text(sql))
            return [dict(row) for row in result.mappings().all()]
    finally:
        await engine.dispose()


async def _advance_resend_cooldown(database_url: str) -> None:
    """Let the >= 60 s resend cooldown elapse for every pending challenge.

    Stands in for real time passing between two OTP flows on one phone (the
    partner login earlier in this test), so the patient register below can
    issue a fresh challenge through the real begin-or-resume path.
    """
    engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE iam.iam_otp_challenges SET cooldown_until = now() - interval '1 minute'"
                )
            )
    finally:
        await engine.dispose()


async def _role_grants(database_url: str) -> list[dict[str, Any]]:
    return await _query(
        database_url,
        "SELECT role, status FROM iam.iam_role_grants ORDER BY role",
    )


async def _outbox_event_types(database_url: str, schema: str) -> list[str]:
    return [
        row["event_type"]
        for row in await _query(
            database_url, f"SELECT event_type FROM {schema}.{schema}_outbox ORDER BY id"
        )
    ]


async def _identity(database_url: str) -> dict[str, Any]:
    rows = await _query(
        database_url,
        "SELECT status, phone_verified, id FROM iam.iam_identities ORDER BY id",
    )
    assert len(rows) == 1
    return rows[0]


def _app_client(database_url: str) -> TestClient:
    """A real app against the shared PostgreSQL with the OTP read-back enabled.

    ``app_environment="test"`` turns on the mock-Otp read-back surface
    (``mock_otp_readback_enabled``) so the loop can fetch the live challenge
    code through ``GET /v1/auth/dev/otp`` - the browser-E2E-equivalent seam
    under test - and keeps the artifact store's key ephemeral.
    """
    app = create_app(
        settings=Settings(
            database_url=database_url,
            gateway_jwt_verify_enabled=True,
            gateway_jwt_signing_key=_KEY,
            app_environment="test",
        )
    )
    return TestClient(app)


def _operator_token() -> str:
    """An operator-scoped access JWT minted exactly like the real operator login."""
    return issue_token(
        jti=uuid.uuid4().hex,
        subject_id=_OPERATOR_ID,
        scope="operator",
        signing_key=_KEY,
        now=datetime.now(UTC),
    )


def _partner_session_token(client: TestClient, phone: str) -> dict[str, Any]:
    """Mint a partner-scoped session through the public route and return its body."""
    response = client.post("/v1/auth/partner/session", json={"phone": phone})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["scope"] == "partner"
    return body


def _bearer(body: dict[str, Any]) -> dict[str, str]:
    return {"Authorization": f"Bearer {body['jwt']}"}


def _otp_code(client: TestClient) -> str:
    """Read the most recently delivered mock OTP back through the public dev route."""
    response = client.get("/v1/auth/dev/otp", params={"phone": _PHONE_E164})
    assert response.status_code == 200, response.text
    return response.json()["code"]


def _partner_login(client: TestClient) -> str:
    """Drive one partner login (no prior challenge) and return the live OTP code."""
    response = client.post("/v1/auth/partner/login", json={"phone": _PHONE})
    assert response.status_code == 200, response.text
    assert response.json()["outcome"] == "sent"
    return _otp_code(client)


def _partner_verify(client: TestClient, otp: str) -> dict[str, Any]:
    """Submit the partner's OTP code and return the verify result body."""
    response = client.post("/v1/auth/partner/verify", json={"phone": _PHONE, "otp": otp})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["outcome"] == "verified"
    return body


async def _operator_approve(client: TestClient, database_url: str, partner_id: int) -> None:
    """Approve through the operator decision route and confirm the activation
    envelope lands in the partner outbox - the async activation event only."""
    response = client.post(
        f"/v1/partner/verification/{partner_id}/decision",
        headers={"Authorization": f"Bearer {_operator_token()}"},
        json={"approve": True},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "Active"
    assert (await _outbox_event_types(database_url, "partner")).count("partner.activated") == 1


async def _fan_out_activation(partner_id: int, identity_id: int) -> None:
    """Fan the ``partner.activated`` event to the iam consumer (the async seam)."""
    registry = HandlerRegistry()
    register_iam_handlers(registry)
    await dispatch(registry, partner_activated_envelope(partner_id, identity_id, _OPERATOR_ID))


def _register_partner(client: TestClient) -> dict[str, Any]:
    """Open a partner registration through the public route and return its body."""
    response = client.post(
        "/v1/partner/register",
        json={
            "phone": _PHONE,
            "partner_type": "doctor",
            "practice_address": "Station Road, Daltonganj",
            "practice_latitude": 24.04,
            "practice_longitude": 84.07,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "Registered"
    return body


def _assert_patient_session_refused(client: TestClient) -> None:
    """The phone cannot mint a patient session before the separate patient act."""
    response = client.post("/v1/auth/session", json={"phone": _PHONE})
    assert response.status_code == 409
    assert response.json()["code"] == "SESSION_REFUSED"


@pytest.mark.asyncio
async def test_full_partner_login_loop_register_to_home_grants_role_only_at_activation(
    database_url: str, clean_loop_state: Any
) -> None:
    """AC-1 + AC-2: the whole vertical flow at the HTTP seam, grant-gated only by
    the operator activation event."""
    client = _app_client(database_url)

    # 1. Open partner registration creates the sync credential account and an
    #    [Unverified] profile with no role grant (ADR-0010).
    registration = _register_partner(client)
    partner_id, identity_id = registration["partner_id"], registration["identity_id"]
    assert await _role_grants(database_url) == []

    # 2. Partner login issues an OTP through the shared machine - still no grant.
    otp = _partner_login(client)
    assert await _role_grants(database_url) == []

    # 3. Partner verify consumes the code and marks the phone verified SILENTLY:
    #    identity still [Unverified], no partner role, no patient role, and no
    #    patient.verified event (AC-3 partner-side half).
    verification = _partner_verify(client, otp)
    assert verification["identity_id"] == identity_id
    identity = await _identity(database_url)
    assert identity["status"] == "Unverified"
    assert identity["phone_verified"] is True
    assert identity["id"] == identity_id
    assert await _role_grants(database_url) == []
    assert "patient.verified" not in await _outbox_event_types(database_url, "iam")

    # 4. Partner session mint (phone-verified gate, #464) - STILL no role grant,
    #    and the patient session for the same phone is refused (it needs the
    #    separate patient act).
    partner_session = _partner_session_token(client, _PHONE)
    assert partner_session["identity_id"] == identity_id
    assert await _role_grants(database_url) == []
    _assert_patient_session_refused(client)

    # 5. Partner self-service is reachable pre-activation (state-based gating
    #    #466 keeps status reads open): the partner reads their own status.
    response = client.get("/v1/partner/me", headers=_bearer(partner_session))
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "Registered"

    # 6. Credential submission passes the Step-1 pre-filter into the operator queue.
    response = client.post(
        "/v1/partner/credentials",
        headers=_bearer(partner_session),
        json={
            "credentials": [{"credential_type": "medical_registration", "artifacts": [_DOC_B64]}]
        },
    )
    assert response.status_code == 200, response.text
    submission = response.json()
    assert submission["status"] == "Under Verification"
    assert submission["round"] == 1

    response = client.get("/v1/partner/me/verification", headers=_bearer(partner_session))
    assert response.status_code == 200, response.text
    assert response.json()["round"] == 1

    # 7. Operator activation decision (approve) -> Active and partner.activated
    #    written to the partner outbox. The iam grant has STILL not happened.
    await _operator_approve(client, database_url, partner_id)
    assert await _role_grants(database_url) == []

    # 8. The activation event reaches the iam consumer - only now the partner
    #    role grant exists (AC-2).
    await _fan_out_activation(partner_id, identity_id)
    grants = await _role_grants(database_url)
    assert grants == [{"role": "partner", "status": "Active"}]

    # 9. The loop reaches the partner home post-activation through the public
    #    session route + self-service route.
    activated_session = _partner_session_token(client, _PHONE)
    response = client.get("/v1/partner/me", headers=_bearer(activated_session))
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "Active"
    assert response.json()["partner_id"] == partner_id


@pytest.mark.asyncio
async def test_shared_phone_partner_login_is_silent_until_the_patient_act(
    database_url: str, clean_loop_state: Any
) -> None:
    """AC-3: partner login on a phone that later becomes a patient stays silent -
    no patient role grant, no ``patient.verified``, and the patient session
    requires the separate patient verify act."""
    client = _app_client(database_url)

    partner_registration = _register_partner(client)
    identity_id = partner_registration["identity_id"]

    # The partner leg completes silently on the shared phone.
    verification = _partner_verify(client, _partner_login(client))
    assert verification["identity_id"] == identity_id
    assert await _role_grants(database_url) == []
    assert "patient.verified" not in await _outbox_event_types(database_url, "iam")

    partner_session = _partner_session_token(client, _PHONE)
    assert partner_session["identity_id"] == identity_id

    # Before the separate patient act, a patient session for the phone is refused.
    _assert_patient_session_refused(client)

    # The separate patient act (time passes, the cooldown elapses): register
    # resolves the existing identity (no new one), verify grants the patient role
    # and emits patient.verified.
    await _advance_resend_cooldown(database_url)
    response = client.post("/v1/auth/register", json={"phone": _PHONE})
    assert response.status_code == 200, response.text
    register = response.json()
    assert register["outcome"] == "sent"
    assert register["is_existing"] is True
    assert register["identity_id"] == identity_id

    response = client.post("/v1/auth/verify", json={"phone": _PHONE, "otp": _otp_code(client)})
    assert response.status_code == 200, response.text
    assert response.json()["outcome"] == "verified"
    assert response.json()["identity_id"] == identity_id

    grants = await _role_grants(database_url)
    assert grants == [{"role": "patient", "status": "Active"}]
    events = await _outbox_event_types(database_url, "iam")
    assert events.count("patient.verified") == 1

    # Now the patient session mints on the same phone.
    response = client.post("/v1/auth/session", json={"phone": _PHONE})
    assert response.status_code == 200, response.text
    assert response.json()["scope"] == "patient"
    assert response.json()["identity_id"] == identity_id
