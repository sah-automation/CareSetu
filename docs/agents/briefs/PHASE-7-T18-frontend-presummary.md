# Brief - T18 Frontend: pre-summary review page (clean + low-confidence)

**Ticket:** #362 · **Parent:** #344 · **Refreshed:** 2026-09-08
**Reading surface:** ~8K tokens (budget 10K) - within budget

## Scope

A patient can see and correct the AI draft pre-summary: the structured fields with the honesty cue "AI draft - doctor will verify" (never "AI diagnosis"), a structuring-confidence value with a light indicator, and - for low-confidence results - a calm amber notice that the doctor will need to check, never alarming. The patient can edit fields as corrections and continue toward booking a consultation. Bilingual per prototype.

Acceptance criteria:

- [ ] Clean variant shows the structured fields, confidence value + indicator, honesty cue, and edit/confirm
- [ ] Low-confidence variant shows the calm amber (warn, never red) doctor-must-check notice and the forced-review framing
- [ ] Patient edits persist via the save-edits route and are shown as corrections
- [ ] Continuation affordance toward consultation booking is present
- [ ] Bilingual copy passes the i18n parity test

## Read-list (in order)

1. `prototype/phase-7-8/pre-summary-review.html` + `pre-summary-low-confidence.html` + `prototype/phase-7-8/BUILD-PLAN.md` Part 4 - both variants, honesty cue, amber notice, copy (~2.5K)
2. The get/save-edits client and pre-summary DTO from T15 - get_pre_summary + save-edits methods and shape (~1.5K)
3. `docs/design/ui-blueprint.md` honesty-cue section - the "AI draft - doctor will verify" wording rule (~1K)
4. `apps/frontend/src/lib/i18n/dictionaries.ts` + `dictionaries.test.ts` - bilingual strings and parity gate (~2K)

## Do NOT read

- `docs/archive`
- backend internals beyond the route contract
- voice/text intake pages (except their build-plan parts)

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` - 687 pass with 1 known unrelated flake: `(operator)/operator/verification/[partner_id] > renders partner profile on load` times out intermittently (verified 2026-09-08); re-run if only that test fails
- `npm run typecheck` - clean (verified 2026-09-08)

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:frontend`
- `npm run check:pages`

## Handoff notes

- Honesty cue is fixed copy: "AI draft - doctor will verify" - never "AI diagnosis". Low confidence uses calm amber (warn), never red, with the forced-review framing (per ADR-0001 / pre-summary glossary).
- Patient edits persist via the save-edits route and render as corrections.
