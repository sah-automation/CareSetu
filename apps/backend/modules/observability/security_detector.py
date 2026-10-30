"""MOD-013: the security detector adapter (PHASE-14B Batch 2, #779).

Reads the recent ``observability_security_signals`` window and the detector's
standing alerts, asks the pure core what one pass decides, then writes the new
alerts and resolves the cleared standing ones in one transaction. The worker
schedules this five-minute pass behind ``SECURITY_DETECTION_ENABLED``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from modules.observability.domain.rollup import (
    ALERT_STATUS_ACKNOWLEDGED,
    ALERT_STATUS_OPEN,
    ALERT_STATUS_RESOLVED,
)
from modules.observability.domain.security_detector import (
    SECURITY_ALERT_SOURCE,
    SecurityDetectorThresholds,
    SecurityScanPlan,
    SecuritySignalRow,
    SecurityStandingAlert,
    plan_security_scan,
)
from modules.observability.schema.models import (
    observability_alert_events,
    observability_security_signals,
)


@dataclass(frozen=True)
class SecurityScanReport:
    """What one detector pass wrote."""

    alerts_raised: int
    alerts_resolved: int


async def _load_signal_rows(
    connection: AsyncConnection,
    *,
    window_start: datetime,
    now: datetime,
) -> list[SecuritySignalRow]:
    table = observability_security_signals
    statement = select(
        table.c.id,
        table.c.signal_kind,
        table.c.minute_ts,
        table.c.count,
    ).where(
        table.c.minute_ts >= window_start,
        table.c.minute_ts <= now,
    )
    rows = (await connection.execute(statement)).all()
    return [
        SecuritySignalRow(
            row_id=row_id,
            signal_kind=signal_kind,
            minute_ts=minute_ts,
            count=count,
        )
        for row_id, signal_kind, minute_ts, count in rows
    ]


async def _load_standing_alerts(connection: AsyncConnection) -> list[SecurityStandingAlert]:
    table = observability_alert_events
    statement = select(table.c.id, table.c.kind, table.c.payload).where(
        table.c.status.in_((ALERT_STATUS_OPEN, ALERT_STATUS_ACKNOWLEDGED))
    )
    rows = (await connection.execute(statement)).all()
    standing: list[SecurityStandingAlert] = []
    for alert_id, kind, payload in rows:
        if not isinstance(payload, dict):
            continue
        if payload.get("source") != SECURITY_ALERT_SOURCE:
            continue
        scope = payload.get("scope")
        if not isinstance(scope, str) or not scope:
            continue
        standing.append(SecurityStandingAlert(alert_id=alert_id, kind=kind, scope=scope))
    return standing


async def _load_last_raised(
    connection: AsyncConnection,
    *,
    now: datetime,
    cooldown_seconds: int,
) -> dict[str, datetime]:
    table = observability_alert_events
    statement = (
        select(table.c.kind, func.max(table.c.created_at))
        .where(
            table.c.created_at >= now - timedelta(seconds=cooldown_seconds),
            table.c.payload.op("->>")("source") == SECURITY_ALERT_SOURCE,
        )
        .group_by(table.c.kind)
    )
    rows = (await connection.execute(statement)).all()
    return {kind: created_at for kind, created_at in rows if created_at is not None}


async def run_security_scan(
    engine: AsyncEngine,
    *,
    thresholds: SecurityDetectorThresholds,
    now: datetime | None = None,
) -> SecurityScanReport:
    """Run one five-minute security detector pass.

    ``now`` exists for deterministic tests; the scheduled callback omits it and
    the pass reads the clock in UTC.
    """
    resolved_now = now if now is not None else datetime.now(UTC)
    window_start = resolved_now - timedelta(minutes=thresholds.window_minutes)
    async with engine.begin() as connection:
        rows = await _load_signal_rows(
            connection,
            window_start=window_start,
            now=resolved_now,
        )
        standing = await _load_standing_alerts(connection)
        last_raised_at = await _load_last_raised(
            connection,
            now=resolved_now,
            cooldown_seconds=thresholds.cooldown_seconds,
        )
        plan: SecurityScanPlan = plan_security_scan(
            rows,
            now=resolved_now,
            thresholds=thresholds,
            standing=standing,
            last_raised_at=last_raised_at,
        )

        for alert in plan.alerts:
            await connection.execute(
                insert(observability_alert_events).values(
                    severity=alert.severity,
                    kind=alert.kind,
                    title=alert.title,
                    payload=alert.payload,
                )
            )

        resolved = 0
        if plan.resolved_alert_ids:
            result = await connection.execute(
                update(observability_alert_events)
                .where(
                    observability_alert_events.c.id.in_(plan.resolved_alert_ids),
                    observability_alert_events.c.status.in_(
                        (ALERT_STATUS_OPEN, ALERT_STATUS_ACKNOWLEDGED)
                    ),
                )
                .values(status=ALERT_STATUS_RESOLVED)
            )
            resolved = int(result.rowcount or 0)
    return SecurityScanReport(alerts_raised=len(plan.alerts), alerts_resolved=resolved)


# Re-exported for the facade's public surface; the worker never imports this
# module directly (modules reach the composition root through ``facade``).
__all__ = ["SecurityScanReport", "run_security_scan"]
