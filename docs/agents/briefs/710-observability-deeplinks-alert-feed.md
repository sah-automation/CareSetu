# Brief - 710 C3 - Deep-links + alert feed

**Ticket:** #710 · **Parent:** #692 · **Refreshed:** 2026-10-12
**Reading surface:** ~6K tokens (budget 10K) - within budget

## Scope

**What to build:** Finish the operator Observability surface with the alert feed and the deep-links. Show the in-app alert feed from `/alerts` (severity, kind, title, time) as the operator-visible record, and render outbound deep-links from `/deeplinks` to Grafana, Sentry, and Langfuse so the operator can drill into raw traces, errors, and AI spans. Alert acknowledgement is deferred to Batch 2.

**Acceptance criteria**

- [ ] An inline alert feed panel renders the alert rows with severity styling and empty/error states.
- [ ] Deep-links render as outbound links to Grafana/Sentry/Langfuse; absent vendor config renders no broken link.
- [ ] A vitest test covers populated / empty / absent-link states.
- [ ] `npm run typecheck`; `npm run test:unit:frontend` pass.

## Read-list (in order)

1. `docs/plans/plan-phase14-observability.md` §9.1 routes (`/alerts`, `/deeplinks`) + §9.2 (inline alert feed, deep-links out) + §11 minimum alert set + §10 (audit-tamper surfaced in the feed). (~0.9K)
2. C1b response shapes: `GET /v1/operator/observability/alerts` (severity, kind, title, created/`created_at`, `acked_by`) and `/v1/operator/observability/deeplinks` (present vs absent vendor URLs), or the plan §7.2 `obs_alert_events` columns if the ticket is not landed. The client conforms to these; do not invent fields. (~1.5K)
3. C2a deliverable (#708): `lib/operator/observability.ts` + the overview page's state closure. Extend the client with `fetchAlerts` / `fetchDeeplinks` (shape guards) and render both panels in the existing surface. (~2.0K)
4. `components/ui/badge.tsx` + `lib/operator/badges.ts` (`STATUS_BADGE`, `TYPE_BADGE`, `statusKey`) - the badge/severity-styling pattern for alert rows. (~0.8K)
5. `components/layout/EmptyState`, `components/layout/ErrorBanner`, `components/ui/skeleton` - the empty / error / loading states the feed and the links panel use. (~0.5K)

## Do NOT read

- Backend modules/routes (C1b owns the alerts/deeplinks read APIs).
- The C2b chart panels.
- Unrelated frontend surfaces.

## Baseline verify (must pass before the first edit)

- `npm run typecheck` - PASS on the current tree.
- `npm run test:unit:frontend` - all 1910 tests in 133 files pass; the vitest process exits non-zero on a worker-timeout error (environment flake, not a test failure). Treat the suite as green.

## Done-verify (acceptance criteria → commands)

- New alert-feed vitest test covers populated / empty / absent-link states.
- `npm run typecheck`
- `npm run test:unit:frontend`

## Handoff notes

- **Alert acknowledgement is Batch 2**: no ack action, no ack endpoint, no `acked_by` write - render the feed read-only.
- **Absent vendor config must render no link**, never a dead/broken one: the backend returns null/absent URLs for an unconfigured vendor; the panel omits that link.
- `obs_alert_events` (`severity`, `kind`, `title`, `payload`, `status`, `created_at`, `acked_by`) is the data contract; map `severity` through the badge pattern for row styling.
- Outbound links are plain anchors to Grafana / Sentry / Langfuse (new tab); no PHI in any link payload (plan §10).
- Prior art: `(operator)/operator/page.tsx` table + badge styling and its `page.test.tsx` api-client mock seam are the direct templates.
