"""MOD-010: SQLAlchemy models for the ``notify`` schema only (ADR-0003).

Table namespace rule (coding-standards §2, T6a checker #26):
every table is prefixed with ``notify_`` and lives in
the ``notify`` schema. Models are added incrementally
as Phase 2 tickets land. The transactional outbox mirrors the shared
``bus/outbox_ddl.py`` shape (single source of truth, ADR-0002).
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    text,
)

from bus.outbox_ddl import outbox_table

MODULE_METADATA = MetaData(schema="notify")


notify_identities = Table(
    "notify_identities",
    MODULE_METADATA,
    Column("id", BigInteger, primary_key=True),
)


notify_notifications = Table(
    "notify_notifications",
    MODULE_METADATA,
    Column("id", BigInteger, primary_key=True),
    # The E.164 recipient (a partner on the gated-activation path, ADR-0009).
    Column("recipient_phone_e164", String(32), nullable=False),
    # The terminal-status body sent to the partner; never a secret.
    Column("message", Text, nullable=False),
    # The channel currently being attempted (ADR-0009: WhatsApp first, SMS
    # fallback). Tracks the fallback chain so a ``notification.failed`` on the
    # SMS leg is not re-routed into an endless WhatsApp loop.
    Column("channel", String(20), nullable=False, server_default=text("'wa'")),
    # Delivery lifecycle: ``pending`` -> ``delivering`` -> ``delivered``, or a
    # failed terminal state after the fallback chain is exhausted.
    Column("status", String(20), nullable=False, server_default=text("'pending'")),
    # The last provider error code/category for this delivery attempt (no raw
    # provider payloads, error-handling-observability).
    Column("last_error_code", String(50), nullable=True),
    Column("delivery_attempts", Integer, nullable=False, server_default=text("0")),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    CheckConstraint(
        "channel IN ('wa', 'sms')",
        name="ck_notify_notifications_channel",
    ),
    CheckConstraint(
        "status IN ('pending', 'delivering', 'delivered', 'failed')",
        name="ck_notify_notifications_status",
    ),
)


notify_outbox = outbox_table("notify_outbox", "notify", MODULE_METADATA)
