# Brief - 708 C2a - Frontend client + live nav entry + overview page

**Ticket:** #708 · **Parent:** #692 · **Refreshed:** 2026-10-12
**Reading surface:** ~9K tokens (budget 10K) - within budget

## Scope

**What to build:** Stand up the operator Observability surface: an `observability` API client under `lib/operator/`, an Observability entry in `nav-config.ts` (flip it live, no longer a coming-soon placeholder), and the overview page under `(operator)/operator/observability/` rendering the headline KPIs by reusing the existing `KpiTile`/`KpiRow` pattern. The page handles loading, empty, and error states.

**Acceptance criteria**

- [ ] `lib/operator/observability.ts` exposes typed fetchers for the C1 routes with shape guards.
- [ ] The Observability nav entry is live and routes to the new page; the shell test's nav keys are updated.
- [ ] The overview page renders headline KPIs from the API and shows loading / empty / error states with retry.
- [ ] A vitest page test mocks the client and covers loading, empty, error, populated, and retry.
- [ ] `npm run typecheck`; `npm run test:unit:frontend` pass.

## Read-list (in order)

1. `docs/plans/plan-phase14-observability.md` §9.1 read-routes table + §9.2 Frontend - the nine `GET /v1/operator/observability/*` routes and the C2 UI composition (route group, `lib/operator/observability.ts`, nav flip, `KpiTile`/`KpiRow` reuse). (~0.8K)
2. `lib/operator/api.ts` - the operator client to mirror: the thin `request` + `guardShape` pattern and per-resource `fetch*` + exported types (`fetchVerificationQueue`, `PartnerQueue`, `isPartnerQueue`). Conform `lib/operator/observability.ts` to this same shape. (~1.6K)
3. `lib/request.ts` - the shared `request<T>(path, options?)` and `guardShape<T>(value, guard, message)` interfaces the new fetchers must reuse; both throw `ApiError` (`NETWORK_ERROR`, the envelope code, `UNEXPECTED_ERROR`). (~0.4K)
4. `components/dashboard/nav-config.ts` - `NavItemDef` (`key`, `labelKey`, `href`, `icon`, `soon?`, `group?`) and `NAV_CONFIG.operator`. Add the live `observability` entry here. (~1.0K)
5. i18n convention - `Dictionary["nav"]` and the `NavLabelKey` mapped type; add `nav.observability` to both locale dictionaries, kept in sync by the bilingual parity test. (~0.4K)
6. `components/dashboard/AppShell.test.tsx` - the operator nav-key expectation `["home", "verifications", "disputes", "audit"]` (~line 734) that must gain `observability`; the shell renders `nav-*` / `tab-*` testids straight from `NAV_CONFIG`. (~0.4K)
7. `(operator)/operator/page.tsx` - the existing operator page's `LoadStatus` (`"loading" | "ready" | "error"`), `ErrorBanner` `onRetry`, `EmptyState`, and `Skeleton` pattern to copy for the overview page. (~1.6K)
8. `(operator)/operator/page.test.tsx` - the page-test seam to mirror: `vi.mock("@/lib/operator/api", importOriginal)` for the client seam, mocked `next/navigation` + `@/lib/auth/AuthContext`, and `waitFor` assertions over the loading/empty/error/populated states. (~1.0K)
9. `(doctor)/doctor/page.tsx` `KpiTile`/`KpiRow` (~lines 324-429) - the headline-KPI contract to reuse: `KpiTile({ testId, href, label, value, pending })` renders a skeleton while `pending`, the `DASH` glyph on a failed read, wrapped in a `Link`. (~1.0K)
10. `components/layout/PageHeader`, `components/layout/EmptyState`, `components/layout/ErrorBanner`, `components/ui/skeleton` - the shared layout/state primitives the overview page composes. (~0.6K)

## Do NOT read

- Backend modules/routes (C1a/C1b own the `observability` read APIs).
- The C2b chart panels and any design-system chart work.
- Unrelated frontend surfaces or the other role shells.

## Baseline verify (must pass before the first edit)

- `npm run typecheck` - PASS on the current tree.
- `npm run test:unit:frontend` - all 1910 tests in 133 files pass; the vitest process exits non-zero on a worker-timeout error (environment flake, not a test failure). Treat the suite as green.

## Done-verify (acceptance criteria → commands)

- New `(operator)/operator/observability/page.test.tsx` covers loading / empty / error / populated / retry.
- `components/dashboard/AppShell.test.tsx` operator nav-key list includes `observability`.
- `npm run typecheck`
- `npm run test:unit:frontend`

## Handoff notes

- **No coming-soon placeholder exists** in `NAV_CONFIG.operator` today; the plan's "flip it live" assumes one. Add `{ key: "observability", labelKey: "observability", href: "/operator/observability", icon, group: "work" }` (pick a `lucide-react` icon such as `Activity`) plus the `nav.observability` key in both dictionaries - not just removing a flag.
- Prior art: `lib/audit/api.ts` and `lib/care/api.ts` use the exact `request` + `guardShape` client pattern; `(operator)/operator/page.tsx` + its `page.test.tsx` are the direct page/test templates.
- The client must conform to the C1a/C1b response shapes (own those tickets); do not invent fields. Route names come from plan §9.1.
- Keep the overview to the headline KPIs; the cost/usage/quality/latency charts belong to C2b (#709).
