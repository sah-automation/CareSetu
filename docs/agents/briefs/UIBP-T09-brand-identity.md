# Brief - T09 Brand & visual identity

**Ticket:** #187 · **Parent:** #178 Wayfinder map: Top-level UI Blueprint · **Refreshed:** 2026-08-21
**Reading surface:** ~2K tokens (budget 10K) - within budget

## Scope

Decision question (verbatim): Brand direction for CareSetu: name treatment/logo direction, palette, typography, tone and trust cues for a Tier-3/4 healthcare audience, imagery guidance. Output records decisions the blueprint's design-system section can reference; no final artwork production.

Resolution must produce: palette (with token names mappable to Tailwind config), type scale + font choices (must include Devanagari support for Hindi), logo direction (concept, not production files), tone-of-voice rules, and trust-cue guidance (credential badges, verification marks). Optionally 2-3 rough visual directions via `/prototype` if the choice is contested.

## Read-list (in order)

1. Map #178 body (Notes) - audience and feel preferences (~0.5K)
2. `docs/prd/project-prd.md` §1 Executive Summary & Vision - what the brand must promise (~1K)
3. `apps/frontend/src/app/globals.css` + `tailwind.config.ts` - currently bare/default; this decision seeds real tokens (~0.2K)

## Do NOT read

- All feature epics, backend code, roadmap, archive docs.

## Baseline verify (must pass before the first edit)

- None - read-only decision session; do not edit code.

## Done-verify (acceptance criteria → commands)

- Resolution comment on #187 with palette/type/tone decisions; ticket closed
- Map #178 Decisions-so-far gains one line linking #187

## Handoff notes

- Audience: Tier-3/4 city patients with moderate digital literacy plus professional doctors/partners - trustworthy and warm, not corporate-sterile, not consumer-playful.
- Devanagari rendering is non-negotiable (`REQ-006`) - font picks must be verified for Hindi glyph quality and weight range.
- Page budget (`NFR-003`) constrains webfont payload - prefer system-font stacks or single-family variable fonts.
