# Brief - T11 Four-step provider registration wizard

**Ticket:** #202 · **Parent:** #191 PHASE-2.6 · **Refreshed:** 2026-08-22
**Reading surface:** ~6.5K tokens (budget 10K) - within budget

## Scope

A four-step provider application wizard - account basics, professional/business identity, credentials upload, review & declarations - carrying the `type` preset from Register-as-doctor/lab/chemist CTAs via query param. Client-side validation mirrors the planned field schemas; upload-discipline checks follow the security standard (client-side only: type/size limits, no auto-upload without explicit action). Submission gives honest not-yet-available feedback naming Phase 5 - nothing pretends to persist.

The wizard route sits in the public carve-out of the staff route group (applicants are unauthenticated); CTAs on the homepage providers band and the staff login page link here.

Acceptance criteria: see #202 body verbatim.

## Read-list (in order)

1. Prototype view `provider-register.html` - binding visual/step/copy spec (~2.5K tokens)
2. UI blueprint §4.x provider-application section - step definitions + preset mechanics (~1.5K)
3. Security standard upload section - client-side discipline rules (~1K)
4. PRD §4.x provider onboarding feature rules - field schema source of truth (~1.5K)

## Do NOT read

- Other split-auth prototype views, backend verification modules (Phase 5), `docs/archive/`.

## Baseline verify (must pass before the first edit)

Recorded green on 2026-08-22: lint, typecheck, frontend units 72 tests.

## Done-verify (acceptance criteria → commands)

- Baseline three + new suites: validation matrix per step, type-preset flow from query param, upload discipline checks, honest-submit feedback

## Handoff notes

- The `type` query param arrives from ticket 09's provider-band CTAs; default sensibly when absent.
- Review step must faithfully summarize entered data before declarations; declarations are checkboxes, not passive text.
- Uploads stay local this phase: validate type/size client-side, show what would be submitted, never pretend an upload occurred server-side.
