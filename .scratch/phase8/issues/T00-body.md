## Parent

Part of #416

## What to build

Register the MOD-006 domain vocabulary in the project's single glossary - the **"Language (glossary)" section of `CONTEXT.md`** (per `docs/agents/domain.md`: CONTEXT.md is the canonical glossary; terms are never drifted to synonyms). This is a naming-authority ticket: it runs FIRST so every later ticket (domain enums, events, facade, routes, tests) uses canonical names.

The vocabulary is already fully resolved in issue #416's Implementation Decisions - this is transcription, not design. Add a new glossary section **"Consultation orchestration & e-prescription (Phase 8)"** with terms + `_Avoid_` lines, following the existing glossary format:

- **care case** - one per visit, born when its pre-summary is finalized; carries the consult handshake and prescription lineage. _Avoid_: case record, visit ticket
- **case stage** - closed enum `PreSummary | PrescriptionPending | Closed`. _Avoid_: status, workflow state
- **consult complete milestone** - the audited from-to transition that closes the off-platform consult and moves the case to prescription pending; a milestone, never a dwell state. _Avoid_: consult complete state
- **finalized pre-summary** - a pre-summary in the `final` three-state review state; the sole acceptable input to the consult handshake. _Avoid_: confirmed summary
- **e-prescription** - the issued, attributed, immutable prescription artifact. _Avoid_: prescription (when meaning the live working row)
- **prescription source** - closed enum `ai_draft | manual`. _Avoid_: origin
- **draft snapshot** - the immutable AI-produced drafting-assistant artifact stored per attempt; never directly issuable. _Avoid_: AI prescription
- **drafting cap** - max 3 AI draft attempts per case (2 rejections); limits only draft generation. _Avoid_: retry limit
- **revision-freeze approval** - approval freezes exactly the doctor's saved working revision, never the raw draft snapshot. _Avoid_: review approval
- **verification declaration** - the mandatory double-check assertion (`verification_declaration = true`) ticked before approval. _Avoid_: confirmation checkbox
- **edited_yn** - derived flag on issuance comparing the issued revision to the draft snapshot. _Avoid_: modified
- **doctor input** - a voice note or photo submitted as prescribing input (object storage `rx_input/`). _Avoid_: rx attachment
- **close-without-prescription** - the doctor's deliberate terminal close with a reason; a rejected draft never auto-closes. _Avoid_: skip close

Avoid editing anything else in CONTEXT.md (doc-inventory table, build-session protocol) unless the glossary change makes a row stale.

## Acceptance criteria

- [ ] New "Consultation orchestration & e-prescription (Phase 8)" glossary section in CONTEXT.md with all terms + `_Avoid_` lines
- [ ] Terms match exactly the names used in issue #416 (no invented synonyms)
- [ ] No other CONTEXT.md content changed without note
- [ ] `npm run lint` passes (whitespace/prettier - markdown is gated)

## Blocked by

None - can start immediately (parallel with T01 schema).

## Context pack

- **Read-list:** `CONTEXT.md` "Language (glossary)" section (format template), `docs/agents/domain.md` (glossary conventions), issue #416 Implementation Decisions (term definitions), `docs/spec/phase-5-partner-onboarding.md` lines ~158 (precedent for a new glossary section per phase)
- **Do NOT read:** backend code, invention of new vocabulary, ADR files, prototype HTML
- **Baseline verify:** `npm run lint`
- **Done-verify:** `npm run lint` + read-through of the new CONTEXT.md section
- **Brief file:** `docs/agents/briefs/PHASE-8-T00-context-glossary.md`
