"""MOD-001: SQLAlchemy models for the ``iam`` schema only (ADR-0003).

Table namespace rule (coding-standards §2, T6a checker #26): every table is
prefixed with ``iam_`` and lives in the ``iam`` schema. Phase 2 T1 (#52) adds
the five-table data foundation; the transactional outbox mirrors the shared
``bus/outbox_ddl.py`` shape (single source of truth, ADR-0002).
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    text,
)

from bus.outbox_ddl import outbox_table

MODULE_METADATA = MetaData(schema="iam")


iam_identities = Table(
    "iam_identities",
    MODULE_METADATA,
    Column("id", BigInteger, primary_key=True),
    Column("phone_e164", String(32), nullable=False),
    Column("status", String(20), nullable=False, server_default=text("'Unverified'")),
    Column(
        "lockout_failed_attempts",
        Integer,
        nullable=False,
        server_default=text("0"),
    ),
    Column("lockout_until", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    UniqueConstraint("phone_e164", name="uq_iam_identities_phone_e164"),
    CheckConstraint(
        "status IN ('Unverified', 'Active', 'Suspended')",
        name="ck_iam_identities_status",
    ),
)

iam_otp_challenges = Table(
    "iam_otp_challenges",
    MODULE_METADATA,
    Column("id", BigInteger, primary_key=True),
    Column(
        "identity_id",
        BigInteger,
        ForeignKey("iam_identities.id", name="fk_iam_otp_challenges_identity"),
        nullable=False,
    ),
    Column("otp_hash", String(128), nullable=False),
    Column("status", String(20), nullable=False, server_default=text("'Pending'")),
    Column("attempts", Integer, nullable=False, server_default=text("0")),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("cooldown_until", DateTime(timezone=True), nullable=True),
    Column("verified_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    CheckConstraint(
        "status IN ('Pending', 'Verified', 'Expired', 'Failed')",
        name="ck_iam_otp_challenges_status",
    ),
)

iam_sessions = Table(
    "iam_sessions",
    MODULE_METADATA,
    Column("id", BigInteger, primary_key=True),
    Column("jti", String(64), nullable=False),
    Column(
        "identity_id",
        BigInteger,
        ForeignKey("iam_identities.id", name="fk_iam_sessions_identity"),
        nullable=False,
    ),
    Column("scope", String(255), nullable=False),
    Column("issued_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("revoked_at", DateTime(timezone=True), nullable=True),
    UniqueConstraint("jti", name="uq_iam_sessions_jti"),
)

iam_role_grants = Table(
    "iam_role_grants",
    MODULE_METADATA,
    Column("id", BigInteger, primary_key=True),
    Column(
        "identity_id",
        BigInteger,
        ForeignKey("iam_identities.id", name="fk_iam_role_grants_identity"),
        nullable=False,
    ),
    Column("role", String(20), nullable=False),
    Column("status", String(20), nullable=False, server_default=text("'Active'")),
    Column("granted_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    Column("revoked_at", DateTime(timezone=True), nullable=True),
    CheckConstraint("role IN ('patient', 'partner', 'operator')", name="ck_iam_role_grants_role"),
    CheckConstraint("status IN ('Active', 'Suspended')", name="ck_iam_role_grants_status"),
)

iam_outbox = outbox_table("iam_outbox", "iam", MODULE_METADATA)
