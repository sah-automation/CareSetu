# Brief - T11 Assemble ui-blueprint.md and propose next-phase scope

**Ticket:** #189 · **Parent:** #178 Wayfinder map: Top-level UI Blueprint · **Refreshed:** 2026-08-21
**Reading surface:** ~9K tokens (budget 10K) - within budget

## Scope

Task question (verbatim): Nothing left to decide - assemble every resolution into `docs/design/ui-blueprint.md` (per-surface sections, navigation model, design system, cross-cutting patterns) and append a proposed scope sketch for the UI implementation phase (candidate "PHASE-2.6"). Resolved when the doc exists and the map's destination is met.

This is the map's destination artifact. It synthesizes; it does not re-decide. Where resolutions conflict, flag the conflict in the doc and on the ticket instead of silently picking a winner.

## Read-list (in order)

1. Map #178 body - Destination + all Decisions-so-far links (~0.5K)
2. Resolution comments on #179-#188 (fetch each via `gh issue view <n> --comments`) - the ten decisions being assembled (~8K)
3. `C:\Users\Sonu Gupta\.config\opencode\skills\ui-design\SKILL.md` - diagram conventions if wireframe sketches are included (~0.5K)

## Do NOT read

- PRD/architecture docs wholesale - the resolutions already cite them; re-read only a slice when assembling needs an exact rule verbatim.

## Baseline verify (must pass before the first edit)

- `git status` clean enough to branch; all ten blocker tickets #179-#188 CLOSED before starting.

## Done-verify (acceptance criteria → commands)

- `docs/design/ui-blueprint.md` exists on branch `ui-blueprint`, covering: public site, patient app, doctor channel, partner channels, operator console, navigation model, design system (brand + component-library recommendation), cross-cutting patterns, PHASE-2.6 scope sketch
- PR opened to main, linked from #189; ticket closed after human merge approval
- Map #178 Decisions-so-far gains the final line; map's Not-yet-specified fog graduates into the PHASE-2.6 planning note

## Handoff notes

- Doc structure mirrors the five surfaces + shared sections so later per-phase detailed plans can cite stable headings.
- The PHASE-2.6 sketch proposes scope only (homepage, shell rework, split-auth pages, profile-completion skeleton); actual phase ticketing is a separate effort per the map's Out-of-scope section.
- Follow repo coding standards for docs (plain markdown, no em-dashes).
