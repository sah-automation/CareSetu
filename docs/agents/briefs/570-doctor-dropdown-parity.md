# Brief - 570 The doctor account dropdown reaches patient account-menu parity

**Ticket:** #570 · **Parent:** #560 · **Refreshed:** 2026-09-27
**Reading surface:** ~5.1K tokens (budget 10K) - within budget
**Chain position:** 4 of 4, the last in the chain. **Read `567-shell-supplies-doctor-role.md`, `568-photo-source-byte-reader.md` and `569-doctor-avatar-photo.md` first.** None of their read-lists is repeated here.

## Scope

As a doctor, my account dropdown looks and behaves like the patient's - which is the approved reference: an identity header carrying my avatar, my name, my full E.164 phone number and the shared role badge; a Profile row; role-switch rows where I hold more than one role; a divider; and a danger-accented sign-out row. Rows are full-size tap targets, and the content is the wider width the patient menu uses.

**Only the doctor's branch changes.** The non-doctor staff branch and the operator branch keep their current content, and the non-doctor staff **trigger** keeps its current identifying treatment (that trigger is #569's concern and is already settled by the time this ticket runs - a doctor's trigger is now the shared avatar; a lab/chemist partner's is still the phone digits).

**This ticket changes no fetch, no endpoint, and no dictionary key.** The avatar source and the name both arrive from the shell (#569). This ticket is a structural change to one branch of one JSX tree.

## The reuse question, answered up front

The patient's identity header **cannot be reused verbatim**, and the difference is data, not markup.

The patient header (`AccountMenu.tsx:196-216`) reads its name from `saved` - i.e. `useOptionalProfile()` (`AccountMenu.tsx:91, 102`). **`ProfileProvider` is mounted only in `app/(patient)/layout.tsx:22`**, so in the doctor shell `saved` is `undefined` and never will be. The doctor's name is `practice_name` off the shell-held projection (#569), and the doctor's photo source is the resolved `photoSrc` from the same shell. So the header is reusable as a **parameterised inner component** - `{ name, photoSrc, phone, badge }` - rendered by both branches, with each branch supplying its own name and source. That is the right shape: one identity header, two suppliers. Copy-pasting the JSX is the failure mode this ticket is sized to avoid.

Everything else in the patient branch is already branch-agnostic and reusable as-is: `roleSwitchItems` (112-125), `roleBadge` (144-151, already a shared component-level constant), and `redLogoutItem` (130-141) - though `redLogoutItem` currently bakes in `patientMenuItemClass`, and `roleSwitchItems` gates its own class on `isPatient` (`:121`). Both gates become a third-way condition.

## Key facts and prior art

- **The width is a ternary on one line.** `AccountMenu.tsx:193`: `className={isPatient ? "w-60" : "w-52"}`. The doctor's menu is the narrow one. The criterion is the **wider** width - match the patient menu's value, do not approximate a third one.
- **The full-size row treatment is one module constant, and its comment is now false.** `AccountMenu.tsx:75-78`:

  > `// #527: every patient dropdown row is a >=44px tap target (spec #520 story 30). Shared so a future patient row cannot silently drop the contract; the staff branch deliberately never uses it (staff stays verbatim).` > `const patientMenuItemClass = "min-h-11";`

  The doctor branch adopting it means the constant is no longer patient-only and the "staff branch deliberately never uses it" half of the comment is wrong. **Rename the constant and rewrite the comment** - a constant named `patientMenuItemClass` applied to doctor rows is the kind of lie that survives three more tickets.

- **The sign-out accent already exists as a shared element.** `redLogoutItem` (130-141) is `cn(patientMenuItemClass, "text-danger focus:bg-danger-soft focus:text-danger")` and carries `data-testid="logout-button"`. The staff branch has its **own** `DropdownMenuItem` with the **same** `data-testid="logout-button"` (257-261) and **no** class. Two elements share one test id today, which is a latent trap once the tests start asserting on the doctor's branch - expect to disambiguate, and do so deliberately rather than by accident.
- **The divider is conditional in the staff branch and unconditional in the patient branch.** Patient: `<DropdownMenuSeparator />` at 236, always. Staff: `{otherRoles.length > 0 && <DropdownMenuSeparator />}` at 256. The criterion says the doctor keeps a divider - so it should be unconditional, matching the patient.
- **The patient branch carries a row the doctor must NOT inherit.** The `Complete your profile` CTA (224-234) is gated on `savedBasicsComplete(saved)` (`AccountMenu.tsx:85-87`), which is a **patient-profile** concept built on `basicsComplete(serverProfileToDraft(saved))`. A doctor has no `SavedPatientProfile`. Adopting the CTA verbatim would be a bug. This is the second reason verbatim reuse is wrong.
- **The doctor's Profile row already exists and already points at the right place.** `AccountMenu.tsx:245-254`: the `isDoctor &&` row with `data-testid="account-menu-doctor-profile"` and `<Link href="/doctor/profile">{strings.profile}</Link>`. It is currently unstyled (no `patientMenuItemClass`); parity means it gains the full-size treatment. Its href and its `strings.profile` string stay.
- **No new string is needed.** Every row the doctor adopts already has a dictionary key in both locales: `nav.profileSettings` (`Profile & Settings` / `प्रोफ़ाइल और सेटिंग`, `dictionaries.ts:1006` / `:2390`), `nav.profile` (`Profile` / `प्रोफ़ाइल`, `:1018` / `:2399`), `nav.logOut` (`Log out` / `लॉग आउट`, `:1011` / `:2392`), `accountMenu.switchRole(roleLabel)` (`:1039` / `:2411`). **The doctor Profile row reuses `nav.profile`; do not mint a "Doctor profile" string.**
- **The patient's own assertions are the reference contract.** `AccountMenu.test.tsx` describe `AccountMenu desktop identity dropdown (#526)`, lines 616-795: the identity header showing name + full E.164 + avatar initial (626-635), the masked-phone fallback (637-649), the live Profile entry and its href (651-671), the basics-gated CTA (673-714), role switching (716-745), the red Log out (747-756, asserts `logoutItem.className` contains `"text-danger"`), and the bilingual copy (758-784). The doctor branch's new assertions should be the same shapes, driven by the production-shaped doctor session.
- **`accountIdentity(name, user)` is the shared name → masked-phone → `Subject #id` resolver** (exported from `BottomTabs.tsx:173`, used at `AccountMenu.tsx:207`). It takes a name argument, so it works for a doctor as soon as it is given `practice_name`. Do not fork it.

## Chain ordering (this ticket is last, and depends on all three)

| inherited from | what it is                                                                                                                               |
| -------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| **#567**       | the threaded `role` prop that makes the doctor branch reachable at all. Without it there is no doctor branch to rebuild.                 |
| **#568**       | the doctor byte reader behind `useProfilePhotoSource`.                                                                                   |
| **#569**       | the shell-held `DoctorProfileView` (`photo_ref` + `practice_name`) threaded down, and the resolved `photoSrc` the header avatar renders. |

**#570 re-fetches nothing.** If you find yourself adding a read to the account menu, you have undone #569.

## Spec excerpt

No new spec text, and no doc must be re-read. The governing reference is the **patient menu's own implementation**, which is what "parity" means here - the criteria say _"matching the patient menu's treatment rather than approximating it."_ The historical intent is recorded in `AccountMenu.tsx:20-31` (the `#526` comment) and in `docs/agents/briefs/520-1-avatar-trigger.md` and `520-6-desktop-dropdown.md`; the latter two are cited for provenance, not re-read.

The one doc-level constraint that applies is the bilingual-parity gate: `apps/frontend/src/lib/i18n/dictionaries.test.ts`, describe `bilingual dictionary parity (REQ-006, #194)` - both locales must carry the same key set and shapes. Since this ticket adds **no** key, the gate is a verify, not a work item.

## Read-list (in order)

1. **`apps/frontend/src/components/dashboard/AccountMenu.tsx` lines 75-152** - the shared building blocks the doctor branch adopts. `identityLine` 68-73 (the staff-only label helper, which the doctor's new header makes redundant for the doctor case - check whether it still has a non-doctor caller). **`patientMenuItemClass` and its now-false comment 75-78.** `savedBasicsComplete` 80-87 (the patient-only gate the doctor must not inherit). `currentRole`/`isPatient`/`isDoctor` 99-101, `saved` 102, the `useProfilePhotoSource` call 109-111, `otherRoles` 112-115, `roleSwitchItems` 116-125, **`redLogoutItem` 130-141**, **`roleBadge` 144-151**. (~0.9K tokens)
2. **`apps/frontend/src/components/dashboard/AccountMenu.tsx` lines 153-268** - the whole return tree. The trigger 155-192 (already settled by #569 - read to know what `photoSrc` and the role prop are called, then leave it alone), the content width 193, the **patient branch 194-238** (the reference: identity header 196-216, Profile row 217-223, CTA 224-234, role switches 235, separator 236, red sign-out 237), the **non-patient branch 239-264** (identity label 241-244, doctor Profile row 245-254, role switches 255, conditional separator 256, neutral sign-out 257-261). (~1.2K)
3. **`apps/frontend/src/lib/i18n/dictionaries.ts` lines 1000-1040 and 2386-2412** - the `nav.*` and `accountMenu.*` keys both branches draw on, in both locales, with the model note at 1031-1035 explaining why `accountMenu` is separate from the `nav-config` surface (no functions allowed in `nav-config`). This is where you confirm **no key is missing** and **no key is being added**. (~0.6K)
4. **`apps/frontend/src/components/dashboard/AccountMenu.test.tsx` lines 616-795** - the patient identity-dropdown describe: the assertion shapes the doctor's new cases must mirror, and the `openPatientMenu()` helper at 617-624. Then **lines 528-594** in the same file - the doctor trigger case (now avatar-shaped after #569) plus the three staff cases that must stay byte-identical, especially `non-doctor staff keeps the phone-digit trigger and dropdown verbatim` (578-594). (~1.8K)
5. **`apps/frontend/src/lib/i18n/dictionaries.test.ts` lines 60-130** - the parity gate and its self-test shape. **Read-only, for verification.** Its `parityProblems` differ and the `parity detector self-test (#194 red/green proof)` describe exist so a future change to the gate inherits a working check; you should not need to touch either. (~0.6K)

## Do NOT read

- **`docs/archive/`** - the PRD supersedes it.
- **The earlier three briefs' read-lists.** Absorbed. In particular: do not re-read `types.ts`, `staff-routing.ts`, `lib/doctor/api.ts`, `useProfilePhotoSource.ts`, `AppShell.tsx`'s fetch, `Topbar.tsx`, the route-group layouts, or `AccountMenu.test.tsx:1-200`.
- **The console shell and its fetches.** `AppShell.tsx` in full. The doctor's `photo_ref` and `practice_name` are already threaded down (#569). You consume them; you do not touch, re-read, or re-order them.
- **The sidebar**, `nav-config.ts`, `BottomTabs.tsx` beyond knowing that `accountIdentity` and `maskedPhone` are exported from it (`BottomTabs.tsx:161-173`) and are the single source of the identity resolve.
- **`AccountMenu.tsx` lines 155-192 beyond the prop names** - the trigger is #569's deliverable and its own assertions are #569's.
- **The OTP step, `StaffLoginForm.tsx`, `ProviderRegisterWizard.tsx`.** Unrelated surfaces being rewritten by #562.
- **Backend code, migrations, e2e specs, `docs/prd/*`, `docs/architecture/*`, `docs/roadmap/*`, `docs/adr/*`, `docs/standards/*`.** No module, event, schema, API or standard change. The account menu is chrome.
- **`components/ui/dropdown-menu.tsx` internals** beyond knowing which primitives are re-exported (`AccountMenu.tsx:43-50`): `DropdownMenuLabel`, `DropdownMenuItem` (with and without `asChild`), `DropdownMenuSeparator`, `DropdownMenuContent`, `DropdownMenuTrigger asChild`. If a primitive turns out not to support what parity needs, that is a finding for the ticket, not a shadcn fork.
- **`components/ui/avatar.tsx`.** Not modified; it already accepts a `blob:` source and falls through on `null`.

## Baseline verify (must pass before the first edit)

```bash
npx vitest run src/components/dashboard/AccountMenu.test.tsx src/components/dashboard/AppShell.test.tsx src/lib/i18n/dictionaries.test.ts --root apps/frontend
```

- **Confirmed green 2026-09-27** for the account-menu and shell suites: part of the chain's four fast-loop suites, **4 files, 108 tests passed, 14.7s** (`AccountMenu`, `AppShell`, `useProfilePhotoSource`, `(doctor)/doctor/profile/page`). jsdom `Error: Not implemented: navigation` stderr noise is expected, not a failure.
- #567, #568 and #569 must all be closed first. This ticket's done-verify is "the doctor branch's new assertions and the unchanged non-doctor staff assertions" - there is nothing to assert against until the doctor branch is reachable and hydrated.
- `npm run test:unit:frontend` is **red on the untouched tree at brief time** - #562 and #563 are the blockers (measured breakdown in `docs/agents/briefs/564-design-token-gate-class-attributes.md`). Close them before the first edit.
- `npm run lint`, `npm run typecheck` - confirmed green 2026-09-27 per the #564 brief.

## Done-verify (acceptance criteria → commands)

- `npx vitest run src/components/dashboard/AccountMenu.test.tsx --root apps/frontend` - green, including the doctor branch's new assertions **and the unchanged non-doctor staff assertions**.
- `npx vitest run src/lib/i18n/dictionaries.test.ts --root apps/frontend` - green, bilingual parity intact.
- `npx vitest run src/components/dashboard/AppShell.test.tsx src/components/dashboard/Topbar.test.tsx --root apps/frontend` - green (both render the real account menu through the shell).
- `npm run test:unit:frontend` - green, with #562 and #563 closed.
- `npm run lint`, `npm run typecheck`.

### Acceptance criteria as a checklist

- [ ] **Under a production-shaped doctor session, the dropdown opens onto an identity header showing the avatar, the name, the full E.164 phone number, and the doctor role badge.** Assert on rendered output: an `img` with a `blob:` src (or the person-icon fallback when no photo), the `practice_name` text, `user.phone` in full (not the masked form, not the last two digits), and `data-testid="account-menu-role-badge"` reading `Doctor` from the existing shared `roleBadge`.
- [ ] **A Profile row is present and one click from the dropdown**, pointing at `/doctor/profile`, carrying `patientMenuItemClass`'s treatment, and labelled with the existing `nav.profile` string - not a new string.
- [ ] **Rows are full-size tap targets.** Assert the class on the doctor's Profile row, the doctor's role-switch rows and the doctor's sign-out row, mirroring the patient's `min-h-11` contract.
- [ ] **The content uses the wider width the patient menu uses** - the `w-60` value, adopted, not a third value. The staff branch keeps `w-52`.
- [ ] **The sign-out row is accented in the danger colour, like the patient's** - `text-danger focus:bg-danger-soft focus:text-danger` on the doctor's row, asserted the way `:751` asserts it for the patient. **Disambiguate the shared `data-testid="logout-button"` deliberately** rather than by accident.
- [ ] **The divider is present**, unconditionally, as in the patient branch.
- [ ] **The role-switch row is kept when the doctor holds more than one role, so cross-over still works.** A doctor session holding a second role must render the `accountMenu.switchRole(...)` row. A doctor session holding exactly one role must not.
- [ ] **The `Complete your profile` CTA is NOT adopted.** It is gated on `savedBasicsComplete(saved)`, a patient-profile concept a doctor does not have. Assert its absence for a doctor so it cannot creep in with a later "just reuse the patient branch" edit.
- [ ] **The non-doctor staff branch keeps its current rows and its current identifying trigger**, and its own assertions stay green **untouched** - `AccountMenu.test.tsx:571-576` and `:578-594` in particular. The doctor's icon treatment does not leak onto lab and chemist partners.
- [ ] **The operator's account menu is completely unchanged.** The operator shares the non-patient branch and differs only in the badge label; the branch's own content is not touched.
- [ ] **No new user-facing string is introduced.** The patient menu's existing strings are reused at bilingual parity. `dictionaries.ts` is **byte-identical** afterwards; the parity gate is green without a self-test being weakened.
- [ ] **The identity header is a shared, parameterised component, not a copy.** The patient's rendering must be behaviourally identical after the refactor - its suite green and unedited.

## Handoff notes

- **Verbatim reuse is wrong, and the reason is data, not markup.** The patient header reads `saved` from `useOptionalProfile()`, which is `undefined` outside the patient route group, and the patient's `Complete your profile` row is gated on a patient-profile predicate. Extract a parameterised identity header (`{ name, photoSrc, phone, badge }`) and let each branch supply its own two values. One header, two suppliers - that is what stops this branch drifting again.
- **Rename `patientMenuItemClass`.** It stops being patient-only the moment the doctor branch adopts it, and its comment's "the staff branch deliberately never uses it" becomes false. A constant whose name and comment both lie is a defect this ticket creates if it does not fix it.
- **Two `data-testid="logout-button"` elements exist today** (`:133` and `:259`). Once the doctor's branch is asserted on, that collision bites. Choose test ids deliberately and say which you chose and why.
- **Do not touch the trigger.** #569 settled it. This ticket starts at `<DropdownMenuContent>`.
- **Do not add a read.** The name is `practice_name` off the projection #569 already fetched. A new fetch in the account menu is the regression, not the fix.
- **`accountIdentity` already generalises.** It takes a name argument, so `accountIdentity(practiceName, user)` gives the doctor the same name → masked-phone → `Subject #id` chain the patient gets, for free.
- **This closes the chain.** If any part of the doctor's surface still reads as staff-grade after this ticket, it belongs to the parent (#560), not here - record it as a finding rather than widening the branch.
- **No em-dashes anywhere** (lint-gated by the `no-em-dash gate` pre-commit hook) - use simple dashes.
