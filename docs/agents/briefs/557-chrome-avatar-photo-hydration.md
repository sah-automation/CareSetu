# Brief - 557 Hydrate the desktop and mobile chrome account avatars from the shared photo hook

**Ticket:** #557 · **Parent:** #553 · **Refreshed:** 2026-09-27
**Reading surface:** ~6K tokens (budget 10K) - within budget

## Scope

My uploaded photo appears in the desktop top-right account trigger, in the account menu's identity header, and on the mobile More-sheet account card - and a replacement updates all three at once. Today all three pass the raw opaque photo ref straight to the avatar primitive, which correctly rejects it as unrenderable and falls through to the name initial, **permanently**.

Migrate all three onto the one shared hook from #556, backed by a single **ref-keyed cache** so three avatars showing one ref issue one request rather than three. The cache drops its entry when the ref changes or is cleared, so a replace or remove can never show stale bytes. A failed fetch degrades to the initial rather than a broken image.

The doctor's account-menu disc keeps its person-icon fallback - hydrating it is explicitly later work and is not touched here.

## Read-list (in order)

1. **The shared photo-resolution hook and its ref-keyed cache** (landed by #556) - its signature, how it keys and drops cache entries, and what it returns for null / failed / not-found. If #556 left the cache shape permissive, this is where you tighten it. (~800 tokens)

2. **The desktop account menu** - read the two patient avatar call sites only: the trigger button's avatar, and the identity header inside the dropdown. Both read `saved?.photo_ref` and `saved?.name` off the optional profile context. **Also read the doctor disc call site immediately after them** - it deliberately passes neither, and you must leave it that way; there is a comment saying so. (~1.5K tokens)

3. **The mobile more-sheet account card** - the account-card component inside the bottom tabs, whose avatar receives `photo_ref` and `name` threaded down from the caller. Read the threading, not the whole tabs file. (~1.0K tokens)

4. **How the ref reaches the consumers** - the profile context: the optional-profile accessor the chrome uses, and the `syncPhotoRef` callback that spreads the new ref into the saved profile _and_ the local draft. This is the path a replace or clear travels, and it is why the cache key changes. (~700 tokens)

5. **The existing account-menu avatar tests** - read the patient-avatar describe block in full. Two cases are directly in scope: the one that pins an `https` ref rendering an image, and **the one that pins a bare ref like `me.jpg` as dormant, the initial winning, and no `img` rendered.** That second test exists to pin the bug and must be **rewritten** to the new behaviour, not deleted. Also read the named-profile fixture with a null ref. (~1.2K tokens)

6. **The app-shell more-sheet avatar test** - pins the initial for a null ref on the mobile card. It must stay green. (~400 tokens)

## Do NOT read

- **The avatar primitive's internals.** Its contract does not change in this slice; do not touch it.
- The profile photo card (already migrated by #556), the doctor profile page, the doctor patient/case pages' object-URL effects, the intake voice page.
- Backend modules entirely - consent, care, health, intake, media stores.
- `docs/archive/` (the PRD supersedes it), binary assets, migrations.

## Baseline verify (must pass before the first edit)

```bash
npm run test -w @caresetu/frontend -- src/components/dashboard/AccountMenu.test.tsx src/components/dashboard/AppShell.test.tsx
```

Confirmed green on the untouched tree at brief time: together with the photo-card suite, **81 passed** across 3 files. Note the pre-existing `Error: Not implemented: navigation` stderr noise from jsdom - not a failure.

## Done-verify (acceptance criteria → commands)

- All three surfaces hydrate. Assert an **image element with a renderable source** is rendered - not that a hook was called, and not that internal state was set:
  ```bash
  npm run test -w @caresetu/frontend -- src/components/dashboard/AccountMenu.test.tsx src/components/dashboard/AppShell.test.tsx
  ```
- One ref, one request: the test must count fetch calls and prove three avatars sharing one ref issue **one**.
- Replace and clear both drop the cache entry - no surface shows old bytes.
- Nothing else regressed, and types hold:
  ```bash
  npm run test:unit:frontend
  npm run typecheck:frontend
  ```

## Handoff notes

- **Blocked on #556.** The hook must exist first. Do not re-derive the resolution locally in a consumer.
- **One assertion must flip, by design.** The existing "bare `photo_ref` stays dormant, letter wins" test is the bug's fingerprint. It becomes "a saved profile carrying a photo ref renders an image in the trigger and in the identity header". This is the one place where a green baseline is expected to go red.
- **The doctor disc is a deliberate omission, not an oversight.** It renders the person icon with no ref and no name, and a comment defers hydration. Leave it exactly as it is.
- **The three surfaces are one cache, not three fetches.** A single ref-keyed cache is what keeps the account surfaces snappy. Three consumers each calling the hook independently with their own fetch would satisfy the rendering tests and fail the intent - that is why the fetch-count assertion is in the acceptance criteria.
- **Degrade, never break.** A network blip must land on the initial, not on a broken image. Do not surface a failure notice on a chrome avatar.
- **A ref change must invalidate.** The context's `syncPhotoRef` is the only thing that moves the ref; the cache key follows it, so a replace or clear is automatically a new key. Verify there is no path that leaves a stale object URL alive.
- **ADR-0020 D2 still holds** - resolved source in hand, still streamed through the backend, still never publicly addressable.
