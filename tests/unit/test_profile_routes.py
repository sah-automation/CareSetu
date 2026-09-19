"""PHASE-8.1 T1 (#482): PUT/GET /v1/me/profile HTTP adapters.

Thin adapters: parse the typed profile body, call the identity facade seam
(``save_patient_profile`` / ``get_patient_profile``), answer the typed
read-back wrapper ``PatientProfileResponse``. Both routes are
``require_authenticated``-gated like ``/v1/me`` - anonymous callers are 401.
The facade is stubbed here - the DB-backed one-row-per-identity behaviour is
the integration suite's job. Identity isolation is asserted at the seam: each
authenticated subject id is forwarded verbatim, so identity 1 can never read
or write identity 2's row. Every expected failure answers the shared error
envelope (api-standards §2).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.config import Settings
from app.gateway.idempotency import IdempotencyStore
from app.main import create_app
from modules.iam.domain.exceptions import IamError
from modules.iam.domain.jwt import issue_token
from modules.iam.facade import PatientProfile

_SIGNING_KEY = "test-profile-route-signing-key"


def _token(*, subject_id: int = 1, scope: str = "patient") -> str:
    return issue_token(
        jti=uuid.uuid4().hex,
        subject_id=subject_id,
        scope=scope,
        signing_key=_SIGNING_KEY,
        now=datetime.now(UTC),
    )


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


_PROFILE = PatientProfile(
    name="Asha Devi",
    age=34,
    gender="female",
    preferred_language="hi",
    area="Daltonganj",
    emergency_contact="+9199876543211",
    photo_ref="iam/profile-7.jpg",
)

_PROFILE_BODY = _PROFILE.model_dump(mode="json")


class StubProfileFacade:
    """Identity-facade stand-in that isolates profiles per identity id.

    Mirrors the real facade's one-row-per-identity semantics in memory so the
    route tests can prove the two-identity isolation contract: writes are keyed
    by ``identity_id`` and reads scoped to the same key never leak across
    identities.
    """

    def __init__(self) -> None:
        self.profiles: dict[int, PatientProfile] = {}
        self.save_calls: list[tuple[int, PatientProfile]] = []
        self.error: Exception | None = None

    def _maybe_raise(self) -> None:
        if self.error is not None:
            raise self.error

    async def get_patient_profile(self, identity_id: int) -> PatientProfile | None:
        self._maybe_raise()
        return self.profiles.get(identity_id)

    async def save_patient_profile(
        self, identity_id: int, profile: PatientProfile
    ) -> PatientProfile:
        self._maybe_raise()
        self.save_calls.append((identity_id, profile))
        self.profiles[identity_id] = profile
        return profile


def _client(profile_facade: StubProfileFacade | None = None) -> TestClient:
    settings = Settings(gateway_jwt_verify_enabled=True, gateway_jwt_signing_key=_SIGNING_KEY)
    app = create_app(settings=settings)
    app.state.iam_facade = profile_facade if profile_facade is not None else StubProfileFacade()
    return TestClient(app)


def _client_with_store(facade: StubProfileFacade, store: IdempotencyStore) -> TestClient:
    client = _client(profile_facade=facade)
    client.app.state.idempotency_store = store
    return client


# ---------------------------------------------------------------------------
# GET: read surface
# ---------------------------------------------------------------------------


def test_get_returns_typed_not_set_without_a_saved_profile() -> None:
    client = _client()

    response = client.get("/v1/me/profile", headers=_bearer(_token()))

    assert response.status_code == 200
    assert response.json() == {"set": False, "profile": None}


def test_get_returns_the_saved_profile() -> None:
    facade = StubProfileFacade()
    facade.profiles[1] = _PROFILE
    client = _client(profile_facade=facade)

    response = client.get("/v1/me/profile", headers=_bearer(_token(subject_id=1)))

    assert response.status_code == 200
    assert response.json() == {"set": True, "profile": _PROFILE_BODY}


def test_get_unauthenticated_rejected_with_401() -> None:
    client = _client()

    response = client.get("/v1/me/profile")

    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_UNAUTHENTICATED"


# ---------------------------------------------------------------------------
# PUT: upsert mutation
# ---------------------------------------------------------------------------


def test_put_persists_the_profile_and_returns_the_typed_read_back() -> None:
    facade = StubProfileFacade()
    client = _client(profile_facade=facade)

    response = client.put("/v1/me/profile", json=_PROFILE_BODY, headers=_bearer(_token()))

    assert response.status_code == 200
    assert response.json() == {"set": True, "profile": _PROFILE_BODY}
    assert facade.save_calls == [(1, _PROFILE)]


def test_put_then_get_round_trips_the_saved_profile() -> None:
    client = _client()

    put = client.put("/v1/me/profile", json=_PROFILE_BODY, headers=_bearer(_token()))
    get = client.get("/v1/me/profile", headers=_bearer(_token()))

    assert put.status_code == 200
    assert get.status_code == 200
    assert get.json() == put.json() == {"set": True, "profile": _PROFILE_BODY}


def test_put_repeat_payload_converges_to_one_profile_row() -> None:
    facade = StubProfileFacade()
    client = _client(profile_facade=facade)
    updated = dict(_PROFILE_BODY)
    updated["name"] = "Asha Devi Singh"

    first = client.put("/v1/me/profile", json=_PROFILE_BODY, headers=_bearer(_token()))
    second = client.put("/v1/me/profile", json=updated, headers=_bearer(_token()))

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["profile"] == updated
    assert len(facade.profiles) == 1
    get = client.get("/v1/me/profile", headers=_bearer(_token()))
    assert get.json()["profile"] == updated


def test_put_unauthenticated_rejected_with_401() -> None:
    client = _client()

    response = client.put("/v1/me/profile", json=_PROFILE_BODY)

    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_UNAUTHENTICATED"


# ---------------------------------------------------------------------------
# Identity isolation
# ---------------------------------------------------------------------------


def test_two_identities_read_write_with_no_leakage() -> None:
    facade = StubProfileFacade()
    client = _client(profile_facade=facade)
    second = dict(_PROFILE_BODY)
    second["name"] = "Manoj Kumar"

    first_put = client.put(
        "/v1/me/profile", json=_PROFILE_BODY, headers=_bearer(_token(subject_id=1))
    )
    first_get = client.get("/v1/me/profile", headers=_bearer(_token(subject_id=1)))
    second_get_left = client.get("/v1/me/profile", headers=_bearer(_token(subject_id=2)))
    second_put = client.put("/v1/me/profile", json=second, headers=_bearer(_token(subject_id=2)))
    first_get_after = client.get("/v1/me/profile", headers=_bearer(_token(subject_id=1)))
    second_get_after = client.get("/v1/me/profile", headers=_bearer(_token(subject_id=2)))

    assert first_put.status_code == 200
    assert first_get.json() == {"set": True, "profile": _PROFILE_BODY}
    # Identity 2 must not see identity 1's profile before it saves its own.
    assert second_get_left.json() == {"set": False, "profile": None}
    assert second_put.status_code == 200
    assert first_get_after.json()["profile"] == _PROFILE_BODY
    assert second_get_after.json()["profile"] == second
    assert sorted(identity_id for identity_id, _ in facade.save_calls) == [1, 2]


# ---------------------------------------------------------------------------
# Shared error envelope (api-standards §2)
# ---------------------------------------------------------------------------


def test_invalid_profile_rejected_with_422_envelope() -> None:
    facade = StubProfileFacade()
    client = _client(profile_facade=facade)

    bad = dict(_PROFILE_BODY)
    bad["age"] = -5
    response = client.put("/v1/me/profile", json=bad, headers=_bearer(_token()))

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert facade.save_calls == []


def test_unknown_field_rejected_at_the_gateway() -> None:
    facade = StubProfileFacade()
    client = _client(profile_facade=facade)

    extra = dict(_PROFILE_BODY)
    extra["device"] = "x"
    response = client.put("/v1/me/profile", json=extra, headers=_bearer(_token()))

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert facade.save_calls == []


def test_iam_error_answers_500_envelope() -> None:
    facade = StubProfileFacade()
    facade.error = IamError("boom")
    client = _client(profile_facade=facade)

    response = client.put("/v1/me/profile", json=_PROFILE_BODY, headers=_bearer(_token()))

    assert response.status_code == 500
    body = response.json()
    assert body["code"] == "IAM_INTERNAL"
    assert "boom" not in body["message"]


def test_get_iam_error_answers_500_envelope() -> None:
    facade = StubProfileFacade()
    facade.error = IamError("boom")
    client = _client(profile_facade=facade)

    response = client.get("/v1/me/profile", headers=_bearer(_token()))

    assert response.status_code == 500
    body = response.json()
    assert body["code"] == "IAM_INTERNAL"
    assert "boom" not in body["message"]


def test_overlong_name_rejected_with_422_before_the_facade() -> None:
    facade = StubProfileFacade()
    client = _client(profile_facade=facade)

    bad = dict(_PROFILE_BODY)
    bad["name"] = "x" * 201
    response = client.put("/v1/me/profile", json=bad, headers=_bearer(_token()))

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert facade.save_calls == []


# ---------------------------------------------------------------------------
# Idempotency-Key on the PUT mutation (api-standards §5)
# ---------------------------------------------------------------------------


def test_put_replays_same_key_without_second_facade_call() -> None:
    facade = StubProfileFacade()
    client = _client_with_store(facade, IdempotencyStore())
    headers = {**_bearer(_token()), "Idempotency-Key": "retry-prof-123"}

    first = client.put("/v1/me/profile", json=_PROFILE_BODY, headers=headers)
    replay = client.put("/v1/me/profile", json=_PROFILE_BODY, headers=headers)

    assert first.status_code == 200
    assert replay.status_code == 200
    assert replay.json() == first.json() == {"set": True, "profile": _PROFILE_BODY}
    assert len(facade.save_calls) == 1


def test_put_different_keys_execute_each_mutation() -> None:
    facade = StubProfileFacade()
    client = _client_with_store(facade, IdempotencyStore())

    client.put(
        "/v1/me/profile",
        json=_PROFILE_BODY,
        headers={**_bearer(_token()), "Idempotency-Key": "k-1"},
    )
    client.put(
        "/v1/me/profile",
        json=_PROFILE_BODY,
        headers={**_bearer(_token()), "Idempotency-Key": "k-2"},
    )

    assert len(facade.save_calls) == 2


def test_put_no_key_passes_through_without_store_interaction() -> None:
    facade = StubProfileFacade()
    client = _client(profile_facade=facade)

    client.put("/v1/me/profile", json=_PROFILE_BODY, headers=_bearer(_token()))
    client.put("/v1/me/profile", json=_PROFILE_BODY, headers=_bearer(_token()))

    assert len(facade.save_calls) == 2


def test_same_key_across_identities_never_replays_anothers_profile() -> None:
    facade = StubProfileFacade()
    client = _client_with_store(facade, IdempotencyStore())
    shared = {"Idempotency-Key": "k-shared"}
    second = dict(_PROFILE_BODY)
    second["name"] = "Manoj Kumar"

    first = client.put(
        "/v1/me/profile",
        json=_PROFILE_BODY,
        headers={**_bearer(_token(subject_id=1)), **shared},
    )
    # Identity 2 reuses the same client key: it must NOT get identity 1's
    # cached response - the replay cache is namespaced per principal - so its
    # own profile is written and read back.
    second_put = client.put(
        "/v1/me/profile",
        json=second,
        headers={**_bearer(_token(subject_id=2)), **shared},
    )
    second_get = client.get("/v1/me/profile", headers=_bearer(_token(subject_id=2)))

    assert first.status_code == 200
    assert second_put.status_code == 200
    assert second_put.json()["profile"] == second
    assert second_get.json() == {"set": True, "profile": second}
    assert sorted(identity_id for identity_id, _ in facade.save_calls) == [1, 2]


# ---------------------------------------------------------------------------
# OpenAPI surface
# ---------------------------------------------------------------------------


def test_profile_routes_sit_behind_the_gateway_stack() -> None:
    paths = create_app().openapi()["paths"]

    assert "/v1/me/profile" in paths
    assert set(paths["/v1/me/profile"]) == {"get", "put"}
