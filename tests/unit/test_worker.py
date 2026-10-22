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
stop discipline around the poll loop. PHASE-14A B8 (#726) adds the second
periodic job - the ``error-buffer-drain`` interval pass that empties the gateway
seam's in-process capture buffer into the observability schema - and the callback
that persists it through the module facade. PHASE-14A B9 (#727) adds the third:
the ``http-counter-fold`` interval pass that adds the gateway's per-minute request
buckets onto ``observability_http_minute``, with its OWN failure latch so one
drain's outage cannot speak for the other.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from apscheduler.job import Job
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

import worker.main as worker_main
from app.config import Settings
from bus.bootstrap import MODULE_SCHEMAS
from bus.registry import HandlerRegistry
from modules.observability.facade import ErrorDrainReport, HttpCounterDrainReport
from modules.partner.facade import PartnerFacade


def _job(scheduler: AsyncIOScheduler, job_id: str) -> Job:
    """One registered job by id - asserted by identity rather than by list order.

    Adding a job to the scheduler must not be allowed to renumber the existing
    ones, so these tests never reach for ``get_jobs()[0]``.
    """
    matches = [job for job in scheduler.get_jobs() if job.id == job_id]
    assert len(matches) == 1, f"expected exactly one {job_id!r} job, got {len(matches)}"
    return matches[0]


async def _unreachable_dispose() -> None:
    """A dispose that must never run: it stands in for the worker's own engine."""
    raise AssertionError("a caller-supplied engine must not be disposed by a drain pass")


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
    """#315: the scheduler ships the sweep job on the configured cadence."""
    scheduler = worker_main.build_scheduler(Settings())

    job = _job(scheduler, "credential-expiry-sweep")
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

    job = _job(scheduler, "credential-expiry-sweep")
    next_fire = job.trigger.get_next_fire_time(None, datetime(2026, 9, 5, 12, 0, tzinfo=UTC))
    assert next_fire == datetime(2026, 9, 6, 3, 0, tzinfo=UTC)


def test_build_scheduler_registers_the_error_drain_on_an_interval() -> None:
    """B8 #726: the drain is an INTERVAL job, not a cron.

    It drains in-process buffer state rather than a calendar period, so it has to
    fire on a cadence a cron expression cannot express - and a buffer that waited
    for the next night to drain would not be a live error feed.
    """
    scheduler = worker_main.build_scheduler(Settings(error_capture_enabled=True))

    job = _job(scheduler, "error-buffer-drain")
    assert isinstance(job.trigger, IntervalTrigger)
    assert job.func is worker_main._run_error_drain
    assert job.max_instances == 1
    assert job.coalesce
    assert job.trigger.interval == timedelta(seconds=30)


def test_build_scheduler_honours_a_configured_drain_interval() -> None:
    """B8 #726: the drain cadence is configuration (coding-standards §9.1)."""
    scheduler = worker_main.build_scheduler(
        Settings(error_capture_enabled=True, error_drain_interval_seconds=5)
    )

    assert _job(scheduler, "error-buffer-drain").trigger.interval == timedelta(seconds=5)


def test_build_scheduler_skips_the_error_drain_when_the_capture_gate_is_off() -> None:
    """#753: gate off means the pre-#726 scheduler - the drain job never registers.

    An empty buffer drained every 30 seconds is pure cost, and the gate-off
    posture has to be exactly "as if the feature were not there" - so the
    HTTP-counter fold (a different feature, with its own gate) is skipped too
    while its gate is off.
    """
    scheduler = worker_main.build_scheduler(Settings())

    assert not any(job.id == "error-buffer-drain" for job in scheduler.get_jobs())
    assert not any(job.id == "http-counter-fold" for job in scheduler.get_jobs())
    _job(scheduler, "credential-expiry-sweep")


async def test_drain_callback_persists_the_buffer_through_the_module_facade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B8 #726: the drain reaches the module through its facade, never around it.

    The worker's one composition-root rule (coding-standards §2, ADR-0003) is that a
    module's writes go through ``modules.observability.facade``; importing the
    adapter directly here would open a second path into this module's schema.
    """
    seen: list[object] = []

    async def fake_drain(engine: object) -> ErrorDrainReport:
        seen.append(engine)
        return ErrorDrainReport(written=2, frequencies=1, dropped=0)

    engine = SimpleNamespace(dispose=_unreachable_dispose)
    monkeypatch.setattr(worker_main, "drain_error_buffer", fake_drain)

    await worker_main._run_error_drain(engine=engine)

    assert seen == [engine]


async def test_drain_callback_builds_and_disposes_its_own_engine_when_given_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B8 #726: a supplied engine outlives the pass; an owned one must not.

    The scheduled job hands over the worker's engine, which the worker still needs.
    A call with no engine builds its own and disposes it, so a standalone ``python
    -m worker.main`` - where the scheduler takes the default callback - cannot leak a
    pool every interval.
    """
    disposed = 0

    async def fake_drain(engine: object) -> ErrorDrainReport:
        return ErrorDrainReport(written=0, frequencies=0, dropped=0)

    async def dispose() -> None:
        nonlocal disposed
        disposed += 1

    monkeypatch.setattr(worker_main, "drain_error_buffer", fake_drain)
    monkeypatch.setattr(
        worker_main, "create_async_engine", lambda url: SimpleNamespace(dispose=dispose)
    )

    await worker_main._run_error_drain()

    assert disposed == 1


async def test_drain_callback_swallows_a_failed_pass_and_keeps_the_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B8 #726: a transient database blip must not kill the recurring job.

    Unlike the sweep, a missed drain is not a correctness risk - the records are
    still buffered, so the next pass retries them - and letting the exception reach
    APScheduler would kill the job over a blip the buffer rides out.
    """

    async def exploding_drain(engine: object) -> ErrorDrainReport:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(worker_main, "drain_error_buffer", exploding_drain)

    await worker_main._run_error_drain(engine=SimpleNamespace(dispose=_unreachable_dispose))


async def test_a_drain_failing_on_every_firing_logs_the_transition_not_a_flood(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B8 #726: the feed going blind must be visible without drowning the logs.

    A database down for an hour fires this job ~120 times. One line at the transition
    and one recovery line naming the window is the difference between a readable log
    and a traceback flood - and the recovery line is what tells an operator the error
    stream has a hole in it, which a lone "it failed" line does not.
    """
    monkeypatch.setattr(worker_main, "_error_drain_latch", worker_main._DrainLatch())
    engine = SimpleNamespace(dispose=_unreachable_dispose)

    async def exploding_drain(candidate: object) -> ErrorDrainReport:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(worker_main, "drain_error_buffer", exploding_drain)
    with caplog.at_level(logging.WARNING):
        for _ in range(3):
            await worker_main._run_error_drain(engine=engine)
        assert caplog.text.count("drain pass failed") == 1
        assert "3 consecutive pass(es)" in caplog.text

        async def healthy_drain(candidate: object) -> ErrorDrainReport:
            return ErrorDrainReport(written=1, frequencies=1, dropped=0)

        monkeypatch.setattr(worker_main, "drain_error_buffer", healthy_drain)
        await worker_main._run_error_drain(engine=engine)

    assert "recovered after 3 failed pass(es)" in caplog.text
    assert "unwritten for that window" in caplog.text
    # The counter resets, so a later outage gets its own first-failure traceback.
    assert worker_main._error_drain_latch.failures == 0


# ------------------------------------------------- B9 #727: the HTTP-counter fold


def test_build_scheduler_registers_the_counter_fold_on_an_interval() -> None:
    """B9 #727: the fold is an INTERVAL job on the counter's own grain.

    An interval rather than a cron because it folds in-process state, and the
    default cadence is one minute because that is the grain - which is what bounds
    the write cost at one row per route per minute.
    """
    scheduler = worker_main.build_scheduler(Settings(http_counter_enabled=True))

    job = _job(scheduler, "http-counter-fold")
    assert isinstance(job.trigger, IntervalTrigger)
    assert job.func is worker_main._run_http_counter_drain
    assert job.max_instances == 1
    assert job.coalesce
    assert job.trigger.interval == timedelta(seconds=60)


def test_build_scheduler_honours_a_configured_counter_fold_interval() -> None:
    """B9 #727: the fold cadence is configuration (coding-standards §9.1)."""
    scheduler = worker_main.build_scheduler(
        Settings(http_counter_enabled=True, http_counter_drain_interval_seconds=15)
    )

    assert _job(scheduler, "http-counter-fold").trigger.interval == timedelta(seconds=15)


async def test_the_counter_fold_keeps_its_own_failure_latch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B9 #727: a failing error drain must not be reported as a failing counter fold.

    The two write different tables with different loss semantics - the error feed's
    loss is a countable occurrence, the counter's would inflate throughput
    permanently - so one shared latch would hide a stopped fold behind a healthy
    drain, or the reverse. Proven by BEHAVIOUR rather than by comparing two module
    attributes, because "they are different objects" is only worth anything if
    driving one does not move the other.
    """
    monkeypatch.setattr(worker_main, "_error_drain_latch", worker_main._DrainLatch())
    monkeypatch.setattr(worker_main, "_http_counter_drain_latch", worker_main._DrainLatch())
    engine = SimpleNamespace(dispose=_unreachable_dispose)

    async def exploding(candidate: object) -> Any:
        raise RuntimeError("database unavailable")

    async def healthy(candidate: object) -> HttpCounterDrainReport:
        return HttpCounterDrainReport(series=1, requests=4, dropped=0)

    monkeypatch.setattr(worker_main, "drain_error_buffer", healthy)
    monkeypatch.setattr(worker_main, "drain_http_counter", exploding)
    await worker_main._run_http_counter_drain(engine=engine)

    assert worker_main._http_counter_drain_latch.failures == 1
    assert worker_main._error_drain_latch.failures == 0


async def test_counter_fold_callback_persists_through_the_module_facade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B9 #727: the fold reaches the module through its facade, never around it."""
    seen: list[object] = []

    async def fake_fold(engine: object) -> HttpCounterDrainReport:
        seen.append(engine)
        return HttpCounterDrainReport(series=3, requests=9400, dropped=0)

    engine = SimpleNamespace(dispose=_unreachable_dispose)
    monkeypatch.setattr(worker_main, "drain_http_counter", fake_fold)

    await worker_main._run_http_counter_drain(engine=engine)

    assert seen == [engine]


async def test_counter_fold_builds_and_disposes_its_own_engine_when_given_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A supplied engine outlives the pass; an owned one must not."""
    disposed = 0

    async def fake_fold(engine: object) -> HttpCounterDrainReport:
        return HttpCounterDrainReport(series=0, requests=0, dropped=0)

    async def dispose() -> None:
        nonlocal disposed
        disposed += 1

    monkeypatch.setattr(worker_main, "drain_http_counter", fake_fold)
    monkeypatch.setattr(
        worker_main, "create_async_engine", lambda url: SimpleNamespace(dispose=dispose)
    )

    await worker_main._run_http_counter_drain()

    assert disposed == 1


async def test_counter_fold_swallows_a_failed_pass_so_the_job_survives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A transient blip must not kill the recurring job; the deltas retry next pass."""

    async def exploding_fold(engine: object) -> HttpCounterDrainReport:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(worker_main, "drain_http_counter", exploding_fold)

    await worker_main._run_http_counter_drain(engine=SimpleNamespace(dispose=_unreachable_dispose))


async def test_a_counter_fold_failing_on_every_firing_logs_the_transition_not_a_flood(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B9 #727: throughput going unwritten must be visible without drowning the logs.

    The recovery line is the part that matters - it names the window in which the
    counter was not being written, which is the gap the capture-liveness read will
    later have to answer for.
    """
    monkeypatch.setattr(worker_main, "_http_counter_drain_latch", worker_main._DrainLatch())
    engine = SimpleNamespace(dispose=_unreachable_dispose)

    async def exploding_fold(candidate: object) -> HttpCounterDrainReport:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(worker_main, "drain_http_counter", exploding_fold)
    with caplog.at_level(logging.WARNING):
        for _ in range(3):
            await worker_main._run_http_counter_drain(engine=engine)
        assert caplog.text.count("fold pass failed") == 1
        assert "3 consecutive pass(es)" in caplog.text

        async def healthy_fold(candidate: object) -> HttpCounterDrainReport:
            return HttpCounterDrainReport(series=1, requests=4, dropped=0)

        monkeypatch.setattr(worker_main, "drain_http_counter", healthy_fold)
        await worker_main._run_http_counter_drain(engine=engine)

    assert "recovered after 3 failed pass(es)" in caplog.text
    assert worker_main._http_counter_drain_latch.failures == 0


async def test_the_counter_fold_log_line_reports_both_figures(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B9 #727: buckets and requests say different things, and the line needs both.

    "wrote 9400 rows" would describe a per-request design this ticket exists not to
    build; "wrote 12 buckets covering 9400 requests" is the whole claim in one line.
    """
    logged = False

    async def fake_fold(engine: object) -> HttpCounterDrainReport:
        nonlocal logged
        logged = True
        return HttpCounterDrainReport(series=12, requests=9400, dropped=0)

    monkeypatch.setattr(worker_main, "drain_http_counter", fake_fold)
    with caplog.at_level(logging.INFO):
        await worker_main._run_http_counter_drain(
            engine=SimpleNamespace(dispose=_unreachable_dispose)
        )

    assert logged
    assert "wrote 12 bucket(s) covering 9400 request(s)" in caplog.text


async def test_a_quiet_counter_logs_nothing(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Zero series is not a pass that wrote nothing to report - it is nothing.

    A line every interval for an idle system is how a log gets read past the one
    line that mattered.
    """

    async def quiet_fold(engine: object) -> HttpCounterDrainReport:
        return HttpCounterDrainReport(series=0, requests=0, dropped=0)

    monkeypatch.setattr(worker_main, "drain_http_counter", quiet_fold)
    with caplog.at_level(logging.INFO):
        await worker_main._run_http_counter_drain(
            engine=SimpleNamespace(dispose=_unreachable_dispose)
        )

    assert "bucket(s) covering" not in caplog.text


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
    # ``**_`` so this fake tolerates the callbacks the composition root threads
    # through (the B8 error-drain job) without naming them: these tests are about
    # the start/stop contract, and the drain's own registration is asserted in the
    # build_scheduler tests above.
    monkeypatch.setattr(worker_main, "build_scheduler", lambda settings, **_: scheduler)

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
    monkeypatch.setattr(worker_main, "build_scheduler", lambda settings, **_: scheduler)

    with pytest.raises(RuntimeError, match="db unreachable"):
        await worker_main.run_worker_until_stopped(stop_event, settings=Settings())

    assert scheduler.started
    assert scheduler.shutdown_calls == 1
    assert engine.disposed
