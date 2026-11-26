# Brief - #929 AI settings reskin: status band

**Ticket:** #929 - **Parent:** #928 - **Published:** 2026-11-16
**Reading surface:** the AI section component plus its shared frame/chip primitives and the `operatorSettings.ai` i18n group; nothing else

## Scope

Add the static status band at the top of the AI & LLM settings section: provider, primary-model and ASR-model as accent-chip idiom pills, the auto-derived base URL as a compact read-only mono pill, a pricing-entry count chip, and a last-refresh timestamp - all derived from data the section already fetches (effective settings + provider catalog), no new requests, no live metering/budget data. New decorative ids follow the `settings-*` convention; every existing `data-testid` is preserved verbatim.

- [ ] Status band renders all six summary elements (provider chip, primary-model chip, ASR chip, base-URL mono pill, pricing-entry count chip, last-refresh timestamp) from already-fetched data
- [ ] No new network requests; static config only
- [ ] All existing data-testids preserved verbatim; new ids follow `settings-*`
- [ ] Vitest asserts band content from fixture effective settings

## Blocked by

None - can start immediately.

## Read-list (in order)

1. `apps/frontend/src/components/settings/AiSettingsSection.tsx` - render tree and the data it already fetches
2. `apps/frontend/src/components/settings/SettingsSection.tsx` and `CollapsibleSettingsSection.tsx` - the card frame the band sits in
3. `apps/frontend/src/components/ui/badge.tsx` - the chip idiom to reuse
4. `apps/frontend/src/app/tokens.css` - the token palette (accent teal, surface/hairline, neutrals); any color not a token is a smell
5. `apps/frontend/src/lib/i18n/dictionaries.ts` - the `operatorSettings.ai` group (English around the middle of the file, Hindi near the end)
6. `apps/frontend/src/components/settings/AiSettingsSection.test.tsx` - existing fixtures and mocking pattern

## Do NOT read

- The backend ops module or any API code (no behavior changes)
- Other settings sections beyond the shared frame
- `docs/archive/`, `prototype/`
- E2E specs (ticket 6 owns them)

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend`
- `npm run typecheck`

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:frontend`
- `npm run typecheck`

## Handoff notes

- Presentation only: no state logic, fetch, or write changes of any kind.
- The band's chip anatomy must be identical to the accent chips used on patient/doctor surfaces so the pattern lifts into other settings sections later.
- Link the brief from ticket #929 and apply `ready-for-agent` once done.
