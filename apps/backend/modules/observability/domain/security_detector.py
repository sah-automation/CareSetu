"""MOD-013: the security detector's pure core (PHASE-14B Batch 2, #779).

The five-minute worker scan reads already-aggregated
``observability_security_signals`` rows, so every decision here is a
database-free function over those rows. Two families of alert live in this
module:

* threshold kinds (``auth_failure_high`` and friends) count a whole signal kind
  over a rolling window and raise ONE standing alert while the count stays at or
  above its configured limit. The alert resolves itself when the window falls
  back below the limit, using the same ``(kind, scope)`` and resolve vocabulary
  as the nightly rollup.
* irreversible kinds (``otp_lockout`` and friends) represent one incident each.
  Their scope is the contributing signal ROW, so a retry or an overlapping pass
  cannot raise the same incident twice, and no later empty window can pretend
  the event did not happen.

The cooldown applies to the threshold family only. An irreversible alert is
already one-per-incident; suppressing a second lockout because it followed the
first within thirty minutes would hide a real event rather than prevent a storm.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from app.config import (
    DEFAULT_SECURITY_DETECTOR_AUTH_FAILURE_THRESHOLD,
    DEFAULT_SECURITY_DETECTOR_COOLDOWN_SECONDS,
    DEFAULT_SECURITY_DETECTOR_OPERATOR_MFA_FAILURE_THRESHOLD,
    DEFAULT_SECURITY_DETECTOR_PROMPT_INJECTION_THRESHOLD,
    DEFAULT_SECURITY_DETECTOR_RATE_LIMIT_THRESHOLD,
    DEFAULT_SECURITY_DETECTOR_RECORD_DENIAL_THRESHOLD,
    DEFAULT_SECURITY_DETECTOR_WINDOW_MINUTES,
)
from modules.observability.domain.consumer import (
    ALERT_SEVERITY_CRITICAL,
    ALERT_SEVERITY_WARNING,
    AlertRow,
)
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
    alert_key,
    alert_kind_resolves,
)

#: Signal kinds already produced by the #777 consumers, plus the kinds later
#: tickets reserve: rate limiting (#761), prompt injection (#780), and webhook
#: signature failure (#781). The detector names all of them now so a producer
#: cannot invent a second spelling later.
SECURITY_SIGNAL_AUTH_FAILURE = "auth_failure"
SECURITY_SIGNAL_OTP_FAILURE = "otp_failure"
SECURITY_SIGNAL_OTP_LOCKOUT = "otp_lockout"
SECURITY_SIGNAL_OPERATOR_MFA_FAILURE = "operator_mfa_failure"
SECURITY_SIGNAL_OPERATOR_MFA_LOCKOUT = "operator_mfa_lockout"
SECURITY_SIGNAL_RECORD_DENIAL = "record_denial"
SECURITY_SIGNAL_CONSENT_REVOCATION = "consent_revocation"
SECURITY_SIGNAL_RATE_LIMIT = "rate_limit"
SECURITY_SIGNAL_PROMPT_INJECTION = "prompt_injection"
SECURITY_SIGNAL_WEBHOOK_SIGNATURE_FAILURE = "webhook_signature_failure"

#: The ``payload.source`` marker on every detector alert. The nightly rollup's
#: own loader sees these rows too, but never resolves them: its evaluated-key
#: set names only its own kinds.
SECURITY_ALERT_SOURCE = "security"

#: Threshold alerts scope the whole platform, not a subject. A per-subject alert
#: would turn one distributed attack into one alert per account.
_SECURITY_ALERT_SCOPE = "platform_total"

#: The scan cadence the ticket pins: five minutes. Not a setting, because the
#: acceptance criterion is the cadence itself, not a tunable. The window and
#: cooldown beside it are configurable.
SECURITY_SCAN_INTERVAL_SECONDS = 300


@dataclass(frozen=True)
class SecurityThresholdRule:
    """One signal kind whose count raises one standing alert kind."""

    signal_kind: str
    alert_kind: str
    title: str


@dataclass(frozen=True)
class SecurityIrreversibleRule:
    """One signal kind where each row is a complete, irreversible incident."""

    signal_kind: str
    alert_kind: str
    title: str


#: The count-based half of the vocabulary. Order is stable so a pass raises the
#: alerts in the same order every time, which keeps logs and tests readable.
#: OTP delivery failures are operational (``reason="delivery"``) per #761/#777
#: and are not paged as security alerts ("do not page internal causes").
SECURITY_THRESHOLD_RULES: tuple[SecurityThresholdRule, ...] = (
    SecurityThresholdRule(
        SECURITY_SIGNAL_AUTH_FAILURE,
        ALERT_KIND_AUTH_FAILURE_HIGH,
        "Elevated authentication failures",
    ),
    SecurityThresholdRule(
        SECURITY_SIGNAL_OPERATOR_MFA_FAILURE,
        ALERT_KIND_OPERATOR_MFA_FAILURE_HIGH,
        "Elevated operator MFA failures",
    ),
    SecurityThresholdRule(
        SECURITY_SIGNAL_RECORD_DENIAL,
        ALERT_KIND_RECORD_DENIAL_HIGH,
        "Elevated record denials",
    ),
    SecurityThresholdRule(
        SECURITY_SIGNAL_RATE_LIMIT,
        ALERT_KIND_RATE_LIMIT_HIGH,
        "Elevated rate-limit responses",
    ),
    SecurityThresholdRule(
        SECURITY_SIGNAL_PROMPT_INJECTION,
        ALERT_KIND_PROMPT_INJECTION_HIGH,
        "Elevated prompt-injection findings",
    ),
)

#: The one-event half of the vocabulary. None of these kinds appears in
#: :data:`RESOLVABLE_ALERT_KINDS`, so no later pass can close them.
SECURITY_IRREVERSIBLE_RULES: tuple[SecurityIrreversibleRule, ...] = (
    SecurityIrreversibleRule(
        SECURITY_SIGNAL_OTP_LOCKOUT,
        ALERT_KIND_OTP_LOCKOUT,
        "OTP lockout recorded",
    ),
    SecurityIrreversibleRule(
        SECURITY_SIGNAL_OPERATOR_MFA_LOCKOUT,
        ALERT_KIND_OPERATOR_MFA_LOCKOUT,
        "Operator MFA lockout recorded",
    ),
    SecurityIrreversibleRule(
        SECURITY_SIGNAL_CONSENT_REVOCATION,
        ALERT_KIND_CONSENT_REVOCATION,
        "Consent revocation recorded",
    ),
    SecurityIrreversibleRule(
        SECURITY_SIGNAL_WEBHOOK_SIGNATURE_FAILURE,
        ALERT_KIND_WEBHOOK_SIGNATURE_FAILURE,
        "Webhook signature failure recorded",
    ),
)

_THRESHOLD_RULES_BY_SIGNAL = {rule.signal_kind: rule for rule in SECURITY_THRESHOLD_RULES}
_IRREVERSIBLE_RULES_BY_SIGNAL = {rule.signal_kind: rule for rule in SECURITY_IRREVERSIBLE_RULES}


@dataclass(frozen=True)
class SecurityDetectorThresholds:
    """The configured limits one detector pass reads.

    ``threshold`` fields are counts within ``window_minutes``. ``cooldown_seconds``
    gates a NEW threshold alert after a previous one of the same kind; it never
    delays a resolve and never suppresses an irreversible incident.
    """

    auth_failure: int = DEFAULT_SECURITY_DETECTOR_AUTH_FAILURE_THRESHOLD
    operator_mfa_failure: int = DEFAULT_SECURITY_DETECTOR_OPERATOR_MFA_FAILURE_THRESHOLD
    record_denial: int = DEFAULT_SECURITY_DETECTOR_RECORD_DENIAL_THRESHOLD
    rate_limit: int = DEFAULT_SECURITY_DETECTOR_RATE_LIMIT_THRESHOLD
    prompt_injection: int = DEFAULT_SECURITY_DETECTOR_PROMPT_INJECTION_THRESHOLD
    window_minutes: int = DEFAULT_SECURITY_DETECTOR_WINDOW_MINUTES
    cooldown_seconds: int = DEFAULT_SECURITY_DETECTOR_COOLDOWN_SECONDS

    def threshold_for(self, signal_kind: str) -> int:
        """The configured count for ``signal_kind``; unknown kinds have none."""
        thresholds = {
            SECURITY_SIGNAL_AUTH_FAILURE: self.auth_failure,
            SECURITY_SIGNAL_OPERATOR_MFA_FAILURE: self.operator_mfa_failure,
            SECURITY_SIGNAL_RECORD_DENIAL: self.record_denial,
            SECURITY_SIGNAL_RATE_LIMIT: self.rate_limit,
            SECURITY_SIGNAL_PROMPT_INJECTION: self.prompt_injection,
        }
        return thresholds[signal_kind]


@dataclass(frozen=True)
class SecuritySignalRow:
    """The narrow view of one ``observability_security_signals`` row."""

    row_id: int
    signal_kind: str
    minute_ts: datetime
    count: int


@dataclass(frozen=True)
class SecurityStandingAlert:
    """One open or acknowledged alert the detector owns, keyed by scope."""

    alert_id: UUID
    kind: str
    scope: str

    @property
    def key(self) -> tuple[str, str]:
        return alert_key(
            self.kind,
            {"source": SECURITY_ALERT_SOURCE, "scope": self.scope},
        )


@dataclass(frozen=True)
class SecurityScanPlan:
    """What one detector pass would insert and resolve."""

    alerts: tuple[AlertRow, ...]
    resolved_alert_ids: tuple[UUID, ...]
    evaluated_keys: frozenset[tuple[str, str]]


def _threshold_payload(
    rule: SecurityThresholdRule,
    *,
    observed: int,
    thresholds: SecurityDetectorThresholds,
) -> dict[str, Any]:
    return {
        "source": SECURITY_ALERT_SOURCE,
        "scope": _SECURITY_ALERT_SCOPE,
        "signal_kind": rule.signal_kind,
        "observed": observed,
        "threshold": thresholds.threshold_for(rule.signal_kind),
        "window_minutes": thresholds.window_minutes,
    }


def _irreversible_payload(rule: SecurityIrreversibleRule, row: SecuritySignalRow) -> dict[str, Any]:
    return {
        "source": SECURITY_ALERT_SOURCE,
        "scope": f"incident:{row.row_id}",
        "signal_kind": rule.signal_kind,
        "minute_ts": row.minute_ts.isoformat(),
        "count": row.count,
    }


def plan_security_scan(
    rows: Sequence[SecuritySignalRow],
    *,
    now: datetime,
    thresholds: SecurityDetectorThresholds,
    standing: Sequence[SecurityStandingAlert],
    last_raised_at: Mapping[str, datetime],
) -> SecurityScanPlan:
    """Decide one detector pass from already-loaded rows and alert state.

    ``rows`` is the window the adapter loaded; this function does not filter by
    time again, so the adapter owns the exact half-open boundary. ``standing`` is
    every open or acknowledged detector alert (not only today's), and
    ``last_raised_at`` is the newest alert creation time per kind, used for the
    threshold cooldown.
    """
    standing_by_key = {alert.key: alert for alert in standing}
    counts: dict[str, int] = {rule.signal_kind: 0 for rule in SECURITY_THRESHOLD_RULES}
    for row in rows:
        if row.signal_kind in counts:
            counts[row.signal_kind] += row.count

    alerts: list[AlertRow] = []
    evaluated: set[tuple[str, str]] = set()
    fired: set[tuple[str, str]] = set()

    for rule in SECURITY_THRESHOLD_RULES:
        key = alert_key(
            rule.alert_kind,
            {"source": SECURITY_ALERT_SOURCE, "scope": _SECURITY_ALERT_SCOPE},
        )
        evaluated.add(key)

        observed = counts[rule.signal_kind]
        # One incident produces one alert: if operator MFA lockouts occurred
        # in this window, the irreversible lockout alert is the incident alert
        # and we must not also page on the failure threshold.
        if (
            rule.alert_kind == ALERT_KIND_OPERATOR_MFA_FAILURE_HIGH
            and counts.get(SECURITY_SIGNAL_OPERATOR_MFA_LOCKOUT, 0) > 0
        ):
            continue
        threshold = thresholds.threshold_for(rule.signal_kind)
        if observed < threshold:
            continue

        # The condition is ACTIVE whether or not an alert already exists. Mark it
        # fired before the standing check, otherwise the resolve step below would
        # close a standing alert that this same pass just observed above its limit.
        fired.add(key)
        if key in standing_by_key:
            continue

        last_raised = last_raised_at.get(rule.alert_kind)
        if last_raised is not None and now - last_raised < timedelta(
            seconds=thresholds.cooldown_seconds
        ):
            continue

        alerts.append(
            AlertRow(
                severity=ALERT_SEVERITY_WARNING,
                kind=rule.alert_kind,
                title=rule.title,
                payload=_threshold_payload(rule, observed=observed, thresholds=thresholds),
            )
        )

    for row in rows:
        incident = _IRREVERSIBLE_RULES_BY_SIGNAL.get(row.signal_kind)
        if incident is None or row.count <= 0:
            continue
        payload = _irreversible_payload(incident, row)
        key = alert_key(incident.alert_kind, payload)
        if key in standing_by_key:
            continue
        alerts.append(
            AlertRow(
                severity=ALERT_SEVERITY_CRITICAL,
                kind=incident.alert_kind,
                title=incident.title,
                payload=payload,
            )
        )

    resolved: list[UUID] = []
    for alert in standing:
        key = alert.key
        if key in evaluated and key not in fired and alert_kind_resolves(alert.kind):
            resolved.append(alert.alert_id)

    return SecurityScanPlan(
        alerts=tuple(alerts),
        resolved_alert_ids=tuple(resolved),
        evaluated_keys=frozenset(evaluated),
    )
