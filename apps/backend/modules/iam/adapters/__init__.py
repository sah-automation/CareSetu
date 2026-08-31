"""MOD-001: event handlers for the ``iam`` module (coding-standards §2).

``register_handlers`` is the composition-root seam (PHASE-1 T4, #30):
the worker entrypoint calls it to register this module's handlers on
the shared ``HandlerRegistry``. PHASE-5 T03 (#248) registers the
activation-gated role consumers: ``partner.activated`` grants the
``partner`` role to the partner's identity, and ``partner.rejected`` /
``credential.invalidated`` suspend it, so access follows verification
state (ADR-0008). The identity is fixed at registration (ADR-0010) and
rides each event payload, so this consumer never reads the partner
schema (ADR-0003 module isolation).

Every handler is idempotent (ADR-0002 §3): its ``consumed_events`` ledger
row is written in the SAME transaction as the role grant/suspend, so
replaying a delivered ``event_id`` is a no-op and a crash rolls both back
together.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TypeVar

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import get_settings
from bus.envelope import Envelope
from bus.events import (
    EVENT_CREDENTIAL_INVALIDATED,
    EVENT_PARTNER_ACTIVATED,
    EVENT_PARTNER_REJECTED,
)
from bus.ledger import record_consumed_event
from bus.registry import HandlerRegistry
from modules.iam.domain.consumer import (
    CredentialInvalidatedPayload,
    PartnerActivatedPayload,
    PartnerRejectedPayload,
)
from modules.iam.session_facade import (
    grant_partner_role,
    suspend_partner_role,
)

_T = TypeVar("_T", bound=BaseModel)

_IAM_SCHEMA = "iam"


def _delivery_engine() -> AsyncEngine:
    """A short-lived engine for one delivery (the round-trip harness pattern).

    The composition root passes only the registry to ``register_handlers``,
    so the handler resolves the shared settings lazily at delivery time -
    registration stays connection-free for unit tests and the worker boot.
    ``NullPool`` matches every other short-lived engine in the repo.
    """
    return create_async_engine(get_settings().database_url, poolclass=NullPool)


async def _run_handler(
    envelope: Envelope[BaseModel],
    payload_class: type[_T],
    handler_fn: Callable[[AsyncConnection, _T], Awaitable[None]],
    handler_name: str,
) -> None:
    """Run an event handler with the standard engine-lifecycle boilerplate.

    Handles payload extraction, engine creation, ``record_consumed_event``,
    delivery check, and engine disposal. The callback does the unique work.
    """
    raw_payload = envelope.payload
    payload = (
        raw_payload
        if isinstance(raw_payload, payload_class)
        else payload_class.model_validate(raw_payload.model_dump())
    )
    engine = _delivery_engine()
    try:
        async with engine.begin() as connection:
            delivered = await record_consumed_event(
                connection,
                _IAM_SCHEMA,
                envelope,
                handler_result={"handler": handler_name},
            )
            if not delivered:
                return
            await handler_fn(connection, payload)
    finally:
        await engine.dispose()


def register_handlers(registry: HandlerRegistry) -> None:
    """Register the iam module's event handlers + payload models."""
    # MOD-001 owns the payload mirrors for the partner lifecycle events it
    # consumes (the consumer owns the model, cf. audit's ``register_payload_model``):
    # the dispatcher reconstructs a claimed ``partner.activated`` /
    # ``partner.rejected`` / ``credential.invalidated`` outbox row with them
    # before fan-out, so a typed payload - never a raw dict - reaches the handler.
    for event_type, payload_model in (
        (EVENT_PARTNER_ACTIVATED, PartnerActivatedPayload),
        (EVENT_PARTNER_REJECTED, PartnerRejectedPayload),
        (EVENT_CREDENTIAL_INVALIDATED, CredentialInvalidatedPayload),
    ):
        registry.register_payload_model(event_type, payload_model)

    async def grant_or_restore_partner_role(envelope: Envelope[BaseModel]) -> None:
        """Consume ``partner.activated``: grant the ``partner`` role.

        Ledger first, grant second, one transaction: a redelivered
        ``event_id`` finds its ledger row and skips the grant (at-least-once);
        the grant is itself idempotent, so an already-Active row is a no-op.
        """

        async def _impl(connection: AsyncConnection, payload: PartnerActivatedPayload) -> None:
            await grant_partner_role(connection, payload.identity_id)

        await _run_handler(
            envelope,
            PartnerActivatedPayload,
            _impl,
            "grant_partner_role",
        )

    async def suspend_partner_role_on_rejection(envelope: Envelope[BaseModel]) -> None:
        """Consume ``partner.rejected``: suspend the ``partner`` role.

        Ledger first, suspend second, one transaction: a redelivered
        ``event_id`` skips the suspend; the suspend is idempotent even when no
        grant row exists (a never-activated partner).
        """

        async def _impl(connection: AsyncConnection, payload: PartnerRejectedPayload) -> None:
            await suspend_partner_role(connection, payload.identity_id)

        await _run_handler(
            envelope,
            PartnerRejectedPayload,
            _impl,
            "suspend_partner_role",
        )

    async def suspend_partner_role_on_invalidated(envelope: Envelope[BaseModel]) -> None:
        """Consume ``credential.invalidated``: suspend the ``partner`` role.

        The deactivation path (spec phase-5 "Deactivation"): an Active
        partner's re-verification failed or the grace window lapsed, so the
        IAM role is suspended to match the credential no longer being valid.
        """

        async def _impl(connection: AsyncConnection, payload: CredentialInvalidatedPayload) -> None:
            await suspend_partner_role(connection, payload.identity_id)

        await _run_handler(
            envelope,
            CredentialInvalidatedPayload,
            _impl,
            "suspend_partner_role",
        )

    registry.register(EVENT_PARTNER_ACTIVATED, grant_or_restore_partner_role)
    registry.register(EVENT_PARTNER_REJECTED, suspend_partner_role_on_rejection)
    registry.register(EVENT_CREDENTIAL_INVALIDATED, suspend_partner_role_on_invalidated)
