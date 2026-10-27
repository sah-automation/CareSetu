"""MOD-013: alert delivery core - router, drainer, and channel adapters.

The router creates one delivery row per alert and enabled channel based on
notification routing settings. The drainer uses skip-locked semantics with
exponential backoff to deliver. Feature-gated off by default.
"""

from __future__ import annotations

import asyncio
import json
import logging
import smtplib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from modules.observability.schema.models import (
    observability_alert_delivery,
    observability_alert_events,
)
from modules.ops.facade import OpsFacade

logger = logging.getLogger(__name__)


class DeliveryStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DELIVERED = "delivered"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"


class Channel(StrEnum):
    SLACK = "slack"
    EMAIL = "email"


@dataclass(frozen=True)
class DeliveryRow:
    id: int
    alert_id: UUID
    channel: str
    status: str
    attempts: int
    next_retry_at: datetime | None
    last_attempt_at: datetime | None
    delivered_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class AlertRow:
    id: UUID
    severity: str
    kind: str
    title: str
    payload: dict[str, Any]
    status: str
    created_at: datetime


@dataclass(frozen=True)
class DeliveryAttemptResult:
    success: bool
    error: str | None = None
    response: dict[str, Any] | None = None


@dataclass(frozen=True)
class AlertDeliveryConfig:
    """Configuration for alert delivery behavior."""

    max_attempts: int = 5
    base_backoff_seconds: int = 30
    max_backoff_seconds: int = 3600
    console_base_url: str = "https://console.example.com"


class ChannelAdapter(Protocol):
    """Protocol for notification channel adapters."""

    channel_name: str

    async def send(
        self,
        alert: AlertRow,
        console_url: str,
    ) -> DeliveryAttemptResult: ...


class SlackAdapter:
    """Slack webhook channel adapter."""

    channel_name = "slack"

    def __init__(self, webhook_url: str) -> None:
        self._webhook_url = webhook_url

    async def send(
        self,
        alert: AlertRow,
        console_url: str,
    ) -> DeliveryAttemptResult:
        import httpx

        payload = {
            "text": f"*{alert.title}*",
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": f"[{alert.severity.upper()}] {alert.title}",
                        "emoji": True,
                    },
                },
                {
                    "type": "section",
                    "fields": [
                        {
                            "type": "mrkdwn",
                            "text": f"*Kind:*\n{alert.kind}",
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Alert ID:*\n{alert.id}",
                        },
                    ],
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Details:*\n```{json.dumps(alert.payload, indent=2)}```",
                    },
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {
                                "type": "plain_text",
                                "text": "View in Console",
                                "emoji": True,
                            },
                            "url": console_url,
                            "style": "primary",
                        }
                    ],
                },
            ],
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(self._webhook_url, json=payload)
                response.raise_for_status()
                return DeliveryAttemptResult(
                    success=True, response=response.json() if response.content else {}
                )
        except Exception as e:
            return DeliveryAttemptResult(success=False, error=str(e))


class SmtpAdapter:
    """SMTP email channel adapter."""

    channel_name = "email"

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        from_addr: str,
        to_addrs: list[str],
        use_tls: bool = True,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._from_addr = from_addr
        self._to_addrs = to_addrs
        self._use_tls = use_tls

    async def send(
        self,
        alert: AlertRow,
        console_url: str,
    ) -> DeliveryAttemptResult:
        from email.mime.multipart import MIMEMultipart

        subject = f"[{alert.severity.upper()}] {alert.title}"
        body = (
            f"Alert Kind: {alert.kind}\n"
            f"Alert ID: {alert.id}\n"
            f"Severity: {alert.severity}\n"
            f"Title: {alert.title}\n\n"
            f"Details:\n{json.dumps(alert.payload, indent=2)}\n\n"
            f"View in Console: {console_url}"
        )

        msg = MIMEMultipart()
        msg["From"] = self._from_addr
        msg["To"] = ", ".join(self._to_addrs)
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._send_sync, msg)
            return DeliveryAttemptResult(success=True)
        except Exception as e:
            return DeliveryAttemptResult(success=False, error=str(e))

    def _send_sync(self, msg: MIMEMultipart) -> None:
        if self._use_tls:
            server = smtplib.SMTP(self._host, self._port)
            server.starttls()
        else:
            server = smtplib.SMTP_SSL(self._host, self._port)
        try:
            server.login(self._username, self._password)
            server.send_message(msg)
        finally:
            server.quit()


class FakeAdapter:
    """Fake/test channel adapter for testing."""

    channel_name = "fake"

    def __init__(self) -> None:
        self.sent_alerts: list[tuple[AlertRow, str]] = []
        self.should_fail = False
        self.fail_error = "fake failure"

    async def send(
        self,
        alert: AlertRow,
        console_url: str,
    ) -> DeliveryAttemptResult:
        self.sent_alerts.append((alert, console_url))
        if self.should_fail:
            return DeliveryAttemptResult(success=False, error=self.fail_error)
        return DeliveryAttemptResult(success=True, response={"fake": True})

    def reset(self) -> None:
        self.sent_alerts.clear()
        self.should_fail = False


def compute_next_retry(attempt: int, config: AlertDeliveryConfig) -> datetime:
    """Compute next retry time with exponential backoff and jitter."""
    import secrets

    base = min(
        config.base_backoff_seconds * (2 ** (attempt - 1)),
        config.max_backoff_seconds,
    )
    jitter = base * 0.1 * secrets.randbelow(1000) / 1000.0
    return datetime.now(UTC) + timedelta(seconds=base + jitter)


async def get_enabled_channels_for_alert(
    connection: AsyncConnection,
    alert_kind: str,
    ops_facade: OpsFacade,
) -> list[Channel]:
    """Determine which channels should receive this alert based on routing settings.

    Routing value can be a comma-separated list (e.g. "slack,email") or "none".
    """
    effective_settings = await ops_facade.get_effective_settings()

    # Valid routing targets (defined locally to avoid cross-module import)
    _VALID_ROUTING_TARGETS = {"slack", "email", "none"}

    # Get routing for this alert kind
    routing_key = f"notification.routing.{alert_kind}"
    routing_value = "none"
    for setting in effective_settings:
        if setting.key == routing_key and setting.value is not None:
            routing_value = str(setting.value).strip()
            break

    # Parse comma-separated routing targets
    routing_targets = [t.strip().lower() for t in routing_value.split(",") if t.strip()]

    # Validate each target
    valid_targets = [t for t in routing_targets if t in _VALID_ROUTING_TARGETS]

    # Check which channels are enabled
    channel_enabled: dict[str, bool] = {}
    for setting in effective_settings:
        if setting.key == "notification.channels.slack.enabled":
            channel_enabled["slack"] = setting.value is True
        elif setting.key == "notification.channels.email.enabled":
            channel_enabled["email"] = setting.value is True

    channels: list[Channel] = []
    for target in valid_targets:
        if target == "slack" and channel_enabled.get("slack", False):
            channels.append(Channel.SLACK)
        elif target == "email" and channel_enabled.get("email", False):
            channels.append(Channel.EMAIL)

    return channels


async def get_console_url(alert: AlertRow, config: AlertDeliveryConfig) -> str:
    """Generate console URL for the alert."""
    base_url = config.console_base_url
    return f"{base_url}/observability/alerts/{alert.id}"


async def route_new_alerts(
    engine: AsyncEngine,
    ops_facade: OpsFacade,
    batch_size: int = 100,
) -> int:
    """Router job: create delivery rows for newly opened alerts.

    Finds alerts with status='open' that don't have delivery rows yet,
    determines enabled channels for each, and inserts delivery rows.
    """
    router_count = 0
    async with engine.begin() as connection:
        # Find open alerts without delivery rows
        stmt = (
            select(observability_alert_events.c.id, observability_alert_events.c.kind)
            .where(
                observability_alert_events.c.status == "open",
                ~observability_alert_events.c.id.in_(
                    select(observability_alert_delivery.c.alert_id).distinct()
                ),
            )
            .limit(batch_size)
        )
        result = await connection.execute(stmt)
        alerts = [(row.id, row.kind) for row in result]

        for alert_id, alert_kind in alerts:
            channels = await get_enabled_channels_for_alert(connection, alert_kind, ops_facade)
            for channel in channels:
                # Check if delivery row already exists
                existing = await connection.execute(
                    select(observability_alert_delivery.c.id).where(
                        observability_alert_delivery.c.alert_id == alert_id,
                        observability_alert_delivery.c.channel == channel.value,
                    )
                )
                if existing.first():
                    continue

                await connection.execute(
                    insert(observability_alert_delivery).values(
                        alert_id=alert_id,
                        channel=channel.value,
                        status=DeliveryStatus.PENDING.value,
                        attempts=0,
                    )
                )
                router_count += 1

    if router_count:
        logger.info("alert router created %d delivery row(s)", router_count)
    return router_count


async def _claim_deliveries(
    connection: AsyncConnection,
    limit: int,
    config: AlertDeliveryConfig,
) -> list[DeliveryRow]:
    """Claim pending deliveries using skip-locked."""

    # Use FOR UPDATE SKIP LOCKED to claim rows
    stmt = (
        select(observability_alert_delivery)
        .where(
            observability_alert_delivery.c.status.in_(
                [DeliveryStatus.PENDING.value, DeliveryStatus.FAILED.value]
            ),
            observability_alert_delivery.c.attempts < config.max_attempts,
            observability_alert_delivery.c.next_retry_at.is_(None)
            | (observability_alert_delivery.c.next_retry_at <= datetime.now(UTC)),
        )
        .order_by(
            observability_alert_delivery.c.next_retry_at.nullsfirst(),
            observability_alert_delivery.c.created_at,
        )
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    result = await connection.execute(stmt)
    rows = result.mappings().all()
    return [DeliveryRow(**row) for row in rows]


async def _mark_in_progress(connection: AsyncConnection, delivery_id: int) -> None:
    await connection.execute(
        update(observability_alert_delivery)
        .where(observability_alert_delivery.c.id == delivery_id)
        .values(
            status=DeliveryStatus.IN_PROGRESS.value,
            last_attempt_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
    )


async def _mark_delivered(connection: AsyncConnection, delivery_id: int) -> None:
    await connection.execute(
        update(observability_alert_delivery)
        .where(observability_alert_delivery.c.id == delivery_id)
        .values(
            status=DeliveryStatus.DELIVERED.value,
            delivered_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
    )


async def _mark_failed(
    connection: AsyncConnection,
    delivery_id: int,
    attempt: int,
    config: AlertDeliveryConfig,
) -> None:
    next_retry = (
        compute_next_retry(attempt + 1, config) if attempt + 1 < config.max_attempts else None
    )
    new_status = (
        DeliveryStatus.DEAD_LETTER.value if next_retry is None else DeliveryStatus.FAILED.value
    )
    await connection.execute(
        update(observability_alert_delivery)
        .where(observability_alert_delivery.c.id == delivery_id)
        .values(
            status=new_status,
            attempts=attempt + 1,
            next_retry_at=next_retry,
            last_attempt_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
    )


async def _get_alert(connection: AsyncConnection, alert_id: UUID) -> AlertRow | None:
    stmt = select(observability_alert_events).where(observability_alert_events.c.id == alert_id)
    result = await connection.execute(stmt)
    row = result.mappings().first()
    if not row:
        return None
    return AlertRow(
        id=row["id"],
        severity=row["severity"],
        kind=row["kind"],
        title=row["title"],
        payload=row["payload"],
        status=row["status"],
        created_at=row["created_at"],
    )


async def _raise_delivery_failure_alert(
    connection: AsyncConnection,
    alert: AlertRow,
    channel: str,
    error: str,
) -> None:
    """Raise a delivery-failure alert that is NOT routed to the failing channel."""
    from modules.observability.domain.consumer import ALERT_SEVERITY_CRITICAL
    from modules.observability.domain.consumer import AlertRow as ConsumerAlertRow

    failure_alert = ConsumerAlertRow(
        severity=ALERT_SEVERITY_CRITICAL,
        kind="delivery_failure",
        title=f"Alert delivery failed for {alert.kind} via {channel}",
        payload={
            "original_alert_id": str(alert.id),
            "original_alert_kind": alert.kind,
            "failed_channel": channel,
            "error": error,
        },
    )

    # Insert directly to avoid circular routing
    await connection.execute(
        insert(observability_alert_events).values(
            severity=failure_alert.severity,
            kind=failure_alert.kind,
            title=failure_alert.title,
            payload=failure_alert.payload,
        )
    )


async def drain_deliveries(
    engine: AsyncEngine,
    ops_facade: OpsFacade,
    adapters: dict[str, ChannelAdapter],
    batch_size: int = 50,
    config: AlertDeliveryConfig | None = None,
) -> int:
    """Drainer job: process claimed delivery rows with exponential backoff."""
    if config is None:
        config = AlertDeliveryConfig()
    drain_count = 0

    async with engine.begin() as connection:
        claimed = await _claim_deliveries(connection, batch_size, config)
        for delivery in claimed:
            await _mark_in_progress(connection, delivery.id)

            alert = await _get_alert(connection, delivery.alert_id)
            if not alert:
                logger.warning("alert %s not found for delivery %s", delivery.alert_id, delivery.id)
                await _mark_failed(connection, delivery.id, delivery.attempts, config)
                continue

            adapter = adapters.get(delivery.channel)
            if not adapter:
                logger.warning("no adapter for channel %s", delivery.channel)
                await _mark_failed(connection, delivery.id, delivery.attempts, config)
                continue

            console_url = await get_console_url(alert, config)
            result = await adapter.send(alert, console_url)

            if result.success:
                await _mark_delivered(connection, delivery.id)
                drain_count += 1
            else:
                await _mark_failed(connection, delivery.id, delivery.attempts, config)
                # Raise delivery failure alert (NOT routed to failing channel)
                await _raise_delivery_failure_alert(
                    connection, alert, delivery.channel, result.error or "unknown error"
                )
                logger.warning("delivery %s failed: %s", delivery.id, result.error)

    if drain_count:
        logger.info("alert drainer delivered %d notification(s)", drain_count)
    return drain_count


async def redeliver_alert(
    engine: AsyncEngine,
    delivery_id: int,
) -> bool:
    """Admin redelivery: reset a dead_letter or failed delivery to pending."""
    async with engine.begin() as connection:
        stmt = select(observability_alert_delivery).where(
            observability_alert_delivery.c.id == delivery_id,
            observability_alert_delivery.c.status.in_(
                [DeliveryStatus.FAILED.value, DeliveryStatus.DEAD_LETTER.value]
            ),
        )
        result = await connection.execute(stmt)
        row = result.mappings().first()
        if not row:
            return False

        await connection.execute(
            update(observability_alert_delivery)
            .where(observability_alert_delivery.c.id == delivery_id)
            .values(
                status=DeliveryStatus.PENDING.value,
                attempts=0,
                next_retry_at=None,
                last_attempt_at=None,
                updated_at=datetime.now(UTC),
            )
        )
        logger.info("alert delivery %s reset for redelivery", delivery_id)
        return True


async def test_delivery(
    engine: AsyncEngine,
    channel: str,
    adapters: dict[str, ChannelAdapter],
    test_alert: AlertRow | None = None,
    config: AlertDeliveryConfig | None = None,
) -> DeliveryAttemptResult:
    """Send a test notification via the specified channel."""
    if config is None:
        config = AlertDeliveryConfig()
    adapter = adapters.get(channel)
    if not adapter:
        return DeliveryAttemptResult(success=False, error=f"no adapter for channel {channel}")

    if test_alert is None:
        test_alert = AlertRow(
            id=UUID("00000000-0000-0000-0000-000000000000"),
            severity="warning",
            kind="test_delivery",
            title="Test Alert Delivery",
            payload={"message": "This is a test notification from CareSetu alert delivery"},
            status="open",
            created_at=datetime.now(UTC),
        )

    console_url = await get_console_url(test_alert, config)
    return await adapter.send(test_alert, console_url)


# Job entry points for APScheduler


async def run_alert_router_job(
    engine: AsyncEngine,
    ops_facade: OpsFacade,
) -> None:
    """Router job entry point - scheduled periodically."""
    try:
        await route_new_alerts(engine, ops_facade)
    except Exception:
        logger.exception("alert router job failed")


async def run_alert_drainer_job(
    engine: AsyncEngine,
    ops_facade: OpsFacade,
    adapters: dict[str, ChannelAdapter],
    config: AlertDeliveryConfig | None = None,
) -> None:
    """Drainer job entry point - scheduled frequently."""
    try:
        await drain_deliveries(engine, ops_facade, adapters, config=config)
    except Exception:
        logger.exception("alert drainer job failed")
