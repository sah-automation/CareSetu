# Brief - 303 Operator console redirect honors operator role (Phase 5 auth fixes)

**Ticket:** #303 · **Parent:** #299 · **Refreshed:** 2026-09-04
**Reading surface:** ~2.5K tokens novel (budget 10K) - within budget

## Scope

An operator who is signed out and clicks the homepage footer "Operator console" link (which points to `/operator`) is redirected to the operator phone + TOTP login form (`/staff/login?role=operator`), not the partner email + password form. The original `/operator...` path still rides along as the `return` param so the operator is sent back to where they were headed after signing in. Logged-in operators still reach `/operator` directly.

Today an unauthenticated `/operator` hit redirects to plain `/staff/login` (the partner form), because the proxy's app-group entry for `/operator` does not carry the operator role hint.

- [ ] The proxy's `/operator` app group redirects unauthenticated visits to `/staff/login?role=operator` instead of `/staff/login`.
- [ ] The `return` param still carries the original `/operator...` path + query on the redirect.
- [ ] The homepage footer "Operator console" link still points to `/operator` (no text/href change needed).
- [ ] The proxy unit tests cover the new operator redirect shape; existing proxy tests still pass.
- [ ] Full frontend unit suite passes.

## Read-list (in order)

1. **Proxy app-group module** - the `AppGroup` interface (currently `{ prefix, entry }`) and the redirect builder (`proxy` function) which clears the entry's search string, sets the `return` param, and redirects. Add an optional per-group entry-query mechanism (e.g. `entryParams` on `AppGroup`) and apply it for the `/operator` group: `entry: "/staff/login"` + params `{ role: "operator" }`. The `/doctor` and `/partner` groups keep `entry: "/staff/login"` with no params. (~1K tokens)
2. **Proxy unit tests** - currently assert staff groups redirect to `/staff/login?return=...` including `/operator`. Add/update assertions so `/operator` and `/operator/audit` redirect to `/staff/login?role=operator&return=...` while `/doctor` and `/partner` stay unchanged; the `return` value must still encode the original path+query. (~0.8K tokens)
3. **Footer component** - the homepage footer "Operator console" link currently targets `/operator`. Verify only, no change expected. (~0.3K tokens)

## Do NOT read

- The registration wizard, backend IAM modules, patient routes, the login form internals, archives.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` - 58 files / 617 tests pass. Note: the process exits 1 on a _pre-existing_ teardown-timing error in `channels.test.tsx` ("window is not defined" after environment teardown, an uncleared timer). That file is unrelated to this ticket; ignore its teardown error, your suite must remain green otherwise.

## Done-verify (acceptance criteria -> commands)

- `npm run test -w @caresetu/frontend -- src/proxy.test.ts` - operator redirect tests pass, doctor/partner/patient unchanged.
- `npm run typecheck:frontend` - the extended `AppGroup` shape compiles across call sites.
- `npm run test:unit:frontend` - no new failures.

## Handoff notes

- Blocked by #302: `/staff/login?role=operator` must actually render the operator form before this redirect is useful - that is the landing surface this ticket points at.
- The proxy checks only the presence-hint cookie (`caresetu_authed`), never JWT claims. Signed-out operators get the redirect; signed-in operators pass through. Keep that invariant.
- The `return` param must continue to be added after the entry search is cleared, exactly as today - the only change is the extra entry query for the operator group.
- The footer link (`/operator` href, "Operator console" label) needs no change; the behavior is entirely the proxy's.
