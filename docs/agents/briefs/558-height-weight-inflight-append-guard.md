# Brief - 558 Regression guard: a measurement appended before the first load lands survives

**Ticket:** #558 · **Parent:** #553 · **Refreshed:** 2026-09-27
**Reading surface:** ~5K tokens (budget 10K) - within budget

## Scope

**No new behaviour.** The height/weight series fix already landed: an append reconciles against the API, and every read claims a generation so a superseded read cannot answer over a newer one. This slice adds exactly one thing - a test that adds a measurement while the first page load is still in flight and asserts the entry survives once the list settles.

If you find yourself editing production code to make the test pass, stop: either the landed fix is genuinely broken, or the test is wrong. Read the generation-claim logic first and decide which.

## Read-list (in order)

1. **The health-metrics series component** (~18KB file, but read only the list/append/load machinery, roughly the top third) - three things: the mount effect that triggers the first page load; the append handler, which optimistically prepends the new entry, bumps the total, and clears the draft; and the load path's **generation claim**, which is what stops a superseded read from answering over a newer one. Also note the reconciliation step after a successful append, and the load-more path, which is the existing refetch pattern to match. (~1.5K tokens)

2. **The health-background client wrapper** - the four thin typed wrappers: the metrics first-page read, the metrics append (which takes an input and a retry key), the background read, and the background save (which takes an acknowledgement flag and a retry key). The retry key is what makes the reconciliation safe to re-fire. (~500 tokens)

3. **The existing test suite for the zone** - read the metrics portion of `HealthBackgroundZone.test.tsx` (the file is 38KB, so read the metrics describe blocks, not the whole thing). You need: how the client module is mocked, how `appendHealthMetric` is currently asserted, and how the first-page read is stubbed. Critically, find whether an existing test **already controls the timing** of the first load with a deferred promise - if so, copy that mechanism rather than inventing one. (~2K tokens)

4. **The read-generation mechanism's own name and contract** - grep for the generation claim in the series component and read what it actually does. This is the behaviour under test; you are pinning it, not redesigning it. (~700 tokens)

## Do NOT read

- The health module facade, routes, or the consent/care/intake backend modules. This is a frontend test-only slice.
- The avatar, photo-resolution, and profile-media paths (#556 / #557).
- The doctor pages, `docs/archive/` (the PRD supersedes it), binary assets, migrations.

## Baseline verify (must pass before the first edit)

```bash
npm run test -w @caresetu/frontend -- src/components/patient/profile/HealthBackgroundZone.test.tsx
```

## Done-verify (acceptance criteria → commands)

- The new test exists and is **deterministic** - it controls the in-flight read with a deferred promise, never a timing sleep:
  ```bash
  npm run test -w @caresetu/frontend -- src/components/patient/profile/HealthBackgroundZone.test.tsx
  ```
- Run it repeatedly to prove it is not flaky:
  ```bash
  npm run test -w @caresetu/frontend -- src/components/patient/profile/HealthBackgroundZone.test.tsx --repeat=5
  ```
- The change is additive - no production code touched, no existing test altered:
  ```bash
  git diff --stat
  ```
- Full frontend suite still green:
  ```bash
  npm run test:unit:frontend
  ```

## Handoff notes

- **This is a guard, not a fix.** The parent spec is explicit: "This spec adds only a regression guard, not new behaviour." The landed fix is the append reconciliation plus the read-generation claim, both in `f10f1b2`.
- **Why the guard is worth writing.** The original symptom was an entry added before the list finished loading disappearing when the initial read answered over it. The fix is in place; nothing pins it. A future refactor that drops the generation claim reintroduces the bug with a fully green suite.
- **The test must be deterministic.** Reach for a deferred promise you resolve by hand, or an explicitly ordered sequence of mock resolutions. A `setTimeout`, `waitFor` with a real delay, or a bare `await` in the wrong order will pass in CI and flake locally, and a flaky guard is worse than no guard because it trains people to re-run it.
- **Match the existing mock style.** The suite already mocks the client module and asserts against the mocked wrappers. Do not introduce a second mocking approach in the same file.
- **If the test fails against current code, do not paper over it.** That would mean the landed fix does not actually cover this case. That is a finding worth reporting on the ticket, not something to fix by relaxing the assertion.
