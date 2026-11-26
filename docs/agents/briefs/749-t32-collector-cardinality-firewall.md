# Brief - #749 OpenTelemetry collector configuration as the cardinality firewall

**Ticket:** #749 · **Parent:** #717 · **Refreshed:** 2026-10-14
**Reading surface:** ~6K tokens (budget 10K) - within budget

## Scope

Ship the cardinality firewall as a committed collector configuration, so the free tier's ten-thousand-active-series ceiling cannot be exceeded by the request-duration histogram alone. Histogram series cardinality is controlled by the collector rather than by the application, so the app never has to know the vendor's budget.

- [ ] An OpenTelemetry collector configuration is committed as the cardinality firewall.
- [ ] Response status is collapsed into success, client-error and server-error classes before export, so series cardinality does not explode.
- [ ] Histogram export uses native histograms, so a label set is one series rather than one per bucket.
- [ ] The application's own instrumentation is unchanged by this ticket.
- [ ] The pinned OpenTelemetry FastAPI instrumentation version is verified against the open unbounded-cardinality advisory before this lands, since the firewall is the mitigation and the two belong together.
- [ ] The collector configuration is validated as part of the repository's verification harness.

## Read-list (in order)

1. Spec #717 - Implementation Decisions 37 and 38; the further note about the OpenTelemetry advisory and the migration to check before the next instrumentor bump. (~1K)
2. `docs/adr/0026-*.md` - the OpenTelemetry adoption decision: the fixed instrumentation set, the configured sampling, and where the vendor boundary sits. (~0.5K)
3. `docs/adr/0024-*.md` - the free-tier ceiling the firewall exists to protect. (~0.4K)
4. The existing OpenTelemetry instrumentation setup and its environment gate, to confirm which signals are exported and with what attributes. (~0.9K)
5. The status taxonomy the counter uses (#727) - the collector must collapse to the same three classes, not invent a fourth vocabulary. (~0.4K)
6. The repository's verification harness scripts, to see where a configuration validation step would be wired and how the lint/typecheck gates are composed. (~0.6K)

## Do NOT read

- Frontend sources, `docs/archive/`.
- The Grafana dashboards (#748) - they consume the firewall's output taxonomy.
- The langfuse batch pull and evaluators.
- The intake and care modules.

## Baseline verify (must pass before the first edit)

- `npm run lint`
- `npm run typecheck`
- `npm run test:unit:backend`

## Done-verify (acceptance criteria → commands)

- `npm run lint`
- `npm run test:unit:backend`
- `npm run typecheck`

## Handoff notes

- **Check the advisory before you configure anything.** The FastAPI instrumentation has an open unbounded-cardinality advisory, and this firewall is its mitigation. If the pinned version is still exposed, the version check and the bump are part of this ticket, not a follow-up - shipping the firewall against an exposed version closes nothing.
- The application's instrumentation stays unchanged. The firewall is the collector's job; a code change here would move the vendor's budget into the application, which is the thing being avoided.
- Reuse the three status classes from #727. Two taxonomies means a dashboard that groups by one and a firewall that collapses to the other.
- Validation in the harness means it fails the build, not that a human remembers to run it. Wire it beside the existing configuration checks.
- Commit the configuration as data. If you find yourself templating it from application settings, that couples the firewall to the app again.
