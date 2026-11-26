# Brief - 503 Patient home: Recommended near you rail from directory data

**Ticket:** #503 · **Parent:** #498 · **Refreshed:** 2026-09-21
**Reading surface:** ~5K tokens (budget 10K) - within budget

## Scope

A patient sees a "Recommended near you" rail under the home search, fed by real directory data for the active Doctor / Lab / Chemist scope: only operator-verified providers within the Daltonganj service area, distance-sorted ascending. On a phone it is a horizontal snap-scroll row; on desktop (>=720px) a 3-up grid. Switching scope swaps the rail and keeps destinations scoped. A friendly empty state covers no-results.

- [ ] Rail fetches per active scope and shows only verified providers.
- [ ] Providers are distance-sorted ascending.
- [ ] Mobile renders a horizontal snap-scroll row; desktop renders a 3-up grid.
- [ ] Switching scope swaps the rail content and the Search / See-all destinations together.
- [ ] No-results renders a friendly empty state.
- [ ] Strings under `patientHome.*`/`rec.*` in en + hi with parity enforced.

## Read-list (in order)

1. The recommended-rail markup, the per-scope panels (`data-rec-panel`) and the scope-swap JS in the binding `shell-light.html` spec (grep `rec-scroll`, `data-rec-set`, `data-rec-panel`, ~240-377, ~573-617) (~1.5K).
2. The directory search client surface: the query shape (`partnerType`), the `DirectoryEntry` projection (verified, `distance_km`), and the fell_back view - what the rail can rely on and what it must sort itself (~0.8K).
3. The search-card scope state from #502 - the single source the rail reads and writes (~0.5K).
4. The `patientHome.*`/`rec.*` dictionary slices and the composed home `page.test.tsx` seam (~0.8K).
5. The blocking ticket #502 closing comment, if any (~0.2K).

## Do NOT read

- The full `DirectoryBrowser` UI, candidate/listing internals beyond the search-result projection, backend directory modules, unrelated dictionary sections.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` and `npm run typecheck:frontend` (green on 2026-09-21 baseline; #502 may drift them only if broken).

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:frontend` - rail fetches per scope, only verified + distance-sorted at the composed seam; scope swap swaps panel + destinations; empty state renders.
- `npm run typecheck:frontend` - clean.
- `npm run lint` - clean.

## Handoff notes

- Verified is a derived backend guarantee: `searchDirectory` only ever returns [Active] partners with valid credentials, so `verified` is true on returned rows - but the ticket still requires the rail to only _show_ verified entries (defensive filter, mining the DirectoryCard gate rule "tick gone = card gone").
- Distance sorting is client-side: sort by `distance_km` ascending after fetch.
- Swap all three together on scope change: active pill, rail panel, and the Search / See-all destination from #502.
