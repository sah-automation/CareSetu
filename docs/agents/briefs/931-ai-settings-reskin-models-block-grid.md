# Brief - #931 AI settings reskin: models block grid

**Ticket:** #931 - **Parent:** #928 - **Published:** 2026-11-16
**Reading surface:** the AI section component's models block, its test file's filtering cases, and the `operatorSettings.ai` i18n group

## Scope

Restyle the models block as a responsive grid grouping the four selects (primary model, fallback provider, fallback model, ASR model) - multi-column at the standard breakpoint, stacking on small screens. The custom-model option keeps revealing its free-text input directly beneath its select. Every row keeps its source badge and inline save/status slot. Dependent filtering logic is unchanged; only presentation is restyled.

- [ ] Four selects in a tidy multi-column grid at the standard breakpoint; full-width stack on small screens
- [ ] Custom-model selection reveals the free-text input directly beneath its select
- [ ] Every row keeps its source badge and inline save/status slot in consistent positions
- [ ] Vitest covers dependent filtering of model/ASR options after provider change and the custom-model reveal

## Blocked by

- #929 - AI settings reskin: status band
- #930 - AI settings reskin: provider and credentials block

## Read-list (in order)

1. `apps/frontend/src/components/settings/AiSettingsSection.tsx` - the models/select rendering and dependent-filter state (only the models portion)
2. `apps/frontend/src/lib/i18n/dictionaries.ts` - `operatorSettings.ai` model/fallback/ASR strings
3. `apps/frontend/src/components/settings/AiSettingsSection.test.tsx` - existing filtering and custom-model cases

## Do NOT read

- The backend ops module or any API code (no behavior changes)
- `docs/archive/`, `prototype/`
- E2E specs (ticket 6 owns them)

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend`
- `npm run typecheck`

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:frontend`
- `npm run typecheck`

## Handoff notes

- Preserve every existing `data-testid` verbatim; the filtering tests are the guard.
- No new primitives: selects keep the section's established control styling.
- Link the brief from ticket #931 and apply `ready-for-agent` once done.
