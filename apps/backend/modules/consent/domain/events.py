"""MOD-004: canonical consent event payloads and envelope builders.

Event names follow the registry dot-notation in ``internal-modules.md``
§4.2; payloads are typed Pydantic models (coding-standards §3) and carry
only the lineage identity and lifecycle facts - never record content or
any other PHI. Every builder answers an :class:`~bus.envelope.Envelope`
the facade writes into ``consent.consent_outbox`` in the SAME transaction
as the state change (ADR-0002 §1).

Alongside each lifecycle event the module publishes the generic
``audit.event`` (KPI-006: 100% of consent actions audited). MOD-011's
consumption engine arrives in Phase 4 - emission coverage is this ticket's
contract; when that engine lands, the audit payload-model registration in
``adapters/__init__.py`` moves to its owning module deliberately.
"""

from __future__ import annotations

from typing import Literal
from uuid import uuid4

from pydantic import BaseModel

from bus.envelope import Envelope
from bus.events import (
    EVENT_AUDIT_EVENT,
    EVENT_CONSENT_GRANTED,
    EVENT_CONSENT_REQUESTED,
    EVENT_CONSENT_REVOKED,
)

PRODUCER_MODULE = "consent"

CounterpartyType = Literal["doctor", "lab", "chemist"]
RecordScope = Literal["consultations", "prescriptions", "lab_results", "metrics", "full_record"]


class ConsentRequestedPayload(BaseModel):
    """Subject of ``consent.requested``: a lineage entered ``Requested``."""

    consent_id: int
    lineage_ref: str
    patient_id: int
    counterparty_type: CounterpartyType
    counterparty_id: str
    record_scope: RecordScope


class ConsentGrantedPayload(BaseModel):
    """Subject of ``consent.granted``: version ``version`` went live.

    A re-grant re-emits the event with the minted version number inside the
    same lineage reference, exactly as egress receipts will cite it.
    """

    consent_id: int
    lineage_ref: str
    patient_id: int
    counterparty_type: CounterpartyType
    counterparty_id: str
    record_scope: RecordScope
    version: int


class ConsentRevokedPayload(BaseModel):
    """Subject of ``consent.revoked``: the named version is now terminal."""

    consent_id: int
    lineage_ref: str
    patient_id: int
    counterparty_type: CounterpartyType
    counterparty_id: str
    record_scope: RecordScope
    version: int


ConsentAuditAction = Literal["requested", "granted", "revoked", "declined"]


class ConsentAuditPayload(BaseModel):
    """Subject of the generic ``audit.event`` for one consent action.

    Names the regulated act, the acting patient and the affected lineage +
    version without any record content. ``action`` is the human-readable
    verb (``requested | granted | revoked | declined``); decline publishes
    ONLY this audit event - no ``consent.*`` bus event exists for it.
    """

    action: ConsentAuditAction
    actor_patient_id: int
    consent_id: int
    lineage_ref: str
    record_scope: RecordScope
    version: int


def consent_requested_envelope(
    consent_id: int,
    lineage_ref: str,
    patient_id: int,
    counterparty_type: CounterpartyType,
    counterparty_id: str,
    record_scope: RecordScope,
) -> Envelope[ConsentRequestedPayload]:
    """Build the ``consent.requested`` envelope for the consent outbox."""
    return Envelope[ConsentRequestedPayload](
        event_id=uuid4(),
        event_type=EVENT_CONSENT_REQUESTED,
        producer=PRODUCER_MODULE,
        payload=ConsentRequestedPayload(
            consent_id=consent_id,
            lineage_ref=lineage_ref,
            patient_id=patient_id,
            counterparty_type=counterparty_type,
            counterparty_id=counterparty_id,
            record_scope=record_scope,
        ),
    )


def consent_granted_envelope(
    consent_id: int,
    lineage_ref: str,
    patient_id: int,
    counterparty_type: CounterpartyType,
    counterparty_id: str,
    record_scope: RecordScope,
    version: int,
) -> Envelope[ConsentGrantedPayload]:
    """Build the ``consent.granted`` envelope for the consent outbox."""
    return Envelope[ConsentGrantedPayload](
        event_id=uuid4(),
        event_type=EVENT_CONSENT_GRANTED,
        producer=PRODUCER_MODULE,
        payload=ConsentGrantedPayload(
            consent_id=consent_id,
            lineage_ref=lineage_ref,
            patient_id=patient_id,
            counterparty_type=counterparty_type,
            counterparty_id=counterparty_id,
            record_scope=record_scope,
            version=version,
        ),
    )


def consent_revoked_envelope(
    consent_id: int,
    lineage_ref: str,
    patient_id: int,
    counterparty_type: CounterpartyType,
    counterparty_id: str,
    record_scope: RecordScope,
    version: int,
) -> Envelope[ConsentRevokedPayload]:
    """Build the ``consent.revoked`` envelope for the consent outbox."""
    return Envelope[ConsentRevokedPayload](
        event_id=uuid4(),
        event_type=EVENT_CONSENT_REVOKED,
        producer=PRODUCER_MODULE,
        payload=ConsentRevokedPayload(
            consent_id=consent_id,
            lineage_ref=lineage_ref,
            patient_id=patient_id,
            counterparty_type=counterparty_type,
            counterparty_id=counterparty_id,
            record_scope=record_scope,
            version=version,
        ),
    )


def consent_audit_envelope(
    action: ConsentAuditAction,
    actor_patient_id: int,
    consent_id: int,
    lineage_ref: str,
    record_scope: RecordScope,
    version: int,
) -> Envelope[ConsentAuditPayload]:
    """Build the ``audit.event`` envelope for one consent action (KPI-006)."""
    return Envelope[ConsentAuditPayload](
        event_id=uuid4(),
        event_type=EVENT_AUDIT_EVENT,
        producer=PRODUCER_MODULE,
        payload=ConsentAuditPayload(
            action=action,
            actor_patient_id=actor_patient_id,
            consent_id=consent_id,
            lineage_ref=lineage_ref,
            record_scope=record_scope,
            version=version,
        ),
    )
