# Brief - 925 Operator settings UI: API-key field with masked status states

**Ticket:** #925 · **Parent:** #917 (ticket 8 of 10) · **Refreshed:** 2026-11-16
**Reading surface:** ~4K tokens (budget 10K) - within budget

## Scope

Add a password-style API-key field to the AI & LLM operator settings section, gated per selected provider, with masked status states ("configured from environment", "configured from dashboard, set <date>", "missing") read from the effective settings endpoint. Writes go through the existing `writeSetting` path (`ai.api_key`) which encrypts at rest; plaintext never renders. i18n strings (en + hi) for all key-related copy. Vitest covers the three status states, the end-to-end save flow, the server-rejection surface, and the mock-provider hide case.

Acceptance criteria (from ticket):

- Key field renders password-style per provider with the correct status label in all three states (env, dashboard, missing).
- Enter-and-save flow works end to end; status flips to the dashboard form with the set date; plaintext never renders anywhere.
- Non-mock provider without a resolvable key surfaces the server's rejection clearly.
- Vitest covers key masking/status states and the write path; i18n strings added for all key-related copy.

Blocked by: #4 (encrypted key storage), #6 (key write path), #7 (AI & LLM section) - all delivered; this ticket is unblocked.

## Read-list (in order)

1. `apps/frontend/src/components/settings/AiSettingsSection.tsx` - the AI & LLM section component to extend (#924 delivered it).
2. `apps/frontend/src/components/settings/AiSettingsSection.test.tsx` - existing section tests to mirror for the new field.
3. `apps/frontend/src/lib/operator/settings.ts` - `writeSetting`, `fetchEffectiveSettings`, `EffectiveSetting`, `SettingSource` types (~60 lines).
4. `apps/frontend/src/lib/i18n/dictionaries.ts` - `operatorSettings.ai` surface (en ~2732, hi ~5221); add `apiKeyLabel`/`apiKeyPlaceholder`, reuse `keyFromEnv`/`keyFromDashboard`/`keyMissing`.
5. `apps/frontend/src/lib/operator/usePanelRead.ts` - `settingsRead.reload()` semantics used after a write.
6. Backend contract (read-only): `apps/backend/modules/ops/facade.py` `get_effective_settings` returns `ai.api_key` with masked status value; `write_setting` encrypts and validates non-mock providers require a resolvable key (#923).

## Do NOT read

- `docs/archive/` - superseded by the PRD.
- `prototype/` - disposable, gitignored.
- Backend encryption internals (`setting_encryption_service.py`) - the frontend only consumes masked status strings.
- e2e specs.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` (AiSettingsSection suite: 12 passed)
- `npm run typecheck` (tsc --noEmit clean)

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:frontend` (AiSettingsSection suite: 19 passed incl. 7 new)
- `npx tsc --noEmit` (clean)
- `src/lib/i18n/dictionaries.test.ts` bilingual parity (passes)

## Handoff notes

- The API-key field is rendered only when the selected provider requires a key (non-empty `api_key_env` in the catalog); mock providers hide it.
- Status is derived from the effective `ai.api_key` value: `configured from environment` → `keyFromEnv`; `configured from dashboard, set <ts>` → `keyFromDashboard, set <date>`; otherwise → `keyMissing`.
- `providerEntry` for the key-visibility decision uses `current["ai.provider"]` (settings-synced) rather than `drafts["ai.provider"]` (draft-only, unsynced after mount).
- Writes call `writeSetting("ai.api_key", value)` then `settingsRead.reload()` to flip the status badge.
- Plaintext is never rendered: the input is `type="password"` and the written value is asserted absent from the DOM in tests.
- Pre-existing failures in `settings/page.test.tsx` (7) are unrelated to this change (confirmed identical with changes stashed).
