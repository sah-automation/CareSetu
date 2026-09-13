# Brief - T17 Frontend: text intake page

**Ticket:** #361 · **Parent:** #344 · **Refreshed:** 2026-09-08
**Reading surface:** ~7K tokens (budget 10K) - within budget

## Scope

A patient can type their symptoms in a prominent large textbox capped at 2000 characters, with a hint that Hindi and English are both accepted, and an optional voice-note attach - a doctor-only audio artifact that is stored for the doctor to listen to and never fed to the structuring pipeline. Submit shows the same in-button Structuring state and continues to the pre-summary review. Bilingual per prototype.

Acceptance criteria:

- [ ] The textarea is prominent with the 2000-character cap enforced in page
- [ ] The optional voice attach is present, non-blocking, and posts as a doctor-only audio artifact (never structuring input)
- [ ] Submit -> in-button Structuring pending -> continuation to pre-summary review
- [ ] Bilingual copy passes the i18n parity test

## Read-list (in order)

1. `prototype/phase-7-8/intake-text.html` + `prototype/phase-7-8/BUILD-PLAN.md` Part 3 - layout, cap, doctor-only attach semantics, copy (~2K)
2. The intake client + page conventions from T15 - esp. one-mode-per-intake and doctor-only artifact rules (~1.5K)
3. `apps/frontend/src/lib/i18n/dictionaries.ts` + `dictionaries.test.ts` - bilingual strings and parity gate (~2K)

## Do NOT read

- `docs/archive`
- backend internals beyond the route contract
- voice and review pages (except their build-plan parts)

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` - 687 pass with 1 known unrelated flake: `(operator)/operator/verification/[partner_id] > renders partner profile on load` times out intermittently (verified 2026-09-08); re-run if only that test fails
- `npm run typecheck` - clean (verified 2026-09-08)

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:frontend`
- `npm run check:pages`

## Handoff notes

- The voice-note attach is doctor-only: stored for the doctor, never fed to the structuring pipeline; it must be non-blocking.
- 2000-char cap enforced in page (server also caps per T07/T08).
- Bilingual hint: Hindi and English are both accepted.
