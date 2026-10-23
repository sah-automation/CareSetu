# Brief - #782 Security summary and signal read API

**Ticket:** #782 - **Parent:** #761 - **Published:** 2026-10-23
**Reading surface:** ~8K

## Scope

Add operator read endpoints for the security summary, auth and lockout trends, consent and rate-limit anomalies, CSP violations, prompt-injection counts, and webhook monitoring status.

- [ ] Routes are operator-guarded.
- [ ] Responses cover trends, anomalies, CSP, prompt-injection, and webhook status.
- [ ] No PHI or raw report is returned.
- [ ] Empty and degraded states are well defined.
- [ ] Tests cover shapes and guard behavior.

## Blocked by

- #776 - Public CSP report collector and daily aggregation
- #777 - Security signal aggregation consumers
- #779 - Security detector scan job and alert kinds
- #780 - Prompt-injection heuristics before AI egress
- #781 - Webhook-signature monitoring deferral and reserved kind

## Read-list (in order)

1. Spec #761, security read decisions.
2. The observability read facade and routes, the signal and aggregate models, and the alert feed.

## Do NOT read

- docs/archive/
- The frontend security page.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run typecheck`

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend`
- `npm run test:integration`
- `npm run typecheck`

## Handoff notes

- Read-only.
- Never expose raw CSP reports or subject keys.
- Read only the named sections and grep for interfaces by name. Do not read whole files, unrelated modules, or generated files.
