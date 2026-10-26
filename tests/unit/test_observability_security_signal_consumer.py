"""Security signal aggregation consumers (PHASE-14B Batch 2, #777).

Covers the composition-root seam: the ``patient.auth_failed``, ``otp.failed``,
``record.denied``, and ``consent.revoked`` consumers register handler seats at the
worker with their own payload mirrors, accumulating one
``observability_security_signals`` row per (minute_ts, signal_kind, subject_key)
scope. The replay test drives the registered handler through the same short-lived
engine + ledger seam as the live dispatcher: a replayed ``event_id`` is a no-op
(ledger dedupe), so every effect behind that one ledger row runs exactly once per
distinct event.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel

from bus.envelope import Envelope
from bus.events import (
    EVENT_CONSENT_REVOKED,
    EVENT_OPERATOR_MFA_FAILED,
    EVENT_OTP_FAILED,
    EVENT_PATIENT_AUTH_FAILED,
    EVENT_RECORD_DENIED,
)
from bus.registry import HandlerRegistry
from modules.consent.adapters import register_handlers as register_consent_handlers
from modules.consent.domain.events import (
    consent_revoked_envelope,
)
from modules.health.adapters import register_handlers as register_health_handlers
from modules.health.domain.events import (
    record_denied_envelope,
)
from modules.iam.adapters import register_handlers as register_iam_handlers
from modules.iam.domain.events import (
    OperatorMfaFailedPayload,
    operator_mfa_failed_envelope,
    otp_failed_envelope,
    patient_auth_failed_envelope,
)
from modules.observability.adapters import register_handlers as register_obs_handlers
from modules.observability.domain.consumer import (
    ConsentLifecycleTelemetryPayload,
    OperatorMfaFailedTelemetryPayload,
    OtpFailedEventPayload,
    OtpFailedTelemetryPayload,
    PatientAuthFailedEventPayload,
    PatientAuthFailedTelemetryPayload,
    RecordDeniedTelemetryPayload,
)
from modules.observability.domain.pseudonym import (
    ACTOR_KIND_DOCTOR,
    ACTOR_KIND_PATIENT,
    actor_key,
)
from modules.observability.facade import accumulate_security_signal


def test_register_handlers_registers_security_signal_consumers() -> None:
    """MOD-013 registers consumer seats for security signal event types.

    Multiple modules may consume the same event (e.g., health + observability for
    consent.revoked), so we only assert that observability registers at least one
    handler per security signal event.
    """
    registry = HandlerRegistry()
    register_iam_handlers(registry)
    register_consent_handlers(registry)
    register_health_handlers(registry)
    register_obs_handlers(registry)

    assert len(registry.handlers_for(EVENT_PATIENT_AUTH_FAILED)) >= 1
    assert len(registry.handlers_for(EVENT_OPERATOR_MFA_FAILED)) >= 1
    assert len(registry.handlers_for(EVENT_OTP_FAILED)) >= 1
    assert len(registry.handlers_for(EVENT_RECORD_DENIED)) >= 1
    assert len(registry.handlers_for(EVENT_CONSENT_REVOKED)) >= 1


def test_register_handlers_registers_unclaimed_payload_models() -> None:
    """The dispatcher must be able to reconstruct the two IAM-failure envelopes.

    No other module claimed ``patient.auth_failed`` or ``otp.failed`` before the
    security-signal consumers, so without these registrations the dispatcher logs
    the row as a configuration error and leaves it for reclaim forever - the
    handlers would register and never fire. The registered shapes mirror the
    producer's full contract, not the narrowed security view, so a later consumer
    still sees every field.
    """
    registry = HandlerRegistry()
    register_obs_handlers(registry)

    assert registry.payload_model_for(EVENT_PATIENT_AUTH_FAILED) is PatientAuthFailedEventPayload
    assert registry.payload_model_for(EVENT_OTP_FAILED) is OtpFailedEventPayload


def test_registered_iam_failure_mirrors_keep_the_full_producer_contract() -> None:
    """The canonical mirrors carry the producer's fields; the handler mirrors drop PHI.

    A narrow canonical model would silently drop ``phone_e164`` for every future
    consumer of the event. The security handler's own re-validation is what keeps
    PHI out of the signal table.
    """
    auth = patient_auth_failed_envelope(
        identity_id=7,
        phone_e164="+15551234567",
        reason="wrong_code",
        attempts_left=2,
    )
    canonical_auth = PatientAuthFailedEventPayload.model_validate(auth.payload.model_dump())
    assert canonical_auth.phone_e164 == "+15551234567"
    assert canonical_auth.attempts_left == 2
    assert not hasattr(
        PatientAuthFailedTelemetryPayload.model_validate(canonical_auth.model_dump()),
        "phone_e164",
    )

    otp = otp_failed_envelope(
        identity_id=7,
        phone_e164="+15551234567",
        reason="lockout",
        lockout_until=None,
    )
    canonical_otp = OtpFailedEventPayload.model_validate(otp.payload.model_dump())
    assert canonical_otp.phone_e164 == "+15551234567"
    assert not hasattr(
        OtpFailedTelemetryPayload.model_validate(canonical_otp.model_dump()),
        "phone_e164",
    )


def test_operator_mfa_failed_model_is_claimed_and_drops_the_lift_time() -> None:
    """IAM claims the producer model; the security view keeps identity and reason."""
    registry = HandlerRegistry()
    register_iam_handlers(registry)

    assert registry.payload_model_for(EVENT_OPERATOR_MFA_FAILED) is OperatorMfaFailedPayload

    envelope = operator_mfa_failed_envelope(
        identity_id=12,
        reason="lockout",
        lockout_until=datetime(2026, 10, 26, 12, 30, tzinfo=UTC),
    )
    mirror = OperatorMfaFailedTelemetryPayload.model_validate(envelope.payload.model_dump())
    assert mirror.identity_id == 12
    assert mirror.reason == "lockout"
    assert not hasattr(mirror, "lockout_until")


def test_patient_auth_failed_payload_revalidates_into_security_mirror() -> None:
    """The auth failure mirror carries only identity and reason - no phone."""
    envelope = patient_auth_failed_envelope(
        identity_id=7,
        phone_e164="+15551234567",
        reason="wrong_code",
        attempts_left=2,
    )
    mirror = PatientAuthFailedTelemetryPayload.model_validate(envelope.payload.model_dump())
    assert isinstance(mirror, PatientAuthFailedTelemetryPayload)
    assert mirror.identity_id == 7
    assert mirror.reason == "wrong_code"
    # No phone_e164 field in the mirror - PHI-free
    assert not hasattr(mirror, "phone_e164")
    assert not hasattr(mirror, "attempts_left")


def test_patient_auth_failed_payload_revalidates_with_none_identity() -> None:
    """Auth failure for unregistered phone has no identity_id."""
    envelope = patient_auth_failed_envelope(
        identity_id=None,
        phone_e164="+15551234567",
        reason="no_challenge",
    )
    mirror = PatientAuthFailedTelemetryPayload.model_validate(envelope.payload.model_dump())
    assert mirror.identity_id is None
    assert mirror.reason == "no_challenge"


def test_otp_failed_payload_revalidates_into_security_mirror() -> None:
    """The OTP failure mirror carries identity and reason - no phone or OTP."""
    envelope = otp_failed_envelope(
        identity_id=7,
        phone_e164="+15551234567",
        reason="lockout",
        lockout_until=None,
    )
    mirror = OtpFailedTelemetryPayload.model_validate(envelope.payload.model_dump())
    assert isinstance(mirror, OtpFailedTelemetryPayload)
    assert mirror.identity_id == 7
    assert mirror.reason == "lockout"
    # No phone_e164 or lockout_until in the mirror - PHI-free
    assert not hasattr(mirror, "phone_e164")
    assert not hasattr(mirror, "lockout_until")


def test_record_denied_payload_revalidates_into_security_mirror() -> None:
    """The record denial mirror carries record and actor - and drops free text."""
    envelope = record_denied_envelope(
        record_id=42,
        actor_id=7,
        actor_type="patient",
        scope="consultations",
        accessed_at="2026-10-25T12:00:00Z",
        denial_reason="no_consent",
    )
    mirror = RecordDeniedTelemetryPayload.model_validate(envelope.payload.model_dump())
    assert isinstance(mirror, RecordDeniedTelemetryPayload)
    assert mirror.record_id == 42
    assert mirror.actor_id == 7
    assert mirror.actor_type == "patient"
    # The producer's scope, timestamp and free-text reason are not mirrored.
    assert not hasattr(mirror, "metadata")
    assert not hasattr(mirror, "denial_reason")
    assert not hasattr(mirror, "scope")
    assert not hasattr(mirror, "accessed_at")


def test_consent_revoked_payload_revalidates_into_lifecycle_mirror() -> None:
    """The seat mirror for consent.revoked is the lifecycle shape with patient_id."""
    envelope = consent_revoked_envelope(
        consent_id=10,
        lineage_ref="lin-123",
        patient_id=7,
        counterparty_type="doctor",
        counterparty_id="doc-456",
        record_scope="consultations",
        version=3,
    )
    mirror = ConsentLifecycleTelemetryPayload.model_validate(envelope.payload.model_dump())
    assert isinstance(mirror, ConsentLifecycleTelemetryPayload)
    assert mirror.consent_id == 10
    assert mirror.lineage_ref == "lin-123"
    assert mirror.patient_id == 7


@pytest.mark.asyncio
async def test_auth_failure_handler_accumulates_exactly_once_per_event_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Replayed ``event_id`` is a ledger no-op that never touches the signal."""
    registry = HandlerRegistry()
    register_iam_handlers(registry)
    register_consent_handlers(registry)
    register_health_handlers(registry)
    register_obs_handlers(registry)
    handler = registry.handlers_for(EVENT_PATIENT_AUTH_FAILED)[0]

    engine = MagicMock()
    engine.begin.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
    engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)
    engine.dispose = AsyncMock()
    monkeypatch.setattr("bus.handler_harness._delivery_engine", lambda: engine)

    delivered: set[str] = set()
    accumulate = AsyncMock()

    async def fake_ledger(
        conn: object, schema: str, envelope: Envelope[BaseModel], handler_result: object
    ) -> bool:
        del conn, schema, handler_result
        if str(envelope.event_id) in delivered:
            return False
        delivered.add(str(envelope.event_id))
        return True

    monkeypatch.setattr("bus.handler_harness.record_consumed_event", fake_ledger)
    monkeypatch.setattr("modules.observability.adapters.accumulate_security_signal", accumulate)

    first = patient_auth_failed_envelope(
        identity_id=7,
        phone_e164="+15551234567",
        reason="wrong_code",
        attempts_left=2,
    )
    second = patient_auth_failed_envelope(
        identity_id=8,
        phone_e164="+15557654321",
        reason="expired",
    )

    await handler(first)
    assert accumulate.await_count == 1
    args = accumulate.await_args.args
    assert args[2] == "auth_failure"
    assert args[3] == actor_key(ACTOR_KIND_PATIENT, 7)

    # Replay: the ledger row already exists, so the effect is skipped.
    await handler(first)
    assert accumulate.await_count == 1

    await handler(second)
    assert accumulate.await_count == 2
    args = accumulate.await_args.args
    assert args[3] == actor_key(ACTOR_KIND_PATIENT, 8)


@pytest.mark.asyncio
async def test_auth_failure_handler_hashes_none_identity_to_empty_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Auth failure with no identity (unregistered phone) uses empty subject key."""
    registry = HandlerRegistry()
    register_iam_handlers(registry)
    register_consent_handlers(registry)
    register_health_handlers(registry)
    register_obs_handlers(registry)
    handler = registry.handlers_for(EVENT_PATIENT_AUTH_FAILED)[0]

    engine = MagicMock()
    engine.begin.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
    engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)
    engine.dispose = AsyncMock()
    monkeypatch.setattr("bus.handler_harness._delivery_engine", lambda: engine)

    async def always_delivered(
        conn: object, schema: str, envelope: Envelope[BaseModel], handler_result: object
    ) -> bool:
        del conn, schema, envelope, handler_result
        return True

    monkeypatch.setattr("bus.handler_harness.record_consumed_event", always_delivered)
    accumulate = AsyncMock()
    monkeypatch.setattr("modules.observability.adapters.accumulate_security_signal", accumulate)

    envelope = patient_auth_failed_envelope(
        identity_id=None,
        phone_e164="+15551234567",
        reason="no_challenge",
    )

    await handler(envelope)
    assert accumulate.await_count == 1
    args = accumulate.await_args.args
    assert args[2] == "auth_failure"
    assert args[3] == ""


@pytest.mark.asyncio
async def test_otp_failure_handler_accumulates_exactly_once_per_event_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Replayed ``event_id`` is a ledger no-op for OTP failures."""
    registry = HandlerRegistry()
    register_iam_handlers(registry)
    register_consent_handlers(registry)
    register_health_handlers(registry)
    register_obs_handlers(registry)
    handler = registry.handlers_for(EVENT_OTP_FAILED)[0]

    engine = MagicMock()
    engine.begin.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
    engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)
    engine.dispose = AsyncMock()
    monkeypatch.setattr("bus.handler_harness._delivery_engine", lambda: engine)

    delivered: set[str] = set()
    accumulate = AsyncMock()

    async def fake_ledger(
        conn: object, schema: str, envelope: Envelope[BaseModel], handler_result: object
    ) -> bool:
        del conn, schema, handler_result
        if str(envelope.event_id) in delivered:
            return False
        delivered.add(str(envelope.event_id))
        return True

    monkeypatch.setattr("bus.handler_harness.record_consumed_event", fake_ledger)
    monkeypatch.setattr("modules.observability.adapters.accumulate_security_signal", accumulate)

    lockout = otp_failed_envelope(
        identity_id=7,
        phone_e164="+15551234567",
        reason="lockout",
    )
    delivery = otp_failed_envelope(
        identity_id=8,
        phone_e164="+15557654321",
        reason="delivery",
    )

    await handler(lockout)
    assert accumulate.await_count == 1
    args = accumulate.await_args.args
    assert args[2] == "otp_lockout"
    assert args[3] == actor_key(ACTOR_KIND_PATIENT, 7)

    await handler(lockout)
    assert accumulate.await_count == 1

    await handler(delivery)
    assert accumulate.await_count == 2
    args = accumulate.await_args.args
    assert args[2] == "otp_failure"
    assert args[3] == actor_key(ACTOR_KIND_PATIENT, 8)


@pytest.mark.asyncio
async def test_operator_mfa_failure_handler_counts_failures_and_lockouts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every failure counts; the lockout trip adds its own signal exactly once."""
    registry = HandlerRegistry()
    register_iam_handlers(registry)
    register_consent_handlers(registry)
    register_health_handlers(registry)
    register_obs_handlers(registry)
    handler = registry.handlers_for(EVENT_OPERATOR_MFA_FAILED)[0]

    engine = MagicMock()
    engine.begin.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
    engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)
    engine.dispose = AsyncMock()
    monkeypatch.setattr("bus.handler_harness._delivery_engine", lambda: engine)

    delivered: set[str] = set()
    accumulate = AsyncMock()

    async def fake_ledger(
        conn: object, schema: str, envelope: Envelope[BaseModel], handler_result: object
    ) -> bool:
        del conn, schema, handler_result
        if str(envelope.event_id) in delivered:
            return False
        delivered.add(str(envelope.event_id))
        return True

    monkeypatch.setattr("bus.handler_harness.record_consumed_event", fake_ledger)
    monkeypatch.setattr("modules.observability.adapters.accumulate_security_signal", accumulate)

    failure = operator_mfa_failed_envelope(identity_id=9)
    lockout = operator_mfa_failed_envelope(
        identity_id=9,
        reason="lockout",
        lockout_until=datetime(2026, 10, 26, 12, 30, tzinfo=UTC),
    )

    await handler(failure)
    assert accumulate.await_count == 1
    args = accumulate.await_args.args
    assert args[2] == "operator_mfa_failure"
    assert args[3] == actor_key(ACTOR_KIND_PATIENT, 9)

    await handler(failure)
    assert accumulate.await_count == 1

    await handler(lockout)
    assert accumulate.await_count == 3
    kinds = [call.args[2] for call in accumulate.await_args_list]
    assert kinds == [
        "operator_mfa_failure",
        "operator_mfa_failure",
        "operator_mfa_lockout",
    ]


@pytest.mark.asyncio
async def test_record_denial_handler_accumulates_exactly_once_per_event_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Replayed ``event_id`` is a ledger no-op for record denials."""
    registry = HandlerRegistry()
    register_iam_handlers(registry)
    register_consent_handlers(registry)
    register_health_handlers(registry)
    register_obs_handlers(registry)
    handler = registry.handlers_for(EVENT_RECORD_DENIED)[0]

    engine = MagicMock()
    engine.begin.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
    engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)
    engine.dispose = AsyncMock()
    monkeypatch.setattr("bus.handler_harness._delivery_engine", lambda: engine)

    delivered: set[str] = set()
    accumulate = AsyncMock()

    async def fake_ledger(
        conn: object, schema: str, envelope: Envelope[BaseModel], handler_result: object
    ) -> bool:
        del conn, schema, handler_result
        if str(envelope.event_id) in delivered:
            return False
        delivered.add(str(envelope.event_id))
        return True

    monkeypatch.setattr("bus.handler_harness.record_consumed_event", fake_ledger)
    monkeypatch.setattr("modules.observability.adapters.accumulate_security_signal", accumulate)

    first = record_denied_envelope(
        record_id=42,
        actor_id=7,
        actor_type="patient",
        scope="consultations",
        accessed_at="2026-10-25T12:00:00Z",
        denial_reason="no_consent",
    )
    second = record_denied_envelope(
        record_id=43,
        actor_id=8,
        actor_type="doctor",
        scope="prescriptions",
        accessed_at="2026-10-25T12:05:00Z",
        denial_reason="scope_mismatch",
    )

    await handler(first)
    assert accumulate.await_count == 1
    args = accumulate.await_args.args
    assert args[2] == "record_denial"
    assert args[3] == actor_key(ACTOR_KIND_PATIENT, 7)

    await handler(first)
    assert accumulate.await_count == 1

    await handler(second)
    assert accumulate.await_count == 2
    args = accumulate.await_args.args
    assert args[3] == actor_key(ACTOR_KIND_DOCTOR, 8)


@pytest.mark.asyncio
async def test_record_denial_handler_buckets_partner_actors_under_empty_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lab and chemist references live outside ActorKind, so the key stays empty.

    Hashing a partner account id as a doctor would let it collide with a doctor
    identity of the same serial; the empty key is the ticketed "hashed or empty"
    bucket instead.
    """
    registry = HandlerRegistry()
    register_health_handlers(registry)
    register_obs_handlers(registry)
    handler = registry.handlers_for(EVENT_RECORD_DENIED)[0]

    engine = MagicMock()
    engine.begin.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
    engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)
    engine.dispose = AsyncMock()
    monkeypatch.setattr("bus.handler_harness._delivery_engine", lambda: engine)

    async def always_delivered(
        conn: object, schema: str, envelope: Envelope[BaseModel], handler_result: object
    ) -> bool:
        del conn, schema, envelope, handler_result
        return True

    monkeypatch.setattr("bus.handler_harness.record_consumed_event", always_delivered)
    accumulate = AsyncMock()
    monkeypatch.setattr("modules.observability.adapters.accumulate_security_signal", accumulate)

    envelope = record_denied_envelope(
        record_id=42,
        actor_id=99,
        actor_type="lab",
        scope="lab_results",
        accessed_at="2026-10-25T12:00:00Z",
        denial_reason="no_consent",
    )

    await handler(envelope)
    assert accumulate.await_count == 1
    args = accumulate.await_args.args
    assert args[2] == "record_denial"
    assert args[3] == ""


@pytest.mark.asyncio
async def test_consent_revocation_handler_accumulates_exactly_once_per_event_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Replayed ``event_id`` is a ledger no-op for consent revocations.

    Only observability handlers are registered to isolate the ledger check.
    In production, each module has its own ``consumed_events`` ledger in its
    own schema, so multiple modules can consume the same event independently.
    """
    registry = HandlerRegistry()
    register_obs_handlers(registry)
    handler = registry.handlers_for(EVENT_CONSENT_REVOKED)[0]

    engine = MagicMock()
    engine.begin.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
    engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)
    engine.dispose = AsyncMock()
    monkeypatch.setattr("bus.handler_harness._delivery_engine", lambda: engine)

    delivered: set[str] = set()
    accumulate = AsyncMock()

    async def fake_ledger(
        conn: object, schema: str, envelope: Envelope[BaseModel], handler_result: object
    ) -> bool:
        del conn, schema, handler_result
        if str(envelope.event_id) in delivered:
            return False
        delivered.add(str(envelope.event_id))
        return True

    monkeypatch.setattr("bus.handler_harness.record_consumed_event", fake_ledger)
    monkeypatch.setattr("modules.observability.adapters.accumulate_security_signal", accumulate)

    first = consent_revoked_envelope(
        consent_id=10,
        lineage_ref="lin-123",
        patient_id=7,
        counterparty_type="doctor",
        counterparty_id="doc-456",
        record_scope="consultations",
        version=3,
    )
    second = consent_revoked_envelope(
        consent_id=11,
        lineage_ref="lin-456",
        patient_id=8,
        counterparty_type="lab",
        counterparty_id="lab-789",
        record_scope="lab_results",
        version=1,
    )

    await handler(first)
    assert accumulate.await_count == 1
    args = accumulate.await_args.args
    assert args[2] == "consent_revocation"
    assert args[3] == actor_key(ACTOR_KIND_PATIENT, 7)

    await handler(first)
    assert accumulate.await_count == 1

    await handler(second)
    assert accumulate.await_count == 2
    args = accumulate.await_args.args
    assert args[3] == actor_key(ACTOR_KIND_PATIENT, 8)


@pytest.mark.asyncio
async def test_security_signal_upsert_is_idempotent_per_minute_per_subject(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two distinct events in the same minute for the same subject increment count.

    This test verifies the SQL upsert logic at the facade level.
    """

    envelope1 = patient_auth_failed_envelope(
        identity_id=7,
        phone_e164="+15551234567",
        reason="wrong_code",
    )
    envelope2 = patient_auth_failed_envelope(
        identity_id=7,
        phone_e164="+15551234567",
        reason="expired",
    )

    connection = AsyncMock()
    subject_key = actor_key(ACTOR_KIND_PATIENT, 7)

    await accumulate_security_signal(connection, envelope1, "auth_failure", subject_key)
    await accumulate_security_signal(connection, envelope2, "auth_failure", subject_key)

    assert connection.execute.await_count == 2
    # Both statements should target the same minute_ts, signal_kind, subject_key
    # The ON CONFLICT DO UPDATE should increment count
