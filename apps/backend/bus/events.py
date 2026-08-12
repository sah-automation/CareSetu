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
# Reserved: the registry lists otp.failed but no module emits it yet. Do not
# use this constant before the producing phase lands.
EVENT_OTP_FAILED = "otp.failed"
