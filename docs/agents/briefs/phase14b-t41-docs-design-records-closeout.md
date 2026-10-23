# Brief - #802 Docs, design records, and traceability closeout

**Ticket:** #802 - **Parent:** #761 - **Published:** 2026-10-23
**Reading surface:** ~9K (budget 10K), named sections only

## Scope

Update the MOD-014 module spec, schema count, sync matrix, event registry, roadmap and CONTEXT status, and add the design records for operator tiers, the ops module, CSP report-only, and the webhook deferral. Confirm i18n parity.

- [ ] The MOD-014 spec and schema count are updated.
- [ ] The sync matrix and event registry include the new events and module edges.
- [ ] Design records exist for operator tiers, ops, CSP report-only, and webhook deferral.
- [ ] Roadmap and CONTEXT status reflect Batch 2.
- [ ] i18n parity tests pass.

## Blocked by

- #762 - Shared plain-text normalizer and no-new-HTML-sink rule
- #763 - IAM operator profile schema and admin backfill
- #764 - MOD-014 ops schema scaffold and single registration
- #765 - Observability security signal, CSP aggregate, and alert delivery schema
- #766 - Evaluation dataset, run, and judge score schema
- #767 - Operator tier claim, gateway principal, admin guard, and me tier
- #768 - Admin operator list and tiered invite
- #769 - Operator tier and active-state changes with last-admin guards
- #770 - First-admin CLI promotion
- #771 - Effective settings read with source and allowlist
- #772 - Allowlisted settings writes with history and audit
- #773 - Feature flags with runtime and restart-required typing
- #774 - Notification routing, recipients, and channel settings
- #775 - Hardened API CSP and frontend report-only CSP
- #776 - Public CSP report collector and daily aggregation
- #777 - Security signal aggregation consumers
- #778 - Operator TOTP failure counter and lockout
- #779 - Security detector scan job and alert kinds
- #780 - Prompt-injection heuristics before AI egress
- #781 - Webhook-signature monitoring deferral and reserved kind
- #782 - Security summary and signal read API
- #783 - Security page in the operator console
- #784 - Durable alert delivery core, retries, and redelivery
- #785 - Slack alert delivery channel
- #786 - SMTP alert delivery channel
- #787 - Versioned evaluation dataset API
- #788 - Evaluation dataset validation and PHI-pattern rejection
- #789 - LLM judge run worker and completeness evaluator
- #790 - Confidence calibration and prescription-draft accuracy evaluators
- #791 - Human labels on golden examples
- #792 - Judge and human agreement computation
- #793 - Evaluation read API
- #794 - Evals page read-only view
- #795 - Evals page admin controls
- #796 - Admin-only navigation filtering and permission state
- #797 - Settings page shell and AI read section
- #798 - Settings AI writes and history
- #799 - Settings Notifications section
- #800 - Settings Feature flags section
- #801 - Settings Users section

## Read-list (in order)

1. `CONTEXT.md` doc inventory and the Observability glossary section.
2. `docs/architecture/internal-modules.md` MOD-014 spec, §4.2 event registry, and §5 traceability.
3. `docs/roadmap/implementation-roadmap.md` PHASE-14B status and §3 traceability rows.
4. `docs/plans/plan-phase14-observability.md` §12, §12.1, and §13.
5. The ADR index plus ADR-0025, ADR-0030, and ADR-0031.
6. The event registry and the i18n parity test, plus the locale namespaces touched by this batch.

## Do NOT read

- docs/archive/
- Unrelated module specs.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend`
- `npm run typecheck`

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:frontend`
- `npm run lint`
- `npm run typecheck`

## Handoff notes

- Do not read docs/archive.
- Keep the glossary vocabulary.
- Update the private schema count to thirteen and register MOD-014 in the same change.
- Add design records for operator tiers, the `ops` module, CSP report-only, and the webhook deferral.
- Read only the named sections and grep for interfaces by name. Do not read whole docs or unrelated module specs.
