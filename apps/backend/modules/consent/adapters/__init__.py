"""MOD-004: event handlers for the ``consent`` module (coding-standards §2).

``register_handlers`` is the composition-root seam (PHASE-1 T4, #30):
the worker entrypoint calls it to register this module's handlers on the
shared ``HandlerRegistry``. PHASE-3 T3 (#212) registers the PAYLOAD MODELS
for the lifecycle events the module PUBLISHES (``consent.requested/granted/
revoked``) - the dispatcher needs a registered model to reconstruct a typed
envelope from any claimed ``consent.consent_outbox`` row at all. No handlers
yet. The generic ``audit.event`` carrier's payload model is owned by its
consumer MOD-011 (registered there, not here, since PHASE-4 T4 #239).
"""

from __future__ import annotations

from bus.events import (
    EVENT_CONSENT_GRANTED,
    EVENT_CONSENT_REQUESTED,
    EVENT_CONSENT_REVOKED,
)
from bus.registry import HandlerRegistry
from modules.consent.domain.events import (
    ConsentGrantedPayload,
    ConsentRequestedPayload,
    ConsentRevokedPayload,
)


def register_handlers(registry: HandlerRegistry) -> None:
    """Register the consent module's produced-event payload models."""
    registry.register_payload_model(EVENT_CONSENT_REQUESTED, ConsentRequestedPayload)
    registry.register_payload_model(EVENT_CONSENT_GRANTED, ConsentGrantedPayload)
    registry.register_payload_model(EVENT_CONSENT_REVOKED, ConsentRevokedPayload)
