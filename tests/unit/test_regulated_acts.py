"""PHASE-4 T3: regulated-act filter for the audit chain (ticket #237, NFR-D01).

Pins the classifer contract without a database: every regulated-act event
type returns True, every operational event type returns False, and unknown
event types default to False (conservative). Prior art: the pure-logic
parametrized suites (test_audit_chain, test_consent_state_machine).
"""

from __future__ import annotations

import pytest

from bus.events import (
    REGULATED_ACT_TYPES,
    is_regulated_act,
)

#: The ~20 regulated-act event types from the spec (PHASE-4 / NFR-D01).
_REGULATED: tuple[str, ...] = (
    # Consent lifecycle
    "consent.requested",
    "consent.granted",
    "consent.revoked",
    # Record access
    "record.accessed",
    "record.denied",
    # Prescriptions
    "prescription.approved",
    "prescription.rejected",
    "prescription.routed",
    # Diagnostics
    "report.filed",
    "report.rejected_mismatch",
    "sample.collected",
    # Settlements / payments
    "settlement.recorded",
    "platform_payment.initiated",
    "payment.webhook_received",
    "order.cancelled",
    "refund.partner_direct",
    # Partner decisions
    "partner.registered",
    "partner.activated",
    "partner.rejected",
    "credential.invalidated",
    # Patient lifecycle
    "patient.registered",
    "patient.verified",
    "patient.auth_failed",
)

#: Operational event types that must NOT enter the hash chain.
_OPERATIONAL: tuple[str, ...] = (
    "notification.sent",
    "notification.delivered",
    "notification.failed",
    "otp.sent",
    "otp.failed",
    "partner.verification_started",
    "partner.credential_reviewed",
    "metric.logged",
    "metric_out_of_range",
    "follow_up.due",
    "order.preparing",
    "order.out_for_delivery",
    "order.delivered",
    "intake.captured",
    "pre_summary.ready",
    "pre_summary.low_confidence",
    "ai_job.failed",
    "case.consult_complete",
)


@pytest.mark.parametrize("event_type", _REGULATED)
def test_regulated_act_types_return_true(event_type: str) -> None:
    assert is_regulated_act(event_type)


@pytest.mark.parametrize("event_type", _OPERATIONAL)
def test_operational_event_types_return_false(event_type: str) -> None:
    assert not is_regulated_act(event_type)


@pytest.mark.parametrize(
    "event_type",
    [
        "some.future_event",
        "unknown.type",
        "audit.event",
        "audit.tamper_detected",
        "prescription.issued",
        "prescription.delivered",
        "diagnostic.order_booked",
        "report.uploaded",
        "out_of_stock.notified",
        "delivery.failure",
        "case.egress_authorized",
        "",
    ],
)
def test_unknown_event_types_return_false(event_type: str) -> None:
    assert not is_regulated_act(event_type)


def test_whitelist_is_a_frozenset() -> None:
    assert isinstance(REGULATED_ACT_TYPES, frozenset)
    assert len(REGULATED_ACT_TYPES) == len(_REGULATED)


def test_whitelist_contains_exactly_the_regulated_acts() -> None:
    assert set(_REGULATED) == REGULATED_ACT_TYPES


def test_partner_regulated_events_referenced_by_constant() -> None:
    # PHASE-5 T04 (#247): the four regulated partner events must be referenced
    # in the whitelist by their canonical constants, never a bare string, so
    # the code-side mirror cannot drift from bus.events.
    from bus import events as bus_events

    partner_regulated = (
        "EVENT_PARTNER_REGISTERED",
        "EVENT_PARTNER_ACTIVATED",
        "EVENT_PARTNER_REJECTED",
        "EVENT_CREDENTIAL_INVALIDATED",
    )
    for name in partner_regulated:
        assert getattr(bus_events, name) in REGULATED_ACT_TYPES
