# Third-Party Integration Standards

**Scope:** All calls to external systems — `EXT-001` SMS/OTP, `EXT-002` LLM/AI, `EXT-003` WhatsApp, `EXT-004` UPI — and their inbound webhooks.
**Upstream:** Whitebox §4 sync matrix + §2.1 container diagram; `NFR-SEC-004/005`, `NFR-PERF-003`, `NFR-001`, PRD §5.2.

---

## 1. Outbound Call Discipline (every provider)

| Provider         | Timeout | Retries        | Backoff              | Circuit breaker |
| ---------------- | ------- | -------------- | -------------------- | --------------- |
| EXT-001 SMS/OTP  | ≤ 10 s  | 3              | exponential + jitter | yes             |
| EXT-002 LLM/AI   | ≤ 30 s  | 3              | exponential + jitter | yes             |
| EXT-003 WhatsApp | ≤ 10 s  | 3 (next slot)  | scheduled retry      | yes             |
| EXT-004 UPI      | ≤ 10 s  | 3 (idempotent) | exponential + jitter | yes             |

- **Never in the user-critical path:** all provider calls are async (outbox/scheduler) or degrade — `NFR-PERF-003`.
- Timeout is always set explicitly; no unbounded waits.
- Retries share the request's idempotency key where the provider supports it (UPI) so no double charge.

## 2. Degradation Rule (the hard one)

> **An external failure never blocks the care loop.**

- LLM failure/timeout → degrade to forced doctor review (never present AI output as verified). `MOD-005`.
- UPI gateway unavailable on a fraud-risk case → fall back to direct cash/UPI with a risk note. `FEAT-016`.
- WhatsApp failure → log + retry next scheduled slot; prompt number confirmation on repeated failure. `FEAT-019`.
- OTP provider outage → never bricks existing sessions; refresh path is SMS-independent.
- Every degradation decision is recorded to `MOD-011` audit + telemetry, so operators can see the fallback happened.

## 3. Secrets & Keys

- Server-side API keys only; never client-side. Secrets in a secret manager / env, never in code, logs, or the repo.
- Keys are scoped and rotatable; a key used in a leaked log is revoked immediately.

## 4. Inbound Webhooks (EXT-003 delivery status, EXT-004 payment status)

- **Verify every webhook:** signature (HMAC) or signed payload per provider contract, checked before any processing — `NFR-SEC-005`.
- Reject on bad signature with `401`, log the attempt.
- **Idempotent + replay-safe:** dedupe on provider event/payment ref; duplicate deliveries no-op.
- Webhooks accept fast (`p95 < 100 ms`), then enqueue via outbox for async processing — never do slow work in the webhook handler.
- Webhook payloads are untrusted input: validate against Pydantic schema; no SQL interpolation.

## 5. Cost Metering (EXT-002, paid tiers)

- Every AI call records provider, tokens, ₹cost to `ai_jobs`; counters persisted — `NFR-001`, `NFR-COST-001`.
- Hard budget enforcement: when the monthly meter is exhausted, AI features degrade to their fallback path instead of spending over budget.
- Egress carries only intake/prescription context — **never the full record** — and is consent-gated + audited (`NFR-SEC-006`).

## 6. Provider Changes

- Providers are behind a port/adapter per module (`MOD-005` LLM client, `MOD-010` WhatsApp client, `MOD-009` UPI client, `MOD-001` SMS client). Swapping a provider = new adapter, zero domain changes.
- Adding an integration requires updating the whitebox §4.1/4.2 registry (sync matrix + event registry) — no new integration is merged silently.

## 7. Extensibility: Future Providers & Paid Services

The platform must have headroom for advanced/paid providers and services later without a redesign.

- **Provider-agnostic ports:** every external dependency is a typed port. Choosing a provider is **configuration, not code** — a new provider is a new adapter selected by config/feature-flag, never a domain change.
- **Feature-flag gating:** experimental or paid providers ship behind flags with a default that keeps the care loop on the free-tier path. Promote to default only after budget + quality validation.
- **Scaling cost model:** the budget meter (`NFR-001`) is built to grow — from a single free tier today to multiple paid providers/tiers later. Cost is metered per provider and per task, so adding a paid tier is a config change, not a re-architecture.
- **Change discipline:** adopting a new integration or provider follows ADR + whitebox registry update; it must never silently override the plan's `NFR-001` posture.
