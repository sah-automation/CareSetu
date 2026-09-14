"""Shared application settings (PHASE-1 T7a, #28).

Env-driven configuration consumed by the app shell now and by the worker (#30)
and gateway (#29) next. Plain frozen dataclass over ``os.environ`` - no extra
dependency beyond the declared stack (cost floor ``NFR-001``).
"""

import os
from dataclasses import dataclass

DEFAULT_DATABASE_URL = "postgresql+asyncpg://caresetu:caresetu@localhost:5432/caresetu"
DEFAULT_APP_ENVIRONMENT = "production"
DEFAULT_SMS_PROVIDER = "mock"
DEFAULT_SMS_TIMEOUT_SECONDS = 10.0
DEFAULT_SMS_MAX_RETRIES = 3
DEFAULT_SMS_CIRCUIT_BREAKER_THRESHOLD = 5
DEFAULT_SMS_CIRCUIT_BREAKER_COOLDOWN_SECONDS = 30.0
DEFAULT_WHATSAPP_PROVIDER = "mock"
DEFAULT_WHATSAPP_TIMEOUT_SECONDS = 10.0
DEFAULT_WHATSAPP_MAX_RETRIES = 3
DEFAULT_WHATSAPP_CIRCUIT_BREAKER_THRESHOLD = 5
DEFAULT_WHATSAPP_CIRCUIT_BREAKER_COOLDOWN_SECONDS = 30.0
# Redis consent-status cache (PHASE-3 T4, #213): optional; SQL fallback when
# absent or unhealthy. p95 < 50 ms SLA on the hot path.
DEFAULT_REDIS_URL = ""
DEFAULT_REDIS_CONSENT_TTL_SECONDS = 300
# Redis directory-search result cache (PHASE-6 T02b, #314): optional, same SQL
# fallback + accelerator-only discipline (ADR-0011). p95 < 250 ms cached target.
DEFAULT_REDIS_DIRECTORY_TTL_SECONDS = 300
# Boundary directory result cap (PHASE-6 T2, #324): directory search never
# returns an unbounded nearest-first list - the facade caps the returned items
# at this top-N after distance ordering, on both the in-scope and the wider-area
# fallback paths. A limit, not a correctness rule: filtering, distance ordering
# and fallback semantics are unchanged (MOD-002).
DEFAULT_DIRECTORY_MAX_RESULTS = 50
# Auth-surface rate limit (``NFR-SEC-004``): the OTP/auth endpoints are the
# abuse target, so the gateway caps them per caller. 10 requests / 60 s per
# IP is a headroom-rich ceiling above the one-user flow (register + verify +
# resend) while still stopping bursts.
DEFAULT_AUTH_RATE_LIMIT_MAX_REQUESTS = 10
DEFAULT_AUTH_RATE_LIMIT_WINDOW_SECONDS = 60
# Mirrors ``modules.iam.domain.jwt.ACCESS_TOKEN_TTL_SECONDS``; config stays
# import-free so it reads as one plain dataclass over the environment.
DEFAULT_ACCESS_TOKEN_TTL_SECONDS = 900
# Mirrors ``modules.iam.domain.refresh.REFRESH_TOKEN_TTL_SECONDS`` (~30 days).
DEFAULT_REFRESH_TOKEN_TTL_SECONDS = 2_592_000
# Audit retention (PHASE-4, issue #234 storage item 21): 0 = no expiry, keep
# every regulated act indefinitely. A future compliance decision may raise this
# to 2555 (7 years) via AUDIT_RETENTION_DAYS without code changes; compaction/
# archive logic stays deferred (GAP-011).
DEFAULT_AUDIT_RETENTION_DAYS = 0
# Partner credential artifacts (PHASE-5 T06, #251): encrypted local filesystem
# store under the ``partner/`` object-storage prefix. ``PARTNER_ARTIFACT_KEY``
# is a base64 32-byte AES-256 key from the environment (never committed); the
# store refuses a blank/malformed key (fail-closed, security-phii-standards §4).
DEFAULT_PARTNER_ARTIFACT_ROOT = "var/partner-artifacts"
# MOD-006 intake audio (PHASE-7 T08, #373): encrypted local filesystem store
# under the ``intake/`` object-storage prefix. ``INTAKE_MEDIA_KEY`` is a base64
# 32-byte AES-256 key from the environment (never committed); empty derives an
# ephemeral dev/test key so the encrypted write path always runs (same
# convention as the partner artifact store).
DEFAULT_INTAKE_MEDIA_ROOT = "var/intake-media"
# Durable intake-media backend (PHASE-7 fix, #385): ``local`` files the
# ciphertext under ``var/intake-media`` (dev/CI/tests, byte-identical to the
# original store); ``supabase`` POSTs it into a private Supabase Storage bucket
# so hosted captures survive Render's ephemeral disk. Default ``local`` keeps
# dev/CI/tests unchanged - nothing depends on the network.
DEFAULT_INTAKE_MEDIA_BACKEND = "local"
# Rejected-partner re-submission throttle (PHASE-5 T09, #253): the max
# re-submission rounds a rejected partner may open before the operator queue is
# protected, and the cooldown (days) after which the budget refreshes. Queue
# protection is behavior/limits config, not code (coding-standards §9). ADR-0008
# pins no numbers, so the default stands as a config fallback, overridable by env.
DEFAULT_PARTNER_RE_SUBMISSION_MAX = 3
DEFAULT_PARTNER_RE_SUBMISSION_COOLDOWN_DAYS = 30
# Credential-document cleanup after permanent rejection (US-27, ticket #263):
# the rejection path schedules ``partner_credentials.cleanup_due_at`` this many
# days out; the purge seam then deletes the documents so identity files are not
# hoarded (spec phase-5 "Credential document storage"). Spec-pinned at 30 days.
DEFAULT_PARTNER_CREDENTIAL_CLEANUP_DAYS = 30
# Daily credential-expiry sweep cadence (ADR-0011): the worker's APScheduler
# periodic job (PHASE-6 T04a, #315) runs the close-out pass on this crontab
# expression. Defaults to the daily 01:30 cadence of the backup cron precedent
# (deploy/cron/caresetu-backup.cron); the cadence is a changeable cost, never
# architecture - one env var moves it.
DEFAULT_PARTNER_CREDENTIAL_SWEEP_CRON = "30 1 * * *"
# Langfuse AI observability host (plan-phase7-tracing-prep): the US-region
# cloud endpoint for the CareSetu project. Overridable via ``LANGFUSE_HOST``
# (e.g. a self-hosted instance). Tracing is a no-op until both keys are supplied.
DEFAULT_LANGFUSE_HOST = "https://us.cloud.langfuse.com"
# EXT-002 LLM/AI gateway (PHASE-7 T05, #348): provider selection is a config
# knob with a fail-closed default (mock). The real provider is gated to
# staging/production by ``__post_init__`` - a real key in dev/test is refused
# unless demo mode forces the mock or ``AI_ALLOW_DEV_PROVIDER`` overrides the
# gate. Timeout honours the EXT-002 call discipline (<= 30 s,
# third-party-integration-standards §1).
DEFAULT_AI_PROVIDER = "mock"
DEFAULT_AI_MODEL = ""
# ASR model for the OpenAI-compatible /audio/transcriptions leg (#387): the
# freemium default tier (Groq ``whisper-large-v3-turbo``); overridable via
# ``AI_ASR_MODEL`` so the transcription model is decoupled from the structurer.
DEFAULT_AI_ASR_MODEL = "whisper-large-v3-turbo"
DEFAULT_AI_ALLOW_DEV_PROVIDER = False
DEFAULT_AI_TIMEOUT_SECONDS = 30.0
DEFAULT_AI_MAX_RETRIES = 3
DEFAULT_AI_CIRCUIT_BREAKER_THRESHOLD = 5
DEFAULT_AI_CIRCUIT_BREAKER_COOLDOWN_SECONDS = 30.0
# NFR-001 freemium AI spend cap (PHASE-7 T06/T11): the monthly budget in paise
# the meter reports spend against - observe-and-warn only (PS-10, #408), the
# meter never blocks: the knob stays so a hard cap can be reintroduced later
# without a rewrite. Rs 2,000 / month = 200,000 paise.
DEFAULT_AI_MONTHLY_BUDGET_PAISE = 200_000
DEFAULT_AI_FALLBACK_PROVIDER = ""
DEFAULT_AI_FALLBACK_BASE_URL = ""
DEFAULT_AI_FALLBACK_API_KEY = ""
DEFAULT_AI_FALLBACK_MODEL = ""
# Operator MFA TOTP secret encryption (PHASE-5 S8, #261): the AES-256-GCM key
# for encrypting/decrypting the TOTP secret stored in ``iam_operator_mfa.secret``
# comes from the ``IAM_MFA_SECRET_KEY`` environment variable (never committed).
# Fail-closed: ``issue_operator_session`` refuses to verify without it.


_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_DEV_TEST_ENVIRONMENTS = frozenset({"dev", "test"})


@dataclass(frozen=True)
class Settings:
    """Runtime settings resolved from the environment at load time."""

    database_url: str = DEFAULT_DATABASE_URL
    app_environment: str = DEFAULT_APP_ENVIRONMENT
    gateway_jwt_verify_enabled: bool = False
    gateway_rate_limit_enabled: bool = False
    gateway_jwt_signing_key: str = ""
    gateway_access_token_ttl_seconds: int = DEFAULT_ACCESS_TOKEN_TTL_SECONDS
    gateway_refresh_token_ttl_seconds: int = DEFAULT_REFRESH_TOKEN_TTL_SECONDS
    gateway_rate_limit_auth_max_requests: int = DEFAULT_AUTH_RATE_LIMIT_MAX_REQUESTS
    gateway_rate_limit_auth_window_seconds: int = DEFAULT_AUTH_RATE_LIMIT_WINDOW_SECONDS
    # Intake strict tier (PS-05, #403): its own settings, defaulting to the
    # auth tier values so both surfaces are strict by default and only diverge
    # when configured. Each surface keeps an independent per-client-IP bucket,
    # so a burst on one can never exhaust the other's budget.
    gateway_rate_limit_intake_max_requests: int = DEFAULT_AUTH_RATE_LIMIT_MAX_REQUESTS
    gateway_rate_limit_intake_window_seconds: int = DEFAULT_AUTH_RATE_LIMIT_WINDOW_SECONDS
    sms_provider: str = DEFAULT_SMS_PROVIDER
    sms_api_key: str = ""
    sms_base_url: str = ""
    sms_timeout_seconds: float = DEFAULT_SMS_TIMEOUT_SECONDS
    sms_max_retries: int = DEFAULT_SMS_MAX_RETRIES
    sms_circuit_breaker_threshold: int = DEFAULT_SMS_CIRCUIT_BREAKER_THRESHOLD
    sms_circuit_breaker_cooldown_seconds: float = DEFAULT_SMS_CIRCUIT_BREAKER_COOLDOWN_SECONDS
    whatsapp_provider: str = DEFAULT_WHATSAPP_PROVIDER
    whatsapp_api_key: str = ""
    whatsapp_base_url: str = ""
    whatsapp_timeout_seconds: float = DEFAULT_WHATSAPP_TIMEOUT_SECONDS
    whatsapp_max_retries: int = DEFAULT_WHATSAPP_MAX_RETRIES
    whatsapp_circuit_breaker_threshold: int = DEFAULT_WHATSAPP_CIRCUIT_BREAKER_THRESHOLD
    whatsapp_circuit_breaker_cooldown_seconds: float = (
        DEFAULT_WHATSAPP_CIRCUIT_BREAKER_COOLDOWN_SECONDS
    )
    redis_url: str = DEFAULT_REDIS_URL
    redis_consent_ttl_seconds: int = DEFAULT_REDIS_CONSENT_TTL_SECONDS
    redis_directory_ttl_seconds: int = DEFAULT_REDIS_DIRECTORY_TTL_SECONDS
    # Directory result cap (PHASE-6 T2, #324): the top-N bound applied after
    # distance ordering in ``search_directory`` (both the in-scope and fallback
    # paths), so a patient's list tops out at the meaningful nearest matches.
    directory_max_results: int = DEFAULT_DIRECTORY_MAX_RESULTS
    # The stub flag for audit retention (GAP-011): 0 means no expiry today; the
    # future 2555-day (7-year) policy is a one-line env change, never a code change.
    audit_retention_days: int = DEFAULT_AUDIT_RETENTION_DAYS
    # Extra browser origins allowed by the CORS middleware, e.g. the Vercel
    # origin of the public demo (deployment plan 4.1). Empty by default, which
    # preserves today's posture: only the localhost dev origin is allowed.
    cors_allowed_origins: tuple[str, ...] = ()
    # Explicit demo-flag: when set, the mock-OTP read-back route answers even
    # in production so the deployed portfolio demo can drive register -> verify
    # (deployment plan 4.3). Fail-closed: never valid with a real provider.
    demo_mode: bool = False
    # In-process dispatcher (worker-outbox-runbook Rule 1): when enabled the
    # FastAPI lifespan runs exactly one outbox poll loop (dispatcher +
    # credential-expiry sweep) inside the web process instead of a separate
    # worker process. Only valid at uvicorn --workers 1 (the single-worker
    # rule); default OFF so localhost dev / CI keeps the standalone-worker
    # workflow untouched. Turned ON via DISPATCHER_IN_PROCESS_ENABLED=true in
    # the Render web service's env vars (free compute covers web services
    # only - background workers require a paid instance).
    dispatcher_in_process_enabled: bool = False
    # Encrypted credential-document store (PHASE-5 T06, #251): local root and
    # the base64 AES-256 key. Root defaults to a repo-local ``var/`` dir; the
    # key is empty unless supplied by the environment (the store derives an
    # ephemeral dev key, never committed).
    partner_artifact_root: str = DEFAULT_PARTNER_ARTIFACT_ROOT
    partner_artifact_key: str = ""
    # MOD-006 intake audio media store (PHASE-7 T08, #373; fix #385): the
    # concrete backend is selected by ``intake_media_backend`` - ``local``
    # (default, dev/CI/tests) files encrypted clips under a repo-local ``var/``
    # dir, ``supabase`` (production) stores the same ciphertext in a private
    # Supabase Storage bucket so captures survive Render's ephemeral disk. The
    # AES key ``intake_media_key`` is empty unless supplied by the environment
    # (the store derives an ephemeral dev key, never committed).
    # ``__post_init__`` requires BOTH ``supabase_url`` and
    # ``supabase_service_role_key`` when the backend is ``supabase``
    # (fail-fast boot - a misconfigured production box never boots half-wired).
    intake_media_root: str = DEFAULT_INTAKE_MEDIA_ROOT
    intake_media_key: str = ""
    intake_media_backend: str = DEFAULT_INTAKE_MEDIA_BACKEND
    supabase_url: str = ""
    supabase_service_role_key: str = ""
    # Rejected-partner re-submission throttle (PHASE-5 T09, #253): environment
    # driven like the SMS/WhatsApp knobs (coding-standards §9.1). ``max`` is the
    # re-submission budget before cooldown; ``cooldown_days`` the cooldown length.
    partner_re_submission_max: int = DEFAULT_PARTNER_RE_SUBMISSION_MAX
    partner_re_submission_cooldown_days: int = DEFAULT_PARTNER_RE_SUBMISSION_COOLDOWN_DAYS
    # Credential-document cleanup window after permanent rejection (US-27) - a
    # retention policy, env-driven like the other phase-5 knobs.
    partner_credential_cleanup_days: int = DEFAULT_PARTNER_CREDENTIAL_CLEANUP_DAYS
    # Daily credential-expiry sweep cadence (ADR-0011): the cron expression the
    # worker's periodic job schedules the close-out pass on (PHASE-6 T04a, #315).
    partner_credential_sweep_cron: str = DEFAULT_PARTNER_CREDENTIAL_SWEEP_CRON
    # Encrypted TOTP secret for operator MFA (PHASE-5 S8, #261): AES-256-GCM key
    # from the ``IAM_MFA_SECRET_KEY`` environment; ``issue_operator_session``
    # refuses to verify without it.
    iam_mfa_secret_key: str = ""
    # Langfuse AI observability (plan-phase7-tracing-prep): the SDK keys for LLM
    # call tracing, consumed by the AI gateway port from Phase 7 onward. Both
    # empty by default = tracing disabled, the app boots cleanly without an
    # account. ``__post_init__`` enforces both set or both empty.
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = DEFAULT_LANGFUSE_HOST
    # EXT-002 LLM/AI gateway (PHASE-7 T05, #348): provider selection is a config
    # knob (mock is the fail-closed default); the real provider key/base URL/
    # model. ``__post_init__`` refuses a real provider in dev/test unless demo
    # mode forces the mock or ``ai_allow_dev_provider`` overrides the gate,
    # mirroring the SMS/WhatsApp fail-closed posture.
    ai_provider: str = DEFAULT_AI_PROVIDER
    ai_model: str = DEFAULT_AI_MODEL
    ai_asr_model: str = DEFAULT_AI_ASR_MODEL
    ai_allow_dev_provider: bool = DEFAULT_AI_ALLOW_DEV_PROVIDER
    ai_api_key: str = ""
    ai_base_url: str = ""
    ai_timeout_seconds: float = DEFAULT_AI_TIMEOUT_SECONDS
    ai_max_retries: int = DEFAULT_AI_MAX_RETRIES
    ai_circuit_breaker_threshold: int = DEFAULT_AI_CIRCUIT_BREAKER_THRESHOLD
    ai_circuit_breaker_cooldown_seconds: float = DEFAULT_AI_CIRCUIT_BREAKER_COOLDOWN_SECONDS
    ai_monthly_budget_paise: int = DEFAULT_AI_MONTHLY_BUDGET_PAISE
    ai_fallback_provider: str = DEFAULT_AI_FALLBACK_PROVIDER
    ai_fallback_base_url: str = DEFAULT_AI_FALLBACK_BASE_URL
    ai_fallback_api_key: str = DEFAULT_AI_FALLBACK_API_KEY
    ai_fallback_model: str = DEFAULT_AI_FALLBACK_MODEL

    def __post_init__(self) -> None:
        if self.gateway_jwt_verify_enabled and not self.gateway_jwt_signing_key:
            raise ValueError(
                "gateway_jwt_verify_enabled=True requires GATEWAY_JWT_SIGNING_KEY; "
                "refusing to verify tokens with a blank key."
            )
        if self.gateway_rate_limit_auth_max_requests <= 0:
            raise ValueError("gateway_rate_limit_auth_max_requests must be positive")
        if self.gateway_rate_limit_auth_window_seconds <= 0:
            raise ValueError("gateway_rate_limit_auth_window_seconds must be positive")
        provider = self.sms_provider.strip().lower()
        if provider not in {"mock", "provider"}:
            raise ValueError(
                f"unsupported sms_provider {self.sms_provider!r}; expected 'mock' or 'provider'"
            )
        if self.demo_mode and provider != "mock":
            raise ValueError(
                "demo_mode=True requires sms_provider='mock' (fail-closed): "
                "the demo flag must never ride a real provider"
            )
        if provider == "provider":
            if self.app_environment.strip().lower() in _DEV_TEST_ENVIRONMENTS:
                raise ValueError(
                    "sms_provider='provider' is gated to staging/production: set "
                    "APP_ENVIRONMENT to 'staging' or 'production' before using the "
                    "real EXT-001 path. Refusing it in dev/test."
                )
            if not self.sms_api_key:
                raise ValueError(
                    "sms_provider='provider' requires SMS_API_KEY from the environment"
                )
            if not self.sms_base_url:
                raise ValueError(
                    "sms_provider='provider' requires SMS_BASE_URL from the environment"
                )
        if not (0 < self.sms_timeout_seconds <= 10):
            raise ValueError(
                "sms_timeout_seconds must be in (0, 10] to honour the EXT-001 "
                "call discipline (third-party-integration-standards §1)"
            )
        whatsapp_provider = self.whatsapp_provider.strip().lower()
        if whatsapp_provider not in {"mock", "provider"}:
            raise ValueError(
                f"unsupported whatsapp_provider {self.whatsapp_provider!r}; "
                "expected 'mock' or 'provider'"
            )
        if whatsapp_provider == "provider":
            if self.app_environment.strip().lower() in _DEV_TEST_ENVIRONMENTS:
                raise ValueError(
                    "whatsapp_provider='provider' is gated to staging/production: set "
                    "APP_ENVIRONMENT to 'staging' or 'production' before using the "
                    "real EXT-003 path. Refusing it in dev/test."
                )
            if not self.whatsapp_api_key:
                raise ValueError(
                    "whatsapp_provider='provider' requires WHATSAPP_API_KEY from the environment"
                )
            if not self.whatsapp_base_url:
                raise ValueError(
                    "whatsapp_provider='provider' requires WHATSAPP_BASE_URL from the environment"
                )
        if not (0 < self.whatsapp_timeout_seconds <= 10):
            raise ValueError(
                "whatsapp_timeout_seconds must be in (0, 10] to honour the EXT-003 "
                "call discipline (third-party-integration-standards §1)"
            )
        ai_provider = self.ai_provider.strip().lower()
        if ai_provider not in {"mock", "openai_compatible"}:
            raise ValueError(
                f"unsupported ai_provider {self.ai_provider!r}; expected "
                "'mock' or 'openai_compatible'"
            )
        if self.demo_mode and ai_provider != "mock":
            raise ValueError(
                "demo_mode=True requires ai_provider='mock' (fail-closed): "
                "the demo flag must never ride a real EXT-002 provider"
            )
        if ai_provider == "openai_compatible":
            if (
                self.app_environment.strip().lower() in _DEV_TEST_ENVIRONMENTS
                and not self.ai_allow_dev_provider
            ):
                raise ValueError(
                    "ai_provider='openai_compatible' is gated to staging/production: set "
                    "APP_ENVIRONMENT to 'staging' or 'production' (or set "
                    "AI_ALLOW_DEV_PROVIDER=true for dev/test) before using the "
                    "real EXT-002 path. Refusing it in dev/test."
                )
            if not self.ai_api_key:
                raise ValueError(
                    "ai_provider='openai_compatible' requires AI_API_KEY from the environment"
                )
            if not self.ai_base_url:
                raise ValueError(
                    "ai_provider='openai_compatible' requires AI_BASE_URL from the environment"
                )
            if not self.ai_model:
                raise ValueError(
                    "ai_provider='openai_compatible' requires AI_MODEL from the environment"
                )
            if not self.ai_asr_model:
                raise ValueError(
                    "ai_provider='openai_compatible' requires AI_ASR_MODEL from the environment"
                )
        fallback_vars = {
            "AI_FALLBACK_PROVIDER": self.ai_fallback_provider,
            "AI_FALLBACK_BASE_URL": self.ai_fallback_base_url,
            "AI_FALLBACK_API_KEY": self.ai_fallback_api_key,
            "AI_FALLBACK_MODEL": self.ai_fallback_model,
        }
        if any(value.strip() for value in fallback_vars.values()):
            unset = [name for name, value in fallback_vars.items() if not value.strip()]
            if unset:
                raise ValueError(
                    "AI fallback must be all-or-none; missing: " + ", ".join(sorted(unset))
                )
            if self.ai_fallback_provider.strip().lower() != "openai_compatible":
                raise ValueError(
                    "ai_fallback_provider must be 'openai_compatible'; got "
                    f"{self.ai_fallback_provider!r}"
                )
        if not (0 < self.ai_timeout_seconds <= 30):
            raise ValueError(
                "ai_timeout_seconds must be in (0, 30] to honour the EXT-002 "
                "call discipline (third-party-integration-standards §1)"
            )
        if self.ai_max_retries <= 0:
            raise ValueError("ai_max_retries must be positive")
        if self.ai_circuit_breaker_threshold <= 0:
            raise ValueError("ai_circuit_breaker_threshold must be positive")
        if self.ai_monthly_budget_paise <= 0:
            raise ValueError("ai_monthly_budget_paise must be positive")
        if self.ai_circuit_breaker_cooldown_seconds <= 0:
            raise ValueError("ai_circuit_breaker_cooldown_seconds must be positive")
        if self.redis_consent_ttl_seconds <= 0:
            raise ValueError("redis_consent_ttl_seconds must be positive")
        if self.redis_directory_ttl_seconds <= 0:
            raise ValueError("redis_directory_ttl_seconds must be positive")
        if self.directory_max_results <= 0:
            raise ValueError("directory_max_results must be positive")
        if self.audit_retention_days < 0:
            raise ValueError("audit_retention_days must be zero or positive (0 = no expiry)")
        if self.gateway_access_token_ttl_seconds <= 0:
            raise ValueError("gateway_access_token_ttl_seconds must be positive")
        if self.gateway_refresh_token_ttl_seconds <= 0:
            raise ValueError("gateway_refresh_token_ttl_seconds must be positive")
        if self.sms_circuit_breaker_threshold <= 0:
            raise ValueError("sms_circuit_breaker_threshold must be positive")
        if self.sms_circuit_breaker_cooldown_seconds <= 0:
            raise ValueError("sms_circuit_breaker_cooldown_seconds must be positive")
        if self.whatsapp_circuit_breaker_threshold <= 0:
            raise ValueError("whatsapp_circuit_breaker_threshold must be positive")
        if self.whatsapp_circuit_breaker_cooldown_seconds <= 0:
            raise ValueError("whatsapp_circuit_breaker_cooldown_seconds must be positive")
        if self.partner_re_submission_max <= 0:
            raise ValueError("partner_re_submission_max must be positive")
        if self.partner_re_submission_cooldown_days <= 0:
            raise ValueError("partner_re_submission_cooldown_days must be positive")
        if self.partner_credential_cleanup_days <= 0:
            raise ValueError("partner_credential_cleanup_days must be positive")
        if bool(self.langfuse_public_key) != bool(self.langfuse_secret_key):
            raise ValueError(
                "LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY must both be set or "
                "both empty; refusing to initialise Langfuse with a partial key pair."
            )
        intake_backend = self.intake_media_backend.strip().lower()
        if intake_backend not in {"local", "supabase"}:
            raise ValueError(
                f"unsupported intake_media_backend {self.intake_media_backend!r}; "
                "expected 'local' or 'supabase'"
            )
        if intake_backend == "supabase":
            if not self.supabase_url.strip():
                raise ValueError(
                    "intake_media_backend='supabase' requires SUPABASE_URL from the environment"
                )
            if not self.supabase_service_role_key.strip():
                raise ValueError(
                    "intake_media_backend='supabase' requires "
                    "SUPABASE_SERVICE_ROLE_KEY from the environment"
                )

    @property
    def mock_otp_readback_enabled(self) -> bool:
        """Whether the plaintext mock-OTP read-back surface may be exposed.

        True only for the mock provider in a dev/test environment, or under the
        explicit ``DEMO_MODE`` flag (deployment plan 4.3) - never for the real
        provider. One settled policy behind both the adapter-storage gate and
        the ``/v1/auth/dev/otp`` route gate in ``create_app``.
        """
        return self.sms_provider.strip().lower() == "mock" and (
            self.app_environment.strip().lower() in _DEV_TEST_ENVIRONMENTS or self.demo_mode
        )


def _env_bool(name: str, default: bool) -> bool:
    """Parse a boolean environment variable, falling back to ``default``."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in _TRUE_VALUES


def _env_float(name: str, default: float) -> float:
    """Parse a float environment variable, falling back to ``default``."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    return float(raw)


def _env_int(name: str, default: int) -> int:
    """Parse an integer environment variable, falling back to ``default``."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    return int(raw)


def _env_csv(name: str) -> tuple[str, ...]:
    """Parse a comma-separated environment variable into trimmed entries.

    Splits on commas, strips whitespace, and drops empties; an unset or empty
    value yields ``()`` so the caller's default posture is untouched.
    """
    raw = os.environ.get(name)
    if raw is None:
        return ()
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def get_settings() -> Settings:
    """Build ``Settings`` from environment variables.

    ``create_app`` resolves this and stores it on ``app.state.settings`` once
    per process; the worker (#30) and gateway (#29) consume that resolved value
    rather than re-reading the environment. Both gateway middleware default to
    disabled (PHASE-1 T7b, #29); the Phase 2 real ``jwt_verify`` (ticket #59)
    additionally requires ``GATEWAY_JWT_SIGNING_KEY`` - ``Settings`` refuses
    the flag otherwise (fail-closed boot, never a blank-key verify).
    """
    return Settings(
        database_url=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL),
        app_environment=os.environ.get("APP_ENVIRONMENT", DEFAULT_APP_ENVIRONMENT),
        gateway_jwt_verify_enabled=_env_bool("GATEWAY_JWT_VERIFY_ENABLED", False),
        gateway_rate_limit_enabled=_env_bool("GATEWAY_RATE_LIMIT_ENABLED", False),
        gateway_jwt_signing_key=os.environ.get("GATEWAY_JWT_SIGNING_KEY", ""),
        gateway_access_token_ttl_seconds=_env_int(
            "GATEWAY_ACCESS_TOKEN_TTL_SECONDS", DEFAULT_ACCESS_TOKEN_TTL_SECONDS
        ),
        gateway_refresh_token_ttl_seconds=_env_int(
            "GATEWAY_REFRESH_TOKEN_TTL_SECONDS", DEFAULT_REFRESH_TOKEN_TTL_SECONDS
        ),
        gateway_rate_limit_auth_max_requests=_env_int(
            "GATEWAY_RATE_LIMIT_AUTH_MAX_REQUESTS", DEFAULT_AUTH_RATE_LIMIT_MAX_REQUESTS
        ),
        gateway_rate_limit_auth_window_seconds=_env_int(
            "GATEWAY_RATE_LIMIT_AUTH_WINDOW_SECONDS", DEFAULT_AUTH_RATE_LIMIT_WINDOW_SECONDS
        ),
        gateway_rate_limit_intake_max_requests=_env_int(
            "GATEWAY_RATE_LIMIT_INTAKE_MAX_REQUESTS", DEFAULT_AUTH_RATE_LIMIT_MAX_REQUESTS
        ),
        gateway_rate_limit_intake_window_seconds=_env_int(
            "GATEWAY_RATE_LIMIT_INTAKE_WINDOW_SECONDS", DEFAULT_AUTH_RATE_LIMIT_WINDOW_SECONDS
        ),
        sms_provider=os.environ.get("SMS_PROVIDER", DEFAULT_SMS_PROVIDER),
        sms_api_key=os.environ.get("SMS_API_KEY", ""),
        sms_base_url=os.environ.get("SMS_BASE_URL", ""),
        sms_timeout_seconds=_env_float("SMS_TIMEOUT_SECONDS", DEFAULT_SMS_TIMEOUT_SECONDS),
        sms_max_retries=_env_int("SMS_MAX_RETRIES", DEFAULT_SMS_MAX_RETRIES),
        sms_circuit_breaker_threshold=_env_int(
            "SMS_CIRCUIT_BREAKER_THRESHOLD", DEFAULT_SMS_CIRCUIT_BREAKER_THRESHOLD
        ),
        sms_circuit_breaker_cooldown_seconds=_env_float(
            "SMS_CIRCUIT_BREAKER_COOLDOWN_SECONDS",
            DEFAULT_SMS_CIRCUIT_BREAKER_COOLDOWN_SECONDS,
        ),
        whatsapp_provider=os.environ.get("WHATSAPP_PROVIDER", DEFAULT_WHATSAPP_PROVIDER),
        whatsapp_api_key=os.environ.get("WHATSAPP_API_KEY", ""),
        whatsapp_base_url=os.environ.get("WHATSAPP_BASE_URL", ""),
        whatsapp_timeout_seconds=_env_float(
            "WHATSAPP_TIMEOUT_SECONDS", DEFAULT_WHATSAPP_TIMEOUT_SECONDS
        ),
        whatsapp_max_retries=_env_int("WHATSAPP_MAX_RETRIES", DEFAULT_WHATSAPP_MAX_RETRIES),
        whatsapp_circuit_breaker_threshold=_env_int(
            "WHATSAPP_CIRCUIT_BREAKER_THRESHOLD",
            DEFAULT_WHATSAPP_CIRCUIT_BREAKER_THRESHOLD,
        ),
        whatsapp_circuit_breaker_cooldown_seconds=_env_float(
            "WHATSAPP_CIRCUIT_BREAKER_COOLDOWN_SECONDS",
            DEFAULT_WHATSAPP_CIRCUIT_BREAKER_COOLDOWN_SECONDS,
        ),
        redis_url=os.environ.get("REDIS_URL", DEFAULT_REDIS_URL),
        redis_consent_ttl_seconds=_env_int(
            "REDIS_CONSENT_TTL_SECONDS", DEFAULT_REDIS_CONSENT_TTL_SECONDS
        ),
        redis_directory_ttl_seconds=_env_int(
            "REDIS_DIRECTORY_TTL_SECONDS", DEFAULT_REDIS_DIRECTORY_TTL_SECONDS
        ),
        directory_max_results=_env_int("DIRECTORY_MAX_RESULTS", DEFAULT_DIRECTORY_MAX_RESULTS),
        audit_retention_days=_env_int("AUDIT_RETENTION_DAYS", DEFAULT_AUDIT_RETENTION_DAYS),
        cors_allowed_origins=_env_csv("CORS_ALLOWED_ORIGINS"),
        demo_mode=_env_bool("DEMO_MODE", False),
        dispatcher_in_process_enabled=_env_bool("DISPATCHER_IN_PROCESS_ENABLED", False),
        partner_artifact_root=os.environ.get(
            "PARTNER_ARTIFACT_ROOT", DEFAULT_PARTNER_ARTIFACT_ROOT
        ),
        partner_artifact_key=os.environ.get("PARTNER_ARTIFACT_KEY", ""),
        intake_media_root=os.environ.get("INTAKE_MEDIA_ROOT", DEFAULT_INTAKE_MEDIA_ROOT),
        intake_media_key=os.environ.get("INTAKE_MEDIA_KEY", ""),
        intake_media_backend=os.environ.get("INTAKE_MEDIA_BACKEND", DEFAULT_INTAKE_MEDIA_BACKEND),
        supabase_url=os.environ.get("SUPABASE_URL", ""),
        supabase_service_role_key=os.environ.get("SUPABASE_SERVICE_ROLE_KEY", ""),
        partner_re_submission_max=_env_int(
            "PARTNER_RE_SUBMISSION_MAX", DEFAULT_PARTNER_RE_SUBMISSION_MAX
        ),
        partner_re_submission_cooldown_days=_env_int(
            "PARTNER_RE_SUBMISSION_COOLDOWN_DAYS",
            DEFAULT_PARTNER_RE_SUBMISSION_COOLDOWN_DAYS,
        ),
        partner_credential_cleanup_days=_env_int(
            "PARTNER_CREDENTIAL_CLEANUP_DAYS",
            DEFAULT_PARTNER_CREDENTIAL_CLEANUP_DAYS,
        ),
        partner_credential_sweep_cron=os.environ.get(
            "PARTNER_CREDENTIAL_SWEEP_CRON", DEFAULT_PARTNER_CREDENTIAL_SWEEP_CRON
        ),
        iam_mfa_secret_key=os.environ.get("IAM_MFA_SECRET_KEY", ""),
        langfuse_public_key=os.environ.get("LANGFUSE_PUBLIC_KEY", ""),
        langfuse_secret_key=os.environ.get("LANGFUSE_SECRET_KEY", ""),
        langfuse_host=os.environ.get("LANGFUSE_HOST", DEFAULT_LANGFUSE_HOST),
        ai_provider=os.environ.get("AI_PROVIDER", DEFAULT_AI_PROVIDER),
        ai_model=os.environ.get("AI_MODEL", DEFAULT_AI_MODEL),
        ai_asr_model=os.environ.get("AI_ASR_MODEL", DEFAULT_AI_ASR_MODEL),
        ai_allow_dev_provider=_env_bool("AI_ALLOW_DEV_PROVIDER", DEFAULT_AI_ALLOW_DEV_PROVIDER),
        ai_api_key=os.environ.get("AI_API_KEY", ""),
        ai_base_url=os.environ.get("AI_BASE_URL", ""),
        ai_timeout_seconds=_env_float("AI_TIMEOUT_SECONDS", DEFAULT_AI_TIMEOUT_SECONDS),
        ai_max_retries=_env_int("AI_MAX_RETRIES", DEFAULT_AI_MAX_RETRIES),
        ai_circuit_breaker_threshold=_env_int(
            "AI_CIRCUIT_BREAKER_THRESHOLD", DEFAULT_AI_CIRCUIT_BREAKER_THRESHOLD
        ),
        ai_circuit_breaker_cooldown_seconds=_env_float(
            "AI_CIRCUIT_BREAKER_COOLDOWN_SECONDS",
            DEFAULT_AI_CIRCUIT_BREAKER_COOLDOWN_SECONDS,
        ),
        ai_monthly_budget_paise=_env_int(
            "AI_MONTHLY_BUDGET_PAISE", DEFAULT_AI_MONTHLY_BUDGET_PAISE
        ),
        ai_fallback_provider=os.environ.get("AI_FALLBACK_PROVIDER", DEFAULT_AI_FALLBACK_PROVIDER),
        ai_fallback_base_url=os.environ.get("AI_FALLBACK_BASE_URL", DEFAULT_AI_FALLBACK_BASE_URL),
        ai_fallback_api_key=os.environ.get("AI_FALLBACK_API_KEY", DEFAULT_AI_FALLBACK_API_KEY),
        ai_fallback_model=os.environ.get("AI_FALLBACK_MODEL", DEFAULT_AI_FALLBACK_MODEL),
    )
