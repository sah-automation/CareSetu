"""Issue #944: handler-coverage guard over the composition-root registry.

The dispatcher now deletes an outbox row whose fan-out returns zero outcomes -
a successful delivery to all zero subscribers (ADR-0002: a row is deleted once
every subscriber has handled it). That makes a forgotten subscriber silent:
an event type whose handlers were never registered drains cleanly instead of
erroring. This guard is the tripwire the spec asks for - every event type with
a registered payload model (the transport-level declaration that the type
exists and is produced) must have at least one registered handler, unless it is
consciously listed in ``NO_SUBSCRIBER_EVENT_TYPES`` with a reason. A new event
type that adds a payload model but no handler fails here, forcing the missing
subscriber to be either registered or explicitly declared.
"""

from __future__ import annotations

from bus.events import (
    EVENT_DIRECTORY_SEARCH,
    EVENT_OPERATOR_ACTIVE_CHANGED,
    EVENT_OPERATOR_INVITED,
    EVENT_OPERATOR_TIER_CHANGED,
    EVENT_OTP_SENT,
    EVENT_PATIENT_VERIFIED,
    EVENT_PRESCRIPTION_REJECTED,
    EVENT_PRESCRIPTION_REVIEWED,
)
from worker.main import build_registry

#: Payload-modeled event types with deliberately no registered handler. Each
#: entry is a present-tense fact about the registry, not a licence: a type
#: added here must carry a reason, and a type NOT here must have handlers.
NO_SUBSCRIBER_EVENT_TYPES: frozenset[str] = frozenset(
    {
        # Analytics-only telemetry (internal-modules.md §4.2): no module
        # subscriber exists or is planned.
        EVENT_DIRECTORY_SEARCH,
        # Doc registry declares subscribers (MOD-011 / MOD-010) but no direct
        # handler is registered yet - a known gap, tracked for subscriber work
        # separately from the dispatcher transport fix (#944).
        EVENT_OTP_SENT,
        EVENT_PATIENT_VERIFIED,
        EVENT_OPERATOR_INVITED,
        EVENT_OPERATOR_TIER_CHANGED,
        EVENT_OPERATOR_ACTIVE_CHANGED,
        EVENT_PRESCRIPTION_REVIEWED,
        EVENT_PRESCRIPTION_REJECTED,
    }
)


def test_every_payload_modeled_event_type_has_a_handler_or_is_declared() -> None:
    """The guard: a payload model without handlers must be a declared exception."""
    registry = build_registry()

    modeled_without_handler = frozenset(registry.payload_models) - frozenset(
        registry.event_types_with_handlers
    )
    undeclared = modeled_without_handler - NO_SUBSCRIBER_EVENT_TYPES

    assert not undeclared, (
        "event types with a registered payload model but no handler and no "
        f"NO_SUBSCRIBER_EVENT_TYPES entry: {sorted(undeclared)}. Register the "
        "subscribers' handlers, or declare the type no-subscriber there with a "
        "reason - with zero-outcome rows now deleted, a missing subscriber is "
        "otherwise a silent no-op (issue #944)."
    )


def test_every_declared_no_subscriber_event_type_is_payload_modeled() -> None:
    """The exemption list stays honest in the other direction too.

    A type dropped from the producers (model removed) must leave the exemption
    set, so the list tracks reality rather than accumulating entries.
    """
    registry = build_registry()

    stale = NO_SUBSCRIBER_EVENT_TYPES - frozenset(registry.payload_models)

    assert not stale, (
        f"NO_SUBSCRIBER_EVENT_TYPES entries with no registered payload model: {sorted(stale)}"
    )
