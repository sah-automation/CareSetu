# Brief - 392 ASR port seam + OpenAI-compatible multipart upload

**Ticket:** #392 · **Parent:** #388 · **Refreshed:** 2026-09-12
**Reading surface:** ~8K tokens (budget 10K) - within budget

## Scope

The AI gateway port and the OpenAI-compatible ASR adapter are aligned with the declared egress boundary so a real voice intake can be transcribed. `TranscribeRequest` gains an `audio_bytes` field (the decrypted clip) while keeping `audio_ref` for the proxy-style adapter and audit. The OpenAI-compatible adapter's transcribe leg posts the clip as `multipart/form-data` (audio file + configured ASR model + language) instead of the current JSON body carrying only the `audio_ref`, which the provider rejects with HTTP 400. Retry/backoff and error taxonomy match the structure leg: 429/5xx retried then typed outage; 4xx contract rejections propagate immediately and never trip the circuit breaker. When no clip bytes are supplied the leg fails closed with a contract-rejection error. The mock and proxy-style EXT-002 adapters keep their current behavior; the fallback chain is unchanged. A line in the egress matrix notes that the decrypted clip is sent to the ASR provider under the documented boundary (clip + declared context only, never name/phone/full record).

Acceptance criteria:

- [ ] `TranscribeRequest` carries both `audio_ref` (unchanged, for proxy/audit) and optional `audio_bytes`; existing adapters unaffected
- [ ] OpenAI-compatible `transcribe` sends `multipart/form-data` containing the audio file, model, and language - pinned by an injected-HTTP unit test
- [ ] Provider HTTP 400 maps to a contract-rejection `Ext002CallError` (`retries_exhausted=False`) that never trips the breaker and never falls back
- [ ] 429/5xx retried with the existing backoff, then typed outage (`retries_exhausted=True`)
- [ ] No clip bytes supplied -> fails closed with a contract-rejection error
- [ ] `@observe` and the AI-tracing gate stay green; per-call usage still recorded on the result
- [ ] Mock and proxy-style EXT-002 adapters unchanged; fallback-chain semantics unchanged
- [ ] Egress matrix line updated: decrypted clip is within the documented boundary (clip + declared context only)

## Read-list (in order)

1. `apps/backend/modules/intake/adapters/ai_gateway.py` - `TranscribeRequest` (fields `audio_ref`, `mode`, `context`, the docstring stating the clip is within the egress boundary), `TranscribeResult`, `AiEgressContext`, `Ext002CallError` (`retries_exhausted` semantics), the `AiGateway` protocol (~0.6K)
2. `apps/backend/modules/intake/adapters/ai_provider_openai_compatible.py` - constructor-injected transport/client, the `_post_json`/`_post_chat` retry/backoff/error-taxonomy pattern (httpx errors and 429/5xx retried; 4xx/malformed -> `Ext002CallError(retries_exhausted=False)`; exhausted -> `True`), the current transcribe leg (posts JSON with `audio_ref`, ~`/audio/transcriptions`), the response-parse and usage-extraction patterns, the structure/draft_rx legs, `@observe` usage (~3.5K)
3. `tests/unit/test_ai_gateway_openai_compatible.py` - the `httpx.MockTransport` suite for the structure leg to mirror for transcribe (happy path, 429/5xx retry-then-outage, 4xx/malformed non-retryable, egress assertions) (~2.2K)
4. `apps/backend/app/config.py` - ASR model binding (`DEFAULT_AI_ASR_MODEL` etc.) plus `ai_provider_ext.build_ai_gateway` composition so the model/url/key resolve from settings (~0.8K)
5. `docs/standards/third-party-integration-standards.md` - EXT-002 timeout/retry/degradation discipline and the NFR-SEC-006 egress boundary reference for the matrix line (~0.6K)

## Do NOT read

- Pipeline internals (this is a provider-adapter ticket - bytes are populated by #393)
- Mock/ext/fallback adapter internals beyond construction · frontend · `docs/archive`

## Baseline verify (must pass before the first edit, verified 2026-09-12)

- `npm run test:unit:backend` - 1723 passed, 3 pre-existing failures unrelated to intake (`test_app_shell.py::test_dev_otp_gated_outside_dev_test_environment`, `test_app_shell.py::test_mock_sms_adapter_stored_in_demo_mode_but_not_production_default`, `test_seed_demo.py::test_otp_surface_disabled_by_default`)
- `npm run typecheck` - backend mypy clean (213 files)
- `npm run check:ai-tracing` - green (pre-commit gate over `@observe`)

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend` - new transcribe multipart/contract-rejection/outage tests plus the existing gateway suites green
- `npm run check:ai-tracing` - green
- `npm run typecheck` - backend clean

## Handoff notes

- Additive port change: `audio_bytes` defaults to `None` and `audio_ref` stays - the mock and the proxy-style EXT-002 adapters must keep compiling with zero edits.
- The provider in use (OpenAI-compatible, Groq) requires `multipart/form-data` with the actual audio file; a JSON/ref-only payload is rejected with HTTP 400 - that rejection is a CONTRACT rejection, distinguishable from an outage.
- Contract rejections (`retries_exhausted=False`) propagate immediately, never trip the breaker (threshold 5, cooldown 30s), never fall back. 429/5xx after the existing backoff -> `retries_exhausted=True`.
- Until #393 feeds bytes, a real voice intake against this adapter fails closed -> the #386 degrade path keeps it non-blocking. This ticket alone must not regress anything today.
- Record per-call usage on the result so the pipeline's budget metering can account for ASR spend.
- Egress: the decrypted clip + declared context (language/age_range/sex) only - never any identity/full-record field (NFR-SEC-006).
