"""PHASE-14A T31 (#748): generate the Grafana dashboards, datasource and alert rules.

The operator's Grafana stack was console-clicked configuration: a dashboard edit
left no diff, no review and no revert, and an alert rule could be changed by
anyone with a browser and nobody with a commit. This generator turns that
configuration back into repository files - a read-only PostgreSQL datasource onto
the ``observability`` schema, one provisioned dashboard, and a capped set of alert
rules - so a change to any of them is a reviewable, revertible commit.

**Why a generator and not hand-written JSON.** Grafana dashboard JSON is long,
deeply nested and full of ids and coordinates a human edits by accident. Spelling
it once in Python means the panel list, the datasource UID and the alert cap are
each declared in exactly one place, and the checked-in artefact is a pure function
of this file. ``tests/unit/test_grafana_assets.py`` regenerates the asset and
asserts it still equals the committed copy, so a hand-edit to the JSON (or a drift
between the two) fails the suite rather than silently becoming the deployed
dashboard - the same generator-plus-committed-output pattern the OpenAPI slice
exporter uses (``scripts/export_openapi_schemas.py``).

**The datasource is READ-ONLY and points at the observability schema.** Grafana
must never write back into the platform's Postgres: the operator dashboard is a
read surface, and a datasource with write access to the system of record is a
standing footgun. Every panel's SQL is fully schema-qualified
(``observability.<table>``), so the business and product numbers render from the
same system of record the operator APIs read rather than from a vendor's
14-day window (ADR-0024 D2).

**No panel calls a vendor API.** A panel that shelled out to the AI tracing
vendor on refresh would exhaust the free tier's hundred-request-a-day ceiling in
an afternoon; Grafana reads Postgres and nothing else
(third-party-integration-standards.md §1, story 111).

**The active-series alert is set BELOW the ceiling.** Grafana Cloud's free tier
allows ten thousand active series with no overage: crossing it drops data
silently, so the alert that guards it fires early rather than at the wall
(#717 decision 38, story 105). The alert rule set is capped at
:data:`MAX_ALERT_RULES` so nobody suffers alert fatigue inside a generous vendor
allowance (story 104) - a new rule has to argue a rule out to earn its place.

**No unbounded status label.** A panel grouped by a raw HTTP status code
multiplies series without bound; the dashboards group by the four-value
``status_class`` vocabulary the collector already collapses response status into
(``observability.error_capture``), so the cardinality the free tier spends is
bounded by construction (#717 decision 37, story 106).

Usage:
    node scripts/py.cjs apps/backend/scripts/gen_grafana_assets.py
    node scripts/py.cjs apps/backend/scripts/gen_grafana_assets.py --check
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ASSET_ROOT = REPO_ROOT / "deploy" / "grafana" / "provisioning"

# The UID the operator console deep-links to (#736). Imported rather than
# re-spelled: the constant lives beside the link that uses it, and a provisioning
# file that declared a different UID would send every Grafana link in the console
# to a 404 - the exact drift #748 exists to prevent, so the generator reads the
# one source of truth and the test asserts they agree.
sys.path.insert(0, str(REPO_ROOT / "apps" / "backend"))
from modules.observability.domain.deeplinks import GRAFANA_DASHBOARD_UID  # noqa: E402

DASHBOARD_UID = GRAFANA_DASHBOARD_UID

#: The Grafana "organisation"-scoped identifier the datasource is provisioned
#: under. Fixed, because the provisioning file names it and the dashboard panels
#: resolve their datasource by it.
DATASOURCE_UID = "caresetu-observability-postgres"

#: The datasource UID the alert rules' QUERY node runs against - the deployment's
#: metrics backend (Grafana Cloud's own Prometheus/Mimir), NOT the read-only
#: Postgres datasource the panels use. That datasource is provisioned by the
#: deployment, so a hard-coded UID would point the rule at a datasource the stack
#: may not own; Grafana interpolates this ``$VAR`` at provisioning time, so the
#: operator binds it in the environment (see ``deploy/grafana/README.md``). An
#: unset variable resolves to empty, which the operator sees as a rule that loads
#: but finds no data - visible, not silently pointed at the wrong series.
METRICS_DATASOURCE_UID_ENV = "GRAFANA_METRICS_DATASOURCE_UID"

#: The Postgres schema every panel reads. The datasource is pinned to it and every
#: query is qualified with it, so the business and product numbers come from the
#: system of record (ADR-0024 D2) rather than from a vendor window.
OBSERVABILITY_SCHEMA = "observability"

#: Grafana Cloud's free-tier active-series allowance. A hard stop with no
#: overage: crossing it silently drops telemetry, which is why the alert below
#: fires early rather than at the wall (#717 "known ceiling").
ACTIVE_SERIES_CEILING = 10_000

#: Where the active-series alert fires. Deliberately BELOW the ceiling: the whole
#: point of the rule is to warn while there is still headroom to shed a label
#: before data is lost silently (#717 decision 38, story 105).
ACTIVE_SERIES_ALERT_THRESHOLD = 8_000

#: The small deliberate cap on alert rules (story 104). Enforced by the generator
#: test, so adding a rule is a conscious argument rather than an accumulation -
#: alert fatigue is what makes every alert ignorable, and the vendor allowance is
#: generous enough that the number here is a choice, not a limit.
MAX_ALERT_RULES = 6

#: The four-value status vocabulary the collector collapses response status into
#: (``observability.error_capture.STATUS_CLASS_*``). Named here because a panel
#: that grouped by a raw status CODE would multiply series without bound; grouping
#: by these four is the cardinality firewall at the dashboard layer (story 106).
STATUS_CLASSES: tuple[str, ...] = ("2xx", "3xx", "4xx", "5xx")

#: The default dashboard window, matching the console deep-link default so a link
#: and a hand-opened dashboard land on the same range.
DEFAULT_WINDOW = "now-6h"


class GrafanaAssetError(RuntimeError):
    """A generated asset failed its own invariants before it was written."""


@dataclass(frozen=True, slots=True)
class Panel:
    """One dashboard panel: an id, a title, and the SQL that answers it.

    ``sql`` is schema-qualified and status-class collapsed by the panel builders
    below; the ``grid`` is the (x, y, w, h) position so the layout is a pure
    function of this list rather than hand-tuned coordinates.
    """

    id: int
    title: str
    sql: str
    grid: tuple[int, int, int, int]
    unit: str | None = None
    panel_type: str = "timeseries"


@dataclass(frozen=True, slots=True)
class AlertRule:
    """One provisioned alert rule.

    A Grafana alert is not a bare expression: it is a small pipeline of *data
    nodes* - a query that loads the series and an expression that reduces and
    thresholds it - and the rule's ``condition`` names the node whose verdict
    fires the alert. ``expr`` is the PromQL the query node runs; ``reducer`` and
    ``threshold`` build the threshold node that fires when ``reducer(series)
    > threshold`` (the documented Grafana Cloud shape).
    """

    uid: str
    title: str
    summary: str
    expr: str
    for_duration: str
    severity: str
    threshold: float
    #: How the query node's series collapses before the threshold compares it -
    #: ``last`` for a gauge (active series, in-flight), ``sum`` for a counter rate.
    reducer: str = "last"
    #: ``gt`` (fires above the threshold, the common case) or ``lt`` (fires below
    #: it - the liveness rule, where a rate that HAS gone quiet is the alarm).
    comparison: str = "gt"


def _panel(
    panel_id: int,
    title: str,
    sql: str,
    *,
    col: int,
    row: int,
    unit: str | None = None,
    panel_type: str = "timeseries",
) -> Panel:
    """One panel on a two-column grid; ``col``/``row`` are grid cells."""
    return Panel(
        id=panel_id,
        title=title,
        sql=sql,
        grid=(col * 12, row * 8, 12, 8),
        unit=unit,
        panel_type=panel_type,
    )


def build_panels() -> tuple[Panel, ...]:
    """Every dashboard panel, in layout order.

    The panel set is the union of the three lenses' system-of-record sources: HTTP
    throughput and error rate (reliability), the per-provider board (reliability,
    stories 36-40), queue depth and age (reliability, #729), AI usage and cost
    (business), the registry-driven business daily store (#737), and the product
    funnel rollup (#743). Every one of them reads ``observability.<table>`` - none
    of them touches a vendor.
    """
    return (
        _panel(
            1,
            "Request throughput",
            _sql(
                """
                SELECT minute_ts AS time, sum(requests) AS requests
                FROM {schema}.observability_http_minute
                WHERE $__timeFilter(minute_ts)
                GROUP BY minute_ts
                ORDER BY minute_ts
                """
            ),
            col=0,
            row=0,
            unit="reqpm",
        ),
        _panel(
            2,
            "Error rate (5xx over all)",
            _sql(
                """
                SELECT minute_ts AS time,
                       sum(errors)::float / nullif(sum(requests), 0) AS error_rate
                FROM {schema}.observability_http_minute
                WHERE $__timeFilter(minute_ts)
                GROUP BY minute_ts
                ORDER BY minute_ts
                """
            ),
            col=1,
            row=0,
            unit="percentunit",
        ),
        _panel(
            3,
            "Requests by status class",
            # Grouped by the four-value status CLASS, never by a raw status code:
            # grouping by code is the unbounded-cardinality mistake the collector
            # exists to prevent (story 106).
            _sql(
                """
                SELECT minute_ts AS time, status_class, sum(requests) AS requests
                FROM {schema}.observability_http_minute
                WHERE $__timeFilter(minute_ts)
                GROUP BY minute_ts, status_class
                ORDER BY minute_ts
                """
            ),
            col=0,
            row=1,
            unit="short",
        ),
        _panel(
            4,
            "Provider success rate",
            _sql(
                """
                SELECT provider, success_rate
                FROM {schema}.observability_ai_provider_health
                ORDER BY provider
                """
            ),
            col=1,
            row=1,
            unit="percentunit",
        ),
        _panel(
            5,
            "Provider latency (p50/p95/p99)",
            _sql(
                """
                SELECT provider, p50_duration_ms, p95_duration_ms, p99_duration_ms
                FROM {schema}.observability_ai_provider_health
                ORDER BY provider
                """
            ),
            col=0,
            row=2,
            unit="ms",
        ),
        _panel(
            6,
            "Provider throttling and timeouts",
            # Stories 38-39: rate-limit rejections and timeouts are the two signals
            # that separate "we are being throttled" from "the provider is slow".
            _sql(
                """
                SELECT provider, rate_limit_count, timeout_count
                FROM {schema}.observability_ai_provider_health
                ORDER BY provider
                """
            ),
            col=1,
            row=2,
            unit="short",
        ),
        _panel(
            7,
            "AI queue depth by leg",
            _sql(
                """
                SELECT $__timeGroupAlias(now(), '1m'), queue, count(*) AS depth
                FROM {schema}.observability_ai_queue_open
                GROUP BY queue
                ORDER BY queue
                """
            ),
            col=0,
            row=3,
            unit="short",
        ),
        _panel(
            8,
            "Oldest open AI queue age",
            _sql(
                """
                SELECT $__timeGroupAlias(now(), '1m'), queue,
                       EXTRACT(EPOCH FROM (now() - min(enqueued_at))) AS age_seconds
                FROM {schema}.observability_ai_queue_open
                GROUP BY queue
                ORDER BY queue
                """
            ),
            col=1,
            row=3,
            unit="s",
        ),
        _panel(
            9,
            "AI usage and spend (per day)",
            _sql(
                """
                SELECT usage_date AS time, provider, sum(cost_paise) AS cost_paise
                FROM {schema}.observability_ai_usage_daily
                WHERE $__timeFilter(usage_date)
                GROUP BY usage_date, provider
                ORDER BY usage_date
                """
            ),
            col=0,
            row=4,
            unit="short",
        ),
        _panel(
            10,
            "Product funnel events (per day)",
            _sql(
                """
                SELECT event_date AS time, funnel, step, sum(events) AS events
                FROM {schema}.observability_product_daily
                WHERE $__timeFilter(event_date)
                GROUP BY event_date, funnel, step
                ORDER BY event_date
                """
            ),
            col=1,
            row=4,
            unit="short",
        ),
        _panel(
            11,
            "Business daily registry",
            _sql(
                """
                SELECT metric_date AS time, metric_key, (value->>'count')::float AS value
                FROM {schema}.observability_business_daily
                WHERE $__timeFilter(metric_date) AND value ? 'count'
                ORDER BY metric_date
                """
            ),
            col=0,
            row=5,
            unit="short",
        ),
        _panel(
            12,
            "Open alerts by severity",
            # Bucketed in time and grouped by SEVERITY (one of four-ish values),
            # never by ``created_at``: grouping a timeseries by a per-row timestamp
            # makes every distinct instant its own series - the same
            # unbounded-cardinality mistake as grouping by a raw status code
            # (story 106). The bucket is the time axis; severity is the breakdown.
            _sql(
                """
                SELECT $__timeGroupAlias(created_at, '1h') AS time,
                       severity, count(*) AS open_alerts
                FROM {schema}.observability_alert_events
                WHERE status = 'open'
                GROUP BY 1, severity
                ORDER BY 1
                """
            ),
            col=1,
            row=5,
            unit="short",
        ),
    )


def _sql(body: str) -> str:
    """Normalise a panel query: qualify the schema and collapse whitespace.

    ``body`` is a static triple-quoted template with a ``{schema}`` placeholder;
    the single schema constant is substituted here via ``str.replace`` so the SQL
    text is assembled without the string concatenation bandit flags as a
    (false-positive) injection vector. Whitespace is then collapsed to single
    spaces, so the committed SQL is the text a reader sees rather than the
    artefact of how it was wrapped.
    """
    return " ".join(body.replace("{schema}", OBSERVABILITY_SCHEMA).split())


def build_alert_rules() -> tuple[AlertRule, ...]:
    """The capped set of alert rules, including the active-series guard.

    The set is deliberately small and infrastructure-focused, because a Grafana
    alert evaluates a TIME SERIES and the platform's domain alarms are not series:
    an AI provider going degraded, a stalled queue and a spend outlier are raised
    by the observability module's own alert feed (``observability_alert_events``)
    and surfaced through the operator console, so a Grafana rule duplicating them
    would be a second, drifting answer to the same question.

    What is left is what only Grafana can see - the telemetry pipeline's own
    health:

    * the **active-series guard**, which exists because the free tier's ceiling is a
      hard stop with no overage: it fires BELOW the ceiling so the operator sheds a
      label before ingestion is dropped (#717 decision 38, story 105);
    * the **error-capture liveness** rule, so an empty error feed is never mistaken
      for a healthy platform (story 35);
    * the **outbox dead-letter** rule, grounded on the dispatcher's own
      ``caresetu.outbox.dead_lettered`` counter;
    * the **in-flight saturation** rule, grounded on the platform's recorded
      ``caresetu.http.server.inflight`` UpDownCounter.
    """
    rules = (
        AlertRule(
            uid="caresetu-active-series",
            title="Active series approaching the free-tier ceiling",
            summary=(
                "Active series is within 80 percent of Grafana Cloud's free-tier "
                "ceiling of 10000. Exceeding it drops telemetry silently, so shed a "
                "label now."
            ),
            # Grafana Cloud's usage metric, exported by the stack's own
            # ``grafanacloud-usage`` datasource. It is the one signal that says how
            # much of the free tier's series allowance is spent.
            expr="max(grafanacloud_instance_active_series)",
            for_duration="10m",
            # Warning, not critical: there is headroom left, and the rule exists to
            # give the operator time to act - a critical that fires while nothing is
            # yet broken trains the operator to ignore it.
            severity="warning",
            threshold=float(ACTIVE_SERIES_ALERT_THRESHOLD),
        ),
        AlertRule(
            uid="caresetu-error-capture-dead",
            title="Error capture stalled",
            summary="No requests recorded in ten minutes: the capture path itself is down.",
            # Grounded on the platform's own exported histogram
            # (``caresetu.http.server.duration`` -> ``_count``); a rate of zero over
            # a busy service means the capture path, not the platform, is quiet.
            expr="sum(rate(caresetu_http_server_duration_count[10m]))",
            for_duration="10m",
            severity="warning",
            threshold=1.0,
            reducer="last",
            # Fires when the rate drops BELOW one: quiet is the alarm here.
            comparison="lt",
        ),
        AlertRule(
            uid="caresetu-outbox-dead-letter",
            title="Outbox rows dead-lettered",
            summary="The dispatcher dead-lettered an outbox row; a delivery gave up.",
            # Grounded on ``caresetu.outbox.dead_lettered`` (observability.otel).
            expr="increase(caresetu_outbox_dead_lettered_total[15m])",
            for_duration="5m",
            severity="critical",
            threshold=0.0,
            reducer="sum",
        ),
        AlertRule(
            uid="caresetu-inflight-saturation",
            title="Request concurrency saturated",
            summary="In-flight requests are sustained high; the service is near saturation.",
            # Grounded on ``caresetu.http.server.inflight`` (observability.otel,
            # HTTP_INFLIGHT_METRIC).
            expr="max(caresetu_http_server_inflight)",
            for_duration="10m",
            severity="warning",
            threshold=50.0,
        ),
    )
    if len(rules) > MAX_ALERT_RULES:
        raise GrafanaAssetError(
            f"{len(rules)} alert rules exceed the deliberate cap of {MAX_ALERT_RULES}; "
            "adding a rule means removing one or raising the cap on purpose"
        )
    return rules


def assert_no_unbounded_status_label(panels: Sequence[Panel]) -> None:
    """Every panel that GROUPS BY a status label must group by the CLASS, never a code.

    A raw status code (``200``, ``404``, ...) in a ``GROUP BY`` multiplies series
    without bound; the four-value ``status_class`` vocabulary is the firewall
    (story 106). The rule is deliberately about the GROUP BY clause and not about
    the word "status" appearing anywhere: a ``WHERE status = 'open'`` filter on the
    alert feed collapses to one series and is fine, while the same column in a
    ``GROUP BY`` is the cardinality regression. Asserted in the generator rather
    than reviewed by eye, because a cardinality regression is invisible until the
    vendor's ceiling is hit.
    """
    for panel in panels:
        grouped = _grouped_labels(panel.sql)
        for label in grouped:
            if "status" not in label:
                continue
            if label != "status_class":
                raise GrafanaAssetError(
                    f"panel {panel.id} ({panel.title!r}) groups by {label!r}; a raw "
                    "status label is unbounded - group by status_class instead"
                )


def assert_status_class_vocabulary(panels: Sequence[Panel]) -> None:
    """The dashboard must carry a panel grouping by the full ``status_class`` set.

    The four classes are named in :data:`STATUS_CLASSES` and nowhere else, so this
    both keeps that constant load-bearing and fails a dashboard that dropped the
    per-class breakdown panel the reliability lens reads.
    """
    for panel in panels:
        if "status_class" in _grouped_labels(panel.sql):
            return
    raise GrafanaAssetError(
        "no panel groups by status_class; the free tier's cardinality firewall "
        f"({', '.join(STATUS_CLASSES)}) must back a dashboard panel"
    )


def _grouped_labels(sql: str) -> tuple[str, ...]:
    """The comma-separated labels in a query's ``GROUP BY`` clause, lowercased.

    A deliberately small parser: it reads from ``group by`` to the end of the
    statement and splits on commas, which is enough for the flat panel SQL this
    generator emits and avoids pulling a SQL parser into a stdlib-only tool.
    """
    lowered = sql.lower()
    marker = "group by"
    index = lowered.find(marker)
    if index == -1:
        return ()
    tail = sql[index + len(marker) :]
    # A trailing ORDER BY (or a closing paren) ends the group list.
    for terminator in ("order by", "limit", ")"):
        cut = tail.lower().find(terminator)
        if cut != -1:
            tail = tail[:cut]
    return tuple(part.strip().strip('"').lower() for part in tail.split(",") if part.strip())


def build_datasource() -> dict[str, Any]:
    """The read-only PostgreSQL datasource onto the observability schema.

    ``readOnly`` is true and ``editable`` is false: the operator dashboard is a
    read surface, and a datasource that could write into the system of record is a
    standing footgun. The schema is pinned to ``observability`` and every panel
    qualifies its tables, so the numbers render from the system of record rather
    than a vendor window (ADR-0024 D2, stories 103-105).
    """
    # A Grafana environment-variable reference, resolved on the Grafana host
    # against the read-only role's password; no secret is committed
    # (security-phii-standards.md §3). The key is ``password`` because that is what
    # Grafana reads, but the VALUE is a placeholder, so this is not a credential.
    secure: dict[str, str] = {"password": "${CARESETU_DB_READONLY_PASSWORD}"}  # nosec B105
    json_data: dict[str, Any] = {
        "sslmode": "require",
        "postgresVersion": 1600,
        "schema": OBSERVABILITY_SCHEMA,
        "readOnly": True,
    }
    entry: dict[str, Any] = {
        "name": "CareSetu Observability (Postgres)",
        "uid": DATASOURCE_UID,
        "type": "postgres",
        "access": "proxy",
        "url": "${CARESETU_DB_HOST}:${CARESETU_DB_PORT}",
        "database": "${CARESETU_DB_NAME}",
        "user": "${CARESETU_DB_READONLY_USER}",
        "secureJsonData": secure,
        "jsonData": json_data,
        "editable": False,
    }
    return {"apiVersion": 1, "datasources": [entry]}


def build_dashboard() -> dict[str, Any]:
    """The provisioned dashboard, a pure function of :func:`build_panels`.

    The UID is :data:`DASHBOARD_UID` - the constant the operator console deep-links
    to (#736) - declared once and imported here so the two cannot drift.
    """
    panels = build_panels()
    assert_no_unbounded_status_label(panels)
    assert_status_class_vocabulary(panels)
    return {
        "uid": DASHBOARD_UID,
        "title": "CareSetu Observability",
        "tags": ["caresetu", "observability"],
        "timezone": "browser",
        "editable": False,
        "schemaVersion": 39,
        "time": {"from": DEFAULT_WINDOW, "to": "now"},
        "templating": {
            "list": [
                {
                    "name": "service",
                    "type": "textbox",
                    "label": "Service",
                    "query": "caresetu",
                    "current": {"text": "caresetu", "value": "caresetu"},
                },
                {
                    "name": "env",
                    "type": "textbox",
                    "label": "Environment",
                    "query": "production",
                    "current": {"text": "production", "value": "production"},
                },
            ]
        },
        "panels": [_panel_json(panel) for panel in panels],
    }


def _panel_json(panel: Panel) -> dict[str, Any]:
    """One panel's Grafana JSON, with its datasource and target wired by UID."""
    x, y, w, h = panel.grid
    field_config: dict[str, Any] = {"defaults": {}, "overrides": []}
    if panel.unit is not None:
        field_config["defaults"]["unit"] = panel.unit
    return {
        "id": panel.id,
        "title": panel.title,
        "type": panel.panel_type,
        "datasource": {"type": "postgres", "uid": DATASOURCE_UID},
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "fieldConfig": field_config,
        "targets": [
            {
                "refId": "A",
                "datasource": {"type": "postgres", "uid": DATASOURCE_UID},
                "format": "time_series",
                "rawSql": panel.sql,
            }
        ],
    }


def build_dashboard_provider() -> dict[str, Any]:
    """The provisioned dashboard-provider file, so Grafana loads the JSON on boot."""
    return {
        "apiVersion": 1,
        "providers": [
            {
                "name": "caresetu",
                "orgId": 1,
                "folder": "CareSetu",
                "type": "file",
                "disableDeletion": True,
                "updateIntervalSeconds": 30,
                "editable": False,
                "options": {"path": "/etc/grafana/provisioning/dashboards/caresetu"},
            }
        ],
    }


#: Seconds of history each rule's query loads, keyed by the rule's ``for`` window.
#: Grafana evaluates on this range; a reduced value is compared against the
#: threshold, so the range must cover at least the window the alert reasons over.
_RULE_LOOKBACK_SECONDS = 600


def _threshold_condition(rule: AlertRule) -> dict[str, Any]:
    """The threshold expression node's conditions - the operator the rule fires on."""
    return {
        "evaluator": {"type": rule.comparison, "params": [rule.threshold]},
        "operator": {"type": "and"},
        "query": {"params": ["A"]},
        "reducer": {"type": rule.reducer},
        "type": "query",
    }


def build_alerting_provider() -> dict[str, Any]:
    """The provisioned alert-rules file, so the rules load from configuration.

    Each rule is Grafana's documented two-node pipeline: an ``A`` QUERY node that
    loads the series from the metrics backend, and a ``B`` expression node that
    reduces the series (``reducer``) and compares it to the rule's ``threshold``.
    The rule's ``condition`` names ``B`` (the expression), which is what actually
    decides firing - a rule with only a query node has nothing to evaluate and
    never fires. The query node's datasource is the interpolated
    :data:`METRICS_DATASOURCE_UID_ENV`, so the deployment binds it rather than the
    repository guessing a UID (Grafana does not interpolate inside ``model``, so
    the ``$VAR`` lives on ``datasourceUid``).
    """
    rules = build_alert_rules()
    return {
        "apiVersion": 1,
        "groups": [
            {
                "orgId": 1,
                "name": "caresetu-observability",
                "folder": "CareSetu",
                "interval": "1m",
                "rules": [
                    {
                        "uid": rule.uid,
                        "title": rule.title,
                        "condition": "B",
                        "for": rule.for_duration,
                        "noDataState": "NoData",
                        "execErrState": "Error",
                        "labels": {"severity": rule.severity},
                        "annotations": {"summary": rule.summary},
                        "data": [
                            {
                                "refId": "A",
                                "datasourceUid": f"${METRICS_DATASOURCE_UID_ENV}",
                                "relativeTimeRange": {
                                    "from": _RULE_LOOKBACK_SECONDS,
                                    "to": 0,
                                },
                                "model": {
                                    "expr": rule.expr,
                                    "instant": True,
                                    "refId": "A",
                                },
                            },
                            {
                                "refId": "B",
                                "datasourceUid": "__expr__",
                                "relativeTimeRange": {
                                    "from": _RULE_LOOKBACK_SECONDS,
                                    "to": 0,
                                },
                                "model": {
                                    "conditions": [_threshold_condition(rule)],
                                    "datasource": {"type": "__expr__", "uid": "__expr__"},
                                    "expression": "A",
                                    "refId": "B",
                                    "type": "threshold",
                                },
                            },
                        ],
                    }
                    for rule in rules
                ],
            }
        ],
    }


def _render_json(document: dict[str, Any]) -> str:
    """Serialise a Grafana dashboard as JSON - the format the dashboard file uses."""
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


def _yaml_scalar(value: Any) -> str:
    """One scalar as a YAML token, quoting only when the plain form would lie.

    JSON's ``true``/``false``/``null`` are YAML's too, so booleans and null fall
    through the same way; only strings that would read as another type (a bare
    number, a bool word, or one carrying YAML punctuation) are quoted.
    """
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return "null"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        # A bare number, not a string: Grafana's threshold evaluator reads the
        # param as a numeric value, so ``8000.0`` must not be quoted.
        return repr(value)
    text = str(value)
    ambiguous = (
        text == ""
        or text.strip() != text
        or text.lower() in {"true", "false", "null", "yes", "no", "on", "off"}
        or _looks_numeric(text)
        or any(char in text for char in ":#{}[]&*!|>'\"%@`,")
    )
    if ambiguous:
        return json.dumps(text)
    return text


def _looks_numeric(text: str) -> bool:
    """Whether ``text`` would parse as a number, so it must be quoted as a string."""
    try:
        float(text)
    except ValueError:
        return False
    return True


def _render_yaml(node: Any, indent: int = 0) -> str:
    """Serialise a mapping/list tree as block-style YAML, deterministically.

    The provisioning files are YAML because that is the format Grafana documents
    and the format a reviewer diffs most easily. Emitting it here keeps the
    generator stdlib-only (no PyYAML) while producing the same bytes on every
    machine: mapping keys are emitted in the order the builders declare them, so a
    re-run is a no-op and a real change is the only diff.
    """
    pad = " " * indent
    if isinstance(node, dict):
        if not node:
            return pad + "{}\n"
        lines: list[str] = []
        for key, value in node.items():
            rendered_key = _yaml_scalar(key)
            if (isinstance(value, dict) and value) or (isinstance(value, list) and value):
                lines.append(f"{pad}{rendered_key}:\n{_render_yaml(value, indent + 2)}")
            elif isinstance(value, dict):
                lines.append(f"{pad}{rendered_key}: {{}}\n")
            elif isinstance(value, list):
                lines.append(f"{pad}{rendered_key}: []\n")
            else:
                lines.append(f"{pad}{rendered_key}: {_yaml_scalar(value)}\n")
        return "".join(lines)
    if isinstance(node, list):
        lines = []
        for item in node:
            if isinstance(item, (dict, list)) and item:
                body = _render_yaml(item, indent + 2)
                # Splice the first line up to the ``- `` marker.
                first, _, rest = body.partition("\n")
                lines.append(f"{pad}- {first.lstrip()}\n")
                if rest:
                    lines.append(rest)
            else:
                lines.append(f"{pad}- {_yaml_scalar(item)}\n")
        return "".join(lines)
    return pad + _yaml_scalar(node) + "\n"


def build_assets() -> dict[str, str]:
    """Every generated asset as ``relative-path -> rendered text``.

    The dashboard itself is Grafana's native JSON (the format its own UI exports
    and imports); the three provisioning files around it - the dashboard provider,
    the datasource and the alert rules - are YAML, which is what Grafana documents
    and what a reviewer diffs most easily.
    """
    return {
        "dashboards/caresetu-provider.yaml": _render_yaml(build_dashboard_provider()),
        "dashboards/caresetu/caresetu-observability.json": _render_json(build_dashboard()),
        "datasources/caresetu-postgres.yaml": _render_yaml(build_datasource()),
        "alerting/caresetu-alerts.yaml": _render_yaml(build_alerting_provider()),
    }


def write_assets(asset_root: Path) -> list[Path]:
    """Write every generated asset under ``asset_root``; return the paths written."""
    written: list[Path] = []
    for relative, text in build_assets().items():
        destination = asset_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        # ``newline="\n"`` keeps the generated bytes LF on every platform, so a
        # Windows checkout writes the exact file the repository stores and the
        # drift check compares like for like.
        destination.write_text(text, encoding="utf-8", newline="\n")
        written.append(destination)
    return written


def check_assets(asset_root: Path) -> list[Path]:
    """Return the committed assets that are stale against a fresh generation."""
    stale: list[Path] = []
    for relative, text in build_assets().items():
        destination = asset_root / relative
        # Compare raw bytes, not translated text: the generator writes LF on every
        # platform, so a Windows checkout must not pass by normalising CRLF. Bytes
        # rather than ``read_text(newline=...)`` keeps this on Python 3.11, which
        # this repo targets.
        if not destination.is_file() or destination.read_bytes() != text.encode("utf-8"):
            stale.append(destination)
    return stale


def main(argv: Sequence[str] | None = None) -> int:
    """Write the Grafana assets, or ``--check`` for drift; exit 0 on success."""
    parser = argparse.ArgumentParser(
        description="Generate the Grafana dashboards, datasource and alert rules (#748).",
    )
    parser.add_argument(
        "--asset-root",
        type=Path,
        default=DEFAULT_ASSET_ROOT,
        help=f"provisioning root (default: {DEFAULT_ASSET_ROOT})",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="do not write; exit 1 when a committed asset is stale",
    )
    args = parser.parse_args(argv)

    try:
        # ``build_assets`` runs the invariant guards (status vocabulary, alert cap),
        # so a generator change that violates one fails here rather than being
        # written - on both the write and the ``--check`` path.
        assets = build_assets()
    except GrafanaAssetError as exc:
        print(f"grafana asset generation FAILED: {exc}", file=sys.stderr)
        return 1

    if args.check:
        stale = check_assets(args.asset_root)
        for path in stale:
            print(f"stale: {path}", file=sys.stderr)
        if stale:
            print(
                "grafana asset check FAILED: regenerate with\n"
                "  node scripts/py.cjs apps/backend/scripts/gen_grafana_assets.py",
                file=sys.stderr,
            )
            return 1
        print(f"grafana asset check OK: {len(assets)} asset(s) match the generator")
        return 0

    written = write_assets(args.asset_root)
    for path in written:
        print(f"wrote {path}")
    print(f"grafana asset generation OK: wrote {len(written)} asset(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
