# Brief - 488 Patient profile persistence frontend

**Ticket:** #488 · **Parent:** #479 · **Refreshed:** 2026-09-19
**Reading surface:** ~5K tokens (budget 10K) - within budget

## Scope

Wizard Finish persists via the profile client (`PUT /v1/me/profile`) on both hosts; gate/nudges/dashboard hydrate from `GET /v1/me/profile` at login before local-draft fallback; remove the "INTEGRATION POINT - later phase" markers; identity isolation.

AC:

- [ ] Wizard Finish persists via the profile client; the local draft stays the in-flight buffer
- [ ] On login, gate/nudges/dashboard hydrate from `GET /v1/me/profile` before local-draft fallback; saved profile short-circuits the gate
- [ ] INTEGRATION POINT markers removed from the profile components / state
- [ ] Photo/area/emergency-contact optional and unsettable; stored profile reflects exactly what was chosen
- [ ] Two identities on the same browser never share a draft view
- [ ] New copy bilingual en/hi; parity test passes
- [ ] Component/page tests `vi.mock` the profile client + `next/navigation`

## Read-list (in order)

1. `components/patient/profile/ProfileCompletionWizard.tsx`, `ProfileGate.tsx`, `ProfileNudges.tsx` + their `.test.tsx` - the surfaces that gain persistence/hydration (~1K tokens)
2. `lib/profile/profileState.ts` + `app/(patient)/patient/page.tsx` + `app/(patient)/patient/profile/complete/page.tsx` - the draft/in-flight buffer model + hosts (~800 tokens)
3. `lib/api-base.ts` + `lib/request.ts` + `lib/api-errors.ts` + `lib/auth/api.ts` + `lib/auth/AuthContext.tsx` - the fetch/authedFetch + error-envelope + login flow to hook hydration into (~900 tokens)
4. `lib/i18n/dictionaries.ts` profile block + `dictionaries.test.ts` parity walk (~500 tokens)

## Do NOT read

- Doctor console, care module, pick flow, backend route code, `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend`
- Known pre-existing (unrelated): frontend homepage parity fails on one Daltonganj string; backend `test_app_shell` demo/OTP + `test_contract_check` fail under the local `DEFAULT_APP_ENVIRONMENT="dev"` override in `apps/backend/app/config.py`.

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:frontend` - profile gate/wizard hydrate + persist tests, parity
- `npm run typecheck`

## Handoff notes

- Blocker #482 must be merged (provides PUT/GET /v1/me/profile and the typed "not set" shape).
- The gate kind mapping (`basics`/`area`, `evaluateGate`) stays as-is; hydration only decides whether the gate fires.
- Language/`setLang` behavior is unchanged; `preferred_language` persists server-side but the app locale keeps its own store.
