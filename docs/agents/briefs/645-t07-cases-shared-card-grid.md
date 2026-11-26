# Brief - 07 Doctor cases list onto the same shared doctor card grid

**Ticket:** #652 · **Parent:** #645 · **Refreshed:** 2026-10-06
**Reading surface:** ~9K tokens (budget 10K) - within budget

## Scope

The doctor's cases list stops reading `Case #<id>`. A new frontend client for the cases-list endpoint, guarded at runtime and pinned by a schema-walking contract test, feeds the same shared card the patients list uses - so a doctor with nine open cases sees nine distinguishable rows instead of nine identical ids.

Each card carries the patient's avatar initial, name and age, the case identifier (so an exact case can still be cited), the case stage, the amber Verify chip on a forced-review case, and how long ago the case was last updated so triage runs on staleness rather than memory. The whole card is the link target. Grid on a desktop, stacked rows on a phone. The existing empty state, loading skeleton, and error banner are preserved and the skeleton matches the new card shape.

## Acceptance criteria

- [ ] A frontend client function for the cases-list endpoint exists, with runtime shape guards that actually execute when the network layer is stubbed and the client module is real - including a body missing a new field, which fails loudly rather than rendering nothing.
- [ ] The new client has a schema-walking contract test built by walking the exported OpenAPI slice rather than hand-copying bodies, generating a removal case per row field so a field added to the backend DTO gets a guard without anyone remembering to add one.
- [ ] Each card shows the patient's avatar initial, name, and age.
- [ ] The case identifier is still visible on the card, alongside the case stage.
- [ ] A forced-review case carries the amber Verify chip, visibly different from a clean one before the case is opened.
- [ ] The card shows how long ago the case was last updated.
- [ ] The whole card is one link target; the grid collapses to a single column on a phone with no horizontal scroll.
- [ ] Every card is a single focus stop whose accessible name includes the patient.
- [ ] The existing empty state, error banner with its trace id, and loading skeleton all still render, with their existing test ids; the skeleton matches the card shape.
- [ ] Every existing data-testid on the cases list is preserved; new ones are added alongside rather than replacing.
- [ ] Every new card label, chip, and empty state ships in English and Hindi.
- [ ] The doctor console landing page's own open-cases card is untouched by this ticket.

## Read-list (in order)

1. The `#645` spec's "Shared doctor card" block plus user stories 1–13 and 66–68 - what the case card must carry, and the consent-gating story that is satisfied by construction. (~900 tokens)
2. The doctor cases page in full - its `LoadStatus` machine, the local `LoadingSkeleton`, `stageLabel`, `stageChipClass`, and the current list markup. Note the testids you must preserve: `cases-skeleton`, `empty-state-wrapper`, `cases-list-wrapper`, `cases-list`, `case-item`, `case-item-id`, `case-item-stage`, `case-item-open`, plus the error banner with its trace id. (~2K)
3. The shared doctor card from #651's diff - its props and its exported names. You are a consumer, not a second author; if you need a variant, extend that component rather than forking it. (~1K)
4. The doctor API client module - one existing read function end to end (the patients list), for the guard style, the `guardShape` usage, and the error-message wording convention. (~1K)
5. The doctor console contract test in full - the schema-walking fixture builder, the `$ref` / `anyOf` / enum resolution, the removal-case generator, and the substring guard-message coupling. This is the pattern you extend, not duplicate. (~2.5K)
6. The doctor cases page test suite in full - the fixtures, the mocking shape, and every assertion you must not break. (~1.5K)
7. The dictionary file's doctor-console namespace in **both** locales - including the existing case-item meta string and the stage labels you reuse. (~700 tokens)

## Do NOT read

- `docs/archive/`.
- The backend facade and the new route's implementation. The wire shape is pinned by the exported slice (#650); if a field you expect is missing there, that is a #646/#650 problem, not something to work around here.
- The doctor console **landing page**, even though it renders the same data with the same testids. It is out of scope by the spec and by this ticket's acceptance criteria. Changing it will break its own suite.
- The patients list page beyond what #651's card already documents.
- The care API client module, except for the link target format the cases page already builds.
- `docs/design/ui-blueprint.md` - #651 already made the layout decisions.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` - expect **1 failed | 2024 passed**, the single pre-existing failure being `record/page.test.tsx > RecordPage access history > shows an empty state when there is no access history`. It fails on the untouched tree.
- `npm run typecheck` - **currently green.**
- `npm run check:pages`.

#647 (route) and #650 (slice) must have landed, and #651 (the shared card) must have landed. Verify each; do not start on a blocked tree.

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:frontend` - new client guard cases, new contract-test cases, new page cases green; every existing cases-page assertion still green; the one pre-existing failure is still the only failure.
- `npm run test:unit:backend` - #650's slice-pinning test must still pass. If the frontend and backend contracts have drifted, this is where it shows.
- `npm run typecheck` - `tsc --noEmit` is also the bilingual gate: a key in English and missing from Hindi is a compile error.
- `npm run lint`
- `npm run check:pages`

## Handoff notes

- **The whole reason the runtime guards get their own test is #624.** Both existing page suites mock the transport module wholesale, so the guards never executed and a `photo_ref` / `has_photo` drift shipped green until a doctor opened the page. Stub **only** the network layer and keep the client module real. A body missing a new field must fail loudly.
- **Extend the existing contract test, do not write a new one.** It builds fixtures by walking the exported slice, which is precisely why it exists. `it.each(Object.keys(schemas.<NewRow>.properties))` is the pattern - a field added to the backend DTO then gets a removal case without anyone remembering to add one.
- **Guard-message strings are substring-coupled.** The contract test matches on the tail of the guard message. If you reword one, update the test in the same change or it will pass for the wrong reason.
- **This list renders in two places.** The cases page and the doctor console landing page both render the open-cases list with **identical `data-testid`s**, and both suites assert them. Only the cases page moves to cards. Do not "fix" the duplication - it is out of scope and editing the landing page breaks its suite.
- **The skeleton is hand-rolled on this page** (raw animated divs) while the patients page uses the shared `Skeleton` primitive. Matching the new card shape is in scope; swapping to the primitive is a small, natural part of that. Do not go further.
- **No query parameters.** The endpoint takes none, the facade returns the full derived list creation-ascending, and the frontend must not invent a filter or a page control here. Pagination on this surface specifically is deferred by the spec.
- **The case identifier stays on the card.** A doctor has to cite an exact case in a note or a referral. Name and age are additive, not a replacement.
