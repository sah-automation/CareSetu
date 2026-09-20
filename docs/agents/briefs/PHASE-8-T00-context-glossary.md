# Brief - T00 Glossary & CONTEXT.md - MOD-006 Vocabulary

**Ticket:** #425 · **Parent:** #416 · **Refreshed:** 2026-09-14
**Reading surface:** ~3K tokens (budget 10K) - well within budget

## Scope

Register the MOD-006 domain vocabulary in CONTEXT.md "Language (glossary)" as a new "Consultation orchestration & e-prescription (Phase 8)" section with `_Avoid_` lines. Terms: care case, case stage, consult complete milestone, finalized pre-summary, e-prescription, prescription source, draft snapshot, drafting cap, revision-freeze approval, verification declaration, edited_yn, doctor input, close-without-prescription. Do NOT touch the doc-inventory table or build-session protocol unless a row goes stale.

### Acceptance criteria

- [ ] New glossary section in CONTEXT.md with all terms + `_Avoid_` lines
- [ ] Terms match issue #416 exactly (no invented synonyms)
- [ ] No other CONTEXT.md content changed without note
- [ ] `npm run lint` passes

## Read-list (in order)

1. `CONTEXT.md` "Language (glossary)" section (lines ~44-250) - the format template: term with **bold** lead, definition, `_Avoid_:` line, section headers with `###`, per-phase sections (~2K tokens)
2. `docs/agents/domain.md` - glossary conventions: "if the concept isn't in the glossary, either don't use it or flag it for /domain-modeling" (~0.5K)
3. issue #416 Implementation Decisions + User Stories - the authoritative term definitions (~1K tokens)
4. `docs/spec/phase-5-partner-onboarding.md` ~line 158 - precedent for a new per-phase glossary section (~0.2K)

## Do NOT read

- Backend code (this is vocabulary transcription, not implementation)
- ADR files, prototype HTML, tests
- Anything that would tempt inventing new words - the glossary captures spec language, it does not mint terms

## Baseline verify (must pass before the first edit)

- `npm run lint`

## Done-verify (acceptance criteria -> commands)

- `npm run lint` + read the new CONTEXT.md section against issue #416 Implementation Decisions

## Handoff notes

- Precedent: Phase 2, 5, 6 each added a per-phase glossary section the same way (see PHASE-2-T11-doc-deltas, spec/phase-5-partner-onboarding).
- Where a term already exists in the glossary (e.g. "pre-summary", "forced doctor review" from Phase 7) do NOT duplicate it - new terms only.
- Term names are the ones the domain tickets (T02/T03) will use literally: `case stage`, `consult complete milestone`, `draft snapshot`, `revision-freeze approval`, `verification declaration`, `edited_yn`, `close-without-prescription`, `prescription source`. Exact match or the naming lock fails.
