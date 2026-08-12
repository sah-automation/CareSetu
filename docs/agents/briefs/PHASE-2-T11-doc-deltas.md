# Brief - PHASE-2 T11 Doc deltas

**Ticket:** #62 · **Parent:** #51 · **Refreshed:** 2026-08-12
**Reading surface:** ~4K tokens (execution budget 120K incl. initial read + tests) - within budget

## Scope

Record the resolved Phase 2 decisions where later phases read them: CONTEXT.md glossary additions, a new ADR-0004 "OTP challenge & brute-force contract", and MOD-001 spec updates in internal-modules.md.

Acceptance criteria:

- [ ] CONTEXT.md glossary adds `identity`, `OTP challenge`, `phone lockout`, `duplicate resolution`, `E.164 phone` with _Avoid_ notes, including the legacy snake_case event-name warning
- [ ] ADR-0004 exists, follows the ADR-0002/0003 format, records the OTP challenge + brute-force contract
- [ ] internal-modules.md MOD-001 §1/§2/§3 reflect the Phase 2 decisions (lockout counters, latest-wins resend, 5-attempt budget, +91 normalization, session TTLs, event list)
- [ ] No em-dashes anywhere (repo rule)

## Read-list (in order)

1. #51 Implementation Decision 11 (doc deltas) + §5 source list (~1K).
2. `CONTEXT.md` glossary format (~1K).
3. `docs/adr/0002` and `0003` - the ADR format to match (~1K).
4. `docs/architecture/internal-modules.md` MOD-001 §3.1 + event registry §4.2 (~1.5K).

## Do NOT read

- `docs/archive/`, `phase0/`, any application code, other modules' specs.

## Baseline verify

- `npm run lint`

## Done-verify

- `npm run lint` (whitespace/em-dash gate)
- Review the three doc files against the acceptance criteria

## Handoff notes

- The event registry §4.2 in internal-modules.md is the single source of truth - update it in the same pass as the MOD-001 spec.
- The `_Avoid_` note for legacy snake_case event names matters: the PRD's legacy telemetry names are superseded by the dot-notation registry.
