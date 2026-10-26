# ADR-0032: Accepted risk - webhook-signature monitoring is deferred until an inbound webhook exists

**Status:** accepted (risk accepted, 2026-10-26)
**Date:** 2026-10-26
**Decides:** That webhook-signature failure monitoring is deferred because no inbound webhook exists today. The event name `webhook_signature_failure` and alert kind `webhook_signature_failure` are reserved in the registries. A decision to add an inbound webhook receiver reopens this risk.
**Traceability:** `plan-phase14-observability.md` §10, §13; spec #761 "webhook-signature monitoring is deferred because no inbound webhook exists"; parent #761; ticket #781. Related: `ADR-0030` (SLOs and symptom alerting), `ADR-0031` (accepted risk - AI tracing vendor), `internal-modules.md` §4.2 (event registry), `apps/backend/modules/ops/domain/settings.py` (ALERT_KINDS), `apps/backend/modules/observability/domain/security_detector.py` (SECURITY_SIGNAL_WEBHOOK_SIGNATURE_FAILURE), `apps/backend/modules/observability/domain/rollup.py` (ALERT_KIND_WEBHOOK_SIGNATURE_FAILURE).

## Context

The Phase 14 observability plan (§10, §13) names webhook-signature-failure monitoring as part of the full Security & Guardrails monitoring scope. However, the platform does not currently have an inbound webhook receiver - no external system posts HMAC-signed callbacks to the platform that would need signature verification. The settlement webhook (`payment.webhook_received` from MOD-009) is an outbound callback _from_ the UPI gateway, not an inbound webhook _to_ the platform that the platform verifies. The WhatsApp webhook (`notification.sent/.delivered/.failed` from MOD-010) is likewise an outbound status callback.

Without a producer that can emit `webhook_signature_failure` events, there is nothing to detect, no signal to aggregate, and no alert to raise. Building a monitoring pipeline for a non-existent producer would be speculative code that cannot be exercised or validated.

## Decision

### D1 - The deferral is explicit, not forgotten

The webhook-signature-failure event and alert kind are reserved in the registries:

- The event name `webhook_signature_failure` is registered in `internal-modules.md` §4.2 as a deferred event with no publishing module.
- The alert kind `webhook_signature_failure` is included in `ALERT_KINDS` in `apps/backend/modules/ops/domain/settings.py`.
- The signal kind `webhook_signature_failure` is defined in `apps/backend/modules/observability/domain/security_detector.py` as `SECURITY_SIGNAL_WEBHOOK_SIGNATURE_FAILURE`.
- The alert kind constant `ALERT_KIND_WEBHOOK_SIGNATURE_FAILURE` is defined in `apps/backend/modules/observability/domain/rollup.py`.
- The detector includes an irreversible rule for this signal in `SECURITY_IRREVERSIBLE_RULES`.

This reservation prevents a future producer from inventing a second spelling and ensures the monitoring vocabulary is stable.

### D2 - No producer or receiver is added

This decision adds no inbound webhook receiver, no HMAC verification middleware, and no signature validation code. The deferral is recorded so the absence is visible in the Security page and the risk register, not because the work is incomplete.

### D3 - The mitigation is the reservation itself

The mitigation for this deferral is the explicit reservation of the event and alert kind. When an inbound webhook is added, the producer will emit `webhook_signature_failure` using the reserved name, the existing detector rule will raise the reserved alert kind, and the Security page will show live data instead of the deferred status. No schema migration, no new alert kind, and no detector change are needed - only the producer.

### D4 - The rule that reopens this risk

The risk reopens, and this record has to be re-decided, on any of:

- A decision to add an inbound webhook receiver to the platform (any external system posting to a `/webhook/*` or `/callback/*` route that the platform verifies).
- A change to an existing outbound callback that requires the platform to verify the sender's signature (e.g., if the UPI gateway or WhatsApp business API changes to require mutual HMAC verification).
- Any proposal to monitor third-party webhook signatures for compliance or audit reasons.

### D5 - What this record does not do

It does not approve building a webhook receiver. It does not claim the deferred monitoring is unnecessary. It does not authorise a future team to skip signature verification when a webhook is added. It does not close the question - the reservation exists so the question is answerable when it arrives.

## Considered options

- **Build a generic webhook receiver now.** Rejected - there is no consumer for it, no external integration requires it, and it would be untestable code.
- **Monitor the outbound UPI/WhatsApp callbacks.** Rejected - those are callbacks _from_ the platform's partners _to_ the platform; the platform does not verify their signatures, the partners do. The platform's webhook signature concern is inbound webhooks the platform receives.
- **Record the deferral without reserving the names.** Rejected - a future producer would invent its own spelling (`webhook.signature.failed`, `webhook_verification_failure`, etc.), creating drift and requiring a migration later.

## Consequences

- The Security page shows "Deferred - no inbound webhook" for webhook signature monitoring rather than live data.
- The alert feed will never show a `webhook_signature_failure` alert until an inbound webhook exists.
- When an inbound webhook is added, the producer uses the reserved event name and the monitoring activates without schema or registry changes.
- The accepted-risk register (ADR-0031 pattern) now has two entries: the AI tracing vendor free tier (ADR-0031) and this webhook-signature deferral (ADR-0032).
