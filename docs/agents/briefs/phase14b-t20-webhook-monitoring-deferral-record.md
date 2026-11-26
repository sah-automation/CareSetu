# Brief - #781 Webhook-signature monitoring deferral and reserved kind

**Ticket:** #781 - **Parent:** #761 - **Published:** 2026-10-23
**Reading surface:** ~4K

## Scope

Record the accepted risk that webhook-signature monitoring is deferred until an inbound webhook exists, and reserve the event and alert kind without adding a producer or receiver.

- [ ] The accepted-risk register records the deferral, mitigation, and reopen trigger.
- [ ] The webhook-signature-failure event and alert kind are reserved in the registry.
- [ ] The Security page can show the deferred status.
- [ ] No inbound webhook receiver or producer is added.

## Blocked by

None - can start immediately.

## Read-list (in order)

1. Spec #761, out-of-scope and risk decisions.
2. The accepted-risk ADR and the event and alert kind registries.

## Do NOT read

- docs/archive/
- The delivery worker.

## Baseline verify (must pass before the first edit)

- `npm run typecheck`

## Done-verify (acceptance criteria -> commands)

- `npm run typecheck`
- `npm run lint`

## Handoff notes

- Docs and registry only.
- Do not build a webhook receiver.
- Read only the named sections and grep for interfaces by name. Do not read whole files, unrelated modules, or generated files.
