"""PHASE-1 T2b: synchronous dispatch/fan-out contract (ticket #20).

Pins the in-process fan-out step from issue #16/ADR-0002 without a database:
every handler registered for the ``event_type`` is invoked with the envelope,
handler-return-without-exception is a success, one failing handler does not
stop its siblings, and the dispatcher hands handlers nothing but the envelope
(transport-only - it never reads subscriber ledgers).
"""

from uuid import uuid4

from pydantic import BaseModel

from bus.dispatch import HandlerOutcome, dispatch
from bus.envelope import Envelope
from bus.registry import HandlerRegistry


class SamplePayload(BaseModel):
    sample_field: int


def _envelope() -> Envelope[SamplePayload]:
    return Envelope[SamplePayload](
        event_id=uuid4(),
        event_type="phase1.round_trip",
        producer="phase1",
        payload=SamplePayload(sample_field=1),
    )


async def test_dispatch_invokes_every_handler_with_the_envelope() -> None:
    registry = HandlerRegistry()
    received: list[Envelope[BaseModel]] = []

    async def handler_a(envelope: Envelope[BaseModel]) -> None:
        received.append(envelope)

    async def handler_b(envelope: Envelope[BaseModel]) -> None:
        received.append(envelope)

    registry.register("phase1.round_trip", handler_a)
    registry.register("phase1.round_trip", handler_b)
    envelope = _envelope()

    result = await dispatch(registry, envelope)

    assert received == [envelope, envelope]
    assert result.event_type == "phase1.round_trip"
    assert len(result.outcomes) == 2
    assert result.all_succeeded


async def test_handler_returning_without_exception_is_success() -> None:
    registry = HandlerRegistry()

    async def successful_handler(envelope: Envelope[BaseModel]) -> None:
        return None

    registry.register("phase1.round_trip", successful_handler)

    result = await dispatch(registry, _envelope())

    assert result.outcomes == (
        HandlerOutcome(handler_name="successful_handler", success=True, error=None),
    )
    assert result.all_succeeded


async def test_one_failing_handler_does_not_stop_sibling_handlers() -> None:
    registry = HandlerRegistry()
    order: list[str] = []

    async def failing_handler(envelope: Envelope[BaseModel]) -> None:
        order.append("failing")
        raise RuntimeError("boom")

    async def healthy_handler(envelope: Envelope[BaseModel]) -> None:
        order.append("healthy")

    registry.register("phase1.round_trip", failing_handler)
    registry.register("phase1.round_trip", healthy_handler)

    result = await dispatch(registry, _envelope())

    assert order == ["failing", "healthy"]
    assert [outcome.success for outcome in result.outcomes] == [False, True]
    failed = result.outcomes[0]
    assert failed.handler_name == "failing_handler"
    assert failed.error == "RuntimeError: boom"
    assert not result.all_succeeded


async def test_dispatch_with_no_handlers_is_a_vacuous_success() -> None:
    result = await dispatch(HandlerRegistry(), _envelope())

    assert result.outcomes == ()
    assert result.all_succeeded


async def test_dispatch_hands_handlers_nothing_but_the_envelope() -> None:
    registry = HandlerRegistry()
    received: list[tuple[tuple[object, ...], dict[str, object]]] = []

    async def spy_handler(*args: object, **kwargs: object) -> None:
        received.append((args, kwargs))

    registry.register("phase1.round_trip", spy_handler)
    envelope = _envelope()

    await dispatch(registry, envelope)

    assert received == [((envelope,), {})]
