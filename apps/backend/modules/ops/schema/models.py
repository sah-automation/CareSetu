"""MOD-014: SQLAlchemy models for the ``ops`` schema only (ADR-0003).

Table namespace rule (coding-standards §2, T6a checker #26): every table is
prefixed with ``ops_`` and lives in the ``ops`` schema. The module is the
configuration module (spec #761 §Configuration module), not a domain bounded
context; it owns no domain tables, no PHI, and no secrets. #764 creates the
storage scaffold only - the effective-settings read, writes, history, and
feature-flag behavior arrive in later tickets.

Column shapes are defined by the same-name ``v9.9__init_ops`` migration.
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from bus.outbox_ddl import consumed_events_table, outbox_table

MODULE_METADATA = MetaData(schema="ops")


ops_settings = Table(
    "ops_settings",
    MODULE_METADATA,
    Column("id", BigInteger, primary_key=True),
    Column("setting_key", String(200), nullable=False),
    Column("value", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("version", Integer, nullable=False, server_default=text("1")),
    Column("updated_by", BigInteger, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    UniqueConstraint("setting_key", name="uq_ops_settings_key"),
)


ops_setting_history = Table(
    "ops_setting_history",
    MODULE_METADATA,
    Column("id", BigInteger, primary_key=True),
    Column("setting_key", String(200), nullable=False),
    Column("value", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("version", Integer, nullable=False),
    Column("changed_by", BigInteger, nullable=True),
    Column("changed_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    Index("ix_ops_setting_history_key", "setting_key", "changed_at"),
)


ops_feature_flags = Table(
    "ops_feature_flags",
    MODULE_METADATA,
    Column("id", BigInteger, primary_key=True),
    Column("flag_key", String(200), nullable=False),
    Column("enabled", Boolean, nullable=False, server_default=text("false")),
    Column("flag_kind", String(20), nullable=False, server_default=text("'runtime'")),
    Column("description", Text, nullable=True),
    Column("updated_by", BigInteger, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    Column("version", Integer, nullable=False, server_default=text("1")),
    UniqueConstraint("flag_key", name="uq_ops_feature_flags_key"),
    CheckConstraint(
        "flag_kind IN ('runtime', 'restart_required')",
        name="ck_ops_feature_flags_kind",
    ),
)


ops_feature_flag_history = Table(
    "ops_feature_flag_history",
    MODULE_METADATA,
    Column("id", BigInteger, primary_key=True),
    Column("flag_key", String(200), nullable=False),
    Column("enabled", Boolean, nullable=False),
    Column("flag_kind", String(20), nullable=False),
    Column("version", Integer, nullable=False),
    Column("changed_by", BigInteger, nullable=True),
    Column("changed_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    Index("ix_ops_feature_flag_history_key", "flag_key", "changed_at"),
)


ops_outbox = outbox_table("ops_outbox", "ops", MODULE_METADATA)
ops_consumed_events = consumed_events_table("ops")
