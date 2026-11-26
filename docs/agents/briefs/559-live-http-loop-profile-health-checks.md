# Brief - 559 Live HTTP loop: red/green check for the profile photo, first-save grant, and series fixes

**Ticket:** #559 · **Parent:** #553 · **Refreshed:** 2026-09-27
**Reading surface:** ~5K tokens (budget 10K) - within budget

## Scope

One repeatable command that reproduces the three reported symptoms against a **running service**, so a regression is caught by a script rather than by hand. A throwaway script - deliberately not a committed test-suite entry - that registers a throwaway patient through the existing register / OTP read-back / verify / session sequence, then asserts three things:

1. An acknowledged first health-background save answers **success**, and a subsequent read reports the acknowledgment. (Red before #554, green after.)
2. A photo upload's object appears in the **private profile-media bucket** under the service-role key, not only on local disk. (Red before #555, green after.)
3. An appended measurement is present in the first page after the list reloads. (Green already - this is the guard.)

A separate throwaway patient per run keeps it deterministic and repeatable. Run it **before** the edits to confirm red, and **after** to confirm green.

## Read-list (in order)

1. **The repo's existing live-check / end-to-end register sequence** - the scripts that register a patient and drive OTP read-back, verify, and session establishment. Reuse their helper functions and their request conventions; do not invent a second auth client. Find them under the e2e and integration script directories, and read `tests/integration/README.md` for how the local environment is expected to be brought up. (~1.5K tokens)

2. **The four endpoint contracts the script calls**, read from the _client_ wrappers, not the routes: the health-background read and first-save (including the acknowledgement flag and retry key the save requires), the health-metrics append and first-page read, and the patient photo upload. You need request shape, the authed-transport convention, and - critically - the **ack-required error code** the first save answers with when the acknowledgment is missing, because the script must assert success _after_ acknowledging, not confuse the two outcomes. (~800 tokens)

3. **How the service-role Supabase client is used server-side** - enough to check for an object in the private profile-media bucket from a script: the client construction, the bucket name, and the object-key shape the profile-media store writes. You are verifying the bytes landed in the bucket, not re-testing the store. (~600 tokens)

4. **The local environment's readiness contract** - what the script needs before it can run: local PostgreSQL reachable, a Supabase project reachable, and the media backing and encryption keys actually configured locally. Read the integration README and the render manifest's env-var list to build this checklist. (~700 tokens)

5. **The parent spec's three root causes**, as a checklist to assert against - you already have them from the ticket body; re-read the "Problem Statement" section only, to keep the assertions tied to the real symptoms. (~1.2K tokens)

## Do NOT read

- The production implementations behind the routes. The script is an **external consumer** - if you find yourself importing backend modules into it, the seam is wrong.
- The avatar / photo-resolution / profile-media frontend code (#556, #557).
- The consent, care and health backend internals, `docs/archive/` (the PRD supersedes it), binary assets, migrations.

## Baseline verify (read this before you rely on it)

```bash
npm run test:integration
```

**This is red on the untouched tree at brief time** - do not assume a green starting point. Measured: **7 failed, 20 passed, 211 skipped** in ~6 minutes. All seven failures are migration / schema-bootstrap / directory-index-backfill tests, and the common error is:

```
asyncpg.exceptions.PostgresSyntaxError: cannot insert multiple commands into a prepared statement
```

That is an environment/harness problem in the schema-bootstrap path, not a product defect, and it is **not yours to fix in this slice**. Record it as the starting truth. Your script's own preflight should check PostgreSQL connectivity independently, so a broken bootstrap suite does not block you.

Also note the integration suite is slow (~6 min). Budget for it; do not put it in a tight loop.

## Done-verify (acceptance criteria → commands)

- The script runs end to end against a locally running backend, and its three assertions are independently legible - a partial failure must say _which_ symptom regressed.
- Before #554 / #555 land, assertions 1 and 2 are red and assertion 3 is green. Capture that output on the ticket; it is the evidence the loop actually detects the bugs.
- After #554 / #555 / #557 land, all three are green.
- Repeatability: two consecutive runs with two different throwaway patients both pass - no shared state between runs.
- Not a committed suite entry: `git status` shows it as an untracked or explicitly throwaway file, and `npm run test:unit:*` and `npm run test:integration` are unaffected by it.

## Handoff notes

- **Blocked on #554, #555 and #557.** All three must land before the green run. The red run can start earlier - that is the point of writing it first.
- **This loop is why the parent spec exists in this shape.** Every root cause in it was found by reading real data and real configuration, not by reading the diff. Treat the script as a diagnostic instrument, not a test to satisfy.
- **The interesting failure is the 500, not the error code.** The frontend already handles the ack-required code correctly. The live symptom is a genuine server error from a 500, and the bug is an `int()` coercion one layer below the route - so the script must assert on the **response**, not on a code the facade was supposed to translate.
- **Assertion 2 is the one people fake.** Checking that the object is absent from local disk, or that the endpoint returned 200, does not prove durable storage. It must look in the bucket under the service-role key.
- **Assertion 3 is already green and must stay green.** It is the guard for the landed series fix, not a bug reproduction. If it is red, something regressed.
- **Throwaway patient per run** is what makes the script safe to re-run. Do not reuse an identity across runs - leftover grants from a prior run would mask the first-save behaviour you are trying to observe.
- **Keep it out of CI.** A live-loop script that needs a real Supabase project and a running service belongs in the operator's hands, not in the unit or integration gate.
