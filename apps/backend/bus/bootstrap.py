"""Canonical list of private module schemas (ADR-0003, PHASE-1 T1b #18).

One private PostgreSQL schema per bounded context, all eleven created by the
bootstrap migration (``v0.0__bootstrap_schemas``). This tuple is the single
source of truth so the migration, integration tests, and any later harness
agree on the layout.
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
)
