# Brief - 619 Render the declared band on the public provider profile

**Ticket:** #619 · **Parent:** #599 · **Refreshed:** 2026-09-30
**Reading surface:** ~9.6K tokens (budget 10K) - within budget; read-list item 6 is the drop candidate if you are tight.

## Scope

A patient can finally find the kind of doctor they need and see whether they are the right fit: every specialty the doctor practises rather than one, the clinic name so they know which building to go to, the languages they will be understood in, the days and hours so they do not make a wasted trip, the full address including locality, city and PIN code, and the experience and about text. The platform's verified claims and the doctor's own claims render as visibly different things.

AC:

- [ ] The public provider profile renders the clinic name, every specialty, the languages, the consulting days and hours, the full structured address, the years of experience and the about text, all through the shared presentational component.
- [ ] The declared fields render in the declared band and the verified fields in the verified band, and the difference is visible without reading a legend.
- [ ] The renderer never invents a verification - every verified marker it shows came from the API response.
- [ ] The page still renders the not-found state for an unknown or non-visible provider.
- [ ] A frontend suite asserts the declared band renders each of the new fields.

## Read-list (in order)

1. `CONTEXT.md` - only these glossary entries: the **verified** entry (derived, never stored, always agreeing with search visibility - "if the tick is gone, the card is gone"), plus **provider**, **directory entry**, **specialty**, **wider-area fallback**, and the doctor-console section. The explicit verified-versus-declared statement is being added to this file by #622, so today infer it from **verified**: a verified field is what the platform derived and checked, a declared field is what a doctor says about themselves. Skip the patient-identity, record-consent, event-bus and split-origin sections. (~0.7K)
2. `docs/prd/project-prd.md` - the provider-profiles feature `FEAT-005` whole: its user story, the happy-path scenario, the credentials-expired-or-revoked scenario, Rule 1 (the platform displays and gates credentials; it does not itself perform regulated acts) and the state-change line. This is the feature the page realises, and it is where "the platform's claims versus the doctor's claims" is grounded. Its delivery notes were extended by the doctor-console batch (#529); the new field set is added to them by #622. (~1.0K)
3. `docs/design/ui-blueprint.md` - the public-site section `§3.1` (row 5, the provider profile) and the cross-cutting patterns `§9` whole (loading/empty/error, bilingual mechanics, low-bandwidth posture, accessibility floor). These bind the declared band's rendering. Skip `§1`-`§2`, `§4`-`§8`, `§10`-`§12`. (~1.8K)
4. The shared presentational component landed by #618 - its projection prop type, its declared band and verified band, its empty/null handling, and how the public host renders it. This is the component you extend for each new declared field; do not re-implement or fork it. Identify the prop symbol #618 chose and the band boundary it drew. (~2.8K)
5. The public profile route component (`ProvidersProfilePage`) and its API client - `fetchProviderProfile`, the `ProviderProfile` interface, the `ProviderProfileResult` union (`found | not-found`) and the `isProviderProfile` shape guard. Confirm the widened response type is the one the renderer consumes, that the guard is the one you widen (a guard, not a cast), and that the not-found branch and its error code mapping (`PROVIDER_PROFILE_NOT_FOUND`) are untouched. (~1.3K)
6. The directory result card `DirectoryCard` and the pick-a-doctor page - specifically the card's meta join over `[specialty, type, area]`, the `fell_back` flag on `DirectorySearchView`, and the shared `outsideAreaLabel` copy. Confirm the wider-area label this page shows still reads correctly against the card's locality label, and that the card's density is not expanded. (~1.2K, **drop candidate**)
7. The `providerProfile` i18n namespace (both locales) - the labels and headings the new declared fields need (clinic name, languages, consulting days and hours, the structured address parts, years of experience, about), and the bilingual parity rule that every key exists in both locales. The dictionary is one file; read only this namespace. (~0.8K)

## Do NOT read

- `docs/archive/` (**never**), and everything under `docs/roadmap/` and `docs/architecture/` - this ticket renders fields on an existing page; it adds no module, schema or event edge.
- `apps/backend` in full, including the `get_provider_profile` mapper, `ProviderProfileView`, the credential-validity `provider_visible` predicate, the directory models and every migration. The widened response and its unchanged visibility gate are #613's surface and land before you start. Read the client's `ProviderProfile` interface, not the mapper.
- The doctor profile page, its sections, the section shell and the edit buffer - the declared band renders on the patient-facing page; the live preview in the console is #618's.
- The whole `DirectoryBrowser` search UI, its facet chips, its `SPECIALTY_LABEL_KEY` map and its `chipClass` factories - you only confirm the card's area label still reads correctly; do not restyle or re-chip the browse surface.
- The pick-a-doctor page's suggestion logic (`deriveSpecialtyFromSymptoms`) and its suite - its unit test passes while production search is broken because it mocks the directory client; that is a known defect recorded by #612, not something to fix here.
- The `PublicHeader` / `PublicFooter` chrome, the `providers/[id]` route metadata and the anonymous `partner.selected` emission - all unchanged.
- The service-area vocabulary table, `resolve_service_area` and `DEFAULT_SERVICE_AREA_NAME` - #612 demotes that concept from the read path; do not reintroduce it on this page.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` - confirmed green 2026-09-30 on this tree (1697 passed).
- `npm run typecheck` - confirmed green 2026-09-30 (`tsc --noEmit` clean).
- `npm run lint` - confirmed green 2026-09-30.
- `npm run test:e2e` is in the ticket's verify list but is **environment-gated**: it needs Playwright browsers from the shared cache. This ticket adds no new e2e spec; #621 extends the doctor-workspace spec. Run it only to confirm the existing specs stay green, and note a skip in your report if the browsers are unavailable.

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:frontend` - a suite asserts the declared band renders each new field (clinic name, every specialty, the languages, the consulting days and hours, the full structured address including locality, city and PIN code, the years of experience and the about text) from a projection that carries them; that a field absent from the projection renders nothing rather than an invented string; and that no verified marker renders for a field the projection does not mark verified. The existing not-found test still passes.
- `npm run typecheck` - clean; the client `ProviderProfile` interface and the `isProviderProfile` guard both carry every new field the renderer reads.
- `npm run lint` - pre-commit across all hooks (gitleaks, ruff, bandit, prettier, whitespace, the em-dash gate, the event-name gate, the module-boundary checker).
- `npm run test:e2e` - existing specs stay green (environment-gated; this ticket adds no spec).

## Handoff notes

**Blockers, and what they will have landed by the time you start:**

- **#618** (shared public-profile renderer) - lands one presentational component that renders the profile projection from a prop with no fetching of its own, used by both the doctor's live preview and this public page. It also lands the container/presentational split and the no-drift suite. Your job is to widen the projection the component consumes and render the declared fields in its declared band. Do not fork the renderer: if the projection prop cannot carry a field, extend the prop type in the shared component, not in a local copy on the route.
- Transitive: **#613** already widened the backend response with clinic name, the multi-valued specialties, languages, consulting days and hours, about text, years of experience and the structured address parts, and left the frontend `ProviderProfile` interface deliberately untouched. So the client type you inherit still carries only `partner_id`, `practice_name`, `partner_type`, `specialty`, `area`, `verified`, `credentials`. Widening it here, together with `isProviderProfile`, is part of this ticket - a widened response passing the old guard was #613's stopgap, not the contract you render.
- Transitive: **#612** made specialty search an overlap match and served the card's `area` from the doctor-declared locality instead of the service-area vocabulary. That is why the wider-area label on this page must agree with the card's locality label.
- Transitive: **#609** derives the practice position from the declared PIN, so the structured address parts this page renders are the doctor's declared address, not a coordinate pair.

**The truthfulness rule - do not weaken it:**

- **The renderer never invents a verification.** Every verified marker on this page (the hero verified badge, each credential's `verified` status, the trust cue) comes from the API projection: `verified` and `credential.status`. The backend hardcodes `verified=True` and `status="verified"` in `get_provider_profile` once the four-condition visibility gate passes, because a reachable profile already implies it. Nothing in the declared band may render a verified marker, and no declared field may be promoted into the verified band because it looks trustworthy. The declared band says in words that these are the doctor's own claims; the distinction must be visible without reading a legend. This is the same property #613's AC 4 protects.
- Every declared field renders only when the projection carries it: a null or empty value renders nothing, never an invented string (the existing renderer and card already follow this "never invent an area string" discipline - keep it).
- The not-found branch stays exactly where it is: an unknown or non-visible provider still resolves to the not-found state through the client's `PROVIDER_PROFILE_NOT_FOUND` mapping. Do not add a partial-render path that shows declared fields for a provider the gate rejected.

**Judgement calls made while mapping this surface:**

- **The shared component's symbol comes from #618.** If #618 named the presentational component `ProviderProfileBody` and kept `ProviderProfile` as the fetching container, extend `ProviderProfileBody` and leave the container's fetch and emission untouched. If #618's brief is not on disk when you start, resolve the symbol by grepping the public profile component for the prop-taking export, and record the symbol you used.
- **Label consistency is a read, not an edit.** The wider-area label is the shared `outsideAreaLabel` copy plus the `fell_back` flag on `DirectorySearchView`; the card's area text is the doctor-declared locality. Do not relabel the card or the pick card from this page. If this page itself needs to say "outside your area", reuse `outsideAreaLabel` so the two surfaces cannot drift.
- **Relevant ADRs.** **ADR-0011** (credential expiry, lazy-on-read plus daily sweep) is the standing rule the not-found state and the verified marker keep: visibility derives on every read, declared fields never change visibility, and the tick is never stored. **ADR-0012** (one directory entry per partner) is why the page still represents one provider object. **ADR-0003** (db-per-module isolation) is why the locality/area projection change was #612's read-side change and not a schema change here. **ADR-0020** (private profile-media bucket) is why a photo, if the declared band shows one, is streamed through the byte-reader seam (`useProfilePhotoSource`) rather than addressed by URL. The two new ADRs written by #622 (a profile save moves the public directory position; the practice position is a PIN centroid) are the policy behind the address this page renders, not a code contract for this ticket.
- **Bilingual parity.** Every new label ships in both locales; the parity suite walks both recursively and fails on a one-sided key. Read only the `providerProfile` namespace, and add `hi` alongside every new `en` key.
