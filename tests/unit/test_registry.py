"""PHASE-1 T2b: HandlerRegistry routing contract (ticket #20).

Pins the fan-out mapping from issue #16/ADR-0002 without a database: one
``event_type`` routes to all its registered handlers in registration order,
unknown event types route to none, keys follow the registry ``domain.action``
shape, and a handler cannot be registered twice for the same event type.
"""

import pytest
from pydantic import BaseModel

from bus.envelope import Envelope
from bus.registry import HandlerRegistry


class SamplePayload(BaseModel):
    sample_field: int


async def _handler_a(envelope: Envelope[BaseModel]) -> None:
    """No-op handler used only to exercise routing."""


async def _handler_b(envelope: Envelope[BaseModel]) -> None:
    """No-op handler used only to exercise routing."""


def test_handlers_for_returns_all_registered_in_order() -> None:
    registry = HandlerRegistry()

    registry.register("phase1.round_trip", _handler_a)
    registry.register("phase1.round_trip", _handler_b)

    assert registry.handlers_for("phase1.round_trip") == (_handler_a, _handler_b)


def test_handlers_for_unknown_event_type_is_empty() -> None:
    assert HandlerRegistry().handlers_for("phase1.round_trip") == ()


def test_event_types_route_independently() -> None:
    registry = HandlerRegistry()

    registry.register("patient.registered", _handler_a)
    registry.register("pre_summary.low_confidence", _handler_b)

    assert registry.handlers_for("patient.registered") == (_handler_a,)
    assert registry.handlers_for("pre_summary.low_confidence") == (_handler_b,)


def test_register_rejects_non_domain_action_event_type() -> None:
    registry = HandlerRegistry()

    for invalid in ("no_dot", "Domain.action", "domain.Action", "9dom.action"):
        with pytest.raises(ValueError):
            registry.register(invalid, _handler_a)


def test_register_same_handler_twice_for_one_event_type_is_rejected() -> None:
    registry = HandlerRegistry()

    registry.register("phase1.round_trip", _handler_a)

    with pytest.raises(ValueError):
        registry.register("phase1.round_trip", _handler_a)


def test_register_same_handler_for_different_event_types_is_allowed() -> None:
    registry = HandlerRegistry()

    registry.register("phase1.round_trip", _handler_a)
    registry.register("patient.registered", _handler_a)

    assert registry.handlers_for("phase1.round_trip") == (_handler_a,)
    assert registry.handlers_for("patient.registered") == (_handler_a,)


def test_payload_model_registration_round_trips() -> None:
    registry = HandlerRegistry()

    registry.register_payload_model("phase1.round_trip", SamplePayload)

    assert registry.payload_model_for("phase1.round_trip") is SamplePayload


def test_payload_model_for_unknown_event_type_is_none() -> None:
    assert HandlerRegistry().payload_model_for("phase1.round_trip") is None


def test_register_payload_model_rejects_non_domain_action_event_type() -> None:
    registry = HandlerRegistry()

    with pytest.raises(ValueError):
        registry.register_payload_model("no_dot", SamplePayload)


def test_register_payload_model_twice_for_one_event_type_is_rejected() -> None:
    registry = HandlerRegistry()

    registry.register_payload_model("phase1.round_trip", SamplePayload)

    with pytest.raises(ValueError):
        registry.register_payload_model("phase1.round_trip", SamplePayload)


def test_payload_model_registration_is_independent_per_event_type() -> None:
    registry = HandlerRegistry()

    registry.register_payload_model("phase1.round_trip", SamplePayload)

    assert registry.payload_model_for("phase1.round_trip") is SamplePayload
    assert registry.payload_model_for("patient.registered") is None
