"""MOD-002: event handlers for the ``partner`` module (coding-standards §2).

``register_handlers`` is the composition-root seam (PHASE-1 T4, #30):
the worker entrypoint calls it to register this module's handlers on
the shared ``HandlerRegistry``. The partner module PRODUCES the following
events and owns their payload models (the producer owns the model):

- ``partner.verification_started`` → ``VerificationStartedPayload``
- ``partner.activated`` → ``PartnerActivatedPayload``
- ``partner.rejected`` → ``PartnerRejectedPayload``
- ``directory.search`` → ``DirectorySearchPayload``
- ``partner.selected`` → ``PartnerSelectedPayload``

EXCLUDED (Audit owns these regulated acts per REGULATED_ACT_TYPES):
- ``partner.registered`` (regulated act)
- ``partner.credential_reviewed`` (regulated act)
- ``credential.invalidated`` (regulated act, IAM owns per Audit's expectation)
"""

from bus.events import (
    EVENT_DIRECTORY_SEARCH,
    EVENT_PARTNER_ACTIVATED,
    EVENT_PARTNER_REJECTED,
    EVENT_PARTNER_SELECTED,
    EVENT_PARTNER_VERIFICATION_STARTED,
)
from bus.registry import HandlerRegistry
from modules.partner.domain.events import (
    DirectorySearchPayload,
    PartnerActivatedPayload,
    PartnerRejectedPayload,
    PartnerSelectedPayload,
    VerificationStartedPayload,
)


def register_handlers(registry: HandlerRegistry) -> None:
    """Register the partner module's produced-event payload models."""
    for event_type, payload_model in (
        (EVENT_PARTNER_VERIFICATION_STARTED, VerificationStartedPayload),
        (EVENT_PARTNER_ACTIVATED, PartnerActivatedPayload),
        (EVENT_PARTNER_REJECTED, PartnerRejectedPayload),
        (EVENT_DIRECTORY_SEARCH, DirectorySearchPayload),
        (EVENT_PARTNER_SELECTED, PartnerSelectedPayload),
    ):
        registry.register_payload_model(event_type, payload_model)
