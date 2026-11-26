# Brief - 532 Private profile-media storage adapter

**Ticket:** #532 · **Parent:** #529 · **Refreshed:** 2026-09-24
**Reading surface:** ~4.5K tokens (budget 10K) - within budget

## Scope

A new private object-storage surface, `profile-media`, is available to the backend - never public (PII), keyed by role prefix (`patient/<user-id>/`, `doctor/<user-id>/`), owned by a new storage adapter that copies the proven intake-media shape (port + factory + local/supabase backends, AES-256-GCM encryption, service-role writes only), selectable by new configuration (backend, root, key) at the composition root.

This is the infra both the patient profile photo (US-20) and the doctor profile photo (US-26) ride on; no user-facing behavior yet in this ticket. Keys, not blob URLs, are persisted anywhere (ADS: refs only in SQL).

AC:

- [ ] A protocol + `build_*_media_store` factory with local and supabase backends mirrors the intake-media adapter shape, with a `profile-media`-specific port and object key layout (`patient/<id>/...`, `doctor/<id>/...`)
- [ ] Encryption at rest (AES-256-GCM) and service-role-writes-only hold in both backends
- [ ] New settings (backend, root, key) wired at the composition root with `.env.example` entries and validation, following the intake-media config pattern
- [ ] Unit tests cover key layout, local persistence, and the Supabase client contract via an injected fake (prior art: intake media store tests); `npm run test:unit:backend`, `npm run lint`, `npm run typecheck` green

## Read-list (in order)

1. The intake media store adapter in `modules/intake/adapters/media_store.py` - the whole proven shape to copy: the `IntakeMediaStore` port (~0.25K), AES-256-GCM `_encrypt`/`_decrypt` (~0.1K), local backend (~0.6K), supabase backend (~0.9K), `build_media_store` factory + `decode_key` (~0.35K).
2. Config settings in `app/config.py` - the `intake_media_*` fields, `supabase_url`, `supabase_service_role_key`, their `__post_init__` validation, and the env mapping; mirror this block for `profile_media_*` (~0.5K).
3. `.env.example` - the intake-media backend/root/key env documentation to mirror (~0.15K).
4. The composition root in `app/main.py` (`create_app` around the store build) - where the new store is constructed and injected alongside `IntakeFacade` (~0.3K).
5. The intake media store test file(s) under `tests/unit/` - the fake-Supabase-client + local-persistence test shapes to mirror (~1K).
6. `docs/standards/security-phii-standards.md` uploads/object-storage section - the at-rest encryption and access rules the adapter must satisfy (~0.5K).

## Do NOT read

- Frontend code, other modules' internals, `docs/archive/`, the intake module beyond `media_store.py`.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - confirmed green 2026-09-24 (2338 passed).
- `npm run lint` - confirmed green 2026-09-24.
- `npm run typecheck` - mypy strict clean (233 files) confirmed 2026-09-24.

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend` - new profile-media key-layout/local-persistence/supabase-fake tests green.
- `npm run lint`, `npm run typecheck` - clean.

## Handoff notes

- The profile-media port is distinct from the intake port even though the shape is copied: keys are `patient/<id>/...` and `doctor/<id>/...`, never `intake/`/`rx_input/`.
- The intake store key-validates object keys and nonce-prepends plaintext for AES-256-GCM - preserve both; the local backend's ephemeral-dev-key behavior (`<root>/<prefix>/<subject_id>/<uuid>.enc`) is the pattern to keep in tests.
- Only the storage-key ref flows to 530/533/542; nothing in this ticket reaches a profile model or route - refs-only-in-SQL is enforced by the caller tickets, not here.
- No em-dashes anywhere (lint-gated); use simple dashes.
