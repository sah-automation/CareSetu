# Requirements Gathering Document (RGD) - CareSetu

**Document Version:** 1.0
**Date:** 2026-08-07
**Status:** Complete
**Source register:** `docs/archive/requirements/discovery-register.md` (v0.4, `Status: Complete`)

> **Schema conformance note:** the discovery register records `Created: v0.1` for every item and does not track per-item `Updated` versions. Replacement requirements (REQ-023, REQ-026, REQ-030, REQ-035, REQ-038) were authored at the supersession version indicated in Section 9; their `Updated` field below reflects that version. All other items carry `Updated: v0.1`. Flagged for `conflict-gap-analysis-in-rgd` confirmation.

---

## 1. Project Overview & Business Goals

**Product context (as stated by Founder):** End-to-end, zero-inventory aggregator marketplace connecting patients with doctors, local diagnostic labs, and retail pharmacies; digitizes the complete care loop from symptom discovery to consultation, diagnostics, e-prescription, and hyper-local medicine delivery. Primary differentiator: continuous, AI-assisted chronic care loop for Tier 3/4 Indian cities. $0 monetization initially (portfolio / open-architecture project).

- **[REQ-001 | Status: Active | Source: Founder | Created: v0.1 | Updated: v0.1] [Must Have]**: Genuinely 4-sided marketplace (patient, doctor, lab, pharmacy) with a patient-centric experience as the UX center. [IDEA] [Elicitation Confidence: High]
- **[REQ-002 | Status: Active | Source: Founder | Created: v0.1 | Updated: v0.1] [Must Have]**: First release success = full care loop proven end-to-end in one city (symptom intake → consult → diagnostics → e-prescription → delivery). [IDEA] [Elicitation Confidence: High]
- **[REQ-008 | Status: Active | Source: Founder | Created: v0.1 | Updated: v0.1] [Must Have]**: Launch beachhead: Daltonganj, Jharkhand, covering the city and surrounding/peri-urban areas. [IDEA] [Elicitation Confidence: High]
- **[REQ-015 | Status: Active | Source: Founder | Created: v0.1 | Updated: v0.1] [Must Have]**: Core differentiator: shift from transactional "booking directory" to a continuous, AI-assisted chronic care loop. [IDEA] [Elicitation Confidence: High]
- **[REQ-020 | Status: Active | Source: Founder | Created: v0.1 | Updated: v0.1] [Must Have]**: $0 monetization initially (portfolio / open-architecture project). [IDEA] [Elicitation Confidence: High]

## 2. Prioritized Functional Requirements (MoSCoW)

### Must Have

- **[REQ-003 | Status: Active | Source: Founder | Created: v0.1 | Updated: v0.1] [Must Have]**: Primary patient access channel is web-based (mobile web/PWA, no install, works over 4G). Stated "for now" - future channels deferred (see REQ-040). [IDEA] [Elicitation Confidence: High]
- **[REQ-004 | Status: Active | Source: Founder | Created: v0.1 | Updated: v0.1] [Must Have]**: Consultation model: AI-generated asynchronous clinical pre-summary from structured symptom intake; the actual doctor-patient consult happens off-platform. [IDEA] [Elicitation Confidence: High]
- **[REQ-005 | Status: Active | Source: Founder | Created: v0.1 | Updated: v0.1] [Must Have]**: Compliance posture: pure facilitator. Platform verifies and displays partner credentials; regulated acts (consult, e-prescription, dispensing/delivery, lab testing) stay with licensed partners. [IDEA] [Elicitation Confidence: High]
- **[REQ-006 | Status: Active | Source: Founder | Created: v0.1 | Updated: v0.1] [Must Have]**: Patient-facing experience supports English + Hindi at launch. [IDEA] [Elicitation Confidence: High]
- **[REQ-007 | Status: Active | Source: Founder | Created: v0.1 | Updated: v0.1] [Must Have]**: Symptom intake accepts both voice and text; AI structures unstructured English/Hindi input into the clinical pre-summary. (Related: REQ-004, REQ-006) [IDEA] [Elicitation Confidence: High]
- **[REQ-010 | Status: Active | Source: Founder | Created: v0.1 | Updated: v0.1] [Must Have]**: Zero platform inventory; every product/service fulfilled by partner doctors, labs, chemists. [IDEA] [Elicitation Confidence: High]
- **[REQ-011 | Status: Active | Source: Founder | Created: v0.1 | Updated: v0.1] [Must Have]**: Open onboarding for independent local doctors, registered pathology labs (incl. franchised pickup points), and local retail chemists, to minimize operational overhead. [IDEA] [Elicitation Confidence: High]
- **[REQ-012 | Status: Active | Source: Founder | Created: v0.1 | Updated: v0.1] [Must Have]**: Diagnostics: patient chooses home sample pickup or a partner lab / pickup point. [IDEA] [Elicitation Confidence: High]
- **[REQ-013 | Status: Active | Source: Founder | Created: v0.1 | Updated: v0.1] [Must Have]**: E-prescription generated on-platform by the doctor (flow per REQ-023). [IDEA] [Elicitation Confidence: High]
- **[REQ-014 | Status: Active | Source: Founder | Created: v0.1 | Updated: v0.1] [Must Have]**: Hyper-local medicine delivery fulfilled by local retail chemists. [IDEA] [Elicitation Confidence: High]
- **[REQ-021 | Status: Active | Source: Founder | Created: v0.1 | Updated: v0.1] [Must Have]**: Patient data: central longitudinal health record per patient on-platform; patient consents per action (record access, sharing with doctor/lab/pharmacy). [IDEA] [Elicitation Confidence: High]
- **[REQ-022 | Status: Active | Source: Founder | Created: v0.1 | Updated: v0.1] [Must Have]**: Doctor pool: general physicians / GPs plus local specialists, specialists onboarded as available. [IDEA] [Elicitation Confidence: High]
- **[REQ-023 | Status: Active | Source: Founder | Created: v0.1 | Updated: v0.4] [Must Have]**: Post-consult e-prescription: doctor submits a voice note or photo; AI drafts the prescription; doctor reviews and approves before issuance. (Closes ISSUE-001) [IDEA] [Elicitation Confidence: High]
- **[REQ-028 | Status: Active | Source: Founder | Created: v0.1 | Updated: v0.1] [Must Have]**: Partner onboarding: gated - credentials verified (manual or automated) before the partner goes live. Registration remains open (REQ-011); activation gated. (Closes ISSUE-002) [IDEA] [Elicitation Confidence: High]
- **[REQ-035 | Status: Active | Source: Founder | Created: v0.1 | Updated: v0.3] [Must Have]**: Chronic care loop (launch scope): daily BP/sugar metric logging and follow-up interactions happen on the web app; WhatsApp sends notifications only (dosage reminders, 30/90-day re-test nudges). (Supersedes REQ-034, REQ-018) [IDEA] [Elicitation Confidence: High]

### Deferred

- **[REQ-026 | Status: Active | Source: Founder | Created: v0.1 | Updated: v0.2] [Deferred]**: Lab-report baseline parsing deferred to a later phase; launch scope = report filing only. (Supersedes REQ-017) [IDEA] [Elicitation Confidence: High]

### Could Have

- **[REQ-038 | Status: Active | Source: Founder | Created: v0.1 | Updated: v0.4] [Could Have]**: ABHA integration: future goal, important (health-record portability via ABHA), post-launch. (Supersedes REQ-019) [FUTURE] [Elicitation Confidence: High]
- **[REQ-039 | Status: Active | Source: Founder | Created: v0.1 | Updated: v0.1] [Could Have]**: Future monetization: commercial path likely after launch (commission / subscription / freemium); model deferred and unspecified. [FUTURE] [Elicitation Confidence: High]
- **[REQ-040 | Status: Active | Source: Founder | Created: v0.1 | Updated: v0.1] [Could Have]**: Patient access channels beyond web (e.g., native app, WhatsApp-first) as future possibilities. [FUTURE] [Elicitation Confidence: Medium]

## 3. Contextual Non-Functional Requirements (NFRs)

- **[NFR-001 | Status: Active | Source: Founder | Created: v0.1 | Updated: v0.1] Cost [Must Have]**: Near-zero developer + operational hosting cost during development (open-source frameworks, serverless/lightweight backend, freemium AI/LLM tiers). Specific stack = architecture, deferred to later stages. [ASSUMPTION] [Elicitation Confidence: High]
- **[NFR-002 | Status: Active | Source: Founder | Created: v0.1 | Updated: v0.1] Privacy & Security [Must Have]**: Health-data privacy/security baseline: encryption at rest + in transit, role-based access, consent logging, patient access to own record (DPDP baseline). [ASSUMPTION] [Elicitation Confidence: High]
- **[NFR-003 | Status: Active | Source: Founder | Created: v0.1 | Updated: v0.1] Performance & Connectivity [Should Have]**: Standard web performance assuming reasonable 4G; no special low-bandwidth optimization at launch. [ASSUMPTION] [Elicitation Confidence: High]
- **[NFR-004 | Status: Active | Source: Founder | Created: v0.1 | Updated: v0.1] Availability [Must Have]**: Best-effort (portfolio), no SLA, occasional downtime acceptable. [ASSUMPTION] [Elicitation Confidence: High]

## 4. Operational Workflows, Edge Cases & Error Scenarios

- **[REQ-024 | Status: Active | Source: Founder | Created: v0.1 | Updated: v0.1] [Must Have]**: Diagnostics pickup: hybrid - on-platform booking where a partner lab / pickup point is available; direct patient-to-lab arrangement as fallback. [IDEA] [Elicitation Confidence: High]
- **[REQ-025 | Status: Active | Source: Founder | Created: v0.1 | Updated: v0.1] [Must Have]**: Lab report return: lab or patient uploads (whoever has it first), filed into the patient's central record. Must include protection against wrong/mismatched report upload. [IDEA] [Elicitation Confidence: High]
- **[REQ-027 | Status: Active | Source: Founder | Created: v0.1 | Updated: v0.1] [Must Have]**: Medicine fulfillment: approved e-prescription routed to patient's chosen / nearest partner chemist; chemist prepares and delivers via own rider; payment platform-facilitated or cash/UPI on delivery. [IDEA] [Elicitation Confidence: High]
- **[REQ-029 | Status: Active | Source: Founder | Created: v0.1 | Updated: v0.1] [Must Have]**: Settlement model: cash/UPI at point of service is primary; platform-facilitated payments handled on a case-by-case basis. [IDEA] [Elicitation Confidence: High]
- **[REQ-030 | Status: Active | Source: Founder | Created: v0.1 | Updated: v0.3] [Must Have]**: Payments (revised): direct/cash (cash/UPI) is primary; platform-facilitated payment preferred only where fraud risk between the two parties is higher. (Supersedes REQ-009; resolves CONFLICT-001) [IDEA] [Elicitation Confidence: High]
- **[REQ-031 | Status: Active | Source: Founder | Created: v0.1 | Updated: v0.1] [Must Have]**: Out-of-stock handling: patient is notified and chooses - accept partial fulfillment or cancel. [IDEA] [Elicitation Confidence: High]
- **[REQ-032 | Status: Active | Source: Founder | Created: v0.1 | Updated: v0.1] [Must Have]**: Cancellations: policy inherits the relevant partner's (doctor/lab/chemist) policy, shown clearly to the patient at booking time; platform assumes no responsibility for cancellation/refund disputes. [IDEA] [Elicitation Confidence: High]
- **[REQ-033 | Status: Active | Source: Founder | Created: v0.1 | Updated: v0.1] [Must Have]**: Critical lab values: no automated escalation at launch; reports are filed, interpretation left to patient/doctor. [IDEA] [Elicitation Confidence: High]
- **[REQ-036 | Status: Active | Source: Founder | Created: v0.1 | Updated: v0.1] [Must Have]**: Refunds: the partner refunds the patient directly; the platform does not hold or process refunds. (Closes ISSUE-003) [IDEA] [Elicitation Confidence: High]
- **[REQ-037 | Status: Active | Source: Founder | Created: v0.1 | Updated: v0.1] [Must Have]**: Delivery/pickup failure: patient chooses either to arrange a retry off-platform (direct with partner) or return to the platform for retry/reroute; platform supports both paths. [IDEA] [Elicitation Confidence: High]

## 5. Captured Perceived Risks

- **[RISK-001 | Category: Financial | Source: Founder | Related IDs: REQ-030]**: Payment fraud between patient and partner - stated motivation for preferring platform-facilitated payment in select transactions. [Status: Open]
- **[RISK-002 | Category: Data integrity / clinical safety | Source: Founder | Related IDs: REQ-025]**: Wrong/mismatched lab report attached to the wrong patient. [Status: Open]

## 6. Potential Conflicts Register (For Downstream Analysis)

- **[CONFLICT-001 | Related IDs: REQ-009, REQ-029, REQ-030 | Status: Pending Analysis]**: Literal inconsistency between `REQ-009` ("prioritize platform-facilitated payments") and `REQ-029` ("cash/UPI at point of service primary") over which payment mode is primary. **Discovery resolution note:** register records this as reconciled in-session - REQ-009 superseded by REQ-030 (direct/cash primary; platform-facilitated only where fraud risk higher). Since REQ-009 is now `Superseded` (Section 9), no literal conflict remains between active items; `conflict-gap-analysis-in-rgd` to confirm.

## 7. Decision & Open Issues Register

**Open Questions:**

- [ ] **[ISSUE-004 | Category: Open Question | Source: Founder | Status: Open]**: Geographic expansion intent beyond Daltonganj: not decided (replicate Tier 3/4 city-by-city vs move up-tier vs single-city).

**Resolved during discovery (closing notes, for audit continuity):**

- ISSUE-001 (e-prescription flow) → resolved by REQ-023
- ISSUE-002 (partner activation gating) → resolved by REQ-028
- ISSUE-003 (platform refund handling) → resolved by REQ-036

## 8. Categorized Inventory Matrix

- **Facts:** None captured - the register contains no `[FACT]` items; all captures derive from a single Founder voice.
- **Assumptions:** NFR-001, NFR-002, NFR-003, NFR-004 - most likely to be revised under future stakeholder elicitation.
- **Ideas:** REQ-001, REQ-002, REQ-003, REQ-004, REQ-005, REQ-006, REQ-007, REQ-008, REQ-010, REQ-011, REQ-012, REQ-013, REQ-014, REQ-015, REQ-020, REQ-021, REQ-022, REQ-023, REQ-024, REQ-025, REQ-026, REQ-027, REQ-028, REQ-029, REQ-030, REQ-031, REQ-032, REQ-033, REQ-035, REQ-036, REQ-037
- **Future Possibilities:** REQ-038 (ABHA integration), REQ-039 (future monetization), REQ-040 (channels beyond web)

## 9. Superseded Requirements Log

- **[REQ-009 | Status: Superseded | Source: Founder | Created: v0.1 | Superseded: v0.3 by REQ-030]**: Hybrid payments; prioritize platform-facilitated (fraud protection), direct/cash fallback.
- **[REQ-016 | Status: Superseded | Source: Founder | Created: v0.1 | Superseded: v0.4 by REQ-023]**: Computer-vision extraction of test metrics / medicine names from handwritten or PDF prescriptions.
- **[REQ-017 | Status: Superseded | Source: Founder | Created: v0.1 | Superseded: v0.2 by REQ-026]**: Lab-report parsing against past baselines (HbA1c, thyroid, lipid) to flag critical anomalies.
- **[REQ-018 | Status: Superseded | Source: Founder | Created: v0.1 | Superseded: v0.3 by REQ-035]**: WhatsApp AI follow-ups: dosage reminders, daily metric logging, 30/90-day re-test scheduling.
- **[REQ-019 | Status: Superseded | Source: Founder | Created: v0.1 | Superseded: v0.4 by REQ-038]**: Integration with ABHA / government-private infrastructure ("can integrate").
- **[REQ-034 | Status: Superseded | Source: Founder | Created: v0.1 | Superseded: v0.3 by REQ-035]**: Chronic care loop launch scope: WhatsApp AI follow-ups.

## 10. Out of Scope / Unelicited Sections

- **[Not Yet Elicited]** - discovery is complete across Phases 1–3 but with a single stakeholder source. All captures are tagged `Source: Founder`. Unexplored / not-yet-elicited areas for future sessions:
  - **Supply-side partners** (doctors, labs, chemists) - validate onboarding (REQ-028), fulfillment (REQ-024/027/031/037), and settlement (REQ-029/030/036) assumptions they carry.
  - **Patients** - validate channel model (REQ-003 web-first, REQ-035 WhatsApp-notify), language (REQ-006), and consent UX (REQ-021).
  - **Compliance / regulatory** - validate pure-facilitator posture (REQ-005) and DPDP baseline (NFR-002).
- **[Schema flag]** - per-item `Updated` versions were not tracked in the source register; `Updated` values here reflect supersession timing from Section 9. Confirm during audit.
