# Brief - #775 Hardened API CSP and frontend report-only CSP

**Ticket:** #775 - **Parent:** #761 - **Published:** 2026-10-23
**Reading surface:** ~8K

## Scope

Add a hardened CSP to API responses and a report-only CSP to the frontend with Reporting-Endpoints and report-uri. The reporting directives are omitted when the build-time collector URL is unset.

- [ ] API responses carry the hardened CSP.
- [ ] The frontend carries Content-Security-Policy-Report-Only.
- [ ] Reporting-Endpoints and report-uri appear only when the frontend build environment value is set.
- [ ] The policy matches the current Next.js application and remains report-only.
- [ ] No enforcement, nonce plumbing, or Trusted Types work is added.

## Blocked by

None - can start immediately.

## Read-list (in order)

1. Spec #761, security posture decisions.
2. The gateway middleware and the frontend Next.js config or proxy.
3. ADR-0007 for split-origin deployment invariants.

## Do NOT read

- docs/archive/
- The alert and evaluation modules.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run typecheck`

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend`
- `npm run test:unit:frontend`
- `npm run typecheck`
- `npm run lint`

## Handoff notes

- Report-only this batch.
- Do not break inline styles or scripts the framework currently needs.
- The collector is a separate ticket.
- Read only the named sections and grep for interfaces by name. Do not read whole files, unrelated modules, or generated files.
