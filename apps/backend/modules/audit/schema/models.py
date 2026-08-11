"""MOD-011: SQLAlchemy models for the ``audit`` schema only (ADR-0003).

Table namespace rule (coding-standards §2, T6a checker #26):
every table is prefixed with ``audit_`` and lives in
the ``audit`` schema. Models are added incrementally
as Phase 2 tickets land.
"""

from __future__ import annotations

from sqlalchemy import BigInteger, Column, MetaData, Table

MODULE_METADATA = MetaData(schema="audit")


audit_identities = Table(
    "audit_identities",
    MODULE_METADATA,
    Column("id", BigInteger, primary_key=True),
)
