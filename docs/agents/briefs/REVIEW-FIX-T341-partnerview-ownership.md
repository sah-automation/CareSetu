# Brief - 341 Review fix: relocate PartnerView to registration_models.py (US10)

**Ticket:** #341 · **Parent:** #339 · **Refreshed:** 2026-09-07
**Reading surface:** ~4K tokens (budget 10K) - within budget

## Scope

The `PartnerView` model lives in `common_models.py`, a file that contains only this one model. Move it to `registration_models.py` so the registration sub-facade owns it (US10), update all importers, keep the coordinator's re-export, and delete the now-empty `common_models.py`.

Acceptance criteria (from #341):

- [ ] `PartnerView` defined in `modules/partner/registration_models.py`.
- [ ] `common_models.py` deleted (no dead import targets).
- [ ] `facade.py`, `registration_facade.py`, `operator_gate_facade.py`, `credential_intake_facade.py` import `PartnerView` from `registration_models`.
- [ ] `facade.py` re-exports `PartnerView` so routes importing from `modules.partner.facade` still resolve.
- [ ] `npm run typecheck`, `npm run test:unit:backend`, `npm run lint` pass.

## Read-list (in order)

1. `apps/backend/modules/partner/common_models.py` - the 11-line file holding `PartnerView` (the only content).
2. `apps/backend/modules/partner/registration_models.py` - the target module (`RegisterPartnerResult`, `PartnerMeView`); add `PartnerView` here (~1K).
3. Import sites: `apps/backend/modules/partner/facade.py:107`, `registration_facade.py:38`, `operator_gate_facade.py:43`, `credential_intake_facade.py:45` (~1.5K).
4. `apps/backend/modules/partner/adapters/routes.py:46-59,382,389,466,475,519,527` - route consumers importing `PartnerView` from `modules.partner.facade` (must keep working via re-export).

## Do NOT read

- domain layer, schema layer, outbox, IAM module, partner tests, `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `npm run typecheck`
- `npm run test:unit:backend`
- `npm run lint`

## Done-verify (acceptance criteria -> commands)

- `npm run typecheck`
- `npm run test:unit:backend`
- `npm run lint`
- Grep `common_models` across the repo - no hits.
- `from modules.partner.facade import PartnerView` still resolves (routes unchanged).

## Handoff notes

- Verify during implementation whether `credential_intake_facade.py` actually uses `PartnerView`; if not, drop its import entirely.
- `facade.py` re-export must be preserved exactly - routes and tests import `PartnerView` from `modules.partner.facade`.
- Parent for all review-fix briefs is #339. Concept drawn from review finding F3.
