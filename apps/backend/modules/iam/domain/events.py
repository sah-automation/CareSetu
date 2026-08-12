"""MOD-001: canonical auth event payloads (PHASE-2 T3/T4, tickets #54, #55).

Event names follow the registry dot-notation in ``internal-modules.md`` §4.2
(spec #51 §2.6); the legacy snake_case telemetry names are superseded. Payloads
are typed Pydantic models (coding-standards §3) and never carry the OTP value,
the hash, or any other secret - they name the identity and the challenge only.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from pydantic import BaseModel

from bus.envelope import Envelope
from bus.events import (
    EVENT_OTP_SENT,
    EVENT_PATIENT_AUTH_FAILED,
    EVENT_PATIENT_REGISTERED,
    EVENT_PATIENT_VERIFIED,
)
from modules.iam.domain.verify import FailureReason

PRODUCER_MODULE = "iam"


class PatientRegisteredPayload(BaseModel):
    """Subject of ``patient.registered``: the identity just created."""

    identity_id: int
    phone_e164: str


class OtpSentPayload(BaseModel):
    """Subject of ``otp.sent``: the challenge issued, never the code itself."""

    identity_id: int
    challenge_id: int
    expires_at: datetime


class PatientVerifiedPayload(BaseModel):
    """Subject of ``patient.verified``: the identity just verified."""

    identity_id: int
    phone_e164: str


class PatientAuthFailedPayload(BaseModel):
    """Subject of ``patient.auth_failed``: a failed verification attempt.

    ``identity_id`` is ``None`` only when the phone was never registered, so
    there is no identity to name. ``attempts_left`` is the remaining budget
    after a wrong guess, 0 when the budget is exhausted (``spent``), and
    ``None`` for expired/replayed challenges where the remaining budget is
    meaningless.
    """

    identity_id: int | None
    phone_e164: str
    reason: FailureReason
    attempts_left: int | None = None


def patient_registered_envelope(
    identity_id: int, phone_e164: str
) -> Envelope[PatientRegisteredPayload]:
    """Build the ``patient.registered`` envelope for the iam outbox."""
    return Envelope[PatientRegisteredPayload](
        event_id=uuid4(),
        event_type=EVENT_PATIENT_REGISTERED,
        producer=PRODUCER_MODULE,
        payload=PatientRegisteredPayload(identity_id=identity_id, phone_e164=phone_e164),
    )


def otp_sent_envelope(
    identity_id: int, challenge_id: int, expires_at: datetime
) -> Envelope[OtpSentPayload]:
    """Build the ``otp.sent`` envelope for the iam outbox."""
    return Envelope[OtpSentPayload](
        event_id=uuid4(),
        event_type=EVENT_OTP_SENT,
        producer=PRODUCER_MODULE,
        payload=OtpSentPayload(
            identity_id=identity_id, challenge_id=challenge_id, expires_at=expires_at
        ),
    )


def patient_verified_envelope(
    identity_id: int, phone_e164: str
) -> Envelope[PatientVerifiedPayload]:
    """Build the ``patient.verified`` envelope for the iam outbox.

    Emitted on every successful OTP verification (spec #51 §2.6), never on
    failure, and written in the same transaction as the challenge consumption
    and identity transition.
    """
    return Envelope[PatientVerifiedPayload](
        event_id=uuid4(),
        event_type=EVENT_PATIENT_VERIFIED,
        producer=PRODUCER_MODULE,
        payload=PatientVerifiedPayload(identity_id=identity_id, phone_e164=phone_e164),
    )


def patient_auth_failed_envelope(
    identity_id: int | None,
    phone_e164: str,
    reason: FailureReason,
    attempts_left: int | None = None,
) -> Envelope[PatientAuthFailedPayload]:
    """Build the ``patient.auth_failed`` envelope for the iam outbox.

    Emitted for every rejected verification (wrong code, expired, spent,
    replayed, or missing challenge) in the same transaction as the attempt;
    never emitted on success.
    """
    return Envelope[PatientAuthFailedPayload](
        event_id=uuid4(),
        event_type=EVENT_PATIENT_AUTH_FAILED,
        producer=PRODUCER_MODULE,
        payload=PatientAuthFailedPayload(
            identity_id=identity_id,
            phone_e164=phone_e164,
            reason=reason,
            attempts_left=attempts_left,
        ),
    )
