"""MOD-001: canonical auth event payloads (PHASE-2 T3, ticket #54).

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

EVENT_PATIENT_REGISTERED = "patient.registered"
EVENT_OTP_SENT = "otp.sent"

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
