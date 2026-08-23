# Brief - T10 Cross-cutting UX patterns

**Ticket:** #188 · **Parent:** #178 Wayfinder map: Top-level UI Blueprint · **Refreshed:** 2026-08-21
**Reading surface:** ~4.5K tokens (budget 10K) - within budget

## Scope

Decision question (verbatim): Shared UX conventions across all surfaces: empty/loading/error state patterns, bilingual toggle mechanics (per-user setting vs per-session), low-bandwidth/offline-tolerance patterns, accessibility floor, form validation and error-envelope presentation in the UI.

Resolution must produce: one named pattern per concern (empty/loading/error skeletons, language persistence rule, image/asset budget rules for 4G, the accessibility bar the UI commits to, and how API error envelopes render to users). These conventions bind every surface ticket's output retroactively via the blueprint.

## Read-list (in order)

1. Map #178 body (Notes) - audience constraints (~0.5K)
2. `docs/standards/api-standards.md` - the error envelope shape the UI must render (~2K)
3. `docs/standards/error-handling-observability.md` - error taxonomy + no-PHI-in-logs rules that constrain client-side messaging (~2K)
4. `docs/prd/project-prd.md` §5.2 Error Scenarios table - user-facing fallback messages already promised (~0.5K)

## Do NOT read

- Feature epics, backend module specs beyond the standards above, roadmap, archive docs.

## Baseline verify (must pass before the first edit)

- None - read-only decision session; do not edit code.

## Done-verify (acceptance criteria → commands)

- Resolution comment on #188 with the pattern set; ticket closed
- Map #178 Decisions-so-far gains one line linking #188

## Handoff notes

- `REQ-006`: notification/UI language follows the patient's language setting - decide where that setting lives (profile field vs device) and its default.
- §5.2 promises specific fallback copy (retry prompts, low-confidence warnings) - conventions must accommodate those verbatim messages.
- No PHI in telemetry/logs applies client-side too - error reporting patterns must respect it.
