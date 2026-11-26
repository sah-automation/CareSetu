# Brief - 490 Prescription-pending workspace empty state

**Ticket:** #490 · **Parent:** #479 · **Refreshed:** 2026-09-19
**Reading surface:** ~5.5K tokens (budget 10K) - within budget

## Scope

The case workspace `PrescriptionPending` empty state becomes a real doctor-input capture surface: voice note, photo, typed addendum (posting `media_ref` to doctor-input via `submitDoctorInput`), "Request AI draft" enabled only after doctor input exists, "type prescription yourself" for manual authoring (`source=manual`). Backend refusal codes map to specific in-language messages (consent denied / no doctor input / cap / closed / not-found); catch-all stays only as fallback. `submitDoctorInput` in the care API client becomes reachable.

AC:

- [ ] `PrescriptionPending` with no draft renders voice/photo/typed-addendum capture; uploads use the doctor media route and send `media_ref` to doctor-input
- [ ] "Request AI draft" disabled until doctor input exists; succeeds on the mock provider and surfaces the draft
- [ ] "Type prescription yourself" opens the existing manual editor (`createRxDraft source=manual`) and works with no consent/draft
- [ ] Refusal codes -> specific in-language messages; catch-all only as fallback
- [ ] Drafting cap + approval gates visibly preserved
- [ ] Tests: case-workspace page tests mock care client (`submitDoctorInput`, `createRxDraft`, doctor media upload) + error mapping; bilingual parity

## Read-list (in order)

1. `app/(doctor)/doctor/cases/[caseId]/page.tsx` - the prescription empty state (L582-592), `handleRequestDraft` (L242-266), editor section, rejected/redraft states (~2K tokens for the relevant slices)
2. `lib/care/api.ts` - `submitDoctorInput` (L219-233), `createRxDraft`, `saveRxRevision`, working-prescription view model (~800 tokens)
3. `lib/api-errors.ts` (`parseErrorEnvelope`) + `lib/request.ts` + `lib/idempotency.ts` - code mapping + idempotency header discipline (~500 tokens)
4. The doctor media upload client (from ticket #481) - how the voice/photo ref is produced (~400 tokens)
5. `lib/i18n/dictionaries.ts` `caseWorkspace` block + parity test (~600 tokens)
6. Existing case-workspace page test - the `vi.mock` pattern to extend (~700 tokens)

## Do NOT read

- Intake/pick flows, consent internals, backend route code (the seams are already typed), `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend`
- Known pre-existing (unrelated): frontend homepage parity fails on one Daltonganj string; backend `test_app_shell` demo/OTP + `test_contract_check` fail under the local `DEFAULT_APP_ENVIRONMENT="dev"` override in `apps/backend/app/config.py`.

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:frontend` - empty-state capture, input gating, manual authoring, error-code mapping, parity
- `npm run typecheck`

## Handoff notes

- Blockers #480, #481, #487 must land (dual grants, upload route, distinct codes).
- Manual authoring is load-bearing for ADR-0015 ("an AI outage never strands a patient's visit") - it must be reachable from the UI.
- The error-code mapping is the core fix for the confusing "Could not generate the AI draft", not cosmetic.
