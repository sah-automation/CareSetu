"""PHASE-8 #620: the doctor profile flow on real HTTP against real Postgres (FEAT-005, FEAT-004).

The doctor profile had no integration coverage, so every guarantee the profile
redesign rests on was unproven against a database: that a declared PIN becomes
the one public position, that a profile save cannot list a doctor or invalidate a
credential, that an unplaceable PIN is a field-level refusal that costs the
doctor nothing else, that a multi-valued specialty selection survives the round
trip and still matches a filtered search, and that a practice outside the
peri-urban belt is a warning rather than a wall.

This suite closes that gap the way the flows actually happen. Every test drives
the PUBLIC routes of a real ``create_app`` against the shared native PostgreSQL:
open a partner registration, log the doctor in by phone OTP, submit credentials,
let an attributed operator approve, then read and write the profile over
``/v1/doctor/profile`` and read the patient-facing surfaces over
``/v1/directory``. Nothing hand-builds a partner row, a credential stamp or a
directory entry - operator approval is the only path to ``[Active]`` (ADR-0008),
so the suite drives the operator route rather than seeding around it.

What each acceptance criterion is proven by:

1. An address save resolves the declared PIN against the bundled centroid table,
   writes the derived position onto the profile row, re-derives the directory
   entry from it in the SAME transaction, and a subsequent public search finds
   the doctor at the new position.
2. A profile save leaves the entry's listed flag and every credential's
   ``verified`` / ``expires_at`` / ``revoked_at`` exactly as activation left
   them, and neither a re-approval nor a re-save leaves a second directory row.
   Asserted as SQL against the rows, never through ``search_directory``: search
   filters on the status the write was supposed to preserve, so it would pass
   even if the write had mutated it.
3. An unresolvable PIN comes back as a 422 whose ``details.errors[].path`` is the
   PIN field, leaves every address column and the directory entry untouched, and
   the practice, about and notification cards all still save afterwards.
4. A multi-valued specialty selection round-trips through the profile read-back
   and matches a specialty-filtered public search; a doctor who declares none is
   still found by an unfiltered search.
5. A PIN whose centroid sits outside the peri-urban belt still saves - with the
   write's own belt warning attached - and the doctor appears in the wider-area
   fallback (``fell_back``), not nowhere.
6. The PIN centroid table the address write resolves against exists after
   ``upgrade head`` and its migration round-trips back down.

Requires the native PostgreSQL; skips cleanly when unreachable.
"""

from __future__ import annotations

import asyncio
import base64
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from itertools import count
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from alembic.script import Script, ScriptDirectory
from conftest import seed_daltonganj_service_area
from fastapi.testclient import TestClient
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import Settings
from app.main import create_app
from modules.iam.domain.jwt import issue_token
from modules.partner.domain.practice_position import PracticePosition, great_circle_km
from modules.partner.facade import (
    DALTONGANJ_LATITUDE,
    DALTONGANJ_LONGITUDE,
    PERI_URBAN_RADIUS_KM,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "apps" / "backend" / "alembic.ini"

_OPERATOR_ID = 77
_KEY = "integration-test-signing-key"
_DOC_BYTES = b"medical registration certificate image"
_DOC_B64 = base64.b64encode(_DOC_BYTES).decode("ascii")

#: Unique phones drive the real registration seam - the partner session mint
#: resolves a phone to exactly one profile, so each doctor needs its own.
_phone_numbers = count(9200000000)

#: Where a doctor is put when they register. Inside the peri-urban belt (so a
#: search for them does not fall back before they have touched anything) but
#: deliberately NOT the position the address save will derive, so "the listing
#: moved" is a difference rather than a coincidence.
_REGISTRATION_LATITUDE = 24.10
_REGISTRATION_LONGITUDE = 84.07

#: A real PIN whose centroid sits ~1.3 km from the belt centre - inside it, on
#: the Palamu side of the Daltonganj meridian. Its centroid is the position the
#: address write must derive, so these numbers are the expected RESULT rather than
#: an input: the seed file is the migration's own dataset (PHASE-8 #601).
_IN_BELT_PIN = "822101"
_IN_BELT_CENTROID = (24.040917, 84.057250)

#: A real PIN ~95 km north on the same meridian (Rohtas district) - nearly four
#: belt radii out. The belt is a WARNING, not a refusal, so this doctor saves and
#: is found only through the wider-area fallback.
_OUT_OF_BELT_PIN = "821113"
_OUT_OF_BELT_CENTROID = (24.886505, 83.920166)

#: Well-formed (six digits) but never listed by the source dataset, so the write
#: answers "this PIN code is not one we can place yet" rather than "malformed".
_UNRESOLVABLE_PIN = "000000"

#: What a doctor registers under before they have filled the Practice card in. A
#: test that then asserts a practice-card value is only proving this flow wrote it
#: if the value differs from this.
_UNSET_NAME = "Name pending"

#: The distance assertion tolerance. The search computes its distance in SQL and
#: the belt decision in Python from the same great-circle formula, so the two
#: agree to well under a tenth of a kilometre; anything looser would hide a real
#: disagreement about which point was derived.
_DISTANCE_TOLERANCE_KM = 0.05


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
async def clean_partner(database_url: str, migration: None) -> AsyncIterator[None]:
    """Empty the iam + partner tables before every test, re-seed Daltonganj.

    ``partner.partner_pin_centroids`` is deliberately NOT truncated: it is the
    bundled reference dataset the address write resolves against, seeded by the
    v8.16 migration, exactly like the service-area vocabulary row re-seeded here.
    Truncating it would empty India, and every address save in the suite would
    then be refused for a reason no acceptance criterion is about.
    """
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


async def _query(
    database_url: str,
    sql: str,
    params: dict[str, Any] | None = None,
    expanding: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            statement = text(sql).bindparams(
                *(bindparam(name, expanding=True) for name in expanding)
            )
            result = await connection.execute(statement, params or {})
            return [dict(row) for row in result.mappings().all()]
    finally:
        await engine.dispose()


async def _entry_counts(database_url: str, partner_id: int) -> dict[str, int]:
    """How many directory rows exist for this partner - and in the whole table.

    ``entries`` and ``listed`` are the criterion's own counts. ``table_entries``
    is the guard that makes them falsifiable: the index is keyed on ``partner_id``,
    so a second row written under any other key would slip past a per-partner
    count, and in this test the activated doctor owns the only rows in the table.
    """
    rows = await _query(
        database_url,
        "SELECT count(*) FILTER (WHERE partner_id = :partner_id) AS entries, "
        "count(*) FILTER (WHERE partner_id = :partner_id AND is_active) AS listed, "
        "count(*) AS table_entries FROM partner.partner_directory_index",
        {"partner_id": partner_id},
    )
    return dict(rows[0])


def _app_client(database_url: str) -> TestClient:
    """A real app against the shared PostgreSQL with the OTP read-back enabled.

    ``app_environment="test"`` turns on the mock-Otp read-back surface so the
    flow can fetch each live challenge code through ``GET /v1/auth/dev/otp`` -
    the browser-equivalent seam under test - and keeps the artifact store's key
    ephemeral. JWT verify stays ON, so the doctor console routes are exercised
    through the gateway rather than around it.
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


def _operator_headers() -> dict[str, str]:
    """An operator-scoped access JWT minted exactly like the real operator login."""
    token = issue_token(
        jti=uuid.uuid4().hex,
        subject_id=_OPERATOR_ID,
        scope="operator",
        signing_key=_KEY,
        now=datetime.now(UTC),
    )
    return {"Authorization": f"Bearer {token}"}


def _partner_headers(client: TestClient, phone: str) -> dict[str, str]:
    """Log the partner in by phone OTP and mint the partner-scoped session.

    The full three-step loop (challenge, verify, session) rather than a
    hand-minted token: the session mint gates on a phone-verified identity, so a
    doctor who skipped the verify could not log in at all. This suite asserts the
    surfaces a real activated doctor reaches, not a shortcut to them.
    """
    challenge = client.post("/v1/auth/partner/login", json={"phone": phone})
    assert challenge.status_code == 200, challenge.text
    assert challenge.json()["outcome"] == "sent"

    otp = client.get("/v1/auth/dev/otp", params={"phone": f"+91{phone}"})
    assert otp.status_code == 200, otp.text

    verified = client.post(
        "/v1/auth/partner/verify",
        json={"phone": phone, "otp": otp.json()["code"]},
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["outcome"] == "verified"

    session = client.post("/v1/auth/partner/session", json={"phone": phone})
    assert session.status_code == 200, session.text
    assert session.json()["scope"] == "partner"
    return {"Authorization": f"Bearer {session.json()['jwt']}"}


def _activate_doctor(
    client: TestClient,
    phone: str,
    *,
    practice_name: str,
    latitude: float = _REGISTRATION_LATITUDE,
    longitude: float = _REGISTRATION_LONGITUDE,
) -> tuple[int, dict[str, str]]:
    """Drive the real activation seam: register, submit, operator approve.

    Returns the partner profile id and the partner-scoped bearer headers. The
    operator decision route is the ONLY path to ``[Active]`` and therefore to a
    directory entry (ADR-0008, ADR-0002: the entry and the credential stamps land
    in the decision's own transaction), so a suite that wants a listed doctor has
    to go through it exactly as a real one does.
    """
    registered = client.post(
        "/v1/partner/register",
        json={
            "phone": phone,
            "partner_type": "doctor",
            "practice_name": practice_name,
            "practice_address": "Station Road, Daltonganj",
            "practice_latitude": latitude,
            "practice_longitude": longitude,
        },
    )
    assert registered.status_code == 200, registered.text
    assert registered.json()["status"] == "Registered"
    partner_id = int(registered.json()["partner_id"])

    headers = _partner_headers(client, phone)

    submitted = client.post(
        "/v1/partner/credentials",
        headers=headers,
        json={
            "credentials": [{"credential_type": "medical_registration", "artifacts": [_DOC_B64]}]
        },
    )
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["status"] == "Under Verification"

    approved = client.post(
        f"/v1/partner/verification/{partner_id}/decision",
        headers=_operator_headers(),
        json={"approve": True},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "Active"
    return partner_id, headers


def _save_address(
    client: TestClient,
    headers: dict[str, str],
    *,
    pin_code: str,
    locality: str = "Belwatikar",
) -> dict[str, Any]:
    """PUT the Address card and return the decoded response (asserting 200)."""
    response = client.put(
        "/v1/doctor/profile/address",
        headers=headers,
        json={
            "address_line": "Main Road, near the bus stand",
            "landmark": "Opposite the pharmacy",
            "locality": locality,
            "city": "Medininagar",
            "pin_code": pin_code,
        },
    )
    assert response.status_code == 200, response.text
    decoded: dict[str, Any] = response.json()
    return decoded


def _save_practice(
    client: TestClient,
    headers: dict[str, str],
    *,
    full_name: str,
    clinic_name: str,
    specialties: list[str],
    experience_years: int,
) -> dict[str, Any]:
    """PUT the Practice card and return the decoded response (asserting 200)."""
    response = client.put(
        "/v1/doctor/profile/practice",
        headers=headers,
        json={
            "full_name": full_name,
            "clinic_name": clinic_name,
            "specialties": specialties,
            "experience_years": experience_years,
        },
    )
    assert response.status_code == 200, response.text
    decoded: dict[str, Any] = response.json()
    return decoded


def _save_about(
    client: TestClient,
    headers: dict[str, str],
    *,
    about: str,
    languages: list[str],
    consulting_days: list[str],
    consulting_hours: str,
) -> dict[str, Any]:
    """PUT the About card and return the decoded response (asserting 200)."""
    response = client.put(
        "/v1/doctor/profile/about",
        headers=headers,
        json={
            "about": about,
            "languages": languages,
            "consulting_days": consulting_days,
            "consulting_hours": consulting_hours,
        },
    )
    assert response.status_code == 200, response.text
    decoded: dict[str, Any] = response.json()
    return decoded


def _save_notifications(
    client: TestClient, headers: dict[str, str], preferences: dict[str, bool]
) -> dict[str, Any]:
    """PUT the Notification card and return the decoded response (asserting 200)."""
    response = client.put(
        "/v1/doctor/profile/notifications",
        headers=headers,
        json={"notification_preferences": preferences},
    )
    assert response.status_code == 200, response.text
    decoded: dict[str, Any] = response.json()
    return decoded


def _read_profile(client: TestClient, headers: dict[str, str]) -> dict[str, Any]:
    """GET the doctor's own profile through the console route (asserting 200)."""
    response = client.get("/v1/doctor/profile", headers=headers)
    assert response.status_code == 200, response.text
    decoded: dict[str, Any] = response.json()
    return decoded


def _search(client: TestClient, **params: str) -> dict[str, Any]:
    """GET the public directory search and return the decoded view."""
    response = client.get("/v1/directory/search", params=params)
    assert response.status_code == 200, response.text
    decoded: dict[str, Any] = response.json()
    return decoded


def _distance_km(centroid: tuple[float, float]) -> float:
    """The great-circle distance from the belt centre to a centroid, in km.

    The domain's own function, not a hand-computed constant: it is the same
    formula the belt decision uses, so the assertion compares the search's
    distance against the one the write reasoned with.
    """
    return great_circle_km(
        PracticePosition(latitude=DALTONGANJ_LATITUDE, longitude=DALTONGANJ_LONGITUDE),
        PracticePosition(latitude=centroid[0], longitude=centroid[1]),
    )


def _revision_named(database_url: str, marker: str) -> Script:
    """Find the migration whose own filename carries ``marker``.

    Derived from the script directory rather than pinned as a literal revision
    id, so a migration landing on top of head cannot silently turn the round trip
    below into a no-op or into an unrelated revision.
    """
    script = ScriptDirectory.from_config(_alembic_config(database_url))
    for revision in script.walk_revisions():
        if marker in Path(revision.path or "").name:
            return revision
    raise AssertionError(f"no migration in the script directory is named {marker}")


async def _pin_centroid_rows(database_url: str) -> dict[str, dict[str, Any]]:
    """The centroid rows for the PIN codes this flow resolves, keyed by PIN."""
    rows = await _query(
        database_url,
        "SELECT pin, latitude, longitude, district FROM partner.partner_pin_centroids "
        "WHERE pin IN :pins ORDER BY pin",
        {"pins": [_IN_BELT_PIN, _OUT_OF_BELT_PIN]},
        expanding=("pins",),
    )
    return {str(row["pin"]): row for row in rows}


@pytest.mark.asyncio
async def test_address_save_resolves_the_pin_and_re_derives_the_directory_entry(
    database_url: str, clean_partner: None
) -> None:
    """AC-1 (FEAT-004, FEAT-005): a declared PIN becomes the one public position a patient finds.

    The whole correction story in one flow: a doctor registered at whatever their
    sign-up form captured saves their real address, the backend resolves the PIN
    against the bundled centroid table, and the directory entry moves with it in
    the same transaction - so the very next public search, before any cache could
    expire, finds them where they actually practise.
    """
    client = _app_client(database_url)
    partner_id, headers = _activate_doctor(
        client, str(next(_phone_numbers)), practice_name="Dr Rao"
    )

    before = _search(client)
    assert before["fell_back"] is False
    assert [item["partner_id"] for item in before["items"]] == [partner_id]
    assert before["items"][0]["distance_km"] == pytest.approx(
        _distance_km((_REGISTRATION_LATITUDE, _REGISTRATION_LONGITUDE)),
        abs=_DISTANCE_TOLERANCE_KM,
    )

    saved = _save_address(client, headers, pin_code=_IN_BELT_PIN)

    # The write's own answer: the position came from the PIN, not from the client.
    assert saved["pin_code"] == _IN_BELT_PIN
    assert saved["address_line"] == "Main Road, near the bus stand"
    assert saved["locality"] == "Belwatikar"
    assert saved["outside_peri_urban_belt"] is False
    assert saved["practice_latitude"] == pytest.approx(_IN_BELT_CENTROID[0], abs=1e-6)
    assert saved["practice_longitude"] == pytest.approx(_IN_BELT_CENTROID[1], abs=1e-6)
    assert _IN_BELT_PIN in saved["practice_address"], (
        "the assembled display string is what every existing reader of the column "
        "sees, so it must carry the declared PIN"
    )

    # The row itself carries the derived position, not just the response body.
    profile_row = await _query(
        database_url,
        "SELECT address_pin, practice_latitude, practice_longitude "
        "FROM partner.partner_profiles WHERE id = :partner_id",
        {"partner_id": partner_id},
    )
    assert profile_row[0]["address_pin"] == _IN_BELT_PIN
    assert float(profile_row[0]["practice_latitude"]) == pytest.approx(
        _IN_BELT_CENTROID[0], abs=1e-6
    )
    assert float(profile_row[0]["practice_longitude"]) == pytest.approx(
        _IN_BELT_CENTROID[1], abs=1e-6
    )

    # And the directory entry was re-derived from it, not left at sign-up.
    entry_row = await _query(
        database_url,
        "SELECT practice_latitude, practice_longitude FROM partner.partner_directory_index "
        "WHERE partner_id = :partner_id",
        {"partner_id": partner_id},
    )
    assert len(entry_row) == 1
    assert float(entry_row[0]["practice_latitude"]) == pytest.approx(_IN_BELT_CENTROID[0], abs=1e-6)
    assert float(entry_row[0]["practice_longitude"]) == pytest.approx(
        _IN_BELT_CENTROID[1], abs=1e-6
    )

    after = _search(client)
    assert after["fell_back"] is False
    assert [item["partner_id"] for item in after["items"]] == [partner_id]
    assert after["items"][0]["distance_km"] == pytest.approx(
        _distance_km(_IN_BELT_CENTROID), abs=_DISTANCE_TOLERANCE_KM
    )
    assert after["items"][0]["distance_km"] != pytest.approx(
        before["items"][0]["distance_km"], abs=_DISTANCE_TOLERANCE_KM
    ), "the listing must have actually moved, not merely been recomputed in place"

    # The declared locality is what a patient reads as the area (#612), so the
    # moved listing carries it rather than the registration-era vocabulary.
    assert after["items"][0]["area"] == "Belwatikar"


@pytest.mark.asyncio
async def test_a_profile_save_preserves_listing_and_credentials_and_re_approval_is_idempotent(
    database_url: str, clean_partner: None
) -> None:
    """AC-2 (FEAT-005): nothing a doctor declares can list them or un-verify them.

    Profile fields are DECLARED; credentials are VERIFIED and activation is the
    operator's (ADR-0011, ADR-0008). So all four section writes must leave the
    entry's listed flag and every credential stamp exactly as approval wrote them,
    and re-approving must converge on the one entry rather than fork into two.

    Read straight off the rows, and counted rather than fetched: search filters
    on exactly the state this criterion says is preserved, so asserting through
    it would pass even if the write had moved the flag.
    """
    client = _app_client(database_url)
    partner_id, headers = _activate_doctor(
        client, str(next(_phone_numbers)), practice_name="Dr Sen"
    )

    credentials_sql = (
        "SELECT credential_type, round, verified, expires_at, revoked_at "
        "FROM partner.partner_credentials WHERE profile_id = :partner_id ORDER BY id"
    )
    before_flags = await _query(
        database_url,
        "SELECT is_active FROM partner.partner_directory_index WHERE partner_id = :partner_id",
        {"partner_id": partner_id},
    )
    before_credentials = await _query(database_url, credentials_sql, {"partner_id": partner_id})
    assert before_flags == [{"is_active": True}]
    assert before_credentials, "the approval must have stamped at least one credential"

    _save_practice(
        client,
        headers,
        full_name="Dr Sen",
        clinic_name="Sadar Clinic",
        specialties=["General Physician", "Pediatrician"],
        experience_years=12,
    )
    _save_about(
        client,
        headers,
        about="Twenty years on the Daltonganj fever ward.",
        languages=["Hindi", "Maithili"],
        consulting_days=["Monday", "Tuesday", "Wednesday"],
        consulting_hours="Mon-Sat mornings",
    )
    _save_notifications(client, headers, {"new_consultations": True, "case_updates": False})
    _save_address(client, headers, pin_code=_IN_BELT_PIN)

    after_saves = await _entry_counts(database_url, partner_id)
    assert after_saves == {"entries": 1, "listed": 1, "table_entries": 1}, (
        "a profile save re-derives the entry in place (ADR-0012: one partner is "
        "one entry) and can never move the listed flag, which only activation owns"
    )
    after_credentials = await _query(database_url, credentials_sql, {"partner_id": partner_id})
    assert after_credentials == before_credentials, (
        "a profile save must not touch a credential's verified stamp, expiry or "
        "revocation - those are the operator's to set"
    )

    # Re-approval through the operator route again: the same state-machine step on
    # an already-Active partner, and the entry must converge rather than fork.
    reapproved = client.post(
        f"/v1/partner/verification/{partner_id}/decision",
        headers=_operator_headers(),
        json={"approve": True},
    )
    assert reapproved.status_code == 200, reapproved.text
    assert reapproved.json()["status"] == "Active"

    after_reapproval = await _entry_counts(database_url, partner_id)
    assert after_reapproval == {"entries": 1, "listed": 1, "table_entries": 1}, (
        "re-approving an already-Active partner opens no new round and must leave "
        "exactly one listed entry behind"
    )
    restamped = await _query(database_url, credentials_sql, {"partner_id": partner_id})
    assert restamped == before_credentials, (
        "with no new round there is nothing to restamp, so the approved round's "
        "credential history must be untouched"
    )

    # The doctor is still listed and still verified, read through the surfaces a
    # patient and a doctor actually see.
    profile = _read_profile(client, headers)
    assert profile["verified"] is True
    assert profile["credentials"][0]["status"] == "verified"
    listed = _search(client)
    assert [item["partner_id"] for item in listed["items"]] == [partner_id]


@pytest.mark.asyncio
async def test_an_unresolvable_pin_is_refused_on_the_pin_field_and_other_cards_still_save(
    database_url: str, clean_partner: None
) -> None:
    """AC-3 (FEAT-004, FEAT-005): a PIN the platform cannot place is one field's problem.

    The refusal arrives as a 422 keyed to ``pin_code`` so the address card renders
    it under that input (api-standards §2/§3), the write leaves every address
    column and the directory entry exactly as they were - the PIN is resolved
    BEFORE the UPDATE, so a refused save is not a partial one - and the doctor's
    other three cards still save, because a section write touches only its own
    columns.

    The doctor registers under a placeholder name, so every practice-card value
    asserted below is a value THIS flow wrote - a practice write that silently
    dropped a column could not pass by echoing the registration.
    """
    client = _app_client(database_url)
    partner_id, headers = _activate_doctor(
        client, str(next(_phone_numbers)), practice_name=_UNSET_NAME
    )

    columns = (
        "address_line, address_landmark, address_locality, address_city, address_pin, "
        "practice_address, practice_latitude, practice_longitude"
    )
    before_profile = await _query(
        database_url,
        f"SELECT {columns} FROM partner.partner_profiles WHERE id = :partner_id",
        {"partner_id": partner_id},
    )
    before_entry = await _query(
        database_url,
        "SELECT practice_latitude, practice_longitude FROM partner.partner_directory_index "
        "WHERE partner_id = :partner_id",
        {"partner_id": partner_id},
    )

    refused = client.put(
        "/v1/doctor/profile/address",
        headers=headers,
        json={
            "address_line": "Main Road, near the bus stand",
            "landmark": "Opposite the pharmacy",
            "locality": "Belwatikar",
            "city": "Medininagar",
            "pin_code": _UNRESOLVABLE_PIN,
        },
    )
    assert refused.status_code == 422, refused.text
    envelope = refused.json()
    assert envelope["code"] == "DOCTOR_PROFILE_ADDRESS_PIN_UNRESOLVED"
    assert envelope["details"]["errors"][0]["path"] == "pin_code"
    assert envelope["details"]["errors"][0]["reason"], "the doctor is told why it was refused"
    assert _UNRESOLVABLE_PIN not in str(envelope["details"]["errors"][0]["reason"]), (
        "the reason is written for the doctor, so it explains rather than quotes"
    )

    after_profile = await _query(
        database_url,
        f"SELECT {columns} FROM partner.partner_profiles WHERE id = :partner_id",
        {"partner_id": partner_id},
    )
    assert after_profile == before_profile, (
        "an unresolvable PIN must not write a partial address or move the position"
    )
    after_entry = await _query(
        database_url,
        "SELECT practice_latitude, practice_longitude FROM partner.partner_directory_index "
        "WHERE partner_id = :partner_id",
        {"partner_id": partner_id},
    )
    assert after_entry == before_entry, "the refused write must not re-derive the directory entry"

    # Every other card still saves, on the same session, right after the refusal.
    _save_practice(
        client,
        headers,
        full_name="Dr Das",
        clinic_name="Bazaar Clinic",
        specialties=["Gynecologist"],
        experience_years=7,
    )
    _save_about(
        client,
        headers,
        about="Deliveries on alternate Tuesdays.",
        languages=["Hindi"],
        consulting_days=["Tuesday"],
        consulting_hours="Tuesdays and Fridays, 10 to 2",
    )
    _save_notifications(client, headers, {"record_shared": True})

    body = _read_profile(client, headers)
    assert body["practice_name"] == "Dr Das"
    assert body["clinic_name"] == "Bazaar Clinic"
    assert body["specialties"] == ["Gynecologist"]
    assert body["about"] == "Deliveries on alternate Tuesdays."
    assert body["languages"] == ["Hindi"]
    assert body["consulting_days"] == ["Tuesday"]
    assert body["notification_preferences"] == {"record_shared": True}
    assert body["pin_code"] is None, "the refused address card left its own fields alone"


@pytest.mark.asyncio
async def test_multi_valued_specialties_round_trip_and_match_a_specialty_filtered_search(
    database_url: str, clean_partner: None
) -> None:
    """AC-4 (FEAT-004, FEAT-005): a specialty set round-trips and is found by any member.

    A doctor's selection is a SET, not a single value: it round-trips through the
    private profile read-back, and a patient filtering on ANY one member finds
    the doctor. The directory entry receives that selection through the shared
    refresh (#607), and the practice card is one of that refresh's two callers -
    so the assertion below is made straight after the PRACTICE save, with no
    address save in between. A doctor who finishes their profile card first, or
    who never touches the address card at all, must still be findable by their
    declared specialty; making the address save a prerequisite here would hide
    the opposite bug.

    The second half is the other half of the same rule: a doctor who has declared
    no specialty yet is not invisible. The membership predicate fails only the
    specialty FILTER, so an unfiltered search still returns them.
    """
    client = _app_client(database_url)
    multi_id, multi_headers = _activate_doctor(
        client, str(next(_phone_numbers)), practice_name="Dr Iyer"
    )
    plain_id, _ = _activate_doctor(client, str(next(_phone_numbers)), practice_name="Dr Gill")

    selection = ["General Physician", "Pediatrician", "Dermatologist"]
    saved = _save_practice(
        client,
        multi_headers,
        full_name="Dr Iyer",
        clinic_name="Pahar Clinic",
        specialties=selection,
        experience_years=19,
    )
    assert saved["specialties"] == selection, (
        "the write answers with the profile the doctor's next GET would serve"
    )
    assert _read_profile(client, multi_headers)["specialties"] == selection

    # The practice save alone publishes the declared selection onto the entry the
    # specialty filter reads - asserted BEFORE any address save, because that is
    # the ordering a doctor completing the Practice card first actually makes.
    entry_specialties = await _query(
        database_url,
        "SELECT specialty FROM partner.partner_directory_index WHERE partner_id = :partner_id",
        {"partner_id": multi_id},
    )
    assert entry_specialties[0]["specialty"] == selection, (
        "a practice-only save must not leave the directory entry filtering on the "
        "pre-save selection while the public profile already shows the new one"
    )

    for requested in selection:
        filtered = _search(client, specialty=requested)
        assert filtered["fell_back"] is False, (
            "the doctor is inside the belt, so a specialty-filtered search has to "
            "match in scope: a fell_back view would match them with the specialty "
            "predicate switched off, which proves nothing about the predicate"
        )
        assert [item["partner_id"] for item in filtered["items"]] == [multi_id], (
            f"a search filtering on {requested} must find a doctor who declared it"
        )

    assert _search(client, specialty="Cardiologist")["items"] == [], (
        "a specialty nobody declared matches nobody"
    )

    # The address save re-derives the same entry for the POSITION, and must leave
    # the selection the practice save published exactly as it was.
    _save_address(client, multi_headers, pin_code=_IN_BELT_PIN)
    after_address = await _query(
        database_url,
        "SELECT specialty FROM partner.partner_directory_index WHERE partner_id = :partner_id",
        {"partner_id": multi_id},
    )
    assert after_address[0]["specialty"] == selection

    # The doctor who declared none is still in the directory, unfiltered.
    unfiltered = _search(client)
    assert unfiltered["fell_back"] is False
    assert {item["partner_id"] for item in unfiltered["items"]} == {multi_id, plain_id}


@pytest.mark.asyncio
async def test_a_pin_outside_the_peri_urban_belt_still_saves_and_appears_as_outside_your_area(
    database_url: str, clean_partner: None
) -> None:
    """AC-5 (FEAT-004): the peri-urban belt is a warning the doctor is told, never a wall.

    A doctor whose real practice is ~95 km out must be able to correct their
    address - that is exactly the doctor the derived position exists for. So the
    save succeeds, carries the belt warning the write alone evaluates, and the
    doctor reaches patients through the wider-area fallback, which relaxes only
    the location constraint and labels the results honestly (glossary).
    """
    assert _distance_km(_OUT_OF_BELT_CENTROID) > PERI_URBAN_RADIUS_KM, (
        "this case is only meaningful if the chosen PIN really is outside the belt"
    )

    client = _app_client(database_url)
    partner_id, headers = _activate_doctor(
        client, str(next(_phone_numbers)), practice_name="Dr Roy"
    )

    saved = _save_address(client, headers, pin_code=_OUT_OF_BELT_PIN, locality="Alampur")

    assert saved["outside_peri_urban_belt"] is True
    assert saved["distance_from_belt_centre_km"] == pytest.approx(
        _distance_km(_OUT_OF_BELT_CENTROID), abs=_DISTANCE_TOLERANCE_KM
    )
    assert saved["practice_latitude"] == pytest.approx(_OUT_OF_BELT_CENTROID[0], abs=1e-6)
    assert saved["practice_longitude"] == pytest.approx(_OUT_OF_BELT_CENTROID[1], abs=1e-6)

    profile = _read_profile(client, headers)
    assert profile["practice_latitude"] == pytest.approx(_OUT_OF_BELT_CENTROID[0], abs=1e-6)

    # Anchored on the Daltonganj centre, nothing matches in scope - so the one
    # search relaxes only the location constraint and says so.
    fallback = _search(client)
    assert fallback["fell_back"] is True, (
        "with no in-scope match the search must relax ONLY the location "
        "constraint and flag the view, never serve the result as local"
    )
    assert [item["partner_id"] for item in fallback["items"]] == [partner_id]
    assert fallback["items"][0]["distance_km"] == pytest.approx(
        _distance_km(_OUT_OF_BELT_CENTROID), abs=_DISTANCE_TOLERANCE_KM
    )
    assert fallback["items"][0]["area"] == "Alampur"

    public = client.get(f"/v1/directory/providers/{partner_id}")
    assert public.status_code == 200, public.text
    assert public.json()["pin_code"] == _OUT_OF_BELT_PIN
    assert public.json()["locality"] == "Alampur"


def test_the_pin_centroid_table_exists_after_upgrade_and_round_trips_down(
    database_url: str, reachable_db: None, migration: None
) -> None:
    """AC-6 (FEAT-004): the table the address write resolves against is real and reversible.

    The derived position is only as good as the dataset under it, so the flow's
    own two PIN codes must come from the migrated table after ``upgrade head``.
    And because the seed is derived data that nothing else references, the
    migration drops the table on the way down rather than trying to preserve rows
    - so a downgrade to the revision before it must leave the table gone, and a
    second upgrade must bring the same dataset back.

    Synchronous like every other migration round trip in ``tests/integration``:
    Alembic's own runner drives its own event loop, so the queries around it are
    reached with ``asyncio.run`` rather than from inside a live loop.
    """
    revision = _revision_named(database_url, "pin_centroid_table_and_seed")
    parent_revision = revision.down_revision
    assert isinstance(parent_revision, str), (
        "the round trip needs the single revision before the centroid migration"
    )

    present = asyncio.run(_pin_centroid_rows(database_url))
    assert sorted(present) == sorted([_IN_BELT_PIN, _OUT_OF_BELT_PIN]), (
        "both PIN codes the flow resolves must come from the migrated dataset"
    )
    assert present[_IN_BELT_PIN]["latitude"] is not None

    command.downgrade(_alembic_config(database_url), parent_revision)
    dropped = asyncio.run(
        _query(
            database_url,
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'partner' AND table_name = 'partner_pin_centroids') AS exists",
        )
    )
    assert dropped == [{"exists": False}]

    command.upgrade(_alembic_config(database_url), "head")
    assert asyncio.run(_pin_centroid_rows(database_url)) == present, (
        "the upgrade after a downgrade must re-seed the same dataset, so the "
        "second run of this suite starts from where the first left off"
    )
