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
# MOD-003 (health): emitted on every record read - owner or consented partner.
# Dual-write with the health_record_access_history ledger (FEAT-003): the
# event drives MOD-011's hash chain, the local ledger feeds the fast patient
# view. internal-modules.md §4.2 registry.
EVENT_RECORD_ACCESSED = "record.accessed"
# MOD-003 (health): emitted when a read attempt is denied (non-owner or a
# failed consent check); carries denied=true + denial_reason in metadata.
# Dot-notation per the registry grammar (CONTEXT.md glossary) - the PRD's
# legacy snake_case spelling is superseded and rejected repo-wide.
EVENT_RECORD_DENIED = "record.denied"
# MOD-011 (audit): emitted into ``audit.audit_outbox`` by the tamper guard
# trigger when an UPDATE/DELETE on ``audit.audit_events`` is attempted and
# blocked (PHASE-4 #234 user story 11). Telemetry only - deliberately NOT in
# ``REGULATED_ACT_TYPES``, so it never enters the hash chain; real-time
# alert delivery is deferred, the outbox row is the publication.
EVENT_AUDIT_TAMPER_DETECTED = "audit.tamper_detected"
# MOD-002 (partner): emitted when a partner credential account is created
# synchronously by the iam facade (ADR-0010, ticket #245).
EVENT_OPERATOR_INVITED = "operator.invited"
EVENT_PARTNER_REGISTERED = "partner.registered"
# MOD-002 (partner): emitted when a verification round (first-time or
# re-verification) opens, carrying the round/version in the payload so the
# audit trail distinguishes rounds (ADR-0008, ticket #247).
EVENT_PARTNER_VERIFICATION_STARTED = "partner.verification_started"
# MOD-002 (partner): emitted ONLY on explicit operator approval - no
# auto-approve path ever reaches Active (ADR-0008 two-step gate, ticket #247).
EVENT_PARTNER_ACTIVATED = "partner.activated"
# MOD-002 (partner): emitted on operator rejection (carries the reason) or on
# Step-1 auto-fail (never queued) (ADR-0008, ticket #247).
EVENT_PARTNER_REJECTED = "partner.rejected"
# MOD-002 (partner): emitted when an operator views a partner's credentials
# during review, carrying actor + partner + timestamp (ADR-0008, ticket #247).
# Layered on top of the terminal decision audit (partner.activated/rejected).
EVENT_PARTNER_CREDENTIAL_REVIEWED = "partner.credential_reviewed"
# MOD-002 (partner): emitted when a credential is invalidated - on permanent
# rejection or when an active partner's re-verification window fails and the
# credential expires (7-day grace window), deindexing the directory (ticket #247).
EVENT_CREDENTIAL_INVALIDATED = "credential.invalidated"
# MOD-010 (notify): emitted into ``notify.notify_outbox`` when a delivery
# channel reports the message failed/undeliverable (ADR-0009). The EXT-003
# delivery webhook's ``notification.failed`` drives the WhatsApp -> SMS
# fallback: this event is the signal the notify consumer re-routes a
# terminal-status message to SMS on. Operational, deliberately NOT in
# ``REGULATED_ACT_TYPES``. internal-modules.md §4.2 registry.
EVENT_NOTIFICATION_FAILED = "notification.failed"
# MOD-002 (partner): emitted once per public directory search (FEAT-004,
# PHASE-6 T02a #313) for analytics - records the filters/query, the result
# count, and whether the wider-area fallback fired. Dot-notation ``directory
# .search`` per the registry grammar (the PRD's legacy ``directory_search``
# spelling is the display label; the ``Envelope`` validator enforces
# ``domain.action``). Deliberately NOT in ``REGULATED_ACT_TYPES`` - this is
# anonymous product analytics, not a regulated act, and carries no PHI.
EVENT_DIRECTORY_SEARCH = "directory.search"
# MOD-002 (partner): emitted once per directory pick - a patient selects a
# provider from the search results or a profile (FEAT-004 telemetry, PHASE-6 T4
# #326). Client-initiated product analytics, not a regulated act: carries only
# the pick facts (picked partner id + partner type, source surface), no actor
# (the public ingest route is anonymous) and no PHI. Dot-notation
# ``partner.selected`` per the registry grammar, superseding the PRD's legacy
# ``provider_selected`` spelling; the ``Envelope`` validator rejects the
# snake_case form and ``check_event_names.py`` gates it repo-wide. Deliberately
# NOT in ``REGULATED_ACT_TYPES``.
EVENT_PARTNER_SELECTED = "partner.selected"

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
        EVENT_RECORD_ACCESSED,
        EVENT_RECORD_DENIED,
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
        EVENT_PARTNER_REGISTERED,
        EVENT_PARTNER_ACTIVATED,
        EVENT_PARTNER_REJECTED,
        EVENT_PARTNER_CREDENTIAL_REVIEWED,
        EVENT_CREDENTIAL_INVALIDATED,
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
