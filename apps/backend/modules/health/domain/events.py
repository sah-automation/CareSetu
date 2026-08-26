"""MOD-003: subscriber-side view of the events the health module consumes.

The health module is the app's first real bus consumer (PHASE-3 T2, #211):
``patient.registered`` -> record shell creation. Module isolation
(coding-standards §2, ADR-0003) forbids importing the producer's payload
model (iam's ``domain.events``), so a subscriber declares its own typed
mirror of the payload shape it consumes; the dispatcher validates the stored
JSONB against whatever model is registered for the event type. The registry
admits exactly one payload model per event type and health is
``patient.registered``'s only consumer today - when a second subscriber
appears (consent profile init, PHASE-3 T3), either it reuses a shared mirror
home or the registration moves there deliberately.
"""

from __future__ import annotations

from pydantic import BaseModel


class PatientRegisteredPayload(BaseModel):
    """Subscriber mirror of ``patient.registered``: the identity just created.

    Field-for-field the producer's contract (identity id + normalized E.164
    phone); extra producer fields would be dropped by validation, missing ones
    fail the delivery loudly instead of creating a half-named shell.
    """

    identity_id: int
    phone_e164: str


class ReportFiledPayload(BaseModel):
    """Subscriber mirror of ``report.filed``: a lab report filed into the record.

    Minimal fields to create a record entry: the diagnostic order id, patient
    identity, report filename, and when the clinical event occurred.
    """

    order_id: int
    patient_id: int
    filename: str
    occurred_at: str  # ISO 8601 datetime string


class PrescriptionIssuedPayload(BaseModel):
    """Subscriber mirror of ``prescription.issued``: a prescription issued to the patient.

    Fields to create a record entry: prescription id, patient identity, and
    the clinical time of issuance.
    """

    prescription_id: int
    patient_id: int
    occurred_at: str  # ISO 8601 datetime string


class PrescriptionDeliveredPayload(BaseModel):
    """Subscriber mirror of ``prescription.delivered``: a prescription fulfilled/delivered.

    Fields to create a record entry: fulfillment order id, prescription id,
    patient identity, and when the clinical event occurred.
    """

    fulfillment_order_id: int
    prescription_id: int
    patient_id: int
    occurred_at: str  # ISO 8601 datetime string


class SettlementRecordedPayload(BaseModel):
    """Subscriber mirror of ``settlement.recorded``: a settlement recorded for an order.

    Fields to create a record entry: settlement id, order reference, patient
    identity, amount in paise, and when the clinical event occurred.
    """

    settlement_id: int
    order_ref: str
    patient_id: int
    amount_paise: int
    occurred_at: str  # ISO 8601 datetime string
