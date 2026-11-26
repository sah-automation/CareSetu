# Brief - 568 Generalise the shared photo-source seam to a byte reader, put the doctor profile page on it

**Ticket:** #568 · **Parent:** #560 · **Refreshed:** 2026-09-27
**Reading surface:** ~7.9K tokens (budget 10K) - within budget
**Chain position:** 2 of 4. **Read `docs/agents/briefs/567-shell-supplies-doctor-role.md` first** and treat everything it established as already known. This ticket adds no role plumbing.

## Scope

The doctor's own profile page's photo goes through the same private, ref-keyed resolution the patient's does, so the two surfaces cannot drift apart and the doctor's bytes are read once.

**Today's hole.** `apps/frontend/src/app/(doctor)/doctor/profile/page.tsx:934-959` hand-rolls the resolution in a local effect: null-ref short-circuit, `cancelled` flag, `URL.createObjectURL` guard, object URL, `revokeObjectURL` in the cleanup, `.catch` that nulls the state. All of that is correct - and all of it duplicates a seam that already exists and is better. Specifically it has **no shared cache** (so it re-reads per mount) and **no definite-absence versus failed-read distinction** (it collapses every failure to the same answer).

**The change.** `useProfilePhotoSource` gains a byte-reader parameter, defaulting to the patient's own reader, so every existing patient caller is byte-for-byte unchanged in behaviour. The doctor profile page is switched onto the seam and its local effect is **deleted, not left alongside**.

**No backend change.** `fetchDoctorProfilePhoto` already streams the doctor's own private bytes over the authed transport (`lib/doctor/api.ts:414-416`). No new endpoint.

## Key facts and prior art

- **The seam is `useProfilePhotoSource`** (`apps/frontend/src/lib/profile/useProfilePhotoSource.ts:115`), not a generic name. Its byte reader is the **module-private `resolveStoredPhoto()` at line 80**, which hardcodes `fetchPatientPhoto` from `@/lib/profile/api` (`:31` import, `:82` call). That hardcoding is the single line that has to become a parameter.
- **The doctor's byte reader is `fetchDoctorProfilePhoto`** (`lib/doctor/api.ts:414-416`), a one-line `requestBlob("/v1/doctor/profile/photo")` wrapper. Same shape as the patient's `fetchPatientPhoto` (`lib/profile/api.ts:155`) - which is why a byte-reader parameter is the whole generalisation.
- **Five behaviours the seam already owns, each carrying a rationale comment. All five are what the doctor's local effect lacks:**

  | behaviour                                                              | lines              | what the doctor's local effect lacks          |
  | ---------------------------------------------------------------------- | ------------------ | --------------------------------------------- |
  | module-level ref-keyed `CACHE` with holder acquire/release             | 78, 91-108         | no cache at all - re-reads per mount          |
  | one shared read per ref, dropped at zero holders                       | 59-64, 102-108     | n/a                                           |
  | object-URL ownership + revoke on teardown **and** replacement          | 133-158            | has teardown revoke, but no holder accounting |
  | SSR/jsdom guard for missing `URL.createObjectURL`                      | 125-132            | has an inline copy of the same guard          |
  | definite absence (`PROFILE_PHOTO_NOT_FOUND`) vs a blip (anything else) | 34, 80-89, 142-150 | collapses both to `null`                      |

- **The cache key is the ref, not a request parameter** (comment at 69-77): the endpoint serves the caller's _current_ photo, so a ref says which generation a consumer believes it is showing. The doctor's endpoint has the same semantics, so the same keying is correct for it. Do not "fix" this by threading a ref into the reader.
- **The existing suite is the prior art and the contract.** `useProfilePhotoSource.test.ts` already pins the single-read count, the revocation counts, the absence-versus-blip distinction, and the no-`createObjectURL` capability gap. Its mocking shape is `vi.mock("@/lib/profile/api", importOriginal)` with `fetchPatientPhoto: vi.fn()` (lines 17-20) - a **partial** mock, which is exactly what lets a second reader be injected without disturbing the first.
- **`ProfilePhotoCard.tsx:56-58` is the consumer that must not move.** It calls `useProfilePhotoSource(photoRef)` with one argument and consumes **both** returns: `const { src: photoUrl, absent: mediaAbsent } = useProfilePhotoSource(photoRef);` then `hasPhoto = photoRef != null && !mediaAbsent`. A defaulted second parameter keeps this line unchanged.
- **`PhotoCard` receives the resolved URL, not the ref** (`(doctor)/doctor/profile/page.tsx:307-344`): `PhotoCardProps.photoUrl: string | null` and `<Avatar photoRef={photoUrl} name={profile.practice_name} .../>`. The page already treats the resolved source as its input; only the producer of that source changes.
- **The doctor suite already stubs object-URL creation** (`page.test.tsx:114-131`, saved in `beforeEach` and restored in `afterEach`, returning the constant `"blob:http://localhost/doctor-photo"`), and already mocks the whole `@/lib/doctor/api` module (`:52-62`). Injecting the doctor reader through the hook's parameter means **the existing doctor suite's mocks keep working unchanged** - `getPhoto` stays `vi.mocked(fetchDoctorProfilePhoto)`.

## Chain ordering (where the later tickets attach)

| ticket   | what it inherits from this one                                                                                                                                                                                      |
| -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **#569** | the byte-reader parameter. It resolves the doctor's photo ref in the account menu and in the dropdown header, so it needs the hook to already take a doctor reader. **This is the only reason #568 precedes #569.** |
| **#570** | nothing structural. It reuses the resolved `photoSrc` the #569 change already produces for the identity-header avatar.                                                                                              |

**This ticket must not fetch anything new.** The doctor profile page already loads `photo_ref` via `fetchDoctorProfile()` (`page.tsx:912`); the hook only consumes the ref it is handed. Where the **chrome** fetches a doctor's ref at all is #569's job.

## Spec excerpt

`docs/adr/0020-*` is the governing decision and it is **unchanged** by this ticket. Two of its rules are load-bearing here:

- **D1** - a `photo_ref` is an opaque object key with a reserved key layout. The ref is a claim, not a URL.
- **D2** - photos are **never publicly addressable**; every read streams decrypted bytes through the backend, so a leaked URL discloses nothing. `CONTEXT.md`'s "profile media" glossary entry restates this.

The brief's own acceptance criterion is the enforceable one: _"The photo is still resolved as a private object key over the authenticated transport. No publicly addressable URL is introduced."_ Do not add a `<img src={photo_ref}>` shortcut anywhere, and do not move the reader behind a public URL builder.

## Read-list (in order)

1. **`apps/frontend/src/lib/profile/useProfilePhotoSource.ts`, whole (162 lines)** - the seam being generalised, and the code the doctor's effect is being moved onto. Header comment 3-26 (the deep-by-design contract, the "no consumer builds that URL itself" rule, and the two-distinct-failure-answers rationale). `PHOTO_NOT_FOUND_CODE` 34. `ProfilePhotoSource` 36-49 (`src` + `absent`, both documented). `ResolvedPhoto` 51-57. `CacheEntry` 59-64. `NO_SOURCE`/`ABSENT` 66-67. The `CACHE` map and its "the ref is the cache key, not a request parameter" comment 69-78. **`resolveStoredPhoto()` 80-89 - the function that hardcodes the reader.** `acquire` 91-100, `release` 102-108. `useProfilePhotoSource` 115-162: the null-ref short-circuit 121-124, the capability guard 125-132, `live`/`objectUrl` ownership 133-140, the resolve handler 142-150, the cleanup 152-158. (~1.6K tokens)
2. **`apps/frontend/src/lib/profile/useProfilePhotoSource.test.ts`, whole (229 lines)** - the prior art and the contract that must keep holding. Header comment 1-8. The partial module mock 17-20. `getPhoto` 22. `REF`/`OTHER_REF` 24-25. `photoNotFound()` 27-34 and `networkBlip()` 36-43 - **the two distinct failure fixtures, reuse them for the doctor reader.** The object-URL stubs 45-60 (a distinct URL per call so a test can tell _which_ bytes were revoked) and the `afterEach` that calls `cleanup()` **before** restoring the stubs 62-70. `renderSource` 72-77, `flush` 79-82. Then the eleven cases: one-read-for-many 102-113, holder survival 115-128, per-consumer revoke 129-149, revoke on teardown 150-159, revoke-old/re-read-new on replacement 160-182, cache dropped on clear 183-198, **absence only on the not-found code 199-206**, **a failed read still looks present 207-220**, no `createObjectURL` 221-229. (~2.2K)
3. **`apps/frontend/src/app/(doctor)/doctor/profile/page.tsx` - four slices only.** 929-959 the hand-rolled effect **and its rationale comment**, which is the code being deleted. 896-898 the `photoUrl`/`photoBusy`/`photoFailure` state triple. 307-345 `PhotoCardProps` and the `Avatar` that receives the resolved URL. 1108-1120 the `<PhotoCard photoUrl={photoUrl} .../>` wiring. Note `photoBusy` and `photoFailure` are **upload** concerns and must survive - only the resolution goes. (~1.1K)
4. **`apps/frontend/src/app/(doctor)/doctor/profile/page.test.tsx` - three slices.** 52-62 the whole-module `vi.mock("@/lib/doctor/api")` and 71-76 the `vi.mocked(...)` aliases (`getPhoto` at 74). 114-131 the object-URL save/restore stubs. 499-545 the three photo cases: preview-through-an-object-URL 500-510 (asserts `src` is the blob URL and **not** the media key - keep this assertion verbatim), upload-then-re-stream 512-525, remove-then-fallback 527-544 (asserts the `img` disappears once the ref drops). (~1.1K)
5. **`apps/frontend/src/lib/doctor/api.ts` lines 253-291, 360-368 and 413-416** - `DoctorProfileView.photo_ref` at 255, `DoctorProfilePhotoRef` 289-291, `fetchDoctorProfile()` 361-368, and **`fetchDoctorProfilePhoto(): Promise<Blob>` 414-416**, the reader you inject. (~0.7K)
6. **`apps/frontend/src/lib/profile/api.ts` lines 145-175** - `uploadPatientPhoto` 132-153, **`fetchPatientPhoto(): Promise<Blob>` 155-162** (the default reader and the shape the doctor reader matches), `deletePatientPhoto` 164-175. Note the shared `requestBlob` helper underneath. (~0.5K)
7. **`apps/frontend/src/components/patient/profile/ProfilePhotoCard.tsx` lines 20-69** - the one consumer that must stay byte-identical. The props contract 27-34, the `api-errors`/idempotency/dictionary imports 20-25, and lines 50-58: the "a ref is a claim, the bytes are the fact" comment plus the **two-value destructure** `const { src: photoUrl, absent: mediaAbsent } = useProfilePhotoSource(photoRef)`. This is why the parameter must be optional. (~0.7K)

## Do NOT read

- **`docs/archive/`** - the PRD supersedes it.
- **`AppShell.tsx`, `Topbar.tsx`, `AccountMenu.tsx`, `AccountMenu.test.tsx`, `AppShell.test.tsx`** beyond the two `AccountMenu.tsx` lines (#567's file). The role plumbing is #567's; the chrome photo work is #569's. If you find yourself reading `AppShell.tsx:119-142`, you have started #569.
- **`lib/auth/staff-routing.ts`** and every `/me` / `partner_type` concern. Irrelevant to a byte reader.
- **The rest of the doctor profile page** (`DetailsForm` 495-725, `FeeEditor` 726-885, `CredentialsCard` 402-494, the notification machinery 76-112, `formFromProfile`/`invalidFields`/`updateFromForm` 155-249). You are changing the producer of one string prop on one card.
- **The rest of `page.test.tsx`** (the practice-details, fee, credential and bilingual cases, lines 145-498 and 546-702). Only the photo describe is in scope.
- **The rest of `useProfilePhotoSource.test.ts`'s consumers** - `BottomTabs.tsx:195` and the mobile More-sheet `AccountCard` (175-227), the patient avatar call site at `AccountMenu.tsx:109-111`. They are unchanged by a defaulted parameter; do not migrate or "improve" them.
- **Backend code, migrations, `docs/prd/*`, `docs/architecture/*`, `docs/roadmap/*`, `docs/standards/*`.** No module, event, schema or API change here. (`docs/adr/0020-*` decisions D1/D2 are quoted in the spec excerpt above; read them only if you need the original wording.)
- The intake voice page's effect and the doctor patient/case pages' effects. Separate duplication, not this ticket.

## Baseline verify (must pass before the first edit)

```bash
npx vitest run src/lib/profile/useProfilePhotoSource.test.ts "src/app/(doctor)/doctor/profile/page.test.tsx" --root apps/frontend
```

- **Confirmed green 2026-09-27** as part of the chain's four fast-loop suites: **4 files, 108 tests passed, 14.7s** (`AccountMenu`, `AppShell`, `useProfilePhotoSource`, `(doctor)/doctor/profile/page`). jsdom `Error: Not implemented: navigation` stderr noise is expected and is not a failure.
- Also green, and must stay green untouched: `src/components/patient/profile/ProfilePhotoCard.test.tsx` and `src/components/dashboard/AccountMenu.test.tsx` (the patient callers of the defaulted parameter).
- `npm run test:unit:frontend` is **red on the untouched tree at brief time** - #562 and #563 are the blockers (see `docs/agents/briefs/564-design-token-gate-class-attributes.md` for the measured 13-failure breakdown). Close them before the first edit, because "full suite green" is this ticket's done-verify.
- `npm run lint`, `npm run typecheck` - confirmed green 2026-09-27 per the #564 brief.

## Done-verify (acceptance criteria → commands)

- `npx vitest run src/lib/profile/useProfilePhotoSource.test.ts --root apps/frontend` - green, **with its eleven existing cases unchanged in what they assert**, plus the doctor-reader cases.
- `npx vitest run "src/app/(doctor)/doctor/profile/page.test.tsx" --root apps/frontend` - green, including the single-read assertion and the pre-existing "never the media key" assertion at `:509`.
- `npx vitest run src/components/patient/profile/ProfilePhotoCard.test.tsx src/components/dashboard/AccountMenu.test.tsx --root apps/frontend` - green, **with the patient call sites unmodified**.
- `npm run test:unit:frontend` - green, with #562 and #563 closed.
- `npm run lint`, `npm run typecheck`.

### Acceptance criteria as a checklist

- [ ] **The seam takes a byte reader, defaulted to the patient's own.** Every existing patient caller (`ProfilePhotoCard.tsx:57`, `BottomTabs.tsx:195`, `AccountMenu.tsx:109`) is **byte-for-byte unchanged** - a one-argument call still compiles and behaves identically. No existing call site is edited to pass a reader explicitly.
- [ ] **The doctor reader is `fetchDoctorProfilePhoto`**, injected by the doctor profile page, matching the patient's `() => Promise<Blob>` shape.
- [ ] **The doctor's hand-rolled resolution effect (`page.tsx:934-959`) is deleted, not left alongside.** Grep the file for `createObjectURL` and `fetchDoctorProfilePhoto` afterwards: the page should contain **no** direct resolution logic. `photoBusy` and `photoFailure` (upload concerns) stay.
- [ ] **One read per ref, asserted not assumed.** A test mounts two consumers of the same doctor ref and asserts the doctor reader was called **exactly once**, mirroring `useProfilePhotoSource.test.ts:102-113`. The page's own preview plus a second consumer must not add a second request.
- [ ] **The doctor surface gains the absence-versus-blip distinction.** Reuse the `photoNotFound()` / `networkBlip()` fixtures: a definite `PROFILE_PHOTO_NOT_FOUND` sets `absent: true`, and a `NETWORK_ERROR` leaves `absent: false`. **This is new behaviour for the doctor page** - the old local effect could not express it.
- [ ] **A failed read still degrades to the avatar fallback**, never an error surface. No `<img>` is left pointing at nothing, and the page's own upload-failure `ErrorBanner` is not triggered by a read failure.
- [ ] **Object-URL ownership and revocation are unchanged in shape**: created only while the consumer is mounted, revoked on teardown, revoked on replacement when the ref moves. The revocation assertions from the existing patient suite still hold.
- [ ] **No publicly addressable URL is introduced.** The doctor's photo still resolves from a private `photo_ref` over the authenticated transport; the page's `img src` is a `blob:` object URL and never the media key (the existing `:509` assertion is the proof).
- [ ] **The shared-seam and patient-avatar suites stay green unchanged in what they assert.** No existing assertion is weakened, skipped or deleted to accommodate the parameter.

## Handoff notes

- **This is a generalisation plus a delete, not a rewrite.** The doctor's local effect is _correct_. The reason to move it is that it is a second implementation that will drift - it already has, on cache and on the absence/blip split. Move it; change nothing else.
- **The default parameter is the whole compatibility story.** A required reader would force an edit at three patient call sites and blow the "byte-for-byte unchanged" criterion. Optional, defaulted to `fetchPatientPhoto`.
- **Watch the `afterEach` ordering trap.** `useProfilePhotoSource.test.ts:62-70` calls `cleanup()` before restoring the object-URL stubs, because unmounting is what drops the cache entry. Any doctor-reader test you add inherits that discipline or the next test inherits a live cache entry.
- **The cache key stays the ref.** Do not pass the ref into the reader. The comment at `useProfilePhotoSource.ts:69-77` explains why: the endpoint serves the caller's _current_ photo, so a ref is a generation claim, never a request parameter. Both photo endpoints have that semantics.
- **The doctor's suite needs no new mocking.** It already mocks the whole `@/lib/doctor/api` module and already stubs `URL.createObjectURL`. Injecting through the parameter is what keeps that true - resist the urge to add a second mock layer.
- **What you deliberately do not do:** the doctor's photo ref is already in hand from `fetchDoctorProfile()` at `page.tsx:912`. Do not add a second read to get it, and do not touch the chrome. #569 fetches the doctor's ref in the shell; that is a different, later concern.
- **No em-dashes anywhere** (lint-gated by the `no-em-dash gate` pre-commit hook) - use simple dashes.
