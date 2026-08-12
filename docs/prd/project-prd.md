# Product Requirement Document (PRD) - CareSetu

**Product Name:** CareSetu
**Document Version:** 1.0 (Baseline)
**Date:** 2026-08-07
**Product Manager / Author:** Product Discovery (single Founder voice)
**Upstream Inputs:** RGD v1.0 | Conflict & Gap Report v1.0

> **Baseline note:** Where the Conflict & Gap Report carries an unresolved `CFL-xxx` / `GAP-xxx` / `AMB-xxx`, this PRD proceeds on the _current baseline interpretation_ stated inline at the affected feature, and lists the decision in **Section 7.1 (Open Dependencies)**. No open decision silently changes a feature's behavior.

---

## 1. Executive Summary & Strategic Context

### 1.1 Problem Statement

- Patients in Tier 3/4 Indian cities face a fragmented, hyper-local care journey: symptom onset → finding a doctor → booking a lab → getting a prescription → buying medicine. Each step is a separate, offline, trust-dependent interaction with no shared record and no continuity. Existing aggregators are transactional "booking directories" and do not serve the chronic-care segment (BP/sugar management) that dominates this demographic.
- CareSetu connects patients, doctors, local diagnostic labs, and retail chemists as a **zero-inventory aggregator** that digitizes the complete care loop - symptom intake → consultation → diagnostics → e-prescription → hyper-local delivery - with a continuous, AI-assisted chronic care loop as its differentiator.
- **Scope note:** $0 monetization initially (portfolio / open-architecture project); the product's requirements cover the full product, not an MVP cut.

### 1.2 Vision & Business Objectives

- **Vision:** Become the continuous care platform for Tier 3/4 India - the patient's single trusted entry point for the whole care loop, anchored by a lifelong longitudinal health record.
- **Business objectives (all traced):**
  1. Prove the full care loop end-to-end in one beachhead city (Daltonganj, Jharkhand) before replicating (`REQ-002`, `REQ-008`).
  2. Maintain a pure-facilitator compliance posture - regulated acts stay with licensed partners (`REQ-005`).
  3. Build the chronic-care loop as the durable differentiator, not the booking directory (`REQ-015`).
  4. Operate at near-zero developer and operational hosting cost (`NFR-001`).
  5. Geographic expansion beyond Daltonganj is **undecided** (`ISSUE-004`) - see Section 7.

### 1.3 Key Performance Indicators (KPIs) & Success Metrics

> KPI targets are **proposed** and subject to the `AMB-002` decision (acceptance bar for "full care loop proven").

| Metric                                                                                                               | Baseline (Current) | Target Goal                                         | Measurement Method               |
| :------------------------------------------------------------------------------------------------------------------- | :----------------- | :-------------------------------------------------- | :------------------------------- |
| **[KPI-001]** Completed care loops per week in Daltonganj (intake → consult → diagnostics → prescription → delivery) | 0 (pre-launch)     | ≥ 50/week by end of first launch quarter (proposed) | Pipeline counters per loop stage |
| **[KPI-002]** E-prescription delivery success rate (delivered ÷ approved)                                            | 0                  | ≥ 90%                                               | Fulfillment status events        |
| **[KPI-003]** Lab report mis-attachment rate                                                                         | 0                  | 0 (every upload matched to correct patient + order) | Upload-match audit events        |
| **[KPI-004]** Partner activation cycle time (registration → live)                                                    | N/A                | ≤ 48 hours median                                   | Operator-console timestamps      |
| **[KPI-005]** Chronic-care weekly active loggers (patients logging ≥ 1 metric this week ÷ enrolled)                  | 0                  | ≥ 50%                                               | Metric-logging events            |
| **[KPI-006]** Consent actions granted/revoked - 100% recorded per action                                             | 0                  | 100% of consent actions logged                      | Consent audit events             |
| **[KPI-007]** Monthly operating + hosting cost (incl. AI/LLM spend)                                                  | N/A                | ≤ ₹2,000/month at launch scale                      | Billing telemetry                |
| **[KPI-008]** Median loop completion time (intake → delivery)                                                        | N/A                | ≤ 7 days (proposed, off-platform consult dominates) | Stage timestamp deltas           |

---

## 2. Target Personas & User Hierarchy

- **[Persona-001] Patient:** Adult in a Tier 3/4 city (Daltonganj + peri-urban); primary language Hindi or English; owns a smartphone on 4G; moderate digital literacy; expects low-friction, offline-style trust. Owns a longitudinal record and grants per-action consent. Primary interaction channel is the web app (`REQ-003`).
- **[Persona-002] Doctor (GP / specialist):** Local independent physician; time-constrained; prefers voice-note or photo input; licensed to issue e-prescriptions; consults with the patient **off-platform** (`REQ-004`); uses the platform to review the AI pre-summary and approve the e-prescription.
- **[Persona-003] Lab Partner:** Registered pathology lab or franchised pickup point; performs testing; returns reports (uploads or patient uploads); accepts sample pickup/booking routing; settles cash/UPI at point of service.
- **[Persona-004] Chemist Partner:** Local retail chemist; receives routed approved prescriptions; prepares and delivers via own rider; settles cash/UPI on delivery; inherits partner cancellation policy.
- **[Persona-005] Operator / Admin:** Platform operator (from `GAP-002`); verifies partner credentials, manages activation gating, moderates disputes, views audit logs. Capability is a discovered gap that this PRD makes explicit (trace `GAP-002`).

**Access hierarchy:** Patient (own record only) → Partner (own scope: own orders/reports/prescriptions) → Operator (all records, audit, moderation). Role-based access enforced per `NFR-002`.

---

## 3. Project Scope

### 3.1 In-Scope (Complete Product)

- **EPIC-01:** Patient identity, longitudinal health record, per-action consent.
- **EPIC-02:** Provider discovery - directory search and profiles with displayed credentials.
- **EPIC-03:** Symptom intake (voice + text, English + Hindi) and AI clinical pre-summary.
- **EPIC-04:** Consultation orchestration (off-platform consult handshake) and on-platform e-prescription (AI draft, doctor approval).
- **EPIC-05:** Diagnostics booking, sample pickup, lab report filing with wrong-upload protection.
- **EPIC-06:** Medicine fulfillment routing to partner chemists; out-of-stock and delivery-failure handling.
- **EPIC-07:** Partner onboarding - open registration, gated activation, operator verification console.
- **EPIC-08:** Payments, settlement, cancellations, and partner-direct refunds.
- **EPIC-09:** Chronic care loop - metric logging, follow-ups, WhatsApp notifications.
- **EPIC-10:** Compliance, audit trail, and consent lifecycle (DPDP baseline).
- Cross-cutting: web-first channel (`REQ-003`), English + Hindi patient UI (`REQ-006`), best-effort availability with a durability floor (`NFR-004`).

### 3.2 Out-of-Scope / Deferred

- **`REQ-026` - Lab-report baseline parsing** (deferred; launch = report filing only). Feature `FEAT-011` excludes parsing/flagging against baselines.
- **`REQ-038` - ABHA integration** (post-launch future goal, `[Could Have]`, `[FUTURE]`).
- **`REQ-039` - Future monetization** (commission / subscription / freemium; model deferred and unspecified).
- **`REQ-040` - Non-web patient channels** (native app, WhatsApp-first; `[Could Have]`, `[FUTURE]`). WhatsApp is used for **notifications only** at launch (`REQ-035`).
- No revenue/fee capture is in scope (`REQ-020`).

---

## 4. Epic & Feature Specifications

### 4.1 [EPIC-01]: Patient Identity & Longitudinal Health Record

_Traceability: `REQ-021`, `REQ-003`, `NFR-002`, `GAP-001`, `GAP-005`, `GAP-013`, `GAP-011`_

#### Feature 4.1.1: Patient Registration & Identity

- **Feature ID:** `FEAT-001`
- **Traceability:** `REQ-021`, `REQ-003`, `GAP-001`
- **Priority:** Must Have

**User Story:**

> As a **[Patient]** , I want **[to register once with a verifiable identity]**, so that **[my health record is uniquely and stably mine across every future interaction]**.

**Acceptance Criteria (BDD / Gherkin):**

- **Scenario 1: Happy Path**
  - **Given** I am a first-time patient on the web app
  - **When** I register with my phone number and verify it
  - **Then** a stable patient identity is created and I can access the platform
- **Scenario 2: Edge Case - Duplicate / re-registration**
  - **Given** I already have an account and I attempt to register with the same phone number
  - **When** I submit registration
  - **Then** the system links me to my existing record instead of creating a duplicate, and I am prompted to authenticate

**Business Rules & State Transitions:**

- **Rule 1:** One stable identity per phone number; re-registration resolves to the existing identity.
- **Rule 2:** Identity verification method (OTP vs. stronger) is **open** - see `GAP-001` in Section 7.1. Baseline: phone OTP verification.
- **State Change:** `[State: Unverified]` → `[State: Active]` → `[State: Suspended]`.

**Telemetry & Event Tracking:**

- `patient.registered`: `identity_id`, `phone_e164`, `timestamp`
- `patient.verified`: `identity_id`, `phone_e164`, `timestamp`
- `patient.auth_failed`: `identity_id`, `phone_e164`, `reason`, `timestamp`

> Event names use the registry `domain.action` dot-notation. The event registry in `internal-modules.md` §4.2 is the single source of truth for event names and payloads; the PRD's earlier snake_case telemetry names are superseded by it.

#### Feature 4.1.2: Longitudinal Health Record & Per-Action Consent

- **Feature ID:** `FEAT-002`
- **Traceability:** `REQ-021`, `NFR-002`, `GAP-005`, `GAP-013`
- **Priority:** Must Have

**User Story:**

> As a **[Patient]**, I want **[a single longitudinal record that I consent to share per action]**, so that **[doctors, labs, and chemists see exactly what I authorize, nothing more]**.

**Acceptance Criteria (BDD / Gherkin):**

- **Scenario 1: Happy Path - consent before sharing**
  - **Given** I have an active identity and a record with entries
  - **When** a doctor/lab/pharmacy requests access to a specific part of my record
  - **Then** I am asked to consent to that specific action before any data is shared, and the consent is recorded
- **Scenario 2: Edge Case - consent revoked**
  - **Given** I previously granted consent to a partner
  - **When** I revoke that consent
  - **Then** the system stops future sharing with that partner and records the revocation; previously shared data handling is per the retention rule (open under `GAP-005`/`GAP-013`)

**Business Rules & State Transitions:**

- **Rule 1:** No record access or sharing without a recorded per-action consent.
- **Rule 2:** Record deletion/retention/portability rules are **open** - see `GAP-005`/`GAP-013` in Section 7.1. Baseline: record retained for the life of the account; deletion requested via operator.
- **State Change:** `[Consent: Requested]` → `[Consent: Granted]` → `[Consent: Revoked]`.

**Telemetry & Event Tracking:**

- `consent_requested`: `patient_id`, `record_scope`, `requester_type`, `timestamp`
- `consent_granted` / `consent_revoked`: `patient_id`, `consent_id`, `timestamp`
- `record_accessed`: `patient_id`, `actor_id`, `access_type`, `timestamp`

#### Feature 4.1.3: Patient Record Access & Audit View

- **Feature ID:** `FEAT-003`
- **Traceability:** `REQ-021`, `NFR-002`, `GAP-011`
- **Priority:** Must Have

**User Story:**

> As a **[Patient]**, I want **[to see my own full record and every access made to it]**, so that **[I trust the platform's data handling]**.

**Acceptance Criteria (BDD / Gherkin):**

- **Scenario 1: Happy Path**
  - **Given** I am authenticated as the record owner
  - **When** I open my record
  - **Then** I see all record entries and an access history listing actor, scope, and timestamp
- **Scenario 2: Edge Case - another identity attempts access**
  - **Given** an identity that is not the record owner requests the record
  - **When** the request is made
  - **Then** access is denied and the attempt is written to the audit log (`FEAT-020`)

**Business Rules & State Transitions:**

- **Rule 1:** Only the owner or a consented partner accesses the record; role-based access enforced (`NFR-002`).
- **State Change:** N/A (read view).

**Telemetry & Event Tracking:**

- `record_view_denied`: `patient_id`, `actor_id`, `reason`, `timestamp`

---

### 4.2 [EPIC-02]: Provider Discovery & Marketplace

_Traceability: `REQ-001`, `REQ-008`, `REQ-022`, `REQ-005`, `GAP-009`_

#### Feature 4.2.1: Provider Directory & Search

- **Feature ID:** `FEAT-004`
- **Traceability:** `REQ-001`, `REQ-008`, `REQ-022`, `GAP-009`
- **Priority:** Must Have

**User Story:**

> As a **[Patient]**, I want **[to search and filter doctors, labs, and chemists near me]**, so that **[I can choose the right provider in my care loop]**.

**Acceptance Criteria (BDD / Gherkin):**

- **Scenario 1: Happy Path**
  - **Given** I am in Daltonganj or its peri-urban area
  - **When** I search for a GP near me
  - **Then** I see active GP profiles sorted by distance, each showing specialty and consultation type
- **Scenario 2: Edge Case - no results**
  - **Given** no provider matches my filters in my area
  - **When** I search
  - **Then** I see an empty state with a clear "no providers found" message and adjacent providers across the wider area

**Business Rules & State Transitions:**

- **Rule 1:** Only **activated** partners appear in search results (`REQ-028` gating).
- **Rule 2:** Geographic scope is Daltonganj + surrounding/peri-urban areas (`REQ-008`).
- **State Change:** N/A (read view).

**Telemetry & Event Tracking:**

- `directory_search`: `patient_id`, `query`, `filters`, `result_count`, `timestamp`
- `provider_selected`: `patient_id`, `provider_id`, `provider_type`, `timestamp`

#### Feature 4.2.2: Provider Profiles & Credential Display

- **Feature ID:** `FEAT-005`
- **Traceability:** `REQ-005`, `REQ-028`, `NFR-002`
- **Priority:** Must Have

**User Story:**

> As a **[Patient]**, I want **[to see each provider's verified credentials on their profile]**, so that **[I can trust that licensed professionals serve me]**.

**Acceptance Criteria (BDD / Gherkin):**

- **Scenario 1: Happy Path**
  - **Given** a provider has passed activation (`REQ-028`)
  - **When** I view their profile
  - **Then** I see their verified credentials (registration/license) and a "verified" indicator
- **Scenario 2: Edge Case - credentials expired / revoked**
  - **Given** a provider's credential is expired or revoked after activation
  - **When** the credential expiry is detected
  - **Then** the provider is deactivated from search and their verified indicator is removed

**Business Rules & State Transitions:**

- **Rule 1:** The platform displays, verifies, and gats credentials; it does not itself perform regulated acts (`REQ-005`).
- **State Change:** `[Partner: Active]` → `[Partner: Credential Revoked]` → `[Partner: Inactive]`.

**Telemetry & Event Tracking:**

- `credential_displayed`: `provider_id`, `credential_type`, `timestamp`
- `credential_invalidated`: `provider_id`, `reason`, `timestamp`

---

### 4.3 [EPIC-03]: Symptom Intake & AI Clinical Pre-Summary

_Traceability: `REQ-006`, `REQ-007`, `REQ-004`, `NFR-003`, `AMB-006`, `RISK-EVAL-006`_

#### Feature 4.3.1: Symptom Intake - Voice & Text

- **Feature ID:** `FEAT-006`
- **Traceability:** `REQ-006`, `REQ-007`, `NFR-003`
- **Priority:** Must Have

**User Story:**

> As a **[Patient]**, I want **[to describe my symptoms by voice or text in English or Hindi]**, so that **[I can start a care visit without typing-heavy forms]**.

**Acceptance Criteria (BDD / Gherkin):**

- **Scenario 1: Happy Path - voice intake**
  - **Given** I am on the symptom intake screen
  - **When** I record a spoken description in Hindi
  - **Then** the description is captured and queued for structuring into the clinical pre-summary
- **Scenario 2: Edge Case - audio too poor / too short to transcribe**
  - **Given** my recording is below a minimum usable quality or length
  - **When** intake is attempted
  - **Then** I am asked to re-record or type, and the system does not silently proceed

**Business Rules & State Transitions:**

- **Rule 1:** Patient-facing intake is offered in English and Hindi (`REQ-006`).
- **Rule 2:** Voice and text are both first-class inputs (`REQ-007`).
- **State Change:** `[Intake: Captured]` → `[Intake: Structuring]` → `[Intake: Ready for Review]`.

**Telemetry & Event Tracking:**

- `intake_started`: `patient_id`, `mode` (voice|text), `language`, `timestamp`
- `intake_captured`: `patient_id`, `mode`, `duration_s`, `timestamp`
- `intake_retry_requested`: `patient_id`, `reason`, `timestamp`

#### Feature 4.3.2: AI Clinical Pre-Summary Generation

- **Feature ID:** `FEAT-007`
- **Traceability:** `REQ-004`, `REQ-007`, `AMB-006`, `RISK-EVAL-006`
- **Priority:** Must Have

**User Story:**

> As a **[Patient]**, I want **[my unstructured symptom description turned into a structured clinical pre-summary]**, so that **[the doctor reviews my case quickly and accurately]**.

**Acceptance Criteria (BDD / Gherkin):**

- **Scenario 1: Happy Path**
  - **Given** I have captured a structured intake
  - **When** the AI processes it
  - **Then** a clinical pre-summary with structured fields is produced and marked for doctor review
- **Scenario 2: Edge Case - low AI confidence**
  - **Given** the AI confidence for structuring is below the acceptance threshold
  - **When** the pre-summary is generated
  - **Then** the item is flagged "low confidence - verify" and a doctor must review before it is treated as structured

**Business Rules & State Transitions:**

- **Rule 1:** The pre-summary is asynchronous and precedes the (off-platform) consult (`REQ-004`).
- **Rule 2:** Extraction accuracy bar and low-confidence fallback are **open** - see `AMB-006` in Section 7.1. Baseline: flag below-confidence results; never present as verified.
- **State Change:** `[Summary: Draft]` → `[Summary: Reviewed]` → `[Summary: Final]`.

**Telemetry & Event Tracking:**

- `pre_summary_generated`: `patient_id`, `intake_id`, `confidence`, `timestamp`
- `pre_summary_low_confidence`: `patient_id`, `intake_id`, `timestamp`

---

### 4.4 [EPIC-04]: Consultation & E-Prescription

_Traceability: `REQ-004`, `REQ-013`, `REQ-023`, `REQ-005`, `CFL-002`, `CFL-003`, `GAP-003`, `RISK-EVAL-003`_

#### Feature 4.4.1: Consult Orchestration & Off-Platform Handshake

- **Feature ID:** `FEAT-008`
- **Traceability:** `REQ-002`, `REQ-004`, `REQ-013`, `CFL-003`, `GAP-003`
- **Priority:** Must Have

**User Story:**

> As a **[Doctor]**, I want **[to close an off-platform consult and hand the patient back into the on-platform flow]**, so that **[the care loop continues with an e-prescription and delivery]**.

**Acceptance Criteria (BDD / Gherkin):**

- **Scenario 1: Happy Path - doctor-initiated handshake (baseline)**
  - **Given** a patient has a reviewed clinical pre-summary and a consult occurred off-platform
  - **When** the doctor opens the patient's record on-platform and marks the consult complete
  - **Then** the platform moves the case to the e-prescription stage and notifies the patient
- **Scenario 2: Edge Case - no pre-summary before handshake**
  - **Given** a doctor attempts to complete a consult for a patient without a reviewed pre-summary
  - **When** the handshake is submitted
  - **Then** the platform requires the pre-summary to be finalized before the prescription stage opens

**Business Rules & State Transitions:**

- **Rule 1:** The consult itself happens off-platform (`REQ-004`); the platform only orchestrates the handshake and downstream stages.
- **Rule 2:** **Open decision `CFL-003`:** who initiates the handshake (doctor vs. patient vs. dual). Baseline for this PRD: doctor-initiated. See Section 7.1.
- **State Change:** `[Case: Pre-Summary]` → `[Case: Consult Complete]` → `[Case: Prescription Pending]`.

**Telemetry & Event Tracking:**

- `consult_marked_complete`: `case_id`, `doctor_id`, `patient_id`, `timestamp`
- `case_stage_changed`: `case_id`, `from_stage`, `to_stage`, `timestamp`

#### Feature 4.4.2: E-Prescription - AI Draft & Doctor Approval

- **Feature ID:** `FEAT-009`
- **Traceability:** `REQ-013`, `REQ-023`, `REQ-005`, `CFL-002`, `RISK-EVAL-003`
- **Priority:** Must Have

**User Story:**

> As a **[Doctor]**, I want **[to submit a voice note or photo and approve an AI-drafted prescription]**, so that **[issuing a precise e-prescription is quick while I keep final control]**.

**Acceptance Criteria (BDD / Gherkin):**

- **Scenario 1: Happy Path**
  - **Given** the case is in the Prescription Pending stage
  - **When** I submit a voice note or photo and approve the AI-drafted prescription
  - **Then** the approved e-prescription is issued on-platform, timestamped, and attributed to me
- **Scenario 2: Edge Case - doctor edits before approval**
  - **Given** the AI draft contains an item I disagree with
  - **When** I edit the draft
  - **Then** the prescription records my edits and is issued only with my explicit approval

**Business Rules & State Transitions:**

- **Rule 1:** An e-prescription is never issued without doctor review and approval (`REQ-023`).
- **Rule 2:** **Open decision `CFL-002`/`RISK-EVAL-003`:** the regulatory posture of AI-drafted prescriptions under a pure-facilitator model is unvalidated; the compliance stakeholder is `[Not Yet Elicited]`. Baseline: AI is a drafting assistant under the licensed doctor's authority.
- **State Change:** `[Rx: Draft]` → `[Rx: Doctor Reviewed]` → `[Rx: Approved & Issued]` → `[Rx: Fulfilled]`.

**Telemetry & Event Tracking:**

- `prescription_draft_created`: `case_id`, `doctor_id`, `input_type` (voice|photo), `timestamp`
- `prescription_approved`: `case_id`, `doctor_id`, `edited_yn`, `timestamp`
- `prescription_rejected`: `case_id`, `doctor_id`, `reason`, `timestamp`

---

### 4.5 [EPIC-05]: Diagnostics & Lab Reports

_Traceability: `REQ-012`, `REQ-024`, `REQ-025`, `REQ-033`, `REQ-026`, `RISK-002`, `GAP-004`, `GAP-008`_

#### Feature 4.5.1: Diagnostics Booking & Sample Pickup

- **Feature ID:** `FEAT-010`
- **Traceability:** `REQ-012`, `REQ-024`, `REQ-033`
- **Priority:** Must Have

**User Story:**

> As a **[Patient]**, I want **[to book a lab test and choose home pickup or a partner lab / pickup point]**, so that **[sample collection fits my situation]**.

**Acceptance Criteria (BDD / Gherkin):**

- **Scenario 1: Happy Path - on-platform booking**
  - **Given** a partner lab / pickup point serves my area
  - **When** I book a test with home pickup
  - **Then** the order is routed to the partner lab and a pickup is arranged on-platform
- **Scenario 2: Edge Case - no partner availability (fallback)**
  - **Given** no partner lab / pickup point is available on-platform for my area
  - **When** I request diagnostics
  - **Then** the platform supports a direct patient-to-lab arrangement and records the outcome for the patient's record

**Business Rules & State Transitions:**

- **Rule 1:** Hybrid model: on-platform booking preferred; direct patient-to-lab arrangement is the fallback (`REQ-024`).
- **Rule 2:** No automated critical-value escalation at launch; interpretation is left to the patient/doctor (`REQ-033`).
- **State Change:** `[Order: Booked]` → `[Order: Sample Collected]` → `[Order: Result Pending]` → `[Order: Result Filed]`.

**Telemetry & Event Tracking:**

- `diagnostic_order_created`: `order_id`, `patient_id`, `lab_id`, `mode` (home|pickup_point|direct), `timestamp`
- `sample_collected`: `order_id`, `timestamp`
- `diagnostic_fallback_used`: `order_id`, `timestamp`

#### Feature 4.5.2: Lab Report Filing & Wrong-Upload Protection

- **Feature ID:** `FEAT-011`
- **Traceability:** `REQ-025`, `REQ-033`, `RISK-002`, `GAP-004`, `GAP-008`
- **Priority:** Must Have

**User Story:**

> As a **[Patient or Lab]**, I want **[an uploaded report to be matched to the correct order and patient before it is filed]**, so that **[a wrong report never contaminates my record]**.

**Acceptance Criteria (BDD / Gherkin):**

- **Scenario 1: Happy Path - matched upload**
  - **Given** a diagnostic order exists and a report is uploaded (by lab or patient, whoever has it first)
  - **When** the upload matches the order and patient identifiers
  - **Then** the report is filed into the patient's record against that order
- **Scenario 2: Edge Case - mismatched upload**
  - **Given** an uploaded report does not match the order/patient identifiers
  - **When** the upload is attempted
  - **Then** the report is rejected with a visible mismatch error and is not filed

**Business Rules & State Transitions:**

- **Rule 1:** Every upload must be matched to an order and patient before filing (`RISK-002` mitigation).
- **Rule 2:** **Open decision `GAP-004`/`GAP-008`:** the matching mechanism (order-id binding vs. manual confirmation) is unconfirmed; the platform must support _some_ binding - baseline is order-ID + patient confirmation. See Section 7.1.
- **Rule 3:** Filing only - no baseline parsing (deferred, `REQ-026`); no critical-value escalation (`REQ-033`).
- **State Change:** `[Report: Uploaded]` → `[Report: Matched]` → `[Report: Filed]` | `[Report: Rejected]`.

**Telemetry & Event Tracking:**

- `report_uploaded`: `report_id`, `uploader_type` (lab|patient), `order_id`, `timestamp`
- `report_matched`: `report_id`, `order_id`, `match_method`, `timestamp`
- `report_rejected_mismatch`: `report_id`, `reason`, `timestamp`

---

### 4.6 [EPIC-06]: Pharmacy Fulfillment & Delivery

_Traceability: `REQ-010`, `REQ-014`, `REQ-027`, `REQ-031`, `REQ-037`, `GAP-007`_

#### Feature 4.6.1: Medicine Fulfillment Routing

- **Feature ID:** `FEAT-012`
- **Traceability:** `REQ-010`, `REQ-014`, `REQ-027`
- **Priority:** Must Have

**User Story:**

> As a **[Chemist Partner]**, I want **[to receive an approved e-prescription routed to me and fulfill it with my own rider]**, so that **[the patient gets medicine without the platform holding inventory]**.

**Acceptance Criteria (BDD / Gherkin):**

- **Scenario 1: Happy Path**
  - **Given** an approved e-prescription exists
  - **When** the prescription is routed to the patient's chosen / nearest chemist
  - **Then** the chemist prepares the order and delivers it via their own rider; the platform records fulfillment status
- **Scenario 2: Edge Case - item unavailable at the routed chemist**
  - **Given** the routed chemist cannot fill an item
  - **When** the chemist updates the order
  - **Then** the out-of-stock workflow (`FEAT-013`) starts

**Business Rules & State Transitions:**

- **Rule 1:** Zero platform inventory - every item fulfilled by partner chemists (`REQ-010`, `REQ-014`).
- **Rule 2:** Routing is to the patient's chosen or nearest chemist (`REQ-027`).
- **State Change:** `[Rx: Approved]` → `[Rx: Routed]` → `[Rx: Preparing]` → `[Rx: Out for Delivery]` → `[Rx: Delivered]`.

**Telemetry & Event Tracking:**

- `prescription_routed`: `rx_id`, `chemist_id`, `route_basis` (chosen|nearest), `timestamp`
- `order_preparing` / `order_out_for_delivery` / `order_delivered`: `order_id`, `timestamp`

#### Feature 4.6.2: Out-of-Stock & Delivery-Failure Handling

- **Feature ID:** `FEAT-013`
- **Traceability:** `REQ-031`, `REQ-037`, `GAP-007`
- **Priority:** Must Have

**User Story:**

> As a **[Patient]**, I want **[to decide what happens when an item is out of stock or a delivery fails]**, so that **[my care is not silently stalled]**.

**Acceptance Criteria (BDD / Gherkin):**

- **Scenario 1: Happy Path - out-of-stock choice**
  - **Given** an item is out of stock at the routed chemist
  - **When** I am notified
  - **Then** I choose to accept partial fulfillment or cancel, and the choice is recorded
- **Scenario 2: Edge Case - delivery/pickup failure**
  - **Given** a delivery or pickup attempt fails
  - **When** the failure is recorded
  - **Then** I choose between retrying off-platform (direct with the partner) or returning to the platform for a retry/reroute

**Business Rules & State Transitions:**

- **Rule 1:** The patient is always notified and always chooses (partial fulfillment vs. cancel; off-platform vs. platform retry).
- **Rule 2:** **Open decision `GAP-007`:** no time-bound partner-action SLA is defined. Baseline: no commitment time; the platform records partner response latency for measurement. See Section 7.1.
- **State Change:** `[Rx: Preparing]` → `[Rx: Partial]` / `[Rx: Cancelled]` | `[Delivery: Failed]` → `[Delivery: Off-Platform Retry]` / `[Delivery: Platform Retry]`.

**Telemetry & Event Tracking:**

- `out_of_stock_notified`: `order_id`, `item_ids`, `timestamp`
- `patient_choice_partial` / `patient_choice_cancel`: `order_id`, `timestamp`
- `delivery_failure`: `order_id`, `reason`, `timestamp`
- `retry_path_selected`: `order_id`, `path` (off_platform|platform), `timestamp`

---

### 4.7 [EPIC-07]: Partner Onboarding & Operations

_Traceability: `REQ-011`, `REQ-028`, `REQ-005`, `GAP-002`, `AMB-003`, `NFR-001`_

#### Feature 4.7.1: Open Registration & Gated Activation

- **Feature ID:** `FEAT-014`
- **Traceability:** `REQ-011`, `REQ-028`, `REQ-005`
- **Priority:** Must Have

**User Story:**

> As a **[Doctor / Lab / Chemist]**, I want **[to register openly and be activated only after my credentials are verified]**, so that **[onboarding stays low-friction while the platform stays trustworthy]**.

**Acceptance Criteria (BDD / Gherkin):**

- **Scenario 1: Happy Path**
  - **Given** I am an independent local doctor, registered lab, or retail chemist
  - **When** I register and submit my credentials
  - **Then** my profile enters verification; I am not searchable until activated
- **Scenario 2: Edge Case - credentials fail verification**
  - **Given** my submitted credentials are invalid or unverifiable
  - **When** verification runs
  - **Then** my activation is rejected and I am notified of the specific failure

**Business Rules & State Transitions:**

- **Rule 1:** Registration is open to all eligible partner types; activation is gated on credential verification (`REQ-011`, `REQ-028`).
- **Rule 2:** Only activated partners receive patients (`REQ-028`).
- **State Change:** `[Partner: Registered]` → `[Partner: Under Verification]` → `[Partner: Active]` | `[Partner: Rejected]`.

**Telemetry & Event Tracking:**

- `partner_registered`: `partner_id`, `partner_type`, `timestamp`
- `partner_verification_started` / `partner_activated` / `partner_rejected`: `partner_id`, `reason`, `timestamp`

#### Feature 4.7.2: Operator Console - Verification & Moderation

- **Feature ID:** `FEAT-015`
- **Traceability:** `REQ-028`, `GAP-002`, `AMB-003`, `NFR-001`
- **Priority:** Must Have

**User Story:**

> As an **[Operator]** , I want **[a console to verify partner credentials and manage activation]**, so that **[the platform can gate partners without a support team]**.

**Acceptance Criteria (BDD / Gherkin):**

- **Scenario 1: Happy Path**
  - **Given** a partner is Under Verification
  - **When** I review their credentials
  - **Then** I can approve or reject activation, and the partner's status updates accordingly
- **Scenario 2: Edge Case - verification backlog**
  - **Given** a backlog of pending verifications
  - **When** I view the queue
  - **Then** I can prioritize by age of registration to meet the activation cycle target (KPI-004)

**Business Rules & State Transitions:**

- **Rule 1:** **Open decision `AMB-003`:** the verification mechanism (fully automated vs. automated + manual review) is undecided - it directly affects operator headcount under `NFR-001`. Baseline: automated checks with manual review for flagged cases.
- **State Change:** N/A (operator workflow).

**Telemetry & Event Tracking:**

- `operator_decision`: `partner_id`, `action` (approve|reject), `actor_id`, `timestamp`
- `verification_duration`: `partner_id`, `duration_hours`, `timestamp`

---

### 4.8 [EPIC-08]: Payments, Settlement, Cancellations & Refunds

_Traceability: `REQ-029`, `REQ-030`, `REQ-032`, `REQ-036`, `RISK-001`, `AMB-004`, `CFL-001`, `GAP-010`_

#### Feature 4.8.1: Settlement & Payments

- **Feature ID:** `FEAT-016`
- **Traceability:** `REQ-029`, `REQ-030`, `RISK-001`, `AMB-004`, `CFL-001`, `GAP-010`
- **Priority:** Must Have

**User Story:**

> As a **[Patient and Partner]**, I want **[payment settled at the point of service, with platform facilitation only where fraud risk is higher]**, so that **[money flows directly between patient and partner and the platform stays out of the middle]**.

**Acceptance Criteria (BDD / Gherkin):**

- **Scenario 1: Happy Path - direct settlement**
  - **Given** a service is completed (delivery, pickup, or consult-related handoff)
  - **When** the patient pays cash/UPI at the point of service
  - **Then** settlement completes directly with the partner; the platform records only the outcome
- **Scenario 2: Edge Case - fraud-risk case (platform-facilitated)**
  - **Given** a transaction meets the fraud-risk threshold
  - **When** the patient chooses platform-facilitated payment
  - **Then** the platform facilitates the payment, records it, and notes the facilitation reason

**Business Rules & State Transitions:**

- **Rule 1:** Cash/UPI at point of service is primary; platform-facilitated is the exception (`REQ-029`, `REQ-030`).
- **Rule 2:** **Open decisions `AMB-004`/`CFL-001`:** the fraud-risk trigger and the overlap between REQ-029/REQ-030/REQ-027 are undecided; the RGD's `CONFLICT-001` is closed via supersession. Baseline: platform-facilitated only when both parties opt in and a risk signal exists. See Section 7.1.
- **Rule 3:** **Open decision `GAP-010`:** payment capture/receipt/reconciliation detail is undefined. Baseline: platform records settlement outcome; receipts are partner-issued. See Section 7.1.
- **State Change:** `[Settlement: Direct]` / `[Settlement: Platform-Facilitated]` → `[Settlement: Completed]`.

**Telemetry & Event Tracking:**

- `settlement_recorded`: `order_id`, `type` (cash|upi|platform_facilitated), `amount`, `timestamp`
- `platform_payment_initiated`: `order_id`, `reason` (risk_signal), `timestamp`

#### Feature 4.8.2: Cancellations & Refunds

- **Feature ID:** `FEAT-017`
- **Traceability:** `REQ-032`, `REQ-036`
- **Priority:** Must Have

**User Story:**

> As a **[Patient]**, I want **[cancellation policies shown before booking and refunds handled directly by the partner]**, so that **[I know the rules in advance and the platform stays neutral]**.

**Acceptance Criteria (BDD / Gherkin):**

- **Scenario 1: Happy Path - cancellation policy shown at booking**
  - **Given** I am about to book a service
  - **When** the booking screen loads
  - **Then** the relevant partner's cancellation policy is displayed clearly before I confirm
- **Scenario 2: Edge Case - refund after cancellation**
  - **Given** a cancellation triggers a refund
  - **When** the cancellation is recorded
  - **Then** the partner refunds the patient directly; the platform does not hold or process the refund

**Business Rules & State Transitions:**

- **Rule 1:** Policy inheritance - each partner's policy applies to their services (`REQ-032`).
- **Rule 2:** Platform assumes no responsibility for cancellation/refund disputes (`REQ-032`); platform holds/processes no refunds (`REQ-036`).
- **State Change:** `[Order: Active]` → `[Order: Cancelled]` → `[Refund: Partner-Direct]`.

**Telemetry & Event Tracking:**

- `cancellation_policy_viewed`: `order_id`, `provider_id`, `timestamp`
- `order_cancelled`: `order_id`, `cancelled_by` (patient|partner), `timestamp`
- `refund_initiated_by_partner`: `order_id`, `timestamp`

---

### 4.9 [EPIC-09]: Chronic Care Loop

_Traceability: `REQ-015`, `REQ-035`, `REQ-006`, `CFL-004`, `AMB-005`_

#### Feature 4.9.1: Chronic Metric Logging & Follow-Ups

- **Feature ID:** `FEAT-018`
- **Traceability:** `REQ-015`, `REQ-035`, `CFL-004`, `AMB-005`
- **Priority:** Must Have

**User Story:**

> As a **[Patient]**, I want **[to log daily BP/sugar metrics and see follow-ups in the web app]**, so that **[my chronic condition is continuously tracked beyond single visits]**.

**Acceptance Criteria (BDD / Gherkin):**

- **Scenario 1: Happy Path - daily metric logging**
  - **Given** I am enrolled in chronic care
  - **When** I log my BP and/or sugar for the day
  - **Then** the values are stored in my longitudinal record and shown on my tracking view
- **Scenario 2: Edge Case - out-of-range value**
  - **Given** a logged value is outside a safe range
  - **When** I log it
  - **Then** the value is stored and surfaced to my care loop, with no automated clinical action (interpretation left to the patient/doctor per `REQ-033`)

**Business Rules & State Transitions:**

- **Rule 1:** Interaction surface is the web app; WhatsApp is notifications-only (`REQ-035`).
- **Rule 2:** **Open decision `CFL-004`/`AMB-005`:** with whom follow-up "interactions" occur (self-service vs. on-platform doctor Q&A vs. re-booking) is undecided. Baseline: follow-ups are patient self-service logging + scheduled re-test nudges; doctor interaction stays off-platform. See Section 7.1.
- **State Change:** `[Log: Due]` → `[Log: Recorded]` → `[Log: Acknowledged in Loop]`.

**Telemetry & Event Tracking:**

- `metric_logged`: `patient_id`, `metric_type` (bp|sugar), `value`, `timestamp`
- `metric_out_of_range`: `patient_id`, `metric_type`, `value`, `timestamp`
- `follow_up_due`: `patient_id`, `follow_up_type` (30d|90d), `timestamp`

#### Feature 4.9.2: WhatsApp Notifications

- **Feature ID:** `FEAT-019`
- **Traceability:** `REQ-035`, `REQ-006`
- **Priority:** Must Have

**User Story:**

> As a **[Patient]**, I want **[dosage reminders and re-test nudges on WhatsApp]**, so that **[I keep up with my chronic care without checking the app]**.

**Acceptance Criteria (BDD / Gherkin):**

- **Scenario 1: Happy Path - dosage reminder**
  - **Given** I have an active prescription with a dosage schedule
  - **When** a reminder time arrives
  - **Then** I receive a WhatsApp notification in my chosen language (English or Hindi)
- **Scenario 2: Edge Case - notification channel unavailable**
  - **Given** WhatsApp notification delivery fails (e.g., number not registered)
  - **When** the notification attempt completes
  - **Then** the failure is logged and the next notification is retried or the patient is prompted to confirm their number

**Business Rules & State Transitions:**

- **Rule 1:** WhatsApp sends **notifications only** - no interaction or transaction occurs there (`REQ-035`).
- **Rule 2:** Notification language follows the patient's language setting (`REQ-006`).
- **State Change:** `[Notify: Scheduled]` → `[Notify: Sent]` → `[Notify: Delivered/Failed]`.

**Telemetry & Event Tracking:**

- `notification_scheduled`: `patient_id`, `type` (dosage|retest_30|retest_90), `timestamp`
- `notification_delivered` / `notification_failed`: `patient_id`, `notification_id`, `timestamp`

---

### 4.10 [EPIC-10]: Compliance & Audit

_Traceability: `REQ-005`, `NFR-002`, `GAP-011`, `GAP-013`_

#### Feature 4.10.1: Audit Trail & Consent Lifecycle

- **Feature ID:** `FEAT-020`
- **Traceability:** `NFR-002`, `REQ-005`, `GAP-011`, `GAP-013`
- **Priority:** Must Have

**User Story:**

> As an **[Operator]**, I want **[a complete, append-only audit trail of regulated acts and consent events]**, so that **[the platform can demonstrate the pure-facilitator posture and DPDP compliance]**.

**Acceptance Criteria (BDD / Gherkin):**

- **Scenario 1: Happy Path - audit completeness**
  - **Given** any regulated act occurs (prescription issued, consent granted/revoked, record accessed, report filed)
  - **When** the act is recorded
  - **Then** the event is written to an append-only audit log with actor, timestamp, and scope
- **Scenario 2: Edge Case - tamper attempt**
  - **Given** an attempt to modify or delete an audit record
  - **When** the attempt is made
  - **Then** the log rejects the modification and the attempt itself is recorded

**Business Rules & State Transitions:**

- **Rule 1:** Audit log is append-only and covers consent, record access, prescription issuance, and report filing (`GAP-011`).
- **Rule 2:** **Open decision `GAP-013`:** consent versioning, withdrawal flow, breach notification, and data-localization specifics are undecided; `NFR-002` states the DPDP baseline. See Section 7.1.
- **State Change:** N/A (write-only log).

**Telemetry & Event Tracking:**

- `audit_event_written`: `event_type`, `actor_id`, `target_id`, `timestamp`
- `audit_tamper_attempt`: `event_id`, `timestamp`

---

## 5. System Workflows & Edge Cases

### 5.1 End-to-End Operational Workflow - Full Care Loop (Daltonganj)

1. **Patient registers and authenticates** (`FEAT-001`); a stable identity is created.
2. **Patient discovers a provider** - GP, lab, or chemist - via the directory (`FEAT-004`); sees verified credentials (`FEAT-005`).
3. **Patient submits symptoms** by voice or text in English/Hindi (`FEAT-006`); the AI generates a clinical pre-summary (`FEAT-007`).
4. **Patient and doctor consult off-platform** (`REQ-004`); the doctor marks the consult complete on-platform (`FEAT-008`) - the handshake seam is the open `CFL-003` decision.
5. **Doctor issues an e-prescription**: AI drafts from a voice note/photo; the doctor reviews and approves (`FEAT-009`).
6. **Patient books diagnostics** (home pickup or partner lab/pickup point; direct fallback) (`FEAT-010`).
7. **Lab returns the report**; the upload is matched to the order and patient before filing (`FEAT-011`).
8. **Prescription routes to the patient's chosen/nearest chemist**, who fulfills via own rider (`FEAT-012`); out-of-stock and delivery failures follow `FEAT-013`.
9. **Settlement occurs at point of service** (cash/UPI primary) (`FEAT-016`); cancellations/refunds follow partner policy (`FEAT-017`).
10. **Chronic care continues**: daily metric logging on the web app, WhatsApp reminders/nudges only (`FEAT-018`, `FEAT-019`). Every regulated act and consent lands in the audit log (`FEAT-020`).

### 5.2 Error Scenarios & System Fallbacks

| Error Trigger                                         | System Response / Error Message                    | Recovery Action                                                                           |
| :---------------------------------------------------- | :------------------------------------------------- | :---------------------------------------------------------------------------------------- |
| Network timeout during intake upload                  | "Connection lost - retry" message                  | Auto-retry up to 3 times with backoff; prompt to re-record if audio unusable (`FEAT-006`) |
| AI structuring confidence below threshold             | Pre-summary flagged "low confidence - verify"      | Forced doctor review before use (`FEAT-007`)                                              |
| Lab report upload mismatch                            | "This report does not match the order/patient"     | Reject and do not file; patient/lab re-upload (`FEAT-011`)                                |
| Out-of-stock at routed chemist                        | "Item unavailable" notification with options       | Patient chooses partial fulfillment or cancel (`FEAT-013`)                                |
| Delivery/pickup failure                               | "Delivery failed" notification with options        | Patient chooses off-platform or platform retry/reroute (`FEAT-013`)                       |
| Credential expiry/revocation detected                 | Provider deactivated; "verified" indicator removed | Re-verification flow (`FEAT-005`, `FEAT-014`)                                             |
| WhatsApp delivery failure                             | Delivery logged as failed                          | Retry next scheduled notification; prompt number confirmation (`FEAT-019`)                |
| Payment facilitator unavailable for a fraud-risk case | "Platform payment unavailable" message             | Fall back to direct cash/UPI at point of service with a risk note (`FEAT-016`)            |

---

## 6. Non-Functional Requirements (NFR Specifications)

| NFR ID        | Category           | Target Specification / Metric SLA                                                                                                                                                                                     | Traceability ID      |
| :------------ | :----------------- | :-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | :------------------- |
| **`NFR-001`** | Cost               | Total monthly operating + hosting + AI spend ≤ ₹2,000 at launch scale (KPI-007); no paid proprietary frameworks at launch                                                                                             | `NFR-001`            |
| **`NFR-002`** | Security & Privacy | Encryption in transit (TLS 1.2+) and at rest; role-based access (Patient/Partner/Operator) enforced on every record; every consent and record-access action logged (100%, per KPI-006); patient can access own record | `NFR-002`            |
| **`NFR-003`** | Performance        | Initial page load ≤ 5 s on 4G; page weight ≤ 1.5 MB; voice intake upload supported at ≥ 1 Mbps downlink; no low-bandwidth optimization below this baseline                                                            | `NFR-003`            |
| **`NFR-004`** | Availability       | Best-effort availability (no uptime SLA); durability floor: backups at least daily (RPO ≤ 24 h), restore validated at least monthly                                                                                   | `NFR-004`, `GAP-012` |
| **`NFR-D01`** | Auditability       | Append-only audit log covering consent, record access, prescription issuance, report filing; retention period per compliance decision (open `GAP-011`)                                                                | `GAP-011`            |
| **`NFR-D02`** | Data Governance    | Consent versioning, withdrawal flow, breach notification, data-localization decisions per DPDP (open `GAP-013`); deletion/retention rules (open `GAP-005`)                                                            | `GAP-013`, `GAP-005` |

---

## 7. Open Dependencies & Risk Matrix

### 7.1 Blockers & Open Items

> Carried forward from the Conflict & Gap Report. Each is flagged inline at the affected feature with its **baseline assumption** in use until the stakeholder decides.

- **`CFL-002` / `RISK-EVAL-003`** - Regulatory posture of AI-drafted e-prescriptions under the pure-facilitator model; compliance stakeholder `[Not Yet Elicited]`. **Baseline:** AI as drafting assistant under doctor's authority (`FEAT-009`).
- **`CFL-003` / `GAP-003`** - Who triggers the off-platform consult → on-platform prescription handshake. **Baseline:** doctor-initiated (`FEAT-008`).
- **`CFL-004` / `AMB-005`** - Counterparty of chronic-care "follow-up interactions." **Baseline:** patient self-service logging + nudges; doctor interaction stays off-platform (`FEAT-018`).
- **`GAP-001`** - Patient identity strength (OTP vs. stronger verification). **Baseline:** phone OTP (`FEAT-001`).
- **`GAP-004` / `GAP-008`** - Report→order→patient matching mechanism. **Baseline:** order-ID binding + patient confirmation (`FEAT-011`).
- **`GAP-007`** - Time-bound partner-action SLA. **Baseline:** none; latency measured (KPI-008 input) (`FEAT-013`).
- **`GAP-010`** - Payment capture/receipt/reconciliation detail. **Baseline:** platform records settlement outcome; partner issues receipts (`FEAT-016`).
- **`GAP-011` / `GAP-012` / `GAP-013` / `GAP-005`** - Audit retention, DR policy, consent lifecycle, retention/deletion - compliance decisions needed (Section 6 NFR-D01/D02).
- **`AMB-002`** - Acceptance bar for "full care loop proven" (defines KPI-001/008 targets). **Baseline:** proposed targets in Section 1.3.
- **`AMB-003`** - Verification mechanism (automated vs. manual). **Baseline:** automated checks + manual review for flagged cases (`FEAT-015`).
- **`AMB-004` / `CFL-001`** - Fraud-risk trigger for platform-facilitated payment; consolidation of REQ-029/REQ-030/REQ-027. **Baseline:** opt-in + risk signal (`FEAT-016`).
- **`AMB-006`** - Structured-extraction accuracy threshold and low-confidence fallback. **Baseline:** flag below-confidence results (`FEAT-007`).
- **`ISSUE-004`** - Geographic expansion intent beyond Daltonganj: undecided. No downstream dependency at launch.

### 7.2 Risk Register & Operational Mitigations

| Risk ID             | Risk Description                                                | Category                         | Impact | Mitigation Strategy                                                                      | Traceability                     |
| :------------------ | :-------------------------------------------------------------- | :------------------------------- | :----- | :--------------------------------------------------------------------------------------- | :------------------------------- |
| **`RISK-001`**      | Payment fraud between patient and partner                       | Financial                        | Medium | Cash/UPI direct primary; platform-facilitated only on risk signal (REQ-030)              | `REQ-030`, `FEAT-016`            |
| **`RISK-002`**      | Wrong/mismatched lab report attached to wrong patient           | Data integrity / clinical safety | High   | Order-ID + patient confirmation binding before filing (FEAT-011); KPI-003 = 0 mismatches | `REQ-025`, `FEAT-011`            |
| **`RISK-EVAL-003`** | AI-drafted prescription regulatory exposure                     | Legal/Regulatory                 | High   | Pending compliance sign-off (CFL-002); doctor approval gate before issuance              | `REQ-005`, `REQ-023`, `FEAT-009` |
| **`RISK-EVAL-004`** | Single-city dependency on Daltonganj partner supply & demand    | Commercial                       | Medium | Activation-cycle KPI (KPI-004); open supply-side elicitation; ISSUE-004 gates expansion  | `REQ-002`, `REQ-008`             |
| **`RISK-EVAL-005`** | Data loss on longitudinal record under best-effort availability | Data                             | High   | Daily backup floor (RPO ≤ 24 h), monthly restore validation (NFR-004)                    | `REQ-021`, `NFR-004`             |
| **`RISK-EVAL-006`** | Hindi voice extraction quality vs. near-zero AI cost            | Feasibility                      | Medium | Early spike to validate; low-confidence fallback to doctor review (AMB-006)              | `REQ-007`, `NFR-001`, `FEAT-007` |

---

## 8. Requirements Traceability Matrix (RTM)

| Feature / User Story ID | Original Requirement ID         | Conflict / Gap ID                           | Final PRD Status                               |
| :---------------------- | :------------------------------ | :------------------------------------------ | :--------------------------------------------- |
| `FEAT-001`              | `REQ-021`, `REQ-003`            | `GAP-001`                                   | Baseline Approved (open decision)              |
| `FEAT-002`              | `REQ-021`                       | `GAP-005`, `GAP-013`                        | Baseline Approved (open decision)              |
| `FEAT-003`              | `REQ-021`                       | `GAP-011`                                   | Baseline Approved (open decision)              |
| `FEAT-004`              | `REQ-001`, `REQ-008`, `REQ-022` | `GAP-009`                                   | Baseline Approved                              |
| `FEAT-005`              | `REQ-005`, `REQ-028`            | -                                           | Baseline Approved                              |
| `FEAT-006`              | `REQ-006`, `REQ-007`            | -                                           | Baseline Approved                              |
| `FEAT-007`              | `REQ-004`, `REQ-007`            | `AMB-006`, `RISK-EVAL-006`                  | Baseline Approved (open decision)              |
| `FEAT-008`              | `REQ-002`, `REQ-004`, `REQ-013` | `CFL-003`, `GAP-003`                        | Baseline Approved (open decision)              |
| `FEAT-009`              | `REQ-013`, `REQ-023`, `REQ-005` | `CFL-002`, `RISK-EVAL-003`                  | Baseline Approved (open decision)              |
| `FEAT-010`              | `REQ-012`, `REQ-024`, `REQ-033` | -                                           | Baseline Approved                              |
| `FEAT-011`              | `REQ-025`, `REQ-033`            | `RISK-002`, `GAP-004`, `GAP-008`            | Baseline Approved (open decision)              |
| `FEAT-012`              | `REQ-010`, `REQ-014`, `REQ-027` | -                                           | Baseline Approved                              |
| `FEAT-013`              | `REQ-031`, `REQ-037`            | `GAP-007`                                   | Baseline Approved (open decision)              |
| `FEAT-014`              | `REQ-011`, `REQ-028`, `REQ-005` | -                                           | Baseline Approved                              |
| `FEAT-015`              | `REQ-028`                       | `GAP-002`, `AMB-003`                        | Baseline Approved (open decision)              |
| `FEAT-016`              | `REQ-029`, `REQ-030`            | `RISK-001`, `AMB-004`, `CFL-001`, `GAP-010` | Baseline Approved (open decision)              |
| `FEAT-017`              | `REQ-032`, `REQ-036`            | -                                           | Baseline Approved                              |
| `FEAT-018`              | `REQ-015`, `REQ-035`            | `CFL-004`, `AMB-005`                        | Baseline Approved (open decision)              |
| `FEAT-019`              | `REQ-035`, `REQ-006`            | -                                           | Baseline Approved                              |
| `FEAT-020`              | `NFR-002`, `REQ-005`            | `GAP-011`, `GAP-013`                        | Baseline Approved (open decision)              |
| `REQ-020`               | `REQ-020`                       | -                                           | Addressed - no revenue capture in scope (§3.2) |
| `REQ-026`               | `REQ-026`                       | -                                           | Out-of-Scope / Deferred (launch = filing only) |
| `REQ-038`               | `REQ-038`                       | -                                           | Out-of-Scope / Future (`[FUTURE]`)             |
| `REQ-039`               | `REQ-039`                       | -                                           | Out-of-Scope / Future (`[FUTURE]`)             |
| `REQ-040`               | `REQ-040`                       | -                                           | Out-of-Scope / Future (`[FUTURE]`)             |
| `NFR-001`               | `NFR-001`                       | -                                           | Baseline Approved (Section 6)                  |
| `NFR-002`               | `NFR-002`                       | `GAP-011`, `GAP-013`                        | Baseline Approved (Section 6)                  |
| `NFR-003`               | `NFR-003`                       | -                                           | Baseline Approved (Section 6)                  |
| `NFR-004`               | `NFR-004`                       | `GAP-012`                                   | Baseline Approved (Section 6)                  |
