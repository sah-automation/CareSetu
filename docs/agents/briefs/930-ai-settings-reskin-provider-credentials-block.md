# Brief - #930 AI settings reskin: provider and credentials block

**Ticket:** #930 - **Parent:** #928 - **Published:** 2026-11-16
**Reading surface:** the AI section component's provider/key block, its test file's key-field cases, and the `operatorSettings.ai` i18n group

## Scope

Restyle the provider & credentials block as the first visually distinct grouped block: provider select at the top, auto-derived base URL as a read-only mono pill beside it, API-key row beneath showing exactly one of three masked states (configured from environment / configured from dashboard / not configured, password input only when missing), shown only when the selected provider requires a key. All state logic unchanged; key material never rendered.

- [ ] Provider select at block top with base-URL mono pill beside it
- [ ] Key row shows the correct masked status in all three states; plaintext never renders
- [ ] Key input hidden for providers that need no key (mock provider)
- [ ] Source badges (Database override / Environment / Default) in a consistent, subtle position on rows
- [ ] Vitest covers the three key-field states

## Blocked by

- #929 - AI settings reskin: status band

## Read-list (in order)

1. `apps/frontend/src/components/settings/AiSettingsSection.tsx` - provider/key rendering and its state logic (read only the provider/credentials portion plus the data types it consumes)
2. `apps/frontend/src/lib/i18n/dictionaries.ts` - `operatorSettings.ai` key-status strings (English + Hindi groups)
3. `apps/frontend/src/components/ui/badge.tsx` - source badges and status chips
4. `apps/frontend/src/components/settings/AiSettingsSection.test.tsx` - existing key-field cases and fixtures

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

- The riskiest regression is testid drift: preserve every existing `data-testid` verbatim.
- No new dropdown/switch primitives; keep the section's established control styling, improved for alignment and spacing.
- Link the brief from ticket #930 and apply `ready-for-agent` once done.
