# CareSetu - Build-Session Navigation Guide

**Read this file first in every session.** It tells you which docs exist, what to read for the work at hand, and what to deliberately skip.

## Doc inventory

| File                                     | Purpose                                                                                                                                                                                       | Read when                                                                                                                   | ~Tokens  |
| :--------------------------------------- | :-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | :-------------------------------------------------------------------------------------------------------------------------- | :------- |
| `CONTEXT.md` (this file)                 | Navigation guide - what to read/skip                                                                                                                                                          | Always (first)                                                                                                              | ~0.5K    |
| `docs/prd/project-prd.md`                | WHAT we build: epics, features (`FEAT-xxx`), NFRs, risks                                                                                                                                      | Every build; the §4.x section for the features in scope                                                                     | ~13K     |
| `docs/architecture/system-context.md`    | External actors (`ACT-xxx`) + third-party integrations (`EXT-001..004`)                                                                                                                       | When touching integrations, actors, or boundary rules                                                                       | ~6K      |
| `docs/architecture/internal-modules.md`  | HOW modules work: per-module specs (`MOD-001..011`), sync matrix §4.1, event registry §4.2, traceability §5                                                                                   | Every build; specs for the modules you touch                                                                                | ~14K     |
| `docs/roadmap/implementation-roadmap.md` | IN WHAT ORDER we build: per-phase specs (`PHASE-0..14` plus delivered chassis inserts `PHASE-2.5`/`PHASE-2.6` in §2.2a/§2.2b), phased traceability §3                                         | Every build; the section for the current phase                                                                              | ~17K     |
| `docs/adr/*`                             | Resolved decisions (ADR-0001: confidence split; ADR-0005: dual JWT storage; **ADR-0007: split-origin deploy + session-transport invariants**; **ADR-0016: partner login method - phone-OTP**) | When a decision or `AMB`/`CFL`/`GAP` baseline is in scope; ADR-0007 before ANY auth/session/CORS/middleware/deploy-env work | ~1K each |
| `docs/design/ui-blueprint.md`            | Top-level UI design for all five surfaces: navigation model, design system, per-surface IA, cross-cutting patterns                                                                            | Any UI/frontend build; the surface sections you touch                                                                       | ~10K     |
| `docs/research/ui-component-library.md`  | Component-library evidence and migration notes behind the blueprint's §1.1 recommendation                                                                                                     | When adopting UI components or touching bundle budget                                                                       | ~2K      |
| `docs/standards/*`                       | Top-level rules per area (coding, api, integrations, errors, security, AI)                                                                                                                    | The relevant standard before working in its area                                                                            | ~2K each |
| `docs/agents/briefs/*`                   | Per-ticket **context packs** (read-list, do-not-read, baseline/done-verify) - the contract for implementing a ticket                                                                          | The ticket's own brief, before anything else                                                                                | ~2K each |

## Build-session protocol

Follow this order and stop when you have what you need:

1. **`CONTEXT.md`** - this guide.
2. **`docs/roadmap/implementation-roadmap.md`** → the section for the current phase (which modules/features it touches, its dependencies and risks).
3. **`docs/architecture/internal-modules.md`** → the spec(s) of the module(s) in scope.
4. **`docs/prd/project-prd.md`** → the `§4.x` epic / feature sections in scope (acceptance criteria, rules, edge cases).
5. **`docs/architecture/system-context.md`** - only if the phase touches external actors/integrations (its §3/§4).
6. **`docs/standards/*`** - the standard(s) relevant to the area you're editing.

Read only the sections you need. If a task stays confined to one module or phase, do not pull in unrelated sections.

**Hard gate:** if the task touches session/auth cookies, CORS, middleware or proxy route guards, `credentials` options, deploy env vars, or Vercel/Render config, read **`docs/adr/0007-split-origin-deployment-session-invariants.md`** before editing. Production is split-origin (Vercel frontend + Render backend) while localhost is same-origin, so designs that pass locally can still fail only when deployed - this has caused incidents #119/#159/#208.

## Cross-reference rule

The cross-reference matrices are **embedded in** `docs/architecture/internal-modules.md` (§4.1 sync, §4.2 events, §5 feature↔module↔storage) and `docs/roadmap/implementation-roadmap.md` (§3.1 feature↔module↔phase, §3.2 actor/interface↔phase, §3.3 module↔primary-build-phase). Read those sections whole when you need to trace an edge - they are the single source of truth for how parts connect. Do not invent new event names or module links; register changes there.

## Do NOT read

- **`docs/archive/`** - superseded by `docs/prd/project-prd.md`. Historical elicitation artifacts (`discovery-register.md`, `rgd.md`, `conflict-gap-report.md`) live there for reference only; the PRD is the single source of requirements.
- No other docs carry authoritative content beyond the files listed above.

## Language (glossary)

Vocabulary resolved by the AMB-006 decision (ADR-0001) and the Phase 1 foundation decisions (ADR-0002, ADR-0003). Terms added here are the canonical names - don't drift to synonyms.

**pre-summary**:
The AI-generated clinical summary draft produced by the `transcribe → structure → pre-summary` pipeline; always a draft for a licensed doctor, never presented as verified.
_Avoid_: AI summary, auto-note

**transcription confidence**:
The measured audio→transcript quality of a clip, scored as WER/CER; a clip is eligible for structuring when its WER ≤ the 0.20 floor.
_Avoid_: ASR score, speech accuracy

**structuring confidence**:
The provider self-reported `structuring_confidence` on the transcript→structured-fields leg; compared against the 0.70 threshold, independent of measured field F1.
_Avoid_: extraction score

**low_confidence flag**:
The quality gate set on a pre-summary when structuring confidence is strictly below 0.70 (or missing); forces doctor review, never a fourth lifecycle state.
_Avoid_: review state, flagged status

**forced doctor review**:
The hard usage gate: a `low_confidence` pre-summary is unusable as `rx_draft`/`consult` input until a timestamped, attributed doctor review is recorded.
_Avoid_: manual review, human-in-the-loop

**dialect cohort**:
A dialect group in the target Hindi spectrum over which WER is scored per-cohort and overall.
_Avoid_: accent class

**well-formed subset**:
The clips whose transcription WER cleared the 0.20 floor; only these are run and scored for structuring.
_Avoid_: good clips, qualifying set

**silent-error bound**:
The ≤ 2% rate of clinically-significant field errors on unflagged pre-summaries, certified over the well-formed subset - the testable core of "never present unverified output as final".
_Avoid_: error budget

### Patient identity & access

**identity**:
The stable, per-phone record that first registration creates and every later login resolves to; one identity per normalized phone, carrying lifecycle status and the lockout counter. The `patient.*` events (`patient.registered`, `patient.verified`, `patient.auth_failed`) are its lifecycle signals.
_Avoid_: account (for the patient's identity), legacy snake_case spellings of the `patient.*` event names (superseded by the dot-notation registry)

**OTP challenge**:
A single-use 6-digit code bound to one phone, hashed at rest and never logged, valid for 5 minutes with a 5-attempt budget; a resend invalidates the pending code (latest-wins).
_Avoid_: verification code (when meaning the OTP itself), SMS code

**phone lockout**:
The temporary, automatic 15-minute block on a phone after 10 consecutive verification failures across challenges; a counter, never identity state, and distinct from the `Suspended` identity status.
_Avoid_: suspension, account ban (lockout is automatic and time-boxed)

**duplicate resolution**:
The rule that re-registering an existing phone resolves to the existing identity instead of creating a second one; the unique index on the normalized phone is the sole arbiter under concurrency.
_Avoid_: dedupe, merge (there is no merge - concurrent writers converge on the winning row)

**E.164 phone**:
The canonical stored form `+91XXXXXXXXXX`, normalized server-side from the 10-digit Indian mobile number; the country code is derived server-side and never trusted from the client.
_Avoid_: mobile number (when meaning the stored canonical form), client-supplied country code

### Record & consent

**record scope**:
The closed enum of record areas a consent grant may name - `consultations | prescriptions | lab_results | metrics | full_record`; `check_consent` matches on (counterparty, scope). Never per-entry, never free-form.
_Avoid_: data category (when meaning a grant's scope), permission level

**standing grant**:
One live consent authorization for one (patient, counterparty, record scope) triple, effective from grant until revoked or superseded by a re-grant. "Per-action" consent means this per-purpose targeting, never a one-shot token.
_Avoid_: per-action token, one-shot consent

**grant lineage**:
The identity of a consent across re-grants - the (patient, counterparty, record scope) triple; referenced to patients as `C-YYYY-NNN`, with versions counting the re-grants inside it.
_Avoid_: consent relationship

**consent version**:
The immutable state of a grant lineage after each grant or re-grant; egress receipts cite lineage id + version exactly as they authorized.
_Avoid_: consent update, consent edit

**revocation**:
The terminal consent transition: stops all future access by the counterparty immediately, durably written before treated inactive, and recorded. Data already disclosed while the grant was live stays outside platform control - deletion requests are operator-mediated (`GAP-005` baseline).
_Avoid_: recall, retroactive revoke (neither happens)

### Partner onboarding & gated activation (Phase 5)

**partner identity**:
The one stable entity per registration that carries the partner lifecycle status (`[Registered] → [Under Verification] → [Active] | [Rejected]`), separate from the display profile and credential metadata. Mirrors patient identity in `MOD-001`.
_Avoid_: partner profile (that is credentials/metadata), partner account (that is the `iam` credential account)

**partner type**:
The closed enum from `doctor | lab | chemist` that fixes which credential types a partner must submit and how verification branches.
_Avoid_: provider kind, role (that is an `iam` scope)

**credential type**:
The closed enum of professional documents a partner submits per partner type - e.g. `medical_registration | lab_license | drug_license` - giving deterministic verification routing, operator-facing labels, and a queryable `partner_credentials` key.
_Avoid_: document type (when meaning the free-form upload), license category

**two-step verification**:
The `AMB-003` resolution: Step 1 is an automated pre-filter (format + duplicate) that auto-rejects obvious bad submissions without queueing; Step 2 is the manual activation gate where every Step-1-pass clears through the operator queue. There is no auto-approve path - no partner activates without human review.
_Avoid_: automated verification, auto-approve (there is none)

**verification round**:
An individual pass through the verification process (first-time or re-verification), each emitting `partner.verification_started` with a round/version in the payload so the audit trail distinguishes rounds.
_Avoid_: verification attempt (that is the Step 1 check), resubmission count

**credential document**:
A sensitive-class upload (a partner's professional identity artifact, e.g. license photo, registration cert) held in the `partner/` object-storage prefix, encrypted at rest, readable only by the owning partner and the operator during review, and logged on every operator view. Not PHI, but access and retention are restricted. Deleted 30 days after permanent rejection/closure.
_Avoid_: credential (that is the structured record), registration proof, supporting file

**grace window**:
The fixed period (7 days, configurable) an `[Active]` partner keeps active while newly submitted credentials are reverified; on lapse without a decision the partner auto-drops to `[Under Verification]`; on verification failure they go `[Rejected]` with `credential.invalidated` firing.
_Avoid_: suspension grace, review buffer

**rejection appeal**:
The rate-limited path for a `[Rejected]` partner: re-submit corrected credentials (a new verification round) or file a one-time appeal that re-enters the operator queue. Guarded to prevent queue spam (max 3 re-submissions before cooldown).
_Avoid_: re-registration (that is a fresh partner identity), complaint

**credential account**:
The `MOD-001` login record a partner gets at registration - created synchronously through the `MOD-002 → MOD-001` facade seam (`create_credential_account`, ADR-0010) in the same transaction as the partner profile, one per partner identity, bound to the normalized phone. Distinct from the partner profile (the `partner` schema row) and from the role grant (async, activation-gated); it is what a returning partner logs into.
_Avoid_: partner account (when meaning the `iam` row - say credential account), login profile

**partner login**:
Phone + SMS one-time code, served on dedicated `POST /v1/auth/partner/*` routes (ADR-0016) so a partner login can never mint a patient session, grant the patient role, or emit a `patient.*` event. Works in every lifecycle state except `Suspended`; the demo code read-back matches the patient wizard. Supersedes the blueprint's earlier "email + password for all staff roles / No OTP for staff".
_Avoid_: staff login (that phrase bundles partner and operator login together), email/password login

**pre-activation restriction**:
The rule that no unactivated partner reaches patient-facing pages. It is enforced by which routes the partner self-service surface exposes per state (status, rejection reason, and appeal reachable in every state except suspended; credential submission gated; consultation fee only when active; suspended is a contact-support-only surface) - never by a separate, reduced kind of login.
_Avoid_: restricted login kind, limited-scope login (there is one partner login for every state)

**operator login**:
Phone + authenticator-app (TOTP), MFA-bound, for the trusted operator group only; the operator entry stays hidden from the partner-facing login page and is untouched by partner login. The platform distinguishes phone-OTP (patient and partner) from operator-TOTP (operators).
_Avoid_: staff login (when meaning a shared partner+operator entry), password login

**operator**:
A member of the trusted closed group that runs the verification queue; bootstrapped at deploy and grown by operator-invites-operator, never self-registering, and MFA-bound at login.
_Avoid_: admin, moderator (when meaning the operator console role)

**operator decision**:
An individual, attributed approve/reject action on a verification round; reason is required on reject, every view of a partner's credentials is itself audited (`partner.credential_reviewed`), and bulk actions are forbidden in Phase 5 so every decision maps to an actor.
_Avoid_: moderation action, verdict

**egress log**:
The consent-schema ledger of successful, consent-authorized PHI disclosures - what left, when, to whom, under which consent id + version; the source of a record entry's "who has seen this" trail.
_Avoid_: access log (that is the record access history), audit log (that is the Phase 4 engine)

**record access history**:
The health-schema ledger of every read attempt on a record - owner reads, partner reads, denied attempts; feeds the patient's trust view (`FEAT-003`, Phase 4).
_Avoid_: audit trail

### Provider directory & credential validity (Phase 6)

**provider**:
Not a domain term. The patient-facing display word for an `[Active]` partner - legal in UI copy and the public profile route, never in schema, events, model, or lifecycle language. A provider stops existing the moment its partner leaves `[Active]`.
_Avoid_: using "provider" where the entity/status/lifecycle is meant - say partner

**directory entry**:
The single read-side row per `[Active]` partner that makes them discoverable in search: one entry per partner identity, one geo point (the practice location), the partner type, specialty (doctors only), and the verified indicator. One partner = one entry; multiple practice locations are a future extension, never a Phase 6 shape.
_Avoid_: provider record, listing

**specialty**:
The label from a closed pick-list (doctors only) of the kind of care an `[Active]` doctor offers - e.g. `General Physician | Pediatrician | Gynecologist | Dentist`. Labs and chemists carry no specialty; the field is never free-form. Homepage chips pre-seed the search filter over it.
_Avoid_: consultation type (that PRD phrase was dropped - it is not a field), expertise

**verified**:
The derived indicator on a directory entry: true iff the partner is `[Active]` AND every required credential is unexpired and unrevoked. Never stored - computed from activation state + credential dates, always agreeing with search visibility: if the tick is gone, the card is gone.
_Avoid_: verification badge (when meaning a stored flag), approved

**credential expiry**:
One of the two `credential.invalidated` triggers: the credential's recorded date passes without renewal. Detection is lazy-on-read (an expired partner never appears, even mid-day) plus a daily sweep that records the official close-out; deliberately no background scanner.
_Avoid_: license expiry in model language (fine in UI copy), auto-deactivation (that implies a scanner)

**credential revocation**:
The other `credential.invalidated` trigger: the credential is taken away by authority or operator decision. Same directory effect as expiry (hidden instantly, tick removed) but the reason is recorded on the event, and the partner keeps the renewal path - no dead-end state is invented.
_Avoid_: suspension

**wider-area fallback**:
The `FEAT-004` no-results shape: when no directory entry matches the patient's filters within the Daltonganj peri-urban scope, relax only the location constraint (keep type and specialty filters), show nearest-first, and label the results "outside your area". The patient is never silently served results that dropped a filter.
_Avoid_: fuzzy match, relaxed filters

### Consultation orchestration & e-prescription (Phase 8)

**care case**:
The per-visit work record in `MOD-006` (the `care` schema), born the moment its pre-summary is finalized, one per visit, carrying the patient, the attending doctor, and the prescription lineage.
_Avoid_: case (bare), visit record (the visit is the off-platform consult that precedes the case), consultation (that is the off-platform event)

**case stage**:
The closed enum dwell state of a care case: `PreSummary → PrescriptionPending → Closed`. `ConsultComplete` is not a stage - it is the milestone on the `PreSummary → PrescriptionPending` transition. A rejected draft never changes the case stage; `Closed` comes only from the doctor's deliberate close-without-prescription.
_Avoid_: case status (the column is `stage`, and status implies free transitions), lifecycle phase

**consult complete milestone**:
The audited marker recorded on the `PreSummary → PrescriptionPending` transition when the doctor closes the off-platform consult on-platform in one action - a milestone on the transition, never a dwell state. It fires `case.consult_complete` and the patient's single notification, then the case enters prescription pending.
_Avoid_: consult complete state, consult-closed flag

**finalized pre-summary**:
The Phase-7 pre-summary in its terminal `final` state - the only summary the handshake gate `get_finalized_pre_summary` ever returns. `mark_consult_complete` is blocked while none exists, so a prescription-stage case can never arise from an unreviewed summary.
_Avoid_: completed summary, reviewed summary (that is the intermediate `reviewed` state, not the gate's `final` state)

**e-prescription**:
The issued, immutable prescription a doctor approves and the patient's record stores: the frozen approved revision, timestamped and attributed to the issuing doctor, with no supersede or void path - corrections require a fresh visit. `get_approved_prescription` serves only these.
_Avoid_: digital prescription, electronic prescription, Rx (in model language; fine in UI copy)

**prescription source**:
The closed enum on a prescription recording where its revision came from: `ai_draft` (from the drafting assistant's immutable draft snapshot) or `manual` (the doctor authored `rx_items` directly). Keeps the audit trail honest about AI involvement.
_Avoid_: origin, provenance

**draft snapshot**:
The immutable AI-draft artifact captured when `request_rx_draft` produces a draft - the frozen baseline against which `edited_yn` is derived on approval. Editing never touches it; the working revision (the current `Draft`/`DoctorReviewed` row and its `rx_items`) is the only thing that changes.
_Avoid_: AI output, stored draft

**drafting cap**:
The guard that a new AI draft is only generated while the care case has fewer than 2 rejected drafts - so at most two AI drafts per care case (`MAX_REJECTED_DRAFTS = 2`, `can_create_draft(rejected_count) = rejected_count < 2`); a rejected draft never auto-closes the case. The cap limits only AI draft generation; manual authoring, edit-and-approve, and close-without-prescription stay open regardless, so an AI outage never strands a patient's visit.
_Avoid_: retry limit, draft budget

**revision-freeze approval**:
The core issuance guarantee: approval saves and freezes exactly the doctor's working revision (the current `Draft`/`DoctorReviewed` row and its `rx_items`), sets `issued_at` and `attributed_doctor`, and derives `edited_yn` against the immutable draft snapshot. If the revision save fails the approval is blocked - the raw AI draft is never approvable, so a lost edit can never mean a wrong prescription issued.
_Avoid_: one-click approve, approve-draft

**verification declaration**:
The mandatory double-check: `approve_prescription` accepts only a `verification_declaration = true`, stored on `care_rx_approvals` with `declared_at`. A declaration-less approval is rejected, so no prescription is issued without the doctor's recorded, double-checked review.
_Avoid_: consent, agree-checkbox

**edited_yn**:
The derived flag on an approval computed by comparing the frozen revision against the immutable draft snapshot - `edited` tells an auditor whether the issued prescription differs from the AI draft. Never set by hand or from client input.
_Avoid_: modified flag, changed flag

**doctor input**:
A voice note or photo the doctor submits as prescribing input for the AI drafting assistant, stored as a sensitive-class object in the `rx_input/` storage prefix. Any use of the patient's record history to shape an AI draft goes through consent-gated reads (`check_consent`), fail-closed.
_Avoid_: media upload, attachment

**close-without-prescription**:
The doctor's deliberate terminal action that moves a care case to `Closed` with no prescription - recorded with a close reason and leaving the pending list. A rejected draft never auto-closes the case; only this explicit action closes a visit when no medicine is needed.
_Avoid_: close case, end-visit-without-prescription

### Event bus & module seams

**outbox**:
A per-module database table written in the same transaction as a state change; the dispatcher claims and fans out its rows. Rows are deleted after successful fan-out to all subscribers - the subscriber's ledger, not the outbox, records delivery.
_Avoid_: event queue

**dispatcher**:
The async worker loop that polls each module's outbox, durably claims pending rows as `inflight`, and fans them out to in-process subscribers. Pure transport - it never authors events and never touches domain tables.
_Avoid_: event bus process

**event bus**:
The informal name for the async seam; there is no broker. It is dispatcher fan-out over per-module outboxes with at-least-once delivery and subscriber-side dedupe.
_Avoid_: message broker

**idempotent subscriber**:
A module that records `event_id` in its own `consumed_events` ledger before applying effects, so that replay of a delivered event is a no-op.
_Avoid_: replay-safe handler

**round-trip**:
The end-to-end proof of the async seam: publish → dispatcher claim → fan-out → subscriber ledger → replay the same `event_id` → exactly one ledger row. The Phase 1 definition-of-done for the outbox/dispatcher contract.
_Avoid_: outbox test (when meaning the seam proof)

**module isolation rule**:
No cross-schema imports, no cross-schema SQL, no cross-schema foreign keys; the only legal cross-module seams are `facade.py` (sync) and outbox events (async). The dispatcher and migration harness are the sole cross-schema readers, and only of outbox/schema plumbing, never domain tables. The worker (PHASE-1 T4, #30) is the composition root that runs the dispatcher; its only module import is each module's `adapters.register_handlers` at boot.
_Avoid_: bounded-context separation (when meaning this CI-enforced rule)

**edge**:
The deployment boundary - the reverse proxy (Caddy/nginx) that terminates TLS at the VM perimeter. Distinct from the in-app gateway. (The current Vercel+Render demo runs without this edge - see split-origin deployment; the edge arrives with the same-origin VM path.)
_Avoid_: gateway

**gateway**:
The in-app FastAPI middleware stack where caller identity is established (JWT-verify, RBAC scope, rate-limit), in front of every route. Distinct from the edge.
_Avoid_: API proxy

**audit event**:
`audit.event` - published by each owning module into its own outbox in the same transaction as the audited change, and consumed by MOD-011 which appends to the audit schema. Never synthesized by the dispatcher.

### Split-origin deployment (ADR-0007)

**split-origin deployment**:
The production/demo topology: Vercel serves the frontend and Render serves the backend as two different sites, so browsers apply cross-site cookie rules between them; localhost dev is same-origin and masks every one of those rules. Session-transport changes are reasoned against this topology first (`ADR-0007`) and verified by live gates, never by local runs alone.
_Avoid_: multi-domain setup, separated hosting (when meaning this specific Vercel+Render topology)

**presence-hint cookie**:
`caresetu_authed=1` - a secret-free, first-party cookie written/cleared by the frontend's `saveSession()`/`clearSession()` and the ONLY cookie the edge guard (`src/proxy.ts`) reads. Attributes are deliberate: `SameSite=Lax`, `Secure` on https, fixed 30-day window (not the JWT TTL). The backend's `caresetu_session` httpOnly cookie never reaches the frontend origin under split hosting.
_Avoid_: session cookie (that name belongs to the backend's httpOnly JWT cookie), auth cookie, JWT cookie (when meaning the hint)
_Avoid_: audit log entry
