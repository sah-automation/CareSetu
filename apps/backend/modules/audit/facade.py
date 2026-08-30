"""MOD-011 Audit: typed public sync API.

The only legal cross-module import target for the ``audit``
module (coding-standards §2, ADR-0003). Public query methods arrive
with T6/T7; this phase exposes the internal helpers the event consumer
uses to compute hashes and append to the ``audit_events`` ledger.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncConnection

from modules.audit.domain.chain import GENESIS_HASH, compute_audit_hash
from modules.audit.domain.consumer import AuditEventPayload, AuditRow, build_audit_row
from modules.audit.schema.models import audit_events

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
    """Return the most recent row's hash, or ``GENESIS_HASH`` for an empty chain.

    The chain head is the newest row by ``timestamp``; its digest becomes the
    next row's ``prev_hash``. An empty ledger chains the first row to the
    pinned genesis constant.
    """
    hash_value = await connection.scalar(
        select(audit_events.c.hash).order_by(audit_events.c.timestamp.desc()).limit(1)
    )
    return hash_value if hash_value is not None else GENESIS_HASH


async def append_audit_event(
    connection: AsyncConnection,
    payload: AuditEventPayload,
    producer: str,
    occurred_at: datetime,
) -> AuditRow:
    """Append one regulated act to the hash-chained ``audit_events`` ledger.

    Reads the latest chain head (or genesis for the first row), computes the
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


class AuditFacade:
    """Typed public facade for audit (query methods arrive with T6/T7)."""
