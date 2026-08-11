"""MOD-009: SQLAlchemy models for the ``settlement`` schema only (ADR-0003).

Table namespace rule (coding-standards §2, T6a checker #26):
every table is prefixed with ``settlement_`` and lives in
the ``settlement`` schema. Models are added incrementally
as Phase 2 tickets land.
"""

from __future__ import annotations

from sqlalchemy import BigInteger, Column, MetaData, Table

MODULE_METADATA = MetaData(schema="settlement")


settlement_identities = Table(
    "settlement_identities",
    MODULE_METADATA,
    Column("id", BigInteger, primary_key=True),
)
