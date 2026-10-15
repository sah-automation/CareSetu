"""Async worker process: composition root + dispatcher poll loop (PHASE-1 T4, #30).

A separate process (``python -m worker.main`` from ``apps/backend``) that is the
system's composition root (issue #16): it builds the ``HandlerRegistry`` by
calling every module's ``register_handlers`` - modules never import each other;
infra imports modules only here - discovers the module outboxes through the
list-based ``discover_outbox_tables`` over ``MODULE_SCHEMAS``, and runs
``run_poll_loop`` until a stop is requested.

Shutdown (issue #16 user story 19, ADR-0002): SIGTERM and SIGINT set a
``stop_event``. ``run_poll_loop`` honours it between passes, so the pass in
flight finishes - inflight claims already under delivery drain - before the loop
returns and the process exits. The dispatcher is pure transport (ADR-0002 §2):
the worker authors no events and its SQL touches outbox plumbing only.

Periodic jobs (PHASE-6 T04a/T04b, #315/#316): the worker also hosts an
APScheduler ``AsyncIOScheduler`` on the same event loop for the scheduled jobs
ADR-0011's daily-sweep mechanism runs on. Today that is exactly one job - the
daily credential-expiry sweep, registered against the configurable cron in
:func:`build_scheduler`. The sweep callback composes the minimal partner stack
(the facade's iam dependency is optional - WI-3 #336) and runs the
``close_out_expired_credentials`` close-out pass (PHASE-6 T04b, #316); only the
scheduler seam shipped in T04a. Job work stays in-process - no new dependency
beyond APScheduler.

The second periodic job is PHASE-14A B8's error-buffer drain (#726): the gateway
error seam buffers captured server errors in this same process, and the drain
writes them into the ``observability`` schema off every request path. It is an
``IntervalTrigger`` rather than a cron because the buffer is in-process state, not
a calendar job - a sub-minute cadence has no cron spelling, and an error feed that
waits for the next night to drain would not be live. Both jobs share the one
scheduler, so shutdown still has a single place to stop timers.
"""

import asyncio
import contextlib
import logging
import signal
from collections.abc import Awaitable, Callable
from functools import partial

# apscheduler ships no py.typed marker; strict mypy skips it (import-untyped).
from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import-untyped]
from apscheduler.triggers.cron import CronTrigger  # type: ignore[import-untyped]
from apscheduler.triggers.interval import IntervalTrigger  # type: ignore[import-untyped]
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.config import Settings, get_settings
from bus.bootstrap import MODULE_SCHEMAS
from bus.dispatcher import (
    DEFAULT_DISPATCHER_CONFIG,
    DispatcherConfig,
    OutboxTable,
    discover_outbox_tables,
    run_poll_loop,
)
from bus.registry import HandlerRegistry
from modules.audit.adapters import register_handlers as audit_register_handlers
from modules.care.adapters import register_handlers as care_register_handlers
from modules.consent.adapters import register_handlers as consent_register_handlers
from modules.diagnostics.adapters import register_handlers as diagnostics_register_handlers
from modules.fulfillment.adapters import register_handlers as fulfillment_register_handlers
from modules.health.adapters import register_handlers as health_register_handlers
from modules.iam.adapters import register_handlers as iam_register_handlers
from modules.intake.adapters import register_handlers as intake_register_handlers
from modules.notify.adapters import register_handlers as notify_register_handlers
from modules.observability.adapters import register_handlers as observability_register_handlers
from modules.observability.facade import drain_error_buffer
from modules.partner.adapters import register_handlers as partner_register_handlers
from modules.partner.facade import PartnerFacade
from modules.settlement.adapters import register_handlers as settlement_register_handlers
from observability.error_capture import configure_error_capture
from observability.langfuse_client import flush_langfuse, get_langfuse_client
from observability.logging import SERVICE_WORKER, configure_logging
from observability.otel import flush_otel, init_otel, start_span
from observability.sentry import flush_sentry, init_sentry

logger = logging.getLogger(__name__)

# Consecutive failed error-drain passes, so the job logs the TRANSITION rather than
# one identical line per firing. Module state on purpose: the sequence spans passes,
# so there is no object to hang it off, and the scheduler fires this job with
# ``max_instances=1`` on a single event loop, so an int is sufficient and a lock
# would be noise.
_error_drain_failures = 0

# Every module's register_handlers, in MODULE_SCHEMAS order. This is the one
# place infra imports module adapters (coding-standards §2, ADR-0003); a new
# module adds its register_handlers here at the composition root.
_MODULE_REGISTERS: tuple[Callable[[HandlerRegistry], None], ...] = (
    iam_register_handlers,
    partner_register_handlers,
    health_register_handlers,
    consent_register_handlers,
    intake_register_handlers,
    care_register_handlers,
    diagnostics_register_handlers,
    fulfillment_register_handlers,
    settlement_register_handlers,
    notify_register_handlers,
    audit_register_handlers,
    observability_register_handlers,
)


def _assert_registers_mirror_schemas(
    registers: tuple[Callable[[HandlerRegistry], None], ...],
    schemas: tuple[str, ...],
) -> None:
    """Composition-root guard: ``registers`` must mirror ``schemas`` in order.

    Names are declared once in ``bus.bootstrap.MODULE_SCHEMAS`` (issue #47);
    a new module must add its ``register_handlers`` here in that same order.
    Runs at import so a drift between the two lists fails before the process
    boots. Imports stay static - no dynamic ``importlib`` (PHASE-1 T4).
    """
    names = tuple(register.__module__.split(".")[1] for register in registers)
    if names != schemas:
        raise RuntimeError(
            f"_MODULE_REGISTERS no longer mirrors MODULE_SCHEMAS: expected {schemas}, got {names}"
        )


_assert_registers_mirror_schemas(_MODULE_REGISTERS, MODULE_SCHEMAS)


def build_registry() -> HandlerRegistry:
    """Wire every module's ``register_handlers`` into one ``HandlerRegistry``.

    Modules never import each other; the worker imports each module's adapters
    only here (the composition root) to register its event handlers. Phase 1
    modules register nothing, so the returned registry carries no handlers yet.
    """
    registry = HandlerRegistry()
    for register_handlers in _MODULE_REGISTERS:
        register_handlers(registry)
    return registry


def _build_sweep_facade(settings: Settings, engine: AsyncEngine) -> PartnerFacade:
    """Compose the minimal partner stack the daily expiry sweep needs.

    The sweep close-out only touches ``partner_credentials`` /
    ``partner_directory_index`` and writes to the partner outbox. The partner
    facade's iam dependency is OPTIONAL (WI-3, #336): only the register path
    consumes it, so this sweep facade is built from the shared engine alone -
    no iam facade, so no SMS adapter is built and no MFA secret is read on this
    path, and no artifact store, audit or notify facade is required either (a
    sweep emits no OTP and never registers). Composed here rather than in the
    API ``create_app`` so the two processes stay independent composition roots
    (coding-standards §2).
    """
    del settings
    return PartnerFacade(engine=engine)


async def _run_credential_sweep() -> None:
    """Run the daily credential-expiry close-out pass (PHASE-6 T04b, #316).

    ADR-0011's daily close-out job is scheduled by :func:`build_scheduler` on
    ``settings.partner_credential_sweep_cron``; this callback is what the job
    fires (T04a shipped the seam as a stub). It resolves the env-driven
    ``Settings`` once, composes the sweep facade on a dedicated engine, runs the
    ``close_out_expired_credentials`` pass, and disposes the engine - a
    self-contained per-fire composition so daily cadence stays cheap and the
    dispatcher's own engine is never shared into the timer. The pass result is
    logged (info for the lifecycle close-out, exception for operational
    failures - error-handling-observability §2; no PHI, ids only); failures
    then bubble into APScheduler's job error path, and the lazy read-hide keeps
    directory correctness regardless (ADR-0011).
    """
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    # PHASE-14A A3b (#698): the scheduler job runs inside a span so worker
    # activity shows up in traces; the sweep is not request-derived, so it has
    # no traceparent to continue and the span is linked to nothing upstream.
    # No-op when tracing is off, so the periodic job is unchanged.
    with start_span(
        "scheduler.credential_expiry_sweep",
        attributes={"job.name": "credential-expiry-sweep", "job.system": "apscheduler"},
    ):
        try:
            facade = _build_sweep_facade(settings, engine)
            closed = await facade.close_out_expired_credentials()
        except Exception:
            logger.exception(
                "credential-expiry sweep pass failed; lazy read-hide keeps directory correctness"
            )
            raise
        finally:
            await engine.dispose()
    logger.info("credential-expiry sweep pass closed out %d credential(s)", len(closed))


async def _run_error_drain(engine: AsyncEngine | None = None) -> None:
    """Drain this process's captured error buffer into the observability schema.

    PHASE-14A B8 (#726). The counterpart of the gateway error seam: failures were
    appended to a bounded in-process buffer by the requests that raised them, and
    this moves them into ``observability_error_events`` through the module facade,
    off every request path, so a failing request never waits on a telemetry write.

    ``engine`` is the worker's own engine when the scheduled job supplies one, and
    ``None`` when it does not. That is the difference from the daily sweep, which
    builds a per-fire engine: this job fires every few SECONDS rather than daily,
    so a per-fire pool would be built and torn down a hundred times an hour to hold
    a connection for a handful of upserts. Sharing the dispatcher's engine for the
    duration of one short transaction is safe precisely because the pass is brief
    and self-contained - it is the long-lived intake pipeline sharing a pool that
    the sweep avoids, and this is not that.

    An empty buffer is a no-op that opens no connection, because a healthy system
    must not hold a pooled connection to discover there is nothing to report.

    Failures are logged and swallowed, and the first of a run is logged louder. Unlike
    the sweep, a missed drain is not a correctness risk: the records are still
    buffered, so the next pass retries them, and letting the exception reach
    APScheduler would kill the recurring job over a transient database blip while the
    buffer quietly does its job (ADR-0011's read-hide discipline, applied to a write).

    That silence is only safe while the buffer is BOUNDED, and it is worth saying why
    rather than assuming: every swallowed pass leaves the records in memory, so a
    database that is down for an hour accumulates errors that a full buffer then
    discards. A drain failing on every firing is therefore a silent gap in the error
    feed - the table that exists to report the outage would be unwritten during it.
    The recovery line fires when the pass starts succeeding again, naming how long
    the feed was blind, so the gap is at least visible in the logs. It is not an
    ALARM: alerting on reliability lives with the reliability alerts (#734), which
    read the feed this job fills - an alarm here would be the second mechanism
    watching the same condition.
    """
    global _error_drain_failures
    settings = get_settings()
    report = None
    owned = engine is None
    drain_engine = engine if engine is not None else create_async_engine(settings.database_url)
    with start_span(
        "scheduler.observability_error_drain",
        attributes={"job.name": "observability-error-buffer-drain", "job.system": "apscheduler"},
    ):
        try:
            report = await drain_error_buffer(drain_engine)
        except Exception:
            _error_drain_failures += 1
            if _error_drain_failures == 1:
                # One line at the transition, not one per firing: a database down
                # for an hour would otherwise emit 120 identical tracebacks.
                logger.exception(
                    "error-buffer drain pass failed; the records stay buffered and the "
                    "next pass retries them. While this persists the error feed is "
                    "not being written and the buffer is discarding the overflow."
                )
            else:
                logger.warning(
                    "error-buffer drain still failing (%d consecutive pass(es))",
                    _error_drain_failures,
                )
        else:
            if _error_drain_failures:
                logger.warning(
                    "error-buffer drain recovered after %d failed pass(es); the "
                    "error stream was unwritten for that window",
                    _error_drain_failures,
                )
            _error_drain_failures = 0
        finally:
            # Only dispose an engine this function built: the scheduled job's engine
            # belongs to the worker and outlives every pass.
            if owned:
                await drain_engine.dispose()
    if report is not None and report.written:
        logger.info(
            "error-buffer drain wrote %d capture(s) across %d distinct failure(s)",
            report.written,
            report.frequencies,
        )


def build_scheduler(
    settings: Settings,
    *,
    sweep_callback: Callable[[], Awaitable[None]] = _run_credential_sweep,
    drain_callback: Callable[[], Awaitable[None]] = _run_error_drain,
) -> AsyncIOScheduler:
    """Build the worker's periodic-job scheduler (PHASE-6 T04a, #315).

    An ``AsyncIOScheduler`` running on the worker's event loop, registered with
    two periodic jobs. The first is the daily credential-expiry sweep, scheduled
    on ``settings.partner_credential_sweep_cron`` (defaults to the daily 01:30
    cadence of the backup cron, ``deploy/cron``), whose callback is the injectable
    ``sweep_callback`` (defaulting to :func:`_run_credential_sweep`, the T04b
    close-out pass) so the scheduler wiring stays unit-testable.

    The second is PHASE-14A B8's error-buffer drain (#726), on an
    ``IntervalTrigger`` of ``settings.error_drain_interval_seconds``. It is an
    interval rather than a cron because it drains in-process buffer state, not a
    calendar period, and it must reach the module through
    ``modules.observability.facade`` like every other composition-root seam -
    importing ``modules.observability.error_stream`` here would bypass the facade
    that owns this module's only legal write path.

    Both jobs use ``coalesce`` + a fixed job id so late or missed firings cannot
    stack duplicate passes across a sleep, and ``max_instances=1`` so a drain that
    is slower than its interval skips rather than overlaps.
    """
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        sweep_callback,
        CronTrigger.from_crontab(settings.partner_credential_sweep_cron, timezone="UTC"),
        id="credential-expiry-sweep",
        name="daily-credential-expiry-sweep",
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(
        drain_callback,
        IntervalTrigger(seconds=settings.error_drain_interval_seconds),
        id="error-buffer-drain",
        name="observability-error-buffer-drain",
        coalesce=True,
        max_instances=1,
    )
    return scheduler


async def run_worker_until_stopped(
    stop_event: asyncio.Event,
    settings: Settings | None = None,
    config: DispatcherConfig = DEFAULT_DISPATCHER_CONFIG,
) -> None:
    """Run the dispatcher loop until ``stop_event`` is set, draining inflight claims.

    Resolves the shared env-driven ``Settings`` once, builds the ``HandlerRegistry``
    at the composition root, creates the engine, discovers the module outboxes
    (list-based over ``MODULE_SCHEMAS``, issue #16), and drives ``run_poll_loop``.
    The periodic-job ``AsyncIOScheduler`` (PHASE-6 T04a, #315) starts on the same
    event loop and the sweep job is stopped before the engine is disposed. The
    loop honours ``stop_event`` between passes, so the pass in flight finishes and
    inflight claims already under delivery drain before this coroutine returns
    (ADR-0002 §2, issue #16 user story 19). Exceptions from ``run_poll_loop``
    propagate - a worker failing to reach its database crashes loudly. The engine
    and scheduler are always disposed.
    """
    resolved_settings = settings if settings is not None else get_settings()
    # PHASE-14A A1 (#694): configure structured logging once at the worker
    # composition root so the dispatcher's lines are JSON/console-rendered and
    # carry the service identity + trace id. Never raises.
    configure_logging(resolved_settings, service=SERVICE_WORKER)
    # PHASE-14A B8 (#726): size the in-process error-capture buffer from Settings
    # once, here, rather than at each capture site - the seam appends without
    # knowing anything about configuration and the drain reads the same bound when
    # it reports what it dropped.
    configure_error_capture(resolved_settings.error_capture_max_records)
    # PHASE-14A A4 (#696): initialise Sentry error tracking at the worker
    # composition root when SENTRY_DSN is set; a no-op when empty and never a
    # boot failure (init failures are logged and swallowed).
    init_sentry(resolved_settings)
    # PHASE-14A B2 (#700): wire the Langfuse client explicitly at the worker
    # composition root so AI spans raised in this process enrich and export.
    # A no-op (returns None, SDK never imported) when the keys are absent.
    get_langfuse_client(
        resolved_settings.langfuse_public_key,
        resolved_settings.langfuse_secret_key,
        resolved_settings.langfuse_host,
    )
    registry = build_registry()
    engine = create_async_engine(resolved_settings.database_url)
    # PHASE-14A A3a (#697): wire the OTel SDK at the worker composition root and
    # instrument the worker's engine (DB spans) + httpx outbound spans when
    # OTEL_ENABLED is on; inert when off. Never raises.
    init_otel(resolved_settings, service=SERVICE_WORKER, engine=engine)
    scheduler = build_scheduler(
        resolved_settings,
        drain_callback=partial(_run_error_drain, engine=engine),
    )
    try:
        async with engine.connect() as connection:
            tables: tuple[OutboxTable, ...] = await discover_outbox_tables(
                connection, MODULE_SCHEMAS
            )
        scheduler.start()
        try:
            await run_poll_loop(engine, tables, registry, config, stop_event=stop_event)
        finally:
            # The poll loop returned (stop_event set) or raised; stop the
            # scheduler before the engine/loop tear down so no timer wakes after
            # return (wait=False: never block the drain on a mid-fire job).
            scheduler.shutdown(wait=False)
    finally:
        await engine.dispose()
        # PHASE-14A A4 (#696): flush queued Sentry events on shutdown; no-op
        # when Sentry is off.
        flush_sentry()
        # PHASE-14A A3a (#697): force-flush the OTel exporter on shutdown so a
        # Render spin-down does not drop buffered spans; no-op when off.
        flush_otel()
        # PHASE-14A B2 (#700): force-flush buffered Langfuse AI spans on
        # shutdown; no-op when Langfuse is unconfigured.
        flush_langfuse()


def install_signal_handlers(
    stop_event: asyncio.Event,
    loop: asyncio.AbstractEventLoop,
) -> dict[int, Callable[..., None]]:
    """Wire SIGTERM and SIGINT to request a graceful drain.

    The signal just sets ``stop_event``; ``run_poll_loop`` finishes the pass in
    flight (draining inflight claims) before exiting. Returns the installed
    callbacks keyed by signal number so tests can drive the shutdown path without
    delivering an OS signal. ``loop.add_signal_handler`` raises ``NotImplementedError``
    for SIGTERM on Windows, so the wiring falls back to ``signal.signal`` there;
    the production target is the Linux staging VM.
    """

    def request_stop(*_args: object) -> None:
        stop_event.set()

    installed: dict[int, Callable[..., None]] = {}
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, request_stop)
        except (NotImplementedError, RuntimeError):
            signal.signal(sig, request_stop)
        installed[sig] = request_stop
    return installed


def main() -> int:
    """Entrypoint for the worker process (``python -m worker.main``).

    Installs the SIGTERM/SIGINT drain wiring, then runs the dispatcher loop until
    a stop is requested. A SIGINT-only fallback path never raises out.
    """

    async def run() -> None:
        stop_event = asyncio.Event()
        install_signal_handlers(stop_event, asyncio.get_running_loop())
        await run_worker_until_stopped(stop_event)

    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(run())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
