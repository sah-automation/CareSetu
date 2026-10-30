# Brief - #776 Public CSP report collector and daily aggregation

**Ticket:** #776 - **Parent:** #761 - **Published:** 2026-10-23
**Reading surface:** ~8K

## Scope

Add a public, rate-limited CSP report collector capped at 16 KB that accepts both CSP report formats, normalizes the report, aggregates daily by directive, disposition, blocked source, and document path, returns 204, and never stores raw reports.

- [ ] Both CSP report formats are accepted and return 204.
- [ ] Oversized reports are rejected and the route is rate limited.
- [ ] Query strings are stripped and lengths are capped.
- [ ] Daily aggregate rows are written by directive, disposition, blocked source, and document path.
- [ ] No raw report, query string, or PHI is stored.

## Blocked by

- #765 - Observability security signal, CSP aggregate, and alert delivery schema
- #775 - Hardened API CSP and frontend report-only CSP

## Read-list (in order)

1. Spec #761, CSP collector decisions.
2. The observability routes and the CSP aggregate model.
3. The rate-limit helper and the pseudonymous hashing scheme.

## Do NOT read

- docs/archive/
- The frontend CSP config except the report shape.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run typecheck`

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend`
- `npm run test:integration`
- `npm run typecheck`

## Handoff notes

- This is the only unauthenticated addition.
- Never log a raw report.
- CSP enforcement is out of scope.
- Read only the named sections and grep for interfaces by name. Do not read whole files, unrelated modules, or generated files.
