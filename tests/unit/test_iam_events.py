"""PHASE-2 REM T5: otp.failed payload + envelope builders (ticket #81).

The event models the two emitters the registry §4.2 lists: the brute-force
lockout (reason ``lockout``, carrying ``lockout_until``) and the delivery-
failure path (reason ``delivery``, no ``lockout_until``). These are pure-model
tests - no database - so they pin the payload contract directly; the outbox-
row writes for both paths are exercised at integration level.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from bus.envelope import Envelope
from bus.events import EVENT_OTP_FAILED, EVENT_PATIENT_AUTH_FAILED
from modules.iam.domain import events

_PHONE = "+919876543210"
_LOCKOUT_UNTIL = datetime(2026, 8, 13, 12, 16, 1, tzinfo=UTC)


def test_otp_failed_payload_models_the_lockout_reason() -> None:
    payload = events.OtpFailedPayload(
        identity_id=7, phone_e164=_PHONE, reason="lockout", lockout_until=_LOCKOUT_UNTIL
    )

    assert payload.reason == "lockout"
    assert payload.lockout_until == _LOCKOUT_UNTIL


def test_otp_failed_payload_models_the_delivery_reason() -> None:
    payload = events.OtpFailedPayload(identity_id=7, phone_e164=_PHONE, reason="delivery")

    assert payload.reason == "delivery"
    assert payload.lockout_until is None


def test_otp_failed_payload_rejects_an_unknown_reason() -> None:
    with pytest.raises(ValidationError):
        events.OtpFailedPayload(identity_id=7, phone_e164=_PHONE, reason="sms_down")


def test_otp_failed_envelope_defaults_to_the_lockout_emitter() -> None:
    envelope = events.otp_failed_envelope(
        identity_id=7, phone_e164=_PHONE, lockout_until=_LOCKOUT_UNTIL
    )

    assert isinstance(envelope, Envelope)
    assert envelope.event_type == EVENT_OTP_FAILED
    assert envelope.producer == "iam"
    assert envelope.payload.reason == "lockout"
    assert envelope.payload.lockout_until == _LOCKOUT_UNTIL


def test_otp_failed_envelope_delivery_emitter_carries_no_lockout_until() -> None:
    envelope = events.otp_failed_envelope(identity_id=7, phone_e164=_PHONE, reason="delivery")

    assert envelope.event_type == EVENT_OTP_FAILED
    assert envelope.producer == "iam"
    assert envelope.payload.reason == "delivery"
    assert envelope.payload.lockout_until is None


def test_otp_failed_payload_serializes_with_both_reasons() -> None:
    lockout = events.otp_failed_envelope(
        identity_id=7, phone_e164=_PHONE, lockout_until=_LOCKOUT_UNTIL
    )
    delivery = events.otp_failed_envelope(identity_id=7, phone_e164=_PHONE, reason="delivery")

    assert lockout.payload.model_dump(mode="json") == {
        "identity_id": 7,
        "phone_e164": _PHONE,
        "reason": "lockout",
        "lockout_until": "2026-08-13T12:16:01Z",
    }
    assert delivery.payload.model_dump(mode="json") == {
        "identity_id": 7,
        "phone_e164": _PHONE,
        "reason": "delivery",
        "lockout_until": None,
    }


# ---------------------------------------------------------------------------
# patient.auth_failed: the access_denied reason (PHASE-2 REM T7, #87)
# ---------------------------------------------------------------------------


def test_patient_auth_failed_payload_accepts_the_access_denied_reason() -> None:
    payload = events.PatientAuthFailedPayload(
        identity_id=7, phone_e164=_PHONE, reason="access_denied"
    )

    assert payload.reason == "access_denied"
    assert payload.attempts_left is None


def test_patient_auth_failed_envelope_models_the_access_denial_emitter() -> None:
    envelope = events.patient_auth_failed_envelope(
        identity_id=7, phone_e164=_PHONE, reason="access_denied"
    )

    assert isinstance(envelope, Envelope)
    assert envelope.event_type == EVENT_PATIENT_AUTH_FAILED
    assert envelope.producer == "iam"
    assert envelope.payload.model_dump(mode="json") == {
        "identity_id": 7,
        "phone_e164": _PHONE,
        "reason": "access_denied",
        "attempts_left": None,
    }
