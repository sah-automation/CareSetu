# Brief - T16 Frontend: voice recorder page

**Ticket:** #360 · **Parent:** #344 · **Refreshed:** 2026-09-08
**Reading surface:** ~8K tokens (budget 10K) - within budget

## Scope

A patient can record symptoms by voice: a large, obvious mic target, a live duration counter capped at 180 seconds, playback and re-record before submit to fix a bad take, at most 3 voice attempts before being asked to type instead, and a plain-language prompt when audio is too short or unclear - never a silent proceed. Upload auto-retries up to 3 times with backoff on a slow connection and the submit shows an in-button Structuring state, no blocking spinner. All in English and Hindi per the prototype.

Acceptance criteria:

- [ ] Recording/playback/pending/poor-audio states and the 3-attempt cap work per prototype (intake-voice)
- [ ] Audio under the 3-second floor triggers the re-record-or-type prompt wired to the server unusable-audio signal
- [ ] Upload retries up to 3x with backoff (no lost input on a flaky 4G connection)
- [ ] Submit shows in-button Structuring pending, then links to the pre-summary review
- [ ] Bilingual copy passes the i18n parity test

## Read-list (in order)

1. `prototype/phase-7-8/intake-voice.html` + `prototype/phase-7-8/BUILD-PLAN.md` Part 2 - states, duration cap, 3-attempt ladder, copy (~2.5K)
2. The intake client + page conventions from T15 - submit/upload/re-record methods and shell conventions (~1.5K)
3. The upload/re-record route contract from T12 - request shapes and the unusable-audio signal (~1K)
4. `apps/frontend/src/lib/i18n/dictionaries.ts` + `dictionaries.test.ts` - bilingual strings and parity gate (~2K)

## Do NOT read

- `docs/archive`
- backend internals beyond the route contract
- text-intake and review pages (except their build-plan parts)

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` - 687 pass with 1 known unrelated flake: `(operator)/operator/verification/[partner_id] > renders partner profile on load` times out intermittently (verified 2026-09-08); re-run if only that test fails
- `npm run typecheck` - clean (verified 2026-09-08)

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:frontend`
- `npm run check:pages`

## Handoff notes

- The 3-second floor is enforced and surfaces a plain-language re-record-or-type prompt (wired to the server unusable-audio signal) - never a silent proceed.
- Upload retry with backoff must not lose a partial capture on flaky connections.
- In-button Structuring state on submit (no blocking spinner), then advance to pre-summary review.
