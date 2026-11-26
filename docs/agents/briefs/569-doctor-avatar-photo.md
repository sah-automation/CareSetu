# Brief - 569 The doctor account avatar shows the doctor photo, read once, degrading to the icon

**Ticket:** #569 · **Parent:** #560 · **Refreshed:** 2026-09-27
**Reading surface:** ~5.8K tokens (budget 10K) - within budget
**Chain position:** 3 of 4. **Read `567-shell-supplies-doctor-role.md` and `568-photo-source-byte-reader.md` first.** Their read-lists are not repeated here.

## Scope

As a doctor signed into the console, the account avatar shows a person instead of the last two digits of my phone number, and shows my real profile photo once I have uploaded one - read once, and degrading to the person icon if the read fails, so a blip never looks broken.

**The shape of the change, in one sentence.** The console shell already fetches its open-case count once per shell and degrades silently on failure; the doctor's photo reference is fetched **alongside that same feed, in exactly the same style**, so the account menu adds **no request of its own**. The shell already knows it is the doctor shell, so it knows whose reference to fetch.

Three moving parts, in dependency order:

1. **`AppShell` gains a doctor-photo-ref fetch** mirroring `useOpenCasesCount`, and threads the ref down to the top bar.
2. **`Topbar` forwards it** to the account menu next to the role prop #567 added.
3. **`AccountMenu` passes the ref to `useProfilePhotoSource` with #568's doctor reader**, and the doctor trigger branch renders the resolved source.

The dropdown **header** avatar reads the same resolved source, so both surfaces share **one** read. (The dropdown header's _body_ - name, full phone, role badge, rows - is #570. This ticket changes only what the avatar inside it is fed.)

**No backend change.** `fetchDoctorProfile()` already returns `photo_ref`, and `fetchDoctorProfilePhoto()` already streams the bytes.

## Key facts and prior art

- **The existing shell fetch to copy is `useOpenCasesCount(role)` at `AppShell.tsx:119-142`.** Module-private, one `useEffect`, a `cancelled` flag, an early return gated on `role !== "doctor"` (line 123), a `.then` that sets state only when `!cancelled`, a `.catch` that degrades to nothing and logs `console.warn("[shell] open-cases count failed to load:", err)` (line 134), and a cleanup that sets `cancelled = true`. The count is deliberately never a "0" badge - a zero or a failure degrades to **no** value. **Copy this shape exactly**, including the console warning, so the two feeds degrade in the same way.
- **One read of the profile projection covers two fields.** `fetchDoctorProfile()` (`lib/doctor/api.ts:361-368`) returns `DoctorProfileView`, whose `photo_ref` is at `:255` and whose `practice_name` is at `:256`. **The shell fetch should take the projection, not just the ref** - the `practice_name` is the only human-readable name the doctor has anywhere in the frontend (`user` is `{ id, phone, roles }`, `lib/auth/AuthContext.tsx:35-39`; `PartnerMeView` carries no name either, `lib/partner/api.ts:42-48`). #570 needs that name, and re-reading the projection to get it would be the second request this ticket exists to avoid.
- **The doctor reader is the one #568 added** - `fetchDoctorProfilePhoto` (`lib/doctor/api.ts:414-416`) passed as #568's byte-reader parameter. Do not re-derive it here.
- **The patient trigger is the pattern to match.** `AccountMenu.tsx:176-181` renders `<Avatar photoRef={photoSrc} name={saved?.name} className={avatarClassName} />`, and the identity header at `:196-216` renders a second `Avatar` off **the same** `photoSrc` variable. The doctor's branch at `:182-187` is a bare `<Avatar className={avatarClassName} />` with no `photoRef` and no `name` - correct in isolation, unreachable before #567, and the thing this ticket hydrates.
- **The current doctor trigger assertion inverts under this ticket.** `AccountMenu.test.tsx:528-560` (`#538 shows the doctor a person-icon account avatar instead of phone digits`) asserts `fetchPatientPhoto` was **not** called, and its comment says the disc is "deliberately un-hydrated (that is later work)" and that "a stored photo must not cost a doctor an authed read for bytes no surface renders." **That comment names this ticket.** The test is rewritten to the new behaviour, not deleted. The `ME_RESPONSE_DOCTOR` fixture it uses is already gone by #567 - it will be reading the production-shaped session and the #567 prop threading.
- **The patient single-read assertion is the prior art**: `AccountMenu.test.tsx:430-447` renders the trigger, opens the menu, and asserts `fetchPatientPhoto` was called **exactly once** for two avatars on one ref ("Two avatars, one ref, one request"). The doctor's version asserts the doctor reader once. The degradation prior art is `:449-465` (`a photo ref that fails to resolve degrades to the initial, not a broken image`).
- **`avatarClassName` (`AccountMenu.tsx:97-98`) is shared by the patient and doctor discs** and stays as is - the doctor's disc is already the right size and colour.
- **The patient branch calls the hook unconditionally with a null ref for non-patients** (`:109-111`). After this ticket the doctor branch needs a ref, so the null-guard expression becomes a three-way selection. Keep the call unconditional - a conditional hook call is a rules-of-hooks break.

## Chain ordering (where the later ticket attaches)

| ticket   | what it inherits from this one                                                                                                                                                                                                |
| -------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **#570** | the threaded `role` prop (#567), the doctor byte reader (#568), and **the shell-held doctor profile projection + resolved `photoSrc` this ticket produces**. #570 changes the dropdown _body_; it must not re-fetch anything. |

**The dependency that forces the order:** #570's acceptance criteria require the doctor identity header to show the avatar, the name, the full phone and the badge. The avatar needs this ticket's resolved source; the name needs this ticket's `practice_name`; both must arrive from the shell, not from a leaf-owned fetch. **Take the whole projection now.**

## Spec excerpt

No new spec text. The governing decision is unchanged and is the one #568 already quotes:

- **ADR-0020 D1** - `photo_ref` is an opaque object key, not a URL.
- **ADR-0020 D2** - photos are never publicly addressable; every read streams decrypted bytes through the backend, so a leaked URL discloses nothing. `CONTEXT.md`'s "profile media" glossary entry restates it.

The enforceable sentences are this ticket's own acceptance criteria: _"The photo reference is fetched once per console shell alongside the existing open-case count feed, degrading silently in exactly the same way, and the account menu issues no request of its own."_ And: _"A failed read degrades to the person icon, not a broken image."_

**`docs/design/ui-blueprint.md` §2.6 (account menu) is unchanged** - the doctor's trigger moves from the masked-identifying treatment to the shared avatar, but no new string and no new primitive is introduced. The shared `Avatar` primitive (`components/ui/avatar.tsx`) is **not modified by this ticket**; it already accepts a `blob:` source and falls through to the person icon on `null`.

## Read-list (in order)

Everything #567 established about `AppShell`'s props, `Topbar`'s props, `AccountMenu`'s props, the `Role` type, and the route-group layouts is **already known - do not re-read them.** What is left is the fetch shape and the hydration call sites.

1. **`apps/frontend/src/components/dashboard/AppShell.tsx` lines 64-142 only** - `FullShellBody` 64-117 (where a doctor-profile fetch and its prop would live, and the `navItems` memo 78-87 that shows the existing "one fetch per full shell" intent) and **`useOpenCasesCount` 119-142 in full, comments included** - the function this ticket's sibling fetch is modelled on. (You already read 27-62 under #567; do not read it again.) (~0.9K tokens)
2. **`apps/frontend/src/components/dashboard/AppShell.test.tsx` lines 95-180 and 699-745** - the test-side model for a shell-level feed. The `vi.mock("@/lib/profile/api", ...)` whole-module mock at 95-99, the **`vi.mock("@/lib/care/api", () => ({ listOpenCases: vi.fn() }))` at 104-106 with its "the whole care module is mocked so shell tests stay unit scoped" comment**, and `const getOpenCases = vi.mocked(listOpenCases)` at 108 - that is the mocking discipline a doctor-profile mock must follow. The `AppShell doctor Cases count pill (PHASE-8.1 T8, #483)` describe 699-745: the `openCase(id)` fixture, `renderDoctor()` 715-722, and the pill assertions 724-742 that prove the feed reached both the sidebar and the phone tab bar from one fetch. (~1.0K)
3. **`apps/frontend/src/lib/doctor/api.ts` lines 253-291, 360-368, 413-416** - `DoctorProfileView` with `photo_ref` (255) and `practice_name` (256), `DoctorProfilePhotoRef` 289-291, `fetchDoctorProfile()` 361-368, and `fetchDoctorProfilePhoto(): Promise<Blob>` 414-416. This is the whole API surface this ticket needs. (~0.7K)
4. **`apps/frontend/src/lib/profile/useProfilePhotoSource.ts` lines 110-162 only** - the signature #568 left behind (the reader parameter and its default), the null-ref short-circuit 121-124, the capability guard 125-132, and the resolve handler 142-150 that decides `src` vs `ABSENT` vs `NO_SOURCE`. **You do not need to re-read the cache internals; #568's brief covers them and they are unchanged.** (~0.5K)
5. **`apps/frontend/src/components/dashboard/AccountMenu.tsx` lines 89-200** - the props #567 introduced, `currentRole`/`isPatient`/`isDoctor` 99-101, `saved` 102, the `useProfilePhotoSource` call site 109-111, `avatarClassName` 97-98, the `roleBadge` 144-151, and the three trigger branches 176-191. The dropdown body 194-268 is #570's - read only the `Avatar` element at 196-201. (~1.0K)
6. **`apps/frontend/src/components/dashboard/AccountMenu.test.tsx` lines 384-470** - the patient-avatar describe that is the prior art for the two assertions this ticket must reproduce for the doctor: `photo_ref resolves to a renderable source, never the ref itself` 417-428 (asserts a `blob:` src that does not contain the ref, plus `toHaveBeenCalledTimes(1)`), `a stored photo ref renders an image in the trigger and in the identity header` 430-447 (**the one-read-for-two-avatars assertion**), `a photo ref that fails to resolve degrades to the initial, not a broken image` 449-465. Also `imageIn(...)` the helper these use. (~1.1K)
7. **`apps/frontend/src/components/dashboard/AccountMenu.test.tsx` lines 528-560** - the doctor trigger test this ticket **inverts**. Its comment block (529-532) is the bug's fingerprint; its assertions (`not.toHaveTextContent("90")`, an `svg`, no `img`, `fetchPatientPhoto` not called) are the current pin. (~0.4K)

## Do NOT read

- **`docs/archive/`** - the PRD supersedes it.
- **`567-shell-supplies-doctor-role.md`'s read-list** - already absorbed. In particular: do not re-read `types.ts`, the four route-group layouts, `staff-routing.ts`, or `AccountMenu.test.tsx:1-200`. If you find yourself at `AccountMenu.test.tsx:74-80` looking for `ME_RESPONSE_DOCTOR`, that fixture is gone by design.
- **`lib/profile/useProfilePhotoSource.test.ts` and its cache internals.** #568's brief owns them; the behaviour you consume is `{ src, absent }` and nothing more.
- **The doctor profile page** (`app/(doctor)/doctor/profile/page.tsx`) and its suite. #568 put it on the shared seam; you consume the same seam, you do not touch that page.
- **`AccountMenu.tsx` lines 194-268's dropdown body** beyond the `Avatar` at 196-201. The identity header's name/phone/badge structure, the Profile row, the role-switch rows, the divider, the sign-out accent, the `w-60` vs `w-52` width, the `patientMenuItemClass` constant - all #570.
- **`Sidebar.tsx` and `nav-config.ts`** beyond knowing that `navItems` already carries the open-case count. The sidebar's composition is not this ticket.
- **The dictonaries** - no new user-facing string is added, so no dictionary edit and no bilingual-parity work.
- **Backend code, migrations, e2e specs, `docs/prd/*`, `docs/architecture/*`, `docs/roadmap/*`, `docs/standards/*`.** No module, event, schema, API or standard change here.
- `ProfilePhotoCard.tsx`, `BottomTabs.tsx`, and the mobile More sheet. Patient chrome is explicitly unchanged by this ticket.

## Baseline verify (must pass before the first edit)

```bash
npx vitest run src/components/dashboard/AccountMenu.test.tsx src/components/dashboard/AppShell.test.tsx --root apps/frontend
```

- **Confirmed green 2026-09-27** as part of the chain's four fast-loop suites: **4 files, 108 tests passed, 14.7s** (`AccountMenu`, `AppShell`, `useProfilePhotoSource`, `(doctor)/doctor/profile/page`). jsdom `Error: Not implemented: navigation` stderr noise is expected, not a failure.
- The doctor-profile projection read is a **new** module dependency of `AppShell.tsx`, so `AppShell.test.tsx` will need `@/lib/doctor/api` mocked at the module boundary in the same style as `@/lib/care/api` at `:104-106`. Do that in the same change that introduces the import, not as a follow-up - an unmocked module is a real-request test, not a failure you can attribute to anything.
- #567 and #568 must be closed first: this ticket's whole premise is a threaded role prop and a reader parameter. If either is open, stop.
- `npm run test:unit:frontend` is **red on the untouched tree at brief time** - #562 and #563 are the blockers (measured breakdown in `docs/agents/briefs/564-design-token-gate-class-attributes.md`). Close them before the first edit.
- `npm run lint`, `npm run typecheck` - confirmed green 2026-09-27 per the #564 brief.

## Done-verify (acceptance criteria → commands)

- `npx vitest run src/components/dashboard/AccountMenu.test.tsx --root apps/frontend` - green, including the doctor's trigger assertions.
- `npx vitest run src/components/dashboard/AppShell.test.tsx --root apps/frontend` - green, including the doctor Cases count pill and the four-layout role-pinning gate.
- `npx vitest run src/lib/profile/useProfilePhotoSource.test.ts --root apps/frontend` - green, unchanged.
- `npm run test:unit:frontend` - green, with #562 and #563 closed.
- `npm run lint`, `npm run typecheck`.

### Acceptance criteria as a checklist

- [ ] **The doctor's trigger shows neither the last two digits of the phone number nor a bare file name**, under a production-shaped doctor session (partner role, doctor partner type, via the #567 prop). The `(user?.phone || "?").slice(-2)` else-branch is never reached by a doctor.
- [ ] **The doctor's photo reference is fetched once per console shell**, in the same module-private-hook style as `useOpenCasesCount`, **gated on the doctor role** and degrading silently with the same `console.warn` discipline. It is **not** fetched on the light (patient) density, and **not** for a partner or operator shell.
- [ ] **The account menu issues no request of its own.** Assert it: the doctor's photo-ref read count is driven entirely by the shell, and the account menu's only read is through `useProfilePhotoSource` with the doctor reader.
- [ ] **Once a photo is uploaded and its reference is present, the trigger renders the photo as an object URL** - asserted on a rendered `img` whose `src` starts with `blob:`, and explicitly **not** the stored `doctor/...` media key.
- [ ] **The read is shared between the trigger and the dropdown header: exactly one doctor-reader call for two avatars on one ref**, mirroring `AccountMenu.test.tsx:430-447`. Count the calls; do not infer.
- [ ] **A failed read degrades to the person icon, not a broken image** - no `img` left pointing at nothing, no failure notice on a chrome avatar, mirroring `:449-465`.
- [ ] **A definitely-absent photo behaves the same way but is still distinguished internally.** The test must show both answers: a `PROFILE_PHOTO_NOT_FOUND` and a `NETWORK_ERROR` both render the icon, and only the former reports absence (#568's `absent`).
- [ ] **The doctor's name is also taken from the shell-held projection** (`practice_name`), so #570 needs no second read. Take the whole `DoctorProfileView`, not a ref-only endpoint.
- [ ] **The lab/chemist partner and operator triggers keep their current masked-identifying treatment.** The `non-doctor staff keeps the phone-digit trigger and dropdown verbatim` regression (`AccountMenu.test.tsx:578-594`) and `#543 keeps the Profile row off non-doctor staff menus` (`:571-576`) stay **untouched and green**, and the doctor's icon treatment does not leak onto them.
- [ ] **The existing patient avatar surfaces are unchanged and their suites stay green** - `AccountMenu.test.tsx:384-470`, `ProfilePhotoCard.test.tsx`, `AppShell.test.tsx`'s mobile account-card cases.
- [ ] **No new endpoint, no backend change, no dictionary key.** `fetchDoctorProfile` and `fetchDoctorProfilePhoto` already exist and are the only reads used.

## Handoff notes

- **One fetch, two fields, one read.** The single most important decision here is to take the **whole `DoctorProfileView`** in the shell rather than a ref-only read. `photo_ref` hydrates the avatar; `practice_name` feeds #570's identity header. Two reads would reintroduce exactly the problem this ticket removes.
- **Mirror `useOpenCasesCount`, do not improve it.** Module-private hook in `AppShell.tsx`, same early return, same `cancelled` flag, same silent degrade, same `console.warn("[shell] ... failed to load:", err)`. A differently-shaped degradation is a drift bug waiting to happen, and the brief's criterion is "in exactly the same way".
- **The hook call must stay unconditional.** `AccountMenu.tsx:109-111` selects a ref with a ternary; extend the selection, do not wrap the call in a branch.
- **#570 will want the resolved `photoSrc` and the name, not a second fetch.** Keep whatever you thread down the shell-to-menu path named and stable; the dropdown header avatar and its identity line read from the same two values.
- **The test at `:528-560` is meant to flip.** Its `fetchPatientPhoto).not.toHaveBeenCalled()` assertion encoded the deliberate omission this ticket removes. Rewrite it to the new behaviour and keep the surrounding shape (`expect(trigger.querySelector("svg")).not.toBeNull()` for the no-photo case, `imageIn(trigger)` for the photo case). Do not delete the case - the person-icon path must stay pinned for a doctor with no photo.
- **No em-dashes anywhere** (lint-gated by the `no-em-dash gate` pre-commit hook) - use simple dashes.
