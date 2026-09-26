# Brief - 556 Extract the shared profile photo-resolution hook and refactor the profile photo card onto it

**Ticket:** #556 · **Parent:** #553 · **Refreshed:** 2026-09-27
**Reading surface:** ~7K tokens (budget 10K) - within budget

## Scope

Extract the profile photo card's private object-URL resolution into **one shared client-side seam** in the profile client module, and refactor the card onto it with **no user-visible behaviour change**. The hook takes a photo ref and returns a renderable source or `null` - fetch the bytes over the authed transport, present an object URL, revoke on teardown and on replacement, return `null` on any failure, and downgrade to "no photo" specifically on the `PROFILE_PHOTO_NOT_FOUND` error.

The avatar primitive is **not** changed. The ref-keyed cache **is** built here, because #556's own acceptance criteria ask for it and #557's read-list expects it landed by this slice: one ref, one request, the entry dropped when the ref changes or is cleared. What #557 owns is migrating the three chrome consumers onto the hook, not the cache itself.

## Read-list (in order)

1. **The private object-URL effect inside the profile photo card** - this is the code being extracted, so read it closely. It holds: a null-ref short-circuit; a `cancelled` flag; a local `objectUrl`; a `typeof URL.createObjectURL !== "function"` guard; `createObjectURL` → set state; a catch that nulls the state and **only** downgrades to media-absent on the `PROFILE_PHOTO_NOT_FOUND` `ApiError` code; and a cleanup that sets `cancelled` and revokes. Its dependency array is the ref alone. Also read the header comment, which states the deep-by-design contract and the degrade-not-error rule. (~700 tokens)

2. **The card's upload/remove path and its props contract** - the props are the ref, the name, and an `onPhotoRefChange` callback; upload mints an idempotency key, PUTs, and calls back with the new ref; remove does the same in reverse. The card's preview avatar already receives the **resolved** URL, not the raw ref. The refactor must leave all of this identical. (~1.1K tokens)

3. **The profile client module's photo fetcher** - the thin typed wrapper that returns a `Blob` over the authed transport, and the shared request helper it builds on (`requestBlob`). The hook must go through this, not through `fetch` directly. Note there is **no hooks file** in the profile client area today - decide where the new hook lives and say so in the PR. (~600 tokens)

4. **The avatar primitive** (`components/ui/avatar.tsx`, 72 lines - read whole) - the props contract, the source-comment that records the photo branch as dormant pending an upload seam, and the ref-acceptance rule (a prefix allowlist of `http://`, `https://`, `/`, `data:`, `blob:`; anything else is treated as unset). `blob:` is already allowed, so an object URL passes. **This file does not change.** (~600 tokens)

5. **The card's existing test suite** (`ProfilePhotoCard.test.tsx`, 301 lines) - read it whole. It is the contract you must not break, and several tests are load-bearing for the extract: the object-URL stubs (saved and restored in `beforeEach`/`afterEach`), the assertion that the `img` src is the blob URL and **not** the media key, revoke-on-unmount, and degrade-to-no-`img` on `PROFILE_PHOTO_NOT_FOUND`. The mocking of the profile client module is the pattern #557 will copy. (~2.6K tokens)

6. **ADR-0020, decisions D1 and D2** - the key layout is reserved for a later resize step, and photos are streamed through the backend, never publicly addressable. Nothing here changes the key shape or adds a public URL. (~1.2K tokens)

## Do NOT read

- **The avatar consumers** - the desktop account trigger, the account menu identity header, the mobile more-sheet account card, the doctor disc. #557 migrates them; reading them here is context you will not use.
- The doctor profile page's duplicated object-URL effect, the doctor patient/case pages' effects, the intake voice page's effect. They are separate duplication, out of scope.
- The backend media stores, the consent/care/health modules, `docs/archive/` (the PRD supersedes it), binary assets, migrations.

## Baseline verify (must pass before the first edit)

```bash
npm run test -w @caresetu/frontend -- src/components/patient/profile/ProfilePhotoCard.test.tsx
```

Confirmed green on the untouched tree at brief time: the card, account-menu and app-shell suites together are **81 passed** across 3 files. Note the suite emits pre-existing `Error: Not implemented: navigation` stderr noise from jsdom - that is not a failure.

## Done-verify (acceptance criteria → commands)

- The card's suite passes with **no assertion weakened or deleted to accommodate the refactor**:
  ```bash
  npm run test -w @caresetu/frontend -- src/components/patient/profile/ProfilePhotoCard.test.tsx
  ```
- The hook is genuinely shared and genuinely transport-aware: a test drives the hook directly (or through the card) and asserts an object URL is returned for a ref and `null` for no ref / for a failed fetch.
- Nothing regressed across the frontend, and types hold:
  ```bash
  npm run test:unit:frontend
  npm run typecheck:frontend
  ```

## Handoff notes

- **The avatar primitive's contract is correct and must not change.** It is a presentational component with no transport knowledge. Loosening it to accept opaque refs would spread key-shape knowledge into every consumer - that is the bug, not the fix. The whole point of this slice is to put the resolution _behind_ the primitive instead.
- **This is an extract, not a rewrite.** The card's current logic is right. The risk is drift, so move it and change nothing - every behaviour in the existing suite must survive verbatim.
- **Two fetch sites matter and they differ.** On `PROFILE_PHOTO_NOT_FOUND`, the card must show "no photo" (Remove button disappears). On any other failure it must keep the Remove button and show a failure notice. The hook must not collapse those two into one. Note the doctor case-page effect uses the _audio_ path and adds its own error state - do not copy that shape here.
- **The cache lands with the hook; the consumers land in #557.** #557 needs three avatars to resolve one ref with one request, keyed by ref, dropping the entry on change or clear. The shape has to make that easy, but do not migrate consumers here.
- **Object-URL lifecycle is the leak risk.** Revoke on teardown _and_ on replacement. There is a revoke-on-unmount test today; keep it passing.
- **ADR-0020 D2 must survive the refactor.** Still streamed through the backend, still never publicly addressable, still never a URL the browser reaches without a session.
