# Brief - 501 Patient home: location chip + single-city picker

**Ticket:** #501 · **Parent:** #498 · **Refreshed:** 2026-09-21
**Reading surface:** ~5K tokens (budget 10K) - within budget

## Scope

A patient sees their persisted location as a chip: on mobile at the top of the home feed, on desktop inside the light top bar. Tapping it opens a picker sheet listing Daltonganj (the single service area today, explicitly marked single-city with a coming-soon note). Choosing persists the area through the profile draft/save flow and becomes Find Care's default area filter. The model is a single-city enum today, ready for more cities later; choosing the one city never re-enters it per search.

- [ ] Chip shows the persisted profile area, falling back to Daltonganj.
- [ ] Picker sheet opens from the chip and lists Daltonganj with the future-cities note.
- [ ] Choosing Daltonganj persists the area via the profile flow and is reflected in the chip and Find Care's default filter.
- [ ] Chip sits at the top of the mobile feed and inside the desktop light top bar.
- [ ] Strings under `patientHome.*`/`loc.*` (or equivalent) in en + hi with parity enforced.

## Read-list (in order)

1. The location chip (desktop top-bar + mobile feed-top) and the `#location-sheet` picker in the binding `shell-light.html` spec (grep `location-sheet`, `loc.`, ~158-162 / 202-206 / 549-571) (~1K).
2. The `Topbar` light density branch (desktop placement) and the composed home page's greeting-strip area (mobile placement) from #499 (~0.8K).
3. The `ProfileContext` value surface - `updateDraft` and how `draft.area` persists through the existing save flow, plus the Daltonganj default when null (~1K).
4. The Find Care route contract - the query-param filter `DirectoryBrowser` reads and commits, so the persisted area maps to its default (~0.8K).
5. The `patientHome.*`/`loc.*` dictionary slices and the composed home `page.test.tsx` seam (~0.8K).
6. The blocking ticket #500 closing comment, if any (~0.2K).

## Do NOT read

- Multi-city logic, geolocation, distance ranking, backend consent/auth modules, `docs/adr/*` (no session work), unrelated dictionary sections.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` and `npm run typecheck:frontend` (green on 2026-09-21 baseline; #500 may drift them only if broken).

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:frontend` - chip renders persisted/fallback area at the composed seam; picker persists area; parity suite green.
- `npm run typecheck:frontend` - clean.
- `npm run lint` - clean.

## Handoff notes

- The profile draft has free-text `area`, not a city enum. The single-city enum is a home-side concept: map Daltonganj into `draft.area` so the profile flow is untouched.
- REQ-008 single-service-area: one city means "no re-entry"; Find Care's default is the persisted area, and with a single city the directory result set is unchanged (Daltonganj = the whole service area). Do not invent multi-city behavior or distance differences.
- Keep the picker a small presentational sheet; no new data seam. Desktop chip mounts in the light top bar, mobile chip at the top of the feed; same component, two placements.
