# Brief - 555 Deploy config: declare the profile-media backing and both media encryption keys

**Ticket:** #555 · **Parent:** #553 · **Refreshed:** 2026-09-27
**Reading surface:** ~3K tokens (budget 10K) - within budget

## Scope

A photo uploaded on the deployed service **survives a redeploy** and is **still readable after a restart**. Two independent gaps: the profile-media store's backend selection defaults to local disk instead of the durable private bucket (which already exists, is private, and has service-role write access per ADR-0020 - only the configuration was missing); and neither media store's encryption key is set, so both derive an **ephemeral per-process** AES key, every restart generates a new one, and every previously stored ciphertext becomes permanently undecryptable - silently, with the profile row still claiming a photo exists.

The key is the load-bearing part. Declaring the secret is the deliverable; generating and pasting the value is an **operator action** - the agent never handles it, and nothing secret is committed.

## Read-list (in order)

1. **The deploy manifest** (`render.yaml` at repo root, single service, `envVars:` block) - read the existing `INTAKE_MEDIA_BACKEND` entry and the `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` pair directly beneath it, including the explanatory comment above them. That entry is the shape to mirror. Then read two more `sync: false` secrets of a different kind (`CORS_ALLOWED_ORIGINS`, `IAM_MFA_SECRET_KEY`) to see the range of shapes, and `GATEWAY_JWT_SIGNING_KEY` which uses `generateValue: true` instead - so you know which shape applies. Confirm no `PROFILE_MEDIA_*` entry exists yet. (~1K tokens)

2. **The example env file** (`.env.example`) - read the intake-media block (including its quick-switch table of local-disk vs Supabase rows) and the profile-media block below it. The profile block's commented vars are what you uncomment. Note the profile block also carries retry/circuit-breaker tuning vars and two vars referenced only from tests - leave those alone. (~450 tokens)

3. **The gateway/config test's env-documentation assertions** - the last two tests in `tests/unit/test_gateway.py`, which assert env-var _names_ are documented in the example file. This is the prior art for the new manifest test's shape: a text assertion over a committed config file. Read them to match the style, not the content. (~400 tokens)

4. **`build_profile_media_store`** in the profile-media adapter, plus **`decode_key`** beside it - read the signature and the `backend: str = "local"` default, where `key_bytes` is computed, and the `supabase` branch. Then find the two `secrets.token_bytes(32)` sites in the same file (one per store implementation) and their comments - that is the ephemeral-key behaviour you are declaring a key to defeat. (~500 tokens)

5. **`build_media_store`** in the intake-media adapter - enough to confirm its backend selection is already correct for durable storage and its only gap is the key. (~400 tokens)

## Do NOT read

- The media stores' upload / retrieval / ciphertext-format internals. You are declaring configuration, not changing storage.
- The consent, doctor, care, health and intake modules; the profile client; the avatar code.
- `docs/archive/` (the PRD supersedes it), binary assets, migration files, CI config.
- The Supabase bucket itself - it already exists. Do not attempt bucket creation or a public-read policy.

## Baseline verify (must pass before the first edit)

```bash
node scripts/py.cjs -m pytest -c apps/backend/pyproject.toml tests/unit/test_gateway.py -q
```

Confirmed green on the untouched tree at brief time: **74 passed**.

## Done-verify (acceptance criteria → commands)

- The new manifest test passes, and the full backend unit suite stays green:
  ```bash
  npm run test:unit:backend
  ```
- The manifest actually declares what the ticket asks - read it back, do not just trust the test:
  - `PROFILE_MEDIA_BACKEND` = `supabase`, mirroring the intake entry
  - `PROFILE_MEDIA_KEY` and `INTAKE_MEDIA_KEY` both declared `sync: false`, never with a value
  - `git diff --stat` shows **no** secret material staged
- The example env file's profile-media block is uncommented and still parses: `npm run lint`.

## Handoff notes

- **The two fixes are independent and both land.** Correcting the backing does not supply the key; setting the key does not move bytes off local disk. The reported symptom ("photo gone after deploy") needs both.
- **Failure mode is silent, which is why it is worth a test.** With no key configured there is no error at all - the profile row keeps claiming a photo exists while the bytes become undecryptable. Worth checking any other store that derives a per-process key.
- **Local dev env file.** The repo-root `.env` (gitignored) currently sets `INTAKE_MEDIA_BACKEND` and `INTAKE_MEDIA_KEY` but has neither `PROFILE_MEDIA_BACKEND` nor `PROFILE_MEDIA_KEY`. Add them so local behaviour matches production and the #559 live check is honest. Never commit it, never print an existing secret value.
- **Operator boundary.** Declaring `sync: false` is the whole deliverable. Generating the key, pasting it into the deployment dashboard, and any rotation are out of scope - the agent does not handle deployment secrets.
- **ADR-0020 D2 holds.** No public-read policy, no public URL. Photos stay streamed through the backend and remain unreachable by the browser without a session.
- **No committed test currently reads the manifest.** The `.env.example` text assertions are the only prior art; the new manifest test is the first of its kind, so match the existing text-assertion style rather than inventing one.
