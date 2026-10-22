# OpenTelemetry collector - the cardinality firewall (#749)

`config.yaml` is the committed OpenTelemetry collector configuration for the
CareSetu observability topology (ADR-0024). It is the one place where the
free-tier budget is enforced: histogram series cardinality is controlled by
the collector before export, so the application never has to know the
vendor's limit (spec #717 decisions 37/38).

- App side: `OTEL_EXPORTER_OTLP_ENDPOINT` points at this collector
  (`http://127.0.0.1:4318`), one endpoint for traces, logs and metrics.
- Collector side: signals are received on `127.0.0.1:4317` (gRPC) and
  `127.0.0.1:4318` (HTTP), transformed, and exported to Grafana Cloud.
- The application's own instrumentation is unchanged by this ticket. Any
  change to what the app emits belongs in the app, not here.

## Environment variables (no secrets are committed)

The config references these variables; values come from the deployment
environment and are validated by the repo's secret scanner in the normal way.

| Variable                 | Purpose                                                               |
| ------------------------ | --------------------------------------------------------------------- |
| `GRAFANA_CLOUD_USER`     | Grafana Cloud metrics/OTLP instance username (basic auth)             |
| `GRAFANA_CLOUD_API_KEY`  | Grafana Cloud access policy token (basic auth password)               |
| `GRAFANA_PROMETHEUS_URL` | Metrics endpoint: `https://<stack>.grafana.net/api/prom/push`         |
| `GRAFANA_OTLP_URL`       | OTLP gateway base URL: `https://otlp-gateway-<zone>.grafana.net/otlp` |

## Running it

The collectors own the build; this repository only commits the config and the
gate that validates it. Deployment installs `otelcol-contrib` at a pinned
version and starts it as a separate process from the app:

```sh
# Grafana Cloud publishes its distribution as a mirrored binary; a pinned
# otelcol-contrib release works too. Run from the repository root.
otelcol-contrib --config deploy/otel-collector/config.yaml
```

The app's telemetry is only exported when `OTEL_ENABLED` (and its OTLP
endpoint) are set; with the gate off the collector simply receives nothing.

## What the firewall enforces

`transform/cardinality_firewall` runs on metric datapoints before export and
does four things. Each rule is asserted by
`apps/backend/scripts/check_otel_collector_config.py`, which runs in
pre-commit and CI, so the firewall cannot silently drift.

1. **Three status classes, no more.** Response status is collapsed into
   `success` (1xx/2xx/3xx), `client-error` (4xx) and `server-error` (5xx) and
   written to `http.status_class`. This is decision 37's three-way collapse
   (#717): the stored Postgres counter keeps a four-way `2xx`/`3xx`/`4xx`/`5xx`
   class (#727, a CHECK-constrained table that predates this work), so this is
   deliberately the collector's own taxonomy, not a second copy of the stored
   one. The raw keys (`http.status_code` from the FastAPI instrumentor, and
   `http.response.status_code` from the app's own middleware) are deleted
   once classified.
2. **Bounded method vocabulary.** `http.method` and `http.request.method` are
   rewritten to `UNKNOWN` unless the value is one of the nine standard HTTP
   verbs. The instrumentor sanitises its own attribute; the app's middleware
   records the raw verb, and any custom verb would otherwise mint a series.
3. **No raw path/URL/Host labels.** `http.host`, `http.server_name`,
   `http.url`, `url.full`, `url.path`, `url.query`, `net.host.name` and
   `net.host.port` are deleted. They carry record identifiers, query strings
   and attacker-controlled Host headers. `http.target` and `http.route`
   survive on purpose: the instrumentor only reports route-templated values
   for those two, so they are bounded by the route table, not by request
   data.
4. **Native histograms.** `prometheus_remote_write/grafana` sets
   `convert_explicit_histograms_to_nhcb: true` and
   `keep_classic_histograms: false`, so a label set is one series instead of
   one series per bucket.

Traces and logs pass through untouched: they are not series, so the firewall
does not apply, but they share the one OTLP endpoint and must still land.

## Advisory verification (part of this ticket)

The FastAPI instrumentation has an open unbounded-cardinality advisory, and
this firewall is its mitigation, so the pinned version was verified before the
config landed.

- Advisory: GHSA-5rv5-6h4r-h22v (CVE-2023-43810, alias PYSEC-2026-1752),
  "unbound `http_method` label" DoS via unsanitised custom HTTP verbs.
- Fixed in `opentelemetry-instrumentation` 0.41b0 / API 1.20.0.
- This repo pins `opentelemetry-instrumentation-fastapi>=0.48b0` (and
  `>=0.48b0` for the SQLAlchemy and httpx instrumentors) and the environment
  installed 0.65b0, both above the fix. The pinned line is **not exposed**.
- Action: no bump required. **Before the next instrumentor bump, re-check the
  advisory**; the version floor in `apps/backend/pyproject.toml` must stay
  above the fixed release, and this firewall must land with it.

## Migration note for #748 dashboards and alerts

The dashboards and alerts committed by #748 query the classic histogram
series, for example `rate(caresetu_http_server_duration_count[10m])`. Once
this config is live, the exporter emits native histograms (NHCB) and no
`_count`, `_sum` or `_bucket` series exist, so those expressions return
nothing. They must be switched to the base metric name
(`caresetu_http_server_duration`) before or with the cutover. That work
belongs to #748 and is not done here.

The same applies to the status dimension: panels that grouped on a raw status
code must group on `http.status_class` (the three classes above).
