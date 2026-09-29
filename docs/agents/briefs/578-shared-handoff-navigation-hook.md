# Brief - 578 Add the shared handoff navigation hook

**Ticket:** #578 · **Parent:** #577 (part of #529) · **Refreshed:** 2026-09-28
**Blocked by:** None
**Reading surface:** ~3.5K tokens (budget 10K) - **PASS, comfortable**

## Scope

One small hook in the frontend's auth library that owns the whole navigation decision for both verified-login flows, and is the single place the minimum dwell is defined.

Two inputs: whether the flow is ready, and the routine that actually navigates. One output: a callback meaning "navigate as soon as possible", which the handoff's "Go to Dashboard" button is wired to.

The rule, stated once:

- while the flow is not ready, do nothing at all
- when the flow becomes ready, schedule the navigation after a short minimum dwell, unless the caller has already asked to go, in which case schedule it immediately
- whichever path fires, it fires at most once
- the dwell is measured **from readiness, not from mount**, so nothing about a slow flow is shortened and a fast flow is still guaranteed a readable beat
- the scheduled timer is cleared if the host goes away first

**No login flow is wired to it yet.** This is the prefactor that makes #579 and #580 easy, and its timing contract is tested directly so its consumers can stay dumb.

## Acceptance criteria (from the ticket)

- [ ] Nothing happens before readiness.
- [ ] Once ready, navigation happens exactly once, after the minimum dwell measured from readiness.
- [ ] The go-now callback skips the dwell, and still does not navigate before ready.
- [ ] Exactly one navigation ever, even when both paths are exercised and go-now is pressed repeatedly.
- [ ] The dwell is measured from readiness, not from mount.
- [ ] The scheduled timer is cleared on unmount; no state update or navigation after teardown.
- [ ] A fresh navigate-routine identity on a later render does not re-arm the timer, restart the dwell, or produce a second navigation.
- [ ] The minimum dwell is defined in exactly one place in the codebase.
- [ ] This hook's own suite is the only new test seam the ticket introduces.

## THE INTERFACE YOU MUST CONFORM TO

Prior art, and the reason this seam is legitimate: the shared profile-photo resolution hook pins its own lifecycle contract directly so its consumers can stay dumb, instead of duplicating five or so assertions in every host.

**The caller-supplied-function rule is the load-bearing part, and it is already solved in this repo.** Both future hosts pass an inline arrow function, so a fresh identity arrives on every render. If the routine becomes an effect dependency, the timer re-arms and the dwell restarts - the flow never navigates.

`lib/profile/useProfilePhotoSource.ts:152-153` is the pattern, and its comment is the reasoning you should mirror:

```ts
const reader = useRef(read);
reader.current = read;
```

and the test that pins it is `useProfilePhotoSource.test.ts:274` - "does not re-read a ref when the reader arrives as a fresh function each render" - which rerenders twice and asserts the work happened exactly once. **Your hook needs the same test, and it is the closest prior art for the whole ticket.**

**The at-most-once guard is already twice-solved in this codebase**, and the shape differs from a `useState` boolean because these hosts can be StrictMode double-invoked: `DoneScreen` keeps a `departedRef` in a ref specifically so the latch survives, with `departed` state only for rendering. Use a ref for the latch. Do not use `useState` as the once-only guard.

**`lib/auth/useRoleHomeHref.ts`** is the one existing hook in the target directory - it is the module-shape precedent (a small named export returning a value, in `lib/auth/`, with a co-located `.test.ts`). There is no `index.ts` in that directory; each module is imported by path.

## Read-list (in order)

1. **`lib/profile/useProfilePhotoSource.ts` L142-181** - the exported hook's head, the reader ref, the effect's guard clauses, and the `live` flag. That is the shape to copy (~0.8K).
2. **`lib/profile/useProfilePhotoSource.test.ts` L246-291** - the `renderHook`-based fresh-identity test and the second describe's setup. This is your suite's template (~0.7K).
3. **`lib/auth/useRoleHomeHref.ts`** in full - the target directory's module shape (~0.2K).
4. **`docs/standards/coding-standards.md`, the tests section only** - test naming, traceability, the rule that test names derive from acceptance criteria and carry the ticket reference in the file header comment (~0.8K).
5. **#577's "Testing Decisions"** - the paragraph that states why this seam exists despite the usual preference for the highest seam, so your file header comment tells the truth (~0.3K).

(~2.8K; the ticket body and this brief carry the rest)

**Re-grep by name if any of these no longer resolves:** `useProfilePhotoSource`, `useRoleHomeHref`, `departedRef` in `components/auth/DoneScreen.tsx`. Then refresh this brief.

## Do NOT read

- **`components/auth/DoneScreen.tsx` and its suite**, the two login forms and their suites, the i18n dictionary. You are writing one hook; every one of those is a future consumer, and #579 and #580 are the tickets that own them.
- **`lib/auth/AuthContext.tsx`, `api.ts`, `session.ts`, `staff-routing.ts`.** The hook is pure timing over two inputs. You need nothing from the auth context, the transport, or the routing matrix, and you are not changing the session seam.
- **The backends, migrations, and `docs/adr/0007-*`.** No cookie, CORS, proxy-guard, `credentials` or deploy-env change, so the ADR-0007 hard gate does not apply. No API contract, no schema, no event.
- **`docs/archive/`, the PRD, `internal-modules.md`, the roadmap, the UI blueprint, the other standards.** No architecture or requirement question is in scope - the rule is stated completely in the ticket.
- **The e2e specs.** They do not reference this screen.

## Baseline verify (must pass before the first edit)

```bash
npm run test:unit:frontend
npm run typecheck
```

**Recorded on 2026-09-28 at `acdb078`, so you do not have to re-derive it:**

- `npm run test:unit:frontend` - **1 failed / 1645 passed (1646), 102 files.** The single failure is `src/app/(doctor)/doctor/cases/[caseId]/page.test.tsx > CaseWorkspacePage stage + forced review (US-15) > renders the case stage chip for the pre-summary stage`, a 5s `Test timed out`. It is the known unowned load flake, documented in #566's brief, and it is **not yours**. Do not fix it and do not count it as your regression.
- `npm run typecheck` - clean.
- `npm run lint` - clean, all pre-commit hooks including the no-em-dash gate.
- `git status --porcelain` - the untracked `docs/agents/briefs/*.md` files are pre-existing repo habit, not yours. Do not stage them.

## Done-verify (acceptance criteria -> commands)

```bash
npx vitest run src/lib/auth --root apps/frontend    # your new suite, plus the neighbours
npm run test:unit:frontend
npm run typecheck
npm run lint
```

Criterion by criterion:

- **Nothing before readiness** - the suite's first test: not ready, advance well past the dwell, `navigate` not called.
- **Once after the dwell** - ready, advance to just under the dwell (not called), then past it (called exactly once).
- **Go-now skips the dwell** - ready, press go-now, advance by a small amount, called.
- **Go-now still waits for readiness** - not ready, press go-now, advance past the dwell, still not called; then flip ready, called once.
- **One navigation, ever** - exercise dwell-scheduled and go-now in both orders, and go-now repeatedly; assert `navigate` was called exactly once in each.
- **Dwell from readiness, not mount** - mount not ready, advance a long time, flip ready, then advance the dwell; called. If the dwell were measured from mount this would have fired during the first advance.
- **Cleared on unmount** - ready, unmount, advance past the dwell; not called. The existing `DoneScreen` suite has a sibling of this test you can pattern-match.
- **Fresh identity** - the `useProfilePhotoSource.test.ts:274` shape: rerender twice with an inline closure, assert one navigation and no restart.
- **One definition of the dwell** - grep it:
  ```bash
  # expect exactly one definition in the tree, inside your hook module
  ```
  Neither host may grow its own copy. This is a user story in its own right (#577 story 34).

**Use fake timers in this suite, and scope them.** The three existing fake-timer suites in the auth area all fake only what they need (`vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] })` in the wizard suite, and a `clearInterval`-only variant in the partner suite) - and they differ because of what they are faking. Your hook schedules with whatever timer you choose; fake exactly that timer, and reset in `afterEach` alongside `cleanup()`. There is **no** global mock-lifecycle option in `vitest.config.ts`, so every lifecycle decision in this file is yours and manual.

## Handoff notes

- **The minimum dwell is the one number in this whole set, and it is deliberately tiny.** #577: the five seconds were doing two jobs and only one was real; the confirmation beat survives as a sub-second minimum dwell measured from readiness, and the delay disappears. An honest login that waited up to five seconds now waits under one. **Keep it well under a second** - if you find yourself writing `5000`, you have rebuilt the bug this ticket exists to remove. #577's closing note also records the escape hatch: removing the dwell entirely is a one-line change to your hook, so if a value ever needs tuning it is tuned here and nowhere else.
- **Do not import anything from the auth context or the transport.** The hook is pure timing over two inputs. If you find yourself reaching for `useAuth`, you are building the wrong module.
- **Do not wire a host in this ticket.** It is tempting (the partner form is one line away) and it would put #579 and #580's work inside a ticket that has no business touching a 1917-line suite. Leave the tree green and unconsumed; a new hook with a complete, directly-pinned contract is a legitimate deliverable.
- **The at-most-once guarantee is a ref, not state.** See `departedRef` in the handoff component. These hosts run under StrictMode, and a state-based latch double-fires.
- **The fresh-identity trap is the one way this hook ships broken**, because both consumers pass inline closures and a per-render re-arm produces "the button does nothing and the flow never navigates" - a symptom that looks like the old frozen screen and would be misfiled as a network problem. Write that test first, before the hook, and see it fail.
- **No em-dashes anywhere** in code, comments, or the commit message. The repo's `no-em-dash gate` pre-commit hook enforces it and the codebase follows the rule in its own prose. Use simple dashes.
- **This brief is the contract.** Read it, not the world. Do not read the handoff component, the two forms, or the dictionary.
