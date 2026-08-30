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

from datetime import UTC, datetime

# Type-only import to avoid circular dependency at runtime
from typing import TYPE_CHECKING

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.config import Settings
from bus.outbox_writer import write_outbox
from modules.health.domain.events import record_accessed_envelope, record_view_denied_envelope
from modules.health.domain.exceptions import (
    RecordAccessDeniedError,
    RecordNotFoundError,
)
from modules.health.outbox import HEALTH_OUTBOX_TABLE
from modules.health.schema.models import (
    health_patient_records,
    health_record_access_history,
    health_record_entries,
)

if TYPE_CHECKING:
    from modules.consent.facade import ConsentFacade

HEALTH_SCHEMA = "health"

# The default scope for an owner's own read of their complete record; matches
# the consent ``RecordScope`` vocabulary ("full_record").
_OWNER_SCOPE = "full_record"

_ACTOR_TYPE_PATIENT = "patient"


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


class AccessHistoryEntry(BaseModel):
    """One read attempt on the patient's record as the trust view answers it.

    Every row of ``health_record_access_history`` becomes one entry: who read
    (``actor_id`` + ``actor_type``), over which scope, when, and whether the
    attempt was refused - with the ``denial_reason`` when it was (FEAT-003
    "who / how / why"). The health ledger is the fast patient-facing source;
    the hash-chained copy of the same acts lives in MOD-011's ``audit_events``.
    """

    actor_id: int
    actor_type: str | None
    scope: str | None
    accessed_at: datetime
    denied: bool
    denial_reason: str | None


class AccessHistoryView(BaseModel):
    """The typed contract of the patient access-history view (FEAT-003).

    ``entries`` is reverse-chronological by ``accessed_at``. A record no one
    has touched yet answers an empty list - never an error (zero-setup trust
    view for a freshly registered patient).
    """

    entries: list[AccessHistoryEntry]


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
    connection: AsyncConnection,
    record_id: int,
    accessor_identity_id: int,
    outcome: str,
    *,
    actor_type: str,
    scope: str,
    denial_reason: str | None = None,
) -> None:
    """Record one read attempt in BOTH the access-history ledger and the outbox.

    Dual write (FEAT-003, KPI-006) in the caller's transaction: the
    ``health_record_access_history`` row feeds the fast patient view, and the
    ``record.accessed`` / ``record_view_denied`` event drives MOD-011's hash
    chain. The caller commits or rolls both back together.
    """
    accessed_at = datetime.now(UTC)
    # actor_type / scope / denial_reason persist next to the ledger row too
    # (PHASE-4 T7, #241) so the fast patient view answers who/how/why without
    # joining the outbox payload; denial_reason stays NULL for allowed reads.
    await connection.execute(
        health_record_access_history.insert().values(
            record_id=record_id,
            accessor_identity_id=accessor_identity_id,
            outcome=outcome,
            actor_type=actor_type,
            scope=scope,
            denial_reason=denial_reason,
        )
    )
    if outcome == "allowed":
        envelope = record_accessed_envelope(
            record_id=record_id,
            actor_id=accessor_identity_id,
            actor_type=actor_type,
            scope=scope,
            accessed_at=accessed_at,
        )
    else:
        envelope = record_view_denied_envelope(
            record_id=record_id,
            actor_id=accessor_identity_id,
            actor_type=actor_type,
            scope=scope,
            accessed_at=accessed_at,
            denial_reason=denial_reason or "access denied",
        )
    await write_outbox(connection, HEALTH_SCHEMA, HEALTH_OUTBOX_TABLE, envelope)


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


async def query_access_history(connection: AsyncConnection, patient_id: int) -> AccessHistoryView:
    """Read every access-history row for a patient's record, newest first.

    Resolves the patient's single record shell via ``health_patient_records``
    and selects every ``health_record_access_history`` row bound to it - owner
    reads, partner reads, and denied attempts alike - concretizing the
    ``denied`` flag from the ``outcome`` column. A patient whose record has
    never been touched answers an empty list. Running inside the caller's
    connection keeps the read single-transaction and testable without a
    database (same seam shape as MOD-011's ``query_audit_events``).
    """
    rows = (
        await connection.execute(
            select(
                health_record_access_history.c.accessor_identity_id,
                health_record_access_history.c.actor_type,
                health_record_access_history.c.scope,
                health_record_access_history.c.accessed_at,
                health_record_access_history.c.outcome,
                health_record_access_history.c.denial_reason,
            )
            .select_from(
                health_record_access_history.join(
                    health_patient_records,
                    health_record_access_history.c.record_id == health_patient_records.c.id,
                )
            )
            .where(health_patient_records.c.identity_id == patient_id)
            .order_by(
                health_record_access_history.c.accessed_at.desc(),
                health_record_access_history.c.id.desc(),
            )
        )
    ).all()
    return AccessHistoryView(
        entries=[
            AccessHistoryEntry(
                actor_id=int(row.accessor_identity_id),
                actor_type=row.actor_type,
                scope=row.scope,
                accessed_at=row.accessed_at,
                denied=row.outcome == "denied",
                denial_reason=row.denial_reason,
            )
            for row in rows
        ]
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
            await _log_access(
                connection,
                record_id,
                patient_id,
                "allowed",
                actor_type=_ACTOR_TYPE_PATIENT,
                scope=_OWNER_SCOPE,
            )
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
                await _log_access(
                    connection,
                    record_id,
                    patient_id,
                    "denied",
                    actor_type=_ACTOR_TYPE_PATIENT,
                    scope=_OWNER_SCOPE,
                    denial_reason="only the record owner may read this record",
                )
                denial_recorded = True
            else:
                await _log_access(
                    connection,
                    record_id,
                    patient_id,
                    "allowed",
                    actor_type=_ACTOR_TYPE_PATIENT,
                    scope=_OWNER_SCOPE,
                )
                return await _load_timeline(connection, record_id, patient_id)
        if denial_recorded:
            raise RecordAccessDeniedError("only the record owner may read this record")
        raise RecordNotFoundError(f"no record exists with id {record_id}")

    async def get_access_history(self, patient_id: int) -> AccessHistoryView:
        """Return the patient's record access history, newest first (FEAT-003).

        A pure read of ``health_record_access_history`` for every row keyed to
        the patient's record - owner reads, partner reads, and denied attempts
        alike. A record no one has touched yet answers an empty list, not an
        error. The ledger is a trust read, not a record access itself, so it
        is not logged back into the ledger.
        """
        async with self._engine.begin() as connection:
            return await query_access_history(connection, patient_id)

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
                # Denied read: log access history + denied event, then raise
                # AFTER the transaction commits (cf. get_record_as_owner pattern).
                await _log_access(
                    connection,
                    record_id,
                    counterparty_id,
                    "denied",
                    actor_type=counterparty_type,
                    scope=scope,
                    denial_reason="consent check failed",
                )
            else:
                # Allowed read: load entries and log access history + event
                await _log_access(
                    connection,
                    record_id,
                    counterparty_id,
                    "allowed",
                    actor_type=counterparty_type,
                    scope=scope,
                )
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
