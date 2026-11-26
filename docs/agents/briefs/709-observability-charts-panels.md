# Brief - 709 C2b - Cost/usage/quality/health panels + charts

**Ticket:** #709 · **Parent:** #692 · **Refreshed:** 2026-10-12
**Reading surface:** ~8K tokens (budget 10K) - within budget

## Scope

**What to build:** Add the remaining Observability panels with charts: cost-vs-budget, daily cost trend, usage by provider/task, quality (low-confidence and success rates), and latency percentiles. Use the design-system chart components (recharts under the hood) for consistency, and hold each page under the `NFR-003` 1.5 MB page-weight gate.

**Acceptance criteria**

- [ ] Cost, usage, quality, and latency panels render from their C1 routes as charts, with loading / empty / error states.
- [ ] Charts use the shared design-system chart component; no ad-hoc chart libs.
- [ ] The added bundle keeps the observability pages within the `NFR-003` page-weight budget.
- [ ] Vitest page tests mock the client and cover populated + chart-render + error states.
- [ ] `npm run typecheck`; `npm run test:unit:frontend` pass.

## Read-list (in order)

1. `docs/plans/plan-phase14-observability.md` §9.2 Frontend (chart-library decision) + §7.2 schema tables (`obs_ai_usage_daily`, `obs_ai_cost_budget`, `obs_ai_provider_health`) - what each cost/usage/quality/latency panel can read. (~1.0K)
2. C2a deliverable (#708): `lib/operator/observability.ts` + the overview page + the shared `LoadStatus` / `ErrorBanner` / `EmptyState` shell. Extend the client with the cost / cost-trend / usage / quality / latency / health fetchers and reuse the page state pattern. (~2.5K)
3. `docs/research/ui-component-library.md` Recommendation + Constraints recap + Adoption steps & guardrails - shadcn/ui on Tailwind v3, adoption strictly lazy and per feature, app-owned string layer, and the 1.5 MB budget every addition is measured against. (~1.5K)
4. `docs/design/ui-blueprint.md` §8 operator console + §9.1 loading / empty / error states - operator-surface IA and the states every panel owes. (~1.5K)
5. `scripts/measure-pages.cjs` - `CHANNELS`, `BUDGET_BYTES` (1.5 MB), and the `check:pages` gate; `/operator` is already a measured channel. (~0.4K)
6. `apps/frontend/src/components/ui/*` and `apps/frontend/package.json` - confirm no chart component or `recharts` dependency exists yet; the shared chart primitive is added here. (~0.6K)

## Do NOT read

- Backend modules/routes (C1a/C1b own the data).
- Unrelated frontend surfaces or other role shells.
- The C3 deep-links / alert feed (its own ticket).

## Baseline verify (must pass before the first edit)

- `npm run typecheck` - PASS on the current tree.
- `npm run test:unit:frontend` - all 1910 tests in 133 files pass; the vitest process exits non-zero on a worker-timeout error (environment flake, not a test failure). Treat the suite as green.

## Done-verify (acceptance criteria → commands)

- Panel vitest tests cover populated + chart-render + error states.
- `npm run typecheck`
- `npm run test:unit:frontend`
- `npm run check:pages` - builds and serves the app, then asserts each channel (incl. `/operator`) is `<= 1.5 MB`. Run it because this change adds the chart runtime.

## Handoff notes

- **No chart component or `recharts` dependency exists today.** C2b owns adding the single shared design-system chart component (shadcn/ui chart primitive on recharts), and every panel consumes it - no ad-hoc chart libs, no per-panel recharts imports.
- Route group and IA follow C2a: pages under `(operator)/operator/observability/*` (cost, usage, quality, health), sharing the overview page's `LoadStatus` / retry / empty closure.
- Adopt the chart primitive lazily and measure it: `/operator` is the channel the `NFR-003` gate already covers. If the page lands over budget, record the finding rather than raising the ceiling.
- Prior art: the C2a overview page is the composition template; `components/ui/*` shows the local-token component shape to follow.
