# Brief - 04 Access-history API resolves and exposes counterparty display names

**Ticket:** #668 · **Parent:** #662 · **Refreshed:** 2026-10-08
**Reading surface:** ~8.5K tokens (budget 10K) - within budget

## Scope

The access-history API carries a resolved counterparty display name: the composition-root counterparty display-name resolver (branded AI label first, then doctor partner-profile practice name, lab/chemist to null) is also bound into the health facade at composition time, and the access-history read resolves a nullable `actor_display_name` for every surviving non-self row. The health module stays name-agnostic behind the module-isolation boundary the consent binding established. Failures degrade to null with a type-only warning, never PHI; patient-type actors never resolve to a name.

Acceptance criteria:

- [ ] The composition root binds the existing counterparty display-name resolver into the health facade, following the consent binding prior art
- [ ] The access-history entry model gains a nullable `actor_display_name` alongside the existing actor id/type, scope, timestamp, denied, and denial reason fields
- [ ] The access-history read resolves the name: doctor rows resolve the practice name, unresolvable or patient-type rows degrade to null without erroring
- [ ] Binding + resolution integration tests follow the consent display-name binding prior art; unit tests pin the row-mapping of the new field
- [ ] `npm run test:unit:backend`, `npm run test:integration`, `npm run lint`, `npm run typecheck` pass

## Blocked by

#665 (Record access history stops recording owner reads) - same read path and same test files; the row set and seeding must be settled first.

## Read-list (in order)

1. Spec #662 §Solution "Access history: no self rows, real names" - name-resolution Implementation Decisions bullets and Testing Decisions (backend half); user stories 16-18, 23 (~1.5K)
2. Composition root: `_build_counterparty_display_name_resolver` and the `AI_INTAKE_COUNTERPARTY_DISPLAY_NAME` constant, plus its binding into `ConsentFacade` in `create_app` (apps/backend/app/main.py) - the exact prior art to mirror for `HealthFacade` (~1.5K)
3. Consent facade resolver seam: the `CounterpartyDisplayNameResolver` type alias, the constructor kwarg, and `_display_name` (degrade-to-null, never raises) - the contract the health binding must conform to (~1K)
4. `HealthFacade.query_access_history` + `AccessHistoryEntry` + `get_access_history` - where resolution runs and where the field lands (post-ticket #665 shape) (~1.2K)
5. Binding prior art tests: `tests/unit/test_consent_counterparty_display_name_binding.py` and `tests/integration/test_consent_counterparty_display_name_binding.py` - rule order and end-to-end shape to copy (~2.5K)
6. `tests/unit/test_access_history_facade.py` and `tests/integration/test_patient_access_history_api.py` - the seams to extend with the new field (post-#665 state) (~1.8K)

## Do NOT read

- Frontend rendering (ticket #670 owns the label fallback)
- The owner-read write stop internals beyond what the read path needs (done in #665)
- Egress log, consent state machine, partner facade beyond `get_provider_profile`'s role in the resolver
- `docs/archive/`

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - 2919 passed (2026-10-08)
- `npm run test:integration` - baseline: 263 passed, 1 pre-existing failure (`test_consent_check_gate.py::test_p95_latency_under_50ms`, environment-sensitive - do not blame this change for it)
- `npm run lint`, `npm run typecheck` - passed

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend` - row-mapping of the new field pinned
- `npm run test:integration` - a doctor consented read produces a row carrying a resolved display name; a cross-patient denied row survives with no name leak; resolver binding rule order holds
- `npm run lint`, `npm run typecheck`

## Handoff notes

- Resolution rules (spec): branded AI label (id `intake-ai`) -> doctor -> partner profile practice name -> lab/chemist -> null; any miss/failure -> null with a type-only warning, never PHI. The AI-intake branding rule is an id check before any type parse.
- Health module stays name-agnostic: the resolver is injected at composition root exactly like the consent binding - no cross-module imports inside the module (module isolation rule).
- Patient-type actors (cross-patient denied rows) must resolve to null - never disclose another person's identity on the patient's behalf (stories 21-22).
- Requires ticket #665 merged first; integration baseline notes from #665's brief apply.
