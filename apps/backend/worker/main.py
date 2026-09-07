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
"""

import asyncio
import contextlib
import logging
import signal
from collections.abc import Awaitable, Callable

# apscheduler ships no py.typed marker; strict mypy skips it (import-untyped).
from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import-untyped]
from apscheduler.triggers.cron import CronTrigger  # type: ignore[import-untyped]
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
from modules.partner.adapters import register_handlers as partner_register_handlers
from modules.partner.facade import PartnerFacade
from modules.settlement.adapters import register_handlers as settlement_register_handlers

logger = logging.getLogger(__name__)

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


def build_scheduler(
    settings: Settings,
    *,
    sweep_callback: Callable[[], Awaitable[None]] = _run_credential_sweep,
) -> AsyncIOScheduler:
    """Build the worker's periodic-job scheduler (PHASE-6 T04a, #315).

    An ``AsyncIOScheduler`` running on the worker's event loop, registered with
    exactly one periodic job: the daily credential-expiry sweep, scheduled on
    ``settings.partner_credential_sweep_cron`` (defaults to the daily 01:30
    cadence of the backup cron, ``deploy/cron``). The callback is the injectable
    ``sweep_callback`` (defaulting to :func:`_run_credential_sweep`, the T04b
    close-out pass) so the scheduler wiring stays unit-testable.
    ``coalesce`` + a fixed job id keep late/missed firings from stacking
    duplicate sweeps across a sleep.
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
    registry = build_registry()
    engine = create_async_engine(resolved_settings.database_url)
    scheduler = build_scheduler(resolved_settings)
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
