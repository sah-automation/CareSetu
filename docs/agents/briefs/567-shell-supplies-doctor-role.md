# Brief - 567 The doctor console shell knows the role, so the shell supplies it

**Ticket:** #567 · **Parent:** #560 · **Refreshed:** 2026-09-27
**Reading surface:** ~9.3K tokens (budget 10K) - within budget
**Chain position:** 1 of 4. This brief is the chain's foundation. #568, #569 and #570 all read it first and must not re-list anything established here.

## Scope

As a doctor signed into the console, every doctor-only affordance is reachable, because doctor-ness is read from the shell the component sits inside rather than re-derived from the session's roles.

**The root cause, and the point of the whole chain.** The identity layer grants exactly three roles: `patient`, `partner`, `operator`. A doctor is a **partner whose partner type is doctor**. Any component that asks the session "are you a doctor?" gets `false` in production, so everything gated on it is unreachable. The console shell is pinned to the doctor role by its route group, so **the shell already holds the right answer**. The fix threads it down: `AppShell` → `Topbar` → `AccountMenu`, with the shell's role authoritative for doctor-ness and the session role still governing the patient and non-doctor staff branches.

**This ticket changes no backend, no session transport, and no role vocabulary.** "A doctor is a partner" is the design, not a defect.

### The four facts that shape the edit

1. **`AccountMenu` takes no props today.** `export function AccountMenu() {` at `AccountMenu.tsx:89` - zero parameters. `Topbar.tsx:71` renders `<AccountMenu />` bare, even though `Topbar` already receives `role: Role` (`Topbar.tsx:22-31`). The account menu is the **sole exception** to the shell's prop-threading rule: `Sidebar` (`AppShell.tsx:104`), `Topbar` (`:111`, `:43`) and `BottomTabs` (`:49`, `:114`) all take `role`.
2. **The role decision is made at line 99-101 from the wrong source.** `const currentRole = resolveRole(selectedRole); const isPatient = currentRole === "patient"; const isDoctor = currentRole === "doctor";` - `selectedRole` is the session's selected role, and the session can never carry `"doctor"`, so `isDoctor` is `false` in production.
3. **The doctor's branch of the trigger is already correct and already unreachable.** `AccountMenu.tsx:182-187` renders `<Avatar className={avatarClassName} />` with **no `photoRef` and no `name`**, so it falls through to the person icon. That branch is right in isolation; it is simply never taken. The `else` at `:188-190` - `(user?.phone || "?").slice(-2)` - is what a real doctor actually gets today.
4. **The existing tests conceal the bug by fabricating a role the backend cannot issue.** `AccountMenu.test.tsx:74-80` builds `ME_RESPONSE_DOCTOR` with `roles: ["doctor"]`. Nothing in the identity layer can produce that payload.

## Spec excerpt

The binding rule is the one the codebase already states for itself. `apps/frontend/src/app/(patient)/layout.tsx:1-6`, the header comment that the three sibling layouts defer to:

> The path prefix fixes the shell role, so each group layout pins the shared AppShell family to one role instead of resolving it from the session's selectedRole.

And `apps/frontend/src/lib/auth/staff-routing.ts:187-189`, the existing statement of the domain fact:

> Doctor-ness is a partner_type, never an iam role (the grants table only allows patient|partner|operator), so an active doctor partner lands on the doctor console via type rather than a doctor role.

**There is no spec or architecture document that must be re-read to do this ticket.** The rule is the code's own comment, and #567's own acceptance criteria are the contract. `docs/design/ui-blueprint.md` §2.6 is the account-menu convention; §2.3 is the two densities. Neither changes here.

## Chain ordering (where the later tickets attach)

| ticket   | what it inherits from this one                                                                                                                                  |
| -------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **#568** | nothing from the role plumbing; it generalises `useProfilePhotoSource` and moves the doctor profile page onto it. It runs **after** #567 so its suite is green. |
| **#569** | the threaded `role` prop. It needs the shell to know it is the doctor shell before it can fetch a doctor photo ref "alongside that same feed".                  |
| **#570** | the threaded `role` prop **and** #569's shell-held doctor photo ref. It rebuilds only the dropdown body, not the trigger.                                       |

**#567 must land with the doctor branch reachable but otherwise unchanged.** Do not widen the dropdown body, do not touch the doctor trigger's icon treatment, and do not add any read. Those are #569 and #570.

## Read-list (in order)

1. **`apps/frontend/src/components/dashboard/AccountMenu.tsx`, whole (268 lines)** - the component being changed. Header comment 3-31 (the `#521` / `#538` / `#526` provenance, including line 16-17 "person-icon fallback until the doctor profile seam lands" and line 25-28 "the staff branch keeps ... a non-accented Log out row"). `identityLine` 68-73. `patientMenuItemClass` 75-78. `AccountMenu` body 89-151: `currentRole`/`isPatient`/`isDoctor` 99-101, `saved` 102, the `useProfilePhotoSource` call 109-111, `otherRoles`/`roleSwitchItems` 112-125, `redLogoutItem` 130-141, `roleBadge` 144-151. JSX 153-268: the three trigger branches 176-191, the content width `isPatient ? "w-60" : "w-52"` at 193, the patient branch 194-238, the non-patient branch 239-264 with the doctor-only Profile row at 245-254. (~2.8K tokens)
2. **`apps/frontend/src/components/dashboard/AppShell.tsx`, whole (142 lines)** - where the role already lives. `AppShell({ role, children })` 27-33; the light branch 36-52 (`<Topbar density="light" role={role} />` at 43, `<BottomTabs role={role} />` at 49); `FullShellBody` 64-117 (`<Sidebar role={role} ...>` 104, `<Topbar density="full" role={role} />` 111, `<BottomTabs role={role} items={navItems} />` 114); `useOpenCasesCount` 119-142. **Note the light branch also renders a `Topbar` with no account-menu-relevant role beyond `patient`** - whatever prop shape you choose must not break `density="light"`. (~1.1K)
3. **`apps/frontend/src/components/dashboard/Topbar.tsx` lines 20-31 and 54-72** - `TopbarProps { density; role }` 22-25, the signature 31, the `density === "full"` page-title slot 54-59, and the account cluster 60-72 with the bare `<AccountMenu />` at 71. The full-density slot is a page-title div and nothing else, so adding a prop to the cluster costs no layout change. (~0.5K)
4. **`apps/frontend/src/components/dashboard/types.ts`, whole (42 lines)** - `Role` union at line 5 (four members, `"doctor"` among them), `ROLE_LABELS` 7-12 (the authoritative key set), `roleLabel` 14-16, `isAppRole` 21-23, `resolveRole` 27-29, `ROLE_HOME` 37-42. **Do not edit this file's union** - the role vocabulary is unchanged by this ticket; only who supplies the value changes. (~0.45K)
5. **The four route-group layouts, header comments plus the single `AppShell` line** - `(patient)/layout.tsx` lines 1-9 and 16-26 (the "path prefix fixes the shell role" rationale, plus the `ProfileProvider` wrapper that only the patient group has), `(doctor)/layout.tsx` 1-16, `(partner)/layout.tsx` 1-14, `(operator)/layout.tsx` 1-13. (~0.4K)
6. **`apps/frontend/src/lib/auth/staff-routing.ts` lines 100-135 and 185-201** - the prior art for the production-shaped doctor session. `PostLoginInput.partnerType` 120-122, `returnAllowed`'s `partnerType === "doctor"` territory widening 131-149, and `postLoginTarget`'s single-staff-role branch 185-194 carrying the `Doctor-ness is a partner_type, never an iam role` comment. This is how the app already decides doctor-ness: **partner role + doctor partner type**. (~1.0K)
7. **`apps/frontend/src/components/dashboard/AccountMenu.test.tsx` lines 1-200** - the suite being rebuilt. Header comment 1-12. The `profileApi` hoisted mock 47-57 (a **whole-module** `vi.mock("@/lib/profile/api")`, so any new import the menu adds must be added here). `VALID_SESSION` 59-66. **`ME_RESPONSE_DOCTOR` 74-80 - the synthetic doctor-role fixture to delete.** `ME_RESPONSE_PARTNER` 82-87, `ME_RESPONSE_NO_PHONE` 89-93. `NAMED_PROFILE` 95-113. `setStoredSession` 115-119, `renderAccountMenu` 121-127, `mockMeResponse` 129-133, `renderClosedTrigger` 138-169, `renderPatientWithProfile` 171-173. (~1.75K)
8. **`AccountMenu.test.tsx` lines 528-595 and 716-739** - the tests that must be rewritten, not deleted. 528-560 is `#538 shows the doctor a person-icon account avatar instead of phone digits` (asserts no `"90"` text, an `svg`, no `img`, and `fetchPatientPhoto` not called). 562-569 is the doctor Profile row. 571-576 is the non-doctor-staff negative. 578-594 is the non-doctor-staff verbatim regression. 716-739 is `keeps role switching for multi-role accounts`, which fabricates `roles: ["patient", "doctor"]` at 721 and asserts the label `"Switch to Doctor"`. (~0.6K)
9. **`apps/frontend/src/lib/auth/staff-routing.test.ts` lines 55-140** - the other synthetic-doctor-role sites, so you know what you are **not** fixing. `roles: ["patient", "doctor"]` at 69, `["doctor", "operator"]` at 78, `["doctor"]` at 121, `["doctor", "operator"]` at 131. (~0.75K)

## Do NOT read

- **`docs/archive/`** - the PRD supersedes it.
- `docs/prd/project-prd.md`, `docs/architecture/*`, `docs/roadmap/*`, `docs/adr/*`. This ticket touches no module, no event, no API, no schema, no ADR, and no session transport. Nothing there constrains the work, and `CONTEXT.md`'s hard gate does not fire (no cookies, no CORS, no middleware, no `credentials`, no deploy env).
- **The photo seam** - `useProfilePhotoSource.ts`, its suite, `ProfilePhotoCard.tsx`, `BottomTabs.tsx`'s `useProfilePhotoSource` call at line 195. That is #568. You only need to know the account menu's own call site at `AccountMenu.tsx:109-111`.
- **The doctor photo reader** (`lib/doctor/api.ts`) and the doctor profile page. #568/#569.
- **`Sidebar.tsx` and `nav-config.ts`.** The shell already passes the role correctly to both; the sidebar is not the defect and its composition is later work.
- **`PartnerRegisterWizard.tsx`, `StaffLoginForm.tsx`** beyond noting that both are being rewritten by #562. Do not fix their classes or their mock hygiene here.
- **Backend code, migrations, e2e specs.** No e2e spec asserts a doctor account-menu branch today (the three specs are `auth-loop`, `doctor-workspace`, `patient-journey`); grep if you need to confirm, do not read them.
- `docs/design/ui-blueprint.md` beyond §2.3/§2.6 if you need the density vocabulary. §1.2 tokens are out of scope (that is #564's territory).

## Key facts and prior art

- **The production-shaped doctor session is a `partner` role.** The `/me` payload's `roles` array can only contain `patient | partner | operator`. Doctor-ness is the partner's `partner_type`, read from `/v1/partner/me` (`PartnerMeView.partner_type`, `lib/partner/api.ts:42-48`) and carried on `PostLoginInput.partnerType` (`staff-routing.ts:120-122`). **The account menu's own test does not have to model the partner-type read at all** - after this fix it is told doctor-ness by a prop, which is precisely the point. What the test must do is stop fabricating a `"doctor"` role.
- **An existing gate already pins the shell role.** `AppShell.test.tsx:914-927` (`each per-role group layout wires its role through AppShell`) reads all four `app/(role)/layout.tsx` files and asserts each contains `<AppShell` and `role="<role>"`. If you move where the role is pinned, that test goes red. That is a feature.
- **`useOptionalProfile()` returns `null` outside the patient group.** `ProfileContext`'s `ProfileProvider` is mounted only in `(patient)/layout.tsx:22`. So in the doctor shell `saved` is `undefined` and the patient branch is unreachable there anyway. Do not build the doctor photo/name path on the patient profile context.
- **The role badge is already a shared component-level constant** (`roleBadge`, `AccountMenu.tsx:144-151`), used by both branches. It is not part of this ticket's work and must stay shared.

## Baseline verify (must pass before the first edit)

```bash
npx vitest run src/components/dashboard/AccountMenu.test.tsx src/components/dashboard/AppShell.test.tsx --root apps/frontend
```

- **Confirmed green 2026-09-27: 4 files, 108 tests passed, 14.7s** for the four fast-loop suites of this chain (`AccountMenu`, `AppShell`, `useProfilePhotoSource`, `(doctor)/doctor/profile/page`). Expect jsdom `Error: Not implemented: navigation` stderr noise - not a failure.
- **Blockers #562 and #563 must be closed before the first edit.** `npm run test:unit:frontend` is **red on the untouched tree at brief time** - see `docs/agents/briefs/564-design-token-gate-class-attributes.md` for the measured breakdown (13 failed / 1519 passed across 3 files: `StaffLoginForm.test.tsx` 10 failures = #562, `PatientAuthWizard.test.tsx` 2 failures = #563, plus one third-file 5s timeout = a load flake not in scope, whose identity moves between runs). "Full frontend unit suite green" is a done-verify here, and you cannot attribute a red suite to your own change on a red baseline.
- `npm run lint`, `npm run typecheck` - confirmed green 2026-09-27 per the #564 brief.

## Done-verify (acceptance criteria → commands)

- `npx vitest run src/components/dashboard/AccountMenu.test.tsx --root apps/frontend` - green, **including the rebuilt production-shaped doctor session** and an unchanged `ME_RESPONSE_PARTNER` negative.
- `npx vitest run src/components/dashboard/AppShell.test.tsx --root apps/frontend` - green, including the four-layout role-pinning gate at `:917`.
- `npx vitest run src/components/dashboard/Topbar.test.tsx --root apps/frontend` - green (it opens the real account menu through the shell, `Topbar.test.tsx:150,166,182,241,248,297`).
- `npm run test:unit:frontend` - green, with #562 and #563 closed.
- `npm run lint`, `npm run typecheck`.

### Acceptance criteria as a checklist

- [ ] **Doctor-ness is an input, not an inference.** `AccountMenu` takes the shell's role as a prop; the `isDoctor` decision comes from that prop. `resolveRole(selectedRole)` no longer decides doctor-ness anywhere.
- [ ] **The role is threaded, not re-inferred at each leaf.** `AppShell` → `Topbar` → `AccountMenu`, matching how it already reaches `Sidebar` and `BottomTabs`. One decision, made at the shell.
- [ ] **The prop travels unbroken on both densities.** The light (`density="light"`) top bar still compiles and renders; the patient branch is untouched.
- [ ] **The rendered-surface test is driven by a production-shaped doctor session** and would fail against a component that went back to asking the session. Prove the direction of the test: the doctor affordances must be asserted _through_ the shell's role, with no `"doctor"` in any `/me` roles array.
- [ ] **`ME_RESPONSE_DOCTOR` is gone from `AccountMenu.test.tsx`.** The doctor session is built the way the backend builds one - a `partner` role with a doctor partner type - and no synthetic doctor role survives in that suite, **including the multi-role role-switch test at line 716-739** (its `["patient", "doctor"]` becomes a real role pair and its asserted label changes with it).
- [ ] **No synthetic doctor role is introduced anywhere in the frontend.** Grep `roles: [` across `apps/frontend/src` and `tests/` before you close. The four sites in `lib/auth/staff-routing.test.ts` (lines 69, 78, 121, 131) are **out of scope for this ticket** - that suite feeds raw role strings to a pure router whose contract is the role vocabulary, not a session - so record them as findings on the ticket rather than silently rewriting them.
- [ ] **The session role still governs the patient branch and the non-doctor staff branch**, and both keep their current behaviour. The `#543 keeps the Profile row off non-doctor staff menus` negative and the `non-doctor staff keeps the phone-digit trigger and dropdown verbatim` regression must be **untouched and green**, and must still be driven by a `partner` role.
- [ ] **No backend change, no session-transport change, no change to the identity layer's role vocabulary.** `Role`, `ROLE_LABELS`, `isAppRole`, `resolveRole`, `ROLE_HOME` in `types.ts` are byte-identical afterwards.
- [ ] **No new read, no new endpoint, no new user-facing string.** This ticket only moves a boolean.

## Handoff notes

- **The bug is a fixture, not a component.** The `isDoctor ? ... : phone-digits` branch is already written and already correct. The line you change is `:99-101`. If you find yourself editing the doctor's JSX, you are doing #569 or #570.
- **Prop naming matters for #569/#570.** #569 threads a doctor photo ref down the same path; #570 changes the dropdown body. Pick a prop name that reads as "the role I am inside" rather than "am I a doctor" - a boolean prop would push the branch decision back down to the leaf and undo the ticket. Say which name you chose and why in the PR.
- **`Topbar`'s full-density branch is a page-title slot and nothing else** (`Topbar.tsx:54-59`). Nothing to reflow; the change is a prop on the cluster's `AccountMenu` element.
- **The stale-session degrade must survive.** `identityLine` (`:68-73`) and `accountIdentity` (`BottomTabs.tsx:173`) are the single source of the `Subject #id` fallback. Do not fork them for the doctor branch.
- **This brief is the chain's foundation.** When #569 and #570 are implemented, their read-lists point here, not back at `AccountMenu.tsx` and `AppShell.tsx` from scratch. Keep the names you introduce stable.
- **No em-dashes anywhere** (lint-gated by the `no-em-dash gate` pre-commit hook) - use simple dashes.
