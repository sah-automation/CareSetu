# CareSetu — Requirement Discovery Register

**Status:** Complete
**Register version:** v0.4
**Session source:** Founder (single voice)
**Date:** 2026-08-07
**Session type:** Product Requirement Discovery (interview)
**Handoff:** → `to-rgd` → `docs/archive/requirements/rgd.md`

---

## 1. Session metadata

- **Register opened:** v0.1 — `REQ-001` through `REQ-008`
- **Phases completed:** Phase 1 (high), Phase 2 (medium), Phase 3 (low)
- **Context drift summaries confirmed:** v0.2 (Phase 1), v0.3 (Phase 2), v0.4 (Phase 3 + close)
- **Product context (as stated):** End-to-end, zero-inventory aggregator marketplace connecting patients with doctors, local diagnostic labs, and retail pharmacies; digitizes the complete care loop from symptom discovery to consultation, diagnostics, e-prescription, and hyper-local medicine delivery. Primary differentiator: continuous, AI-assisted chronic care loop for Tier 3/4 Indian cities. $0 monetization initially (portfolio / open-architecture project).

### Information categories

`[FACT]` verified · `[ASSUMPTION]` unverified · `[IDEA]` conceptual · `[FUTURE]` post-MVP

### Elicitation confidence

`[Elicitation Confidence: High]` explicit and unambiguous · `[Medium]` broad preference · `[Low]` vague or ambiguous

---

## 2. Active functional requirements (REQ-xxx)

| ID      | Statement                                                                                                                                                                                                                       | Info   | MoSCoW     | Confidence | Source  | Created |
| ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------ | ---------- | ---------- | ------- | ------- |
| REQ-001 | Genuinely 4-sided marketplace (patient, doctor, lab, pharmacy) with a patient-centric experience as the UX center.                                                                                                              | IDEA   | Must Have  | High       | Founder | v0.1    |
| REQ-002 | First release success = full care loop proven end-to-end in one city (symptom intake → consult → diagnostics → e-prescription → delivery).                                                                                      | IDEA   | Must Have  | High       | Founder | v0.1    |
| REQ-003 | Primary patient access channel is web-based (mobile web/PWA, no install, works over 4G). Stated "for now" — future channels deferred (see REQ-040).                                                                             | IDEA   | Must Have  | High       | Founder | v0.1    |
| REQ-004 | Consultation model: AI-generated asynchronous clinical pre-summary from structured symptom intake; the actual doctor-patient consult happens off-platform.                                                                      | IDEA   | Must Have  | High       | Founder | v0.1    |
| REQ-005 | Compliance posture: pure facilitator. Platform verifies and displays partner credentials; regulated acts (consult, e-prescription, dispensing/delivery, lab testing) stay with licensed partners.                               | IDEA   | Must Have  | High       | Founder | v0.1    |
| REQ-006 | Patient-facing experience supports English + Hindi at launch.                                                                                                                                                                   | IDEA   | Must Have  | High       | Founder | v0.1    |
| REQ-007 | Symptom intake accepts both voice and text; AI structures unstructured English/Hindi input into the clinical pre-summary. (Related: REQ-004, REQ-006)                                                                           | IDEA   | Must Have  | High       | Founder | v0.1    |
| REQ-008 | Launch beachhead: Daltonganj, Jharkhand, covering the city and surrounding/peri-urban areas.                                                                                                                                    | IDEA   | Must Have  | High       | Founder | v0.1    |
| REQ-010 | Zero platform inventory; every product/service fulfilled by partner doctors, labs, chemists.                                                                                                                                    | IDEA   | Must Have  | High       | Founder | v0.1    |
| REQ-011 | Open onboarding for independent local doctors, registered pathology labs (incl. franchised pickup points), and local retail chemists, to minimize operational overhead.                                                         | IDEA   | Must Have  | High       | Founder | v0.1    |
| REQ-012 | Diagnostics: patient chooses home sample pickup or a partner lab / pickup point.                                                                                                                                                | IDEA   | Must Have  | High       | Founder | v0.1    |
| REQ-013 | E-prescription generated on-platform by the doctor (flow per REQ-023).                                                                                                                                                          | IDEA   | Must Have  | High       | Founder | v0.1    |
| REQ-014 | Hyper-local medicine delivery fulfilled by local retail chemists.                                                                                                                                                               | IDEA   | Must Have  | High       | Founder | v0.1    |
| REQ-015 | Core differentiator: shift from transactional "booking directory" to a continuous, AI-assisted chronic care loop.                                                                                                               | IDEA   | Must Have  | High       | Founder | v0.1    |
| REQ-020 | $0 monetization initially (portfolio / open-architecture project).                                                                                                                                                              | IDEA   | Must Have  | High       | Founder | v0.1    |
| REQ-021 | Patient data: central longitudinal health record per patient on-platform; patient consents per action (record access, sharing with doctor/lab/pharmacy).                                                                        | IDEA   | Must Have  | High       | Founder | v0.1    |
| REQ-022 | Doctor pool: general physicians / GPs plus local specialists, specialists onboarded as available.                                                                                                                               | IDEA   | Must Have  | High       | Founder | v0.1    |
| REQ-023 | Post-consult e-prescription: doctor submits a voice note or photo; AI drafts the prescription; doctor reviews and approves before issuance. (Closes ISSUE-001)                                                                  | IDEA   | Must Have  | High       | Founder | v0.1    |
| REQ-024 | Diagnostics pickup: hybrid — on-platform booking where a partner lab / pickup point is available; direct patient-to-lab arrangement as fallback.                                                                                | IDEA   | Must Have  | High       | Founder | v0.1    |
| REQ-025 | Lab report return: lab or patient uploads (whoever has it first), filed into the patient's central record. Must include protection against wrong/mismatched report upload.                                                      | IDEA   | Must Have  | High       | Founder | v0.1    |
| REQ-026 | Lab-report baseline parsing deferred to a later phase; launch scope = report filing only. (Supersedes REQ-017)                                                                                                                  | IDEA   | Deferred   | High       | Founder | v0.1    |
| REQ-027 | Medicine fulfillment: approved e-prescription routed to patient's chosen / nearest partner chemist; chemist prepares and delivers via own rider; payment platform-facilitated or cash/UPI on delivery.                          | IDEA   | Must Have  | High       | Founder | v0.1    |
| REQ-028 | Partner onboarding: gated — credentials verified (manual or automated) before the partner goes live. Registration remains open (REQ-011); activation gated. (Closes ISSUE-002)                                                  | IDEA   | Must Have  | High       | Founder | v0.1    |
| REQ-029 | Settlement model: cash/UPI at point of service is primary; platform-facilitated payments handled on a case-by-case basis.                                                                                                       | IDEA   | Must Have  | High       | Founder | v0.1    |
| REQ-030 | Payments (revised): direct/cash (cash/UPI) is primary; platform-facilitated payment preferred only where fraud risk between the two parties is higher. (Supersedes REQ-009; resolves CONFLICT-001)                              | IDEA   | Must Have  | High       | Founder | v0.1    |
| REQ-031 | Out-of-stock handling: patient is notified and chooses — accept partial fulfillment or cancel.                                                                                                                                  | IDEA   | Must Have  | High       | Founder | v0.1    |
| REQ-032 | Cancellations: policy inherits the relevant partner's (doctor/lab/chemist) policy, shown clearly to the patient at booking time; platform assumes no responsibility for cancellation/refund disputes.                           | IDEA   | Must Have  | High       | Founder | v0.1    |
| REQ-033 | Critical lab values: no automated escalation at launch; reports are filed, interpretation left to patient/doctor.                                                                                                               | IDEA   | Must Have  | High       | Founder | v0.1    |
| REQ-035 | Chronic care loop (launch scope): daily BP/sugar metric logging and follow-up interactions happen on the web app; WhatsApp sends notifications only (dosage reminders, 30/90-day re-test nudges). (Supersedes REQ-034, REQ-018) | IDEA   | Must Have  | High       | Founder | v0.1    |
| REQ-036 | Refunds: the partner refunds the patient directly; the platform does not hold or process refunds. (Closes ISSUE-003)                                                                                                            | IDEA   | Must Have  | High       | Founder | v0.1    |
| REQ-037 | Delivery/pickup failure: patient chooses either to arrange a retry off-platform (direct with partner) or return to the platform for retry/reroute; platform supports both paths.                                                | IDEA   | Must Have  | High       | Founder | v0.1    |
| REQ-038 | ABHA integration: future goal, important (health-record portability via ABHA), post-launch. (Supersedes REQ-019)                                                                                                                | FUTURE | Could Have | High       | Founder | v0.1    |
| REQ-039 | Future monetization: commercial path likely after launch (commission / subscription / freemium); model deferred and unspecified.                                                                                                | FUTURE | Could Have | High       | Founder | v0.1    |
| REQ-040 | Patient access channels beyond web (e.g., native app, WhatsApp-first) as future possibilities.                                                                                                                                  | FUTURE | Could Have | Medium     | Founder | v0.1    |

---

## 3. Non-functional requirements (NFR-xxx)

| ID      | Statement                                                                                                                                                                                                   | Info       | MoSCoW      | Confidence | Source  | Created |
| ------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------- | ----------- | ---------- | ------- | ------- |
| NFR-001 | Near-zero developer + operational hosting cost during development (open-source frameworks, serverless/lightweight backend, freemium AI/LLM tiers). Specific stack = architecture, deferred to later stages. | ASSUMPTION | Must Have   | High       | Founder | v0.1    |
| NFR-002 | Health-data privacy/security baseline: encryption at rest + in transit, role-based access, consent logging, patient access to own record (DPDP baseline).                                                   | ASSUMPTION | Must Have   | High       | Founder | v0.1    |
| NFR-003 | Connectivity/performance: standard web performance assuming reasonable 4G; no special low-bandwidth optimization at launch.                                                                                 | ASSUMPTION | Should Have | High       | Founder | v0.1    |
| NFR-004 | Availability: best-effort (portfolio), no SLA, occasional downtime acceptable.                                                                                                                              | ASSUMPTION | Must Have   | High       | Founder | v0.1    |

---

## 4. Perceived risks (RISK-xxx)

| ID       | Statement                                                                                                                         | Category                         | Related | Status | Source  | Created |
| -------- | --------------------------------------------------------------------------------------------------------------------------------- | -------------------------------- | ------- | ------ | ------- | ------- |
| RISK-001 | Payment fraud between patient and partner — stated motivation for preferring platform-facilitated payment in select transactions. | Financial                        | REQ-030 | Open   | Founder | v0.1    |
| RISK-002 | Wrong/mismatched lab report attached to the wrong patient.                                                                        | Data integrity / clinical safety | REQ-025 | Open   | Founder | v0.1    |

---

## 5. Open issues / deferred decisions / action items (ISSUE-xxx)

| ID        | Statement                                                                                                                    | Status | Source  | Created |
| --------- | ---------------------------------------------------------------------------------------------------------------------------- | ------ | ------- | ------- |
| ISSUE-004 | Geographic expansion intent beyond Daltonganj: not decided (replicate Tier 3/4 city-by-city vs move up-tier vs single-city). | Open   | Founder | v0.1    |

_(ISSUE-001 → resolved by REQ-023; ISSUE-002 → resolved by REQ-028; ISSUE-003 → resolved by REQ-036.)_

---

## 6. Conflicts register

| ID           | Statements                                                                                                                                                           | Status   | Resolution                                                                                                                    | Source  | Created |
| ------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- | ----------------------------------------------------------------------------------------------------------------------------- | ------- | ------- |
| CONFLICT-001 | REQ-009 ("prioritize platform-facilitated" payments) vs REQ-029 ("cash/UPI at point of service primary") — literal inconsistency over which payment mode is primary. | Resolved | Reconciled in-session: REQ-009 superseded → REQ-030 (direct/cash primary; platform-facilitated only where fraud risk higher). | Founder | v0.1    |

---

## 7. Superseded requirements log

| ID      | Original statement                                                                                 | Replaced by | Reason                                                                                                       | Superseded at |
| ------- | -------------------------------------------------------------------------------------------------- | ----------- | ------------------------------------------------------------------------------------------------------------ | ------------- |
| REQ-009 | Hybrid payments; prioritize platform-facilitated (fraud protection), direct/cash fallback.         | REQ-030     | Founder revised payment priority in-session.                                                                 | v0.3          |
| REQ-016 | Computer-vision extraction of test metrics / medicine names from handwritten or PDF prescriptions. | REQ-023     | Subsumed: covered by doctor-photo → AI-draft flow; no separate patient-supplied prescription flow at launch. | v0.4          |
| REQ-017 | Lab-report parsing against past baselines (HbA1c, thyroid, lipid) to flag critical anomalies.      | REQ-026     | Deferred to later phase; launch = report filing only.                                                        | v0.2          |
| REQ-018 | WhatsApp AI follow-ups: dosage reminders, daily metric logging, 30/90-day re-test scheduling.      | REQ-035     | Channel clarified: web is interaction surface, WhatsApp notifications only.                                  | v0.3          |
| REQ-019 | Integration with ABHA / government-private infrastructure ("can integrate").                       | REQ-038     | Clarified as future goal, important, post-launch.                                                            | v0.4          |
| REQ-034 | Chronic care loop launch scope: WhatsApp AI follow-ups.                                            | REQ-035     | Channel clarified in-session.                                                                                | v0.3          |

---

## 8. Elicitation coverage notes

- **Complete:** Phases 1–3 captured. Latest context drift summary (v0.4) explicitly confirmed by the user before closing.
- **[Not Yet Elicited] — future sources:** all captures are tagged `Source: Founder`. No other stakeholder source has been interviewed. Candidate future elicitation sessions:
  - **Supply-side partners** (doctors, labs, chemists) — validate onboarding (REQ-028), fulfillment (REQ-024/027/031/037), and settlement (REQ-029/030/036) assumptions they carry.
  - **Patients** — validate channel model (REQ-003 web-first, REQ-035 WhatsApp-notify), language (REQ-006), and consent UX (REQ-021).
  - **Compliance / regulatory** — validate pure-facilitator posture (REQ-005) and DPDP baseline (NFR-002).
- Items tagged `[ASSUMPTION]` (NFR-001…004) are the most likely to be revised under those future sources.
