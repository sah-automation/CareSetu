# Brief - T6 Emit `partner.selected` on card tap / profile open (frontend)

**Ticket:** #328 · **Parent:** #319 · **Refreshed:** 2026-09-06
**Reading surface:** ~5K tokens (budget 10K) - within budget

## Scope

Tapping a directory result card - or opening a provider profile - fires the `partner.selected` analytics event: a small client emitter POSTs it (anonymous actor, pick-only facts, fire-and-forget) to the new public ingest route, exactly once per interaction. Client-initiated product analytics, not a regulated act - no identity, consent, or PHI involved.

Acceptance criteria (from #328):

- [ ] The client emitter posts `partner.selected` to the public ingest route with an anonymous actor and pick-only facts.
- [ ] A card tap in the directory browse surface fires the event exactly once.
- [ ] Opening a provider profile fires the event exactly once.
- [ ] Frontend tests assert the single anonymous emission per interaction (mocked transport); no double-fire on re-render.
- [ ] `npm run test:unit:frontend`, `npm run typecheck`, `npm run lint` pass.

## Read-list (in order)

1. `docs/architecture/internal-modules.md` MOD-002 event registry - the `partner.selected` registration (from #326) this emitter consumes; event name constant must match exactly (~0.3K)
2. `docs/design/ui-blueprint.md` directory surface sections - where card taps and profile opens live (~0.5K)
3. `apps/frontend/src/lib/request.ts` - the `request`/`guardShape` transport the directory client already uses; your emitter POSTs through it (or the same fetch pattern) (~0.5K)
4. `apps/frontend/src/lib/directory/search.ts` + `links.ts` - the client-side directory conventions (event-name constant placement, provider-profile href) (~0.5K)
5. `apps/frontend/src/components/directory/DirectoryBrowser.tsx` (card tap) + `DirectoryCard.tsx` (the `Link` to `/providers/:id`) - where the tap handler attaches (~0.5K)
6. `apps/frontend/src/components/public/ProviderProfile.tsx` + `app/providers/[id]/page.tsx` - the profile-open trigger (mount effect) (~0.5K)
7. `DirectoryBrowser.test.tsx` / `DirectoryCard.test.tsx` / `ProviderProfile.test.tsx` - the mocked-fetch test harness pattern (assert the POST fires once, anonymous payload) (~2K)

## Do NOT read

- Any backend code (the route is consumed, not built), auth/identity wiring, consent/regulated-act code, other components. `npm run check:contract` does not cover the directory client - ignore it.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend`
- `npm run typecheck`

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:frontend`
- `npm run typecheck`
- `npm run lint`

## Handoff notes

- Baseline truth (2026-09-06, before any edit): frontend unit 674 pass (first run flaked with an unreproduced exit-1; re-run green).
- **Blocked by #326** - the backend route + registered event name must exist first.
- The emitted event name is exactly `partner.selected` (dot grammar); shipping it under any other spelling fails the backend catalog gate.
- Fire-and-forget: never block UI on the POST; failures are silent (follow the `featured-doctors` degrade-gracefully precedent in this codebase rather than throwing).
- Exactly once PER interaction: an onClick handler (not an effect that can re-run) on the card, and a mount-once effect on the profile page - the tests pin the no-double-fire behaviour.
- Pick-only facts: partner id + a source marker (e.g. card vs profile) + anonymous actor - mirror the payload field names the #326 envelope defines.
