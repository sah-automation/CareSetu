# Security & PHI Data Handling Standards

**Scope:** Protecting patient health information and the platform's compliance posture (DPDP baseline).
**Upstream:** `NFR-002`, `NFR-SEC-002/003/004/005/006`, `NFR-D02`, `FEAT-002`, `FEAT-020`, PRD §7 (open `GAP-005/011/013`).

---

## 1. Encryption & Transport

- TLS 1.2+ on every external interface — `NFR-002`. HSTS; no legacy ciphers.
- At-rest encryption for PostgreSQL, object storage, backups, and secrets.
- OTP values hashed at rest, single-use, 5-min TTL, never logged (`MOD-001`).

## 2. Data Minimization & Consent Gating

- **No PHI egress without a live consent check** against `MOD-004` `check_consent()` — this is a hard gate on every share and every LLM egress (`NFR-SEC-006`). Denials short-circuit the requesting module.
- Egress carries the minimum context (intake/prescription scope only) — **never the full record**.
- Record deletion/retention follows the DPDP baseline; open decisions `GAP-005`/`GAP-013` are tracked in the PRD, not resolved ad hoc in code.

## 3. Authentication & Authorization

- RBAC at the edge (`NFR-SEC-002/003`): patient → own record; partner → own scope; operator → all records. Every endpoint re-checks scope in the facade — edge checks are convenience, not the boundary.
- Operator accounts require MFA. Partner roles activate only after credential verification (`REQ-028`).
- Credential expiry/revocation deactivates the partner and removes them from search immediately (`FEAT-005`).
- Authn/authz failures and consent events are 100% audited (`KPI-006`).

## 4. Secret Management

- All secrets (SMS/LLM/WhatsApp/UPI keys, DB creds, JWT signing keys) in a secret manager / environment — **never in code, config committed to git, or logs**.
- Keys are per-provider, scoped, rotatable; any leaked key is revoked immediately and rotated.
- **gitleaks runs as a pre-commit hook and in CI** — a commit/PR that ships a detected secret is rejected. Repo-local values (`.env.example`, local dev credentials) are synthetic; real secrets never get an allowlist entry.

## 5. Inputs & Uploads

- Every request body is a validated Pydantic schema; untrusted webhook payloads are validated before use.
- Uploads (audio, doctor inputs, lab reports) are scanned before filing (`NFR-SEC-004`) and stored in private object-storage prefixes — never served from a public bucket.
- Report uploads are matched to order + patient before filing; mismatches are rejected and never filed (`RISK-002`, `FEAT-011`).

## 6. Audit & Tamper Resistance

- Regulated acts (consent, record access, prescription issuance, report filing, settlements, partner decisions, auth failures) are appended to `MOD-011`'s hash-chained, append-only log (`FEAT-020`, `NFR-D01`).
- DB grants revoke UPDATE/DELETE on `audit` tables; any tamper attempt is itself recorded and alerts.
- Patient can view their own access history (`FEAT-003`).

## 7. Breach & Incident Response

- A breach-notification path is required by the DPDP baseline (open `GAP-013`) — when decided, it triggers from `MOD-011` tamper/egress anomalies. Until then, any suspected PHI leak is a `critical` incident: freeze, rotate keys, audit-query the leak window.
