# Brief - T02 Design tokens & Mukta typography

**Ticket:** #193 · **Parent:** #191 PHASE-2.6 · **Refreshed:** 2026-08-22
**Reading surface:** ~5K tokens (budget 10K) - within budget

## Scope

The resolved brand rendered everywhere: token hex migration only - accent moves from the seeded cyan set to true teal (`#0f766e` primary, darker hover, soft tint, border ring) plus a new saffron warm ramp (`#c2410c` / `#ea580c` / soft). Token names unchanged so component code is untouched; `warn` stays reserved for system warnings, `warm` brand-only. Semantic colors and neutrals unchanged; dark mode out of scope but tokens structured for a later dark ramp.

Typography: Mukta self-hosted via next/font google integration, weights 400/500/600/700, latin + devanagari unicode-range subsetting, fallback stack `'Mukta', 'Noto Sans Devanagari', 'Nirmala UI', system-ui, sans-serif`; global body line-height >= 1.625 in both locales (Devanagari matra rule); heading scale per blueprint §1.3.

Also: unify the duplicated palette sources into one CSS-variable source consumed by the Tailwind v3 config (today the palette exists twice), and add a reduced-motion kill switch for skeleton pulse/animations (user story 33).

Acceptance criteria: see #193 body verbatim.

## Read-list (in order)

1. UI blueprint §1 (design system + §1.3 heading scale) - the resolved palette/typography spec (~2K tokens)
2. Prototype foundations `prototype/assets/css/tokens.css` + `base.css` - binding reference values (~1.5K)
3. Current Tailwind v3 config + global stylesheet - where hexes live today (~0.7K)
4. The OTP wizard's CSS-variable block (`.otpProto` in its shared module CSS) - the duplicate source to unify (~0.8K)

## Do NOT read

- Other prototype views beyond the two foundation assets, `docs/archive/`, backend, component code (names unchanged = no need).

## Baseline verify (must pass before the first edit)

Recorded green on 2026-08-22: lint, typecheck, frontend units 72 tests, measure-pages PASSED.

## Done-verify (acceptance criteria → commands)

- Baseline four green; visual spot-check dashboard + login surfaces against prototype foundations
- Grep check: no duplicate hex definitions remain outside the unified source

## Handoff notes

- Token names unchanged is the whole point - if any component references a renamed token, you drifted.
- The wizard's `.otpProto` variables should consume the unified source rather than redefine hexes; its rendered copy must stay byte-stable (smoke asserts it) - colors changing is fine, text is not.
- Reduced-motion rule belongs at the base layer so every future skeleton inherits it.
