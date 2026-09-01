"""MOD-011 Audit: typed public sync API.

The only legal cross-module import target for the ``audit``
module (coding-standards §2, ADR-0003). Public query methods arrive
with T6/T7; this phase exposes the internal helpers the event consumer
uses to compute hashes and append to the ``audit_events`` ledger.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine
from sqlalchemy.orm import aliased

from modules.audit.domain.chain import GENESIS_HASH, compute_audit_hash
from modules.audit.domain.consumer import (
    AuditEventPayload,
    AuditRow,
    CredentialInvalidatedPayload,
    CredentialReviewedPayload,
    PartnerDecisionPayload,
    PartnerRegisteredPayload,
    RecordAccessAuditPayload,
    _partner_uuid,
    build_audit_row,
    build_credential_invalidated_row,
    build_credential_reviewed_row,
    build_partner_decision_row,
    build_partner_registered_row,
    build_record_access_row,
)
from modules.audit.schema.models import audit_events

if TYPE_CHECKING:
    # Type-only import for the T7 delegation seam: AuditFacade calls through to
    # MOD-003's facade rather than reading the health schema (module isolation).
    from modules.health.facade import AccessHistoryView, HealthFacade

AUDIT_SCHEMA = "audit"


def compute_event_hash(
    event_type: str,
    actor_id: str | None,
    target_id: str | None,
    scope: str | None,
    metadata: dict[str, object] | None,
    timestamp: datetime,
    prev_hash: str,
) -> str:
    """Compute the deterministic digest for one ``audit_events`` row (internal).

    The facade's hash-computation helper (issue #239): delegates to T2's
    ``compute_audit_hash`` so the facade is a stable internal seam for hash
    work - the consumer appends through it, and T6/T7's verification/query
    helpers reuse it without importing the domain directly.
    """
    return compute_audit_hash(
        event_type,
        actor_id,
        target_id,
        scope,
        metadata,
        timestamp,
        prev_hash,
    )


async def _latest_hash(connection: AsyncConnection) -> str:
    """Return the chain tail's hash, or ``GENESIS_HASH`` for an empty ledger.

    The tail is the row no other row references as its ``prev_hash`` - the
    chain is defined by those links, never by ``timestamp``. A record-access
    row carries the historical ``accessed_at`` (so the audit view matches the
    access-history view); a newest-row-by-timestamp selection would make a
    backdated row fork off an older head. The first row chains to the pinned
    genesis constant. The ``references`` alias is explicit so the correlation
    binds the inner ``prev_hash`` to each outer row, not to itself.
    """
    references = aliased(audit_events)
    referenced = (
        select(references.c.prev_hash).where(references.c.prev_hash == audit_events.c.hash).exists()
    )
    hash_value = await connection.scalar(select(audit_events.c.hash).where(~referenced).limit(1))
    return hash_value if hash_value is not None else GENESIS_HASH


async def append_audit_event(
    connection: AsyncConnection,
    payload: AuditEventPayload,
    producer: str,
    occurred_at: datetime,
) -> AuditRow:
    """Append one regulated act to the hash-chained ``audit_events`` ledger.

    Reads the chain tail (or genesis for the first row), computes the
    deterministic digest with ``build_audit_row``, and inserts the row with
    every required column populated. Designed to run inside the caller's
    transaction - the ``consumed_events`` ledger row - so a crash rolls both
    back together (ADR-0002 §3). Returns the built row values.
    """
    prev_hash = await _latest_hash(connection)
    row = build_audit_row(payload, producer, occurred_at, prev_hash)
    await connection.execute(
        insert(audit_events).values(
            event_type=row.event_type,
            actor_id=row.actor_id,
            target_id=row.target_id,
            scope=row.scope,
            metadata=row.metadata,
            timestamp=row.timestamp,
            prev_hash=row.prev_hash,
            hash=row.hash,
        )
    )
    return row


async def append_record_access_event(
    connection: AsyncConnection,
    event_type: str,
    payload: RecordAccessAuditPayload,
    producer: str,
) -> AuditRow:
    """Append one record-access regulated act to the hash-chained ledger.

    Mirrors ``append_audit_event`` for ``record.accessed`` / ``record.denied``:
    reads the chain tail (or genesis), computes the deterministic digest
    with ``build_record_access_row``, and inserts the row with every required
    column populated. The event type is already the regulated act, so there is
    no derived act type. Runs inside the caller's transaction (the
    ``consumed_events`` ledger row), so a crash rolls both back together
    (ADR-0002 §3).
    """
    prev_hash = await _latest_hash(connection)
    row = build_record_access_row(event_type, payload, producer, prev_hash)
    await connection.execute(
        insert(audit_events).values(
            event_type=row.event_type,
            actor_id=row.actor_id,
            target_id=row.target_id,
            scope=row.scope,
            metadata=row.metadata,
            timestamp=row.timestamp,
            prev_hash=row.prev_hash,
            hash=row.hash,
        )
    )
    return row


async def append_partner_decision_event(
    connection: AsyncConnection,
    event_type: str,
    payload: PartnerDecisionPayload,
    producer: str,
    occurred_at: datetime,
) -> AuditRow:
    """Append one partner terminal decision to the hash-chained ledger.

    Mirrors ``append_record_access_event`` for ``partner.activated`` /
    ``partner.rejected``: reads the chain tail (or genesis), computes the
    deterministic digest with ``build_partner_decision_row``, and inserts the
    row with every required column populated. The event type is already the
    regulated act, so there is no derived act type. Runs inside the caller's
    transaction (the ``consumed_events`` ledger row), so a crash rolls both
    back together (ADR-0002 §3).
    """
    prev_hash = await _latest_hash(connection)
    row = build_partner_decision_row(event_type, payload, producer, occurred_at, prev_hash)
    await connection.execute(
        insert(audit_events).values(
            event_type=row.event_type,
            actor_id=row.actor_id,
            target_id=row.target_id,
            scope=row.scope,
            metadata=row.metadata,
            timestamp=row.timestamp,
            prev_hash=row.prev_hash,
            hash=row.hash,
        )
    )
    return row


async def append_credential_reviewed_event(
    connection: AsyncConnection,
    payload: CredentialReviewedPayload,
    producer: str,
    occurred_at: datetime,
) -> AuditRow:
    """Append one ``partner.credential_reviewed`` view to the hash-chained ledger.

    Mirrors ``append_partner_decision_event`` for the credential-view act:
    reads the chain tail (or genesis), computes the deterministic digest with
    ``build_credential_reviewed_row``, and inserts the row with every required
    column populated. One append per credential view - every view is
    traceable, not just a summary. Runs inside the caller's transaction (the
    ``consumed_events`` ledger row), so a crash rolls both back together
    (ADR-0002 §3).
    """
    prev_hash = await _latest_hash(connection)
    row = build_credential_reviewed_row(payload, producer, occurred_at, prev_hash)
    await connection.execute(
        insert(audit_events).values(
            event_type=row.event_type,
            actor_id=row.actor_id,
            target_id=row.target_id,
            scope=row.scope,
            metadata=row.metadata,
            timestamp=row.timestamp,
            prev_hash=row.prev_hash,
            hash=row.hash,
        )
    )
    return row


async def append_partner_registered_event(
    connection: AsyncConnection,
    payload: PartnerRegisteredPayload,
    producer: str,
    occurred_at: datetime,
) -> AuditRow:
    """Append one ``partner.registered`` act to the hash-chained ledger.

    Mirrors ``append_partner_decision_event`` for the registration act: reads
    the chain tail (or genesis), computes the deterministic digest with
    ``build_partner_registered_row``, and inserts the row with every required
    column populated. Runs inside the caller's transaction (the
    ``consumed_events`` ledger row), so a crash rolls both back together
    (ADR-0002 §3).
    """
    prev_hash = await _latest_hash(connection)
    row = build_partner_registered_row(payload, producer, occurred_at, prev_hash)
    await connection.execute(
        insert(audit_events).values(
            event_type=row.event_type,
            actor_id=row.actor_id,
            target_id=row.target_id,
            scope=row.scope,
            metadata=row.metadata,
            timestamp=row.timestamp,
            prev_hash=row.prev_hash,
            hash=row.hash,
        )
    )
    return row


async def append_credential_invalidated_event(
    connection: AsyncConnection,
    payload: CredentialInvalidatedPayload,
    producer: str,
    occurred_at: datetime,
) -> AuditRow:
    """Append one ``credential.invalidated`` act to the hash-chained ledger.

    Mirrors ``append_credential_reviewed_event`` for the invalidation act:
    reads the chain tail (or genesis), computes the deterministic digest with
    ``build_credential_invalidated_row``, and inserts the row with every
    required column populated. Runs inside the caller's transaction (the
    ``consumed_events`` ledger row), so a crash rolls both back together
    (ADR-0002 §3).
    """
    prev_hash = await _latest_hash(connection)
    row = build_credential_invalidated_row(payload, producer, occurred_at, prev_hash)
    await connection.execute(
        insert(audit_events).values(
            event_type=row.event_type,
            actor_id=row.actor_id,
            target_id=row.target_id,
            scope=row.scope,
            metadata=row.metadata,
            timestamp=row.timestamp,
            prev_hash=row.prev_hash,
            hash=row.hash,
        )
    )
    return row


class AuditEventView(BaseModel):
    """One ``audit_events`` row as the operator query API answers it (T6).

    A typed, read-only projection of a ledger row - the full event plus its
    chain links (``prev_hash``/``hash``), so an operator can trace a row back
    to its predecessor for tamper verification. No new PHI is disclosed
    beyond what the operator role already authorizes (NFR-SEC-003).
    """

    id: UUID
    event_type: str
    actor_id: UUID | None
    target_id: UUID | None
    scope: str | None
    metadata: dict[str, object]
    timestamp: datetime
    prev_hash: str
    hash: str


class AuditPage(BaseModel):
    """Paginated operator query result: the page plus the full match count.

    ``events`` is one page of ``AuditEventView`` rows ordered most-recent
    first; ``total_count`` reflects every matching row, not just the page, so
    the caller can page through the whole result set.
    """

    events: list[AuditEventView]
    total_count: int


async def query_audit_events(
    connection: AsyncConnection,
    *,
    actor_id: UUID | None,
    event_type: str | None,
    target_id: UUID | None,
    scope: str | None,
    from_ts: datetime | None,
    to_ts: datetime | None,
    page: int,
    page_size: int,
) -> AuditPage:
    """Query the ``audit_events`` ledger with optional filters + pagination.

    Builds the WHERE clause dynamically from the non-null filters (no filter
    = unfiltered SELECT over the whole ledger), counts the full match set for
    ``total_count``, then returns one page ordered by ``timestamp`` DESC
    (most recent first). Running inside the caller's connection keeps the
    read single-transaction and testable without a live database.
    """
    stmt = select(audit_events)
    if event_type is not None:
        stmt = stmt.where(audit_events.c.event_type == event_type)
    if actor_id is not None:
        stmt = stmt.where(audit_events.c.actor_id == actor_id)
    if target_id is not None:
        stmt = stmt.where(audit_events.c.target_id == target_id)
    if scope is not None:
        stmt = stmt.where(audit_events.c.scope == scope)
    if from_ts is not None:
        stmt = stmt.where(audit_events.c.timestamp >= from_ts)
    if to_ts is not None:
        stmt = stmt.where(audit_events.c.timestamp <= to_ts)

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_count = await connection.scalar(count_stmt) or 0

    page_stmt = (
        stmt.order_by(audit_events.c.timestamp.desc(), audit_events.c.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = await connection.execute(page_stmt)
    events = [
        AuditEventView(
            id=row["id"],
            event_type=row["event_type"],
            actor_id=row["actor_id"],
            target_id=row["target_id"],
            scope=row["scope"],
            metadata=row["metadata"],
            timestamp=row["timestamp"],
            prev_hash=row["prev_hash"],
            hash=row["hash"],
        )
        for row in rows.mappings()
    ]
    return AuditPage(events=events, total_count=total_count)


class AuditFacade:
    """Typed public facade for audit (query methods arrive with T6/T7).

    ``query_audit`` is the operator-facing query seam (T6): a thin wrapper
    that opens the settled engine connection and delegates the filtered,
    paginated SELECT to the module helper, so routes call one typed facade
    and the DB read stays inside the module.
    """

    def __init__(self, engine: AsyncEngine, health_facade: HealthFacade | None = None) -> None:
        self._engine = engine
        self._health_facade = health_facade

    async def query_audit(
        self,
        *,
        actor_id: UUID | None = None,
        event_type: str | None = None,
        target_id: UUID | None = None,
        scope: str | None = None,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> AuditPage:
        """Query the audit ledger as an operator (most recent first, paged)."""
        async with self._engine.begin() as connection:
            return await query_audit_events(
                connection,
                actor_id=actor_id,
                event_type=event_type,
                target_id=target_id,
                scope=scope,
                from_ts=from_ts,
                to_ts=to_ts,
                page=page,
                page_size=page_size,
            )

    async def query_partner_audit(self, partner_id: int, *, page_size: int = 50) -> AuditPage:
        """Return the audit chain for one partner (S7 detail-view augmentation).

        A partner's ledger rows are keyed by ``target_id = uuid5("caresetu.audit",
        "partner:{partner_id}")`` (the deterministic ``_partner_uuid`` mapping the
        partner consumers use when appending). This is the read-side reuse of that
        seam - the partner module asks the audit facade for the ledger rows instead
        of duplicating the int->UUID derivation.
        """
        target_id = UUID(_partner_uuid(partner_id))
        async with self._engine.begin() as connection:
            return await query_audit_events(
                connection,
                actor_id=None,
                event_type=None,
                target_id=target_id,
                scope=None,
                from_ts=None,
                to_ts=None,
                page=1,
                page_size=page_size,
            )

    async def get_access_history(self, patient_id: int) -> AccessHistoryView:
        """Return a patient's record access history via the MOD-003 facade (T7).

        MOD-003 owns the ``health.record_access_history`` ledger, so the
        cross-module seam is its facade (module isolation rule) - never a
        direct audit-schema read. Route-level RBAC (patient role + own record
        only) gates who may call this; the facade trusts the caller's record
        scope like ``get_own_record``.
        """
        if self._health_facade is None:
            raise RuntimeError("HealthFacade not configured on AuditFacade")
        return await self._health_facade.get_access_history(patient_id)
