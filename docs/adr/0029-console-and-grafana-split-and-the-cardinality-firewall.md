# ADR-0029: The split of responsibility between the in-app operator console and Grafana, and the cardinality firewall

**Status:** accepted
**Date:** 2026-10-21
**Decides:** That the in-app operator console is the decision surface and Grafana is the diagnostic surface - the console owns every number an operator acts on and reads it from the Postgres `observability` schema, Grafana owns the time-series and trace view and the alert delivery - and that the OpenTelemetry collector configuration is the cardinality firewall that protects the free tier's ten-thousand-active-series ceiling.
**Traceability:** `plan-phase14-observability.md` §3, §11, §14, §15; spec #717 decisions 36, 37, 38, 39, 40, 41; parent #717; tickets #736, #737, #738, #743, #748, #749, #750. Related: `ADR-0024` (the hybrid free-tier topology), `ADR-0025` (the `observability` schema), `ADR-0026` (OpenTelemetry), `ADR-0007` (split-origin deployment), `NFR-001`, `NFR-003`, `internal-modules.md` §3.14.

## Context

Two surfaces now show the operator what the platform is doing. The in-app console (the Observability group: Overview, Business, Product, Reliability, the four AI panels and Settings) is a React application served from the frontend origin. Grafana Cloud is a hosted service holding infra and app metrics, traces, logs, the provisioned dashboards and the alert rules.

That split is not free to get wrong, for two reasons that pull in opposite directions.

**The console has to be the place decisions are made.** The numbers an operator acts on - spend against the cap, which patient is burning the budget, which provider is throwing 429s, how old the oldest queued item is, which funnel step loses people - have to be readable in one place, and they have to survive a vendor's retention window. The free metrics tier keeps fourteen days. A month-to-date figure read from Grafana is a figure that was never stored.

**The console is the wrong tool for a time-series canvas.** Trace waterfalls, latency distributions with exemplars, log streams and the infra view are what Grafana is for, and re-implementing them in React would be a large piece of work that ages badly and still would not have the traces.

And behind both of them sits the ceiling that decides the shape of everything: the free tier allows **ten thousand active series with no overage**, and the request-duration histogram alone can consume over half of it. Crossing the ceiling drops telemetry silently, so the boundary has to be enforced somewhere that cannot be forgotten.

## Decision

### D1 - The console is the decision surface; Grafana is the diagnostic surface

**The in-app console owns** every number an operator acts on, read from the Postgres `observability` schema: cost and unit economics, the product funnel and active users, reliability, the provider board, the alert feed and its acknowledgement, the deep links. It is the only surface that works with no vendor configured at all, because it reads our own database.

**Grafana owns** the time-series and trace view: request latency distributions, per-series drilldown, the trace waterfall, the log stream, the infrastructure view, and the alert rules that deliver to email or a chat webhook. The console never re-implements it; it deep-links into it with the time range and template variables already set, so the operator lands on the answer rather than on an empty canvas.

**Sentry** stays the crash tracker and a deep-link target, not a store the console reads: the live error feed is served from Postgres, which is the system of record.

**The AI tracing vendor** is the AI trace view, reached by deep link, and its metrics reach Postgres by a daily batch rather than by a live datasource (D3).

### D2 - Grafana reads Postgres, read-only, and only from the `observability` schema

The provisioned datasource points at the `observability` schema through a read-only role, and every panel's SQL is schema-qualified. The business and product numbers therefore render from the system of record rather than from a vendor's fourteen-day window, and Grafana never writes into the system of record. A panel that read any other schema would be a cross-schema read by another name, and it is the same rule `ADR-0003` keeps inside the application.

### D3 - No live vendor API sits behind a dashboard refresh

A panel that called the AI tracing vendor on refresh would exhaust that vendor's hundred-requests-a-day allowance in an afternoon. **No panel calls a vendor API.** A panel's data comes from two places and only two: the metrics the collector remote-writes into the vendor's own store, and the `observability` schema through the read-only datasource (D2). The AI tracing vendor is the one that is never read live - its metrics arrive by a daily batch pull that runs on the same schedule as the nightly rollup and makes **at most one** metrics request per run, and it writes into the `observability` schema so the numbers outlive the vendor's retention window. No console refresh, and no panel refresh, can reach a vendor API.

### D4 - The cardinality firewall is the collector configuration, not the application

The application's own instrumentation is unchanged by the firewall. Histogram series cardinality is controlled by the OpenTelemetry collector before export, so the application never has to know the vendor's budget. `deploy/otel-collector/config.yaml` is the committed configuration, and its rules are:

1. **Three status classes, no more.** Response status is collapsed into `success` (1xx/2xx/3xx), `client-error` (4xx) and `server-error` (5xx) and written to `http.status_class`; the raw status keys are deleted once classified. This is the collector's own taxonomy, deliberately different from the four-way class the stored Postgres counter keeps.
2. **Bounded method vocabulary.** `http.method` and `http.request.method` are rewritten to `UNKNOWN` unless the value is one of the nine standard verbs, so a custom verb cannot mint a series.
3. **No raw path, URL or host labels.** `http.host`, `http.server_name`, `http.url`, `url.full`, `url.path`, `url.query`, `net.host.name` and `net.host.port` are deleted: they carry record identifiers, query strings and attacker-controlled headers. `http.target` and `http.route` survive on purpose, because the instrumentor only reports route-templated values for those two, so they are bounded by the route table rather than by request data.
4. **Native histograms.** The remote-write exporter converts explicit histograms to native histograms and keeps no classic buckets, so a label set is one series instead of one series per bucket.

The rules are asserted by a repository check that runs in pre-commit and CI, so the firewall cannot drift away from the configuration it describes. Traces and logs pass through untouched: they are not series, and they share the one OTLP endpoint and must still land.

The firewall is also the mitigation for the open unbounded-cardinality advisory on the FastAPI instrumentation, which is why the two belong together: the pinned instrumentor version must stay above the fixed release, and the firewall must land with the next bump.

### D5 - The active-series count is alerted on below the ceiling

The free tier's ceiling is a hard stop with no overage, so the alert fires at 8,000 active series, not at 10,000. The operator is warned while a label can still be shed, because a ceiling crossed is telemetry dropped with no error message. The rule is a version-controlled alert rule, like every other Grafana asset.

### D6 - The Grafana assets are repository files, generated and validated

The dashboards, the datasource and the alert rules are generated by one generator that owns the bytes, committed, and provisioned from configuration rather than clicked into the console, so a dashboard change is a reviewable, revertible commit. The generator is unit-tested, and a check fails when a committed asset is stale, so the files and the generator cannot drift apart.

The alert-rule set is capped at a small deliberate number (6). The vendor's allowance is generous, and a generous allowance is exactly how alert fatigue arrives. Adding a rule means arguing one out.

### D7 - The in-app alert feed is the record; Grafana is the delivery channel

The `observability_alert_events` feed in the console is the durable, operator-visible record of what fired, and acknowledgement is an in-app write that fills the row's own `acked_by` and `acked_at`. Delivery rides the free channels (Grafana Cloud alerting to email or a chat webhook, Sentry alerts). The two are not the same thing and are not confused: the feed is where the answer lives, the channel is how it reaches the operator.

### D8 - The console keeps its own chart primitives

The console's panels use the platform's own panel frame and chart primitives, reading the `observability` schema through the operator API. The console does not embed Grafana, and Grafana does not render console panels. Each surface is rendered by the tool that owns it, and the join between them is a parameterised deep link carrying the platform's own stored trace id, so one identifier joins every tool.

## Considered options

- **Embed Grafana in the console.** Rejected - the console and Grafana are different origins, and the split-origin deployment (`ADR-0007`) means a cross-origin embed is exactly the kind of thing that works locally and fails in production. It would also make the console's own read contract pointless.
- **One surface: the console only, drop Grafana.** Rejected - the console would have to re-implement trace waterfalls, log search and latency distributions, and the traces still have to live somewhere.
- **One surface: Grafana only, drop the console panels.** Rejected - the decision data would live in a fourteen-day window, the acknowledgement write would have nowhere to live, and the operator would lose the one surface that works with no vendor configured.
- **Let the application control cardinality.** Rejected - the application would have to know the vendor's budget, which changes every time the vendor changes its price, and the budget would live in a dozen instrumented modules instead of in one place.
- **A live AI-tracing datasource in Grafana.** Rejected - a panel refresh would spend a hundred-request-a-day allowance in an afternoon, and a fast refresh would spend it faster.
- **Click Grafana dashboards into the console by hand.** Rejected - a console-clicked configuration is not reviewable, not revertible, and not testable, and the next person cannot tell what changed.
- **Unbounded alert rules because the allowance is generous.** Rejected - the alert set is deliberately small, and each rule that lands is one more reason to ignore the feed.

## Consequences

- The console is the only surface that has to keep working when a vendor is unconfigured, missing a key, or has changed its retention. That is the direct beneficiary of the Postgres system of record (`ADR-0024` D2).
- The cardinality firewall is a shipped artefact with a gate, not a tuning exercise. A change that reintroduces an unbounded label fails pre-commit.
- Because the exporter emits native histograms, the classic `_count`, `_sum` and `_bucket` series no longer exist once the collector is live. Any dashboard or alert expression that names them must be rewritten to the base metric name and to `http.status_class`. This is a migration of the provisioned assets, it belongs with the asset change that made it necessary, and it is not optional: an expression naming a series that no longer exists returns nothing, and a rule that can never fire is worse than no rule because it looks like coverage.
- The console's deep links are parameterised rather than three bare URLs, so a link lands on the answer. A vendor with no configured key is absent from the response rather than a broken link.
- The alert-rule cap is a number someone has to argue with. That is the point.
