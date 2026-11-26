"""Security detector pure core (PHASE-14B Batch 2, #779).

The scan job's decisions are made here, without a database: threshold sums,
cooldown suppression, one alert per irreversible incident, and the resolve
boundary that closes a threshold alert only when its condition has cleared.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from modules.observability.domain.consumer import ALERT_SEVERITY_CRITICAL
from modules.observability.domain.rollup import (
    ALERT_KIND_AUTH_FAILURE_HIGH,
    ALERT_KIND_CONSENT_REVOCATION,
    ALERT_KIND_OPERATOR_MFA_FAILURE_HIGH,
    ALERT_KIND_OPERATOR_MFA_LOCKOUT,
    ALERT_KIND_OTP_LOCKOUT,
    ALERT_KIND_PROMPT_INJECTION_HIGH,
    ALERT_KIND_RATE_LIMIT_HIGH,
    ALERT_KIND_RECORD_DENIAL_HIGH,
    ALERT_KIND_WEBHOOK_SIGNATURE_FAILURE,
    NON_RESOLVABLE_ALERT_KINDS,
    RESOLVABLE_ALERT_KINDS,
    alert_key,
    alert_kind_resolves,
)
from modules.observability.domain.security_detector import (
    SECURITY_ALERT_SOURCE,
    SECURITY_IRREVERSIBLE_RULES,
    SECURITY_SIGNAL_AUTH_FAILURE,
    SECURITY_SIGNAL_CONSENT_REVOCATION,
    SECURITY_SIGNAL_OPERATOR_MFA_FAILURE,
    SECURITY_SIGNAL_OPERATOR_MFA_LOCKOUT,
    SECURITY_SIGNAL_OTP_LOCKOUT,
    SECURITY_SIGNAL_PROMPT_INJECTION,
    SECURITY_SIGNAL_RATE_LIMIT,
    SECURITY_SIGNAL_RECORD_DENIAL,
    SECURITY_SIGNAL_WEBHOOK_SIGNATURE_FAILURE,
    SECURITY_THRESHOLD_RULES,
    SecurityDetectorThresholds,
    SecuritySignalRow,
    SecurityStandingAlert,
    plan_security_scan,
)

_NOW = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)
_THRESHOLDS = SecurityDetectorThresholds(
    auth_failure=10,
    operator_mfa_failure=4,
    record_denial=6,
    rate_limit=12,
    prompt_injection=3,
    window_minutes=15,
    cooldown_seconds=1800,
)


def _row(row_id: int, signal_kind: str, count: int, *, minutes_ago: int = 1) -> SecuritySignalRow:
    return SecuritySignalRow(
        row_id=row_id,
        signal_kind=signal_kind,
        minute_ts=_NOW - timedelta(minutes=minutes_ago),
        count=count,
    )


def _threshold_scope() -> str:
    return "platform_total"


def _standing(kind: str, *, scope: str = "platform_total") -> SecurityStandingAlert:
    return SecurityStandingAlert(alert_id=uuid4(), kind=kind, scope=scope)


def test_threshold_signals_sum_across_rows_and_raise_one_alert() -> None:
    plan = plan_security_scan(
        (
            _row(1, SECURITY_SIGNAL_AUTH_FAILURE, 4),
            _row(2, SECURITY_SIGNAL_AUTH_FAILURE, 7),
        ),
        now=_NOW,
        thresholds=_THRESHOLDS,
        standing=(),
        last_raised_at={},
    )

    assert len(plan.alerts) == 1
    alert = plan.alerts[0]
    assert alert.kind == ALERT_KIND_AUTH_FAILURE_HIGH
    assert alert.severity == "warning"
    assert alert.payload["observed"] == 11
    assert alert.payload["threshold"] == 10
    assert alert.payload["window_minutes"] == 15
    assert "subject_key" not in alert.payload
    assert plan.resolved_alert_ids == ()


def test_threshold_below_the_limit_raises_nothing_and_resolves_the_standing_alert() -> None:
    standing = _standing(ALERT_KIND_AUTH_FAILURE_HIGH)

    plan = plan_security_scan(
        (_row(1, SECURITY_SIGNAL_AUTH_FAILURE, 9),),
        now=_NOW,
        thresholds=_THRESHOLDS,
        standing=(standing,),
        last_raised_at={},
    )

    assert plan.alerts == ()
    assert plan.resolved_alert_ids == (standing.alert_id,)
    key = alert_key(
        ALERT_KIND_AUTH_FAILURE_HIGH,
        {"source": SECURITY_ALERT_SOURCE, "scope": _threshold_scope()},
    )
    assert key in plan.evaluated_keys


def test_a_still_active_threshold_never_resolves_its_standing_alert() -> None:
    standing = _standing(ALERT_KIND_AUTH_FAILURE_HIGH)

    plan = plan_security_scan(
        (_row(1, SECURITY_SIGNAL_AUTH_FAILURE, 10),),
        now=_NOW,
        thresholds=_THRESHOLDS,
        standing=(standing,),
        last_raised_at={},
    )

    assert plan.alerts == ()
    assert plan.resolved_alert_ids == ()


def test_cooldown_suppresses_a_new_threshold_alert_after_one_was_raised() -> None:
    plan = plan_security_scan(
        (_row(1, SECURITY_SIGNAL_AUTH_FAILURE, 10),),
        now=_NOW,
        thresholds=_THRESHOLDS,
        standing=(),
        last_raised_at={ALERT_KIND_AUTH_FAILURE_HIGH: _NOW - timedelta(seconds=1799)},
    )

    assert plan.alerts == ()


def test_cooldown_expiry_allows_a_new_threshold_alert() -> None:
    plan = plan_security_scan(
        (_row(1, SECURITY_SIGNAL_AUTH_FAILURE, 10),),
        now=_NOW,
        thresholds=_THRESHOLDS,
        standing=(),
        last_raised_at={ALERT_KIND_AUTH_FAILURE_HIGH: _NOW - timedelta(seconds=1800)},
    )

    assert [alert.kind for alert in plan.alerts] == [ALERT_KIND_AUTH_FAILURE_HIGH]


def test_irreversible_signals_raise_one_alert_per_signal_row() -> None:
    plan = plan_security_scan(
        (
            _row(41, SECURITY_SIGNAL_OTP_LOCKOUT, 1),
            _row(42, SECURITY_SIGNAL_OTP_LOCKOUT, 2),
            _row(43, SECURITY_SIGNAL_OPERATOR_MFA_LOCKOUT, 1),
            _row(44, SECURITY_SIGNAL_CONSENT_REVOCATION, 1),
        ),
        now=_NOW,
        thresholds=_THRESHOLDS,
        standing=(),
        last_raised_at={},
    )

    assert len(plan.alerts) == 4
    assert {alert.kind for alert in plan.alerts} == {
        ALERT_KIND_OTP_LOCKOUT,
        ALERT_KIND_OPERATOR_MFA_LOCKOUT,
        ALERT_KIND_CONSENT_REVOCATION,
    }
    for alert in plan.alerts:
        assert alert.severity == ALERT_SEVERITY_CRITICAL
        # The incident identity is the signal ROW, never a subject hash.
        assert alert.payload["scope"].startswith("incident:")
        assert "subject_key" not in alert.payload


def test_an_irreversible_alert_is_not_re_raised_and_never_resolved() -> None:
    row = _row(41, SECURITY_SIGNAL_OTP_LOCKOUT, 1)
    key = alert_key(
        ALERT_KIND_OTP_LOCKOUT,
        {"source": SECURITY_ALERT_SOURCE, "scope": "incident:41"},
    )
    standing = SecurityStandingAlert(
        alert_id=uuid4(),
        kind=ALERT_KIND_OTP_LOCKOUT,
        scope="incident:41",
    )

    while_active = plan_security_scan(
        (row,),
        now=_NOW,
        thresholds=_THRESHOLDS,
        standing=(standing,),
        last_raised_at={},
    )
    after_clear = plan_security_scan(
        (),
        now=_NOW,
        thresholds=_THRESHOLDS,
        standing=(standing,),
        last_raised_at={},
    )

    assert while_active.alerts == ()
    assert while_active.resolved_alert_ids == ()
    assert after_clear.alerts == ()
    assert after_clear.resolved_alert_ids == ()
    assert key not in after_clear.evaluated_keys


def test_every_security_alert_kind_is_in_the_shared_resolve_vocabulary() -> None:
    threshold_kinds = {
        ALERT_KIND_AUTH_FAILURE_HIGH,
        ALERT_KIND_OPERATOR_MFA_FAILURE_HIGH,
        ALERT_KIND_RECORD_DENIAL_HIGH,
        ALERT_KIND_RATE_LIMIT_HIGH,
        ALERT_KIND_PROMPT_INJECTION_HIGH,
    }
    irreversible_kinds = {
        ALERT_KIND_OTP_LOCKOUT,
        ALERT_KIND_OPERATOR_MFA_LOCKOUT,
        ALERT_KIND_CONSENT_REVOCATION,
        ALERT_KIND_WEBHOOK_SIGNATURE_FAILURE,
    }

    assert threshold_kinds <= RESOLVABLE_ALERT_KINDS
    assert irreversible_kinds <= NON_RESOLVABLE_ALERT_KINDS
    for kind in threshold_kinds:
        assert alert_kind_resolves(kind), kind
    for kind in irreversible_kinds:
        assert not alert_kind_resolves(kind), kind


def test_every_security_signal_kind_is_handled_by_exactly_one_rule() -> None:
    threshold_kinds = {rule.signal_kind for rule in SECURITY_THRESHOLD_RULES}
    irreversible_kinds = {rule.signal_kind for rule in SECURITY_IRREVERSIBLE_RULES}

    assert not threshold_kinds & irreversible_kinds
    assert threshold_kinds | irreversible_kinds == {
        SECURITY_SIGNAL_AUTH_FAILURE,
        SECURITY_SIGNAL_OTP_LOCKOUT,
        SECURITY_SIGNAL_OPERATOR_MFA_FAILURE,
        SECURITY_SIGNAL_OPERATOR_MFA_LOCKOUT,
        SECURITY_SIGNAL_RECORD_DENIAL,
        SECURITY_SIGNAL_CONSENT_REVOCATION,
        SECURITY_SIGNAL_RATE_LIMIT,
        SECURITY_SIGNAL_PROMPT_INJECTION,
        SECURITY_SIGNAL_WEBHOOK_SIGNATURE_FAILURE,
    }
