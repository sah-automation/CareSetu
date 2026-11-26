# Brief - T5 `area` on directory cards + featured homepage (frontend)

**Ticket:** #327 · **Parent:** #319 · **Refreshed:** 2026-09-06
**Reading surface:** ~5K tokens (budget 10K) - within budget

## Scope

The patient sees the partner's area on each directory result card and on the homepage featured-doctors list: the client directory type carries `area` (validated by the runtime shape guard), the result card renders it among the non-null meta (never invented copy when absent), and the featured mapping passes the area through. The redundant `.filter((entry) => entry.verified)` in the featured mapping is dropped - the API guarantees every returned row is verified (ADR-0011). Search, distance, and navigation are unchanged.

Acceptance criteria (from #327):

- [ ] The client directory entry type + runtime shape guard accept the search response's `area` field.
- [ ] `DirectoryCard` renders the area when non-null (in the localised meta line) and renders no area copy when it is null; unverified rows still never render (defensive gate untouched).
- [ ] The homepage featured mapping carries `area` through and no longer filters on `entry.verified`.
- [ ] Frontend tests cover: area rendered from the response, no invented copy on a missing area, featured mapping passes area + drops the verified filter.
- [ ] `npm run test:unit:frontend`, `npm run typecheck`, `npm run lint` pass.

## Read-list (in order)

1. `docs/architecture/internal-modules.md` MOD-002 spec - the `directory entry` shape and `verified` semantics the client mirrors (~0.5K)
2. `docs/design/ui-blueprint.md` directory surface + card language sections - the display rules the card obeys (~1K)
3. `apps/frontend/src/lib/directory/search.ts` - `DirectoryEntry` + `isDirectoryEntry` guardShape; add `area: string | null` to both (~0.5K)
4. `apps/frontend/src/components/directory/DirectoryCard.tsx` - the meta line join (`specialty/type`, `formatDistanceKm`) + the defensive `if (!entry.verified) return null` gate that stays (~0.3K)
5. `apps/frontend/src/components/directory/DirectoryBrowser.tsx` card rendering - how `distanceLabel`/meta reach the card (~0.5K)
6. `apps/frontend/src/lib/directory/featured.ts` + `apps/frontend/src/components/public/FeaturedDoctors.tsx` - the featured mapping (drop `.filter(entry => entry.verified)`, carry `area`) and the `DoctorCard` meta join that will render it (~0.5K)
7. `DirectoryCard.test.tsx`, `DirectoryBrowser.test.tsx`, `FeaturedDoctors.test.tsx` - the assertion patterns to extend (mocked `searchDirectory`) (~2K)

## Do NOT read

- Any backend code, auth, or unrelated frontend surfaces. `npm run check:contract` does not cover the directory client - ignore it.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend`
- `npm run typecheck`

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:frontend`
- `npm run typecheck`
- `npm run lint`

## Handoff notes

- Baseline truth (2026-09-06, before any edit): frontend unit 674 pass (first run flaked with an unreproduced exit-1; re-run green).
- **Blocked by #325** - do not start until the backend ships `area` on the search response (the guard expects it).
- Update the STALE comments that encode the old guard: `search.ts` DirectoryEntry says "area is not part of the search projection ... never invented here" and `DirectoryCard.tsx` says "never an area string the search projection does not carry" - both must be rewritten to match the new projection.
- Card meta joins only non-null values (same `filter(Boolean).join(" · ")` language as `DoctorCard`); on a null `area` the card renders no area copy at all.
- Keep the defensive `if (!entry.verified) return null` in `DirectoryCard` - only the featured mapping's dead `.filter` is dropped.
