# Brief â€” 387 Voice Intake T02: real ASR transcribe leg for OpenAI-compatible adapter

**Ticket:** #387 Â· **Parent:** #384 Â· **Refreshed:** 2026-09-11
**Reading surface:** ~8K tokens (budget 10K) â€” within budget

## Scope

The `openai_compatible` adapter gains a real ASR transcribe leg, so voice intakes can produce genuine `transcribe -> structure -> pre-summary` output against a real freemium ASR endpoint instead of only the deterministic mock path. `transcribe` POSTs `{base_url}/audio/transcriptions` (standard OpenAI-compatible endpoint) with the audio clip reference and minimal egress context, returns a parsed `TranscribeResult`, and records per-call usage. Timeout/retry/error-taxonomy/`@observe`/breaker/fallback semantics match the structure leg exactly. The degrade-to-raw-review failure path (ticket #386) is the safety net beneath this leg.

Acceptance criteria:

- [ ] `OpenAiCompatibleAdapter.transcribe` POSTs `{base_url}/audio/transcriptions` with Bearer auth and the configured `model` (default `whisper-large-v3-turbo`, overridable via config), carrying the audio clip reference â€” never raw bytes, never name/phone/full record
- [ ] The response is parsed into a real `TranscribeResult` (transcript + transcription confidence proxy); per-call usage is extracted and recorded when the response carries it
- [ ] Timeout <= 30 s; exponential + jitter retries and injectable `client`/`sleep` reused from existing plumbing, not duplicated
- [ ] Outage (network/timeout/429/5xx after retries) typed `retries_exhausted=True`; contract rejection (4xx, malformed payload, schema validation failure) typed `retries_exhausted=False`
- [ ] `@observe` remains on the method so the AI-tracing pre-commit gate stays green
- [ ] Fallback-chain and breaker semantics unchanged â€” a primary ASR outage degrades to the secondary provider
- [ ] Unit tests via `httpx.MockTransport`: happy-path parse into `TranscribeResult`, usage extraction when present, 429/5xx retry-then-outage, 4xx/malformed non-retryable â€” mirroring the adapter's structure-leg suite
- [ ] Docs/brief text stating transcribe is "not supported in this phase" for the `openai_compatible` adapter is updated to describe the real-ASR leg and the degrade-to-raw-review failure path

## Read-list (in order)

1. `apps/backend/modules/intake/adapters/ai_provider_openai_compatible.py` â€” constructor (~57â€“84), `_build_messages` (~86â€“100), `_post_chat` (~102â€“173, the retry/backoff/error-taxonomy pattern to mirror: `httpx.HTTPError` retry, 429/5xx retry, 4xx non-retryable â†’ `Ext002CallError(retries_exhausted=False)`, exhausted â†’ `True`), `_parse_structure_response` (~175â€“217, malformed-output contract-rejection pattern), `_extract_usage_tokens` (~219â€“231), `transcribe` stub (~233â€“238, currently raises not-supported), `structure` (~240â€“252), `@observe` usage (~line 22) (~4K)
2. `apps/backend/modules/intake/adapters/ai_gateway.py` â€” `AiEgressContext` (~53â€“66, extra="forbid"), `TranscribeRequest` (`audio_ref` + context, ~69â€“82), `TranscribeResult` (`transcript` + `confidence`, ~85â€“90), `Ext002CallError` (~149â€“162) (~0.5K)
3. `tests/unit/test_ai_gateway_openai_compatible.py` â€” the structure-leg `httpx.MockTransport` suite to mirror (~2.5K)
4. `apps/backend/app/config.py` â€” `ai_model`/`ai_base_url`/`ai_api_key` settings binding (~202â€“215) and `ai_provider_ext.build_ai_gateway` composition (~290â€“344) so the ASR model override resolves from settings (~1K)
5. `docs/standards/third-party-integration-standards.md` â€” EXT-002 timeout/retry/degradation discipline (Â§ about existing plumbing reuse, not duplication) (~0.5K)

## Do NOT read

- `pipeline.py` (harness/loop unchanged â€” this is a provider-adapter ticket)
- `ai_provider_mock.py`, `ai_provider_ext.py`, `ai_provider_fallback.py` internals
- frontend sources, `docs/archive`, partner/iAM internals
- the degrade path internals beyond what #386 delivered (the failure taxonomy the adapter must type its errors with)

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` â€” warning: 3 pre-existing failures unrelated to intake (`test_app_shell.py::test_dev_otp_gated_outside_dev_test_environment`, `test_app_shell.py::test_mock_sms_adapter_stored_in_demo_mode_but_not_production_default`, `test_seed_demo.py::test_otp_surface_disabled_by_default`); all gateway/intake tests pass (verified 2026-09-11)
- `npm run typecheck` â€” clean (mypy + tsc, verified 2026-09-11)

## Done-verify (acceptance criteria â†’ commands)

- `npm run test:unit:backend` â€” new ASR transcribe tests in `test_ai_gateway_openai_compatible.py` plus the existing gateway suites green
- `npm run check:ai-tracing` â€” green (pre-commit gate over `@observe`)
- `npm run typecheck` â€” clean

## Handoff notes

- Blocked by #386: the degrade fix ships first so the loop is non-blocking even before real ASR exists. #386's tests patch `gateway.transcribe` to raise the typed errors; once this ticket lands, the adapter's own transcribe raises those errors naturally under real failures.
- The `mock` adapter stays the default and is never breaker-wrapped; the degrade path and this leg both belong to the `openai_compatible` configuration.
- Egress discipline mirrors the structure leg: the request carries the audio clip reference plus minimal `AiEgressContext` (language/age_range/sex) â€” never raw bytes stored elsewhere, never patient identity (NFR-SEC-006).
- Groq `/audio/transcriptions` is the freemium default tier (model `whisper-large-v3-turbo`); Gemini fallback flows through the existing primary+secondary fallback chain.
- NFR-001 budget metering is the pipeline's concern (budget gate runs before both legs) â€” the adapter only needs to report per-call usage on the result so metering can account for ASR spend.
