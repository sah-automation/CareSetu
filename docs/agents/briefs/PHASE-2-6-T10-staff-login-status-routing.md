# Brief - T10 Staff login, status screens & post-login routing

**Ticket:** #201 · **Parent:** #191 PHASE-2.6 · **Refreshed:** 2026-08-22
**Reading surface:** ~7.5K tokens (budget 10K) - within budget

## Scope

Split-auth entry surfaces for staff, pages only (Phase 5 fills the backends):

- **Staff login** (`/staff/login`): composition visually and functionally distinct from the patient OTP wizard - email + password with show/hide, forgot-password link placeholder, error-envelope presentation keyed on stable codes, conditional MFA step slot rendered only when enrolled (never functional this phase).
- **Status screens:** pending/under-verification and rejected-with-reason screens reachable post-login, resubmission edge stubbed.
- **Post-login routing:** landing determined by the login surface used (blueprint §4.5 against the current session model); scoped role picker only for multi-staff-role accounts; interim choose-role entry retained until Phase 5 replaces staff auth.
- All submits give honest not-yet-available feedback naming Phase 5; `/staff/login` joins the page-budget measurement.

Acceptance criteria: see #201 body verbatim.

## Read-list (in order)

1. Prototype views `staff-login.html`, `partner-pending.html`, `partner-rejected.html`, `post-login-routing.html` - binding visual/copy specs (~3.5K tokens)
2. UI blueprint §4.x staff-surface sections + §4.5 routing rules (~1.5K)
3. API standard's error envelope + stable codes section - what "keyed on stable codes" means concretely (~1K)
4. Ticket 07's guard carve-outs + ticket 08's account menu/PageHeader surfaces - where these pages mount (~1K)

## Do NOT read

- Provider-registration prototype view (ticket 11), backend staff-auth modules (Phase 5), `docs/archive/`.

## Baseline verify (must pass before the first edit)

Recorded green on 2026-08-22: lint, typecheck, frontend units 72 tests.

## Done-verify (acceptance criteria → commands)

- Baseline three + new suites: validation/error-code mapping, routing logic per login surface, MFA-slot inertness
- Extended measure-pages includes `/staff/login`, still passing

## Handoff notes

- Submits must fail honestly: name Phase 5 in the feedback; no fake success states anywhere.
- The conditional MFA slot renders only when enrollment is indicated by local state (which nothing sets this phase) - build the slot, prove it stays hidden.
- Multi-role picker is scoped to staff roles only; patient sessions never see it.
