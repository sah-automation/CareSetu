"""PHASE-5 T04: partner lifecycle event payloads + envelope builders (ticket #247).

Pins the code-side mirror of the §4.2 registry names the partner module
publishes: every event names its partner (and the actor / round / reason facts),
and no payload carries credential artifact bytes or any sensitive document
content (security-phii-standards). The builders are the ONLY way a
``partner.*`` or ``credential.*`` envelope enters the module's outbox, so these
tests pin the seam's producer contract without a database.
"""

from __future__ import annotations

from bus.events import (
    EVENT_CREDENTIAL_INVALIDATED,
    EVENT_DIRECTORY_SEARCH,
    EVENT_PARTNER_ACTIVATED,
    EVENT_PARTNER_CREDENTIAL_REVIEWED,
    EVENT_PARTNER_REGISTERED,
    EVENT_PARTNER_REJECTED,
    EVENT_PARTNER_VERIFICATION_STARTED,
)
from modules.partner.domain.events import (
    PRODUCER_MODULE,
    credential_invalidated_envelope,
    credential_reviewed_envelope,
    directory_search_envelope,
    partner_activated_envelope,
    partner_registered_envelope,
    partner_rejected_envelope,
    verification_started_envelope,
)


def test_producer_names_the_partner_module() -> None:
    assert PRODUCER_MODULE == "partner"


def test_registered_envelope_names_the_partner() -> None:
    envelope = partner_registered_envelope(partner_id=3, identity_id=9, partner_type="doctor")

    assert envelope.event_type == EVENT_PARTNER_REGISTERED
    assert envelope.producer == PRODUCER_MODULE
    assert envelope.payload.partner_id == 3
    assert envelope.payload.identity_id == 9
    assert envelope.payload.partner_type == "doctor"


def test_verification_started_carries_the_round() -> None:
    envelope = verification_started_envelope(partner_id=3, round=2)

    assert envelope.event_type == EVENT_PARTNER_VERIFICATION_STARTED
    assert envelope.payload.partner_id == 3
    assert envelope.payload.round == 2


def test_activated_carries_the_approving_operator() -> None:
    envelope = partner_activated_envelope(partner_id=3, identity_id=9, decision_by=77)

    assert envelope.event_type == EVENT_PARTNER_ACTIVATED
    assert envelope.payload.partner_id == 3
    assert envelope.payload.identity_id == 9
    assert envelope.payload.decision_by == 77


def test_rejected_carries_reason_and_round() -> None:
    envelope = partner_rejected_envelope(
        partner_id=3, identity_id=9, reason="doc unreadable", round=1
    )

    assert envelope.event_type == EVENT_PARTNER_REJECTED
    assert envelope.payload.reason == "doc unreadable"
    assert envelope.payload.round == 1
    assert envelope.payload.decision_by is None


def test_rejected_operator_decision_carries_actor() -> None:
    envelope = partner_rejected_envelope(
        partner_id=3, identity_id=9, reason="fraud signal", round=2, decision_by=77
    )

    assert envelope.payload.decision_by == 77


def test_credential_reviewed_carries_actor_and_partner() -> None:
    envelope = credential_reviewed_envelope(partner_id=3, actor_id=77)

    assert envelope.event_type == EVENT_PARTNER_CREDENTIAL_REVIEWED
    assert envelope.payload.partner_id == 3
    assert envelope.payload.actor_id == 77


def test_credential_invalidated_carries_reason() -> None:
    envelope = credential_invalidated_envelope(
        partner_id=3, identity_id=9, reason="grace lapsed", credential_id=5
    )

    assert envelope.event_type == EVENT_CREDENTIAL_INVALIDATED
    assert envelope.payload.partner_id == 3
    assert envelope.payload.identity_id == 9
    assert envelope.payload.credential_id == 5
    assert envelope.payload.reason == "grace lapsed"


def test_directory_search_carries_only_search_facts() -> None:
    """The analytics payload (FEAT-004) names the search, never the results.

    Filters, result count and the fallback flag travel on the bus; partner ids
    and distances (and anything PHI-ish) do not - the analytics consumer only
    needs the shape of the demand, not its content (error-handling-observability
    no-PHI; privacy by design, only the facts required.)
    """
    envelope = directory_search_envelope(
        patient_id=3,
        query="Sharma",
        partner_type="doctor",
        specialty="General Physician",
        result_count=2,
        fell_back=False,
    )

    assert envelope.event_type == EVENT_DIRECTORY_SEARCH
    assert envelope.producer == PRODUCER_MODULE
    assert envelope.payload.patient_id == 3
    assert envelope.payload.query == "Sharma"
    assert envelope.payload.partner_type == "doctor"
    assert envelope.payload.specialty == "General Physician"
    assert envelope.payload.result_count == 2
    assert envelope.payload.fell_back is False


def test_directory_search_allows_anonymous_fallbacks() -> None:
    """Anonymous patients and empty-wider-fallback outcomes are legal payloads."""
    envelope = directory_search_envelope(
        patient_id=None,
        query="No Such Clinic",
        partner_type=None,
        specialty=None,
        result_count=0,
        fell_back=True,
    )

    assert envelope.payload.patient_id is None
    assert envelope.payload.query == "No Such Clinic"
    assert envelope.payload.result_count == 0
    assert envelope.payload.fell_back is True


def test_no_payload_carries_credential_artifact_bytes() -> None:
    # security-phii-standards: credential documents are never in a payload -
    # only the profile identity, actor, round and reason travel on the bus.
    for envelope in (
        partner_registered_envelope(3, 9, "lab"),
        verification_started_envelope(3, 1),
        partner_activated_envelope(3, 9, 77),
        partner_rejected_envelope(3, 9, "reason", 1),
        credential_reviewed_envelope(3, 77),
        credential_invalidated_envelope(3, 9, "reason", 5),
        directory_search_envelope(
            patient_id=None,
            query="query",
            partner_type=None,
            specialty=None,
            result_count=0,
            fell_back=True,
        ),
    ):
        dumped = envelope.payload.model_dump(mode="json")
        assert "artifact" not in dumped
        assert "doc" not in dumped
        assert "ref" not in dumped


def test_every_builder_produces_distinct_event_ids() -> None:
    envelopes = [
        partner_registered_envelope(3, 9, "doctor"),
        verification_started_envelope(3, 1),
        partner_activated_envelope(3, 9, 77),
        partner_rejected_envelope(3, 9, "reason", 1),
        credential_reviewed_envelope(3, 77),
        credential_invalidated_envelope(3, 9, "reason", 5),
        directory_search_envelope(
            patient_id=None,
            query="query",
            partner_type="doctor",
            specialty="General Physician",
            result_count=2,
            fell_back=False,
        ),
    ]

    ids = {envelope.event_id for envelope in envelopes}
    assert len(ids) == len(envelopes)
