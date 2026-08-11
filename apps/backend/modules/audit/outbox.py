"""MOD-011: outbox table contract for the ``audit`` module (ADR-0003).

The transactional outbox table name is a module contract; the
T6a boundary checker (#26) verifies it matches the schema table.
"""

from __future__ import annotations

AUDIT_OUTBOX_TABLE = "audit_outbox"
