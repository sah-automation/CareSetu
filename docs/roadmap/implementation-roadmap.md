# Project Phase Division & Implementation Roadmap

**System Name:** CareSetu - zero-inventory, pure-facilitator care-loop aggregator (Daltonganj beachhead)
**Document Version:** 1.0 (Baseline)
**Date:** 2026-08-07
**Lead Architect / TPM:** Engineering / Architecture (derived from PRD v1.0, System Context v1.0, Internal Modules v1.0)
**Upstream Inputs:** Module 4 PRD (`FEAT-001`–`FEAT-020`, `NFR-001`–`NFR-004`, `NFR-D01`, `NFR-D02`) | Module 5 Context (`EXT-001`–`EXT-004`, `ACT-001`–`ACT-005`) | Module 6 Whitebox (`MOD-001`–`MOD-011`)

---

## 1. Executive Phasing Strategy & Granular Roadmap Overview

### 1.1 Rationale for small-phase decomposition

CareSetu is a 20-feature, 11-module, 4-integration system with one dominating constraint: **`NFR-001` (total monthly operating + hosting + AI spend ≤ ₹2,000)**. That cost floor forces a modular monolith on a single VM + one PostgreSQL instance - which in turn makes a **single, small-AI-context-window, independently verifiable phase sequence** the only safe way to build it. Every phase is a slice that:

- **Builds, tests, and verifies independently** - no phase depends on the _outputs_ of an unbuilt phase to prove its own correctness (dependencies are limited to the _schemas/facades_ of already-built phases).
- **Introduces a versioned, idempotent schema delta** on the single PostgreSQL instance (11 private schemas, migration harness from Phase 1).
- **De-risks the cost floor early** - the cheapest de-risking spikes (Hindi ASR, outbox round-trip) happen in Phase 0–1, before any LLM or provider spend is committed.
- **Matches the whitebox build order** - foundation/auth → trusted data engine → onboarding/directory → core workflows → integrations → events → admin/observability.

**Dependency spine (build order):**

```
PHASE-0  Hindi ASR spike ───────────────┐
PHASE-1  Foundation/CI ────────────┐    │
PHASE-2  IAM Auth (FEAT-001) ──────┤    │
PHASE-3  Record+Consent (FEAT-002) ┤    │
PHASE-4  Audit+Access View (FEAT-003, 020) ─┐
PHASE-5  Partner Onboarding (014, 015) ─────┤
PHASE-6  Directory (004, 005) ──────────────┤
PHASE-7  Intake+AI (006, 007) ◄─────────────┘  (needs Phase-0 gate)
PHASE-8  Care+Rx (008, 009) ◄─ Phase-7 (pre-summary), Phase-3 (consented history)
PHASE-9  Diagnostics (010, 011) ◄─ Phase-5 (lab partner), Phase-3 (record)
PHASE-10 Fulfillment (012, 013) ◄─ Phase-8 (approved rx)
PHASE-11 Settlement (016, 017) ◄─ Phase-8/9 (order context)
PHASE-12 Chronic Care (018) ◄─ Phase-3 (health schema)
PHASE-13 Notifications (019) ◄─ Phase-8 (rx schedules), Phase-12 (follow-ups)
PHASE-14 E2E + Observability + Release ◄─ all phases
```

### 1.2 Phase Summary Mapping Table

| Phase ID       | Phase Name                                      | Primary Technical Scope                                                                                                                             | Target Deliverable                                   |
| :------------- | :---------------------------------------------- | :-------------------------------------------------------------------------------------------------------------------------------------------------- | :--------------------------------------------------- |
| **`PHASE-0`**  | Hindi Voice Feasibility Spike                   | `EXT-002` ASR/structuring provider eval; `AMB-006` threshold spike (`RISK-EVAL-006`)                                                                | Go/no-go report + low-confidence fallback design     |
| **`PHASE-1`**  | Modular-Monolith Foundation & CI                | Monorepo skeleton, 11-schema baseline + migration harness, transactional-outbox round-trip, edge/gateway skeleton, cost-floor tech lock (`NFR-001`) | Green CI monolith + outbox event loop                |
| **`PHASE-2`**  | Patient Identity & Phone-OTP Auth               | `MOD-001` IAM core + `EXT-001` SMS/OTP + patient PWA registration; JWT + RBAC at edge (`FEAT-001`)                                                  | Register/verify/login loop with mocked SMS           |
| **`PHASE-3`**  | Longitudinal Record & Consent Engine            | `MOD-003` LHR + `MOD-004` consent lifecycle + `check_consent` gate (`FEAT-002`)                                                                     | Consent-gated longitudinal record APIs               |
| **`PHASE-4`**  | Append-Only Audit Trail & Access History        | `MOD-011` hash-chained audit + tamper detection + operator query + patient access history (`FEAT-003`, `FEAT-020`)                                  | Append-only audit engine + tamper tests              |
| **`PHASE-5`**  | Partner Onboarding & Gated Activation           | `MOD-002` registration/credentials/verification + operator console + `MOD-001` role grants/MFA (`FEAT-014`, `FEAT-015`)                             | Partner register→verify→activate loop                |
| **`PHASE-6`**  | Provider Directory & Profiles                   | `MOD-002` geo search, activated-only gating, credential display + expiry deactivation (`FEAT-004`, `FEAT-005`)                                      | Directory search + verified profiles                 |
| **`PHASE-7`**  | Symptom Intake & AI Pre-Summary                 | `MOD-005` voice/text intake, `EXT-002` transcribe/structure, budget meter, low-confidence fallback (`FEAT-006`, `FEAT-007`)                         | Voice/text intake → structured pre-summary           |
| **`PHASE-8`**  | Care Case, Consult Handshake & E-Prescription   | `MOD-006` case + rx lifecycle, doctor approval gate, `MOD-005` rx-draft facade (`FEAT-008`, `FEAT-009`)                                             | Pre-summary → handshake → approved e-prescription    |
| **`PHASE-9`**  | Diagnostics Booking & Report Match/Filing       | `MOD-007` booking, order-ID+patient match, wrong-upload protection, lab channel (`FEAT-010`, `FEAT-011`)                                            | Book → collect → upload → match → file/reject        |
| **`PHASE-10`** | Pharmacy Fulfillment & Delivery                 | `MOD-008` routing, fulfilment status, out-of-stock / delivery-failure choices, chemist channel (`FEAT-012`, `FEAT-013`)                             | Approved rx → route → deliver + failure workflows    |
| **`PHASE-11`** | Settlement, Cancellations & Refunds             | `MOD-009` outcome recording, `EXT-004` UPI exception path (HMAC/idempotent), policies, partner-direct refunds (`FEAT-016`, `FEAT-017`)              | Settlement recording + facilitated-payment exception |
| **`PHASE-12`** | Chronic Care Loop - Metrics & Follow-Ups        | `MOD-003` chronic metrics + follow-up plans + due-eval scheduler (`FEAT-018`)                                                                       | Daily BP/sugar logging + follow-up nudges            |
| **`PHASE-13`** | WhatsApp Notifications                          | `MOD-010` templates (hi/en), `EXT-003` signed callbacks, retry, in-app inbox (`FEAT-019`)                                                           | Dosage reminders + 30/90-day nudges delivered        |
| **`PHASE-14`** | End-to-End Integration, Observability & Release | Full care-loop E2E (`KPI-001`), audit wiring, cost telemetry (`KPI-007`), backup/restore drill, launch env                                          | Verified full loop + Daltonganj release readiness    |

**Module primary build phases:** `MOD-001`→2, `MOD-002`→5, `MOD-003`→3, `MOD-004`→3, `MOD-005`→7, `MOD-006`→8, `MOD-007`→9, `MOD-008`→10, `MOD-009`→11, `MOD-010`→13, `MOD-011`→4. (Phase 1 scaffolds all modules; later phases extend already-built modules' facades where the traceability matrix in §5 shows it.)

---

## 2. Granular Phase Breakdown Specifications

---

### 2.0 Phase 0: Hindi Voice Feasibility Spike

- **Phase ID:** `PHASE-0-HINDI-ASR-SPIKE`
- **Phase Strategic Objective:** Prove, before any production LLM spend is committed, that a freemium `EXT-002` tier can transcribe and structure Hindi voice intake (target dialect spectrum) well enough for doctor-reviewed pre-summaries within the `NFR-001` budget and ≤ 30 s timeouts.
- **Release Readiness Criteria:** A written spike report on the sample corpus: transcription quality metric, Hindi structuring accuracy, per-call ₹cost + token estimate extrapolated to KPI-001 volume, provider selection, and a **go / no-go** recommendation. The `AMB-006` low-confidence threshold and forced-doctor-review fallback are validated on the sample. No production code is merged.

#### 1. In-Scope Modules & Features

| PRD Feature ID                     | Feature Name                       | Internal Module ID (Mod 6) | External Interface ID (Mod 5) |
| :--------------------------------- | :--------------------------------- | :------------------------- | :---------------------------- |
| `FEAT-007` (feasibility gate only) | AI Clinical Pre-Summary Generation | `MOD-005` (Intake & AI)    | `EXT-002` (LLM/AI Provider)   |

#### 2. Deferred / Out-of-Scope Items

- No production wiring, no `intake` schema, no budget-meter implementation - only a throwaway prototype against provider sandboxes.
- No e-prescription drafting validation here (deferred to `PHASE-8`).

#### 3. Data Schema & Entity Delta (Phase Data Model)

- **Databases Introduced/Updated:** None.
- **Tables / Entities Created/Modified:** None.
- **Migration Scripts:** None.

#### 4. Infrastructure, DevOps & Environment Targets

- **Hosting / Cloud Provisioning:** Throwaway provider sandbox keys + a local sample-audio corpus (recorded or vendor sample sets). No persistent infra.
- **CI/CD Requirements:** None (research phase). Findings recorded in the spike report and fed to `PHASE-7` design.

#### 5. Phase Dependency & Risk Matrix

| Dependency / Blocked By  | Potential Risk                                      | Mitigation Plan                                                                                     |
| :----------------------- | :-------------------------------------------------- | :-------------------------------------------------------------------------------------------------- |
| `EXT-002` freemium quota | Provider quota too small for realistic sample       | Test 2–3 providers; budget a tiny paid allowance within `NFR-001`                                   |
| `RISK-EVAL-006`          | Hindi ASR quality below usefulness on low-cost tier | Measure early; if no-go, fall back to text-first intake with voice as an upload-for-doctor artifact |

#### 6. Downstream AI Engineering Handoff Specs

- **Target for grilling (`grill-with-docs`):** Stress-test the `AMB-006` confidence threshold semantics and the "low confidence → forced doctor review" fallback; validate that a Hindi-quality floor can be expressed as a testable acceptance bar.
- **Target for `prototype`:** Throwaway voice→transcript→structured-fields pipeline against 2–3 candidate providers.
- **Target for `to-spec` & `to-tickets`:** Scope boundary = nothing ships; output is a decision record + go/no-go gate consumed by `PHASE-7` (LLM provider choice, timeout/retry, threshold constants).

---

### 2.1 Phase 1: Modular-Monolith Foundation & CI

- **Phase ID:** `PHASE-1-FOUNDATION`
- **Phase Strategic Objective:** Stand up the cost-floor modular monolith skeleton - monorepo, one FastAPI backend + async worker + shared Next.js frontend, single PostgreSQL with the 11-schema baseline, transactional-outbox round-trip, edge/gateway skeleton, and a CI/CD pipeline that enforces module isolation.
- **Release Readiness Criteria:** CI green on `lint` / `unit` / `migration-check` / `integration`; an **outbox → dispatcher → idempotent subscriber round-trip test** passes end-to-end; a hello-world route on each of the three frontends renders under the 1.5 MB page budget (`NFR-003`); the local native PostgreSQL (no Docker) serves integration tests; backup scaffolding job exists (`NFR-004` floor).

#### 1. In-Scope Modules & Features

| PRD Feature ID                                  | Feature Name         | Internal Module ID (Mod 6)                                                   | External Interface ID (Mod 5) |
| :---------------------------------------------- | :------------------- | :--------------------------------------------------------------------------- | :---------------------------- |
| - (infrastructure phase; no `FEAT-xxx` claimed) | All module scaffolds | `MOD-001`…`MOD-011` (empty bounded-context packages, facades, outbox tables) | -                             |

#### 2. Deferred / Out-of-Scope Items

- Any feature logic (all `FEAT-xxx` start from Phase 2 onward).
- Real external provider adapters (mocks only in CI).
- Persistent production hosting (launch env is Phase 14).

#### 3. Data Schema & Entity Delta (Phase Data Model)

- **Databases Introduced/Updated:** PostgreSQL instance provisioned (dev/staging); MinIO (S3-compatible) for PHI media; Redis optional.
- **Tables / Entities Created/Modified:** Baseline migration creates the **11 private schemas** (`iam`, `partner`, `health`, `consent`, `intake`, `care`, `diagnostics`, `fulfillment`, `settlement`, `notify`, `audit`) + the **outbox DDL template** (per-module `*_outbox` tables instantiated by each module's own migration from Phase 2 onward).
- **Migration Scripts:** `v0.0__bootstrap_schemas.sql` (schemas + outbox template); Alembic async baseline.

#### 4. Infrastructure, DevOps & Environment Targets

- **Hosting / Cloud Provisioning:** Local native PostgreSQL (no Docker). The staging VM with TLS termination (Caddy/nginx) behind the edge is **deferred** until a server is provisioned (see the CI/CD note below).
- **CI/CD Requirements:** GitHub Actions pipeline - lint (incl. **CI-enforced no-cross-schema-import rule**), unit tests, migration apply + seed on a throwaway DB, integration round-trip test. Verification stays on `main` via this pipeline alone; deploy-to-staging-on-merge and the staging-branch flow are future options once a staging server is provisioned.
- **Local test harness (established here):** pytest + vitest unit suites, integration tests vs a native PostgreSQL (no Docker), the **Playwright** E2E harness (established here; the first E2E spec and CI job land in Phase 2 with the patient auth routes, per roadmap §3.2 and the `.github/workflows/ci.yml` comment), `gitleaks`/`bandit`/`pip-audit` security scans, `alembic` single-head `migration-check`, all gated locally by **pre-commit** and runnable in CI via the same commands (`npm run test|lint|typecheck|scan|migration-check`; `.github/workflows/ci.yml`). See `docs/standards/coding-standards.md` §6.

#### 5. Phase Dependency & Risk Matrix

| Dependency / Blocked By         | Potential Risk                                                  | Mitigation Plan                                                                                |
| :------------------------------ | :-------------------------------------------------------------- | :--------------------------------------------------------------------------------------------- |
| None (phase 0 is advisory only) | Module-isolation discipline erodes later, violating whitebox §1 | CI lint blocks cross-schema imports / cross-schema FKs from day one                            |
| Cost floor (`NFR-001`)          | A paid framework or managed broker sneaks in                    | Tech stack locked in PR: FastAPI + SQLAlchemy 2.0 + PostgreSQL + Next.js, no paid dependencies |

#### 6. Downstream AI Engineering Handoff Specs

- **Target for grilling (`grill-with-docs`):** Validate the outbox/dispatcher at-least-once + idempotency contract and the DB-per-module isolation rule as the skeleton's non-negotiable seams.
- **Target for `prototype`:** The outbox round-trip harness (publish → poll → fan-out → idempotent dedupe).
- **Target for `to-spec` & `to-tickets`:** Scope boundary = scaffold packages per module (11), outbox utility, dispatcher, edge middleware (JWT-verify stub + rate-limit stub), migration harness, CI config. No business logic.

---

### 2.2 Phase 2: Patient Identity & Phone-OTP Authentication

- **Phase ID:** `PHASE-2-IAM-AUTH`
- **Phase Strategic Objective:** Deliver the patient identity core - phone-OTP registration with duplicate resolution, session JWT issuance/validation, RBAC scope enforcement at the edge - so every later phase has a trustworthy caller identity (`FEAT-001`).
- **Release Readiness Criteria:** E2E: register → OTP (mocked SMS) → verify → authenticated session → access a protected route; duplicate phone re-registration resolves to the existing identity; OTP single-use, 5-min TTL, ≥ 60 s resend cooldown; `validate_token` p95 < 100 ms (measured - pinned by a benchmark unit test, PHASE-2 REM T9 #79); `patient.auth_failed` and consent/access-denial attempts written to audit events (authenticated denials only - anonymous 401s stay log-only, PHASE-2 REM T7 #87).

#### 1. In-Scope Modules & Features

| PRD Feature ID | Feature Name                    | Internal Module ID (Mod 6)    | External Interface ID (Mod 5)            |
| :------------- | :------------------------------ | :---------------------------- | :--------------------------------------- |
| `FEAT-001`     | Patient Registration & Identity | `MOD-001` (Identity & Access) | `ACT-001` (Patient), `EXT-001` (SMS/OTP) |

#### 2. Deferred / Out-of-Scope Items

- Partner credential accounts & operator MFA (Phase 5).
- Stronger-than-OTP identity (open `GAP-001` - OTP baseline kept).
- Any record/consent behavior (Phase 3).

#### 3. Data Schema & Entity Delta (Phase Data Model)

- **Databases Introduced/Updated:** PostgreSQL `iam` schema.
- **Tables / Entities Created/Modified:** `identities` (phone_e164 unique, status Unverified/Active/Suspended), `otp_challenges` (hashed OTP, single-use, TTL 5 min, cooldown), `sessions` (jti, expiry, scope), `role_grants` (patient role), `iam_outbox`.
- **Migration Scripts:** `v1.0__init_iam.sql`.

#### 4. Infrastructure, DevOps & Environment Targets

- **Hosting / Cloud Provisioning:** `EXT-001` SMS provider key in staging (mock in CI); rate-limit config on `/otp` + `/auth` endpoints (`NFR-SEC-004`); OTP hashed at rest, never logged.
- **CI/CD Requirements:** Auth E2E suite runs against the mocked SMS adapter in CI; real-SMS smoke test gated to staging. The dev/test OTP read-back route `GET /v1/auth/dev/otp` (gated to the mock SMS adapter and `dev`/`test` environments) is kept so the E2E auth loop stays deterministic once SMS delivery moved off the request path; it is the only plaintext-OTP surface and never ships outside dev/test (PHASE-2 REM T4 #86). A repo-wide `check_event_names` gate enforces internal-modules.md §4.2 as the single source of truth for event names, so a drifted name (e.g. a legacy snake_case telemetry name) fails CI instead of silently desyncing code from the docs (PHASE-2 REM T1 #84).

#### 5. Phase Dependency & Risk Matrix

| Dependency / Blocked By            | Potential Risk                                           | Mitigation Plan                                                                  |
| :--------------------------------- | :------------------------------------------------------- | :------------------------------------------------------------------------------- |
| `PHASE-1` (skeleton, outbox, edge) | SMS gateway best-effort outage bricks logins (`NFR-004`) | Refresh path independent of SMS; resend gate; OTP stored hashed so retry is safe |
| `EXT-001` API key in dev           | Blocked local workflow                                   | In-CI mock adapter; provider key only in staging env vars                        |

#### 6. Downstream AI Engineering Handoff Specs

- **Target for grilling (`grill-with-docs`):** Brute-force / cooldown semantics on `resend_otp` + `verify_otp`; duplicate-identity resolution under concurrent registration (`FEAT-001` edge case).
- **Target for `prototype`:** Patient PWA registration/OTP screen (mobile-first, ≤ 1.5 MB).
- **Target for `to-spec` & `to-tickets`:** Scope boundary = `register_patient`, `verify_otp`, `resend_otp`, `issue_session`/`refresh`, `validate_token` + RBAC scope resolver + patient PWA auth routes. Nothing about records/consent.

---

### 2.3 Phase 3: Longitudinal Record & Consent Engine

- **Phase ID:** `PHASE-3-RECORD-CONSENT`
- **Phase Strategic Objective:** Build the trusted data core - the patient's single longitudinal record plus the per-action consent registry that gates every share - establishing the `check_consent` hot path every later module will call (`FEAT-002`).
- **Release Readiness Criteria:** On `patient.registered` (from Phase 2), a record shell + empty consent profile are created; consent request→grant→revoke→version transitions persist and are immediately effective; `check_consent` returns deny without a live grant (p95 < 50 ms); 100% of consent/record-access actions are emitted as audit events (`KPI-006`); the record is only readable by its owner or a live-consent counterparty.

#### 1. In-Scope Modules & Features

| PRD Feature ID | Feature Name                                    | Internal Module ID (Mod 6)            | External Interface ID (Mod 5) |
| :------------- | :---------------------------------------------- | :------------------------------------ | :---------------------------- |
| `FEAT-002`     | Longitudinal Health Record & Per-Action Consent | `MOD-003` (LHR) + `MOD-004` (Consent) | `ACT-001` (Patient)           |

#### 2. Deferred / Out-of-Scope Items

- Append-only audit _engine_ (Phase 4) - this phase only emits audit events.
- Chronic metrics & follow-ups (Phase 12); record entries from prescriptions/reports (phases 8–9 events).
- Deletion/retention/portability decisions (open `GAP-005`/`GAP-013` - record retained for account life; operator-mediated deletion).

#### 3. Data Schema & Entity Delta (Phase Data Model)

- **Databases Introduced/Updated:** PostgreSQL `health` + `consent` schemas.
- **Tables / Entities Created/Modified:** `health`: `patient_records`, `record_entries`, `record_access_history`, `health_outbox`; `consent`: `consents` (patient_id, counterparty_type/id, record_scope, status, version), `consent_events` (requested/granted/revoked), `egress_log`, `consent_outbox`.
- **Migration Scripts:** `v2.0__init_health_consent.sql`.

#### 4. Infrastructure, DevOps & Environment Targets

- **Hosting / Cloud Provisioning:** Redis consent-status cache (optional, SQL fallback); object-storage prefixes reserved for `MOD-003` attachments (not yet written).
- **CI/CD Requirements:** Consent-state-machine property tests + `check_consent` latency check in CI; audit-event emission asserted.

#### 5. Phase Dependency & Risk Matrix

| Dependency / Blocked By                       | Potential Risk                                     | Mitigation Plan                                                                                       |
| :-------------------------------------------- | :------------------------------------------------- | :---------------------------------------------------------------------------------------------------- |
| `PHASE-2` (`patient.registered` event)        | Consent-gate hot-path latency degrades every share | `check_consent` cached + p95 < 50 ms budget; revocation written durably before grant treated inactive |
| Open `GAP-013` (consent versioning specifics) | Behavior drift if decision changes                 | Implement the PRD baseline (re-grant = new version) and flag for grilling                             |

#### 6. Downstream AI Engineering Handoff Specs

- **Target for grilling (`grill-with-docs`):** Revocation semantics (future sharing stops, previously shared data handling), consent versioning, `egress_log` scope, and the `check_consent` contract consumed by `MOD-005`/`MOD-006`/`MOD-007`.
- **Target for `prototype`:** Per-action consent grant/revoke UX in the patient PWA.
- **Target for `to-spec` & `to-tickets`:** Scope boundary = `create_record`, `get_own_record` (owner-only), `request/grant/revoke_consent`, `check_consent`, `list_consents`, `list_egress_log`; record shell on `patient.registered`. No audit queries yet.

---

### 2.4 Phase 4: Append-Only Audit Trail & Access History

- **Phase ID:** `PHASE-4-AUDIT-ENGINE`
- **Phase Strategic Objective:** Deliver the compliance backbone - an append-only, hash-chained audit engine with tamper detection, plus the patient access-history view, so every regulated act across the system can be demonstrated (`FEAT-003`, `FEAT-020`).
- **Release Readiness Criteria:** Audit events from IAM (auth failures/OTP), consent lifecycle, and record access are appended with `prev_hash` linkage; UPDATE/DELETE on `audit_events` is rejected at the DB level and the attempt recorded as a tamper event; operator audit query (RBAC all-records) and patient `get_access_history` (own record only) return complete, ordered results; tamper-detection E2E test passes.

#### 1. In-Scope Modules & Features

| PRD Feature ID | Feature Name                       | Internal Module ID (Mod 6)              | External Interface ID (Mod 5) |
| :------------- | :--------------------------------- | :-------------------------------------- | :---------------------------- |
| `FEAT-003`     | Patient Record Access & Audit View | `MOD-003` (LHR) + `MOD-011` (Audit)     | `ACT-001` (Patient)           |
| `FEAT-020`     | Audit Trail & Consent Lifecycle    | `MOD-011` (Audit) + `MOD-004` (Consent) | `ACT-005` (Operator)          |

#### 2. Deferred / Out-of-Scope Items

- Audit wiring for prescription/report/settlement/notification acts - built in their owning phases (8, 9, 11, 13), all funneling into the engine built here.
- Audit retention/expiry decision (open `GAP-011` - retained; expiry carried forward).

#### 3. Data Schema & Entity Delta (Phase Data Model)

- **Databases Introduced/Updated:** PostgreSQL `audit` schema.
- **Tables / Entities Created/Modified:** `audit_events` (event_type, actor_id, target_id, scope, timestamp, prev_hash, hash - append-only, DB-level revoke of UPDATE/DELETE), `tamper_attempts`, `audit_outbox`.
- **Migration Scripts:** `v3.0__init_audit.sql` (+ DB permission statements enforcing append-only).

#### 4. Infrastructure, DevOps & Environment Targets

- **Hosting / Cloud Provisioning:** None new - rides the Phase 1 stack; audit appends share the daily-backup durability floor (`NFR-004`).
- **CI/CD Requirements:** Hash-chain integrity test (replay all events, verify chain), tamper test, RBAC tests for `query_audit` / `get_access_history`.

#### 5. Phase Dependency & Risk Matrix

| Dependency / Blocked By               | Potential Risk                             | Mitigation Plan                                                                 |
| :------------------------------------ | :----------------------------------------- | :------------------------------------------------------------------------------ |
| `PHASE-2`/`PHASE-3` (event producers) | Append-only bypass via DB superuser or bug | DB-level revoke + hash-chain verification in CI + tamper attempt self-recording |
| Open `GAP-011` (retention)            | Re-audit cost if retention changes         | Retention as config, engine independent of it                                   |

#### 6. Downstream AI Engineering Handoff Specs

- **Target for grilling (`grill-with-docs`):** Tamper-detection guarantees, retention/expiry (open `GAP-011`), and what "regulated act" must include per `NFR-D01`.
- **Target for `prototype`:** Operator audit-view screens (filter by actor/type/scope) and patient access-history view.
- **Target for `to-spec` & `to-tickets`:** Scope boundary = audit append API + outbox consumer + hash chain, `query_audit`, `get_access_history`, `record_view_denied` handling, tamper detection. No partner/fulfillment audit wiring yet.

---

### 2.5 Phase 5: Partner Onboarding & Gated Activation

- **Phase ID:** `PHASE-5-PARTNER-ONBOARDING`
- **Phase Strategic Objective:** Let doctors, labs, and chemists register openly and be activated only after credential verification, with an operator console to run the gate - so no unverified partner can ever receive patients (`FEAT-014`, `FEAT-015`).
- **Release Readiness Criteria:** Partner register → submit credentials → `[Under Verification]` → operator approve/reject → `[Active]`/`[Rejected]`; rejected partners notified of the specific failure; activation state published as `partner.activated`/`partner.rejected` and consumed by `MOD-001` (role grant/deny); every operator decision audited; verification queue sortable by registration age (KPI-004 input); operator login requires MFA.

#### 1. In-Scope Modules & Features

| PRD Feature ID | Feature Name                                 | Internal Module ID (Mod 6)                 | External Interface ID (Mod 5) |
| :------------- | :------------------------------------------- | :----------------------------------------- | :---------------------------- |
| `FEAT-014`     | Open Registration & Gated Activation         | `MOD-002` (Partner) + `MOD-001` (accounts) | `ACT-002/003/004` (partners)  |
| `FEAT-015`     | Operator Console - Verification & Moderation | `MOD-002` (Partner) + `MOD-011` (Audit)    | `ACT-005` (Operator)          |

#### 2. Deferred / Out-of-Scope Items

- Directory search / profiles (Phase 6).
- Automated credential expiry/revocation detection (Phase 6).
- Verification mechanism beyond baseline (`AMB-003` - automated checks + manual review for flagged cases).

#### 3. Data Schema & Entity Delta (Phase Data Model)

- **Databases Introduced/Updated:** PostgreSQL `partner` schema; `iam` extended.
- **Tables / Entities Created/Modified:** `partner`: `partner_profiles` (type doctor|lab|chemist, status), `partner_credentials` (registration/license refs, verified flag, expiry), `partner_verifications` (queue, status, decision), `service_areas`, `partner_outbox`; `iam`: `role_grants` extended for partner + operator roles and MFA fields.
- **Migration Scripts:** `v4.0__init_partner.sql`, `v4.1__iam_roles_mfa.sql`.

#### 4. Infrastructure, DevOps & Environment Targets

- **Hosting / Cloud Provisioning:** Operator Console route group in the shared Next.js deploy (role-scoped); credential document upload to object storage `partner/` prefix.
- **CI/CD Requirements:** Activation state-machine tests; RBAC tests for operator-only `operator_decision`; audit of every decision.

#### 5. Phase Dependency & Risk Matrix

| Dependency / Blocked By              | Potential Risk                                      | Mitigation Plan                                                                |
| :----------------------------------- | :-------------------------------------------------- | :----------------------------------------------------------------------------- |
| `PHASE-2` (IAM credential accounts)  | Manual-review headcount blows `NFR-001` (`AMB-003`) | Automated checks default; manual only for flagged cases; KPI-004 ≤ 48 h median |
| Real credential verification sources | Local partner docs not machine-verifiable           | Accept uploaded credential artifacts; operator review queue                    |

#### 6. Downstream AI Engineering Handoff Specs

- **Target for grilling (`grill-with-docs`):** `AMB-003` verification automation vs. manual split; deactivation semantics on failed re-verification.
- **Target for `prototype`:** Operator verification queue (approve/reject, flag, priority-by-age) and partner registration form.
- **Target for `to-spec` & `to-tickets`:** Scope boundary = `register_partner`, `submit_credentials`, `list_verification_queue`, `operator_decision`, role grant/deny on activation events, operator MFA login. No directory search.

---

### 2.6 Phase 6: Provider Directory & Profiles

- **Phase ID:** `PHASE-6-DIRECTORY`
- **Phase Strategic Objective:** Let patients find and trust providers - distance-sorted search over **activated-only** partners with verified credential display, and automatic deactivation when a credential expires or is revoked (`FEAT-004`, `FEAT-005`).
- **Release Readiness Criteria:** Search within Daltonganj + peri-urban returns only `[Active]` partners, sorted by distance (p95 < 250 ms cached); profile shows verified credentials + "verified" indicator; on credential expiry/revocation the partner is deindexed and the indicator removed; empty state shows "no providers found" + adjacent-area results; `directory_search` / `provider_selected` / `credential_invalidated` events emitted.

#### 1. In-Scope Modules & Features

| PRD Feature ID | Feature Name                           | Internal Module ID (Mod 6)      | External Interface ID (Mod 5) |
| :------------- | :------------------------------------- | :------------------------------ | :---------------------------- |
| `FEAT-004`     | Provider Directory & Search            | `MOD-002` (Partner & Directory) | `ACT-001` (Patient)           |
| `FEAT-005`     | Provider Profiles & Credential Display | `MOD-002` (Partner & Directory) | `ACT-001`, `ACT-002/003/004`  |

#### 2. Deferred / Out-of-Scope Items

- Ratings/reviews, consultation slots, availability calendars.
- Multi-city geo expansion (`ISSUE-004` - Daltonganj only at launch).

#### 3. Data Schema & Entity Delta (Phase Data Model)

- **Databases Introduced/Updated:** PostgreSQL `partner` schema (extension).
- **Tables / Entities Created/Modified:** `directory_index` (geo point, specialties, active flag, service area), `partner_credentials` gains expiry/revoked fields + deactivation triggers.
- **Migration Scripts:** `v5.0__directory_index.sql` (PostGIS optional; SQL point/range fallback at cost floor).

#### 4. Infrastructure, DevOps & Environment Targets

- **Hosting / Cloud Provisioning:** Redis search cache (invalidated on activation/revocation); geo index in Postgres.
- **CI/CD Requirements:** Search-gating tests (deactivated partner never returned), credential-expiry deactivation test, geo-range tests.

#### 5. Phase Dependency & Risk Matrix

| Dependency / Blocked By        | Potential Risk                          | Mitigation Plan                                                                       |
| :----------------------------- | :-------------------------------------- | :------------------------------------------------------------------------------------ |
| `PHASE-5` (activated partners) | Geo accuracy in peri-urban Daltonganj   | SQL range fallback + explicit `service_areas`; no reliance on precise reverse-geocode |
| `REQ-028` gating rule          | Stale cache returns deactivated partner | Cache invalidation on `partner.activated`/`credential.invalidated` events             |

#### 6. Downstream AI Engineering Handoff Specs

- **Target for grilling (`grill-with-docs`):** "No results → adjacent providers" semantics; credential-expiry detection cadence; search relevance (specialty + distance weighting).
- **Target for `prototype`:** Directory list + provider profile screens (verified badge, credential display) on the patient PWA.
- **Target for `to-spec` & `to-tickets`:** Scope boundary = `search_directory`, `get_provider_profile`, `invalidate_credential` + deindex, directory_index caching. No bookings yet.

---

### 2.7 Phase 7: Symptom Intake & AI Pre-Summary

- **Phase ID:** `PHASE-7-INTAKE-AI`
- **Phase Strategic Objective:** Capture symptoms by voice or text in English/Hindi and turn them into a structured, consent-gated, budget-metered clinical pre-summary that the doctor will review before consulting (`FEAT-006`, `FEAT-007`).
- **Release Readiness Criteria:** Voice and text intake both captured (`intake_started`/`intake_captured`), upload-resilient (auto-retry ×3, unusable audio prompts re-record); AI pipeline transcribe→structure produces a pre-summary; low-confidence output is flagged "low confidence - verify" and forces doctor review; `EXT-002` call timeouts ≤ 30 s and degrade gracefully (never block the loop); every LLM egress is consent-gated via `check_consent` + PHI-minimized (never the full record) and lands in audit; AI spend metered against `NFR-001`.

#### 1. In-Scope Modules & Features

| PRD Feature ID | Feature Name                       | Internal Module ID (Mod 6) | External Interface ID (Mod 5) |
| :------------- | :--------------------------------- | :------------------------- | :---------------------------- |
| `FEAT-006`     | Symptom Intake - Voice & Text      | `MOD-005` (Intake & AI)    | `ACT-001` (Patient)           |
| `FEAT-007`     | AI Clinical Pre-Summary Generation | `MOD-005` (Intake & AI)    | `EXT-002` (LLM/AI Provider)   |

_Also built here (verified in `PHASE-8`):_ `MOD-005` `request_rx_draft` facade for the e-prescription drafting input.

#### 2. Deferred / Out-of-Scope Items

- The rx-draft → doctor-approval flow (Phase 8).
- ASR tuning beyond the Phase 0 spike; any paid LLM tier beyond the freemium budget.

#### 3. Data Schema & Entity Delta (Phase Data Model)

- **Databases Introduced/Updated:** PostgreSQL `intake` schema; object storage `intake/` prefix.
- **Tables / Entities Created/Modified:** `intakes` (mode voice|text, language hi|en, status Captured/Structuring/Ready for Review/Re-record), `pre_summaries` (structured fields, confidence, review state Draft/Reviewed/Final), `ai_jobs` (provider, tokens, ₹cost, status), `media_refs`, `intake_outbox`.
- **Migration Scripts:** `v6.0__init_intake.sql`.

#### 4. Infrastructure, DevOps & Environment Targets

- **Hosting / Cloud Provisioning:** `EXT-002` freemium provider key (chosen in Phase 0); hard token/₹ budget meter + alert (`NFR-001`); bucket policies restricting `intake/` to `MOD-005`.
- **CI/CD Requirements:** AI pipeline tests against a mock `EXT-002` (deterministic confidence), low-confidence fallback test, budget-meter overrun test, upload-resilience test (≥ 1 Mbps, 3 retries).

#### 5. Phase Dependency & Risk Matrix

| Dependency / Blocked By                 | Potential Risk                                 | Mitigation Plan                                                            |
| :-------------------------------------- | :--------------------------------------------- | :------------------------------------------------------------------------- |
| `PHASE-0` (go/no-go gate)               | Hindi ASR quality below floor on low-cost tier | No-go → text-first intake fallback; forced doctor review on low confidence |
| `PHASE-2`/`PHASE-3` (identity, consent) | PHI egress to `EXT-002` violates `NFR-SEC-006` | `check_consent` gate + PHI-minimized context + audit `egress_log`          |
| `EXT-002` latency/freemium quota        | LLM outage or cost blowout blocks intake       | ≤ 30 s timeout, 3 retries, degrade to review path; budget meter hard-stop  |

#### 6. Downstream AI Engineering Handoff Specs

- **Target for grilling (`grill-with-docs`):** `AMB-006` threshold placement; PHI-minimization boundary for `transcribe`/`structure` payloads; degradation semantics when the LLM is down mid-intake.
- **Target for `prototype`:** Voice recorder + upload-resilient intake screen (hi/en toggle).
- **Target for `to-spec` & `to-tickets`:** Scope boundary = `submit_intake`, `get_intake`, `get_pre_summary`, `mark_pre_summary_reviewed`, `request_rx_draft` (facade), AI pipeline worker + budget meter, intake PWA screen.

---

### 2.8 Phase 8: Care Case, Consult Handshake & E-Prescription

- **Phase ID:** `PHASE-8-CARE-RX`
- **Phase Strategic Objective:** Orchestrate the off-platform consult handshake into an on-platform e-prescription that is only ever issued under a licensed doctor's explicit approval - the highest-regulatory-stakes slice (`FEAT-008`, `FEAT-009`).
- **Release Readiness Criteria:** Doctor marks consult complete only after a finalized pre-summary (else blocked); case moves Pre-Summary → Consult Complete → Prescription Pending; AI draft produced from voice note/photo; doctor edits recorded (`edited_yn`) and approval issues the prescription timestamped + attributed; reject path recorded; **hard gate test: zero prescriptions issued without doctor approval** (`REQ-023`); `prescription.approved` event published for downstream phases.

#### 1. In-Scope Modules & Features

| PRD Feature ID | Feature Name                                   | Internal Module ID (Mod 6)    | External Interface ID (Mod 5) |
| :------------- | :--------------------------------------------- | :---------------------------- | :---------------------------- |
| `FEAT-008`     | Consult Orchestration & Off-Platform Handshake | `MOD-006` (Care Case & Rx)    | `ACT-002` (Doctor)            |
| `FEAT-009`     | E-Prescription - AI Draft & Doctor Approval    | `MOD-006` + `MOD-005` (draft) | `ACT-002`, `EXT-002`          |

#### 2. Deferred / Out-of-Scope Items

- Patient-initiated handshake (open `CFL-003` - doctor-initiated baseline kept).
- Regulatory sign-off beyond the baseline (open `CFL-002`/`RISK-EVAL-003` - AI as drafting assistant under doctor authority).

#### 3. Data Schema & Entity Delta (Phase Data Model)

- **Databases Introduced/Updated:** PostgreSQL `care` schema; object storage `rx_input/` prefix.
- **Tables / Entities Created/Modified:** `cases` (patient, doctor, stage), `prescriptions` (status Draft/Doctor Reviewed/Approved & Issued/Fulfilled, issued_at, attributed_doctor), `rx_items` (name, dose, duration), `rx_approvals` (doctor_id, edited_yn, decision, reason), `doctor_inputs` (voice_note/photo refs), `care_outbox`.
- **Migration Scripts:** `v7.0__init_care.sql`.

#### 4. Infrastructure, DevOps & Environment Targets

- **Hosting / Cloud Provisioning:** Doctor channel (ACT-002) route group in the shared Next.js deploy; object storage `rx_input/` for doctor media.
- **CI/CD Requirements:** Case-state-machine tests (incl. pre-summary-required gate), approval-gate hard test, doctor-RBAC tests, audit of issuance/rejection.

#### 5. Phase Dependency & Risk Matrix

| Dependency / Blocked By       | Potential Risk                                                | Mitigation Plan                                                                       |
| :---------------------------- | :------------------------------------------------------------ | :------------------------------------------------------------------------------------ |
| `PHASE-7` (pre-summary)       | AI-drafted prescription regulatory exposure (`RISK-EVAL-003`) | Doctor approval gate before issuance (hard test); compliance note carried to Phase 14 |
| `PHASE-3` (consented history) | Drafting reads history without consent                        | `read_consented_history` gated by `check_consent`                                     |
| Open `CFL-002`                | Baseline posture changes later                                | Build draft/edit/approve seam so a stricter gate slots in without redesign            |

#### 6. Downstream AI Engineering Handoff Specs

- **Target for grilling (`grill-with-docs`):** `CFL-002`/`RISK-EVAL-003` regulatory posture of AI drafts; `CFL-003` handshake initiator; the edit-then-approve audit trail.
- **Target for `prototype`:** Doctor review/approve screen (voice note + photo input, editable draft items, approve/reject).
- **Target for `to-spec` & `to-tickets`:** Scope boundary = `mark_consult_complete`, `list_doctor_cases`, `submit_doctor_input`, `approve_prescription`, `reject_prescription`, `get_approved_prescription`, case/rx state machines.

---

### 2.9 Phase 9: Diagnostics Booking & Report Match/Filing

- **Phase ID:** `PHASE-9-DIAGNOSTICS`
- **Phase Strategic Objective:** Let patients book diagnostics (home pickup / partner lab / direct fallback) and guarantee a lab report is matched to its order and patient before it ever touches the record - the `KPI-003` zero-mis-attachment slice (`FEAT-010`, `FEAT-011`).
- **Release Readiness Criteria:** Booking on-platform (home pickup / pickup point) routed to an activated lab; direct patient-to-lab fallback recorded; sample-collected → result-pending transitions; upload (lab or patient) matched via order-ID + patient confirmation; mismatch is rejected visibly and never filed; matched report filed into the patient's record via event; **mis-attachment E2E test = 0**; upload scanning at the edge; `report.filed` / `report.rejected_mismatch` events published.

#### 1. In-Scope Modules & Features

| PRD Feature ID | Feature Name                                | Internal Module ID (Mod 6) | External Interface ID (Mod 5) |
| :------------- | :------------------------------------------ | :------------------------- | :---------------------------- |
| `FEAT-010`     | Diagnostics Booking & Sample Pickup         | `MOD-007` (Diagnostics)    | `ACT-001`, `ACT-003` (Lab)    |
| `FEAT-011`     | Lab Report Filing & Wrong-Upload Protection | `MOD-007` (Diagnostics)    | `ACT-001`, `ACT-003`          |

#### 2. Deferred / Out-of-Scope Items

- Lab-report baseline parsing (`REQ-026` - filing only at launch).
- Critical-value escalation (`REQ-033` - interpretation left to patient/doctor).

#### 3. Data Schema & Entity Delta (Phase Data Model)

- **Databases Introduced/Updated:** PostgreSQL `diagnostics` schema; object storage `reports/` prefix.
- **Tables / Entities Created/Modified:** `diagnostic_orders` (patient, lab, mode home|pickup_point|direct, state), `sample_pickups`, `lab_reports` (status, matched, filed), `report_uploads` (uploader_type lab|patient, checksums), `upload_matches` (match_method), `diagnostics_outbox`.
- **Migration Scripts:** `v8.0__init_diagnostics.sql`.

#### 4. Infrastructure, DevOps & Environment Targets

- **Hosting / Cloud Provisioning:** Upload scanning hook at the edge (`NFR-SEC-004`); object-storage prefix `reports/` restricted to `MOD-007`.
- **CI/CD Requirements:** Match-before-file hard test, mismatch-reject test, order state-machine tests, upload scanning + size/content-type validation tests.

#### 5. Phase Dependency & Risk Matrix

| Dependency / Blocked By                    | Potential Risk                                            | Mitigation Plan                                                                  |
| :----------------------------------------- | :-------------------------------------------------------- | :------------------------------------------------------------------------------- |
| `PHASE-5` (activated lab partner)          | Wrong report attached to wrong patient (`RISK-002`, high) | Order-ID binding + patient confirmation before filing; 0-mis-attachment KPI test |
| `PHASE-3` (record filing via event)        | Direct write into `health` breaks isolation               | `MOD-007` publishes `report.filed`; `MOD-003` consumes and files                 |
| Open `GAP-004`/`GAP-008` (match mechanism) | Matching rule change                                      | Match seam abstracted behind `upload_matches.match_method`                       |

#### 6. Downstream AI Engineering Handoff Specs

- **Target for grilling (`grill-with-docs`):** `GAP-004`/`GAP-008` matching semantics (order-ID + patient confirmation), mismatch UX, and the re-upload path.
- **Target for `prototype`:** Upload + match-confirmation flow for lab and patient; mismatch error state.
- **Target for `to-spec` & `to-tickets`:** Scope boundary = `book_diagnostic`, `confirm_pickup`, `collect_sample`, `upload_report`, `confirm_report_match`, `get_order`, report filing event flow.

---

### 2.10 Phase 10: Pharmacy Fulfillment & Delivery

- **Phase ID:** `PHASE-10-FULFILLMENT`
- **Phase Strategic Objective:** Route approved e-prescriptions to the patient's chosen/nearest chemist and track zero-inventory fulfilment, with the patient always deciding on out-of-stock and delivery failures so care never silently stalls (`FEAT-012`, `FEAT-013`).
- **Release Readiness Criteria:** Approved rx routed (chosen|nearest); chemist prepares → out-for-delivery → delivered with status events; out-of-stock notifies patient who chooses partial or cancel; delivery/pickup failure offers off-platform vs platform retry, choice recorded; every event published for notifications (sent in Phase 13); fulfilment success rate tracked (KPI-002); partner response latency measured (KPI-008 input).

#### 1. In-Scope Modules & Features

| PRD Feature ID | Feature Name                             | Internal Module ID (Mod 6)       | External Interface ID (Mod 5) |
| :------------- | :--------------------------------------- | :------------------------------- | :---------------------------- |
| `FEAT-012`     | Medicine Fulfillment Routing             | `MOD-008` (Pharmacy Fulfillment) | `ACT-004` (Chemist)           |
| `FEAT-013`     | Out-of-Stock & Delivery-Failure Handling | `MOD-008` (Pharmacy Fulfillment) | `ACT-001`, `ACT-004`          |

#### 2. Deferred / Out-of-Scope Items

- Time-bound partner-action SLA (open `GAP-007` - no commitment time; latency measured).
- Geofenced auto-routing to the nearest chemist (route_basis supports both chosen and nearest).

#### 3. Data Schema & Entity Delta (Phase Data Model)

- **Databases Introduced/Updated:** PostgreSQL `fulfillment` schema.
- **Tables / Entities Created/Modified:** `fulfillment_orders` (rx_id, chemist_id, route_basis, state), `fulfillment_events` (preparing/out_for_delivery/delivered), `out_of_stock_items` (item_ids), `patient_choices` (partial|cancel, off_platform|platform), `fulfillment_outbox`.
- **Migration Scripts:** `v9.0__init_fulfillment.sql`.

#### 4. Infrastructure, DevOps & Environment Targets

- **Hosting / Cloud Provisioning:** Chemist channel (ACT-004) route group in the shared Next.js deploy.
- **CI/CD Requirements:** Fulfilment state-machine tests (incl. partial/cancel branches), patient-choice recording tests, routing-gate test (approved rx only).

#### 5. Phase Dependency & Risk Matrix

| Dependency / Blocked By            | Potential Risk                  | Mitigation Plan                                                                                        |
| :--------------------------------- | :------------------------------ | :----------------------------------------------------------------------------------------------------- |
| `PHASE-8` (approved rx via facade) | Chemist works a non-approved rx | `get_approved_prescription` gate via `MOD-006` facade; state machine starts only from `[Rx: Approved]` |
| Open `GAP-007`                     | No SLA → perceived stall        | Patient always notified + chooses; latency recorded for `KPI-008`                                      |

#### 6. Downstream AI Engineering Handoff Specs

- **Target for grilling (`grill-with-docs`):** `GAP-007` partner-SLA stance; out-of-stock partial/cancel semantics; delivery-failure retry-path rules.
- **Target for `prototype`:** Chemist fulfilment status console + patient choice dialogs (partial vs cancel, off-platform vs platform retry).
- **Target for `to-spec` & `to-tickets`:** Scope boundary = `route_prescription`, `update_fulfillment`, `report_out_of_stock`, `record_patient_choice`, `report_delivery_failure`, `record_retry_path`.

---

### 2.11 Phase 11: Settlement, Cancellations & Refunds

- **Phase ID:** `PHASE-11-SETTLEMENT`
- **Phase Strategic Objective:** Record direct cash/UPI settlement outcomes (the primary path), support the platform-facilitated UPI exception on a fraud-risk signal, and keep cancellations/refunds entirely partner-direct - the platform holds no funds and processes no refunds (`FEAT-016`, `FEAT-017`).
- **Release Readiness Criteria:** Direct settlement outcome recorded (`settlement_recorded`); facilitated path only when both parties opt in + risk signal, with `EXT-004` initiation + HMAC-verified, idempotent webhook (no double charge; replay-safe); gateway unavailable → fallback to direct cash/UPI with a risk note; cancellation policy displayed before booking; cancellation → `[Order: Cancelled]` → partner-direct refund recorded; `RISK-001` mitigated by direct-payment-primary posture.

#### 1. In-Scope Modules & Features

| PRD Feature ID | Feature Name            | Internal Module ID (Mod 6) | External Interface ID (Mod 5)         |
| :------------- | :---------------------- | :------------------------- | :------------------------------------ |
| `FEAT-016`     | Settlement & Payments   | `MOD-009` (Settlement)     | `ACT-001/003/004`, `EXT-004` (UPI GW) |
| `FEAT-017`     | Cancellations & Refunds | `MOD-009` (Settlement)     | `ACT-001`                             |

#### 2. Deferred / Out-of-Scope Items

- Partner-issued receipts / reconciliation detail beyond recording (open `GAP-010`).
- Fraud-risk trigger tuning beyond the baseline (open `AMB-004`/`CFL-001` - opt-in + risk signal).

#### 3. Data Schema & Entity Delta (Phase Data Model)

- **Databases Introduced/Updated:** PostgreSQL `settlement` schema.
- **Tables / Entities Created/Modified:** `settlements` (order_ref, type cash|upi|platform_facilitated, amount_paise, status), `payment_intents` (idempotency_key, payment_ref, upi status), `webhook_events` (HMAC-verified, dedupe on payment_ref), `cancellations` (cancelled_by), `refund_records` (partner-direct), `cancellation_policies` (per partner/service), `settlement_outbox`.
- **Migration Scripts:** `v10.0__init_settlement.sql`.

#### 4. Infrastructure, DevOps & Environment Targets

- **Hosting / Cloud Provisioning:** `EXT-004` sandbox credentials + HMAC webhook secrets; webhook endpoint hardening (signature verify, idempotency).
- **CI/CD Requirements:** Webhook replay/dedupe tests, idempotency-key test (no double charge), HMAC-signature-verification test, cancellation-policy-display test.

#### 5. Phase Dependency & Risk Matrix

| Dependency / Blocked By             | Potential Risk                             | Mitigation Plan                                                                              |
| :---------------------------------- | :----------------------------------------- | :------------------------------------------------------------------------------------------- |
| `PHASE-8`/`PHASE-9` (order context) | Double charge / payment fraud (`RISK-001`) | Idempotency key per order; direct cash/UPI primary; facilitated only on opt-in + risk signal |
| `EXT-004` gateway outage            | Facilitated path unavailable               | Fallback to direct cash/UPI with risk note (PRD §5.2)                                        |
| Open `AMB-004`/`CFL-001`            | Risk-trigger tuning                        | Trigger as config; audit every facilitated case                                              |

#### 6. Downstream AI Engineering Handoff Specs

- **Target for grilling (`grill-with-docs`):** `AMB-004`/`CFL-001` fraud-risk trigger; `GAP-010` receipt/reconciliation posture; webhook replay-safety guarantees.
- **Target for `prototype`:** Cancellation-policy display at booking; settlement outcome confirmation UX.
- **Target for `to-spec` & `to-tickets`:** Scope boundary = `record_settlement`, `initiate_facilitated_payment`, `get_cancellation_policy`, `cancel_order`, `record_partner_refund`, UPI webhook consumer.

---

### 2.12 Phase 12: Chronic Care Loop - Metrics & Follow-Ups

- **Phase ID:** `PHASE-12-CHRONIC-CARE`
- **Phase Strategic Objective:** Turn the platform into a continuous-care differentiator - daily BP/sugar logging stored in the longitudinal record, out-of-range surfacing with **no automated clinical action**, and follow-up plans that emit re-test nudges (`FEAT-018`).
- **Release Readiness Criteria:** Enrolled patient logs BP and/or sugar; values persist in the record and render on the tracking view; out-of-range values stored + surfaced, no automated clinical action (`REQ-033`); follow-up plans (30d/90d) evaluate and emit `follow_up.due` events; `metric.logged` / `metric_out_of_range` / `follow_up.due` events published (consumed by Phase 13).

#### 1. In-Scope Modules & Features

| PRD Feature ID | Feature Name                        | Internal Module ID (Mod 6)                              | External Interface ID (Mod 5) |
| :------------- | :---------------------------------- | :------------------------------------------------------ | :---------------------------- |
| `FEAT-018`     | Chronic Metric Logging & Follow-Ups | `MOD-003` (LHR) + `MOD-010` (Notify, scheduling inputs) | `ACT-001` (Patient)           |

#### 2. Deferred / Out-of-Scope Items

- WhatsApp nudges/dosage reminders (Phase 13).
- On-platform doctor Q&A as the follow-up counterparty (open `CFL-004`/`AMB-005` - self-service baseline).

#### 3. Data Schema & Entity Delta (Phase Data Model)

- **Databases Introduced/Updated:** PostgreSQL `health` schema (extension).
- **Tables / Entities Created/Modified:** `chronic_metrics` (patient_id, metric_type bp|sugar, value, out-of-range flag, timestamp), `follow_up_plans` (type 30d|90d, due timestamps), `health_outbox` (reuse).
- **Migration Scripts:** `v11.0__chronic_metrics.sql`.

#### 4. Infrastructure, DevOps & Environment Targets

- **Hosting / Cloud Provisioning:** Follow-up due-eval job in the async worker (APScheduler cron).
- **CI/CD Requirements:** Metric-logging state-machine tests, out-of-range surfacing tests, follow-up due-eval + event-emission tests.

#### 5. Phase Dependency & Risk Matrix

| Dependency / Blocked By           | Potential Risk                        | Mitigation Plan                                                   |
| :-------------------------------- | :------------------------------------ | :---------------------------------------------------------------- |
| `PHASE-3` (health schema, record) | Low weekly engagement (KPI-005)       | Nudges in Phase 13; out-of-range surfacing keeps the loop visible |
| Open `CFL-004`/`AMB-005`          | Follow-up counterparty decision later | Self-service baseline; seam for re-booking/doctor Q&A             |

#### 6. Downstream AI Engineering Handoff Specs

- **Target for grilling (`grill-with-docs`):** `CFL-004`/`AMB-005` follow-up counterparty; safe-range surfacing without clinical-action creep (`REQ-033`).
- **Target for `prototype`:** Daily BP/sugar logging + tracking view on the patient PWA.
- **Target for `to-spec` & `to-tickets`:** Scope boundary = `log_metric`, `get_follow_up_plan`, follow-up due-eval job, `follow_up.due` event. No WhatsApp sends.

---

### 2.13 Phase 13: WhatsApp Notifications

- **Phase ID:** `PHASE-13-NOTIFICATIONS`
- **Phase Strategic Objective:** Deliver dosage reminders and 30/90-day re-test nudges on WhatsApp in the patient's language - **notifications only**, no interaction or transaction there (`REQ-035`) - with signed delivery callbacks and graceful failure (`FEAT-019`).
- **Release Readiness Criteria:** Templates (dosage_reminder, retest_30, retest_90; hi/en) configured against `EXT-003`; scheduling from rx dosage schedules + `follow_up.due`; send → delivery-status callback (signature-verified) → Delivered/Failed; failure logged, retried at next slot, repeated failure prompts number confirmation; **inbound non-template messages never trigger clinical/transactional workflows** (hard test); in-app inbox mirrors sends; every send recorded in audit.

#### 1. In-Scope Modules & Features

| PRD Feature ID | Feature Name           | Internal Module ID (Mod 6) | External Interface ID (Mod 5)                |
| :------------- | :--------------------- | :------------------------- | :------------------------------------------- |
| `FEAT-019`     | WhatsApp Notifications | `MOD-010` (Notifications)  | `ACT-001`, `EXT-003` (WhatsApp Business API) |

#### 2. Deferred / Out-of-Scope Items

- WhatsApp-first patient channel (`REQ-040`, `[FUTURE]`).
- Transactional/interactive WhatsApp flows (explicitly excluded by `REQ-035`).

#### 3. Data Schema & Entity Delta (Phase Data Model)

- **Databases Introduced/Updated:** PostgreSQL `notify` schema.
- **Tables / Entities Created/Modified:** `notifications` (type dosage|retest_30|retest_90|in_app, channel wa|inapp, status), `notification_schedules` (due timestamps), `delivery_logs` (message_id, status, error_code), `notify_outbox`.
- **Migration Scripts:** `v12.0__init_notify.sql`.

#### 4. Infrastructure, DevOps & Environment Targets

- **Hosting / Cloud Provisioning:** `EXT-003` sandbox/test number + India DLT template registration; webhook signature-verification secrets; APScheduler cron for nudges.
- **CI/CD Requirements:** Template-parameter tests, callback-signature-verification test (bad signature rejected), notification-only posture test (non-template inbound ignored), failure-retry + number-confirm tests.

#### 5. Phase Dependency & Risk Matrix

| Dependency / Blocked By                              | Potential Risk                       | Mitigation Plan                                                              |
| :--------------------------------------------------- | :----------------------------------- | :--------------------------------------------------------------------------- |
| `PHASE-8` (rx schedules), `PHASE-12` (follow_up.due) | DLT/template approval delays         | Start sandbox + template submission early; template content frozen           |
| `EXT-003` rate limits / delivery failure             | Notifications silently dropped       | Failure logged + retry next slot + number-confirmation prompt                |
| Inbound callback abuse                               | Forged callbacks flip delivery state | Signature verification (`NFR-SEC-005`) + idempotent delivery-status handling |

#### 6. Downstream AI Engineering Handoff Specs

- **Target for grilling (`grill-with-docs`):** `REQ-035` notifications-only boundary (what a callback must never do); retry/backoff policy; number-confirmation flow.
- **Target for `prototype`:** Template delivery rendering (hi/en) + in-app inbox.
- **Target for `to-spec` & `to-tickets`:** Scope boundary = `schedule_notification`, `send_now`, `list_inbox`, `mark_read`, EXT-003 webhook consumer, scheduler jobs.

---

### 2.14 Phase 14: End-to-End Integration, Observability & Release Readiness

- **Phase ID:** `PHASE-14-E2E-RELEASE`
- **Phase Strategic Objective:** Prove the complete care loop end-to-end (intake → consult → diagnostics → prescription → delivery → settlement → chronic care), verify compliance/durability/cost floors, and harden the Daltonganj production environment for launch.
- **Release Readiness Criteria:** Full-loop E2E test suite passes (loop stages 1–10 from PRD §5.1; stage-timestamp deltas recorded for `KPI-008`); cross-module audit wiring verified (every regulated act present in the append-only trail); backup ≥ daily + monthly restore-validation drill passes (`NFR-004`, `GAP-012`); cost telemetry shows monthly spend within `NFR-001`/`KPI-007`; load check meets `NFR-003` page budget; launch runbook + staging→prod promotion complete.

#### 1. In-Scope Modules & Features

| PRD Feature ID            | Feature Name                              | Internal Module ID (Mod 6) | External Interface ID (Mod 5)                |
| :------------------------ | :---------------------------------------- | :------------------------- | :------------------------------------------- |
| All `FEAT-001`–`FEAT-020` | Full care loop (integration verification) | All `MOD-001`–`MOD-011`    | All `ACT-001`–`ACT-005`, `EXT-001`–`EXT-004` |

#### 2. Deferred / Out-of-Scope Items

- Geographic expansion beyond Daltonganj (open `ISSUE-004`).
- `REQ-026` baseline parsing, `REQ-038` ABHA, `REQ-039` monetization, `REQ-040` native/WhatsApp-first (all carried forward).

#### 3. Data Schema & Entity Delta (Phase Data Model)

- **Databases Introduced/Updated:** PostgreSQL `ops` schema (telemetry only - non-domain).
- **Tables / Entities Created/Modified:** `cost_meters` (monthly spend per provider vs `NFR-001` budget), `restore_validations` (monthly drill log), `e2e_runs` (loop-stage timestamps for `KPI-008`).
- **Migration Scripts:** `v13.0__ops_telemetry.sql`.

#### 4. Infrastructure, DevOps & Environment Targets

- **Hosting / Cloud Provisioning:** Production single VM (FastAPI + worker + Next.js + Postgres + MinIO), TLS 1.2+, backup cron (RPO ≤ 24 h) + monthly restore drill, observability stack (logs, metrics, alerts), cost-alert wiring.
- **CI/CD Requirements:** E2E suite runs on every merge + nightly on staging; release gate = E2E green + restore drill green + cost-under-budget check.

#### 5. Phase Dependency & Risk Matrix

| Dependency / Blocked By         | Potential Risk                                     | Mitigation Plan                                                  |
| :------------------------------ | :------------------------------------------------- | :--------------------------------------------------------------- |
| All phases 1–13                 | Integration gaps between module seams              | Full-loop E2E + stage-timestamp deltas; audit completeness check |
| Open `AMB-002` (acceptance bar) | "Full care loop proven" bar undefined              | Use PRD §1.3 proposed targets; revisit post-launch               |
| `NFR-004` durability            | Data loss on longitudinal record (`RISK-EVAL-005`) | Daily backups + validated monthly restore drill before launch    |

#### 6. Downstream AI Engineering Handoff Specs

- **Target for grilling (`grill-with-docs`):** `AMB-002` acceptance bar; launch checklist completeness; residual open decisions (`GAP-005/011/013`, `CFL-001/002/003/004`, `AMB-003/004/006`) that must NOT block launch.
- **Target for `prototype`:** Operator dashboards (audit views, cost telemetry, activation queue).
- **Target for `to-spec` & `to-tickets`:** Scope boundary = E2E test suite, backup/restore drill automation, cost telemetry dashboard, launch runbook + release gate. No new feature work.

---

## 3. End-to-End Traceability Matrix (Phased Delivery)

### 3.1 Feature → Module → Phase Traceability

| PRD Feature ID                                    | Module ID                                  | Phase Assigned | Data Schema Impact                                                                            | Infra Impact                              | Status    |
| :------------------------------------------------ | :----------------------------------------- | :------------- | :-------------------------------------------------------------------------------------------- | :---------------------------------------- | :-------- |
| `FEAT-001` (registration & identity)              | `MOD-001`                                  | Phase 2        | `iam` - identities, otp_challenges, sessions, role_grants                                     | SMS/OTP adapter + edge JWT/RBAC           | Scheduled |
| `FEAT-002` (record & consent)                     | `MOD-003`, `MOD-004`                       | Phase 3        | `health` - patient_records, record_entries; `consent` - consents, consent_events, egress_log  | Redis consent cache                       | Scheduled |
| `FEAT-003` (own record & access view)             | `MOD-003`, `MOD-011`                       | Phase 4        | `health` - record_access_history; `audit` - audit_events                                      | None new                                  | Scheduled |
| `FEAT-004` (directory & search)                   | `MOD-002`                                  | Phase 6        | `partner` - directory_index, service_areas                                                    | Redis search cache; geo index             | Scheduled |
| `FEAT-005` (profiles & credentials)               | `MOD-002`                                  | Phase 6        | `partner` - partner_credentials (expiry/revoked)                                              | Credential-expiry deactivation            | Scheduled |
| `FEAT-006` (symptom intake)                       | `MOD-005`                                  | Phase 7        | `intake` - intakes, media_refs                                                                | Object storage `intake/`                  | Scheduled |
| `FEAT-007` (AI pre-summary)                       | `MOD-005`                                  | Phase 7        | `intake` - pre_summaries, ai_jobs                                                             | LLM adapter + budget meter                | Scheduled |
| `FEAT-008` (consult handshake)                    | `MOD-006`                                  | Phase 8        | `care` - cases                                                                                | Doctor channel                            | Scheduled |
| `FEAT-009` (e-prescription)                       | `MOD-006`, `MOD-005`                       | Phase 8        | `care` - prescriptions, rx_items, rx_approvals, doctor_inputs                                 | Object storage `rx_input/`; approval gate | Scheduled |
| `FEAT-010` (diagnostics booking)                  | `MOD-007`                                  | Phase 9        | `diagnostics` - diagnostic_orders, sample_pickups                                             | Lab channel                               | Scheduled |
| `FEAT-011` (report match & filing)                | `MOD-007`                                  | Phase 9        | `diagnostics` - lab_reports, report_uploads, upload_matches                                   | Upload scanning; `reports/` bucket        | Scheduled |
| `FEAT-012` (fulfilment routing)                   | `MOD-008`                                  | Phase 10       | `fulfillment` - fulfillment_orders, fulfillment_events                                        | Chemist channel                           | Scheduled |
| `FEAT-013` (out-of-stock / delivery failure)      | `MOD-008`                                  | Phase 10       | `fulfillment` - out_of_stock_items, patient_choices                                           | Latency measurement (KPI-008)             | Scheduled |
| `FEAT-014` (open registration & gated activation) | `MOD-002`, `MOD-001`                       | Phase 5        | `partner` - partner_profiles, partner_credentials, partner_verifications; `iam` - role_grants | Operator Console route group              | Scheduled |
| `FEAT-015` (operator console)                     | `MOD-002`, `MOD-011`                       | Phase 5        | `partner` - partner_verifications; `iam` - MFA                                                | Operator MFA                              | Scheduled |
| `FEAT-016` (settlement & payments)                | `MOD-009`, `MOD-011`                       | Phase 11       | `settlement` - settlements, payment_intents, webhook_events                                   | UPI adapter + HMAC webhooks               | Scheduled |
| `FEAT-017` (cancellations & refunds)              | `MOD-009`                                  | Phase 11       | `settlement` - cancellations, refund_records, cancellation_policies                           | Policy display cache                      | Scheduled |
| `FEAT-018` (chronic metrics & follow-ups)         | `MOD-003`, `MOD-010`                       | Phase 12       | `health` - chronic_metrics, follow_up_plans                                                   | Scheduler due-eval job                    | Scheduled |
| `FEAT-019` (WhatsApp notifications)               | `MOD-010`                                  | Phase 13       | `notify` - notifications, notification_schedules, delivery_logs                               | WhatsApp adapter + signed callbacks       | Scheduled |
| `FEAT-020` (audit trail & consent lifecycle)      | `MOD-011`, `MOD-004`                       | Phase 4        | `audit` - audit_events, tamper_attempts                                                       | Append-only DB policy                     | Scheduled |
| `NFR-001` (cost floor)                            | all modules                                | Phase 1, 7, 14 | `intake` - ai_jobs; `ops` - cost_meters                                                       | Budget meters + cost alerts               | Scheduled |
| `NFR-002` (security & privacy)                    | `MOD-001`, `MOD-003`, `MOD-004`, `MOD-011` | Phase 2, 3, 4  | `iam`, `health`, `consent`, `audit`                                                           | TLS 1.2+; RBAC at edge                    | Scheduled |
| `NFR-003` (performance)                           | Gateway + all modules                      | Phase 1, 14    | -                                                                                             | Page-budget + latency budgets             | Scheduled |
| `NFR-004` (availability & durability)             | `MOD-003` + shared infra                   | Phase 1, 14    | all schemas (RPO ≤ 24 h)                                                                      | Daily backup + monthly restore drill      | Scheduled |
| `NFR-D01` (auditability)                          | `MOD-011`                                  | Phase 4        | `audit`                                                                                       | Append-only engine                        | Scheduled |
| `NFR-D02` (data governance)                       | `MOD-004`, `MOD-011`                       | Phase 3, 4     | `consent`, `audit`                                                                            | Consent versioning + egress log           | Scheduled |

### 3.2 External Interface / Actor → Phase Traceability

| External Interface / Actor ID | Phase Assigned                                                         | Primary Module       | Verification Hook                          |
| :---------------------------- | :--------------------------------------------------------------------- | :------------------- | :----------------------------------------- |
| `ACT-001` (Patient)           | Phase 2 (PWA shell) → increments through 3, 4, 6, 7, 9, 10, 11, 12, 13 | `MOD-001` + channel  | Feature E2Es per owning phase              |
| `ACT-002` (Doctor)            | Phase 8                                                                | `MOD-006`            | Rx approval-gate E2E                       |
| `ACT-003` (Lab)               | Phase 9                                                                | `MOD-007`            | Match-before-file E2E                      |
| `ACT-004` (Chemist)           | Phase 10                                                               | `MOD-008`            | Fulfilment state E2E                       |
| `ACT-005` (Operator)          | Phase 5 (console) + Phase 4 (audit views)                              | `MOD-002`, `MOD-011` | Verification queue + audit query E2Es      |
| `EXT-001` (SMS/OTP)           | Phase 2                                                                | `MOD-001`            | Mocked-SMS auth E2E                        |
| `EXT-002` (LLM/AI)            | Phase 0 (spike) + Phase 7                                              | `MOD-005`            | Mocked-LLM pipeline + budget tests         |
| `EXT-003` (WhatsApp)          | Phase 13                                                               | `MOD-010`            | Signed-callback + notifications-only tests |
| `EXT-004` (UPI GW)            | Phase 11                                                               | `MOD-009`            | Webhook replay/idempotency tests           |

### 3.3 Module Primary-Build-Phase Map (every `MOD-xxx` covered)

| Module                          | Primary Build Phase | First Consumed By                  | Traceability Note                                |
| :------------------------------ | :------------------ | :--------------------------------- | :----------------------------------------------- |
| `MOD-001` (IAM)                 | Phase 2             | all phases (edge scope)            | Facade extended Phase 5 (partner/operator roles) |
| `MOD-002` (Partner & Directory) | Phase 5             | Phase 6 (search)                   | -                                                |
| `MOD-003` (LHR)                 | Phase 3             | Phase 4, 12 (access view, metrics) | -                                                |
| `MOD-004` (Consent)             | Phase 3             | all sharing phases (7, 8, 9)       | -                                                |
| `MOD-005` (Intake & AI)         | Phase 7             | Phase 8 (rx draft)                 | -                                                |
| `MOD-006` (Care & Rx)           | Phase 8             | Phase 10 (routing), 13 (schedules) | -                                                |
| `MOD-007` (Diagnostics)         | Phase 9             | Phase 11 (order context)           | -                                                |
| `MOD-008` (Fulfillment)         | Phase 10            | Phase 13 (status notifications)    | -                                                |
| `MOD-009` (Settlement)          | Phase 11            | Phase 14 (audit completeness)      | -                                                |
| `MOD-010` (Notifications)       | Phase 13            | -                                  | Consumes Phase 8/12 events                       |
| `MOD-011` (Audit)               | Phase 4             | all phases (audit.event)           | Engine precedes consumers                        |

---

## 4. Verification Checklist

- [x] **Every `FEAT-001`–`FEAT-020` assigned to exactly one phase** (§3.1).
- [x] **Every `MOD-001`–`MOD-011` has a primary build phase** and every consumer is ordered after its producer (§2 spine, §3.3).
- [x] **Every `EXT-001`–`EXT-004` and `ACT-001`–`ACT-005` placed** with its owning phase (§3.2).
- [x] **Every phase is small and independently verifiable** - each has explicit release-readiness criteria, schema delta, infra targets, and no dependency on an unbuilt phase's outputs.
- [x] **Every phase details its data-schema & entity delta** with versioned migrations (`v0.0` → `v13.0`).
- [x] **Phases ordered by dependency** - foundation/auth → data engine → onboarding/directory → core workflows → integrations → events → admin/observability.
- [x] **Cost floor preserved throughout** (`NFR-001`): single VM + one PostgreSQL, no paid frameworks, LLM budget-metered, spike before any AI spend.
- [x] **Deferred items explicit** (`REQ-026`, `REQ-038/039/040`, open `CFL`/`GAP`/`AMB` decisions) and not silently dropped.

_Next stage: each phase feeds `grill-with-docs` (handoff block 6), `prototype`, then `to-spec` / `to-tickets` to publish engineering backlog tickets._
