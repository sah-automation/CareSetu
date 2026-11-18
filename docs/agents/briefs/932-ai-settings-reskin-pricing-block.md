# Brief - #932 AI settings reskin: pricing block

**Ticket:** #932 - **Parent:** #928 - **Published:** 2026-11-16
**Reading surface:** the AI section component's pricing block, its test file's pricing cases, and the `operatorSettings.ai` i18n group

## Scope

Prettify the pricing block without rebuilding it: the raw textarea stays the editor but gains a mono typeface and comfortable width/height; the paise-per-token hint and USD-per-1M preview render as tidy helper chips beneath it. Per-row inline saved/saving/error status works exactly as today, restyled only. Validation errors (missing value, custom model without pricing entry) render inline near the offending field. Validation and the custom-model-needs-price rule are untouched.

- [ ] Pricing textarea mono-styled with comfortable dimensions
- [ ] Pricing hint and USD-per-1M preview render as tidy helper chips beneath the textarea
- [ ] Inline saved/saving/error status per row behaves exactly as today, restyled only
- [ ] Validation errors render inline near the offending field
- [ ] Vitest covers the USD-per-1M preview and the custom-model-needs-price validation

## Blocked by

- #929 - AI settings reskin: status band
- #930 - AI settings reskin: provider and credentials block
- #931 - AI settings reskin: models block grid

## Read-list (in order)

1. `apps/frontend/src/components/settings/AiSettingsSection.tsx` - the pricing textarea, validation, and USD-preview logic (only the pricing portion)
2. `apps/frontend/src/lib/i18n/dictionaries.ts` - `operatorSettings.ai` pricing strings
3. `apps/frontend/src/components/ui/badge.tsx` - the helper-chip idiom
4. `apps/frontend/src/components/settings/AiSettingsSection.test.tsx` - existing pricing cases

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

- The USD preview math and validation rules must not change by a single line of logic.
- Helper chips reuse the badge idiom, not new components.
- Link the brief from ticket #932 and apply `ready-for-agent` once done.
