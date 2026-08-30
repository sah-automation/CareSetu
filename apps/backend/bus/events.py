"""Canonical event-type names for the async seam (single source of truth).

The ``Envelope`` and ``HandlerRegistry`` (``bus/envelope.py``,
``bus/registry.py``) enforce the registry ``domain.action`` grammar
(coding-standards §3). The event registry in ``internal-modules.md`` §4.2 is
the doc-side source of truth; these constants are its code-side mirror, so a
name is defined once and imported by every producing module instead of being
reinvented ad hoc. The PRD's legacy snake_case telemetry names are superseded
by this registry and are rejected repo-wide by ``check_event_names.py``.
"""

EVENT_PATIENT_REGISTERED = "patient.registered"
EVENT_PATIENT_VERIFIED = "patient.verified"
EVENT_PATIENT_AUTH_FAILED = "patient.auth_failed"
EVENT_OTP_SENT = "otp.sent"
# Emitted by MOD-001 (iam) when the brute-force lockout triggers (spec #51 §2.4).
EVENT_OTP_FAILED = "otp.failed"
# MOD-004 (consent) lifecycle events - internal-modules.md §4.2 registry.
EVENT_CONSENT_REQUESTED = "consent.requested"
EVENT_CONSENT_GRANTED = "consent.granted"
EVENT_CONSENT_REVOKED = "consent.revoked"
# MOD-007 (diagnostics) - report filed into patient record.
EVENT_REPORT_FILED = "report.filed"
# MOD-006 (care) - prescription lifecycle.
EVENT_PRESCRIPTION_ISSUED = "prescription.issued"
EVENT_PRESCRIPTION_DELIVERED = "prescription.delivered"
# MOD-009 (settlement) - settlement recorded.
EVENT_SETTLEMENT_RECORDED = "settlement.recorded"
# The generic audit carrier every module publishes into its OWN outbox in the
# same transaction as the audited change; MOD-011 consumes and appends to the
# audit schema (ADR-0002 §5) - the dispatcher never synthesizes it.
EVENT_AUDIT_EVENT = "audit.event"

# PHASE-4 T3 (#237): the canonical regulated-act whitelist. MOD-011 appends an
# ``audit.event`` payload to the hash chain only when its ``event_type`` is
# regulated; operational events (notifications, OTPs, metrics, order
# lifecycle, intake pipeline, case consult) are skipped. Mirrors the
# regulatory scope documented in implementation-roadmap PHASE-4 / NFR-D01.
REGULATED_ACT_TYPES: frozenset[str] = frozenset(
    {
        EVENT_CONSENT_REQUESTED,
        EVENT_CONSENT_GRANTED,
        EVENT_CONSENT_REVOKED,
        "record.accessed",
        "record_view_denied",
        "prescription.approved",
        "prescription.rejected",
        "prescription.routed",
        EVENT_REPORT_FILED,
        "report.rejected_mismatch",
        "sample.collected",
        EVENT_SETTLEMENT_RECORDED,
        "platform_payment.initiated",
        "payment.webhook_received",
        "order.cancelled",
        "refund.partner_direct",
        "partner.registered",
        "partner.activated",
        "partner.rejected",
        "credential.invalidated",
        EVENT_PATIENT_REGISTERED,
        EVENT_PATIENT_VERIFIED,
        EVENT_PATIENT_AUTH_FAILED,
    }
)


def is_regulated_act(event_type: str) -> bool:
    """Return True when ``event_type`` is a regulated act for the audit chain.

    Lookup is exact and conservative: an unknown (or future) event type is
    False, so only an explicitly whitelisted act is appended to the hash chain.
    """
    return event_type in REGULATED_ACT_TYPES
