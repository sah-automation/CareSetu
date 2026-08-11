# Requirements Conflict & Gap Analysis Report - CareSetu

**Ingested Document Version:** RGD v1.0 (`docs/archive/requirements/rgd.md`)
**Analysis Date:** 2026-08-07
**Overall Requirements Health Score:** **Medium**

---

## 1. Executive Summary & Critical Blockers

- **Key Findings:** Elicitation breadth is strong - 34 functional requirements, 4 NFRs, 2 risks, all tagged with complete metadata and mostly `[Elicitation Confidence: High]`. However, the entire corpus derives from a **single Founder source**, contains **zero `[FACT]` items**, and every NFR is an `[ASSUMPTION]`. The product is a **regulated healthcare marketplace** with a "pure facilitator" posture, yet the operational seams where the platform hands off to licensed partners are the least specified - and those seams carry the highest clinical, regulatory, and data-integrity risk.
- **Critical Blockers** (must resolve before PRD drafting or architecture):
  1. **AI-drafted e-prescriptions vs. "pure facilitator" posture** ([CFL-002]) - regulatory position on the platform's AI drafting a prescription is unvalidated (compliance stakeholder `[Not Yet Elicited]`).
  2. **Off-platform consult → on-platform prescription handshake** ([CFL-003], [GAP-003]) - the core loop (REQ-002) has no defined trigger that moves a patient from an off-platform consult into the on-platform e-prescription flow (REQ-023).
  3. **Patient identity, consent, and record integrity** ([GAP-001], [GAP-005], [GAP-008]) - no patient authentication/identity requirement, no data retention/deletion rules, and no mechanism linking a lab order to its uploaded report (the root of RISK-002).
  4. **No operator/admin role** ([GAP-002]) - REQ-028's "manual or automated" credential verification needs an operator capability, but none is specified; conflicts with near-zero ops cost (NFR-001).
  5. **Unscoped critical NFRs for a healthcare domain** ([GAP-010]) - audit logging, backup/DR, and consent-lifecycle compliance are undefined.

---

## 2. Conflict Analysis Matrix

| Conflict ID   | Incompatible Requirement IDs                               | Stakeholders Involved                         | Nature of Conflict                                                                                                                                                                                                                                                                                                                                                                                                                   | Proposed Resolution Options                                                                                                                                                                                                                                                                                          |
| :------------ | :--------------------------------------------------------- | :-------------------------------------------- | :----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **[CFL-001]** | `REQ-027`, `REQ-029`, `REQ-030` (+ carries `CONFLICT-001`) | Founder (self)                                | **Confirmed resolved / redundancy.** `CONFLICT-001` (REQ-009 vs REQ-029) is closed by supersession - REQ-009 is `[Superseded]`, so no literal active conflict remains. **Residual:** three _active_ items (REQ-027, REQ-029, REQ-030) all describe the payment/settlement model with _different_ decision triggers ("case-by-case basis" vs "where fraud risk is higher" vs "payment platform-facilitated or cash/UPI on delivery"). | 1. Consolidate into one Settlement requirement with a single decision rule (fraud-risk threshold) and delete/merge REQ-029.<br>2. Keep all three, but define what "case-by-case" and "fraud risk higher" mean operationally.                                                                                         |
| **[CFL-002]** | `REQ-005` vs. `REQ-023` (+ `REQ-013`)                      | Founder vs. Compliance (`[Not Yet Elicited]`) | **Literal tension.** REQ-005: "regulated acts (consult, e-prescription…) stay with licensed partners; platform is pure facilitator." REQ-023: "AI drafts the prescription." AI drafting a prescription is arguably the platform participating in a regulated act - direct tension with the pure-facilitator posture.                                                                                                                 | 1. Define AI as a drafting _assistant_ under the licensed doctor's authority; platform claims zero clinical liability (doctor approves before issuance).<br>2. Restrict AI to structured data capture; doctor composes the prescription. Requires compliance sign-off either way.                                    |
| **[CFL-003]** | `REQ-004` vs. `REQ-023` (+ `REQ-002`, `REQ-013`)           | Founder (self)                                | **Implicit inconsistency / undefined seam.** REQ-004: "actual doctor-patient consult happens off-platform." REQ-023/REQ-013: e-prescription is generated _on-platform_ post-consult. Nothing specifies how the platform learns a consult occurred or is triggered into the prescription flow.                                                                                                                                        | 1. Doctor-initiated: doctor opens the patient's record on-platform post-consult and initiates the prescription flow (needs doctor-side UI + linkage to the off-platform visit).<br>2. Patient-initiated: patient marks the consult done; doctor then issues.<br>3. Hybrid with a "consult completed" handshake step. |
| **[CFL-004]** | `REQ-004` vs. `REQ-035`                                    | Founder (self)                                | **Implicit tension.** REQ-004: consultations are off-platform. REQ-035: chronic-care "follow-up interactions happen on the web app." With whom does the patient interact for follow-up if the doctor is off-platform?                                                                                                                                                                                                                | 1. Follow-ups = patient self-service (logging + content), doctor offline.<br>2. Follow-ups = asynchronous doctor Q&A on-platform (breaks REQ-004 - needs decision).<br>3. Follow-ups = re-book an off-platform consult (web app is a thin orchestrator).                                                             |

---

## 3. Coverage & Gap Identification

### 3.1 Missing Operational Workflows & Edge Cases

- **[GAP-001] [Severity: High]** (Relates to `REQ-021`, `REQ-002`): **No patient identity or authentication requirement.** A central longitudinal health record (REQ-021) and per-action consent presuppose a stable patient identity, but signup, login, OTP/phone verification, and session management are unspecified. Without it, consent logging and record integrity (RISK-002's cousin) are unbuildable.
- **[GAP-002] [Severity: High]** (Relates to `REQ-028`, `NFR-001`): **No operator/admin role.** REQ-028 requires partner credential verification "manual or automated" - but no admin console, operator identity, moderation, or credential-management capability exists anywhere in the RGD. Near-zero ops cost (NFR-001) collides with manual verification headcount.
- **[GAP-003] [Severity: High]** (Relates to `REQ-004`, `REQ-023`): **Missing consult→prescription handshake workflow** - see [CFL-003]. The platform has no defined trigger or doctor-side initiation path.
- **[GAP-004] [Severity: High]** (Relates to `REQ-025`, `RISK-002`): **Wrong-report-upload protection is specified but its mechanism is not.** With baseline parsing deferred (REQ-026) and critical-value escalation excluded (REQ-033), the only available detection is identity/order matching at upload - but no requirement defines how a report is matched to a test order or patient.
- **[GAP-005] [Severity: High]** (Relates to `REQ-021`, `NFR-002`): **No data retention, deletion, or portability rules.** A lifelong longitudinal record with per-action consent has no retention schedule, no consent-revocation consequences, no right-to-erasure, no export - all required under a DPDP-compliance posture.
- **[GAP-006] [Severity: Medium]** (Relates to `REQ-007`, `REQ-033`): **No triage disclaimer / emergency path.** AI symptom intake (REQ-007) with zero critical-value escalation (REQ-033) has no requirement for a medical disclaimer, red-flag routing, or "contact emergency services" guidance.
- **[GAP-007] [Severity: Medium]** (Relates to `REQ-027`, `REQ-031`): **No time-bound partner action SLA.** Out-of-stock (REQ-031) is only discovered when the chemist acts; no requirement bounds how quickly a chemist confirms availability/accepts an order, so delivery-time expectations are unverifiable.
- **[GAP-008] [Severity: High]** (Relates to `REQ-024`, `REQ-025`): **No order→report linkage requirement.** Nothing ties the lab booking (REQ-024) to the uploaded report (REQ-025). This is the structural root of RISK-002.
- **[GAP-009] [Severity: Medium]** (Relates to `REQ-001`, `REQ-002`): **Marketplace discovery omitted.** The 4-sided marketplace (REQ-001) has no requirement for doctor/lab/chemist search, filtering by location/specialty, profiles, or slot/availability booking - the core marketplace transaction surface.
- **[GAP-010] [Severity: Medium]** (Relates to `REQ-029`, `REQ-030`): **Payment capture/reconciliation unspecified.** Settlement policy exists, but payment initiation, receipting, status tracking, and reconciliation (especially "case-by-case" platform-facilitated payments) are undefined.

### 3.2 Unaddressed Non-Functional Requirements (NFRs)

- **[GAP-011] [Domain: Healthcare / Compliance]** (Relates to `NFR-002`): **Audit logging undefined.** No requirement for an immutable audit trail of regulated acts (prescriptions issued, consents granted/revoked, records accessed, reports uploaded). Essential for a facilitator claiming zero liability and for DPDP.
- **[GAP-012] [Domain: Healthcare / Data resilience]** (Relates to `NFR-004`, `REQ-021`): **Disaster recovery / backup undefined.** NFR-004 accepts "occasional downtime," but a longitudinal health record with no backup, restore, or durability requirement risks total patient-data loss - inconsistent with REQ-021.
- **[GAP-013] [Domain: Compliance]** (Relates to `NFR-002`, `REQ-021`): **Consent lifecycle under-specified.** Per-action consent (REQ-021) lacks consent versioning, withdrawal flow, breach-notification process, and data-localization decisions (DPDP Act 2023).
- **[GAP-014] [Domain: Accessibility / Localization]** (Relates to `REQ-006`, `REQ-007`): **Partner-facing language and accessibility unspecified.** Patient-facing English+Hindi is defined; doctor/lab/chemist-facing UI language and any accessibility (screen-reader, large-font) are not.

---

## 4. Ambiguity & Quality Audit

- **[AMB-001] (Relates to `REQ-003`, `NFR-003`)**: "Works over 4G" / "reasonable 4G" is non-verifiable.
  - **Action Required:** Define targets - e.g., initial load <5s on a mid-tier 4G device, page weight <1.5 MB, and the assumed minimum downlink (e.g., 1 Mbps).
- **[AMB-002] (Relates to `REQ-002`)**: "Full care loop proven end-to-end" - success is not measurable.
  - **Action Required:** Define the proof-of-loop acceptance criteria (e.g., ≥N completed loops, ≥N prescriptions delivered, ≤X% failed orders) for the Daltonganj beachhead.
- **[AMB-003] (Relates to `REQ-028`, `NFR-001`)**: "Credentials verified (manual or automated)" is non-verifiable and cost-relevant.
  - **Action Required:** Decide the mechanism (automated checks + manual spot-check vs. fully manual) because it directly determines operator headcount under NFR-001.
- **[AMB-004] (Relates to `REQ-029`, `REQ-030`, `RISK-001`)**: "Case-by-case" and "fraud risk higher" are undefined triggers.
  - **Action Required:** State the rule that selects platform-facilitated payment (e.g., order value > ₹X, specific categories, partner risk score) or drop the mechanism.
- **[AMB-005] (Relates to `REQ-035`)**: "Follow-up interactions happen on the web app" - unclear counterparty (see [CFL-004]).
  - **Action Required:** Specify what a follow-up interaction is (self-logging vs. doctor Q&A vs. re-booking).
- **[AMB-006] (Relates to `REQ-007`, `NFR-001`)**: Hindi voice-to-text accuracy bar is unspecified, yet is a launch `[Must Have]` and depends on a freemium LLM tier (NFR-001). Non-verifiable clinical-quality bar for the pre-summary.
  - **Action Required:** Set an accuracy/acceptance threshold for structured extraction and a fallback (human/doctor review) when confidence is low.
- **[AMB-007] (Relates to `REQ-040`)**: Sole `[Elicitation Confidence: Medium]` item - "native app, WhatsApp-first as future possibilities."
  - **Action Required:** Confirm this remains `[Could Have]`/post-MVP so architecture does not prematurely pay for multi-channel abstractions. (No `[Low]`-confidence items exist in the RGD; nothing else needs this drilldown.)

---

## 5. Dependency & Risk Mapping

- **[DEP-001]**: `REQ-015` (chronic-care differentiator) → `REQ-035` (chronic loop) → `REQ-023` (e-prescription) → `REQ-004` (off-platform consult). The chain's weakest link is the unresolved [CFL-003] seam; the flagship differentiator cannot be built until the handshake is defined.
- **[DEP-002]**: `REQ-002` (loop proven in one city) depends on **partner network density** in Daltonganj (REQ-028 gated onboarding + REQ-011 open registration). Success of the beachhead is coupled to supply-side adoption, which no requirement models (no partner supply target, no ramp).
- **[DEP-003]**: `REQ-006`/`REQ-007` (Hindi voice/text) depend on LLM transcription quality and freemium pricing - both assumptions (NFR-001). Feasibility of Hindi voice in Tier 3/4 accents is untested.
- **[DEP-004]**: `REQ-025` (report filing) and `REQ-021` (longitudinal record) both depend on the missing order→report linkage ([GAP-008]); RISK-002 cannot be mitigated without it.

- **[RISK-EVAL-001] (Relates to `RISK-001`)**: Payment fraud - **Impact: Medium, Likelihood: Medium.** Mitigated in principle by REQ-030 (fraud-triggered platform facilitation), but the trigger is ambiguous (AMB-004). Acceptable once REQ-030 is made operational.
- **[RISK-EVAL-002] (Relates to `RISK-002`)**: Wrong/mismatched lab report - **Impact: High (clinical safety + record integrity), Likelihood: Medium, escalating without mitigation.** Mitigation (REQ-025) lacks a mechanism ([GAP-004]/[GAP-008]). Critical blocker.
- **[RISK-EVAL-003] (New) [Category: Legal/Regulatory]** (Relates to `REQ-005`, `REQ-023`, `NFR-002`): AI-drafted prescriptions against the pure-facilitator posture, with compliance stakeholder `[Not Yet Elicited]`. **Impact: High, Likelihood: Medium.** Blocking decision.
- **[RISK-EVAL-004] (New) [Category: Commercial]** (Relates to `REQ-002`, `REQ-008`): Single-city dependency - the whole first release stands or falls on Daltonganj partner supply and demand, unmodeled. **Impact: Medium, Likelihood: Medium.**
- **[RISK-EVAL-005] (New) [Category: Data]** (Relates to `REQ-021`, `NFR-004`): Best-effort availability + no backup/DR (GAP-012) against a lifelong longitudinal record. **Impact: High, Likelihood: Low–Medium.** Needs a durability floor (e.g., daily backup) even under best-effort.
- **[RISK-EVAL-006] (New) [Category: Feasibility]** (Relates to `REQ-007`, `NFR-001`): Hindi voice extraction quality vs. near-zero AI cost cap. **Impact: Medium, Likelihood: Medium.** Needs a spike/validation early.

---

## 6. Stakeholder Action Plan & Clarification Questions

### For Founder / Product Owner (primary decision-maker)

1. **Regarding [CFL-002] and [RISK-EVAL-003]:** "The platform's AI would draft prescriptions, yet your posture is 'pure facilitator.' Do you accept the AI as a drafting assistant under the licensed doctor's authority (doctor reviews and approves before issuance), or should AI be limited to structured data capture with the doctor composing the prescription? The first preserves the differentiated UX but requires explicit compliance sign-off and a liability disclaimer; the second is lower-risk but heavier on doctors. Which do you choose?"
2. **Regarding [CFL-003] and [GAP-003]:** "The consult happens off-platform, but the e-prescription is generated on-platform. Who triggers the platform to start the prescription flow after a consult, and how does the platform know the consult happened - doctor-initiated (doctor opens the patient record and starts the prescription), patient-initiated, or a 'consult completed' handshake? This is the seam the entire care loop depends on."
3. **Regarding [CFL-004] and [AMB-005]:** "What is a chronic-care 'follow-up interaction' on the web app if the doctor is off-platform - patient self-logging with push content, asynchronous doctor Q&A on-platform (which would break the off-platform rule), or simply re-booking another off-platform consult?"
4. **Regarding [GAP-001]:** "How should patients be identified and authenticated for a longitudinal health record with per-action consent - phone OTP with a platform account, or a deeper verification? The stronger the identity, the more credible the consent log and the more defensible against RISK-002, but the heavier the onboarding friction and cost."
5. **Regarding [AMB-002]:** "Define the acceptance bar for 'full care loop proven' in Daltonganj - for example, how many completed loops, how many delivered prescriptions, and what failure-rate ceiling qualifies as proven?"
6. **Regarding [CFL-001] and [AMB-004]:** "Three requirements (REQ-027, REQ-029, REQ-030) describe the payment model. Do you want one consolidated settlement requirement with a single rule - cash/UPI primary, platform-facilitated only above a defined fraud-risk/order-value trigger - and what is that trigger?"
7. **Regarding [GAP-006]:** "With no critical-value escalation at launch, what medical-safety posture should the symptom intake have - a visible disclaimer, red-flag routing to emergency services, or a cutoff message for high-severity symptoms?"
8. **Regarding [GAP-010] and [AMB-003]:** "Given near-zero ops cost, how are partner credentials verified - fully automated checks, or automated plus a small manual review step? And who operates the platform's admin/moderation capability that would require?"
9. **Regarding [GAP-005] and [GAP-013]:** "What data-retention and deletion rules apply to the longitudinal record - retention period, patient-triggered deletion, export/portability, and what happens to shared data when a patient revokes consent?"
10. **Regarding [REQ-040] (AMB-007):** "Confirm WhatsApp-first and native-app channels remain post-MVP so we don't over-engineer multi-channel abstractions in the launch architecture."

### For Compliance / Regulatory (future elicitation - `[Not Yet Elicited]`)

1. **Regarding [CFL-002] and [RISK-EVAL-003]:** "Under DPDP Act 2023 and India's telemedicine practice guidelines, does an AI-drafted, doctor-approved e-prescription on an aggregator platform preserve a 'pure facilitator' liability posture? What consent, breach-notification, and data-localization obligations apply to NFR-002?"
2. **Regarding [GAP-011] and [GAP-012]:** "What audit-trail retention period and data-backup/DR minimums are required for a platform handling longitudinal health records, even under a best-effort availability posture?"

### For Supply-side Partners (future elicitation - validate assumptions)

1. **Regarding [DEP-002] and [GAP-007]:** "Can Daltonganj's local chemists commit to time-bounded order acceptance and self-delivery? What supply density is realistic at launch to make REQ-002 provable?"
2. **Regarding [GAP-008] and [REQ-025]:** "Which party should own the order→report linkage - can partner labs accept a booking ID to attach to the upload, or will patients self-upload more often?"
3. **Regarding [REQ-029]/[REQ-030]:** "For small chemists and labs, is cash/UPI at point of service actually the preferred settlement, or do partners expect the platform to handle money?"

### For Patients (future elicitation - validate assumptions)

1. **Regarding [REQ-003]/[REQ-035] and [CFL-004]:** "Would a web-only (PWA) interaction surface with WhatsApp notifications support daily BP/sugar logging habit, or does the chronic-care loop need an on-app Q&A channel to feel like 'care'?"
2. **Regarding [GAP-001]:** "What identity/onboarding friction is acceptable in exchange for a longitudinal health record?"

### For Engineering / Architecture (deferred - confirm feasibility)

1. **Regarding [RISK-EVAL-006] and [AMB-006]:** "Is Hindi voice-to-text at launch quality achievable within a freemium LLM budget? What structured-extraction fallback is acceptable when AI confidence is low?"
2. **Regarding [GAP-012] and [NFR-004]:** "Under best-effort availability, what durability floor (backup frequency, restore target) is acceptable for the longitudinal record?"

---

## 7. Verification Checklist

- ✅ Every `CONFLICT-xxx` in the RGD addressed - `CONFLICT-001` confirmed closed via supersession and carried forward in [CFL-001].
- ✅ Low-confidence items drilled down - sole `[Medium]` item `REQ-040` has [AMB-007]; no `[Low]` items exist (recorded for audit).
- ✅ Critical domain NFRs checked - security/privacy (NFR-002, GAP-013), compliance (CFL-002, GAP-011, GAP-013), performance (NFR-003, AMB-001), disaster recovery (GAP-012), auditability (GAP-011).
- ✅ Every finding traces to RGD IDs.
- ❌ **Resolutions pending stakeholder decisions** - [CFL-002], [CFL-003], [CFL-004], [GAP-001], [GAP-003], [GAP-008] remain unresolved and are carried forward to the PRD gate.
