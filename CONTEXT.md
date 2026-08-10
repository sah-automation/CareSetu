# CareSetu — Build-Session Navigation Guide

**Read this file first in every session.** It tells you which docs exist, what to read for the work at hand, and what to deliberately skip.

## Doc inventory

| File                                     | Purpose                                                                                                              | Read when                                                 | ~Tokens  |
| :--------------------------------------- | :------------------------------------------------------------------------------------------------------------------- | :-------------------------------------------------------- | :------- |
| `CONTEXT.md` (this file)                 | Navigation guide — what to read/skip                                                                                 | Always (first)                                            | ~0.5K    |
| `docs/prd/project-prd.md`                | WHAT we build: epics, features (`FEAT-xxx`), NFRs, risks                                                             | Every build; the §4.x section for the features in scope   | ~13K     |
| `docs/architecture/system-context.md`    | External actors (`ACT-xxx`) + third-party integrations (`EXT-001..004`)                                              | When touching integrations, actors, or boundary rules     | ~6K      |
| `docs/architecture/internal-modules.md`  | HOW modules work: per-module specs (`MOD-001..011`), sync matrix §4.1, event registry §4.2, traceability §5          | Every build; specs for the modules you touch              | ~14K     |
| `docs/roadmap/implementation-roadmap.md` | IN WHAT ORDER we build: per-phase specs (`PHASE-0..14`), phased traceability §3                                      | Every build; the section for the current phase            | ~16K     |
| `docs/adr/*`                             | Resolved decisions (ADR-0001: AMB-006 confidence split, 0.70 threshold, forced-review gate)                          | When a decision or `AMB`/`CFL`/`GAP` baseline is in scope | ~1K each |
| `docs/standards/*`                       | Top-level rules per area (coding, api, integrations, errors, security, AI)                                           | The relevant standard before working in its area          | ~2K each |
| `docs/agents/briefs/*`                   | Per-ticket **context packs** (read-list, do-not-read, baseline/done-verify) — the contract for implementing a ticket | The ticket's own brief, before anything else              | ~2K each |

## Build-session protocol

Follow this order and stop when you have what you need:

1. **`CONTEXT.md`** — this guide.
2. **`docs/roadmap/implementation-roadmap.md`** → the section for the current phase (which modules/features it touches, its dependencies and risks).
3. **`docs/architecture/internal-modules.md`** → the spec(s) of the module(s) in scope.
4. **`docs/prd/project-prd.md`** → the `§4.x` epic / feature sections in scope (acceptance criteria, rules, edge cases).
5. **`docs/architecture/system-context.md`** — only if the phase touches external actors/integrations (its §3/§4).
6. **`docs/standards/*`** — the standard(s) relevant to the area you're editing.

Read only the sections you need. If a task stays confined to one module or phase, do not pull in unrelated sections.

## Cross-reference rule

The cross-reference matrices are **embedded in** `docs/architecture/internal-modules.md` (§4.1 sync, §4.2 events, §5 feature↔module↔storage) and `docs/roadmap/implementation-roadmap.md` (§3.1 feature↔module↔phase, §3.2 actor/interface↔phase, §3.3 module↔primary-build-phase). Read those sections whole when you need to trace an edge — they are the single source of truth for how parts connect. Do not invent new event names or module links; register changes there.

## Do NOT read

- **`docs/archive/`** — superseded by `docs/prd/project-prd.md`. Historical elicitation artifacts (`discovery-register.md`, `rgd.md`, `conflict-gap-report.md`) live there for reference only; the PRD is the single source of requirements.
- No other docs carry authoritative content beyond the files listed above.

## Language (glossary)

Vocabulary resolved by the AMB-006 decision (ADR-0001) and the Phase 1 foundation decisions (ADR-0002, ADR-0003). Terms added here are the canonical names — don't drift to synonyms.

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
The ≤ 2% rate of clinically-significant field errors on unflagged pre-summaries, certified over the well-formed subset — the testable core of "never present unverified output as final".
_Avoid_: error budget

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
No cross-schema imports, no cross-schema SQL, no cross-schema foreign keys; the only legal cross-module seams are `facade.py` (sync) and outbox events (async). The dispatcher and migration harness are the sole cross-schema readers, and only of outbox/schema plumbing, never domain tables.
_Avoid_: bounded-context separation (when meaning this CI-enforced rule)

**edge**:
The deployment boundary - the reverse proxy (Caddy/nginx) that terminates TLS at the VM perimeter. Distinct from the in-app gateway.
_Avoid_: gateway

**gateway**:
The in-app FastAPI middleware stack where caller identity is established (JWT-verify, RBAC scope, rate-limit), in front of every route. Distinct from the edge.
_Avoid_: API proxy

**audit event**:
`audit.event` - published by each owning module into its own outbox in the same transaction as the audited change, and consumed by MOD-011 which appends to the audit schema. Never synthesized by the dispatcher.
_Avoid_: audit log entry
