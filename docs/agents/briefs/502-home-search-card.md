# Brief - 502 Patient home: search card with Doctor/Lab/Chemist scope

**Ticket:** #502 · **Parent:** #498 · **Refreshed:** 2026-09-21
**Reading surface:** ~5K tokens (budget 10K) - within budget

## Scope

A patient can jump into Find Care scoped to what they need directly from the home: a search card under the greeting with Doctor / Lab / Chemist scope pills, a full-width search input with a Search button (48px touch target on phone), and a See-all destination. Enter/Search routes to Find Care scoped to the active pill (`type=doctor|lab|chemist`); the See-all link carries the same scope. The search input keeps `flex:1; min-width:0` so a long query can never widen the page. Scope-switching is display-driven and also drives the recommended rail (filled by the next ticket).

- [ ] Doctor / Lab / Chemist pills render and switching scope updates the active pill and the Search / See-all destinations.
- [ ] Enter or tapping Search on a query navigates to scoped Find Care.
- [ ] On phone, the search input and button are full width with a 48px touch target.
- [ ] A long query in the box never triggers page-level horizontal overflow at 320px.
- [ ] Strings under `patientHome.*`/`search.*` in en + hi with parity enforced.

## Read-list (in order)

1. The search card and scope pills in the binding `shell-light.html` spec (grep `search-scope`, `.search-card`, `data-rec-set`, ~223-377) - note the pill-to-panel/destination wiring (~1.2K).
2. The Find Care route contract: `DirectoryBrowser` and its parse of the `type` query param (the scoped destination, `?type=doctor|lab|chemist`), and the provider-type label helper (~1K).
3. The prototype's search-input regression rule (flex:1 + min-width:0, ~229-237) and the shell's min-width layout rules from #499 (~0.4K).
4. The `patientHome.*`/`search.*` dictionary slices and the composed home `page.test.tsx` seam (~0.8K).
5. The blocking ticket #501 closing comment, if any (~0.2K).

## Do NOT read

- The recommended-rail fetch logic itself (ticket #503), directory query internals beyond the filter contract, backend modules, unrelated dictionary sections.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` and `npm run typecheck:frontend` (green on 2026-09-21 baseline; #501 may drift them only if broken).

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:frontend` - pills render and swap destinations; Enter/Search routes scoped; overflow-free at 320px.
- `npm run typecheck:frontend` - clean.
- `npm run lint` - clean.

## Handoff notes

- The live `DirectoryBrowser` uses URL query params as the single filter source; the home search only needs to route to the scoped URL (`/patient/find?type=...`), never to run its own search.
- The pills are display-driven scope state shared with the rail from #503 - shape it so the next ticket can read the active scope.
- Keep the 48px touch target and separate the Search button from the input on the grid; the input must never stretch the page (min-width:0), verified against a long query.
