"""MOD-010: outbox table contract for the ``notify`` module (ADR-0003).

The transactional outbox table name is a module contract; the
T6a boundary checker (#26) verifies it matches the schema table.
"""

from __future__ import annotations

NOTIFY_OUTBOX_TABLE = "notify_outbox"
