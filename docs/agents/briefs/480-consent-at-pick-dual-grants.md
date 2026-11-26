# Brief - 480 Consent-at-pick dual grants

**Ticket:** #480 · **Parent:** #479 · **Refreshed:** 2026-09-19
**Reading surface:** ~4.5K tokens (budget 10K) - within budget

## Scope

`pick-doctor` records both `consultations` and `prescriptions` standing grants atomically in the same transaction as the assignment (either both or neither). Grant lineage / consent version semantics and `check_consent` fail-closed behaviour unchanged. Pick-step consent sheet copy states both scopes (en/hi).

AC:

- [ ] pick-doctor records both grants atomically with the assignment in the same single write transaction
- [ ] Grant-leg failure prevents the pick assignment persisting (no partial grant/pick)
- [ ] `PickDoctorResult` consumers still work; `check_consent` identical
- [ ] Consent sheet copy states consultations + prescriptions (en/hi)
- [ ] Route + facade lifecycle tests cover both-grants and either-neither

## Read-list (in order)

1. `modules/intake/facade.py` `pick_doctor` (L1054+, today `record_scope = "consultations"` at L1095) + the SAME-transaction `grant_consent_on` call (L1124) - the exact seam to extend (~800 tokens)
2. `modules/consent/facade.py` `grant_consent_on` (L552) + `grant`/version semantics around it - what one double-grant call must do (~600 tokens)
3. `intake_models.py` `PickDoctorResult` (L290-305) - the response contract consumers rely on (unchanged)
4. `tests/unit/test_pick_doctor_facade.py` + `tests/unit/test_consent_*` - the test patterns for atomic grant (L~) (~800 tokens)
5. `components/pick/PickConsentSheet.tsx` + `lib/i18n/dictionaries.ts` pick block + parity test - the sheet copy to update (~600 tokens)

## Do NOT read

- care module, media upload, pre-summary pipeline, `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- Known pre-existing (unrelated to this ticket): `test_app_shell` demo/OTP tests + `test_contract_check` fail under the local `DEFAULT_APP_ENVIRONMENT="dev"` override in `apps/backend/app/config.py`; frontend homepage parity fails on one Daltonganj string.

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend` - pick-doctor returns/records both grants; failure = neither
- `npm run test:unit:frontend` - sheet copy + parity
- `npm run typecheck`

## Handoff notes

- pick-doctor already counts toward rate limiting; the second grant is in the same single write, so no new rate-limit surface (#479 D-B).
- The `prescriptions` scope is what the AI-draft consent-gated read (ticket #487) needs to pass - this lands before/with it.
