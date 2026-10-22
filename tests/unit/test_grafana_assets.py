"""PHASE-14A T31 (#748): the Grafana assets are generated, validated and committed.

The dashboards, the read-only datasource and the alert rules live in the repository
as provisioned files (``deploy/grafana/provisioning/``) so a change to any of them
is reviewable and revertible. This suite is the contract those files must satisfy,
and it asserts the acceptance criteria rather than the console configuration:

* the committed assets still equal a fresh generation (no hand-edit drift);
* the dashboard declares the exact UID the operator console deep-links to (#736);
* required panels are present;
* the datasource is READ-ONLY and points at the ``observability`` schema;
* the alert-rule count stays within its deliberate cap;
* no panel groups by an unbounded status label;
* an alert fires on active-series approaching the free-tier ceiling, below it.
"""

import json
from pathlib import Path

import pytest
import yaml
from scripts.gen_grafana_assets import (
    ACTIVE_SERIES_ALERT_THRESHOLD,
    ACTIVE_SERIES_CEILING,
    DASHBOARD_UID,
    DATASOURCE_UID,
    DEFAULT_WINDOW,
    MAX_ALERT_RULES,
    STATUS_CLASSES,
    GrafanaAssetError,
    assert_no_unbounded_status_label,
    assert_status_class_vocabulary,
    build_alert_rules,
    build_assets,
    build_dashboard,
    build_datasource,
    build_panels,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
ASSET_ROOT = REPO_ROOT / "deploy" / "grafana" / "provisioning"
DASHBOARD_FILE = ASSET_ROOT / "dashboards" / "caresetu" / "caresetu-observability.json"
DATASOURCE_FILE = ASSET_ROOT / "datasources" / "caresetu-postgres.yaml"
ALERT_FILE = ASSET_ROOT / "alerting" / "caresetu-alerts.yaml"

REGENERATE_HINT = (
    "regenerate with `node scripts/py.cjs apps/backend/scripts/gen_grafana_assets.py` "
    "and commit the result"
)


@pytest.fixture(scope="module")
def dashboard() -> dict:
    return build_dashboard()


@pytest.fixture(scope="module")
def alerting() -> dict:
    return yaml.safe_load(ALERT_FILE.read_text(encoding="utf-8"))


def test_every_committed_asset_matches_the_generator() -> None:
    """A hand-edit to any committed asset fails here, not in production (#748)."""
    for relative, expected in build_assets().items():
        destination = ASSET_ROOT / relative
        assert destination.is_file(), f"{destination} is missing; {REGENERATE_HINT}"
        # Compare the file's real bytes: the generator writes LF on every platform,
        # so a Windows checkout cannot pass by normalising CRLF.
        assert destination.read_bytes() == expected.encode("utf-8"), (
            f"{destination.name} is stale against the generator; {REGENERATE_HINT}"
        )


def test_dashboard_declares_the_console_deep_link_uid(dashboard: dict) -> None:
    # #736 deep-links by UID; a provisioning file that declared a different one
    # would send every console Grafana link to a 404.
    assert dashboard["uid"] == DASHBOARD_UID


def test_required_panels_are_present() -> None:
    titles = {panel.title for panel in build_panels()}
    required = {
        "Request throughput",
        "Error rate (5xx over all)",
        "Requests by status class",
        "Provider success rate",
        "Provider latency (p50/p95/p99)",
        "Provider throttling and timeouts",
        "AI queue depth by leg",
        "Oldest open AI queue age",
        "AI usage and spend (per day)",
        "Product funnel events (per day)",
        "Business daily registry",
        "Open alerts by severity",
    }
    assert required <= titles


def test_datasource_is_read_only_and_points_at_the_observability_schema() -> None:
    datasource = build_datasource()
    entries = datasource["datasources"]
    assert len(entries) == 1
    entry = entries[0]
    assert entry["uid"] == DATASOURCE_UID
    assert entry["type"] == "postgres"
    # Read-only: the operator dashboard is a read surface, never a writer.
    assert entry["editable"] is False
    # Grafana's PostgreSQL datasource honours sslmode, postgresVersion,
    # timescaledb and the pool settings - and nothing else. A `readOnly` or
    # `schema` key here would read like a control that exists while enforcing
    # nothing, so the file carries only what Grafana acts on: the read-only
    # posture is the Postgres ROLE's grants and the schema is pinned by every
    # panel's qualified SQL.
    assert set(entry["jsonData"]) == {"sslmode", "postgresVersion"}
    assert entry["jsonData"]["sslmode"] == "require"


def test_no_panel_queries_a_table_outside_the_observability_schema() -> None:
    for panel in build_panels():
        assert "FROM observability." in panel.sql, (
            f"panel {panel.id} ({panel.title!r}) must read the observability schema"
        )


def test_the_active_series_rule_reads_the_vendor_usage_datasource(alerting: dict) -> None:
    # The ceiling signal is Grafana Cloud's OWN usage metric. It lives in the
    # vendor's usage datasource, not in the deployment's metrics backend, so a
    # rule pointed at the metrics datasource would load and never find a series.
    rules = {rule["uid"]: rule for rule in alerting["groups"][0]["rules"]}
    active = rules["caresetu-active-series"]
    query = next(target for target in active["data"] if target["refId"] == "A")
    assert query["datasourceUid"] == "$GRAFANA_USAGE_DATASOURCE_UID"
    assert "grafanacloud_instance_active_series" in query["model"]["expr"]


def test_the_platform_rules_read_the_metrics_datasource(alerting: dict) -> None:
    for rule in alerting["groups"][0]["rules"]:
        if rule["uid"] == "caresetu-active-series":
            continue
        query = next(target for target in rule["data"] if target["refId"] == "A")
        assert query["datasourceUid"] == "$GRAFANA_METRICS_DATASOURCE_UID"


def test_no_alert_rule_queries_a_classic_histogram_series(alerting: dict) -> None:
    # The collector exports histograms as NATIVE histograms (NHCB) with classic
    # histograms switched off, so the `_count` series does not exist and a rule
    # naming it never fires.
    for rule in alerting["groups"][0]["rules"]:
        query = next(target for target in rule["data"] if target["refId"] == "A")
        expr = query["model"]["expr"]
        assert "_bucket" not in expr
        assert not expr.endswith("_count[10m])")
        assert "_count[" not in expr


def test_the_dashboard_default_window_is_the_deep_link_window() -> None:
    # One window, two surfaces: the console's deep link opens the dashboard with
    # `?from=`, so a second copy of the value in the generator could drift and
    # the two would land on different ranges.
    from modules.observability.domain.deeplinks import DEFAULT_GRAFANA_WINDOW

    assert DEFAULT_WINDOW == DEFAULT_GRAFANA_WINDOW
    assert build_dashboard()["time"]["from"] == DEFAULT_GRAFANA_WINDOW


def test_alert_rule_count_is_within_the_deliberate_cap(alerting: dict) -> None:
    rules = alerting["groups"][0]["rules"]
    assert len(rules) <= MAX_ALERT_RULES
    # The cap is small on purpose: a future rule has to argue a rule out to earn
    # its place rather than accumulate into alert fatigue (story 104).
    assert MAX_ALERT_RULES <= 6


def test_alert_rules_evaluate_the_metrics_backend_not_postgres(alerting: dict) -> None:
    # The alerts evaluate time series (the deployment-bound metrics datasource),
    # not the read-only Postgres datasource the panels use; a rule pinned to the
    # Postgres UID would evaluate no series at all.
    for rule in alerting["groups"][0]["rules"]:
        for target in rule["data"]:
            assert target.get("datasourceUid") != DATASOURCE_UID


def test_every_alert_rule_is_a_query_plus_threshold_pipeline(alerting: dict) -> None:
    # A Grafana rule needs a QUERY node and an EXPRESSION node, and `condition`
    # must name the expression node: a rule with only a query has nothing to
    # evaluate and never fires (the defect a bare `expr` would ship).
    for rule in alerting["groups"][0]["rules"]:
        by_ref = {target["refId"]: target for target in rule["data"]}
        assert set(by_ref) == {"A", "B"}
        assert rule["condition"] == "B"
        assert by_ref["A"]["model"]["expr"]
        assert by_ref["B"]["model"]["type"] == "threshold"
        assert by_ref["B"]["model"]["expression"] == "A"
        assert by_ref["B"]["model"]["conditions"][0]["evaluator"]


def test_active_series_alert_fires_below_the_ceiling(alerting: dict) -> None:
    rules = {rule["uid"]: rule for rule in alerting["groups"][0]["rules"]}
    guard = rules["caresetu-active-series"]
    # The ceiling is a hard stop with no overage, so the alert is set BELOW it
    # (story 105, #717 decision 38). The bound is the threshold node's parameter.
    query_node = next(t for t in guard["data"] if t["refId"] == "A")
    threshold_node = next(t for t in guard["data"] if t["refId"] == "B")
    assert "grafanacloud_instance_active_series" in query_node["model"]["expr"]
    evaluator = threshold_node["model"]["conditions"][0]["evaluator"]
    assert evaluator["params"][0] == float(ACTIVE_SERIES_ALERT_THRESHOLD)
    assert ACTIVE_SERIES_ALERT_THRESHOLD < ACTIVE_SERIES_CEILING


def test_no_panel_groups_by_an_unbounded_status_label() -> None:
    # Not a style rule: a panel grouped by a raw status code multiplies series
    # without bound (story 106). The generator's own guard is the assertion.
    assert_no_unbounded_status_label(build_panels())


def test_the_status_class_vocabulary_backs_a_panel() -> None:
    assert_status_class_vocabulary(build_panels())


def test_generator_rejects_a_raw_status_grouping() -> None:
    """The guard actually fires - a bare status column in a GROUP BY is refused."""
    from scripts.gen_grafana_assets import Panel

    offending = Panel(
        id=99,
        title="bad panel",
        sql="SELECT status, count(*) FROM observability.observability_http_minute GROUP BY status",
        grid=(0, 0, 12, 8),
    )
    with pytest.raises(GrafanaAssetError):
        assert_no_unbounded_status_label((offending,))


def test_the_alert_set_stays_within_the_cap_and_names_the_status_classes() -> None:
    assert len(build_alert_rules()) <= MAX_ALERT_RULES
    assert set(STATUS_CLASSES) == {"2xx", "3xx", "4xx", "5xx"}


def test_the_generator_refuses_more_rules_than_the_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    # The cap is load-bearing: the generator raises rather than quietly writing an
    # over-cap set, so accumulation is a failure and not a drift. Force the cap
    # under the real rule count to prove the guard actually fires.
    monkeypatch.setattr("scripts.gen_grafana_assets.MAX_ALERT_RULES", 1)
    with pytest.raises(GrafanaAssetError):
        build_alert_rules()


def test_dashboard_provider_loads_the_committed_dashboard_file() -> None:
    provider = yaml.safe_load(
        (ASSET_ROOT / "dashboards" / "caresetu-provider.yaml").read_text(encoding="utf-8")
    )
    options = provider["providers"][0]["options"]
    # The provider path is where the dashboard JSON is committed, so Grafana loads
    # the same artifact the repository holds.
    assert options["path"].endswith("/caresetu")
    assert DASHBOARD_FILE.is_file()


def test_committed_dashboard_is_parseable_json() -> None:
    document = json.loads(DASHBOARD_FILE.read_text(encoding="utf-8"))
    assert document["uid"] == DASHBOARD_UID
    assert len(document["panels"]) == len(build_panels())
