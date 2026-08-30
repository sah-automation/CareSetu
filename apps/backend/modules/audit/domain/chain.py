"""MOD-011: deterministic SHA-256 hash chain for the ``audit`` ledger (PHASE-4 T2, #236).

The append-only audit trail is guarded by prev-hash linkage: every
``audit_events`` row stores the digest of its own canonical fields and
the digest of the previous row. Recomputing hashes over the whole chain
detects any tamper that replaced or reordered row fields, because the
tampered row's stored hash no longer matches a recomputed digest and
every successor's ``prev_hash`` stops matching the preceding recomputed
hash.

Pure logic only: no imports from schema, facade or adapters - rows are
plain dataclasses so the verifier runs with no database (coding-standards §2).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

#: Root of the chain: every first row's ``prev_hash`` must equal this.
GENESIS_HASH = hashlib.sha256(b"CareSetu-audit-genesis").hexdigest()

#: Compact, deterministic JSON separators: one encoding per dict.
_JSON_SEPARATORS: tuple[str, str] = (",", ":")


@dataclass(frozen=True)
class AuditEventRow:
    """One ``audit_events`` row exactly as the verifier needs it."""

    event_type: str
    timestamp: datetime
    prev_hash: str
    hash: str
    actor_id: str | None = None
    target_id: str | None = None
    scope: str | None = None
    metadata: dict[str, Any] | None = None


def compute_audit_hash(
    event_type: str,
    actor_id: str | None,
    target_id: str | None,
    scope: str | None,
    metadata: dict[str, Any] | None,
    timestamp: datetime,
    prev_hash: str,
) -> str:
    """Return the deterministic SHA-256 hex digest for one audit event.

    The digest covers a canonical JSON rendering of every field: UUIDs
    lower-cased, ``None`` distinct from empty, dictionary keys sorted
    recursively, and the timestamp in fixed microsecond ISO-8601 UTC
    offset. Identical inputs always produce identical digests, regardless
    of the insertion order of ``metadata``.
    """
    canonical = json.dumps(
        [
            event_type,
            None if actor_id is None else actor_id.lower(),
            None if target_id is None else target_id.lower(),
            scope,
            metadata,
            timestamp.isoformat(timespec="microseconds"),
            prev_hash,
        ],
        sort_keys=True,
        separators=_JSON_SEPARATORS,
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def verify_chain(rows: list[AuditEventRow]) -> bool:
    """Return True when every row's stored hash matches a recomputation.

    Rows are iterated in ``timestamp`` order: the first row must be
    chained to ``GENESIS_HASH`` and every later row must chain to the
    recomputed hash of its predecessor. Any mismatch - a rewritten
    field, a wrong prev link, or a stale hash - fails the whole chain.
    An empty chain is valid by convention.
    """
    prev_hash = GENESIS_HASH
    for row in sorted(rows, key=lambda r: r.timestamp):
        if row.prev_hash != prev_hash:
            return False
        expected = compute_audit_hash(
            row.event_type,
            row.actor_id,
            row.target_id,
            row.scope,
            row.metadata,
            row.timestamp,
            row.prev_hash,
        )
        if row.hash != expected:
            return False
        prev_hash = row.hash
    return True
