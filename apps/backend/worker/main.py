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

No scheduler yet: the APScheduler scaffold from issue #16 lands with the first
scheduled job (roadmap Phase 12/13) and is deliberately absent here.
"""

import asyncio
import contextlib
import signal
from collections.abc import Callable

from sqlalchemy.ext.asyncio import create_async_engine

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
from modules.settlement.adapters import register_handlers as settlement_register_handlers

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


async def run_worker_until_stopped(
    stop_event: asyncio.Event,
    settings: Settings | None = None,
    config: DispatcherConfig = DEFAULT_DISPATCHER_CONFIG,
) -> None:
    """Run the dispatcher loop until ``stop_event`` is set, draining inflight claims.

    Resolves the shared env-driven ``Settings`` once, builds the ``HandlerRegistry``
    at the composition root, creates the engine, discovers the module outboxes
    (list-based over ``MODULE_SCHEMAS``, issue #16), and drives ``run_poll_loop``.
    The loop honours ``stop_event`` between passes, so the pass in flight finishes
    and inflight claims already under delivery drain before this coroutine returns
    (ADR-0002 §2, issue #16 user story 19). The engine is always disposed.
    """
    resolved_settings = settings if settings is not None else get_settings()
    registry = build_registry()
    engine = create_async_engine(resolved_settings.database_url)
    try:
        async with engine.connect() as connection:
            tables: tuple[OutboxTable, ...] = await discover_outbox_tables(
                connection, MODULE_SCHEMAS
            )
        await run_poll_loop(engine, tables, registry, config, stop_event=stop_event)
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
