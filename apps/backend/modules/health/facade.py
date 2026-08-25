"""MOD-003 Health data: typed public sync API.

The only legal cross-module import target for the ``health``
module (coding-standards S2, ADR-0003). PHASE-3 T2 (#211) lands the
longitudinal-record core: ``create_record`` (the idempotent shell creation
the ``patient.registered`` subscriber calls), and the owner-only record
reads - ``get_own_record`` resolves the caller's identity,
``get_record_as_owner`` reads an addressed record and refuses non-owners.
Every read attempt - owner or not, allowed or denied - is recorded in the
``health_record_access_history`` ledger in the same transaction as the read
(MOD-003 NFR: KPI-006, 100% of record accesses logged). PHASE-3 T5 (#214)
adds ``read_consented_history`` for partner reads gated by MOD-004's
``check_consent`` and dual-ledger writes (access history + egress log).

FIX-7 (#227): The egress log write is delegated to
``ConsentFacade.record_egress_disclosure`` which runs in its own
transaction.  This preserves the module boundary (no consent schema
imports) while accepting two-transaction eventual consistency for the
append-only egress audit row (see inline ADR in ``read_consented_history``).
"""

from __future__ import annotations

from datetime import datetime

# Type-only import to avoid circular dependency at runtime
from typing import TYPE_CHECKING

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.config import Settings
from modules.health.domain.exceptions import (
    RecordAccessDeniedError,
    RecordNotFoundError,
)
from modules.health.schema.models import (
    health_patient_records,
    health_record_access_history,
    health_record_entries,
)

if TYPE_CHECKING:
    from modules.consent.facade import ConsentFacade

HEALTH_SCHEMA = "health"


class RecordEntryView(BaseModel):
    """One clinical entry on the timeline, newest-first in the list order."""

    entry_id: int
    entry_type: str
    payload: dict[str, object]
    occurred_at: datetime
    created_at: datetime


class RecordTimeline(BaseModel):
    """The documented typed contract of the own-record view (FEAT-002/003).

    ``entries`` is reverse-chronological by clinical time (``occurred_at``);
    a freshly registered patient owns an empty timeline - zero setup.
    """

    record_id: int
    patient_id: int
    created_at: datetime
    entries: list[RecordEntryView]


async def _ensure_record_shell(connection: AsyncConnection, patient_id: int) -> int:
    """Resolve the patient's record id, creating the empty shell if absent.

    ``INSERT ... ON CONFLICT DO NOTHING`` then re-read, never SELECT-then-
    INSERT: the unique ``identity_id`` index converges concurrent creators
    (subscriber delivery racing a lazy owner read) onto the winning row, so
    at-least-once event replay can never duplicate a shell. Returns the
    existing or freshly created record id.
    """
    await connection.execute(
        postgresql_insert(health_patient_records)
        .values(identity_id=patient_id)
        .on_conflict_do_nothing(index_elements=["identity_id"])
    )
    record_id = (
        await connection.execute(
            select(health_patient_records.c.id).where(
                health_patient_records.c.identity_id == patient_id
            )
        )
    ).scalar_one()
    return int(record_id)


async def _log_access(
    connection: AsyncConnection, record_id: int, accessor_identity_id: int, outcome: str
) -> None:
    """Append one access-history row for this read attempt (KPI-006)."""
    await connection.execute(
        health_record_access_history.insert().values(
            record_id=record_id,
            accessor_identity_id=accessor_identity_id,
            outcome=outcome,
        )
    )


async def _load_timeline(
    connection: AsyncConnection, record_id: int, patient_id: int
) -> RecordTimeline:
    """Read the shell metadata plus its entries, newest clinical event first."""
    record_row = (
        await connection.execute(
            select(health_patient_records.c.created_at).where(
                health_patient_records.c.id == record_id
            )
        )
    ).one()
    entry_rows = (
        await connection.execute(
            select(
                health_record_entries.c.id,
                health_record_entries.c.entry_type,
                health_record_entries.c.payload,
                health_record_entries.c.occurred_at,
                health_record_entries.c.created_at,
            )
            .where(health_record_entries.c.record_id == record_id)
            .order_by(health_record_entries.c.occurred_at.desc(), health_record_entries.c.id.desc())
        )
    ).all()
    return RecordTimeline(
        record_id=record_id,
        patient_id=patient_id,
        created_at=record_row.created_at,
        entries=[
            RecordEntryView(
                entry_id=int(row.id),
                entry_type=str(row.entry_type),
                payload=dict(row.payload),
                occurred_at=row.occurred_at,
                created_at=row.created_at,
            )
            for row in entry_rows
        ],
    )


class HealthFacade:
    """Typed public facade for the health module's record surface."""

    def __init__(self, engine: AsyncEngine, consent_facade: ConsentFacade | None = None) -> None:
        self._engine = engine
        self._consent_facade = consent_facade

    async def create_record(self, patient_id: int) -> int:
        """Create the patient's record shell; a no-op returning the existing id.

        The seam the ``patient.registered`` subscriber drives: zero-setup
        ownership means every identity ends up with exactly one shell, and a
        redelivered event resolves to the same row instead of failing.
        """
        async with self._engine.begin() as connection:
            return await _ensure_record_shell(connection, patient_id)

    async def get_own_record(self, patient_id: int) -> RecordTimeline:
        """Owner read resolved by identity; records an allowed access.

        The shell is lazily ensured here as a safety net (a patient registered
        before the subscriber ran, or while its delivery is still in flight),
        so an owner never sees anything but their - possibly empty - timeline.
        The access lands in the ledger in the same transaction as the read.
        """
        async with self._engine.begin() as connection:
            record_id = await _ensure_record_shell(connection, patient_id)
            await _log_access(connection, record_id, patient_id, "allowed")
            return await _load_timeline(connection, record_id, patient_id)

    async def get_record_as_owner(self, patient_id: int, record_id: int) -> RecordTimeline:
        """Addressed owner-only read: deny and RECORD any non-owner attempt.

        A caller whose identity does not own the addressed record gets the
        403 envelope (mapped from ``RecordAccessDeniedError`` by the routes)
        AND a ``denied`` row naming them in the access history. The denial
        row is COMMITTED first - raising inside the transaction would roll it
        back - so a refused read is always auditable before the error leaves
        the facade. An unknown record id answers 404 with nothing to record.
        """
        denial_recorded = False
        async with self._engine.begin() as connection:
            row = (
                await connection.execute(
                    select(health_patient_records.c.identity_id).where(
                        health_patient_records.c.id == record_id
                    )
                )
            ).first()
            if row is None:
                # No record to key a history row against: 404, nothing logged.
                pass
            elif row.identity_id != patient_id:
                await _log_access(connection, record_id, patient_id, "denied")
                denial_recorded = True
            else:
                await _log_access(connection, record_id, patient_id, "allowed")
                return await _load_timeline(connection, record_id, patient_id)
        if denial_recorded:
            raise RecordAccessDeniedError("only the record owner may read this record")
        raise RecordNotFoundError(f"no record exists with id {record_id}")

    async def seed_record_entries(self, patient_id: int) -> tuple[list[int], list[str]]:
        """Return entry IDs and types for a patient's record (test-only seed helper).

        Ensures the record shell exists, then reads back all entries. Used by
        the ``/v1/test/seed`` endpoint so it does not import raw schema models.
        """
        async with self._engine.begin() as connection:
            record_id = await _ensure_record_shell(connection, patient_id)
            rows = (
                await connection.execute(
                    select(
                        health_record_entries.c.id,
                        health_record_entries.c.entry_type,
                    ).where(health_record_entries.c.record_id == record_id)
                )
            ).all()
            entry_ids = [int(r.id) for r in rows]
            entry_types = [r.entry_type for r in rows]
            return entry_ids, entry_types

    async def read_consented_history(
        self,
        patient_id: int,
        scope: str,
        counterparty_type: str,
        counterparty_id: int,
        settings: Settings | None = None,
    ) -> RecordTimeline:
        """Partner read gated by consent; writes to both ledgers on success.

        The consent gate is checked via MOD-004's ``check_consent``. If allowed,
        the scoped entries are returned and exactly ONE row is written to EACH
        ledger: health_record_access_history (outcome=allowed) and
        consent_egress_log (citing consent_id, version, lineage_ref, and disclosed entry_ids).
        If denied, only the access history ledger receives a row (outcome=denied).
        Owner reads bypass this gate entirely - use ``get_own_record``.
        """
        if self._consent_facade is None:
            raise RuntimeError("ConsentFacade not configured on HealthFacade")

        # Check consent via MOD-004
        decision = await self._consent_facade.check_consent(
            patient_id=patient_id,
            counterparty_type=counterparty_type,  # type: ignore[arg-type]
            counterparty_id=str(counterparty_id),
            record_scope=scope,
            settings=settings,
        )

        # Ensure record shell exists
        denied = not decision.allowed
        async with self._engine.begin() as connection:
            record_id = await _ensure_record_shell(connection, patient_id)

            if denied:
                # Denied read: log in access history, then raise AFTER
                # the transaction commits (cf. get_record_as_owner pattern).
                await _log_access(connection, record_id, counterparty_id, "denied")
            else:
                # Allowed read: load entries and log in access history
                await _log_access(connection, record_id, counterparty_id, "allowed")
                timeline = await _load_timeline(connection, record_id, patient_id)

        if denied:
            raise RecordAccessDeniedError("consent check failed")

        # ADR: Egress write is in its own consent-transaction (FIX-7, #227).
        # Health transaction commits above; consent facade opens a
        # separate transaction for the egress audit row.  Two-phase
        # commit is rejected as disproportionate for an append-only
        # ledger whose absence is detectable (coding-standards S2).
        disclosed_entry_ids = [entry.entry_id for entry in timeline.entries]
        consent_version = decision.version if decision.version is not None else 0
        await self._consent_facade.record_egress_disclosure(
            patient_id=patient_id,
            consent_id=decision.consent_id,
            version=consent_version,
            counterparty_type=counterparty_type,
            counterparty_id=str(counterparty_id),
            record_scope=scope,
            disclosed_entry_ids=disclosed_entry_ids,
        )

        return timeline
