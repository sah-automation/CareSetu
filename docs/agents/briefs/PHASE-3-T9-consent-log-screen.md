# Brief - T9 Consent log screen

**Ticket:** #218 · **Parent:** #209 PHASE-3 · **Refreshed:** 2026-08-24
**Reading surface:** ~6K tokens (budget 10K) - within budget

## Scope

The patient's control panel for sharing: My Consent Log shows every consent interaction - pending requests first, then live and revoked grants - each with expandable receipts (who asked, what scope, when, which version). An active grant revokes with one inline confirm right on the object; revocation stops all future access immediately while the revoked grant stays in the log with its receipts, with plainly stated copy that what a counterparty already saw is not erased. A "what has left your record" slice lists every disclosure: what, when, to whom, under which version. Fully bilingual EN/HI. Prototype `consent-log.html` is the binding visual spec.

Acceptance criteria: see #218 body verbatim.

## Read-list (in order)

1. `prototype/phase-3/consent-log.html` - binding visual/copy spec (~2K)
2. `prototype/PLAN.md` review outcomes relevant to this screen (~0.7K)
3. List-consents + revoke + egress-listing endpoint contracts as T3/T5 landed them (~1K)
4. Dictionaries + LangContext pattern (~0.8K)
5. Shared dashboard chrome conventions from existing patient pages (~0.8K)
6. Existing vitest component-test patterns (~0.5K)

## Do NOT read

- check_consent cache internals; gateway middleware; backend modules beyond endpoint contracts; `docs/archive/`.

## Baseline verify (must pass before the first edit)

Recorded green on 2026-08-24: lint; typecheck; frontend units 442 passed.

For this ticket: `npm run lint`, `npm run typecheck`, `npm run test:unit:frontend`.

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:frontend` (pending-first ordering, receipt expansion, inline-confirm revoke, revoked-stays-visible + stop-forward copy, egress slice, bilingual suites green)
- `npm run typecheck`

## Handoff notes

- Revoked grants are never hidden or pruned - history survives revocation (story #18); receipts stay expandable.
- The stop-forward statement is acceptance-level copy, not decoration: "revocation does not erase what was already seen" must be plainly visible on revoked objects.
- Pending requests sorted above everything (story #15).
- The Share entry point hosting T10's sheet lives here - leave a clean mount point for T10.
