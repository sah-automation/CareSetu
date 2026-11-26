# Brief - 446 FE prefactor: care API client + idempotency helper + i18n scaffold

**Ticket:** #446 · **Parent:** #438 · **Refreshed:** 2026-09-16
**Reading surface:** ~3.7K tokens (budget 10K) - within budget

## Scope

Frontend foundation the console tickets build on: a care-plan API client module alongside the existing per-module clients, a shared idempotency-key header helper for care mutations, and the `doctorConsole`/pick i18n block skeleton in en+hi with parity-test coverage.

AC:

- [ ] Care API client module exists following the existing per-module client pattern
- [ ] Care mutations can set the idempotency-key header through the shared helper, without each page re-implementing it
- [ ] en/hi dictionaries gain the `doctorConsole` and pick blocks with skeleton strings; parity test passes
- [ ] Care client test covers the header emission shape under mock transport

## Read-list (in order)

1. Existing per-module clients in `lib/` (intake, consent, directory, partner) + `lib/request.ts` fetch/guard utilities - the pattern and shared helpers to mirror and extend (~1400 tokens)
2. `app/gateway/idempotency.py` idempotency-key contract (`run_idempotent`) - the header name/shape the helper must emit (~500 tokens)
3. `lib/i18n/dictionaries.ts` en + hi structure and the dictionary-parity test - where the new blocks go and how parity is checked (~700 tokens)
4. An existing API-client vitest test (mock transport, assert shape/headers) - the test pattern to copy (~600 tokens)
5. Issue #438 "Frontend API client discipline" decision (~200 tokens)

## Do NOT read

- Backend route internals, pages/workspace (the consumers are later tickets #449-#453), care case UI, `docs/archive/`, blueprint/PRD internals.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` - currently green (71 files, 801 tests).

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:frontend` - new care-client and idempotency-helper tests pass; parity test passes with the new blocks.

## Handoff notes

- This is a pure additive prefactor - do not repoint existing clients or pages; later tickets migrate page calls onto these helpers.
- Every new string added here must exist in both en and hi (parity is CI-enforced).
