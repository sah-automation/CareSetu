# Brief - 385 Phase 7 fix: intake media must survive Render free redeploys - Supabase Storage private bucket backend (config-switched store)

**Ticket:** #385 · **Parent:** none (independent; ordered after #384) · **Refreshed:** 2026-09-12
**Reading surface:** ~9K tokens (budget 10K) - within budget

## Scope

Intake media (voice clips) currently live on the **ephemeral local filesystem** (`var/intake-media/`) via the encrypted `IntakeMediaStore`. On the Render free web service that disk is wiped on every redeploy, so production voice captures vanish. This ticket swaps the durable backing to a **private Supabase Storage bucket** (config-switched), keeping app-side AES-256-GCM ownership.

### Solution (verbatim from ticket)

- Keep the app-side AES-256-GCM ownership of the bytes (the storage provider only ever sees ciphertext), but swap the durable backing from the ephemeral local disk to a **private Supabase Storage bucket** - the project already runs its Postgres on Supabase free, so no new provider or account is needed.
- A new config switch selects the concrete store: `INTAKE_MEDIA_BACKEND=local|supabase`, defaulting to `local` so dev/CI/tests are unchanged.
- Under `supabase`, votes record as `intake/<patient_id>/<uuid>.enc` in a private bucket, talking to the Supabase Storage REST API over `httpx` (already a dependency) with the service-role key.
- `read(object_key)` downloads the ciphertext and decrypts with the same `INTAKE_MEDIA_KEY` as today - the opaque `intake_media_refs.object_key` contract is unchanged, so no schema or API-route change.

### Implementation decisions (verbatim from ticket)

- **Module and seam:** extend MOD-005 intake's media-store adapter (`modules/intake/adapters/media_store.py`). The single test seam stays the `IntakeMediaStore` port (`async save` / `async read`), the same two operations the facade already calls at `IntakeFacade.upload_intake_media` and `IntakeFacade.get_intake_media`.
- **Async interface:** the store port becomes `async def save(...)` / `async def read(...)`. The local filesystem backend and the new Supabase backend both implement it; the facade's two call sites add `await` (and nothing else). The local backend keeps its current encryption/decryption and path layout so dev behavior is byte-identical.
- **New concrete store:** `SupabaseStorageIntakeMediaStore` uses `httpx.AsyncClient` against `{SUPABASE_URL}/storage/v1/object/{bucket}/{object_key}` with `Authorization: Bearer <service-role-key>`. `save` encrypts locally then `POST`s; `read` `GET`s then decrypts locally. Object keys keep the existing opaque form `intake/<patient_id>/<uuid>.enc`.
- **Error taxonomy:** any non-2xx on `save`/`read` raises `OSError` (read's missing object raises `FileNotFoundError`, an `OSError` subclass), so the facade's existing retry ladder and `(OSError, InvalidTag)` -> `MediaTransferError` wrapping work unchanged on both backends. Decryption-authenticity failure still surfaces as `InvalidTag`.
- **Configuration:** new settings `intake_media_backend` (`INTAKE_MEDIA_BACKEND`, default `"local"`), `supabase_url` (`SUPABASE_URL`), and `supabase_service_role_key` (`SUPABASE_SERVICE_ROLE_KEY`). When backend is `supabase`, both the URL and the service key are required non-blank at settings validation time. AES key ownership is unchanged (`INTAKE_MEDIA_KEY`).
- **Wiring:** `render.yaml` gains `INTAKE_MEDIA_BACKEND: value: supabase` and secret `sync: false` entries for `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`, set in the Render dashboard during provisioning like `DATABASE_URL`. `.env.example` documents the local/supabase quick-switch table.
- **No schema change:** `intake_media_refs.object_key` remains the opaque string; the consumer/pipeline and media routes are untouched, so a later real-ASR leg can still download audio through the same store port.

### Testing decisions (verbatim from ticket)

- **Good-test principle:** assert the store port's observable contract - ciphertext never leaves the app, the same object key round-trips through save/read, correct bucket+path, and the exact error type each backend raises - never provider HTTP plumbing such as which Accept header went out.
- **Module under test:** the media-store adapter (`media_store.py`), via the factory and the two concrete stores.
- **Seam (single, highest):** the `IntakeMediaStore` port - the remote store is exercised against an `httpx.MockTransport` fake network; the facade's existing retry/packaging tests (`test_intake_media_rerecord.py`) are re-run unchanged to prove no behavior fork, only the added `await`.
- **Test cases to add (`tests/unit/test_intake_media_supabase_storage.py`):**
  1. `save` round-trips: returns `intake/<patient_id>/<uuid>.enc`, posts only ciphertext (nonce + GCM output) with the bucket in the path, no plaintext appears in the request body.
  2. `read` of that key returns the original bytes after decryption.
  3. `save` non-2xx (e.g. 401/403/500) raises `OSError`; the facade's retry ladder then wraps into `MediaTransferError` after 3 attempts (reuse the existing facade test harness).
  4. `read` 404 raises `FileNotFoundError`; 5xx raises `OSError`.
  5. `read` of tampered ciphertext raises `InvalidTag` (not `OSError`), and the facade wraps it in `MediaTransferError` unchanged.
  6. `build_media_store` factory: `local` returns the local store, `supabase` returns the remote store, missing URL/service key under `supabase` raises `ValueError` at settings/resolver time.
- **Backend parity check:** the full existing `test_intake_media_rerecord.py` suite stays green against the async port (only the fake store gains `async def`), proving the remote backend did not change facade-level behavior.

### Out of scope (verbatim from ticket)

- Partner credential artifacts (`partner/` prefix, Phase 5) still live on the local filesystem; same risk, separate seam and separate ticket.
- Cloudflare R2 as an alternative backend - not wired; spec standardizes on Supabase.
- Migrating already-recorded clips from staging local disk - no meaningful corpus on staging.
- Real-ASR download plumbing (follow-up in #384) - reads audio through this same store port later.
- Any change to the app-side AES-256-GCM scheme, `INTAKE_MEDIA_KEY`, or bucket visibility (must remain private).

## Read-list (in order)

1. **Ticket #385** (this spec) - the design contract; implementation decisions and testing decisions above are authoritative.
2. `tests/unit/test_intake_media_rerecord.py` - the facade-with-fakes harness (`_facade`, `_engine(connection)`, `_FakeMediaStore` with the sync `save`/`read` port, `_FakeSleep` backoff recorder), the 3-attempt retry ladder assertions, and the `get_intake_media` playback tests incl. `InvalidTag`/`OSError` wrapping. Tells you exactly what must keep passing (only the fake's two methods gain `async def`) and the facade-level assertions to reuse for the new backend's error paths (~3K tokens).
3. `modules/intake/adapters/media_store` - the `IntakeMediaStore` port (`save(*, data, patient_id) -> object_key`, `read(*, object_key) -> bytes`), `build_media_store(root: Path | str, b64_key: str)` factory, `decode_key`, the `PREFIX`/`.enc` opaque-key form `intake/<patient_id>/<uuid>.enc`, the AES-256-GCM nonce(12)+ciphertext payload layout, and the error taxonomy. The concrete remote store must keep this exact two-op seam; the local backend must stay byte-identical when made async (~1.5K tokens).
4. `IntakeFacade.upload_intake_media` and `IntakeFacade.get_intake_media` (`modules/intake/facade`) - the two call sites that gain `await`; the existing retry ladder (`MAX_UPLOAD_ATTEMPTS`, `_upload_backoff_delay`) and `(OSError, InvalidTag) -> MediaTransferError` wrapping that must be unchanged (~1K tokens).
5. `Settings`/`get_settings` in `apps/backend/app/config.py` - the pattern to extend: `intake_media_root`/`intake_media_key` default const + frozen-dataclass field + `__post_init__` validation + env mapping are the direct analog; mirror for `intake_media_backend` / `supabase_url` / `supabase_service_role_key` with the fail-fast required-at-validation rule (~1K tokens).
6. Prior art for injectable remote httpx adapters: `build_openai_compatible_gateway(..., client: httpx.AsyncClient | None = None)` in `modules/intake/adapters/ai_provider_openai_compatible` and the `httpx.MockTransport` client helper in `tests/unit/test_ai_gateway_fallback.py` (`_client(handler)`). Mirror this constructor-injected-client pattern so the Supabase store is exercised against a fake network, never real HTTP (~0.5K tokens).
7. Composition root: `create_app` in `apps/backend/app/main.py`, where `build_media_store` is currently called with `resolved_settings` - the backend-switch wiring goes here (selection by `intake_media_backend`, passing `supabase_url`/`supabase_service_role_key` when remote) (~0.3K tokens).
8. `tests/unit/test_gateway.py` Settings fail-closed assertions - the existing `Settings(...)` validation test shape to follow for pinning the new backend fail-fast rule and the `"local"` default (~0.5K tokens).
9. Docs (read the small sections only): `docs/architecture/internal-modules.md` §MOD-005 (intake audio lives in object storage under the `intake/` prefix, private schema isolation), `docs/adr/0013-voice-first-intake-override.md` §2 (intake capture saved before any AI runs; doctor always review raw audio), `docs/standards/security-phii-standards.md` (uploads in private object-storage prefixes, never a public bucket; at-rest encryption owned by the app) (~1K tokens).

## Do NOT read

- `docs/archive/`, `prototype/` - both authoritative-superseded/gitignored.
- `modules/partner` artifact store internals - same crypto shape, different seam (`partner/` prefix), explicitly out of scope.
- `modules/intake/adapters/ai_gateway.py`, the transcribe/structure adapters, `ai_provider_ext` - the AI pipeline is untouched by this ticket.
- `modules/intake/adapters/routes.py`, schema models, state machines, outbox - no schema/API-route change; the opaque key contract is preserved.
- Integration tests (`tests/integration/`) - no DB/route surface changed; skip them.
- Frontend and `docs/design/ui-blueprint.md` - media-store swap is backend-only.

## Baseline verify (must pass before the first edit)

- `node scripts/py.cjs -m pytest -c apps/backend/pyproject.toml tests/unit/test_intake_media_rerecord.py tests/unit/test_ai_gateway_openai_compatible.py tests/unit/test_gateway.py -q` (verified green 2026-09-12: 112 passed)
- `npm run lint:backend`
- `npm run typecheck:backend`

## Done-verify (acceptance criteria → commands)

- New store suite: `node scripts/py.cjs -m pytest -c apps/backend/pyproject.toml tests/unit/test_intake_media_supabase_storage.py -q`
- Parity prove (no facade behavior fork; only the fake's `save`/`read` become `async def`):
  - `node scripts/py.cjs -m pytest -c apps/backend/pyproject.toml tests/unit/test_intake_media_rerecord.py tests/unit/test_gateway.py -q`
- Full unit + gates: `npm run test:unit:backend` then `npm run lint` then `npm run typecheck`

## Handoff notes

- **Ordering gate:** #384 (voice degrade fix) is still open. #385 is independent but intentionally implemented after #384 to keep the voice-intake surface stable while the pipeline becomes non-blocking. Do not let this block the brief's read-list - build against the current tree, which already contains the #384/ASR legs' unaffected seams.
- **Async port reach:** the store port going async means every fake/consumer of `IntakeMediaStore` adds `await`/`async def`. Grep for `IntakeMediaStore` / `build_media_store` to find every reference - the facade call sites, `app/main.py`, and the `test_intake_media_rerecord.py` `_FakeMediaStore`. No other module imports the store port directly (module isolation rule: facade is the only cross-module seam).
- **Fail-closed precedent:** `Settings.__post_init__` already refuses partial/malformed config (SMS/WhatsApp/AI providers + Langfuse key pairs) - the `supabase` backend's "URL and key both required" rule follows the same shape, and the config tests in `test_gateway.py` pin it.
- **Crypto payload stays identical:** nonce(12) + AESGCM ciphertext; `save` must POST exactly that ciphertext and `read` must decrypt it. No plaintext audio may ever appear in a request body (asserted by test case 1).
- **ADR-0013 safety net:** this is the storage leg of "capture is saved before any AI runs" - the store swap must not introduce any path where a save is acked without durable upload (retry ladder unchanged on the remote backend).
- **Render wiring note:** `render.yaml` secret entries use `sync: false` like `DATABASE_URL`; `INTAKE_MEDIA_BACKEND` is a plain `value:` entry. `.env.example` quick-switch table must document both backends (the intake-media block currently documents only the local root/key).
