"""Canonical list of private module schemas (ADR-0003, PHASE-1 T1b #18).

One private PostgreSQL schema per bounded context. Eleven schemas are created by
the bootstrap migration (``v0.0__bootstrap_schemas``); the twelfth - the
``observability`` telemetry schema of MOD-013 (PHASE-14A B3, #701) - is created
by its own ``v9.0__init_observability`` migration; the thirteenth - the ``ops``
configuration schema of MOD-014 (PHASE-14B, #764) - by its own
``v9.9__init_ops`` migration. This tuple is the single source of truth so the
migrations, integration tests, and any later harness agree on the layout.
"""

MODULE_SCHEMAS: tuple[str, ...] = (
    "iam",
    "partner",
    "health",
    "consent",
    "intake",
    "care",
    "diagnostics",
    "fulfillment",
    "settlement",
    "notify",
    "audit",
    "observability",
    "ops",
)
