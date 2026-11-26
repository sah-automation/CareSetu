# Brief - T03 ADR-0013 + Phase 7 doc deltas (event registry, roadmap)

**Ticket:** #347 · **Parent:** #344 · **Refreshed:** 2026-09-08
**Reading surface:** ~5K tokens (budget 10K) - within budget

## Scope

The voice-first design decision and the events contract are recorded so implementations and the plan agree. New decision record ADR-0013 documents the deliberate override of the Phase 0 Hindi-ASR NO-GO (voice default-highlighted primary input, text equal-first-class, deterministic B3 fallback ladder) with UX rationale and the near-term ASR-improvement plan. The whitebox event registry (section 4.2) and roadmap section 2.7 are aligned to the dot-notation event set the code will publish - the registry is the single source of truth and legacy snake_case intake names are dropped. No application code changes.

Acceptance criteria:

- [ ] ADR-0013 exists at docs/adr/ and records the override rationale, the 3-attempt fallback ladder, and the ASR-improvement plan
- [ ] internal-modules.md section 4.2 lists intake.captured, intake.retry_requested, pre_summary.ready, pre_summary.low_confidence, ai_job.completed, ai_job.failed, ai_egress.recorded with producer MOD-005 and correct subscribers
- [ ] No stale snake_case intake event names (intake_started etc.) remain in the registry or roadmap Phase 7 sections

## Read-list (in order)

1. Issue #344 (ADR-0013 decision + event list) - the content to record (~2K)
2. `docs/adr/0001-amb-006-confidence-and-forced-review.md` + one recent ADR (e.g. `0012-directory-entry-unit-per-partner.md`) - decision-record format and honesty mechanics (~1K)
3. `docs/architecture/internal-modules.md` §4.2 event table - current registry to edit (~1K)
4. `docs/roadmap/implementation-roadmap.md` §2.7 Phase 7 section - where stale snake_case names live (~1K)

## Do NOT read

- `docs/archive`
- backend or frontend source code

## Baseline verify (must pass before the first edit)

- `git status` - tree is NOT clean (unrelated untracked briefs + prototype + modified .gitignore are present as of 2026-09-08); your edit must not touch those files and the doc-delta diff should be isolated to the three docs

## Done-verify (acceptance criteria → commands)

- `git diff` shows the three doc criteria landed (ADR-0013 exists; §4.2 has the 7 events; no snake_case names in registry or roadmap Phase 7)

## Handoff notes

- Next ADR number is 0013 (latest existing is 0012; note a numbering collision already exists at 0004 with two files - do not start a new collision).
- No application code changes in this ticket - docs only.
