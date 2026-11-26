# Brief - #779 Security detector scan job and alert kinds

**Ticket:** #779 - **Parent:** #761 - **Published:** 2026-10-23
**Reading surface:** ~9K

## Scope

Add a five-minute worker scan over recent security signal rows that raises the new security alert kinds with configurable thresholds, cooldown, one alert per incident, and auto-resolve when the condition clears, except for single irreversible events.

- [ ] The scan job is scheduled every five minutes.
- [ ] Thresholds and cooldown are configurable.
- [ ] One incident produces one alert.
- [ ] Condition-clearing kinds auto-resolve.
- [ ] Irreversible kinds do not auto-resolve.
- [ ] New alert kinds are registered and the reserved webhook kind exists.

## Blocked by

- #776 - Public CSP report collector and daily aggregation
- #777 - Security signal aggregation consumers
- #778 - Operator TOTP failure counter and lockout

## Read-list (in order)

1. Spec #761, detector and alert decisions.
2. The worker scheduler, the rollup alert discipline, and the alert resolve vocabulary.
3. The security signal model and the new alert kinds.

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

- Reuse the existing alert-key and resolve discipline.
- Do not page internal causes.
- Do not route the delivery-failure alert back into the failing channel.
- Read only the named sections and grep for interfaces by name. Do not read whole files, unrelated modules, or generated files.
