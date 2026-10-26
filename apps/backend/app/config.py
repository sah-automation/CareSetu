"""Shared application settings (PHASE-1 T7a, #28).

Env-driven configuration consumed by the app shell now and by the worker (#30)
and gateway (#29) next. Plain frozen dataclass over ``os.environ`` - no extra
dependency beyond the declared stack (cost floor ``NFR-001``).
"""

import math
import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from modules.iam.domain.mfa_lockout import (
    DEFAULT_OPERATOR_MFA_LOCKOUT_SECONDS,
    DEFAULT_OPERATOR_MFA_LOCKOUT_THRESHOLD,
)

DEFAULT_DATABASE_URL = "postgresql+asyncpg://caresetu:caresetu@localhost:5432/caresetu"
DEFAULT_APP_ENVIRONMENT = "production"
# The app's human-maintained version (PHASE-14A A4, #696): the default Sentry
# ``release`` when ``OTEL_SERVICE_VERSION`` is unset, also handed to FastAPI.
# The deploy pipeline sets ``OTEL_SERVICE_VERSION`` to the git SHA so production
# releases are SHA-tagged; never hardcode a SHA here.
APP_VERSION = "0.1.0"
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
# MOD-001/MOD-002 profile photos (#529, ADR-0020, #532): encrypted local
# filesystem store under the ``patient/`` and ``doctor/`` object-storage
# prefixes. ``PROFILE_MEDIA_KEY`` is a base64 32-byte AES-256 key from the
# environment (never committed); empty derives an ephemeral dev/test key so the
# encrypted write path always runs (same convention as the intake media store).
DEFAULT_PROFILE_MEDIA_ROOT = "var/profile-media"
# Durable profile-media backend (#529, ADR-0020, #532): ``local`` files the
# ciphertext under ``var/profile-media`` (dev/CI/tests); ``supabase`` POSTs it
# into the private ``profile-media`` Supabase Storage bucket so hosted photos
# survive Render's ephemeral disk and a leaked key is never a leak. Default
# ``local`` keeps dev/CI/tests unchanged - nothing depends on the network.
DEFAULT_PROFILE_MEDIA_BACKEND = "local"
DEFAULT_PROFILE_MEDIA_MAX_ATTEMPTS = 3
DEFAULT_PROFILE_MEDIA_BACKOFF_SECONDS = 0.5
DEFAULT_PROFILE_MEDIA_JITTER_FRACTION = 0.25
DEFAULT_PROFILE_MEDIA_CIRCUIT_BREAKER_THRESHOLD = 5
DEFAULT_PROFILE_MEDIA_CIRCUIT_BREAKER_COOLDOWN_SECONDS = 30.0
DEFAULT_PROFILE_MEDIA_TIMEOUT_SECONDS = 30.0
# The profile-photo size ceiling, and the SINGLE source of that value
# (coding-standards §9.2). Both photo write paths read this one setting: the
# doctor console route through ``app.state.profile_media_max_upload_bytes`` and
# the patient's ``/v1/me/photo`` through the ceiling injected into the identity
# facade, so raising ``PROFILE_MEDIA_MAX_UPLOAD_BYTES`` moves both limits
# together. Nothing else may re-declare the number.
DEFAULT_PROFILE_MEDIA_MAX_UPLOAD_BYTES = 5 * 1024 * 1024
# CSP report-only (PHASE-14B Batch 2, #775): hardened CSP on API responses and
# report-only CSP on the frontend. The report URI points to the backend collector
# endpoint. When unset, reporting directives are omitted.
DEFAULT_CSP_REPORT_ONLY_ENABLED = False
DEFAULT_CSP_REPORT_URI = ""
# CSP report collector (PHASE-14B Batch 2, #776): public, rate-limited endpoint
# accepting both legacy (report-uri) and modern (report-to) CSP report formats.
# All limits are configurable so a deployment can tune them without code changes
# (coding-standards §9.1).
DEFAULT_CSP_COLLECTOR_MAX_REPORT_BYTES = 16 * 1024  # 16 KB
DEFAULT_CSP_COLLECTOR_MAX_DIRECTIVE_LENGTH = 100
DEFAULT_CSP_COLLECTOR_MAX_DISPOSITION_LENGTH = 30
DEFAULT_CSP_COLLECTOR_MAX_BLOCKED_SOURCE_LENGTH = 255
DEFAULT_CSP_COLLECTOR_MAX_DOCUMENT_URI_LENGTH = 255
DEFAULT_CSP_COLLECTOR_RATE_LIMIT_MAX_REQUESTS = 60
DEFAULT_CSP_COLLECTOR_RATE_LIMIT_WINDOW_SECONDS = 60
DEFAULT_CSP_COLLECTOR_MAX_BUCKETS = 1024
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
# The daily metrics pull's request timeout (#750): one aggregate request per
# nightly run, so the ceiling only has to survive a slow vendor answer, not a
# retry loop. Configuration like every other outbound timeout - one env var
# moves it (third-party-integration-standards 1, coding-standards 9.1).
DEFAULT_LANGFUSE_TIMEOUT_SECONDS = 30.0
# EXT-002 LLM/AI gateway (PHASE-7 T05, #348): provider selection is a config
# knob with a fail-closed default (mock). The real provider is gated to
# staging/production by ``__post_init__`` - a real key in dev/test is refused
# unless demo mode forces the mock or ``AI_ALLOW_DEV_PROVIDER`` overrides the
# gate, and a real provider under demo_mode is refused unless
# ``AI_ALLOW_DEMO_PROVIDER`` opts in (T14, #414). Timeout honours the EXT-002
# call discipline (<= 30 s, third-party-integration-standards §1).
DEFAULT_AI_PROVIDER = "mock"
DEFAULT_AI_MODEL = ""
# ASR model for the OpenAI-compatible /audio/transcriptions leg (#387): the
# freemium default tier (Groq ``whisper-large-v3-turbo``); overridable via
# ``AI_ASR_MODEL`` so the transcription model is decoupled from the structurer.
DEFAULT_AI_ASR_MODEL = "whisper-large-v3-turbo"
DEFAULT_AI_ALLOW_DEV_PROVIDER = False
# Opt-in that lets a real OpenAI-compatible provider run under demo_mode (T14,
# #414). Defaults False so demo+mock stays the fail-closed posture; the flag is
# ignored when demo_mode is False. Orthogonal to AI_ALLOW_DEV_PROVIDER.
DEFAULT_AI_ALLOW_DEMO_PROVIDER = False
DEFAULT_AI_TIMEOUT_SECONDS = 30.0
DEFAULT_AI_MAX_RETRIES = 3
DEFAULT_AI_CIRCUIT_BREAKER_THRESHOLD = 5
DEFAULT_AI_CIRCUIT_BREAKER_COOLDOWN_SECONDS = 30.0
# NFR-001 freemium AI spend cap (PHASE-7 T06/T11): the monthly budget in paise
# the meter reports spend against - observe-and-warn only (PS-10, #408), the
# meter never blocks: the knob stays so a hard cap can be reintroduced later
# without a rewrite. Rs 2,000 / month = 200,000 paise.
DEFAULT_AI_MONTHLY_BUDGET_PAISE = 200_000
# Per-model AI pricing (PHASE-14A B1, #699): the metered cost of a completed AI
# call is ``input_tokens * price_in + output_tokens * price_out`` in paise per
# token, looked up by the serving model. It is a comma-separated list of
# ``model:price_in_paise:price_out_paise`` entries - deployment configuration,
# never hardcoded (coding-standards §9.1), because a model's rate tracks the
# provider and tier. The default prices the free mock at an explicit 0 so it is
# a KNOWN free model (never flagged); a model absent from the table is UNKNOWN,
# so its 0 cost is logged (visible, not hidden) until its rate is configured.
DEFAULT_AI_PRICING_TABLE = "mock-model:0:0"
DEFAULT_AI_FALLBACK_PROVIDER = ""
DEFAULT_AI_FALLBACK_BASE_URL = ""
DEFAULT_AI_FALLBACK_API_KEY = ""
DEFAULT_AI_FALLBACK_MODEL = ""
# Observability gates (PHASE-14A A5, #693; plan-phase14 §4, Appendix A.2):
# every vendor gate is additive and disabled by default so local dev, tests and
# CI are unchanged until one is set. Nothing reads these yet - later batch
# tickets A1 (structlog), A2 (trace propagation), A3 (OTel) and A4 (Sentry)
# consume them. ``LOG_FORMAT`` is the two-value log renderer selector.
DEFAULT_LOG_FORMAT = "console"
DEFAULT_SENTRY_TRACES_SAMPLE_RATE = 0.0
DEFAULT_OTEL_TRACES_SAMPLER_RATIO = 1.0
# Days one nightly observability rollup invocation may cover (PHASE-14A B5b, #705).
# Ninety trailing days comfortably spans MOD-013's whole retained history at
# launch scale while keeping a single scheduled pass bounded; the trimmed surplus
# is rolled by the next invocation, never skipped.
DEFAULT_OBSERVABILITY_ROLLUP_MAX_DATES = 90
# PHASE-14A B8 (#726). The gateway error seam buffers captured server errors in a
# bounded in-process deque and the worker drains it on an interval, so two numbers
# describe the capture path rather than living as constants inside it.
# ``ERROR_CAPTURE_MAX_RECORDS`` is the buffer ceiling: a thousand records ride out
# a drain interval through a spike, and a storm past that DISCARDS the oldest
# rather than growing - an unbounded buffer turns an error storm into an
# out-of-memory kill, which is worse than the outage it was recording. It is
# declared HERE and imported by ``observability.error_capture``, the other way
# round from every other default: the buffer needs a ceiling before any
# composition root has run to configure one, and ``app.config`` may not import the
# ``observability`` package - its ``__init__`` reaches back into this module for
# ``APP_VERSION``, so the dependency runs config -> capture and never the reverse
# (coding-standards §9.2).
# ``ERROR_DRAIN_INTERVAL_SECONDS`` is how often the drain fires; a short interval
# keeps the operator's feed close to live without a write per request.
DEFAULT_ERROR_CAPTURE_MAX_RECORDS = 1000
DEFAULT_ERROR_DRAIN_INTERVAL_SECONDS = 30
# PHASE-14A B9 (#727). The gateway counts every answered request into a per-minute
# bucket in process, and the worker folds those buckets into one row per route per
# minute - so two numbers describe the counter rather than living as constants
# inside it.
# ``HTTP_COUNTER_MAX_SERIES`` is the ceiling on how many DISTINCT
# ``(minute, route template, method, status class)`` buckets may be waiting for a
# drain at once. It is not a request ceiling: a thousand requests to one route in
# one minute are ONE series, which is the whole point of the design (#717
# decision 15). A few thousand series is a few hundred routes' worth of a couple
# of minutes' traffic - far more than the drain interval ever lets accumulate -
# and past it the OLDEST minute is discarded and counted rather than the map
# growing, because an unbounded map turns a traffic spike into an out-of-memory
# kill, the same argument the error buffer is bounded on. Declared HERE, and
# imported by ``observability.http_counter`` rather than restated, for the same
# dependency reason as ``ERROR_CAPTURE_MAX_RECORDS`` above: ``app.config`` may not
# import the ``observability`` package (its ``__init__`` reaches back here for
# ``APP_VERSION``), so the dependency runs config -> counter and never the reverse.
# ``HTTP_COUNTER_DRAIN_INTERVAL_SECONDS`` is how often the fold runs. The grain is
# a minute, so a cadence at or above that is what bounds the write cost at one
# row per route per minute; draining faster cannot add information and draining
# slower leaves the operator's "recent past" stale.
DEFAULT_HTTP_COUNTER_MAX_SERIES = 5000
DEFAULT_HTTP_COUNTER_DRAIN_INTERVAL_SECONDS = 60
# MOD-013's ALERT THRESHOLDS (Batch 3, #717; plan-phase14 §11). Every one of
# these is a LIMIT a deployment may have to move - a bigger budget, a busier
# queue, a stricter provider - so each is configuration (coding-standards §9.1)
# rather than a constant buried in the rule that reads it. The four values that
# are deliberately NOT here are the ones a decision record pins: the seven-day
# cost baseline (ADR-0027 D8), the 1% error-rate objective, the 100-request
# floor and the 30 s AI latency objective (ADR-0030 D1, D3). A pinned
# objective is a promise, not a knob, and §9.2 is explicit that only an
# ADR-pinned threshold may stay a constant.
DEFAULT_OBSERVABILITY_BUDGET_ALERT_THRESHOLD_PCT = 80
DEFAULT_OBSERVABILITY_BREAKER_OPEN_SUCCESS_RATE = Decimal("0.5")
DEFAULT_OBSERVABILITY_PROVIDER_HEALTH_DROP_THRESHOLD = Decimal("0.2")
DEFAULT_OBSERVABILITY_OUTBOX_BACKLOG_THRESHOLD = 500
DEFAULT_OBSERVABILITY_QUEUE_AGE_THRESHOLD_SECONDS = 900
# ADR-0027 D8 asks for "a CONFIGURED multiple" of the actor's own trailing
# average, so this one was always meant to be an environment edit.
DEFAULT_OBSERVABILITY_COST_OUTLIER_MULTIPLE = Decimal("3")
DEFAULT_OBSERVABILITY_COST_OUTLIER_MIN_BASELINE_DAYS = 3
DEFAULT_OBSERVABILITY_PROVIDER_RATE_LIMIT_ALERT_COUNT = 1
# Security detector (PHASE-14B Batch 2, #779): a worker scan over the recent
# ``observability_security_signals`` rows. Off until a deployment opts in, like
# every other new safety behavior in this batch. The window bounds how much
# history one pass counts; the cooldown stops a cleared-then-recurring condition
# from raising a second alert immediately; each threshold is the count within the
# window that raises that signal kind's alert. Every value is a limit an operator
# may need to tune, so every value is configuration (coding-standards §9.1).
DEFAULT_SECURITY_DETECTION_ENABLED = False
DEFAULT_SECURITY_DETECTOR_WINDOW_MINUTES = 15
DEFAULT_SECURITY_DETECTOR_COOLDOWN_SECONDS = 1800
DEFAULT_SECURITY_DETECTOR_AUTH_FAILURE_THRESHOLD = 20
DEFAULT_SECURITY_DETECTOR_OPERATOR_MFA_FAILURE_THRESHOLD = 5
DEFAULT_SECURITY_DETECTOR_RECORD_DENIAL_THRESHOLD = 10
DEFAULT_SECURITY_DETECTOR_RATE_LIMIT_THRESHOLD = 50
DEFAULT_SECURITY_DETECTOR_PROMPT_INJECTION_THRESHOLD = 10
# Prompt-injection heuristics (PHASE-14B Batch 2, #780): advisory text checks on
# the transcript immediately before it leaves for the structuring provider. Off
# until a deployment opts in, like every other new safety behavior in this
# batch; a finding is recorded and the pipeline proceeds.
DEFAULT_PROMPT_INJECTION_HEURISTICS_ENABLED = False
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
    # MOD-014 (PHASE-14B Batch 2, #771): the operator effective-settings read
    # caches resolved values in-process for this many seconds so a polling
    # operator surface does not re-query ``ops_settings`` on every call. Reflects
    # the "effective values cached for 30s" contract; positive integer.
    settings_cache_ttl_seconds: int = 30
    # CSP report-only (PHASE-14B Batch 2, #775): hardened CSP on API responses and
    # report-only CSP on the frontend. The report URI points to the backend collector
    # endpoint. When unset, reporting directives are omitted.
    csp_report_only_enabled: bool = DEFAULT_CSP_REPORT_ONLY_ENABLED
    csp_report_uri: str = DEFAULT_CSP_REPORT_URI
    # CSP report collector (PHASE-14B Batch 2, #776): public, rate-limited endpoint
    # accepting both legacy (report-uri) and modern (report-to) CSP report formats.
    csp_collector_max_report_bytes: int = DEFAULT_CSP_COLLECTOR_MAX_REPORT_BYTES
    csp_collector_max_directive_length: int = DEFAULT_CSP_COLLECTOR_MAX_DIRECTIVE_LENGTH
    csp_collector_max_disposition_length: int = DEFAULT_CSP_COLLECTOR_MAX_DISPOSITION_LENGTH
    csp_collector_max_blocked_source_length: int = DEFAULT_CSP_COLLECTOR_MAX_BLOCKED_SOURCE_LENGTH
    csp_collector_max_document_uri_length: int = DEFAULT_CSP_COLLECTOR_MAX_DOCUMENT_URI_LENGTH
    csp_collector_rate_limit_max_requests: int = DEFAULT_CSP_COLLECTOR_RATE_LIMIT_MAX_REQUESTS
    csp_collector_rate_limit_window_seconds: int = DEFAULT_CSP_COLLECTOR_RATE_LIMIT_WINDOW_SECONDS
    csp_collector_max_buckets: int = DEFAULT_CSP_COLLECTOR_MAX_BUCKETS
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
    # Encrypted profile-photo media store (#529, ADR-0020, #532): the concrete
    # backend is selected by ``profile_media_backend`` - ``local`` (default,
    # dev/CI/tests) files encrypted photos under a repo-local ``var/`` dir,
    # ``supabase`` (production) stores the same ciphertext in the private
    # ``profile-media`` Supabase Storage bucket. The AES key ``profile_media_key``
    # is empty unless supplied by the environment (the store derives an ephemeral
    # dev key, never committed). ``__post_init__`` requires BOTH ``supabase_url``
    # and ``supabase_service_role_key`` when the backend is ``supabase``
    # (fail-fast boot, the same shared env pair as the intake store).
    profile_media_root: str = DEFAULT_PROFILE_MEDIA_ROOT
    profile_media_key: str = ""
    profile_media_backend: str = DEFAULT_PROFILE_MEDIA_BACKEND
    profile_media_max_attempts: int = DEFAULT_PROFILE_MEDIA_MAX_ATTEMPTS
    profile_media_backoff_seconds: float = DEFAULT_PROFILE_MEDIA_BACKOFF_SECONDS
    profile_media_jitter_fraction: float = DEFAULT_PROFILE_MEDIA_JITTER_FRACTION
    profile_media_circuit_breaker_threshold: int = DEFAULT_PROFILE_MEDIA_CIRCUIT_BREAKER_THRESHOLD
    profile_media_circuit_breaker_cooldown_seconds: float = (
        DEFAULT_PROFILE_MEDIA_CIRCUIT_BREAKER_COOLDOWN_SECONDS
    )
    profile_media_timeout_seconds: float = DEFAULT_PROFILE_MEDIA_TIMEOUT_SECONDS
    profile_media_max_upload_bytes: int = DEFAULT_PROFILE_MEDIA_MAX_UPLOAD_BYTES
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
    # Consecutive wrong operator TOTP codes before login locks, and how long
    # the lock lasts (PHASE-14B T17, #778). The defaults live in
    # ``modules.iam.domain.mfa_lockout`` so the policy and the environment share
    # one source; override with ``IAM_OPERATOR_MFA_LOCKOUT_THRESHOLD`` /
    # ``IAM_OPERATOR_MFA_LOCKOUT_SECONDS`` (listed in ``.env.example``).
    iam_operator_mfa_lockout_threshold: int = DEFAULT_OPERATOR_MFA_LOCKOUT_THRESHOLD
    iam_operator_mfa_lockout_seconds: int = DEFAULT_OPERATOR_MFA_LOCKOUT_SECONDS
    # Langfuse AI observability (plan-phase7-tracing-prep): the SDK keys for LLM
    # call tracing, consumed by the AI gateway port from Phase 7 onward. Both
    # empty by default = tracing disabled, the app boots cleanly without an
    # account. ``__post_init__`` enforces both set or both empty.
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = DEFAULT_LANGFUSE_HOST
    langfuse_timeout_seconds: float = DEFAULT_LANGFUSE_TIMEOUT_SECONDS
    # EXT-002 LLM/AI gateway (PHASE-7 T05, #348): provider selection is a config
    # knob (mock is the fail-closed default); the real provider key/base URL/
    # model. ``__post_init__`` refuses a real provider in dev/test unless demo
    # mode forces the mock or ``ai_allow_dev_provider`` overrides the gate, and
    # refuses a real provider under demo_mode unless ``ai_allow_demo_provider``
    # opts in (T14, #414), mirroring the SMS/WhatsApp fail-closed posture.
    ai_provider: str = DEFAULT_AI_PROVIDER
    ai_model: str = DEFAULT_AI_MODEL
    ai_asr_model: str = DEFAULT_AI_ASR_MODEL
    ai_allow_dev_provider: bool = DEFAULT_AI_ALLOW_DEV_PROVIDER
    ai_allow_demo_provider: bool = DEFAULT_AI_ALLOW_DEMO_PROVIDER
    ai_api_key: str = ""
    ai_base_url: str = ""
    ai_timeout_seconds: float = DEFAULT_AI_TIMEOUT_SECONDS
    ai_max_retries: int = DEFAULT_AI_MAX_RETRIES
    ai_circuit_breaker_threshold: int = DEFAULT_AI_CIRCUIT_BREAKER_THRESHOLD
    ai_circuit_breaker_cooldown_seconds: float = DEFAULT_AI_CIRCUIT_BREAKER_COOLDOWN_SECONDS
    ai_monthly_budget_paise: int = DEFAULT_AI_MONTHLY_BUDGET_PAISE
    # Per-model pricing table (PHASE-14A B1, #699): ``model:price_in:price_out``
    # entries in paise per token, parsed by :func:`parse_ai_pricing_table`. The
    # default prices the free mock at 0; a paid deployment sets its serving
    # model's rate here or in the environment.
    ai_pricing_table: str = DEFAULT_AI_PRICING_TABLE
    ai_fallback_provider: str = DEFAULT_AI_FALLBACK_PROVIDER
    ai_fallback_base_url: str = DEFAULT_AI_FALLBACK_BASE_URL
    ai_fallback_api_key: str = DEFAULT_AI_FALLBACK_API_KEY
    ai_fallback_model: str = DEFAULT_AI_FALLBACK_MODEL
    # Observability gates (PHASE-14A A5, #693; plan-phase14 §4): all additive
    # and disabled by default, so boot and tests are unchanged until a gate is
    # set. ``log_format`` selects the structlog renderer (A1); ``sentry_*``
    # gates error tracking (A4); ``otel_*`` gate the OTLP exporter, headers and
    # parent-based sampler ratio (A3); ``otel_service_version`` is the git-SHA
    # source shared by A3 and A4; ``metrics_enabled`` gates the optional
    # Prometheus ``/metrics`` surface (A3); ``observability_enabled`` is the
    # MOD-013 aggregate-consumer gate (B-tickets, plan-phase14 §4), reserved for
    # a future opt-in - it is not yet read at runtime, because the composition
    # root registers every module's handlers unconditionally
    # (worker/main.py ``_MODULE_REGISTERS``); ``grafana_url`` is the browsable
    # Grafana base the operator ``/deeplinks`` read links out to (C1b #707).
    log_format: str = DEFAULT_LOG_FORMAT
    sentry_dsn: str = ""
    sentry_traces_sample_rate: float = DEFAULT_SENTRY_TRACES_SAMPLE_RATE
    otel_enabled: bool = False
    otel_exporter_otlp_endpoint: str = ""
    otel_exporter_otlp_headers: tuple[str, ...] = ()
    otel_traces_sampler_ratio: float = DEFAULT_OTEL_TRACES_SAMPLER_RATIO
    otel_service_version: str = ""
    metrics_enabled: bool = False
    observability_enabled: bool = False
    # Browsable Grafana base URL (C1b #707): the Grafana Cloud stack the OTLP
    # endpoint above exports into. NOT derived from
    # ``otel_exporter_otlp_endpoint`` - that host is an ingest endpoint, not
    # something an operator can open - and empty by default, so an unconfigured
    # deployment answers the ``/deeplinks`` read with an absent link.
    grafana_url: str = ""
    # Ceiling on the dates one nightly rollup invocation may cover (B5b #705,
    # `worker/rollup.py`). A first-run backfill of a long history, or a catch-up
    # after a long outage, is trimmed to the OLDEST `max_dates` days and the rest
    # is picked up by the next invocation, so no single pass is unbounded while
    # nothing is skipped. A limit, so configuration (coding-standards §9.1), not a
    # constant.
    observability_rollup_max_dates: int = DEFAULT_OBSERVABILITY_ROLLUP_MAX_DATES
    # The gateway error-capture seam's own gate (B8 #726, gated #753): off (the
    # default) means no server error is captured at all - the catch-all seam and
    # the gateway middleware answer exactly as they would without the feature,
    # and the worker skips the error-buffer drain job. On, the seam is armed and
    # the ceiling below applies.
    error_capture_enabled: bool = False
    # Ceiling on the in-process error-capture buffer (B8 #726). The gateway error
    # seam appends one record per server error and the worker drains the buffer on
    # ``error_drain_interval_seconds``; a full buffer DISCARDS its oldest record, so
    # this is the point past which the error stream becomes incomplete rather than
    # the point past which the process becomes unsafe. A limit, so configuration
    # (coding-standards §9.1), not a constant.
    error_capture_max_records: int = DEFAULT_ERROR_CAPTURE_MAX_RECORDS
    # How often the worker drains the error buffer, in seconds. Bounded below only
    # by "must be positive": a zero interval is a busy loop against the database.
    error_drain_interval_seconds: int = DEFAULT_ERROR_DRAIN_INTERVAL_SECONDS
    # Ceiling on the in-process per-minute HTTP counter (B9 #727). Every answered
    # request increments one ``(minute, route, method, status class)`` bucket and
    # the worker folds them into ``observability_http_minute`` on
    # ``http_counter_drain_interval_seconds``; at the ceiling the OLDEST minute is
    # discarded and counted, so this is the point past which throughput for the
    # dropped minutes is missing rather than the point past which the process
    # becomes unsafe. A limit, so configuration (coding-standards §9.1).
    http_counter_max_series: int = DEFAULT_HTTP_COUNTER_MAX_SERIES
    # The per-minute HTTP counter's own gate (B9 #727, gated #753): off (the
    # default) means no request is counted at all - the gateway middleware is not
    # installed, the seam counts nothing, and the worker skips the fold job. On,
    # the counter is armed and the ceiling above applies. Off by default, like
    # every gate in this block: a deployment opts in per feature, and the inert
    # path is proven by the CI gate job so it cannot rot.
    http_counter_enabled: bool = False
    # How often the worker folds the per-minute counter into the observability
    # schema, in seconds. Bounded below only by "must be positive": a zero
    # interval is a busy loop against the database.
    http_counter_drain_interval_seconds: int = DEFAULT_HTTP_COUNTER_DRAIN_INTERVAL_SECONDS
    # MOD-013's alert thresholds: the LIMITS each rollup rule compares against.
    # They are configuration rather than constants in the rule that reads them
    # (coding-standards §9.1), so a deployment moves a threshold by an
    # environment edit and never by a code change. The defaults are the values
    # plan-phase14 §11 names.
    observability_budget_alert_threshold_pct: int = DEFAULT_OBSERVABILITY_BUDGET_ALERT_THRESHOLD_PCT
    observability_breaker_open_success_rate: Decimal = (
        DEFAULT_OBSERVABILITY_BREAKER_OPEN_SUCCESS_RATE
    )
    observability_provider_health_drop_threshold: Decimal = (
        DEFAULT_OBSERVABILITY_PROVIDER_HEALTH_DROP_THRESHOLD
    )
    observability_outbox_backlog_threshold: int = DEFAULT_OBSERVABILITY_OUTBOX_BACKLOG_THRESHOLD
    observability_queue_age_threshold_seconds: int = (
        DEFAULT_OBSERVABILITY_QUEUE_AGE_THRESHOLD_SECONDS
    )
    observability_cost_outlier_multiple: Decimal = DEFAULT_OBSERVABILITY_COST_OUTLIER_MULTIPLE
    observability_cost_outlier_min_baseline_days: int = (
        DEFAULT_OBSERVABILITY_COST_OUTLIER_MIN_BASELINE_DAYS
    )
    observability_provider_rate_limit_alert_count: int = (
        DEFAULT_OBSERVABILITY_PROVIDER_RATE_LIMIT_ALERT_COUNT
    )
    # Security detector (PHASE-14B Batch 2, #779): the scan gate and its
    # thresholds. Off by default so deploying this batch changes no behavior
    # until the operator opts in.
    security_detection_enabled: bool = DEFAULT_SECURITY_DETECTION_ENABLED
    security_detector_window_minutes: int = DEFAULT_SECURITY_DETECTOR_WINDOW_MINUTES
    security_detector_cooldown_seconds: int = DEFAULT_SECURITY_DETECTOR_COOLDOWN_SECONDS
    security_detector_auth_failure_threshold: int = DEFAULT_SECURITY_DETECTOR_AUTH_FAILURE_THRESHOLD
    security_detector_operator_mfa_failure_threshold: int = (
        DEFAULT_SECURITY_DETECTOR_OPERATOR_MFA_FAILURE_THRESHOLD
    )
    security_detector_record_denial_threshold: int = (
        DEFAULT_SECURITY_DETECTOR_RECORD_DENIAL_THRESHOLD
    )
    security_detector_rate_limit_threshold: int = DEFAULT_SECURITY_DETECTOR_RATE_LIMIT_THRESHOLD
    security_detector_prompt_injection_threshold: int = (
        DEFAULT_SECURITY_DETECTOR_PROMPT_INJECTION_THRESHOLD
    )
    # The producer-side half of the prompt-injection visibility (#780): when on,
    # the intake pipeline screens the transcript before the structuring egress
    # and emits a PHI-free finding. Off by default; the detector threshold above
    # only governs the alert scan over whatever signals arrive.
    prompt_injection_heuristics_enabled: bool = DEFAULT_PROMPT_INJECTION_HEURISTICS_ENABLED
    # Batch-3 observability feature gates (#753): additive and disabled by
    # default, one gate per feature that shipped in this batch, so a deployment
    # opts in per feature and local dev / tests / CI run without them. The A5
    # gate block above is untouched: ``observability_enabled`` stays reserved.
    # ``evaluation_enabled`` runs the #751 code-evaluator batch as part of the
    # daily Langfuse pull (``worker/langfuse_metrics.py``); with it off the
    # pull still runs and only the evaluators are skipped. ``annotation_queue_enabled``
    # feeds the #752 doctor-review annotation queue from review-outcome events;
    # with it off the outcome seats still record their funnel/business effects
    # and only the annotation write is skipped (``modules.observability.adapters``).
    evaluation_enabled: bool = False
    annotation_queue_enabled: bool = False

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
        if self.demo_mode and ai_provider != "mock" and not self.ai_allow_demo_provider:
            raise ValueError(
                "demo_mode=True requires ai_provider='mock' unless "
                "AI_ALLOW_DEMO_PROVIDER=true (fail-closed): the demo flag requires "
                "AI_ALLOW_DEMO_PROVIDER to ride a real EXT-002 provider"
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
        if self.settings_cache_ttl_seconds <= 0:
            raise ValueError("settings_cache_ttl_seconds must be positive")
        if self.observability_rollup_max_dates <= 0:
            raise ValueError("observability_rollup_max_dates must be positive")
        if self.error_capture_max_records <= 0:
            raise ValueError("error_capture_max_records must be positive")
        if self.error_drain_interval_seconds <= 0:
            raise ValueError("error_drain_interval_seconds must be positive")
        if self.http_counter_max_series <= 0:
            raise ValueError("http_counter_max_series must be positive")
        if self.http_counter_drain_interval_seconds <= 0:
            raise ValueError("http_counter_drain_interval_seconds must be positive")
        if not 0 < self.observability_budget_alert_threshold_pct <= 100:
            # A percentage outside 0-100 is not a percentage: at zero the alert
            # would fire on every day the platform spends anything, and above
            # 100 it could never fire at all.
            raise ValueError("observability_budget_alert_threshold_pct must be in (0, 100]")
        if not 0 < self.observability_breaker_open_success_rate <= 1:
            raise ValueError("observability_breaker_open_success_rate must be in (0, 1]")
        if not 0 < self.observability_provider_health_drop_threshold < 1:
            # A drop of a whole success rate is not a drop; a threshold of zero
            # would fire on any movement at all.
            raise ValueError("observability_provider_health_drop_threshold must be in (0, 1)")
        if self.observability_outbox_backlog_threshold <= 0:
            raise ValueError("observability_outbox_backlog_threshold must be positive")
        if self.observability_queue_age_threshold_seconds <= 0:
            raise ValueError("observability_queue_age_threshold_seconds must be positive")
        if self.observability_cost_outlier_multiple <= 1:
            # A multiple of one or less fires on every day merely ABOVE the
            # actor's own average, which is what half of any week looks like.
            raise ValueError("observability_cost_outlier_multiple must be greater than 1")
        if self.observability_cost_outlier_min_baseline_days <= 0:
            raise ValueError("observability_cost_outlier_min_baseline_days must be positive")
        if self.observability_provider_rate_limit_alert_count <= 0:
            # Zero refusals is the ABSENCE of the condition, not a mild form of
            # it; a threshold of zero would make the alert permanent.
            raise ValueError("observability_provider_rate_limit_alert_count must be positive")
        if self.security_detector_window_minutes <= 0:
            raise ValueError("security_detector_window_minutes must be positive")
        if self.security_detector_cooldown_seconds <= 0:
            raise ValueError("security_detector_cooldown_seconds must be positive")
        for name, value in (
            (
                "security_detector_auth_failure_threshold",
                self.security_detector_auth_failure_threshold,
            ),
            (
                "security_detector_operator_mfa_failure_threshold",
                self.security_detector_operator_mfa_failure_threshold,
            ),
            (
                "security_detector_record_denial_threshold",
                self.security_detector_record_denial_threshold,
            ),
            (
                "security_detector_rate_limit_threshold",
                self.security_detector_rate_limit_threshold,
            ),
            (
                "security_detector_prompt_injection_threshold",
                self.security_detector_prompt_injection_threshold,
            ),
        ):
            if value <= 0:
                raise ValueError(f"{name} must be positive")
        parse_ai_pricing_table(self.ai_pricing_table)
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
        if self.iam_operator_mfa_lockout_threshold < 1:
            raise ValueError("iam_operator_mfa_lockout_threshold must be at least 1")
        if self.iam_operator_mfa_lockout_seconds <= 0:
            raise ValueError("iam_operator_mfa_lockout_seconds must be positive")
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
        if not math.isfinite(self.langfuse_timeout_seconds) or self.langfuse_timeout_seconds <= 0:
            raise ValueError("langfuse_timeout_seconds must be finite and positive")
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
        profile_backend = self.profile_media_backend.strip().lower()
        if profile_backend not in {"local", "supabase"}:
            raise ValueError(
                f"unsupported profile_media_backend {self.profile_media_backend!r}; "
                "expected 'local' or 'supabase'"
            )
        if self.profile_media_max_attempts <= 0:
            raise ValueError("profile_media_max_attempts must be positive")
        if (
            not math.isfinite(self.profile_media_backoff_seconds)
            or self.profile_media_backoff_seconds <= 0
        ):
            raise ValueError("profile_media_backoff_seconds must be finite and positive")
        if (
            not math.isfinite(self.profile_media_jitter_fraction)
            or not 0 <= self.profile_media_jitter_fraction < 1
        ):
            raise ValueError(
                "profile_media_jitter_fraction must be finite and between "
                "0 inclusive and 1 exclusive"
            )
        if self.profile_media_circuit_breaker_threshold <= 0:
            raise ValueError("profile_media_circuit_breaker_threshold must be positive")
        if (
            not math.isfinite(self.profile_media_circuit_breaker_cooldown_seconds)
            or self.profile_media_circuit_breaker_cooldown_seconds <= 0
        ):
            raise ValueError(
                "profile_media_circuit_breaker_cooldown_seconds must be finite and positive"
            )
        if (
            not math.isfinite(self.profile_media_timeout_seconds)
            or self.profile_media_timeout_seconds <= 0
        ):
            raise ValueError("profile_media_timeout_seconds must be finite and positive")
        if self.profile_media_max_upload_bytes <= 0:
            raise ValueError("profile_media_max_upload_bytes must be positive")
        if profile_backend == "supabase":
            if not self.supabase_url.strip():
                raise ValueError(
                    "profile_media_backend='supabase' requires SUPABASE_URL from the environment"
                )
            if not self.supabase_service_role_key.strip():
                raise ValueError(
                    "profile_media_backend='supabase' requires "
                    "SUPABASE_SERVICE_ROLE_KEY from the environment"
                )
        log_format = self.log_format.strip().lower()
        if log_format not in {"console", "json"}:
            raise ValueError(
                f"unsupported log_format {self.log_format!r}; expected 'console' or 'json'"
            )
        if (
            not math.isfinite(self.sentry_traces_sample_rate)
            or not 0 <= self.sentry_traces_sample_rate <= 1
        ):
            raise ValueError(
                "sentry_traces_sample_rate must be finite and between 0 and 1 inclusive"
            )
        if self.sentry_traces_sample_rate > 0 and not self.sentry_dsn.strip():
            raise ValueError(
                "sentry_traces_sample_rate>0 requires SENTRY_DSN; refusing a sample "
                "rate with no Sentry DSN (fail-closed)."
            )
        if (
            not math.isfinite(self.otel_traces_sampler_ratio)
            or not 0 <= self.otel_traces_sampler_ratio <= 1
        ):
            raise ValueError(
                "otel_traces_sampler_ratio must be finite and between 0 and 1 inclusive"
            )
        if self.otel_enabled and not self.otel_exporter_otlp_endpoint.strip():
            raise ValueError(
                "otel_enabled=True requires OTEL_EXPORTER_OTLP_ENDPOINT from the "
                "environment (fail-closed)."
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


def _env_decimal(name: str, default: Decimal) -> Decimal:
    """Parse a decimal environment variable, falling back to ``default``.

    Decimal rather than float because the thresholds that use it are RATIOS
    compared for equality against a rolled figure: a float would carry a
    binary approximation into a comparison the operator reads as exact.
    """
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return Decimal(raw.strip())
    except InvalidOperation as exc:
        raise ValueError(f"{name} must be a decimal number; got {raw!r}") from exc


def _env_csv(name: str) -> tuple[str, ...]:
    """Parse a comma-separated environment variable into trimmed entries.

    Splits on commas, strips whitespace, and drops empties; an unset or empty
    value yields ``()`` so the caller's default posture is untouched.
    """
    raw = os.environ.get(name)
    if raw is None:
        return ()
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def parse_ai_pricing_table(raw: str) -> dict[str, tuple[Decimal, Decimal]]:
    """Parse an ``AI_PRICING_TABLE`` value into per-model paise-per-token rates.

    Format: comma-separated ``model:price_in:price_out`` entries, each price in
    paise per token as a decimal (sub-paise fractions are allowed). Empty
    entries are skipped; a malformed entry raises ``ValueError`` so a bad table
    fails closed at boot rather than silently pricing a model at 0.
    """
    table: dict[str, tuple[Decimal, Decimal]] = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        parts = [part.strip() for part in entry.split(":")]
        if len(parts) != 3 or not parts[0]:
            raise ValueError(
                f"malformed AI pricing entry {entry!r}; expected 'model:price_in:price_out'"
            )
        try:
            price_in = Decimal(parts[1])
            price_out = Decimal(parts[2])
        except InvalidOperation as exc:
            raise ValueError(
                f"malformed AI pricing entry {entry!r}; rates must be decimal paise-per-token"
            ) from exc
        if price_in < 0 or price_out < 0:
            raise ValueError(f"AI pricing rates must be non-negative: {entry!r}")
        table[parts[0]] = (price_in, price_out)
    return table


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
        settings_cache_ttl_seconds=_env_int("SETTINGS_CACHE_TTL_SECONDS", 30),
        partner_artifact_root=os.environ.get(
            "PARTNER_ARTIFACT_ROOT", DEFAULT_PARTNER_ARTIFACT_ROOT
        ),
        partner_artifact_key=os.environ.get("PARTNER_ARTIFACT_KEY", ""),
        intake_media_root=os.environ.get("INTAKE_MEDIA_ROOT", DEFAULT_INTAKE_MEDIA_ROOT),
        intake_media_key=os.environ.get("INTAKE_MEDIA_KEY", ""),
        intake_media_backend=os.environ.get("INTAKE_MEDIA_BACKEND", DEFAULT_INTAKE_MEDIA_BACKEND),
        supabase_url=os.environ.get("SUPABASE_URL", ""),
        supabase_service_role_key=os.environ.get("SUPABASE_SERVICE_ROLE_KEY", ""),
        profile_media_root=os.environ.get("PROFILE_MEDIA_ROOT", DEFAULT_PROFILE_MEDIA_ROOT),
        profile_media_key=os.environ.get("PROFILE_MEDIA_KEY", ""),
        profile_media_backend=os.environ.get(
            "PROFILE_MEDIA_BACKEND", DEFAULT_PROFILE_MEDIA_BACKEND
        ),
        profile_media_max_attempts=_env_int(
            "PROFILE_MEDIA_MAX_ATTEMPTS", DEFAULT_PROFILE_MEDIA_MAX_ATTEMPTS
        ),
        profile_media_backoff_seconds=_env_float(
            "PROFILE_MEDIA_BACKOFF_SECONDS", DEFAULT_PROFILE_MEDIA_BACKOFF_SECONDS
        ),
        profile_media_jitter_fraction=_env_float(
            "PROFILE_MEDIA_JITTER_FRACTION", DEFAULT_PROFILE_MEDIA_JITTER_FRACTION
        ),
        profile_media_circuit_breaker_threshold=_env_int(
            "PROFILE_MEDIA_CIRCUIT_BREAKER_THRESHOLD",
            DEFAULT_PROFILE_MEDIA_CIRCUIT_BREAKER_THRESHOLD,
        ),
        profile_media_circuit_breaker_cooldown_seconds=_env_float(
            "PROFILE_MEDIA_CIRCUIT_BREAKER_COOLDOWN_SECONDS",
            DEFAULT_PROFILE_MEDIA_CIRCUIT_BREAKER_COOLDOWN_SECONDS,
        ),
        profile_media_timeout_seconds=_env_float(
            "PROFILE_MEDIA_TIMEOUT_SECONDS", DEFAULT_PROFILE_MEDIA_TIMEOUT_SECONDS
        ),
        profile_media_max_upload_bytes=_env_int(
            "PROFILE_MEDIA_MAX_UPLOAD_BYTES", DEFAULT_PROFILE_MEDIA_MAX_UPLOAD_BYTES
        ),
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
        iam_operator_mfa_lockout_threshold=_env_int(
            "IAM_OPERATOR_MFA_LOCKOUT_THRESHOLD", DEFAULT_OPERATOR_MFA_LOCKOUT_THRESHOLD
        ),
        iam_operator_mfa_lockout_seconds=_env_int(
            "IAM_OPERATOR_MFA_LOCKOUT_SECONDS", DEFAULT_OPERATOR_MFA_LOCKOUT_SECONDS
        ),
        langfuse_public_key=os.environ.get("LANGFUSE_PUBLIC_KEY", ""),
        langfuse_secret_key=os.environ.get("LANGFUSE_SECRET_KEY", ""),
        langfuse_host=os.environ.get("LANGFUSE_HOST", DEFAULT_LANGFUSE_HOST),
        langfuse_timeout_seconds=_env_float(
            "LANGFUSE_TIMEOUT_SECONDS", DEFAULT_LANGFUSE_TIMEOUT_SECONDS
        ),
        ai_provider=os.environ.get("AI_PROVIDER", DEFAULT_AI_PROVIDER),
        ai_model=os.environ.get("AI_MODEL", DEFAULT_AI_MODEL),
        ai_asr_model=os.environ.get("AI_ASR_MODEL", DEFAULT_AI_ASR_MODEL),
        ai_allow_dev_provider=_env_bool("AI_ALLOW_DEV_PROVIDER", DEFAULT_AI_ALLOW_DEV_PROVIDER),
        ai_allow_demo_provider=_env_bool("AI_ALLOW_DEMO_PROVIDER", DEFAULT_AI_ALLOW_DEMO_PROVIDER),
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
        ai_pricing_table=os.environ.get("AI_PRICING_TABLE", DEFAULT_AI_PRICING_TABLE),
        ai_fallback_provider=os.environ.get("AI_FALLBACK_PROVIDER", DEFAULT_AI_FALLBACK_PROVIDER),
        ai_fallback_base_url=os.environ.get("AI_FALLBACK_BASE_URL", DEFAULT_AI_FALLBACK_BASE_URL),
        ai_fallback_api_key=os.environ.get("AI_FALLBACK_API_KEY", DEFAULT_AI_FALLBACK_API_KEY),
        ai_fallback_model=os.environ.get("AI_FALLBACK_MODEL", DEFAULT_AI_FALLBACK_MODEL),
        log_format=os.environ.get("LOG_FORMAT", DEFAULT_LOG_FORMAT),
        sentry_dsn=os.environ.get("SENTRY_DSN", ""),
        sentry_traces_sample_rate=_env_float(
            "SENTRY_TRACES_SAMPLE_RATE", DEFAULT_SENTRY_TRACES_SAMPLE_RATE
        ),
        otel_enabled=_env_bool("OTEL_ENABLED", False),
        otel_exporter_otlp_endpoint=os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", ""),
        otel_exporter_otlp_headers=_env_csv("OTEL_EXPORTER_OTLP_HEADERS"),
        otel_traces_sampler_ratio=_env_float(
            "OTEL_TRACES_SAMPLER_RATIO", DEFAULT_OTEL_TRACES_SAMPLER_RATIO
        ),
        otel_service_version=os.environ.get("OTEL_SERVICE_VERSION", ""),
        grafana_url=os.environ.get("GRAFANA_URL", ""),
        metrics_enabled=_env_bool("METRICS_ENABLED", False),
        observability_enabled=_env_bool("OBSERVABILITY_ENABLED", False),
        observability_rollup_max_dates=_env_int(
            "OBSERVABILITY_ROLLUP_MAX_DATES", DEFAULT_OBSERVABILITY_ROLLUP_MAX_DATES
        ),
        error_capture_enabled=_env_bool("ERROR_CAPTURE_ENABLED", False),
        error_capture_max_records=_env_int(
            "ERROR_CAPTURE_MAX_RECORDS", DEFAULT_ERROR_CAPTURE_MAX_RECORDS
        ),
        error_drain_interval_seconds=_env_int(
            "ERROR_DRAIN_INTERVAL_SECONDS", DEFAULT_ERROR_DRAIN_INTERVAL_SECONDS
        ),
        http_counter_enabled=_env_bool("HTTP_COUNTER_ENABLED", False),
        http_counter_max_series=_env_int(
            "HTTP_COUNTER_MAX_SERIES", DEFAULT_HTTP_COUNTER_MAX_SERIES
        ),
        http_counter_drain_interval_seconds=_env_int(
            "HTTP_COUNTER_DRAIN_INTERVAL_SECONDS", DEFAULT_HTTP_COUNTER_DRAIN_INTERVAL_SECONDS
        ),
        observability_budget_alert_threshold_pct=_env_int(
            "OBSERVABILITY_BUDGET_ALERT_THRESHOLD_PCT",
            DEFAULT_OBSERVABILITY_BUDGET_ALERT_THRESHOLD_PCT,
        ),
        observability_breaker_open_success_rate=_env_decimal(
            "OBSERVABILITY_BREAKER_OPEN_SUCCESS_RATE",
            DEFAULT_OBSERVABILITY_BREAKER_OPEN_SUCCESS_RATE,
        ),
        observability_provider_health_drop_threshold=_env_decimal(
            "OBSERVABILITY_PROVIDER_HEALTH_DROP_THRESHOLD",
            DEFAULT_OBSERVABILITY_PROVIDER_HEALTH_DROP_THRESHOLD,
        ),
        observability_outbox_backlog_threshold=_env_int(
            "OBSERVABILITY_OUTBOX_BACKLOG_THRESHOLD",
            DEFAULT_OBSERVABILITY_OUTBOX_BACKLOG_THRESHOLD,
        ),
        observability_queue_age_threshold_seconds=_env_int(
            "OBSERVABILITY_QUEUE_AGE_THRESHOLD_SECONDS",
            DEFAULT_OBSERVABILITY_QUEUE_AGE_THRESHOLD_SECONDS,
        ),
        observability_cost_outlier_multiple=_env_decimal(
            "OBSERVABILITY_COST_OUTLIER_MULTIPLE", DEFAULT_OBSERVABILITY_COST_OUTLIER_MULTIPLE
        ),
        observability_cost_outlier_min_baseline_days=_env_int(
            "OBSERVABILITY_COST_OUTLIER_MIN_BASELINE_DAYS",
            DEFAULT_OBSERVABILITY_COST_OUTLIER_MIN_BASELINE_DAYS,
        ),
        observability_provider_rate_limit_alert_count=_env_int(
            "OBSERVABILITY_PROVIDER_RATE_LIMIT_ALERT_COUNT",
            DEFAULT_OBSERVABILITY_PROVIDER_RATE_LIMIT_ALERT_COUNT,
        ),
        security_detection_enabled=_env_bool(
            "SECURITY_DETECTION_ENABLED", DEFAULT_SECURITY_DETECTION_ENABLED
        ),
        security_detector_window_minutes=_env_int(
            "SECURITY_DETECTOR_WINDOW_MINUTES", DEFAULT_SECURITY_DETECTOR_WINDOW_MINUTES
        ),
        security_detector_cooldown_seconds=_env_int(
            "SECURITY_DETECTOR_COOLDOWN_SECONDS", DEFAULT_SECURITY_DETECTOR_COOLDOWN_SECONDS
        ),
        security_detector_auth_failure_threshold=_env_int(
            "SECURITY_DETECTOR_AUTH_FAILURE_THRESHOLD",
            DEFAULT_SECURITY_DETECTOR_AUTH_FAILURE_THRESHOLD,
        ),
        security_detector_operator_mfa_failure_threshold=_env_int(
            "SECURITY_DETECTOR_OPERATOR_MFA_FAILURE_THRESHOLD",
            DEFAULT_SECURITY_DETECTOR_OPERATOR_MFA_FAILURE_THRESHOLD,
        ),
        security_detector_record_denial_threshold=_env_int(
            "SECURITY_DETECTOR_RECORD_DENIAL_THRESHOLD",
            DEFAULT_SECURITY_DETECTOR_RECORD_DENIAL_THRESHOLD,
        ),
        security_detector_rate_limit_threshold=_env_int(
            "SECURITY_DETECTOR_RATE_LIMIT_THRESHOLD",
            DEFAULT_SECURITY_DETECTOR_RATE_LIMIT_THRESHOLD,
        ),
        security_detector_prompt_injection_threshold=_env_int(
            "SECURITY_DETECTOR_PROMPT_INJECTION_THRESHOLD",
            DEFAULT_SECURITY_DETECTOR_PROMPT_INJECTION_THRESHOLD,
        ),
        prompt_injection_heuristics_enabled=_env_bool(
            "PROMPT_INJECTION_HEURISTICS_ENABLED", DEFAULT_PROMPT_INJECTION_HEURISTICS_ENABLED
        ),
        evaluation_enabled=_env_bool("EVALUATION_ENABLED", False),
        annotation_queue_enabled=_env_bool("ANNOTATION_QUEUE_ENABLED", False),
    )
