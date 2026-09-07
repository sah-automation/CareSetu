"""PHASE-1 T4 (#30): worker composition root + graceful shutdown.

The worker is the system's composition root (issue #16): it wires every module's
``register_handlers`` into one ``HandlerRegistry`` - modules never import each
other, infra imports modules only here - and runs the dispatcher poll loop until
a stop is requested, draining inflight claims on the way out. These tests pin the
composition (every module's ``register_handlers`` is invoked exactly once) and
the drain/shutdown path (a set ``stop_event`` makes the worker exit after handing
the event through to ``run_poll_loop``; the loop-level drain itself is proven
against the native PostgreSQL in ``tests/integration/test_dispatcher.py``).
PHASE-6 T04a (#315) also pins the periodic-job scheduler seam: exactly one
``credential-expiry-sweep`` job on the configured cron (UTC), and the start /
stop discipline around the poll loop.
"""

from __future__ import annotations

import asyncio
import signal
from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from apscheduler.triggers.cron import CronTrigger

import worker.main as worker_main
from app.config import Settings
from bus.bootstrap import MODULE_SCHEMAS
from bus.registry import HandlerRegistry
from modules.partner.facade import PartnerFacade


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


def test_build_scheduler_registers_the_sweep_on_the_configured_cron() -> None:
    """#315: the scheduler ships exactly one sweep job on the configured cadence."""
    scheduler = worker_main.build_scheduler(Settings())

    jobs = scheduler.get_jobs()
    assert len(jobs) == 1
    job = jobs[0]
    assert job.id == "credential-expiry-sweep"
    assert job.max_instances == 1
    assert job.coalesce
    assert isinstance(job.trigger, CronTrigger)
    assert job.func is worker_main._run_credential_sweep

    # "30 1 * * *" -> 01:30 UTC daily.
    next_fire = job.trigger.get_next_fire_time(None, datetime(2026, 9, 5, 12, 0, tzinfo=UTC))
    assert next_fire == datetime(2026, 9, 6, 1, 30, tzinfo=UTC)


def test_build_scheduler_honours_a_configured_cadence() -> None:
    """#315: an env-driven cron overrides the default sweep time."""
    scheduler = worker_main.build_scheduler(Settings(partner_credential_sweep_cron="0 3 * * *"))

    job = scheduler.get_jobs()[0]
    next_fire = job.trigger.get_next_fire_time(None, datetime(2026, 9, 5, 12, 0, tzinfo=UTC))
    assert next_fire == datetime(2026, 9, 6, 3, 0, tzinfo=UTC)


def test_build_sweep_facade_composes_without_an_iam_facade() -> None:
    """WI-3 (#336): the daily sweep's partner stack carries no iam facade.

    The sweep close-out never registers a partner, so composing the sweep facade
    must not build an iam facade - no SMS adapter is constructed and no MFA
    secret is read on this path. The sweep facade's registration seam is left
    unset; a misuse that calls ``register`` fails loudly with
    ``PartnerIamUnavailableError`` (pinned at unit and integration level).
    """

    class _FakeEngine:
        pass

    sweep_facade = worker_main._build_sweep_facade(Settings(), _FakeEngine())

    assert isinstance(sweep_facade, PartnerFacade)
    assert sweep_facade._registration._iam is None


@pytest.mark.asyncio
async def test_sweep_callback_runs_the_partner_expiry_close_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#316: the daily sweep callback runs the T04b close-out through the facade."""

    class _FakeFacade:
        def __init__(self) -> None:
            self.swept = False

        async def close_out_expired_credentials(self) -> list[int]:
            self.swept = True
            return [1, 2]

    engine = _FakeEngine()
    facade = _FakeFacade()
    monkeypatch.setattr(worker_main, "create_async_engine", lambda url: engine)
    monkeypatch.setattr(worker_main, "_build_sweep_facade", lambda settings, eng: facade)

    await worker_main._run_credential_sweep()

    assert facade.swept
    assert engine.disposed


@pytest.mark.asyncio
async def test_sweep_callback_disposes_the_engine_when_the_pass_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#316: a failing close-out still disposes the sweep's dedicated engine."""

    class _FailingFacade:
        async def close_out_expired_credentials(self) -> list[int]:
            raise RuntimeError("db unreachable")

    engine = _FakeEngine()
    monkeypatch.setattr(worker_main, "create_async_engine", lambda url: engine)
    monkeypatch.setattr(
        worker_main,
        "_build_sweep_facade",
        lambda settings, eng: _FailingFacade(),
    )

    with pytest.raises(RuntimeError, match="db unreachable"):
        await worker_main._run_credential_sweep()

    assert engine.disposed


class _FakeScheduler:
    """A DB-free scheduler stand-in that records start/shutdown only."""

    def __init__(self) -> None:
        self.started = False
        self.shutdown_calls = 0

    def start(self) -> None:
        self.started = True

    def shutdown(self, wait: bool = False) -> None:
        self.shutdown_calls += 1


async def test_run_worker_until_stopped_starts_and_stops_the_scheduler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stop_event = asyncio.Event()
    stop_event.set()
    engine = _FakeEngine()
    scheduler = _FakeScheduler()

    async def fake_discover(connection: object, schemas: object) -> tuple[object, ...]:
        return ()

    async def fake_poll(
        engine: object,
        tables: object,
        registry: object,
        config: object,
        stop_event: asyncio.Event | None = None,
    ) -> None:
        return None

    monkeypatch.setattr(worker_main, "create_async_engine", lambda url: engine)
    monkeypatch.setattr(worker_main, "discover_outbox_tables", fake_discover)
    monkeypatch.setattr(worker_main, "run_poll_loop", fake_poll)
    monkeypatch.setattr(worker_main, "build_scheduler", lambda settings: scheduler)

    await worker_main.run_worker_until_stopped(stop_event, settings=Settings())

    assert scheduler.started
    assert scheduler.shutdown_calls == 1
    assert engine.disposed


async def test_run_worker_until_stopped_stops_scheduler_when_poll_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A crashing poll loop must not leave the scheduler running (crash-loud path)."""
    stop_event = asyncio.Event()
    engine = _FakeEngine()
    scheduler = _FakeScheduler()

    async def fake_discover(connection: object, schemas: object) -> tuple[object, ...]:
        return ()

    async def fake_poll(
        engine: object,
        tables: object,
        registry: object,
        config: object,
        stop_event: asyncio.Event | None = None,
    ) -> None:
        raise RuntimeError("db unreachable")

    monkeypatch.setattr(worker_main, "create_async_engine", lambda url: engine)
    monkeypatch.setattr(worker_main, "discover_outbox_tables", fake_discover)
    monkeypatch.setattr(worker_main, "run_poll_loop", fake_poll)
    monkeypatch.setattr(worker_main, "build_scheduler", lambda settings: scheduler)

    with pytest.raises(RuntimeError, match="db unreachable"):
        await worker_main.run_worker_until_stopped(stop_event, settings=Settings())

    assert scheduler.started
    assert scheduler.shutdown_calls == 1
    assert engine.disposed
