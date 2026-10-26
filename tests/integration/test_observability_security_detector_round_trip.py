"""#779: the security detector against real PostgreSQL.

Seeds the same minute-granular signal rows the #777 consumers leave, runs the
detector's adapter, and asserts the three writes the ticket names: one alert per
threshold condition, one alert per irreversible incident, and a threshold alert
that closes itself once its window clears while an irreversible alert stays open.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from modules.observability.domain.security_detector import SecurityDetectorThresholds
from modules.observability.facade import run_security_scan


async def _seed_signal(
    connection: AsyncConnection,
    *,
    minute_ts: datetime,
    signal_kind: str,
    count: int,
    subject_key: str,
) -> None:
    await connection.execute(
        text(
            "INSERT INTO observability.observability_security_signals "
            "(minute_ts, signal_kind, subject_key, count) "
            "VALUES (:minute_ts, :signal_kind, :subject_key, :count)"
        ),
        {
            "minute_ts": minute_ts,
            "signal_kind": signal_kind,
            "subject_key": subject_key,
            "count": count,
        },
    )


async def _alerts(connection: AsyncConnection) -> list[dict[str, object]]:
    rows = (
        (
            await connection.execute(
                text(
                    "SELECT kind, status, payload FROM observability.observability_alert_events "
                    "ORDER BY kind"
                )
            )
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


async def test_security_scan_raises_once_resolves_thresholds_and_keeps_incidents(
    engine: AsyncEngine,
) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    thresholds = SecurityDetectorThresholds(
        auth_failure=10,
        operator_mfa_failure=1,
        record_denial=10,
        rate_limit=50,
        prompt_injection=10,
        window_minutes=15,
        cooldown_seconds=0,
    )

    async with engine.begin() as connection:
        # Two subjects in the same window sum to 11, over the auth threshold.
        await _seed_signal(
            connection,
            minute_ts=now - timedelta(minutes=6),
            signal_kind="auth_failure",
            count=6,
            subject_key="a" * 64,
        )
        await _seed_signal(
            connection,
            minute_ts=now - timedelta(minutes=2),
            signal_kind="auth_failure",
            count=5,
            subject_key="b" * 64,
        )
        await _seed_signal(
            connection,
            minute_ts=now - timedelta(minutes=1),
            signal_kind="otp_lockout",
            count=1,
            subject_key="c" * 64,
        )
        await _seed_signal(
            connection,
            minute_ts=now - timedelta(minutes=1),
            signal_kind="consent_revocation",
            count=1,
            subject_key="d" * 64,
        )

    first = await run_security_scan(engine, thresholds=thresholds, now=now)
    assert first.alerts_raised == 3
    assert first.alerts_resolved == 0

    async with engine.begin() as connection:
        alerts = await _alerts(connection)
    by_kind = {str(alert["kind"]): alert for alert in alerts}
    assert set(by_kind) == {"auth_failure_high", "otp_lockout", "consent_revocation"}
    assert all(alert["status"] == "open" for alert in alerts)
    for alert in alerts:
        payload = alert["payload"]
        assert isinstance(payload, dict)
        assert payload["source"] == "security"
        assert "subject_key" not in payload
    assert by_kind["auth_failure_high"]["payload"]["observed"] == 11
    assert by_kind["otp_lockout"]["payload"]["scope"].startswith("incident:")

    second = await run_security_scan(engine, thresholds=thresholds, now=now)
    assert second.alerts_raised == 0
    assert second.alerts_resolved == 0

    async with engine.begin() as connection:
        await connection.execute(
            text(
                "DELETE FROM observability.observability_security_signals "
                "WHERE signal_kind = 'auth_failure'"
            )
        )

    cleared = await run_security_scan(engine, thresholds=thresholds, now=now)
    assert cleared.alerts_raised == 0
    assert cleared.alerts_resolved == 1

    async with engine.begin() as connection:
        alerts_after = {str(a["kind"]): a for a in await _alerts(connection)}
    assert alerts_after["auth_failure_high"]["status"] == "resolved"
    assert alerts_after["otp_lockout"]["status"] == "open"
    assert alerts_after["consent_revocation"]["status"] == "open"

    # Removing the irreversible source row does not close its incident alert.
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "DELETE FROM observability.observability_security_signals "
                "WHERE signal_kind = 'otp_lockout'"
            )
        )
    still_open = await run_security_scan(engine, thresholds=thresholds, now=now)
    assert still_open.alerts_resolved == 0
    async with engine.begin() as connection:
        alerts_final = {str(a["kind"]): a for a in await _alerts(connection)}
    assert alerts_final["otp_lockout"]["status"] == "open"


async def test_security_scan_raises_prompt_injection_and_rate_limit_kinds(
    engine: AsyncEngine,
) -> None:
    """The reserved detector kinds are wired before their producers land."""
    now = datetime.now(UTC).replace(microsecond=0)
    thresholds = SecurityDetectorThresholds(
        auth_failure=100,
        operator_mfa_failure=100,
        record_denial=100,
        rate_limit=3,
        prompt_injection=2,
        window_minutes=15,
        cooldown_seconds=1800,
    )

    async with engine.begin() as connection:
        await _seed_signal(
            connection,
            minute_ts=now - timedelta(minutes=1),
            signal_kind="rate_limit",
            count=3,
            subject_key="",
        )
        await _seed_signal(
            connection,
            minute_ts=now - timedelta(minutes=1),
            signal_kind="prompt_injection",
            count=2,
            subject_key="",
        )

    report = await run_security_scan(engine, thresholds=thresholds, now=now)

    assert report.alerts_raised == 2
    async with engine.begin() as connection:
        alerts = {str(a["kind"]) for a in await _alerts(connection)}
    assert alerts == {"rate_limit_high", "prompt_injection_high"}
