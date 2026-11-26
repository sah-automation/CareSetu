# Brief - 01 Consent-at-pick grants all three record scopes atomically

**Ticket:** #663 · **Parent:** #662 · **Refreshed:** 2026-10-08
**Reading surface:** ~9.5K tokens (budget 10K) - within budget

## Scope

Picking a doctor becomes the patient's single deliberate multi-grant moment for three record scopes: the consent-at-pick seam widens its scope set from `consultations` + `prescriptions` to also include `health_background`, so all three standing grants are minted on the caller's open connection inside the same transaction as the doctor assignment - either all three grants and the assignment exist, or none do. The pick result contract continues to report the `consultations` grant only. Post-commit consent-cache invalidation covers all three scopes. Docs naming the dual-grant scope set are updated to name three scopes.

Acceptance criteria:

- [ ] The pick transaction mints standing grants for `consultations`, `prescriptions`, and `health_background` alongside the doctor assignment; a grant failure aborts the pick (all-or-nothing preserved)
- [ ] Post-commit cache invalidation runs for all three scopes
- [ ] The pick response contract is unchanged (still reports the `consultations` grant)
- [ ] Unit tests at the existing intake-facade seam assert the three grants, the abort-on-failure path, and the three invalidations; existing pick route contract tests stay green
- [ ] Docs naming the dual-grant scope set (glossary standing-grant entry, consent-at-pick module spec, and any other doc naming the two scopes) now name three scopes
- [ ] `npm run test:unit:backend`, `npm run lint`, `npm run typecheck` pass

## Read-list (in order)

1. Spec #662 §Solution "Consent-at-pick widening" (all bullets), user stories 1-13, Implementation Decisions, Testing Decisions - the contract, including what must NOT change (response shape, first-save one-shot rule) (~2.5K)
2. CONTEXT.md glossary entries "standing grant" and "first-save acknowledgment" - the vocabulary to update and the one-shot rule to preserve (~0.5K)
3. `docs/architecture/internal-modules.md` MOD-004 §3.4 consent-at-pick seam + the §4.1 sync-matrix pick row - the module spec that documents the seam (~1K)
4. `IntakeFacade.pick_doctor` (apps/backend/modules/intake/facade.py) - the local `record_scopes` tuple, the `grant_consent_on` call loop inside the transaction, the post-commit `invalidate_consent_cache` loop, and the by-name `consultations` response selection (~2K)
5. `ConsentFacade.grant_consent_on` / `_grant_on_connection` (apps/backend/modules/consent/facade.py) - callee semantics: takes a caller-opened connection, opens no transaction (~0.5K)
6. `RECORD_SCOPES` in consent domain state machine - confirm `health_background` already exists, no enum change (~0.2K)
7. `tests/unit/test_pick_doctor_facade.py` - prior-art dual-grant assertions (await_args_list over the consent facade, commit-exit, invalidation calls, parametrized abort-on-failure) to extend from two to three (~2K)
8. Pick section of `tests/unit/test_patient_intake_routes.py` - route contract shape to leave untouched (no grant assertions there) (~0.8K)

## Do NOT read

- The health module first-save acknowledgment path beyond the glossary entry - it is scope-set-independent and needs no change
- Doctor console / patient-detail gating - the health-background gate is already scope-keyed
- The consent state machine beyond `RECORD_SCOPES`, egress log, cache rules (ADR-0004)
- Frontend pick sheet / dictionaries (ticket #664 owns disclosure copy)
- `docs/archive/`

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - 2919 passed (2026-10-08)
- `npm run lint` - passed
- `npm run typecheck` - passed

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend` - three-grant assertions + abort + three invalidations green; route contract unchanged
- `npm run lint`, `npm run typecheck`
- Grep docs for the dual-scope phrasing to confirm no doc still names only two scopes

## Handoff notes

- Prior art brief for the original dual grant: `docs/agents/briefs/480-consent-at-pick-dual-grants.md`; pick write: `docs/agents/briefs/443-patient-pick-doctor-consent-write.md`.
- Post-commit invalidation already iterates the granted scope set - widening the tuple automatically widens invalidation; do not restructure it (ADR-0004 discipline unchanged).
- The response contract selects `consent_granted["consultations"]` by name - keep it that way (user story 12).
- Route registration and pick route contract tests must not change.
- Ticket #664 (disclosure copy) is independent; sequence either way.
