"""MOD-011: event handlers for the ``audit`` module (coding-standards §2).

``register_handlers`` is the composition-root seam (PHASE-1 T4, #30):
the worker entrypoint calls it to register this module's handlers on the
shared ``HandlerRegistry``. PHASE-4 T4 (#239) registers the audit engine's
consumers: ``audit.event`` (the generic consent carrier) and the
``record.accessed`` / ``record.denied`` events MOD-003 publishes - each
appends one regulated act to the hash-chained ``audit_events`` ledger.
PHASE-5 T04/T13 (#247/#256) adds consumers for the partner gate's regulated
acts - ``partner.registered``, ``partner.activated`` / ``partner.rejected``,
``partner.credential_reviewed``, and ``credential.invalidated`` - so every
regulated act the bus carries lands in the chain exactly once. The
``audit.tamper_detected`` telemetry event (written by the tamper guard
trigger) is consumed with a logging handler only, never appended to the
chain (#234 user story 11; real-time alert delivery deferred).

Every handler is idempotent (ADR-0002 §3): its ``consumed_events`` ledger row
is written in the SAME transaction as the effect, so replaying a delivered
``event_id`` is a no-op and a crash rolls both back together.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncConnection

from bus.envelope import Envelope
from bus.events import (
    EVENT_AUDIT_EVENT,
    EVENT_AUDIT_TAMPER_DETECTED,
    EVENT_CREDENTIAL_INVALIDATED,
    EVENT_PARTNER_ACTIVATED,
    EVENT_PARTNER_CREDENTIAL_REVIEWED,
    EVENT_PARTNER_REGISTERED,
    EVENT_PARTNER_REJECTED,
    EVENT_RECORD_ACCESSED,
    EVENT_RECORD_DENIED,
    is_regulated_act,
)
from bus.handler_harness import run_handler
from bus.registry import HandlerRegistry
from modules.audit.domain.consumer import (
    AuditEventPayload,
    CredentialInvalidatedPayload,
    CredentialReviewedPayload,
    PartnerDecisionPayload,
    PartnerRegisteredPayload,
    RecordAccessAuditPayload,
    TamperDetectedPayload,
    is_appended_act,
)
from modules.audit.facade import (
    AUDIT_SCHEMA,
    append_audit_event,
    append_credential_invalidated_event,
    append_credential_reviewed_event,
    append_partner_decision_event,
    append_partner_registered_event,
    append_record_access_event,
)


def register_handlers(registry: HandlerRegistry) -> None:
    """Register the audit module's event handlers + payload models."""
    # MOD-011 owns the payload model for the generic ``audit.event`` carrier
    # (it moved here from MOD-004 in PHASE-4 T4): the dispatcher reconstructs a
    # claimed ``audit.event`` outbox row with this model before fan-out.
    registry.register_payload_model(EVENT_AUDIT_EVENT, AuditEventPayload)

    async def append_audit_act(envelope: Envelope[BaseModel]) -> None:
        """Consume ``audit.event``: append one regulated act to the hash chain.

        Ledger first, filter and append second, one transaction: a redelivered
        ``event_id`` finds its ledger row and skips the append; a crash between
        the writes rolls back together, so the event's next delivery retries
        cleanly (at-least-once). Operational acts pass the ledger row (the event
        was consumed) but are silently skipped - only a regulated act is
        appended to ``audit_events``.
        """

        async def _impl(connection: AsyncConnection, payload: AuditEventPayload) -> None:
            if not is_appended_act(payload):
                return
            await append_audit_event(
                connection,
                payload,
                envelope.producer,
                envelope.occurred_at,
            )

        await run_handler(envelope, AuditEventPayload, _impl, "append_audit_act", AUDIT_SCHEMA)

    registry.register(EVENT_AUDIT_EVENT, append_audit_act)

    # MOD-011 owns the payload mirror for the record-access events MOD-003
    # publishes (the consumer owns the model, cf. ``audit.event``): the
    # dispatcher reconstructs claimed ``record.accessed`` / ``record.denied``
    # outbox rows with it before fan-out. Both events share one mirror shape.
    for record_event_type in (EVENT_RECORD_ACCESSED, EVENT_RECORD_DENIED):
        registry.register_payload_model(record_event_type, RecordAccessAuditPayload)

    async def append_record_access_act(envelope: Envelope[BaseModel]) -> None:
        """Consume ``record.accessed`` / ``record.denied``: append to the chain.

        Ledger first, filter and append second, one transaction: a redelivered
        ``event_id`` finds its ledger row and skips the append (at-least-once).
        Both event types are regulated acts on their own - T3's predicate runs
        on the event type directly, no derivation - so the read facts (who /
        which record / scope, optional denial) are appended with the event type
        as the act type.
        """

        async def _impl(connection: AsyncConnection, payload: RecordAccessAuditPayload) -> None:
            if not is_regulated_act(envelope.event_type):
                return
            await append_record_access_event(
                connection,
                envelope.event_type,
                payload,
                envelope.producer,
            )

        await run_handler(
            envelope,
            RecordAccessAuditPayload,
            _impl,
            "append_record_access_act",
            AUDIT_SCHEMA,
        )

    registry.register(EVENT_RECORD_ACCESSED, append_record_access_act)
    registry.register(EVENT_RECORD_DENIED, append_record_access_act)

    # PHASE-5 T13 (#256): the partner gate's regulated acts. MOD-011 consumes
    # the terminal-decision events with its own payload mirror - MOD-001 owns
    # the registry payload model for ``partner.activated`` / ``partner.rejected``
    # (its role-grant/suspend consumers), so MOD-011 registers no duplicate
    # model here; ``run_handler`` re-validates the dispatched payload into
    # ``PartnerDecisionPayload``. The dispatcher must only know this
    # event has consumers, never claim a model for it.
    async def append_partner_decision(envelope: Envelope[BaseModel]) -> None:
        """Consume ``partner.activated`` / ``partner.rejected``: append to chain.

        Ledger first, filter and append second, one transaction: a redelivered
        ``event_id`` finds its ledger row and skips the append (at-least-once).
        Both event types are regulated acts on their own - T3's predicate runs
        on the event type directly, no derivation - so the terminal operator
        decision (who decided, which partner, why) is appended with the event
        type as the act type.
        """

        async def _impl(connection: AsyncConnection, payload: PartnerDecisionPayload) -> None:
            if not is_regulated_act(envelope.event_type):
                return
            await append_partner_decision_event(
                connection,
                envelope.event_type,
                payload,
                envelope.producer,
                envelope.occurred_at,
            )

        await run_handler(
            envelope,
            PartnerDecisionPayload,
            _impl,
            "append_partner_decision",
            AUDIT_SCHEMA,
        )

    registry.register(EVENT_PARTNER_ACTIVATED, append_partner_decision)
    registry.register(EVENT_PARTNER_REJECTED, append_partner_decision)

    # MOD-011 owns the payload mirror for ``partner.credential_reviewed`` (the
    # "who saw this document" trail, ADR-0008): one append per credential view,
    # attributed with actor + partner + timestamp.
    registry.register_payload_model(EVENT_PARTNER_CREDENTIAL_REVIEWED, CredentialReviewedPayload)

    async def append_credential_reviewed(envelope: Envelope[BaseModel]) -> None:
        """Consume ``partner.credential_reviewed``: append one view to the chain.

        Ledger first, filter and append second, one transaction: a redelivered
        ``event_id`` finds its ledger row and skips the append (at-least-once).
        The event type is a regulated act on its own (T13 added it to T3's
        whitelist) - every view yields one chained append so "who looked at the
        documents" is fully attributed.
        """

        async def _impl(connection: AsyncConnection, payload: CredentialReviewedPayload) -> None:
            if not is_regulated_act(envelope.event_type):
                return
            await append_credential_reviewed_event(
                connection,
                payload,
                envelope.producer,
                envelope.occurred_at,
            )

        await run_handler(
            envelope,
            CredentialReviewedPayload,
            _impl,
            "append_credential_reviewed",
            AUDIT_SCHEMA,
        )

    registry.register(EVENT_PARTNER_CREDENTIAL_REVIEWED, append_credential_reviewed)

    # PHASE-5 T04 (#247) / T13 (#256): ``partner.registered`` is a regulated
    # act on its own, and MOD-011 is its sole consumer (MOD-002 is the sole
    # producer in the registry - the iam-side same-key emission was removed,
    # see internal-modules §4.2). MOD-011 owns the payload model and appends
    # one registration row to the chain.
    registry.register_payload_model(EVENT_PARTNER_REGISTERED, PartnerRegisteredPayload)

    async def append_partner_registered(envelope: Envelope[BaseModel]) -> None:
        """Consume ``partner.registered``: append one registration row.

        Ledger first, filter and append second, one transaction: a redelivered
        ``event_id`` finds its ledger row and skips the append (at-least-once).
        The event type is a regulated act on its own (T04) - every partner
        registration yields one chained append.
        """

        async def _impl(connection: AsyncConnection, payload: PartnerRegisteredPayload) -> None:
            if not is_regulated_act(envelope.event_type):
                return
            await append_partner_registered_event(
                connection,
                payload,
                envelope.producer,
                envelope.occurred_at,
            )

        await run_handler(
            envelope,
            PartnerRegisteredPayload,
            _impl,
            "append_partner_registered",
            AUDIT_SCHEMA,
        )

    registry.register(EVENT_PARTNER_REGISTERED, append_partner_registered)

    # ``credential.invalidated`` is a regulated act (T13, #256) with MOD-001
    # already owning the registry payload model (its role-suspension
    # consumer). MOD-011 registers no duplicate model here; ``run_handler``
    # re-validates the dispatched payload into the local mirror, matching the
    # ``partner.activated`` / ``partner.rejected`` consumer shape.
    async def append_credential_invalidated(envelope: Envelope[BaseModel]) -> None:
        """Consume ``credential.invalidated``: append one invalidation row.

        Ledger first, filter and append second, one transaction: a redelivered
        ``event_id`` finds its ledger row and skips the append (at-least-once).
        The event type is a regulated act on its own (T13) - every credential
        losing validity yields one chained append.
        """

        async def _impl(connection: AsyncConnection, payload: CredentialInvalidatedPayload) -> None:
            if not is_regulated_act(envelope.event_type):
                return
            await append_credential_invalidated_event(
                connection,
                payload,
                envelope.producer,
                envelope.occurred_at,
            )

        await run_handler(
            envelope,
            CredentialInvalidatedPayload,
            _impl,
            "append_credential_invalidated",
            AUDIT_SCHEMA,
        )

    registry.register(EVENT_CREDENTIAL_INVALIDATED, append_credential_invalidated)

    # MOD-011 owns the model + a logging consumer for its own tamper telemetry
    # event (written into ``audit.audit_outbox`` by the v3.2 trigger). Without
    # a registered model and handler the dispatcher would error-loop the row on
    # reclaim (its "no handlers registered" guard); the consumer keeps the
    # outbox draining. Never appended to the hash chain (out of scope: real-time
    # alert delivery).
    registry.register_payload_model(EVENT_AUDIT_TAMPER_DETECTED, TamperDetectedPayload)

    async def log_tamper_detected(envelope: Envelope[BaseModel]) -> None:
        """Consume ``audit.tamper_detected``: log the blocked tamper attempt.

        A telemetry/notification event, NOT a regulated act (PHASE-4 #234 user
        story 11): the ledger row marks delivery, then the attempt facts ride a
        structured log line until real-time alerting lands in a later phase.
        """

        async def _impl(connection: AsyncConnection, payload: TamperDetectedPayload) -> None:
            del connection
            logging.getLogger(__name__).warning(
                "tamper attempt blocked and recorded: operation=%s target_event_id=%s details=%s",
                payload.attempted_operation,
                payload.target_event_id,
                payload.details,
            )

        await run_handler(
            envelope, TamperDetectedPayload, _impl, "log_tamper_detected", AUDIT_SCHEMA
        )

    registry.register(EVENT_AUDIT_TAMPER_DETECTED, log_tamper_detected)
