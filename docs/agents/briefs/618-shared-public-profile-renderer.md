# Brief - 618 Extract the shared public-profile renderer and drive the live preview from it

**Ticket:** #618 · **Parent:** #599 · **Refreshed:** 2026-09-30
**Reading surface:** ~10.1K tokens raw (budget 10K) - marginally OVER; drop read-list item 3 to land at ~9.6K.

## Scope

The doctor's editor finally shows its own output. The public profile's renderer is extracted into one shared presentational component that takes the projection as a prop; the live preview feeds it local form state as the doctor types and the public page feeds it the API response. One code path, so they cannot drift apart - and the doctor sees, updating as they type, exactly what a patient will see.

AC:

- [ ] One presentational component renders the profile projection from a prop, with no data fetching of its own.
- [ ] The live preview feeds it local form state and updates as the doctor types; the preview is sticky on desktop and collapsible on mobile.
- [ ] The public page feeds it the API response through the same component.
- [ ] A suite renders the component once, and asserts that the preview and the public page both render through it - the no-drift property.
- [ ] Every field renders in the declared band, never the verified one.

## Read-list (in order)

1. `CONTEXT.md` - only these glossary entries: the **verified** entry (derived, never stored, "if the tick is gone, the card is gone"), plus **provider**, **directory entry**, **wider-area fallback**, and the doctor-console section. This is where the verified-versus-declared split the two bands encode is named. The explicit "credentials are verified, profile detail is declared" statement is being added to this file by the documentation ticket (#622), so today you infer it from **verified**: a verified field is what the platform derived and checked, a declared field is what a doctor says about themselves. Skip the patient-identity, record-consent, event-bus and split-origin sections. (~0.7K)
2. `docs/design/ui-blueprint.md` - the public-site section `§3.1` (ordered sections; row 5 is the provider profile, the surface this renderer is) and the cross-cutting patterns `§9` whole (loading/empty/error, bilingual mechanics, low-bandwidth posture, accessibility floor). These are the presentation rules both hosts must obey through the one component. Skip `§1`-`§2`, `§4`-`§8`, `§10`-`§12`. (~1.8K)
3. `docs/standards/coding-standards.md` - `§1` (language/framework lock: Next.js / React, one codebase), `§2` (module structure - cross-module access is via facades, which is the backend analogue of "a presentational component owns no transport"), `§3` (typing/naming), `§6` (the frontend unit command and colocated-test convention), `§8` (small single-purpose functions). There is no dedicated frontend section; the presentational-owns-no-fetching rule is this ticket's own constraint, carried by the component split, not a pre-existing standard. (~0.5K, **drop candidate**)
4. The `ProviderProfile` renderer component, in full - the component being extracted. Read its load-status machine (`loading | error | not-found | ready`), the effect that calls `fetchProviderProfile`, the mount-only `emitPartnerSelected` effect, and every render branch: the skeleton, the not-found state, the retryable error state, the hero (initials avatar, name, verified badge, subtitle), the trust cue, the credentials list and the details list. This is the body being lifted into the shared presentational component; the fetch and the emission stay behind in the container. (~3.0K)
5. The public profile API client and its response type - `fetchProviderProfile`, the `ProviderProfile` interface, the `ProviderProfileResult` union (`found | not-found`) and the `isProviderProfile` shape guard. This interface is the projection the renderer takes as a prop; the live preview must present the same shape. The shape guard and the 404-to-not-found mapping stay in the client, out of the presentational component. (~1.0K)
6. The renderer suite beside the component - its `fetchProviderProfile` mock, its `LangProvider` wrapper, its doctor and lab fixtures, and the assertions the extraction must keep alive: the verified indicator derives from the field, credential rows show type/status/expiry only, fields the payload does not carry are never invented, not-found and error states render, bilingual parity flips, and the partner-selected emission fires exactly once on mount across re-renders. The no-drift AC is asserted in this suite. (~1.6K)
7. The profile page shell landed by #615 - the identity band, the two trust bands, the anchor index, and the mount point for the live preview. The preview is fed by the shell's local form state, so identify the aggregate projection the shell exposes and the `doctorProfile` copy keys that declare the verified-versus-declared split. #615 has not landed on this tree yet - see Handoff notes. (~1.5K)

## Do NOT read

- `docs/archive/` (**never**), and everything under `docs/roadmap/` and `docs/architecture/` - this is a frontend extraction with no module or schema edge.
- The public profile route component (`ProvidersProfilePage`) beyond mounting the container - its metadata, `PublicHeader` and `PublicFooter` are unchanged here; #619 owns the field set, not this ticket.
- The doctor profile sections, their section writes and their API calls (`fetchDoctorProfile`, `updateDoctorProfile`, the four section writes) - you consume the shell's aggregate form state, not each section.
- `apps/backend` in full, including `get_provider_profile`, `ProviderProfileView` and the visibility predicate. The response is widened by #613 before you start; read the client's `ProviderProfile` interface, not the backend mapper.
- `DirectoryBrowser`, `DirectoryCard`, the pick-a-doctor page, the `SPECIALTY_LABEL_KEY` maps and the chip-group factories - #619 owns the label-consistency read, not this ticket.
- The directory `emitPartnerSelected` implementation internals - keep the call and its mount-once semantics, do not change emission behaviour or add an emission to the preview.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` - confirmed green 2026-09-30 on this tree (1697 passed).
- `npm run typecheck` - confirmed green 2026-09-30 (`tsc --noEmit` clean).
- `npm run lint` - confirmed green 2026-09-30.
- None of the three is environment-gated. Do not run `npm run test:e2e` or `npm run check:pages` for this ticket.

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:frontend` - the shared renderer suite renders the presentational component once from a projection prop and asserts that both the public host and the live preview render through it (the no-drift property), and the existing assertions from item 6 survive the split. Add an assertion that no verified marker renders for a field the projection does not mark verified.
- `npm run typecheck` - clean; the container keeps the `ProviderProfile` public symbol and its `{ partnerId }` prop, and the presentational component's prop is typed to the client `ProviderProfile` interface.
- `npm run lint` - pre-commit across all hooks (gitleaks, ruff, bandit, prettier, whitespace, the em-dash gate, the event-name gate, the module-boundary checker).

## Handoff notes

**Blockers, and what they will have landed by the time you start:**

- **#613** (public provider profile fields) - widens the backend `ProviderProfileView` with clinic name, a multi-valued specialty selection, languages, consulting days, consulting hours, about text, years of experience and the structured address parts, and keeps the four-condition visibility gate unchanged. Crucially, #613 deliberately leaves the frontend `ProviderProfile` interface and its `isProviderProfile` guard untouched: a widened response passes the guard unchanged, so the client silently ignores the new fields. Your renderer therefore takes the projection exactly as the client interface declares it; do not assume the widened fields are renderable yet. #619 widens the interface and the guard.
- **#615** (profile page shell) - rebuilds the doctor profile page as a shell plus one component per section, with an identity band that carries the avatar, the doctor's name as the heading, the clinic name beneath it, and a chip row with the verified tick and the doctor's specialties. It lands the identity band copy that declares the verified-versus-declared split, and it is the host of the live preview. Its own blockers are #604 (the Dashboard label and the account-menu key), #605 (the reusable section shell and per-section edit buffer) and #608 (the practice section write). If #615's brief is not on disk when you start, read the shell code it landed, not the old monolithic page.
- Transitive: **#605** (section shell and edit buffer) is where the per-section form state lives; the live preview reads that aggregate state. **#608/#609/#610** make the declared fields real, writable values, so the preview updates against real field names. **#612** makes specialty search an overlap match, which is why the preview can show more than one specialty.
- **The renderer never invents a verification.** Every verified marker on the surface (the hero verified badge, each credential's `verified` status label, the trust cue) renders only from the API projection: `verified` and `credential.status`. The backend hardcodes `verified=True` and `status="verified"` in `get_provider_profile` because reaching the profile already implies the four-condition visibility gate passed. The live preview must not fabricate a tick from local form state: when it is fed local form state it renders the declared fields, and any verified marker it shows must come from the last API projection held by the doctor profile context (`useDoctorProfile`), never from a typed value. #613's AC 4 and #619 both depend on this same property.

**Judgement calls made while mapping this surface:**

- **The extraction symbol split.** The current exported `ProviderProfile` owns both fetching and rendering. Split it into (a) a presentational component that takes the projection as a prop and owns no fetching, and (b) a thin fetching container the public route keeps mounting. Keep the container's public symbol `ProviderProfile` and its `{ partnerId }` prop stable - the route and the existing suite depend on them. Propose `ProviderProfileBody` for the presentational component and record whichever name you choose in the brief or a code comment; the durability contract is that exactly one of the two keeps the name `ProviderProfile`.
- **The mount-once emission stays in the container, not the renderer.** The public page fires `emitPartnerSelected` with `source: "provider_profile"` exactly once on mount, keyed on `partnerId`, and never re-fires on retry or re-render. The doctor's live preview must not emit a patient pick. Keep the emission semantics byte-identical and out of the presentational component.
- **Stickiness and collapsibility are the shell's layout, not the renderer's.** The renderer takes the projection and renders the bands; the sticky-on-desktop / collapsible-on-mobile host is #615's shell (or the preview wrapper you add there). Do not bake a layout host into the presentational component.
- **Relevant ADRs.** **ADR-0011** (credential expiry, lazy-on-read plus daily sweep) is the standing rule the renderer must not weaken: visibility derives on every read, the tick is never stored, and a false tick can never render. **ADR-0012** (one directory entry per partner) is why the projection is a single object rather than a list. **ADR-0020** (private profile-media bucket) is why any photo in the projection is a private key streamed by the backend; if the renderer ever shows a photo it goes through the existing byte-reader seam (`useProfilePhotoSource`), never a URL. **ADR-0003** (db-per-module isolation) bounds what the client may assume about the fields, not this component's structure.
