"""MOD-001: SQLAlchemy models for the ``iam`` schema only (ADR-0003).

Table namespace rule (coding-standards §2, T6a checker #26):
every table is prefixed with ``iam_`` and lives in
the ``iam`` schema. Models are added incrementally
as Phase 2 tickets land.
"""

from __future__ import annotations

from sqlalchemy import BigInteger, Column, MetaData, Table

MODULE_METADATA = MetaData(schema="iam")


iam_identities = Table(
    "iam_identities",
    MODULE_METADATA,
    Column("id", BigInteger, primary_key=True),
)
