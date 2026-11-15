# Brief - #923 Runtime-editable provider API keys: write path and key-presence validation

**Ticket:** #923 - **Parent:** #917 - **Blocked by:** #922, #921

## Scope

Allow an admin to enter or replace a provider's API key through the settings write path, with key-presence validation. Non-mock providers require a resolvable key (env or dashboard) or the write is rejected. Mock providers require no key. Keys are write-only; reads return masked status only.

## Acceptance criteria

- [ ] Valid key write stores the encrypted value and the effective resolver resolves dashboard key before env key (integration test).
- [ ] Write for a non-mock provider with no resolvable key (neither env nor dashboard) is rejected with a clear error.
- [ ] Mock provider writes require no key.
- [ ] Key values redacted from history/audit; masked status in reads reflects new state (including "set <date>" form).

## Read-list (in order)

1. `apps/backend/modules/ops/facade.py` - `OpsFacade.write_setting`, `get_effective_settings`.
2. `apps/backend/modules/ops/domain/settings.py` - `EDITABLE_AI_KEYS`, `READ_ONLY_SENSITIVE_KEYS`, `ENCRYPTED_SETTING_KEYS`, `EffectiveSettingsResolver`.
3. `apps/backend/modules/ops/domain/setting_encryption_service.py` - `SettingEncryptionService` (encrypt_if_needed, redact_value, get_masked_status_with_resolver).
4. `apps/backend/app/ai_provider_catalog.py` - provider entries and `api_key_env`.
5. `docs/standards/security-phii-standards.md` - secrets sections.

## Do NOT read

- docs/archive/
- prototype/
- frontend code
- pricing table logic

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend`
- `npm run test:integration`
- `npm run lint`
- `npm run typecheck`

## Handoff notes

- `ai.api_key` / `ai.fallback_api_key` become writable (added to `EDITABLE_AI_KEYS`), stay encrypted and masked on read (stay in `ENCRYPTED_SETTING_KEYS`), removed from `READ_ONLY_SENSITIVE_KEYS` so DB values surface and `requires_restart` is False.
- `write_setting` validates key presence for non-mock providers: written value OR env OR existing dashboard value must exist, else `InvalidSettingWriteError`.
- Mock provider (`provider == "mock"` / empty `api_key_env`) writes require no key.
- Env remains the initial/fallback source for every editable key.
