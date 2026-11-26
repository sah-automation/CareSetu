# Brief - 562 Repair the staff sign-in suite's mock hygiene and its dead-mock contract

**Ticket:** #562 · **Parent:** #560 (front five defects, part 1 of 16) · **Refreshed:** 2026-09-27
**Blocked by:** #561 (the frontier pre-flight; its recorded baseline is the reference for "was it red before")
**Reading surface:** ~7.9K tokens (budget 10K) - within budget

## Scope

Make `src/components/auth/staff/StaffLoginForm.test.tsx` an honest feedback loop. Two independent faults produce its ten failures, and both must go: the suite clears mock _calls_ between tests but not mock _implementations_, so a route-state implementation installed by one test keeps answering for the next; and the module factory for the staff-routing seam replaces `fetchPartnerRouteState` wholesale, so the real reader - and therefore the mock it would call - never runs, leaving `mockFetchPartnerMe` as dead code the suite still asserts on.

**This is a test-harness repair. No production code changes, no backend, no migration, no API contract, no session-transport change.** If you find yourself editing `StaffLoginForm.tsx` or anything under `apps/backend/`, you have left the ticket.

AC:

- [ ] The staff sign-in suite passes on its own, and passes as part of a full frontend unit run.
- [ ] Between-test cleanup resets mock _implementations_, not only call records, so a partner route-state implementation set by one test cannot answer during the next.
- [ ] No test asserts on a mock that the production code path never calls; the partner-status assertion is driven through the seam that actually runs in production, or the mock is removed and the assertion is made at a seam that does run.
- [ ] The suite's mock lifecycle is uniform: a mock installed for one test cannot silently answer for the next, demonstrated by at least one deliberately-broken ordering that the cleanup now prevents.
- [ ] No production code changes; this is a test-harness repair only.
- [ ] The working tree is clean of the uncommitted `doneScreen.module.css` edit before this ticket's verdicts are trusted (tracked by the pre-flight ticket).

## Read-list (in order)

1. **Issue #562 itself** - the six AC above, and its own Context pack. Its read-list hint ("grep for the mock names first, do not read either test file whole") is correct and is why this list is sliced rather than whole-file (~0.7K).
2. **`apps/frontend/src/lib/auth/staff-routing.ts` - named regions only, not the whole file (224 lines):**
   - L10-13, the imports, to see that `fetchPartnerMe` is imported here and nowhere else in the module.
   - L46-56, `partnerStatusToState` - the status-vocabulary mapping.
   - L58-68, the `PartnerRouteState` interface.
   - L70-98, **`fetchPartnerRouteState`** - the whole doc comment and body. This is the seam; note the `!roles?.includes("partner")` short-circuit before the read and the catch that degrades to `{ undefined, undefined }`.
   - L113-129 + L151-201, the `PostLoginInput` shape and `postLoginTarget`'s rule order. Read to know what the _inputs_ being asserted actually mean.
     (~1.5K)
3. **`StaffLoginForm.test.tsx` L44-155 - the module-level mock block, `afterEach` and `beforeEach` (~1.2K).** This is 112 lines and it holds the entire defect:
   - L44-54 `mockLocationReplace` + the `@/lib/operator/api` factory.
   - L56-69 the `@/lib/auth/api` factory (an `importOriginal` spread, so only the listed functions are replaced).
   - L71-74 `@/lib/auth/session`; L79-93 `@/lib/auth/AuthContext` (a `vi.hoisted` `resumeSession`).
   - L95-100 `next/navigation` (`mockRouterReplace`).
   - **L102-107 the `@/lib/partner/api` factory and `mockFetchPartnerMe` - the dead mock.**
   - **L109-121 the `@/lib/auth/staff-routing` factory - the two hoisted mocks and the two replacements. L118-120 is the root cause of the whole ticket.**
   - L123-128 `afterEach` (`vi.clearAllMocks()` only) and L130-155 `beforeEach` (read which mocks get `mockReset()` and which do not).
4. **`StaffLoginForm.test.tsx` - only the ten failing test bodies (~2.7K):** L550-621 (`verifies the code, mints a partner session, and routes via postLoginTarget`), L623-652 (the `completePartnerLogin` shared helper), L654-675 (`it.each` "lands an already-logged-in %s partner"), L677-706 (`derives no partnerState...`), L733-755 (`it.each` "passes the return target even when the %s partner state overrides it downstream"), L757-797 (`falls back to role-based routing when the partner status read fails`), L799-831 (`does not read partner status for a non-partner session`), L932-962 (`Operator login flow > saves session and routes on successful login`). The 42 passing tests you are not touching need not be read - grep them by name if you change shared helpers.
5. **`StaffLoginForm.tsx` L251-296 - `landAfterLogin` and `landPartnerAfterLogin` (~0.5K).** Read this to confirm what production actually calls: `landAfterLogin` (operator) spreads `await fetchPartnerRouteState(me.roles)` inline; `landPartnerAfterLogin` awaits it into a named `routeState` and then branches on `routeState.partnerType !== "doctor" || routeState.partnerState !== undefined`. Both call the seam, both consume its return. Nothing else in the file is in scope.
6. **`apps/frontend/src/lib/auth/staff-routing.test.ts` L20-33 and L224-261 - the exact prior art, in-repo (~0.7K).** It is the file that already does this correctly: it mocks `@/lib/partner/api`'s `fetchPartnerMe` while leaving the **real** `fetchPartnerRouteState` running, and its `beforeEach` is `mockFetchPartnerMe.mockReset()`. Its `describe("fetchPartnerRouteState")` block is the five-case table plus the degrade and short-circuit cases. Copy this shape.
7. **`ProviderRegisterWizard.test.tsx` L150-188 - the second prior art (~0.4K).** Its `beforeEach` gives every partner-mock an explicit default with `.mockReset().mockResolvedValue(...)` rather than trusting cleanup, and its `afterEach` pairs `vi.clearAllMocks()` with the extra resets it needs. This is the "uniform mock lifecycle" shape AC-4 asks for.
8. **`apps/frontend/vitest.config.ts`** (20 lines, read whole) - confirms there is **no** global `clearMocks` / `mockReset` / `restoreMocks` option, so you cannot lean on a config change instead of a per-file fix (~0.2K).

**Re-grep by name if this no longer resolves:** `mockFetchPartnerRouteState`, `mockFetchPartnerMe`, `fetchPartnerRouteState`, `importOriginal` in `StaffLoginForm.test.tsx`; `clearMocks|mockReset|restoreMocks` in `apps/frontend/vitest.config.ts`. If the `vi.mock("@/lib/auth/staff-routing")` factory no longer replaces `fetchPartnerRouteState`, the dead-mock fault is already gone - re-derive the failures from the red output rather than from this brief.

## Do NOT read

- **`StaffLoginForm.test.tsx` whole.** 1218 lines, of which the mock block and the ten failing bodies are all you need. The 42 passing tests are context you will not use; grep them if a shared helper changes.
- **`StaffLoginForm.tsx` beyond L251-296.** 759 lines of phone-step, resend, code-step, demo-banner, and operator-MFA rendering. None of it is what is broken. The failure is in the harness, not the component.
- **`src/components/auth/otp/PatientAuthWizard.test.tsx`** - a separate ticket (#563) with its own two failures. Reading it here is a context switch you do not need, and its `it` names are confusingly similar ("does not double-navigate when the CTA is pressed mid-countdown (#551)" appears in both this file and that one).
- **The backends, `apps/backend/**`, migrations, `docs/adr/0007-\*`.** Nothing here touches a cookie, a CORS rule, a proxy guard, `credentials`, or a deploy env var, so ADR-0007's hard gate does not apply. There is no API contract and no session transport in this ticket.
- **`docs/archive/`**, the PRD, `internal-modules.md`, the roadmap, the UI blueprint.\*\* No architecture or requirement question is in scope. `docs/standards/coding-standards.md` is the only standard that touches you, and only for its tests clause.
- **`apps/frontend/src/lib/auth/return-url.ts` and the `ROLE_HOME` table.** You only assert the _inputs_ handed to `postLoginTarget`; you do not need to re-derive the matrix. `staff-routing.test.ts` (read-list item 6) already pins the real matrix as a table.

## Prefactor - do not re-derive these

- **Ten failures, two mechanisms, and the split is not random.** `StaffLoginForm.test.tsx` alone: `52 tests | 10 failed`. Reproduce with `npx vitest run src/components/auth/staff/StaffLoginForm.test.tsx`. Which assertion each test dies on tells you which fault it is:

  | Failing test                                                                          | Dies at                                                         | Fault                |
  | :------------------------------------------------------------------------------------ | :-------------------------------------------------------------- | :------------------- |
  | `verifies the code, mints a partner session, and routes via postLoginTarget` (L588)   | `expect(mockFetchPartnerMe).toHaveBeenCalled()`                 | dead mock            |
  | `lands an already-logged-in {Registered, Under Verification, Rejected} ...` x3 (L665) | `expect(mockFetchPartnerMe).toHaveBeenCalled()`                 | dead mock            |
  | `derives no partnerState for an active doctor partner ...` (L686)                     | `expect(mockFetchPartnerMe).toHaveBeenCalled()`                 | dead mock            |
  | `passes the return target even when the {Under Verification, Rejected} ...` x2 (L743) | `toHaveBeenCalledWith(objectContaining{ partnerState: state })` | stale implementation |
  | `falls back to role-based routing when the partner status read fails` (L789)          | `toHaveBeenCalledWith({ ... partnerType: undefined })`          | stale implementation |
  | `does not read partner status for a non-partner session` (L824)                       | `toHaveBeenCalledWith({ ... partnerType: undefined })`          | stale implementation |
  | `Operator login flow > saves session and routes on successful login` (L954)           | `toHaveBeenCalledWith({ ... partnerType: undefined })`          | stale implementation |

- **Fault one, the dead mock - the mechanism, exactly.** `vi.mock("@/lib/auth/staff-routing", ...)` (L113-121) spreads the original module and then **replaces** `fetchPartnerRouteState` with `(...args) => mockFetchPartnerRouteState(...args)`. `StaffLoginForm.tsx` only ever calls `fetchPartnerRouteState` (L258, L275), so the real implementation is dead, and `fetchPartnerMe` - whose **only** caller in the whole module graph is that real `fetchPartnerRouteState` (staff-routing.ts L86) - is never invoked. The suite nonetheless mocks `@/lib/partner/api`'s `fetchPartnerMe` (L105-107) and four tests assert it was called. Those assertions are checking a mock production never reaches. `beforeEach` L149-154 even configures a default for it, which is why the file looks like it has a partner-status mock: it does, and it is unreachable.
- **Fault two, the leak - the mechanism, exactly.** `afterEach` L126 is `vi.clearAllMocks()`. That resets _call records_ only; it does **not** touch a mock's implementation. `beforeEach` L130-155 `mockReset()`s twelve mocks but **not** `mockFetchPartnerRouteState`, so the `mockResolvedValue` installed at L552 persists through the `it.each` at L654, and the one at L679 persists through L733, L757, L799 and L932. That is why the last four rows of the table above expect `partnerType: undefined` and receive `"doctor"` from a test that ran several minutes of file-time earlier. `vi.resetAllMocks()` / `vi.restoreAllMocks()`, or a per-mock `mockReset()` in `beforeEach` as `ProviderRegisterWizard.test.tsx` does, is the fix AC-2 names.
- **The one change that kills both faults, and the one the AC actually rewards.** If the `vi.mock` factory stopped replacing `fetchPartnerRouteState` and let the real one run, then `mockFetchPartnerMe` becomes live, every `mockFetchPartnerMe.mockResolvedValue({ status, partner_type })` in the ten tests becomes load-bearing, and the stale-implementation failures disappear because there is no route-state mock left to go stale. That is AC-3's first branch, "driven through the seam that actually runs in production", and it is the same shape `staff-routing.test.ts` already uses. `mockPostLoginTarget` is a different case: it is a deliberate spy _and_ stub, the real `postLoginTarget` matrix is already pinned as a table in `staff-routing.test.ts` and `src/proxy.test.ts`, and AC-3 names the _partner-status_ assertion. Leave the routing spy alone unless the tests prove otherwise.
- **AC-4 is asking for a demonstration, not a vibe.** "A mock installed for one test cannot silently answer for the next, demonstrated by at least one deliberately-broken ordering that the cleanup now prevents" means: add a test that installs a persistent implementation on a partner mock, followed by a test that installs none, and show the suite is green in file order. A concrete form: one test that gives the partner-status seam a non-default answer and a following test that asserts the default, with neither depending on the other's position. Do not satisfy it by reordering `describe` blocks to hide a leak - that is the failure mode AC-4 is written against.
- **The pre-flight ticket's baseline is the number you are measured against.** Per #561's recorded baseline: 10 failures in this file, all 10 reproducing in isolation, plus 1 in `PatientAuthWizard.test.tsx` that is #563's. After this ticket the expected state is **this file 52/52 green and the full suite down to the #563 failures only** - 1 or 2 in `PatientAuthWizard.test.tsx`, depending on run-to-run variance, plus the intermittent `CaseWorkspacePage` flake that belongs to nobody.
- **No global mock-lifecycle option exists.** `apps/frontend/vitest.config.ts` sets no `clearMocks`, `mockReset` or `restoreMocks`. Every lifecycle decision is per file and manual. Do not add a global option as a "fix" - it would change all 101 test files' behaviour to solve a ten-test problem, and it is out of the ticket's scope.

## Baseline verify (must pass before the first edit)

The baseline is deliberately red. Reproduce it and confirm it matches #561's record before touching anything:

```bash
npx vitest run src/components/auth/staff/StaffLoginForm.test.tsx
# expect: 52 tests | 10 failed - the exact ten names in the Prefactor table

npm run test:unit:frontend
# expect: 11 or 12 failed | 1521 or 1520 passed (1532); Test Files 2 failed | 99 passed (101)
```

`git status --porcelain` must be clean of `apps/frontend/src/components/auth/doneScreen.module.css` before you trust a verdict (AC-6). If #561 has not run, stop and do that first.

## Done-verify (acceptance criteria -> commands)

- AC-1, the fast loop, both ways the AC names them:
  ```bash
  npx vitest run src/components/auth/staff/StaffLoginForm.test.tsx   # 52/52 green
  npx vitest run --reporter=json --outputFile="D:/Dev/tools/temp/opencode/after-562.json"
  # assert: 0 failures in StaffLoginForm.test.tsx
  ```
- AC-2 and AC-4, order-independence proven rather than asserted - run the file with a shuffled order if your setup permits it, and otherwise pin the deliberate-ordering test described in Prefactor. A run that is green only in the default order has not met AC-2.
- AC-3, honesty of the seam: grep the finished file and confirm no assertion survives on a mock production cannot reach. `expect(mockFetchPartnerMe).toHaveBeenCalled()` is only meaningful **if** the real `fetchPartnerRouteState` now runs; if you instead removed the mock, confirm the replacement assertion is on a seam that does run.
- AC-5, no production change:
  ```bash
  git diff --stat -- apps/frontend/src/components/auth/staff/StaffLoginForm.tsx
  git diff --stat -- apps/frontend/src/lib/  apps/backend/
  # both empty
  ```
- The full suite, and no collateral damage:
  ```bash
  npm run test:unit:frontend
  npm run typecheck
  npm run lint
  ```
  `npm run test:unit:frontend` should now report `Test Files 1 failed | 100 passed (101)` with 1-2 failures, all in `PatientAuthWizard.test.tsx` (and possibly the intermittent `CaseWorkspacePage` flake). Anything else red is a regression you introduced.

## Handoff notes

- **The tenth failure is in the operator suite, not the partner suite.** `Operator login flow > saves session and routes on successful login` (L932) fails from the same stale `mockFetchPartnerRouteState`: the operator path's `landAfterLogin` also calls `fetchPartnerRouteState` (StaffLoginForm.tsx L258), and the test expects `partnerType: undefined` while inheriting `"doctor"`. Do not scope the fix to the `describe("StaffLoginForm - partner code step")` block and leave it.
- **Two of the ten are `it.each` rows, not distinct tests.** `lands an already-logged-in ...` is one `it.each` over three rows and `passes the return target even when the ...` is one over two. Editing them means editing the table, not three and two separate bodies.
- **`postLoginTarget` stays mocked, deliberately.** It is both the spy the assertions read and the stub that decides the rendered landing. The real matrix is pinned in `staff-routing.test.ts` and `src/proxy.test.ts`; nothing about this ticket requires un-mocking it. Only the _partner-status_ path is in the AC.
- **Do not add a skip, a `.only`, or a deleted assertion.** AC-4 and the ticket's own framing ("a leak-free suite that asserts through a seam production does not use is still not a feedback loop") are explicit that a green-by-deletion suite fails the ticket.
- **Watch the 1097-vs-1218 line-count trap.** `Measure-Object -Line` in PowerShell skips blank lines and under-reports this file by ~120 lines. Use `(Get-Content <f>).Count` if you need a real count.
- **#563 is running against the same tree.** Once you land, #563's implementer inherits whatever mock lifecycle you establish. If your fix is a reusable per-file pattern, say so in the PR - the wizard suite has the same class of problem and will want the same shape.
- **No em-dashes anywhere (lint-gated).** Use simple dashes. `npm run lint` runs pre-commit, which includes prettier and a trailing-whitespace hook, so run it before declaring done.
