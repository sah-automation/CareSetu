# Brief - #803 Combined review of Batch 2 with fixes

**Ticket:** #803 - **Parent:** #761 - **Published:** 2026-10-23
**Reading surface:** Batch 2 diff plus the standards, reviewed with sub-agents (closeout exception to the slice budget)

## Scope

Review the whole Batch 2 change set on both axes, Standards and Spec, using the code-review skill with spec #761 as the reference, then fix every finding and run the full repository harness.

- [ ] The code-review skill runs against the whole Batch 2 change set on both axes.
- [ ] Every finding is fixed and re-verified against the owning ticket.
- [ ] Module isolation holds and no module reads another module's tables.
- [ ] No PHI lands in the observability or ops schema.
- [ ] The full harness is green: lint, typecheck, backend and frontend unit, integration, migration checks, and security scan.

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
- #802 - Docs, design records, and traceability closeout

## Read-list (in order)

1. The Batch 2 diff and the standards for coding, API, integration, errors, security, and AI engineering.

## Do NOT read

- docs/archive/
- Unrelated phases.

## Baseline verify (must pass before the first edit)

- `npm run lint`
- `npm run typecheck`
- `npm run migration-check`

## Done-verify (acceptance criteria -> commands)

- `npm run lint`
- `npm run typecheck`
- `npm run test:unit:backend`
- `npm run test:unit:frontend`
- `npm run test:integration`
- `npm run migration-check`
- `npm run scan`

## Handoff notes

- Use the code-review skill, not ad hoc review.
- Fix findings before declaring done.
- Read only the named sections and grep for interfaces by name. Do not read whole files, unrelated modules, or generated files.
