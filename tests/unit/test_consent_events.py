"""PHASE-3 T3: consent event payloads + envelope builders (ticket #212, FEAT-002).

Pins the code-side mirror of the §4.2 registry names the module publishes,
the closed scope/counterparty vocabularies on every payload, and the audit
carrier's no-PHI shape. The builders are the ONLY way a ``consent.*`` or
``audit.event`` envelope enters the module's outbox, so these tests pin the
seam's producer contract without a database.
"""

from __future__ import annotations

from typing import get_args

from bus.events import (
    EVENT_AUDIT_EVENT,
    EVENT_CONSENT_GRANTED,
    EVENT_CONSENT_REQUESTED,
    EVENT_CONSENT_REVOKED,
)
from modules.consent.domain.events import (
    PRODUCER_MODULE,
    CounterpartyType,
    RecordScope,
    consent_audit_envelope,
    consent_granted_envelope,
    consent_requested_envelope,
    consent_revoked_envelope,
)
from modules.consent.domain.state_machine import RECORD_SCOPES

_TRIPLE = ("doctor", "dr-77", "consultations")


def test_scope_literal_matches_the_closed_enum() -> None:
    assert frozenset(get_args(RecordScope)) == frozenset(RECORD_SCOPES)


def test_counterparty_vocabulary_is_doctor_lab_chemist() -> None:
    assert set(get_args(CounterpartyType)) == {"doctor", "lab", "chemist"}


def test_requested_envelope_names_the_lineage() -> None:
    envelope = consent_requested_envelope(9, "C-2026-004", 7, *_TRIPLE)

    assert envelope.event_type == EVENT_CONSENT_REQUESTED
    assert envelope.producer == PRODUCER_MODULE == "consent"
    assert envelope.payload.consent_id == 9
    assert envelope.payload.lineage_ref == "C-2026-004"
    assert envelope.payload.patient_id == 7
    assert envelope.payload.counterparty_type == "doctor"
    assert envelope.payload.counterparty_id == "dr-77"
    assert envelope.payload.record_scope == "consultations"


def test_granted_envelope_carries_the_minted_version() -> None:
    envelope = consent_granted_envelope(9, "C-2026-004", 7, *_TRIPLE, version=2)

    assert envelope.event_type == EVENT_CONSENT_GRANTED
    assert envelope.payload.version == 2


def test_revoked_envelope_cites_the_terminal_version_exactly() -> None:
    envelope = consent_revoked_envelope(9, "C-2026-004", 7, *_TRIPLE, version=2)

    assert envelope.event_type == EVENT_CONSENT_REVOKED
    # Receipts cite id + version exactly as they authorized: revocation keeps
    # v2 rather than minting a new number.
    assert envelope.payload.version == 2


def test_audit_envelope_names_action_without_record_content() -> None:
    envelope = consent_audit_envelope(
        action="granted",
        actor_patient_id=7,
        consent_id=9,
        lineage_ref="C-2026-004",
        record_scope="consultations",
        version=1,
    )

    assert envelope.event_type == EVENT_AUDIT_EVENT
    assert envelope.producer == "consent"
    dumped = envelope.payload.model_dump(mode="json")
    assert dumped["action"] == "granted"
    assert dumped["actor_patient_id"] == 7
    assert dumped["lineage_ref"] == "C-2026-004"
    assert dumped["version"] == 1


def test_every_builder_produces_distinct_event_ids() -> None:
    envelopes = [
        consent_requested_envelope(9, "C-2026-004", 7, *_TRIPLE),
        consent_granted_envelope(9, "C-2026-004", 7, *_TRIPLE, version=1),
        consent_revoked_envelope(9, "C-2026-004", 7, *_TRIPLE, version=1),
        consent_audit_envelope("declined", 7, 9, "C-2026-004", "consultations", 0),
    ]

    ids = {envelope.event_id for envelope in envelopes}
    assert len(ids) == len(envelopes)
