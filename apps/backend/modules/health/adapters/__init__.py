"""MOD-003: event handlers for the ``health`` module (coding-standards §2).

``register_handlers`` is the composition-root seam (PHASE-1 T4, #30):
the worker entrypoint calls it to register this module's handlers on the
shared ``HandlerRegistry``. PHASE-3 T2 (#211) registers the module's - and
the app's - first real subscriber: ``patient.registered`` -> record shell
creation. The handler is idempotent (ADR-0002 §3): its ``consumed_events``
ledger row is written in the SAME transaction as the effect, so replaying a
delivered ``event_id`` is a no-op and a crash rolls both back together.

PHASE-3 T6 (#215) adds subscribers for ``report.filed``,
``prescription.issued``, ``prescription.delivered``, ``settlement.recorded``,
and ``consent.granted/revoked`` to keep the effective sharing view current.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from bus.envelope import Envelope
from bus.events import (
    EVENT_CONSENT_GRANTED,
    EVENT_CONSENT_REVOKED,
    EVENT_PATIENT_REGISTERED,
    EVENT_PRESCRIPTION_DELIVERED,
    EVENT_PRESCRIPTION_ISSUED,
    EVENT_REPORT_FILED,
    EVENT_SETTLEMENT_RECORDED,
)
from bus.handler_harness import run_handler
from bus.registry import HandlerRegistry
from modules.health.domain.events import (
    PatientRegisteredPayload,
    PrescriptionDeliveredPayload,
    PrescriptionIssuedPayload,
    ReportFiledPayload,
    SettlementRecordedPayload,
)
from modules.health.facade import HEALTH_SCHEMA, _ensure_record_shell
from modules.health.schema.models import health_record_entries


def register_handlers(registry: HandlerRegistry) -> None:
    """Register the health module's event handlers + payload models."""
    # The dispatcher reconstructs a typed envelope from a claimed outbox row
    # with this model before fan-out; health owns the registration because it
    # is patient.registered's only consumer today (see domain/events.py).
    registry.register_payload_model(EVENT_PATIENT_REGISTERED, PatientRegisteredPayload)
    registry.register_payload_model(EVENT_REPORT_FILED, ReportFiledPayload)
    registry.register_payload_model(EVENT_PRESCRIPTION_ISSUED, PrescriptionIssuedPayload)
    registry.register_payload_model(EVENT_PRESCRIPTION_DELIVERED, PrescriptionDeliveredPayload)
    registry.register_payload_model(EVENT_SETTLEMENT_RECORDED, SettlementRecordedPayload)

    async def create_record_shell(envelope: Envelope[BaseModel]) -> None:
        """Consume ``patient.registered``: ensure the identity's empty shell.

        Ledger first, effects second, one transaction: a redelivered
        ``event_id`` finds its ledger row and skips the insert; a crash
        between the two writes rolls back together, so the event's next
        delivery retries cleanly (at-least-once).
        """

        async def _impl(connection: AsyncConnection, payload: PatientRegisteredPayload) -> None:
            await _ensure_record_shell(connection, payload.identity_id)

        await run_handler(
            envelope, PatientRegisteredPayload, _impl, "create_record_shell", HEALTH_SCHEMA
        )

    registry.register(EVENT_PATIENT_REGISTERED, create_record_shell)

    async def handle_report_filed(envelope: Envelope[BaseModel]) -> None:
        """Consume ``report.filed``: create a lab_report entry in the timeline."""

        async def _impl(connection: AsyncConnection, payload: ReportFiledPayload) -> None:
            record_id = await _ensure_record_shell(connection, payload.patient_id)
            await connection.execute(
                insert(health_record_entries).values(
                    record_id=record_id,
                    entry_type="lab_report",
                    payload={
                        "order_id": payload.order_id,
                        "filename": payload.filename,
                    },
                    occurred_at=datetime.fromisoformat(payload.occurred_at.replace("Z", "+00:00")),
                )
            )

        await run_handler(envelope, ReportFiledPayload, _impl, "handle_report_filed", HEALTH_SCHEMA)

    registry.register(EVENT_REPORT_FILED, handle_report_filed)

    async def handle_prescription_issued(envelope: Envelope[BaseModel]) -> None:
        """Consume ``prescription.issued``: create a prescription entry in the timeline."""

        async def _impl(connection: AsyncConnection, payload: PrescriptionIssuedPayload) -> None:
            record_id = await _ensure_record_shell(connection, payload.patient_id)
            await connection.execute(
                insert(health_record_entries).values(
                    record_id=record_id,
                    entry_type="prescription",
                    payload={
                        "prescription_id": payload.prescription_id,
                        "status": "issued",
                    },
                    occurred_at=datetime.fromisoformat(payload.occurred_at.replace("Z", "+00:00")),
                )
            )

        await run_handler(
            envelope, PrescriptionIssuedPayload, _impl, "handle_prescription_issued", HEALTH_SCHEMA
        )

    registry.register(EVENT_PRESCRIPTION_ISSUED, handle_prescription_issued)

    async def handle_prescription_delivered(envelope: Envelope[BaseModel]) -> None:
        """Consume ``prescription.delivered``: create a prescription entry in the timeline."""

        async def _impl(connection: AsyncConnection, payload: PrescriptionDeliveredPayload) -> None:
            record_id = await _ensure_record_shell(connection, payload.patient_id)
            await connection.execute(
                insert(health_record_entries).values(
                    record_id=record_id,
                    entry_type="prescription",
                    payload={
                        "fulfillment_order_id": payload.fulfillment_order_id,
                        "prescription_id": payload.prescription_id,
                        "status": "delivered",
                    },
                    occurred_at=datetime.fromisoformat(payload.occurred_at.replace("Z", "+00:00")),
                )
            )

        await run_handler(
            envelope,
            PrescriptionDeliveredPayload,
            _impl,
            "handle_prescription_delivered",
            HEALTH_SCHEMA,
        )

    registry.register(EVENT_PRESCRIPTION_DELIVERED, handle_prescription_delivered)

    async def handle_settlement_recorded(envelope: Envelope[BaseModel]) -> None:
        """Consume ``settlement.recorded``: create a settlement entry in the timeline."""

        async def _impl(connection: AsyncConnection, payload: SettlementRecordedPayload) -> None:
            record_id = await _ensure_record_shell(connection, payload.patient_id)
            await connection.execute(
                insert(health_record_entries).values(
                    record_id=record_id,
                    entry_type="settlement",
                    payload={
                        "settlement_id": payload.settlement_id,
                        "order_ref": payload.order_ref,
                        "amount_paise": payload.amount_paise,
                    },
                    occurred_at=datetime.fromisoformat(payload.occurred_at.replace("Z", "+00:00")),
                )
            )

        await run_handler(
            envelope, SettlementRecordedPayload, _impl, "handle_settlement_recorded", HEALTH_SCHEMA
        )

    registry.register(EVENT_SETTLEMENT_RECORDED, handle_settlement_recorded)

    async def handle_consent_granted(envelope: Envelope[BaseModel]) -> None:
        """Consume ``consent.granted``: update effective sharing state (placeholder for PHASE-3 T6).

        The effective sharing view is maintained by the health module to know
        which counterparties have access to which record scopes. This is a
        placeholder - the actual implementation will update a materialized view
        or cache in later phases.
        """

        async def _impl(connection: AsyncConnection, payload: BaseModel) -> None:
            pass  # Effective sharing view update happens here in later phases

        await run_handler(envelope, BaseModel, _impl, "handle_consent_granted", HEALTH_SCHEMA)

    registry.register(EVENT_CONSENT_GRANTED, handle_consent_granted)

    async def handle_consent_revoked(envelope: Envelope[BaseModel]) -> None:
        """Consume ``consent.revoked``: update effective sharing state (placeholder for PHASE-3 T6).

        The effective sharing view is updated to remove the revoked counterparty's
        access. This is a placeholder - the actual implementation will update a
        materialized view or cache in later phases.
        """

        async def _impl(connection: AsyncConnection, payload: BaseModel) -> None:
            pass  # Effective sharing view update happens here in later phases

        await run_handler(envelope, BaseModel, _impl, "handle_consent_revoked", HEALTH_SCHEMA)

    registry.register(EVENT_CONSENT_REVOKED, handle_consent_revoked)
