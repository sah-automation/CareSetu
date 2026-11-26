# Brief - T05 Session payload gains phone field (D4)

**Ticket:** #196 · **Parent:** #191 PHASE-2.6 · **Refreshed:** 2026-08-22
**Reading surface:** ~3.5K tokens (budget 10K) - within budget

## Scope

The phase's only backend delta (decision D4): the protected session endpoint response schema gains an additive `phone` field (the caller's E.164 phone) alongside subject id and roles, so the account menu can render a truthful identity. Error envelope, RBAC scoping, rate limiting untouched; the frontend derives its user id from the subject id as today.

Mechanically: handler resolves `phone_e164` from the identity table by the principal's subject id (one-column lookup). Update the strict exact-body contract-test assertion; mirror the new field into the frontend auth API client interface so the OpenAPI-vs-frontend contract gate stays green.

Acceptance criteria: see #196 body verbatim.

## Read-list (in order)

1. Session/me route + response schema in `apps/backend/app/main.py` - `MeResponse` fields (`subject_id`, `roles`) and the handler behind `require_patient` (~0.7K tokens)
2. IAM identity model (`modules/iam/schema/models.py`) - `phone_e164` column + uniqueness on `iam_identities` (~0.4K)
3. Gateway contract tests (`tests/unit/test_gateway.py`) - the exact-body assertion that must gain `phone`; admit/deny cases around it (~0.5K)
4. Contract-check script (`scripts/contract_check.py`) - how it parses the frontend client interface against backend OpenAPI (~1K)
5. Frontend auth API client interface (`lib/auth/api.ts`) - where the mirrored field lands (~0.9K)

## Do NOT read

- Other backend modules, `docs/archive/`, prototype views, frontend components.

## Baseline verify (must pass before the first edit)

Recorded green on 2026-08-22:

- `npm run test:unit:backend` - 654 passed
- `npm run typecheck` - clean (mypy strict included)
- `npm run check:contract` - OK: 5 auth endpoints match OpenAPI
- `npm run lint` - all hooks pass

## Done-verify (acceptance criteria → commands)

- Updated contract test asserts `phone` present; admit/deny cases unchanged and green
- Baseline four commands green after the change

## Handoff notes

- Additive only: no field renames, no removals - older frontend builds keep working.
- The principal already carries subject_id (= identity id), so the phone lookup needs no new auth plumbing.
- Mirror the field as optional-tolerant on the frontend read path if the client interface types it strictly - decide per the existing interface style.
