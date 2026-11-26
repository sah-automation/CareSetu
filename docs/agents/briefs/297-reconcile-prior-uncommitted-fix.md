# Brief - 297 Reconcile prior uncommitted fix for partner registration 409

**Ticket:** #297 · **Parent:** partner registration 409 fix plan · **Refreshed:** 2026-09-04
**Reading surface:** ~3K tokens novel (budget 10K) - within budget, config revert + split change

## Scope

Revert the hazardous `DEFAULT_APP_ENVIRONMENT` change, split out the orthogonal mobile-required validation change, and discard the ineffective wizard ordering edit. Leave a clean working tree ready for the partner session fix.

- [ ] `apps/backend/app/config.py` DEFAULT_APP_ENVIRONMENT restored to `"production"`
- [ ] Mobile-required validation change committed separately (or reverted)
- [ ] Wizard ordering edit in ProviderRegisterWizard.tsx discarded (superseded by plan)
- [ ] `git diff` shows only this ticket's intended changes
- [ ] `npm run lint` and `npm run typecheck` pass

## Read-list (in order)

1. **`apps/backend/app/config.py`** - lines 152-157, 178-183, 224-230, 282: understand why `DEFAULT_APP_ENVIRONMENT = "dev"` is hazardous (SMS providers gated, environment detection wrong). The current uncommitted change sets it to `"dev"`, must revert to `"production"`.
2. **`apps/frontend/src/components/auth/staff/providerRegisterState.ts`** - the mobile-required validation change (concern 2 from plan). Understand what was changed and decide: commit as separate change or revert.
3. **`apps/frontend/src/components/auth/staff/providerRegisterState.test.ts`** - tests for the mobile-required change, if keeping it.
4. **`apps/frontend/src/components/auth/staff/ProviderRegisterWizard.tsx`** - the wizard ordering edit (concern 1 from plan). This must be discarded; the plan's final sequence will handle it in #298.
5. **`apps/frontend/src/lib/i18n/dictionaries.ts`** - any i18n changes related to mobile-required copy.

## Do NOT read

- `modules/iam/session_facade.py`, `modules/iam/facade.py`, `modules/iam/adapters/routes.py` (backend changes belong to #298)
- `docs/plans/phase5-frontend-gap-plan.md`, `docs/archive/`
- Other frontend API clients, partner/audit modules

## Baseline verify (must pass before the first edit)

- `git diff --stat` to see current uncommitted changes
- `npm run lint`
- `npm run typecheck`

## Done-verify (acceptance criteria -> commands)

- `git diff apps/backend/app/config.py` is empty (default restored to `"production"`)
- Mobile-required change is in its own commit or reverted
- `npm run lint` - clean
- `npm run typecheck` - clean
- `git diff` shows only this ticket's intended changes

## Handoff notes

- The config.py revert is urgent - if this line ships and a prod/staging deploy misses the env var, SMS silently stays on mock.
- The mobile-required change is internally consistent and low-risk, but it's a product-behavior change, not a bug fix. Recommend committing it separately before or after the 409 fix.
- The wizard ordering edit must be discarded entirely - #298 will apply the correct sequence with `issuePartnerSession`.
- Commit only this ticket's files; leave the backend/frontend changes for #298.
