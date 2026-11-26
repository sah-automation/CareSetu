# Brief - 583 The doctor account avatar and the doctor Profile page must share one doctor profile source

**Ticket:** #583 · **Parent:** none declared (sibling to #567-#570, all landed) · **Refreshed:** 2026-09-29
**Reading surface:** ~24K tokens against a 10K budget - **GATE OVERRIDDEN by the requester.** Re-cut was offered and declined; this lands as one ticket by explicit instruction. Do not re-litigate the split, and do not re-scope the ticket to fit the budget.
**Chain position:** after #567 (shell supplies role), #568 (byte-reader seam), #569 (doctor avatar), #570 (dropdown parity). All four are in the tree; their briefs are not repeated here.

## Scope

A doctor uploads, replaces, or removes a profile photo on the Profile page, and the account avatar in the console chrome (the account trigger in the top bar, and the header of the account dropdown it opens) keeps showing the person icon or the stale photo until a full page reload. The same defect, one field narrower, hits the practice name in the dropdown's identity header - the only place in the doctor console where the doctor is named.

**The shape of the change, in one sentence.** The doctor route group's layout gets a shared doctor-profile context, mirroring the patient `ProfileProvider` that already solves this for the patient side; the console shell's private read of the same projection moves into it; the chrome and the Profile page both read that one source, and the Profile page hands the source the backend's answer after every edit it makes.

Four moving parts, in dependency order:

1. **A new `DoctorProfileContext` provider** holding the projection, its load status, the failed-load trace id, a reload, and one adopt seam that takes the whole projection.
2. **Mounted once in the doctor route-group layout**, above `<AppShell role="doctor">` and every page beneath it.
3. **The read moves out of `AppShell`**: the module-private `useDoctorProfile` hook is deleted, the `doctorProfile` prop thread through `FullShellBody` -> `Topbar` -> `AccountMenu` is deleted, and the account menu reaches the source through an optional accessor.
4. **The Profile page stops keeping its own copy**: it reads the shared source, and its three edits (upload, remove, save) hand the source the backend's answer.

Plus the two test seams: a new cross-surface suite (the only seam that can see this bug) and a new provider unit suite.

**No backend change, no new endpoint, no schema change, no new copy, no new user-facing string.** The stored `photo_ref` remains an opaque role-prefixed object key in profile media, never a URL, with every read still streaming decrypted bytes through the backend.

## Why the seam takes the whole projection and not a photo ref

This is the decision most worth arguing for, and the ticket argues it at length. The short form:

- The practice-details **save can move the `practice_name`**, and the dropdown's identity header renders that name. A ref-only seam fixes the avatar and leaves the name stale - the same defect, one field narrower, and the one a reviewer is least likely to notice.
- The patient's ref-only seam exists for a hazard that does not apply to a doctor. The patient's profile write carries the photo ref in its body, so the patient's edit buffer must track it or a later save writes a stale ref back and silently detaches the stored photo. **The doctor's profile write declares no photo ref at all**: `DoctorProfileUpdate` has nine fields and none of them is `photo_ref`, and the facade writes only the fields the model declares. Copying the ref-only seam would guard an impossible failure while leaving a real one unfixed.
- The save endpoint already returns the whole projection, so widening the seam costs nothing at the call site.

## Key facts and prior art

- **The patient provider is the structural template, and it is close.** `ProfileContext.tsx` already has: the `createContext<... | null>(null)` object, a **throwing** `useProfile()` and a separate **`useOptionalProfile()`** accessor returning `null` when no provider is mounted, the **identity keying** (`<ProfileProviderInner key={user?.id ?? "anon"} identityId={user?.id}>` on a wrapper around the stateful inner component - a React `key`, so switching identity remounts the subtree atomically), the `cancelled` flag in the hydration effect keyed `[identityId]`, the `console.warn("[profile] hydration failed, using local draft:", err)` degrade, and the object-identity reference guard that reseeds a buffer only when the server answer is a _new object_.
- **The three things the patient provider does NOT have, which the doctor one must add:** no `traceId` anywhere, no `reload()` seam, and no `"loading" | "error"` status - only a boolean `hydrated`. The doctor Profile page owns all three locally today, and they move into the new source.
- **The patient provider's adopt seam is `syncPhotoRef(ref: string | null)`.** The doctor equivalent takes a whole `DoctorProfileView`. Do not copy the name - copy the shape and change the width.
- **The doctor route-group layout is a 13-line file that currently wraps `<AppShell role="doctor">` directly.** The patient layout is the same file with `<ProfileProvider>` added around the shell, and its header comment already explains the group-split rationale. That edit is the structural reason the patient's two surfaces cannot drift; it is the same reason the doctor's will not.
- **The read to move is `useDoctorProfile(role)` in `AppShell.tsx`** - a module-private hook, gated `if (role !== "doctor") return;`, one `useEffect` keyed `[role]`, a `cancelled` flag, a silent degrade, and `console.warn("[shell] doctor profile failed to load:", err)`. It is deliberately the same shape as its sibling `useOpenCasesCount(role)`, which degrades with `console.warn("[shell] open-cases count failed to load:", err)`. Take the shape with it.
- **The warn prefix changes.** The read now lives in the doctor profile module, so the prefix follows the module that owns the read, not the one that used to. The shell suite asserts the current exact string; that assertion moves to the new provider suite and is re-pointed. Do not keep `[shell]` for a read the shell no longer performs.
- **The account menu already uses the optional-accessor pattern for the patient context** (`const profile = useOptionalProfile();`) and already picks a ref and a reader in a single unconditional ternary. The doctor branch is the middle arm. Extending the selection keeps the rules-of-hooks safe - do not wrap the hook call in a branch.
- **The account menu's doctor trigger and its identity header already render off the same resolved `photoSrc` variable**, so the one-read-for-two-avatars invariant is already true there. This ticket does not change that. What changes is where `photoSrc`'s ref comes from.
- **The Profile page's own photo handling is already on the shared resolver** (`useProfilePhotoSource(profile?.photo_ref ?? null, fetchDoctorProfilePhoto)`), which is exactly why the page's avatar updated while the console's did not. The resolution layer was never at fault - it re-resolves correctly when a ref changes. The defect is two consumers holding private copies with no seam between them.
- **The Profile page has no reference guard on its edit buffer.** `setForm(formFromProfile(view))` runs unconditionally on every load answer and again after every save. That unconditional reseed is what the new source's object-identity guard has to replace, so a late-hydrating projection or an unrelated re-render cannot discard what the doctor is typing.
- **`useProfilePhotoSource` keys its cache on the ref**, so adopting an uploaded or cleared ref is a new key: it re-resolves and the previous object URL is revoked. A replaced or removed photo cannot leave stale bytes on screen. You consume this; do not change it.

## Read-list (in order)

Named symbols first, anchors second. **If a symbol no longer resolves, re-grep by name and refresh this brief rather than widening the list.**

1. **`ProfileContext.tsx` - the patient provider template, in full.** The context object, `useProfile()` (throws) and `useOptionalProfile()` (returns `null`), `ProfileProvider` and its `key={user?.id ?? "anon"}` identity wrapper, the state block, the hydration effect with its `cancelled` flag, the reference-guard reseed, the `console.warn` degrade, and `syncPhotoRef`. ~2.1K tokens. This is the single most important read in the brief; everything else is application.

2. **`ProfileContext.test.tsx` - the provider suite template.** The `vi.hoisted` state object, the `vi.mock("@/lib/profile/api", ...)` module-boundary mock, the `useAuth` mock, the `Probe` component, the `async function renderProvider(ui)` helper, and the five describe names verbatim: `"ProfileProvider hydration (#488 AC 2)"`, `"ProfileProvider persist on Finish (#488 AC 1/4)"`, `"ProfileProvider never-silent Finish (#496)"`, `"ProfileProvider identity isolation (#488 AC 5)"`, `"ProfileProvider.syncPhotoRef (#548)"`. ~3.6K.

3. **`AppShell.tsx` - the read that moves.** `useDoctorProfile` (the hook to delete), its call site in `FullShellBody`, the `<Topbar ... doctorProfile={doctorProfile} />` thread, `useOpenCasesCount` (the shape to mirror), and the light-density branch that never passed a `doctorProfile` at all. ~1.5K.

4. **`AppShell.test.tsx` - the four repairs.** The `vi.mock("@/lib/doctor/api", ...)` two-export factory; the `doctorProfileWith(photoRef)` fixture and the `PhotoRefControls` / `imageIn` helpers; `renderShell(role, pathname)` and `renderShellFor(role)`; the `"AppShell feeds the doctor account avatar (#569)"` describe in full, which is where the warn-prefix assertion, the `reads no doctor profile on the other shells` case, and the **source-shape pin** live. That pin reads `AppShell.tsx` off disk and asserts `/useDoctorProfile\([^)]*\): DoctorProfileView/` plus exactly one `fetchDoctorProfile(` occurrence - it asserts on the shell's own source text, so it **moves to the new module's suite and is re-pointed**, not deleted. ~3.0K.

5. **`AccountMenu.tsx` - where the thread dies.** The `AccountMenu({ shellRole, doctorProfile })` props, the `useOptionalProfile()` call, the single unconditional ref/reader ternary, `avatarClassName`, the doctor trigger branch, `IdentityHeader`, and the doctor identity-header call site. The dropdown body beyond the identity header is #570's and is not this ticket's. ~2.0K.

6. **`AccountMenu.test.tsx` - the projection injection and the mock that will throw.** The `vi.hoisted` `doctorApi` and the `vi.mock("@/lib/doctor/api", () => ({ fetchDoctorProfilePhoto: doctorApi.fetchDoctorProfilePhoto }))` factory that **replaces the whole doctor module with a single export** - this is the one that breaks at module init the moment the account menu transitively reaches any other doctor-api symbol, so it must grow in the same change. Also the `doctorProfileWith` fixture, the `renderAccountMenu` / `renderClosedTrigger` helpers, `PhotoRefControls` and `PhotoAbsenceProbe`, the `"AccountMenu doctor dropdown parity (#570)"` describe, and the non-doctor-staff regression cases that must stay untouched. ~5.0K. **This is the largest single item in the read-list**; if you are running long, this is the one to slice.

7. **`lib/doctor/api.ts` - the five functions, nothing else.** `DoctorProfileView` (16 fields, `photo_ref` and `practice_name` among them), `DoctorProfileUpdate` (nine fields, **no `photo_ref`** - this is what makes the stored ref structurally unreachable from the save endpoint), `DoctorProfilePhotoRef`, `fetchDoctorProfile`, `updateDoctorProfile`, `uploadDoctorProfilePhoto`, `fetchDoctorProfilePhoto`, `deleteDoctorProfilePhoto`, and the three shape guards. ~1.5K.

8. **`useProfilePhotoSource.ts` - the resolver you consume.** `ProfilePhotoReader`, the `(photoRef, read)` signature, the `{ src, absent }` return, the `NO_SOURCE` / `ABSENT` constants, the ref-keyed `CACHE` with its acquire/release refcount, and the `PHOTO_NOT_FOUND_CODES` set. You do not need the cache internals; #568's brief owns them and they are unchanged. ~1.0K.

9. **The doctor Profile page - the copy that stops.** The local `profile` state, `loadStatus`, `errorTraceId`, the `load` callback and its `useEffect`, `formFromProfile`, the unconditional `setForm(formFromProfile(view))` reseeds (the two places the reference guard replaces), and the three handlers: upload, remove, save. The fee editor, credentials card, bilingual parity blocks and `formFromProfile`'s callers below are **not** this ticket. ~2.5K.

10. **The doctor Profile page suite - the render helper and the retry assertion.** The `profile(overrides)` fixture factory, the `async function renderReady(view)` helper (which gains the provider), the `"surfaces the retryable error state when the profile read fails"` case whose `expect(getProfile).toHaveBeenCalledTimes(2)` is **re-pointed at the shared source's reload**, the photo describe, and the shared-reader assertion. ~3.0K.

11. **The route-group layouts and the `Topbar` prop block.** The doctor layout (13 lines - the file you add the provider to), the patient layout (the exact template, provider around shell), and `Topbar`'s `{ density, role, doctorProfile }` props and its single `<AccountMenu ... />` thread. ~0.5K.

12. **`docs/adr/0020-profile-media-storage-adapter.md` D1/D2 and the "profile media" entry in `CONTEXT.md`.** D1: `photo_ref` is an opaque object key, not a URL. D2: photos are never publicly addressable; every read streams decrypted bytes through the backend, so a leaked key discloses nothing. ~0.4K.

13. **`docs/standards/coding-standards.md` - the frontend and test rules only.** ~0.5K.

## Do NOT read

- **`docs/archive/`** - the PRD supersedes it.
- **The briefs for #567, #568, #569, #570.** Their read-lists are absorbed into items 3-8 above. Do not re-read `types.ts`, `staff-routing.ts`, or `AccountMenu.test.tsx` lines 1-200 hunting for a fixture that is gone by design.
- **The account menu's dropdown body** beyond the identity header: the branches, widths, row sizing, badges, strings, the Profile row, the role-switch rows, the divider, the sign-out accent. #570 owns those and this ticket must not move them.
- **`Sidebar.tsx`, `nav-config.ts`, `BottomTabs.tsx`, the mobile More sheet, `ProfilePhotoCard.tsx`.** The sidebar's composition is not this ticket; patient chrome is explicitly unchanged.
- **The `Avatar` primitive, the identity-line helper, and `roleBadgeFor`.** Unchanged, and they already accept a resolved `blob:` source and fall through to the person icon on `null`.
- **The dictionaries.** No new user-facing string is introduced, so no dictionary edit and no bilingual-parity work.
- **`docs/prd/*`, `docs/architecture/*`, `docs/roadmap/*`, and the other five standards.** No module, event, schema, API, or standard change here. The empty backend diff is the evidence for that claim.
- **Backend code, migrations, e2e specs.** No backend suite is warranted by this ticket.
- **The doctor landing page's own read of the same projection.** Explicitly out of scope, and named as such in the ticket: same staleness class, different symptom, different retry contract. Do not pull it in.

## Baseline verify (must pass before the first edit)

- **Measured green 2026-09-29 on the untouched tree at `1286679`:**
  - The four suites this ticket repairs: **4 files, 139 tests passed, 19s.**
  - The full frontend unit suite: **104 files, 1665 tests passed.** Two separate full runs.
  - `git status` clean apart from the untracked `docs/agents/briefs/` tree, which is untracked by design.

```bash
npm test -w @caresetu/frontend -- src/components/dashboard/AppShell.test.tsx src/components/dashboard/AccountMenu.test.tsx "src/app/(doctor)/doctor/profile/page.test.tsx" src/lib/profile/ProfileContext.test.tsx
npm run test:unit:frontend
npm run typecheck:frontend
npm run lint:frontend
```

- **Correct the ticket's baseline note before you trust it.** The ticket claims a pre-existing red in the patient record page's access-history empty state. **That is stale - the suite is green.** What actually exists is one **flake**: `"AccountMenu mobile placement (#525) > keeps the non-doctor staff phone-digit trigger fully visible at every width"` failed once under parallel workers and passed on re-run and in isolation. It is a resize / `matchMedia`-mechanics test. Record it as a known flake, not a blocker - but note it lives inside this change's blast radius, so if it fails during your work, check whether it is yours before you chase it.
- **A new `@/lib/doctor/api` import into the account menu's graph will throw at module init** in `AccountMenu.test.tsx` unless that suite's single-export mock is widened in the same change. An unmocked module is a real-request test, not a failure you can attribute to anything - do it in the same commit as the import.
- **jsdom `Error: Not implemented: navigation` stderr noise is expected**, not a failure.

## Done-verify (acceptance criteria to commands)

- `npm test -w @caresetu/frontend -- src/components/dashboard/AccountMenu.test.tsx` - green, including the non-doctor staff regressions, untouched.
- `npm test -w @caresetu/frontend -- src/components/dashboard/AppShell.test.tsx` - green, including the doctor Cases count pill and the four-layout role-pinning gate.
- `npm test -w @caresetu/frontend -- "src/app/(doctor)/doctor/profile/page.test.tsx"` - green, including the fee editor and bilingual parity describes.
- `npm test -w @caresetu/frontend -- src/lib/profile/useProfilePhotoSource.test.ts` - green, unchanged.
- The two new suites green: the cross-surface suite and the provider suite.
- `npm run test:unit:frontend`, `npm run typecheck:frontend`, `npm run lint:frontend`.
- `git diff --stat -- apps/backend` is **empty** - the evidence for the no-backend-change claim.
- `npm run typecheck` and `npm run lint` (full, incl. the `no-em-dash gate`) before the ticket is called done.

### Acceptance criteria as a checklist

**The cross-surface behaviour (the actual defect):**

- [ ] **Upload, replace, and remove each land in the chrome immediately, with no reload.** The account trigger and the dropdown identity header both show the new state, driven from a real edit on the real page.
- [ ] **The remove case is asserted, not assumed.** A photo the doctor has deleted never keeps rendering in the chrome. This is the sharpest of the three and the most user-visible.
- [ ] **The rename case is asserted.** A saved practice name appears in the dropdown's identity header without a reload.
- [ ] **The cross-surface suite is watched going red before the fix and green after.** It is the feedback loop, and it is the only seam that can observe this bug - every existing doctor-avatar test passes today with the bug fully present, because each injects the projection or mocks the read per consumer and therefore never sees two consumers disagree.

**The shared source:**

- [ ] **One shared doctor-profile source, mounted once in the doctor route-group layout**, above both the console chrome and every page beneath it.
- [ ] **It owns the read.** The shell issues **no** request of its own for doctor identity - `fetchDoctorProfile(` no longer appears in `AppShell.tsx`, and the prop thread through `Topbar` to `AccountMenu` is gone.
- [ ] **One read per console visit.** Navigating between console pages does not re-read. The test **counts** the calls; it does not infer sharing from a rendering that looked right.
- [ ] **It hydrates once per doctor and is identity-keyed** exactly as the patient provider is. Signing in as somebody else on the same browser remounts the projection atomically - no render may show the previous doctor's profile. This has no cross-surface expression, so it lives in the provider suite.
- [ ] **It keeps the whole projection** (the photo ref and the practice name together), because the account menu needs both and a second read to get the second field is the request this removes.
- [ ] **One adopt seam, whole-projection**, with three callers: an upload's returned ref, a removal's cleared ref, a save's returned view.
- [ ] **The read is scoped structurally, not by a runtime role check.** The source mounts only in the doctor layout, and that same layout is what pins the shell's role. The non-doctor staff shells have **no provider at all** and the account menu reaches it through an optional accessor that yields `null` where none is mounted. There is no code path in which a partner or operator shell can start a doctor profile read.
- [ ] **Degrade discipline preserved exactly**: one read per visit, a cancellation guard against a stale answer landing after unmount, and a silent degrade with a single console warning. Chrome identity is a bonus and never a blocker. The warning's prefix follows the module that now owns the read.
- [ ] **The account menu still issues no request of its own.** Both avatars read one resolution, and the ref-keyed cache means an adopted or cleared ref re-resolves and revokes the previous object URL.

**The Profile page:**

- [ ] **The page keeps no local copy of the projection**; it reads the shared source.
- [ ] **The edit buffer stays page-local and is seeded once per _distinct_ server answer, guarded by object identity**, so a late-hydrating projection or an unrelated re-render cannot discard what the doctor is typing, while a genuine reload still reseeds.
- [ ] **Upload, remove, and practice save keep working exactly as they do today.** The page's own photo preview, its bilingual parity, and its fee editor are all unregressed.
- [ ] **A failed upload leaves the previously stored photo intact and removable.**
- [ ] **A failed load is retryable, and a retry that succeeds renders the profile** without a reload. The retry-count assertion is re-pointed at the shared source's reload.
- [ ] **A stored photo ref with no media behind it offers Upload, not a Remove that cannot succeed**, and a stored photo that will not load still reads as a photo (the definitely-absent vs merely-unreadable distinction survives).

**The invariants that must not move:**

- [ ] **The stored ref is never rendered as an image source.** Assert a rendered image carrying a `blob:` source, and assert explicitly that the stored role-prefixed key is **not** what is rendered. A test that only checks "an image appeared" passes on a broken image.
- [ ] **Editing practice details can never detach the stored photo** - the save path declares no photo ref at all.
- [ ] **Non-doctor staff account menus are unchanged**: the phone-digit trigger, the dropdown verbatim, and no doctor profile read on their shell. Those assertions stay green and **untouched**, so the doctor treatment cannot leak onto staff who are not doctors.
- [ ] **The operator shell and the entire patient profile path are unchanged**, including the patient's draft, its gate, its save, and its shared photo seam.
- [ ] **No backend, schema, endpoint, migration, dictionary, or new-copy change.**

## Handoff notes

- **Write the cross-surface suite first and watch it fail.** Every existing doctor-avatar test passes today with this bug fully present, because each either injects the projection as a prop or mocks the read per consumer - each sees a world where the shell's copy and the page's copy are trivially in agreement. A defect that only exists as a _divergence between two consumers_ is invisible to any test that exercises one consumer at a time. If your new suite is green before the fix, the test is wrong.
- **Assert on what the doctor sees, never on which hooks were called.** Drive a real edit on the real page and assert on the rendered account trigger and identity header.
- **Count the "one read" claims; do not infer them.** Wherever this work claims one read, the test must count the calls.
- **Two seams, not three.** The cross-surface seam structurally cannot see provider-internal concerns - most importantly identity-switch isolation, which needs two identities on one browser and has no cross-surface expression. That is why the provider suite exists, and why accepting two is what keeps the two role contexts at parallel coverage instead of leaving the doctor one less covered than the patient.
- **Do not copy the patient's ref-only seam.** The hazard it guards (a later save writing a stale ref back) cannot happen for a doctor, because `DoctorProfileUpdate` has no `photo_ref` field and the facade writes only declared fields. Copying it guards an impossible failure while leaving the real one - the stale practice name - unfixed.
- **The four suite repairs are mechanical, not new behaviour.** Move the shell's source-shape pin to the new module (it asserts on the shell's own source text); move the read-count assertions with the read; re-point the exact-string warn assertion at the new prefix; turn the account menu's projection injection into seeded shared state and grow its doctor transport mock; give the page suite's render helper the provider and re-point its retry-count assertion. Do not delete any of them.
- **A third `fetchDoctorProfile` consumer exists and the ticket does not name it**: `StaffLoginForm.tsx`, inside `readPracticeIdentity()` - a login-time read for the greeting, not a console-shell read, so it does not violate "one read per console visit". Leave it alone. If a reviewer raises it, that is why: it is a different consumption with a different contract, and absorbing it would widen the blast radius for no user-visible gain.
- **The photo resolution layer was never at fault** and is verified as such: it re-resolves correctly when a ref changes, which is precisely why the Profile page's own avatar updated while the console's did not. **The fix is the seam, not the read.** If you find yourself touching the resolver, you are solving the wrong problem.
- **The doctor's landing page keeps its own read of the same projection** and stays out of scope. It is the same staleness class - a fee edited on the landing leaves the Profile page's copy stale and vice versa - but a different symptom against a different contract, and absorbing it would pull that landing's retry-count assertions into this change's blast radius. Named follow-up, deliberately not bundled.
- **Do not add a frontend role gate to the doctor route group.** A non-doctor partner who hand-types a doctor URL passes the cookie-presence proxy and receives the doctor shell, where the read is refused by the API. This is pre-existing and unchanged: the shared source mounts in the same layout that already pins the doctor role, so the exposure is exactly what it was. Worth its own ticket; not this one.
- **No em-dashes anywhere** in new prose or comments - the `no-em-dash gate` pre-commit hook fails the build on them. Use plain dashes.
- **The gate was overridden on this ticket.** `/to-brief` measured the reading surface at ~24K against a 10K budget and offered a five-slice re-cut; the requester declined and took it as one ticket. If the session runs out of context before the acceptance checklist is satisfied, that is the expected failure mode - write down where you stopped rather than half-applying the change.
