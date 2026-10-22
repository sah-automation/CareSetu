# Brief - #748 Grafana dashboards, datasource and alert rules as repository files

**Ticket:** #748 · **Parent:** #717 · **Refreshed:** 2026-10-14
**Reading surface:** ~7K tokens (budget 10K) - within budget

## Scope

Put Grafana dashboards, alert rules and the datasource into the repository as provisioned, generated and validated assets, so a dashboard change is reviewable and revertible rather than console-clicked configuration. The free tier's active-series ceiling is a hard stop with no overage, so it gets an alert of its own.

- [ ] Grafana dashboards, a read-only datasource onto the observability schema, and the alert rules are version-controlled repository files, provisioned from configuration.
- [ ] A generated-and-validated asset is committed; the generator is unit-tested rather than the console configuration.
- [ ] The datasource is read-only and points at the observability schema, so business and product numbers render from the system of record.
- [ ] Alert rules are capped at a small deliberate number, so nobody suffers alert fatigue inside a generous vendor allowance.
- [ ] An alert fires on active-series count approaching the free tier's ceiling, set below the ceiling because exceeding it is a hard stop with no overage.
- [ ] Generator unit tests assert: required panels present, the datasource pointing at the observability schema, the alert rule count within its cap, and no unbounded status label.

## Read-list (in order)

1. Spec #717 - Implementation Decisions 36 and 38; the third-party-asset user stories; the known ceiling that constrains the whole design. (~1.1K)
2. `docs/adr/0024-*.md` - the observability topology decision: which vendor, which free tier, what the ceiling is, and why Postgres is the system of record. (~0.5K)
3. The tables and metric shapes the three lenses read from - the daily per-actor aggregate, the per-minute counter, the provider health row, the product daily rollup. These are what the dashboards query. (~1K)
4. The status-collapse rule shared by the counter and the collector, since a dashboard panel that groups by raw status inherits the cardinality problem. (~0.4K)
5. `docs/standards/third-party-integration-standards.md` - the call-discipline, degradation and no-live-API rules a provisioned asset must obey. (~0.8K)
6. The repository's existing conventions for committed configuration and asset directories, and the wiring for provisioning on deploy. (~0.6K)
7. The existing unit-test conventions for pure generators with a validated output shape. (~0.6K)

## Do NOT read

- Frontend sources, `docs/archive/`.
- The collector configuration - #749 owns the cardinality firewall; you consume its status taxonomy.
- The langfuse batch pull and evaluators - #750, #751.
- The intake and care modules.

## Baseline verify (must pass before the first edit)

- `npm run lint`
- `npm run typecheck`
- `npm run test:unit:backend`

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend`
- `npm run lint`
- `npm run typecheck`

## Handoff notes

- **No live vendor API behind any dashboard.** Grafana reads the observability schema through the read-only datasource. A panel that calls the AI tracing vendor's API on refresh is out of bounds and will exhaust a hundred-request-a-day allowance in an afternoon.
- The active-series alert is set _below_ the ceiling deliberately; the ceiling is a hard stop with no overage, so hitting it silently drops data.
- Agree the dashboard identifier scheme with #736, which deep-links to these dashboards by identifier. If they disagree, every deep link lands on nothing.
- The alert-rule cap is a small deliberate number. Write the test that enforces it so a future rule addition has to argue for its place.
- `no unbounded status label` is a cardinality rule, not a style rule: a panel grouped by raw status code multiplies series without bound. Assert it in the generator test rather than reviewing for it.
