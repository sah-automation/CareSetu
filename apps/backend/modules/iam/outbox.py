"""MOD-001: outbox table contract for the ``iam`` module (ADR-0003).

The transactional outbox table name is a module contract; the
T6a boundary checker (#26) verifies it matches the schema table.
"""

from __future__ import annotations

IAM_OUTBOX_TABLE = "iam_outbox"
