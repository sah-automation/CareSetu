# SPEC: Phase 5 - Partner Onboarding & Gated Activation

**Phase:** `PHASE-5-PARTNER-ONBOARDING`
**Features:** `FEAT-014` (Open Registration & Gated Activation), `FEAT-015` (Operator Console - Verification & Moderation)
**Status:** ready-for-agent
**Relates to ADRs:** `ADR-0008` (two-step verification gate), `ADR-0009` (WhatsApp-first/SMS-fallback notifications), `ADR-0010` (sync partner account at registration)

---

## Problem Statement

Doctors, labs, and chemists in Daltonganj + peri-urban need to come onto the CareSetu platform with low friction, but a patient-facing care loop cannot trust an unverified partner to touch a record. Today the platform has no way for a partner to register, no way to prove their professional credentials, and no operator surface to gate who becomes active. Until a partner is verified, no patient can ever be routed to them, so the entire partner side of the product is blocked on this phase.

From the user's perspective: a doctor/lab/chemist cannot get onto the platform at all, and there is no human on the platform side who can admit or reject a partner. The trust boundary that every later phase (directory search, consultations, prescriptions, diagnostics, fulfillment) depends on does not exist yet.

---

## Solution

From the user's perspective:

- A **doctor, lab, or chemist** can register openly with their phone, submit their professional credentials, and watch their onboarding status move from `[Registered]` to `[Under Verification]` to `[Active]` or `[Rejected]`.
- A **verification pre-filter** cheaply rejects obviously bad submissions (malformed/duplicate) right away with a clear reason, without waiting in a queue.
- Every submission that passes the pre-filter is **manually reviewed by a trusted operator**, so no partner ever becomes active without a human having looked at it.
- The **operator** has a console with a sortable verification queue, a per-partner detail view (profile, credentials, verification history, audit link), and can **approve or reject** each round - requiring a reason on reject.
- A partner who is **rejected** learns the specific failure reason, and can re-submit corrected credentials or file a one-time appeal.
- A partner who is **active** who re-submits credentials keeps practicing through a 7-day grace window; if reverification fails they are deactivated and removed from any future directory.
- Partners are notified of `[Active]` and `[Rejected]` status via WhatsApp, falling back to SMS when WhatsApp cannot deliver.
- Every operator decision, every credential view, and every status change is audited.

---

## User Stories

1. As a doctor, I want to register openly with my phone and basic profile, so that I can start onboarding without waiting for an invite.
2. As a doctor, I want to submit my professional credentials (medical registration number, qualification documents) at registration, so that my eligibility can be verified.
3. As a lab, I want to register with my lab type and submit my lab license / accreditation documents, so that my eligibility can be verified.
4. As a chemist, I want to register with my chemist type and submit my drug license / pharmacist registration documents, so that my eligibility can be verified.
5. As any partner, I want my registration to create a login account immediately, so that I can track my onboarding status before I am activated.
6. As any partner, I want to see my onboarding status (`Registered` / `Under Verification` / `Active` / `Rejected`) after logging in, so that I know where I stand.
7. As any partner in `[Under Verification]`, I want to see that my credentials are being reviewed, so that I know a decision is pending.
8. As any partner, I want to be notified when I am `[Active]`, so that I know I can start receiving patients (WhatsApp first, SMS fallback).
9. As any partner, I want to be notified with the specific reason when I am `[Rejected]`, so that I know what failed (WhatsApp first, SMS fallback).
10. As a partner with malformed or duplicate credentials, I want my submission rejected immediately with the specific failure, so that I do not wait in a queue for something I can fix right away.
11. As a rejected partner, I want to re-submit corrected credentials, so that I can enter a fresh verification round.
12. As a rejected partner, I want to file a one-time appeal that re-enters the operator queue, so that I can contest a decision without re-submitting.
13. As an active partner, I want to re-submit updated credentials and keep practicing through a grace window, so that a renewal does not disrupt my work.
14. As an active partner whose reverification fails, I want to be deactivated and notified, so that I do not keep operating on invalid credentials.
15. As an operator, I want to log in only with MFA, so that the verification gate is held by a trusted, attested account.
16. As an operator, I want a verification queue sortable by registration age (default), partner type, and status, so that I can meet the activation-cycle target.
17. As an operator, I want to open a partner's queue item to view their profile, all submitted credentials, and verification history, so that I can make a defensible decision.
18. As an operator, I want to approve a partner, so that their role is granted and they become `[Active]`.
19. As an operator, I want to reject a partner with a required reason, so that the specific failure is recorded and communicated.
20. As an operator, I want every decision I make to be individually attributed and audited, with no bulk actions, so that accountability is preserved.
21. As an operator, I want my every view of a partner's credentials to be audited, so that there is a complete "who saw this document" trail.
22. As an operator, I want to invite additional operators, so that the trusted queue-running group can grow.
23. As the platform, I want no partner to reach `[Active]` without operator approval, so that unverified partners can never receive patients.
24. As the platform, I want the partner role granted in IAM only on `[Active]` and denied on `[Rejected]`, so that access follows verification state.
25. As the platform, I want the verification state machine to emit `partner.registered`, `partner.verification_started` (per round), `partner.activated`, and `partner.rejected`, so that downstream modules (IAM role grant/deny, notify, audit) react.
26. As the platform, I want credential documents stored encrypted under the `partner/` prefix with access limited to the owner, the reviewing operator, and the audit trail, so that identity documents stay protected.
27. As the platform, I want credential documents deleted 30 days after permanent rejection/closure, so that we do not hoard identity documents.
28. As the platform, I want rejected partners throttled (max 3 re-submissions before cooldown) so that the verification queue cannot be spammed.
29. As the platform, I want the operator console to expose an audit link for each partner, so that regulated decisions are traceable.

---

## Implementation Decisions

**Modules built/modified:** `MOD-002` (Partner Lifecycle - new primary build), `MOD-001` (IAM - partner credential accounts + operator MFA + role grant/deny on events), `MOD-011` (Audit - consumes `partner.*` + `partner.credential_reviewed`). `MOD-010` (Notify) is modified for the partner notification channel chain. Gateway/module seam extended for `partner` and `operator` scopes.

**Partner identity vs. profile:** A partner has one stable identity carrying lifecycle status, separate from the display profile and credential metadata - mirroring patient identity in `MOD-001`.

**Partner lifecycle state machine** (from ADR-0008):

```
[Registered] → [Under Verification] → [Active] | [Rejected]
                    │
  Step 1 auto-fail → (Rejected, never queued)
  Step 1 pass → Step 2 manual queue
  operator approve → Active
  operator reject → Rejected
```

**Credential types:** A closed enum per partner type (`doctor | lab | chemist`), e.g. `medical_registration | lab_license | drug_license`. Gives deterministic verification routing, operator-facing labels, and a queryable `partner_credentials` key.

**Two-step verification (AMB-003, ADR-0008):** Step 1 (automated, synchronous on submit) is a **pre-filter** - format validation (known credential type, required fields, artifacts uploaded, no duplicate). Failure returns `[Rejected]` immediately, never queued. Step 2 (manual) is the **activation gate** - every Step-1 pass enters the operator queue; there is **no auto-approve path**. A partner is `[Active]` only on explicit operator approval. Automated checks are deliberately limited to what is verifiable in Phase 5 (no machine-verifiable external credential sources yet).

**Partner account creation (ADR-0010):** The `MOD-001` credential account is created **synchronously at registration** via the existing `MOD-002 → MOD-001` facade seam (`create_credential_account`), in the same transaction boundary, before first login. The partner role grant/deny stays event-driven (`partner.activated`/`partner.rejected`).

**Pre-activation login (restricted scope):** A partner can log in via phone-OTP once their account exists, but with a restricted scope until `[Active]`:

- `[Registered]` / `[Under Verification]` → view status, submit/re-submit credentials, view rejection reason. No patient-facing access.
- `[Active]` → full partner scope.
- `[Rejected]` → re-submit or appeal; no patient-facing access.

**Re-applying after rejection:** A rejected partner can either re-submit corrected credentials (a new verification round) or file a **one-time appeal** that re-enters the operator queue. Both are rate-limited (max 3 re-submissions before cooldown).

**Deactivation on failed re-verification:** An active partner who re-submits credentials stays `[Active]` through a **7-day grace window**. Success → no disruption. Window lapses without a decision → auto-drop to `[Under Verification]`. Failure → `[Rejected]` with specific reason, and `credential.invalidated` fires (deindexes directory, revokes IAM role via MOD-001).

**Verification rounds:** Every round (first-time and re-verification) emits `partner.verification_started` with a round/version in the payload, so the audit trail distinguishes rounds.

**Operator identity & MFA:** Operators are a trusted closed group, never self-registering. A **bootstrap operator** is provisioned at deploy (seed), and operators can **invite additional operators** (credentialed, MFA-bound at login). MFA is required for operator login.

**Operator console & queue:** Queue sortable/filterable by registration age (default, for KPI-004), partner type, status. Per-item approve/reject with a **required reason on reject** (optional on approve). No bulk actions in Phase 5. Opening a partner's credentials triggers an audit event.

**Operator audit depth:** Every operator **view** of a partner's credentials is an audit event (`partner.credential_reviewed`, with actor + partner + timestamp), layered on top of the terminal decision audit (`partner.activated`/`partner.rejected` → MOD-011). Provides a complete "who saw this document" trail.

**Credential document storage (sensitive-class, not PHI):** Uploaded to encrypted object storage under the `partner/` prefix, readable only by the owning partner, the reviewing operator, and the audit trail. Deleted 30 days after permanent rejection/closure.

**Notification channel (ADR-0009):** Terminal status changes (`[Active]`, `[Rejected]` with reason) are delivered **WhatsApp-first via `EXT-003`)**, falling back to **SMS via `EXT-001`** when the `EXT-003` delivery webhook reports failure/undeliverable (`notification.failed`). Non-terminal updates (`Under Verification`, re-submission confirmations) are in-app only. `EXT-001` SMS is now shared beyond OTP.

**Service areas:** Partners declare a service area at registration (informational in Phase 5, consumed by Phase 6 search). Practice location/geo is mandatory; service area is optional, defaulting to Daltonganj (launch scope, `REQ-008`).

**RBAC scopes / IAM:** `partner` and `operator` scopes, previously only reserved in the registry, become mintable in Phase 5. `MOD-001` role grant on `partner.activated`, role deny on `partner.rejected`, via the existing async subscription. Credential account created sync (ADR-0010); role grant is the async activation-gated step.

**Schema delta:** `partner` schema: `partner_profiles` (type, status), `partner_credentials` (type, verified flag, expiry, artifact refs), `partner_verifications` (queue, round, status, decision, reason), `service_areas`, `partner_outbox`. `iam` extended: `iam_role_grants` for partner/operator roles, operator MFA fields. Migrations: `v4.0__init_partner.sql`, `v4.1__iam_roles_mfa.sql`.

**Event registry additions (register in internal-modules §4.2):** `partner.registered`, `partner.verification_started` (per round), `partner.activated`, `partner.rejected`, `partner.credential_reviewed`, `credential.invalidated`.

---

## Testing Decisions

**Seam strategy - one highest seam:** Test Phase 5 at the **module facade + HTTP route + event-catalog** level, not at SQL/implementation level. This matches the repo's existing tests (`test_iam_*.py`, `test_consent_state_machine.py`, `test_audit_consumer.py`, `test_regulated_acts.py`). The lifecycle behavior is fully exercised through: (a) the `MOD-002` lifecycle state machine, (b) the operator decision route gated by `operator` RBAC, (c) the async event chain `partner.activated`/`partner.rejected` → IAM role grant/deny → notify → MOD-011 audit, and (d) the event-name/catalog registrations. Integration tests run against a live Postgres following existing patterns.

**What makes a good test here (external behavior, not implementation):**

- The **state machine**: from any valid start, a known sequence of actions (submit, Step-1 fail, Step-1 pass, operator approve/reject, re-verify, appeal) yields exactly the expected lifecycle transitions. This proves the two-step gate: no path reaches `[Active]` without an operator decision.
- The **no-auto-approve guarantee**: a Step-1-pass alone must never produce `[Active]` - an integration/unit test asserts the partner stays `[Under Verification]` until an operator approves.
- **RBAC/authorization**: only an `operator`-scope MFA-authenticated caller can invoke `operator_decision`; a partner/patient/non-operator is denied (403).
- **Role grant/deny event chain**: `partner.activated` leads to the partner role being granted in IAM; `partner.rejected` leads to it being denied - observable through the IAM facade, not internals.
- **Grace window**: an active partner re-submitting stays `[Active]` within 7 days; lapses to `[Under Verification]` after; reverification failure produces `[Rejected]` + `credential.invalidated`.
- **Rejection reasons + appeals**: rejection requires a reason; rejected partner can re-submit (new round) or one-time appeal; throttle is enforced.
- **Auditability**: every decision and every credential view yields an audit event consumed by MOD-011.

**Modules tested:** `MOD-002` (lifecycle, verification gate, queue, service area), `MOD-001` (partner account, operator MFA, role grant/deny on events), `MOD-011` (partner/credential-review audit), `MOD-010` (WhatsApp→SMS fallback chain).

**Prior art:** `test_iam_verify.py` / `test_iam_verify_route.py` (route + facade split, OTP/phone), `test_consent_state_machine.py` (state machine + gate), `test_audit_consumer.py` + `test_audit_chain.py` (event → audit append), `test_event_names.py` + `test_bus_event_catalog.py` + `test_regulated_acts.py` (event-registry/regulated-acts registration), `test_registry.py` (RBAC scope registry), `tests/integration/*` for live-PG round-trips.

---

## Out of Scope

- **Directory search / provider profiles** (Phase 6).
- **Automated credential expiry/revocation detection** (Phase 6) - the grace-window reverify exists, but background expiry-scanning does not.
- **Deep registry-based verification** beyond format/duplicate (Phase 6 decision; ADR-0008 limits Phase 5's automated check).
- Ratings/reviews, consultation slots, availability calendars.
- Multi-city geo expansion (Daltonganj only at launch).
- Bulk operator actions (approve-all / batch reject).
- Editing partners' profiles/directory data in the operator console.
- **Implementation of Phase 5 tickets** - this spec is the contract; tickets are cut via `/to-tickets` and implemented in separate sessions.

---

## Further Notes

- This spec supersedes the grilling session's interim AMB-003 baseline (auto-approve + manual flag) with the **2-step verification** model: Step 1 automated pre-filter, Step 2 manual activation gate, no auto-approve. See ADR-0008.
- The domain glossary in `CONTEXT.md` has a new **Partner onboarding & gated activation** section (partner identity, partner type, credential type, two-step verification, verification round, credential document, grace window, rejection appeal, operator, operator decision).
- New ADRs: `0008` (two-step verification gate), `0009` (WhatsApp→SMS notification fallback), `0010` (sync partner account at registration).
- `EXT-001` SMS is now shared beyond OTP (used for partner terminal notifications); keep this in mind for any SMS-capability scoping.
- Phase 5 depends on Phase 2 (IAM credential accounts, RBAC scope registry) - those exist, so this phase builds on them.
