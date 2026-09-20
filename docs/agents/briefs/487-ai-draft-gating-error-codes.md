# Brief - 487 AI draft gating + distinct backend error codes

**Ticket:** #487 · **Parent:** #479 · **Refreshed:** 2026-09-19
**Reading surface:** ~5K tokens (budget 10K) - within budget

## Scope

Backend gating so that on the mock provider a `PrescriptionPending` care case with doctor input present and a `prescriptions`-scope grant live can produce an AI draft (`source=ai_draft`); and each backend refusal (consent denied / no doctor input / cap reached / closed / not-found) answers the shared error envelope with its own distinct code. Drafting cap, revision-freeze, verification declaration, `edited_yn` preserved. Manual authoring still works with no consent/input.

AC:

- [ ] Mock provider: `source=ai_draft` succeeds when doctor input exists + `prescriptions`-scope grant live
- [ ] Each refusal surfaces its own distinct code through the shared envelope (not the generic catch-all)
- [ ] Manual authoring (`source=manual`) works with no consent and no doctor input
- [ ] Drafting cap (max 2 AI drafts) + approval/verification semantics unchanged
- [ ] Route + lifecycle tests cover success and every distinct code

## Read-list (in order)

1. `modules/care/adapters/routes.py` `POST /cases/{case_id}/rx/draft` (L297) + `RxDraftRequest` (L120) - the boundary the codes surface through (~400 tokens)
2. `modules/care/rx_facade.py` `create_rx_draft` - the consent-gated history read (`RX_DRAFT_HISTORY_SCOPE = "prescriptions"`, L74), the doctor-input check (L810-816), where each refusal raises (~1.2K tokens)
3. The shared error-envelope mechanism (`app/gateway` or the route error handler + `error-handling-observability.md`) - how care route failures map to codes today; where the current catch-all lives (~700 tokens)
4. `modules/intake/adapters/ai_provider_mock.py` `draft_rx` (L108) - the demo path that must succeed (~400 tokens)
5. `modules/consent/facade.py` `check_consent` (L806) + `ConsentDecision` - the gate that decides consent denied (~600 tokens)
6. `tests/unit/test_care_routes.py` + `tests/unit/test_care_lifecycle_integration.py` (the `MockAiProvider` + faked-engine walk) - test patterns (~800 tokens)

## Do NOT read

- openai_compatible `draft_rx` (out of scope), frontend, intake capture/pipeline, `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- Known pre-existing (unrelated): `test_app_shell` demo/OTP tests + `test_contract_check` fail under the local `DEFAULT_APP_ENVIRONMENT="dev"` override in `apps/backend/app/config.py`; frontend homepage parity fails on one Daltonganj string.

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend` - new gating + distinct-code tests, existing lifecycle still green
- `npm run typecheck`

## Handoff notes

- Blocker #480 (dual grants) must be merged - the `prescriptions`-scope read can only pass once the grant exists.
- Real-provider drafting is out of scope; the OpenAI-compatible `draft_rx` stub stays as-is.
- The frontend message mapping is ticket #490 - this ticket only makes the codes exist at the backend boundary.
