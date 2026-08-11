"""PHASE-1 T4 (#30): worker composition root + graceful shutdown.

The worker is the system's composition root (issue #16): it wires every module's
``register_handlers`` into one ``HandlerRegistry`` - modules never import each
other, infra imports modules only here - and runs the dispatcher poll loop until
a stop is requested, draining inflight claims on the way out. These tests pin the
composition (every module's ``register_handlers`` is invoked exactly once) and
the drain/shutdown path (a set ``stop_event`` makes the worker exit after handing
the event through to ``run_poll_loop``; the loop-level drain itself is proven
against the native PostgreSQL in ``tests/integration/test_dispatcher.py``).
"""

from __future__ import annotations

import asyncio
import signal
from collections.abc import Callable

import pytest

import worker.main as worker_main
from app.config import Settings
from bus.bootstrap import MODULE_SCHEMAS
from bus.registry import HandlerRegistry


def test_register_guard_mirrors_bootstrap_schemas() -> None:
    """The composition-root guard accepts a matching register set (issue #47)."""
    registers = tuple(_fake_register(name) for name in MODULE_SCHEMAS)

    worker_main._assert_registers_mirror_schemas(registers, MODULE_SCHEMAS)


def test_register_guard_rejects_drift_from_schemas() -> None:
    """A name added to MODULE_SCHEMAS but missing from the register fails (issue #47)."""
    registers = tuple(_fake_register(name) for name in MODULE_SCHEMAS)

    with pytest.raises(RuntimeError, match="MODULE_SCHEMAS"):
        worker_main._assert_registers_mirror_schemas(registers, (*MODULE_SCHEMAS, "future_module"))


def test_register_guard_rejects_missing_register() -> None:
    """A register dropped from the composition root fails the guard (issue #47)."""
    registers = tuple(_fake_register(name) for name in MODULE_SCHEMAS[:-1])

    with pytest.raises(RuntimeError, match="MODULE_SCHEMAS"):
        worker_main._assert_registers_mirror_schemas(registers, MODULE_SCHEMAS)


def test_register_guard_rejects_reordering() -> None:
    """Registers out of MODULE_SCHEMAS order fail the guard (issue #47)."""
    registers = tuple(_fake_register(name) for name in reversed(MODULE_SCHEMAS))

    with pytest.raises(RuntimeError, match="MODULE_SCHEMAS"):
        worker_main._assert_registers_mirror_schemas(registers, MODULE_SCHEMAS)


def _fake_register(name: str) -> Callable[[HandlerRegistry], None]:
    """A ``register_handlers``-shaped callable whose ``__module__`` looks real."""

    def register(_registry: HandlerRegistry) -> None:
        return None

    register.__module__ = f"modules.{name}.adapters"
    return register


def test_build_registry_invokes_every_module_register_handlers_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def spy(name: str) -> Callable[[HandlerRegistry], None]:
        def register(registry: HandlerRegistry) -> None:
            calls.append(name)

        return register

    monkeypatch.setattr(
        worker_main,
        "_MODULE_REGISTERS",
        tuple(spy(name) for name in MODULE_SCHEMAS),
    )

    registry = worker_main.build_registry()

    assert isinstance(registry, HandlerRegistry)
    assert calls == list(MODULE_SCHEMAS)


class _FakeEngine:
    """A DB-free stand-in whose only behaviour is disposing and exposing ``connect``."""

    def __init__(self) -> None:
        self.disposed = False

    def connect(self) -> _FakeConnection:
        return _FakeConnection()

    async def dispose(self) -> None:
        self.disposed = True


class _FakeConnection:
    """An async context manager the ``async with engine.connect()`` block expects."""

    async def __aenter__(self) -> _FakeConnection:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None


async def test_run_worker_until_stopped_drains_and_exits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stop_event = asyncio.Event()
    stop_event.set()
    engine = _FakeEngine()
    polled: dict[str, object] = {}

    async def fake_discover(connection: object, schemas: object) -> tuple[object, ...]:
        return ()

    async def fake_poll(
        engine: object,
        tables: object,
        registry: object,
        config: object,
        stop_event: asyncio.Event | None = None,
    ) -> None:
        polled["stop_event"] = stop_event
        polled["registry"] = registry
        polled["tables"] = tables

    monkeypatch.setattr(worker_main, "create_async_engine", lambda url: engine)
    monkeypatch.setattr(worker_main, "discover_outbox_tables", fake_discover)
    monkeypatch.setattr(worker_main, "run_poll_loop", fake_poll)

    await worker_main.run_worker_until_stopped(stop_event, settings=Settings())

    assert polled["stop_event"] is stop_event
    assert isinstance(polled["registry"], HandlerRegistry)
    assert polled["tables"] == ()
    assert engine.disposed


async def test_install_signal_handlers_wires_sigterm_and_sigint() -> None:
    stop_event = asyncio.Event()

    handlers = worker_main.install_signal_handlers(stop_event, asyncio.get_running_loop())

    assert set(handlers) == {signal.SIGTERM, signal.SIGINT}
    assert not stop_event.is_set()
    handlers[signal.SIGTERM]()
    assert stop_event.is_set()
