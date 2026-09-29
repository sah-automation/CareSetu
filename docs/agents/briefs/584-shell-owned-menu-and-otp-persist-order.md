# Brief - 584 Doctor console account popup opens on the patient menu after partner OTP login

**Ticket:** #584 · **Parent:** #560 · **Refreshed:** 2026-09-29
**Reading surface:** ~8.6K tokens (budget 10K) - within budget
**Chain position:** follows #567, #569, #570, #583 (all landed). #567 already threaded `shellRole`; this ticket **completes** it by making the branch selection actually read the shell for every surface, not only doctor-ness.

## Scope

Two client-side defects stack to produce one symptom: after a doctor logs in by partner phone-OTP, the doctor console's top-right account avatar popup opens onto the **patient** account menu (Profile & Settings, "Complete your profile", patient logout). A hard refresh fixes it. It is deterministic on a browser where the same phone also holds a patient session (dual-registered account).

1. **The partner OTP flow publishes the minted partner session into flow state before persisting it to storage** (the localStorage dual-JWT plus the `caresetu_authed=1` presence-hint cookie, per the dual-JWT storage decision). The in-flow identity-resume seam reads the _persisted_ session at that same moment, so it applies the previously stored patient session (or nothing) and the auth context stays on the patient identity (or unresolved). The persistence happens only later, after a network round trip to the identity read. The doctor console is the only partner landing that navigates with the client-side router rather than a full page reload, so the stale or unresolved identity rides straight into the shell.

2. **The account menu treats an unknown or unresolved role as patient.** The patient branch is selected _before_ the doctor branch, so a doctor shell whose session role is unresolved - or still the stale patient role - renders the patient menu.

The hard refresh heals it because a fresh mount replays identity validation against the now-correct stored session, and a partner session's identity answer is always the single partner role (the backend derives roles from the token scope claim, one role per session).

**Solution.** Persist the partner session at the moment it is minted, before the flow publishes it to state - the same ordering the patient flow already follows - so the in-flow resume seam reads the freshly minted partner session. And make the account menu's surface choice a property of the shell, not of the session: each route group (patient, doctor, partner, operator) always renders its own account menu, with the session role only driving role switching and badges. This also removes the wrong-menu flash that renders while identity resolves on a cold load.

**Modules touched:** the partner OTP flow state machine and the account menu component. No API, schema, migration, or backend change; no change to the role vocabulary or to the identity read contract. The identity-resume seam itself is **unchanged** - this fix only guarantees it reads the freshly minted session. A resolution failure still leaves the console usable and never force-logs-out.

### Acceptance criteria (from the ticket's 15 user stories)

- [ ] **A1 (persistence ordering).** The partner OTP flow writes the minted session through the shared session-persistence module (localStorage tokens + presence-hint cookie) **before** it updates the flow state that triggers identity resume and navigation. This mirrors the patient flow's established ordering. No new seam, no new storage format, no session-transport change; the split-origin session invariants stay untouched.
- [ ] **A2 (doctor menu surface).** The account avatar popup in the doctor shell renders the **doctor** branch: identity header (practice identity, full phone number, `Doctor` role badge), the Profile entry linking to the doctor profile page, and the danger-accented sign-out row.
- [ ] **A3 (stale patient session in storage).** A doctor shell whose storage holds a stale patient session still renders the doctor branch, not the patient branch.
- [ ] **A4 (unresolved identity).** A doctor shell with no stored session (identity unresolved, cold load) renders the doctor branch and **never flashes the patient menu** first.
- [ ] **A5 (avatar).** A doctor with no photo sees the person icon, not phone digits. A doctor with a photo sees that photo in both the trigger and the dropdown header.
- [ ] **A6 (no patient rows in a doctor menu).** The patient-only `Profile & Settings` and `Complete your profile` rows never appear in the doctor shell.
- [ ] **A7 (non-doctor staff).** A lab or chemist partner shell keeps its staff treatment (identifying phone trigger, narrow rows, neutral sign-out row) even when identity is unresolved or a patient session is stored.
- [ ] **A8 (operator).** The operator account menu is unchanged.
- [ ] **A9 (patient).** The patient account menu keeps its current content and avatar treatment.
- [ ] **A10 (regression guard, rendered surface).** A test renders the account menu with the shell role threaded down under (a) an unresolved identity and (b) a stale patient session in storage, asserting the doctor branch rows render and the patient rows do not. The same assertion shape covers partner and operator shells rendering the staff branch, and pins the patient menu unchanged in the patient shell.
- [ ] **A11 (regression guard, module boundary).** A test drives the partner flow hook through request-code, enter-code, verify, with the partner API mocked at the module boundary and the **real** session-persistence module, and asserts the session is persisted (localStorage plus presence-hint cookie) **before** the flow publishes the minted session.
- [ ] **A12 (red before green).** Both regression tests are written before the fix and observed **red**, then green after.
- [ ] **A13 (production-shaped sessions).** A good test asserts what the user sees (which menu rows and avatar treatment render, and what was persisted) rather than internal state variables, and builds a session exactly as the backend builds it - a `partner` role for a doctor, **never** a fabricated `doctor` role.
- [ ] **A14 (no scope creep).** No backend change (identity read, role derivation, session minting, scope semantics); no schema or migration; no end-to-end browser coverage - the verification stays in the unit suites. The account menu's existing styling, spacing, widths, bilingual copy, and photo-resolution work are covered by other tickets and unchanged here. The sidebar, the partner OTP step visual redesign, and every other issue in the console chrome batch are untouched. Cross-role switching stays a frontend-local affordance.

**No em-dashes anywhere** in the delivered code or copy (gated by the `no-em-dash gate` pre-commit hook) - use simple dashes.

## Read-list (in order)

Line numbers are **current-tree hints**, not contracts - grep the interface name if one has moved.

1. **`AccountMenu` (`components/dashboard/AccountMenu.tsx`)** - the component being changed, ~410 lines total, read two slices:

   - the **flag-derivation block** (props, `currentRole` / `isPatient` / `isDoctor`, the single photo-ref-and-reader selection, `otherRoles`, `isRealAccountMenu`) - roughly lines 182-243. This is where defect 2 lives: `isPatient` is derived from `resolveRole(selectedRole)`, and the photo-reader ternary is **patient-first**.
   - the **JSX** (trigger `className` ternary, trigger content ternary, dropdown content ternary) - roughly lines 283-409. Four separate `isPatient ? ... :` chains, all patient-first, each of which must flip to the shell. Note the doctor branch (content, `account-menu-doctor-profile`, `account-menu-doctor-logout`) and the non-doctor staff branch (`logout-button`, neutral) are already written and correct - **the branches are not the defect, the selector is**. (~2.5K tokens)

2. **`AccountMenu.test.tsx` - fixtures and render helpers** (`components/dashboard/AccountMenu.test.tsx`, ~1430 lines) - read the fixture block and the helpers, roughly lines 95-135 and 162-232:

   - `VALID_SESSION`, `ME_RESPONSE_SINGLE_ROLE`, **`ME_RESPONSE_PARTNER` (the production-shaped doctor session - `roles: ["partner"]`)**, `ME_RESPONSE_NO_PHONE`, `ME_RESPONSE_OPERATOR`.
   - `setStoredSession(session)`, **`renderAccountMenu(shellRole, doctorProjection?)`** (the `shellRole` parameter is required on purpose), `mockMeResponse(payload)`, `renderClosedTrigger(...)`, `openViaKeyboard()`.
   - **There is no unresolved-identity path in this suite today** - every existing test seeds a session. Case (a) of A10 is the new gap. (~1.8K)

3. **`usePartnerLoginFlow` (`components/auth/staff/partnerLoginState.ts`)** - the partner OTP state machine, ~417 lines, read the state shape (the `session` field and its type) and the `submitOtp` verify branch (where `issuePartnerSession(...).then(...)` sets state). Roughly lines 40-90 and 237-280. **Defect 1 lives here**: the `.then` publishes `session` with no persistence anywhere in the file. (~1.2K)

4. **`useOtpFlow` in `components/auth/otp/otpState.ts`** - the **ordering to mirror**, read only the verified branch of `submitOtp` and the `toStoredSession` helper. Roughly lines 270-300 and 445-457. The three-line shape is: derive the stored session, `saveSession(...)`, **then** `setState(... session: stored)`. (~0.5K)

5. **`components/auth/session.ts`, whole (~92 lines)** - the shared persistence module: `HINT_COOKIE`, `StoredSession`, **`saveSession(session: SessionResult, phone: string): void`** (writes the three localStorage keys, then the hint cookie), `readSession()`, `clearSession()`, `readSelectedRole` / `saveSelectedRole` / `clearSelectedRole`. (~1.1K)

6. **`StaffLoginForm` (`components/auth/staff/StaffLoginForm.tsx`)** - ~898 lines, read three slices only: **`completeStaffLogin(session)`** (which also calls `saveSession`, and is the double-write decision in the handoff notes), the **in-flow resume effect** keyed on `partner.state.session`, and **`landPartnerAfterLogin(session)`**. Roughly lines 77-86, 240-275, 385-400. (~1.0K)

7. **`components/dashboard/types.ts`, whole (42 lines)** - `Role` union (four members), `ROLE_LABELS`, `roleLabel`, `isAppRole`, **`resolveRole(value): Role` - which falls back to `"patient"` on null or unknown (defect 2's mechanism)**, `ROLE_HOME`. **Do not edit this file's union** - the role vocabulary is unchanged by this ticket. (~0.45K)

## Do NOT read

- **`docs/archive/`** - the PRD supersedes it.
- **`docs/prd/project-prd.md`, `docs/architecture/*`, `docs/roadmap/*`, `docs/adr/*`.** This ticket touches no module, no event, no API contract, no schema, and no session transport. `CONTEXT.md`'s hard gate does **not** fire: no cookies are authored here, no CORS, no middleware, no `credentials`, no deploy env - the flow only changes the _ordering_ of an existing `saveSession` call, and the storage format, the hint cookie, and the edge guard are all untouched.
- **`docs/design/ui-blueprint.md`** - no design change. The account menu's styling, spacing, widths, bilingual copy, and photo resolution are explicitly out of scope and covered by other tickets.
- **The photo seam** - `useProfilePhotoSource`, its suite, `ProfilePhotoCard`, `fetchPatientPhoto` / `fetchDoctorProfilePhoto`. #556/#557/#569 territory. You only need the account menu's own single call site.
- **`DoctorProfileContext` / `DoctorProfileProvider` and its suite**, and `app/(doctor)/doctor/profile/profile.shared-source.test.tsx`. #583 landed; the menu's `useOptionalDoctorProfile()` optional accessor is already correct and you do not change it.
- **`Sidebar.tsx`, `BottomTabs.tsx`, `nav-config.ts`, `nav-config`'s role pin.** The shell already passes `role` correctly to all of them. The mobile More sheet (`AccountCard` / `LogoutRow`) is a **separate surface** that does not use `AccountMenu` - do not touch it, and do not let the fix leak onto it.
- **`AppShell.tsx` and `Topbar.tsx` beyond confirming the `shellRole` prop is threaded.** #567 landed that threading; it is not this ticket's work. Do not re-thread or rename it.
- **The four route-group layouts beyond confirming each pins its role** - the existing gate in `AppShell.test.tsx` already pins them.
- **`PartnerRegisterWizard.tsx` / `providerRegisterState` / `ProviderRegisterWizard.test.tsx`** except the single ordering-assertion test named in the handoff notes. The registration sibling already persists correctly; it is prior art, not a site to edit.
- **`AuthContext.tsx` beyond the `resumeSession` contract**, which the handoff notes state. The resume seam is **unchanged** by this ticket - do not edit it.
- **Backend code, migrations, e2e specs.** Nothing here touches a schema, a migration, an API contract, or a session-transport invariant; the ticket puts browser coverage explicitly out of scope. Grep if you need to confirm, do not read.
- **`docs/agents/briefs/560-*.md` and the other 15 briefs in the #560 batch.** Read _this_ brief plus `567-shell-supplies-doctor-role.md` if you want the doctor-is-a-partner-type rationale in the implementer's own words. The rest of the batch is adjacent, not context.

## Key facts (already established - do not re-derive)

- **There is no `doctor` session role.** The identity layer grants exactly `patient | partner | operator`; a doctor is a **partner whose partner type is doctor**. So `/me`'s `roles` array can never contain `"doctor"`, and no session-derived check can authoritatively identify a doctor. `Role` in `types.ts` is a **shell** vocabulary, not a session one.
- **`resolveRole` falls back to `"patient"`**, which is why an unresolved identity silently lands on the patient branch. That fallback is correct for _role-switch_ labelling and must stay; what changes is that it no longer selects the **menu surface**.
- **The shell role is already threaded**: route-group layout pins `role="<role>"` on `AppShell` -> `Topbar` -> `AccountMenu shellRole`. Nothing new to plumb.
- **`resumeSession` reads persisted storage** (`readSession()`) as its first statement, and the partner flow's resume effect is keyed on `partner.state.session`. Because React runs effects in declaration order and both effects are keyed on the same value, the resume currently wins the race against persistence. A fresh mount heals it because a mount replays validation against the now-correct stored session.
- **The doctor branch and the non-doctor staff branch are already written and already correct.** The lines to change are the four `isPatient ? ... :` selectors, not the branch bodies.
- **The trigger already exposes an unresolved-identity hook**: the account-menu button carries `data-session-resolved={user ? "true" : "false"}`. Use it to assert case (a) of A10 rather than reaching for internals.

## Baseline verify (must pass before the first edit)

- **`npm run test:unit:frontend`** - **confirmed green 2026-09-29: 106 files, 1686 tests passed, 174s.** (The #567 brief recorded a red baseline here; the #562/#563 repair has since landed. Green is the current starting truth - a failure you meet later is yours.)
- **`npx vitest run src/components/dashboard/AccountMenu.test.tsx src/components/dashboard/AppShell.test.tsx src/components/auth/otp/PatientAuthWizard.test.tsx --root apps/frontend`** - **confirmed green 2026-09-29: 3 files, 132 tests passed, 17s.** This is your fast loop. Expect jsdom `Error: Not implemented: navigation` stderr noise and a Tailwind `content` warning - neither is a failure.
- **`npm run lint`** - confirmed green 2026-09-29 (all pre-commit hooks, including the `no-em-dash gate`).
- **`npm run typecheck`** - confirmed green 2026-09-29 (mypy strict, 251 backend files; `tsc --noEmit`).

## Done-verify (acceptance criteria -> commands)

- `npx vitest run src/components/dashboard/AccountMenu.test.tsx --root apps/frontend` - green, including the new unresolved-identity and stale-patient-session doctor cases (A3, A4, A10) and the unchanged `ME_RESPONSE_PARTNER` / `ME_RESPONSE_OPERATOR` negatives.
- `npx vitest run src/components/dashboard/AppShell.test.tsx --root apps/frontend` - green, including the gate that pins each route-group layout's role onto `AppShell`.
- `npx vitest run src/components/auth/staff --root apps/frontend` - green, including the new partner-flow ordering suite (A1, A11) and the **existing** `StaffLoginForm` suite, which must not need editing to stay green (see handoff note 2).
- `npx vitest run src/components/dashboard/Topbar.test.tsx --root apps/frontend` - green (it opens the real account menu through the shell).
- `npm run test:unit:frontend` - green at 106 files / 1686 tests or better.
- `npm run lint`, `npm run typecheck` - green.
- **Grep before you close:** no fabricated `roles: ["doctor"]` introduced anywhere in `apps/frontend/src` or `tests/` (A13). The four pre-existing sites in `lib/auth/staff-routing.test.ts` are out of scope for this ticket - record them as findings on the ticket rather than silently rewriting them.
- **Grep before you close:** `saveSession` is not called twice for one partner login, and `types.ts` is byte-identical afterwards (A1, A14).

## Handoff notes

- **The bug is a selector, not a branch.** Every `isPatient ? ... :` in `AccountMenu` must read the shell instead of `resolveRole(selectedRole)`. If you find yourself editing the doctor or staff branch _bodies_, you are re-doing #570, which already landed.
- **The photo-ref-and-reader ternary is a fourth site**, not a fifth thing to forget. It is currently `isPatient ? [patient ref, patient reader] : isDoctor ? [doctor ref, doctor reader] : [null, patient reader]`. It must follow the shell, and its one-branch invariant (#569: the ref and the byte reader must come from the same account, or a dual-role session in the doctor shell pairs a patient's ref with the doctor's byte endpoint) must survive the flip. Non-doctor staff still resolve nothing.
- **The one decision the ticket does not make for you: which phone is authoritative, and whether `completeStaffLogin` still persists.** `completeStaffLogin` in `StaffLoginForm` currently calls `saveSession(session, me.phone)` using the phone from the identity read - a network round trip _after_ the mint. If the flow state now persists `session` with `s.phone` (the number the OTP was entered for), that second `saveSession` becomes redundant. The ticket requires persistence _before_ publish; it does not tell you to delete the later one. **State which one you kept and why in the PR** - a silent double-write is the failure mode here, not a silent removal.
- **`StaffLoginForm.test.tsx` mocks `@/lib/auth/session` as a whole module** with only `saveSession` exported, so `readSession` and `clearSession` are undefined in that tree. If your change makes any newly-reached path call those, that existing suite breaks in a confusing way. Keeping the new partner-flow test in a **new** `partnerLoginState.test.ts` (which does not exist today) rather than growing `StaffLoginForm.test.tsx` avoids this entirely - the sibling `staffLoginState.test.ts` is the naming precedent for a flow-state suite.
- **Assert ordering, not just outcome.** The patient wizard suite reads `localStorage.getItem("caresetu.session")` but does **not** pin persist-before-publish; the only ordering-by-call-order assertions in the repo live in `ProviderRegisterWizard.test.tsx`, which uses vitest's `invocationCallOrder` comparisons (and mocks the session module, so it is order-only). For A11 you need the real persistence module **and** an order assertion - mocking `saveSession` and checking it was called proves it was called, not that it was called first.
- **`ME_RESPONSE_PARTNER` is the production-shaped doctor session** and already carries the `roles: ["partner"]` payload with the `#567` comment explaining why. Reuse it; do not author a new doctor fixture. A doctor differs from a lab only by partner type, which this menu never reads - so the _same_ `/me` payload plus a different `shellRole` is what distinguishes the doctor shell from the staff shell, and that is exactly the assertion A10 asks for.
- **No new read, no new endpoint, no new user-facing string** in the menu work. The branch bodies - including the doctor badge that already reads `shellRole` and the patient/staff badges that already read the session role - are correct as they stand and must keep exactly that split: session role for role-switch rows, the staff badge, and the patient badge; shell role for the surface and the doctor badge.
- **This brief's ancestor is `567-shell-supplies-doctor-role.md`.** #567 threaded `shellRole` but only made **doctor-ness** read it; the patient-vs-staff half of the same decision was left on the session role, which is precisely the residue this ticket removes. Keep the `shellRole` prop name stable - sibling tickets in the batch read it.
- **This ticket is a fix, not a redesign.** A14 is a real constraint, not boilerplate: the styling, spacing, widths, bilingual copy, and photo resolution are other tickets' work and must be byte-identical afterwards.
