"""MOD-013: outbox table contract for the ``observability`` module (ADR-0003).

The transactional outbox table name is a module contract; the
T6a boundary checker (#26) verifies it matches the schema table.
"""

from __future__ import annotations

OBSERVABILITY_OUTBOX_TABLE = "observability_outbox"
