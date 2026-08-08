# API Standards

**Scope:** The public HTTP surface — conventions every endpoint must follow.
**Upstream:** `NFR-002`, `NFR-SEC-002/003/004`, `FEAT-001`..`FEAT-020`, whitebox §4.1 sync matrix.

---

## 1. Shape & Versioning

- REST over HTTPS; JSON bodies; `UTF-8`. No query-string mutations.
- Base path versioned: `/v1/...`. Breaking changes bump the version; additive changes do not.
- Resources are plural nouns; actions that don't map to a resource are verbs under the domain (`/v1/cases/{id}/complete`).
- Endpoints are thin adapters: parse → call module facade → return. No business logic in routers.

## 2. Error Envelope (contract)

Every error response uses one envelope:

```json
{
  "code": "CONSENT_DENIED",
  "message": "Consent for this scope is not granted",
  "trace_id": "c7f2...",
  "details": {}
}
```

- `code`: stable machine-readable `SCREAMING_SNAKE`, namespaced by module. Never the raw exception string.
- `message`: human-safe, no stack traces, no PHI.
- `details`: optional, validated field errors (path + reason), or the internal cause for expected failures.
- HTTP status groups: `4xx` = client/expected, `5xx` = operational, `502/503/504` = third-party/degradation.
- 100% of expected failures follow PRD §5.2 fallback messages; user-visible copy lives in the client, not the API.

## 3. Validation & Schemas

- Every request/response is a Pydantic v2 model — no raw `dict` handlers.
- Validation errors return `422` with a `details` list; unknown/extra fields rejected (strict mode).
- IDs are opaque strings (`uuid4`); amounts in integer paise; timestamps as ISO-8601 UTC (`Z`).

## 4. Pagination, Sorting & Filtering

- List endpoints paginate: `?cursor=` (opaque, preferred) or `?page=&per_page=`. Default `per_page` 25, max 100.
- Response envelope: `{ "items": [...], "next_cursor": "...", "total": 123 }` (total optional where costly).
- Sorting via whitelisted `sort` params only; filters via explicit, validated query params.

## 5. Idempotency & Retries

- Mutations accept `Idempotency-Key` header; duplicate keys return the original result without re-execution.
- `POST /v1/settlements/facilitated` and all webhook-facing paths MUST be idempotent — see third-party-integration-standards.
- Clients may retry on network failure/`5xx` with backoff; never on `4xx`.

## 6. Auth, RBAC & Rate Limiting

- JWT (issued by `MOD-001`) on every authenticated call; **all** authorization enforced at the edge + re-checked in the facade.
- Role scopes: patient (own record), partner (own scope), operator (all records) — `NFR-SEC-003`.
- Rate-limit at the edge: OTP/auth/intake endpoints get the strictest limits (`NFR-SEC-004`); limits are per identity or per IP with `429` + `Retry-After`.
- Telemetry events emitted per PRD event names (`directory_search`, `intake_started`, …) — never invent new event names; register additions in the whitebox §4.2 registry.
