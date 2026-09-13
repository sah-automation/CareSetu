# Phase 7 AI Tracing Preparation Plan

**Status:** implemented (Pre-Phase 7 groundwork complete - 2026-09-07)
**Scope:** Minimal pre-Phase 7 groundwork so every AI phase (7, 8, 11, 13) is built with Langfuse tracing from day one.
**Depends on:** Phase 6 complete (current state). No schema changes, no code changes to existing modules.
**Estimated effort:** ~2-3 hours

## 1. Goal

Before building the AI pipeline in Phase 7 (`MOD-005` Intake & AI Orchestration), set up:

1. Langfuse Python SDK installed and importable
2. Langfuse configuration fields in the backend Settings
3. Langfuse client singleton (no-op when keys are absent)
4. Environment variable documentation for dev and prod
5. AI engineering standard updated with tracing conventions

This ensures every LLM call in Phases 7 (transcribe/structure), 8 (rx drafting), and future AI phases can use `@observe` decorators and structured tracing from the first line of AI code written.

## 2. What gets built

| #   | Deliverable                          | Where                                                                        | Depends On |
| --- | ------------------------------------ | ---------------------------------------------------------------------------- | ---------- |
| 2.1 | Langfuse Python SDK added to backend | `apps/backend/pyproject.toml`                                                | Nothing    |
| 2.2 | Langfuse config fields in Settings   | `apps/backend/app/config.py`                                                 | 2.1        |
| 2.3 | Langfuse client singleton            | `apps/backend/observability/langfuse_client.py` (new)                        | 2.2        |
| 2.4 | Environment variable docs            | `.env.example`, `render.yaml`                                                | 2.2        |
| 2.5 | AI engineering standard update       | `docs/standards/ai-engineering-standards.md`                                 | 2.1        |
| 2.6 | AI-gateway tracing pre-commit gate   | `apps/backend/scripts/check_ai_tracing.py` (new) + `.pre-commit-config.yaml` | 2.3        |

## 3. Detailed work items

### 3.1 Langfuse Python SDK

**What:** Add `langfuse>=2.0` to the backend dependency list.

**File:** `apps/backend/pyproject.toml`

Add to `[project] dependencies`:

```
# Langfuse SDK for AI observability: LLM call tracing, cost metering, and
# quality evaluation. Used by the AI gateway port (standard A6) from Phase 7
# onward. SDK is a no-op when LANGFUSE_PUBLIC_KEY is absent - never blocks boot.
"langfuse>=2.0",
```

**Note:** The project uses `uv` with `pyproject.toml`, not `requirements.txt`. After adding the dependency, run `uv lock` to update the lockfile.

### 3.2 Langfuse Config Fields

**What:** Add Langfuse environment variable fields to the `Settings` dataclass.

**File:** `apps/backend/app/config.py`

Add defaults (above the `Settings` class):

```python
DEFAULT_LANGFUSE_HOST = "https://us.cloud.langfuse.com"
```

Add fields to `Settings`:

```python
# Langfuse AI observability (plan-phase7-tracing-prep): SDK keys for LLM call
# tracing. Empty by default - when absent the Langfuse client is a no-op and
# no traces are emitted, so the app boots cleanly without an account. Keys go
# live when the Langfuse Cloud project is created (manual step, password mgr).
langfuse_public_key: str = ""
langfuse_secret_key: str = ""
langfuse_host: str = DEFAULT_LANGFUSE_HOST
```

Add to `get_settings()`:

```python
langfuse_public_key=os.environ.get("LANGFUSE_PUBLIC_KEY", ""),
langfuse_secret_key=os.environ.get("LANGFUSE_SECRET_KEY", ""),
langfuse_host=os.environ.get("LANGFUSE_HOST", DEFAULT_LANGFUSE_HOST),
```

Add validation in `__post_init__` - fail-closed if only one key is set:

```python
if bool(self.langfuse_public_key) != bool(self.langfuse_secret_key):
    raise ValueError(
        "LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY must both be set or both "
        "empty; refusing to initialise Langfuse with a partial key pair."
    )
```

### 3.3 Langfuse Client Singleton

**What:** Create a small module that exposes a Langfuse client (or `None` when keys are absent). Imported by the AI gateway when Phase 7 builds it.

**File:** `apps/backend/observability/__init__.py` (empty)
**File:** `apps/backend/observability/langfuse_client.py`

```python
"""Langfuse client singleton for AI observability (plan-phase7-tracing-prep).

Exposes :func:`get_langfuse_client` which returns a configured ``Langfuse``
instance or ``None`` when the SDK keys are absent.  The client is lazy
initialised once per process and never blocks boot when unconfigured.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langfuse import Langfuse

log = logging.getLogger(__name__)

_client: Langfuse | None = None
_initialised: bool = False


def get_langfuse_client(
    public_key: str,
    secret_key: str,
    host: str,
) -> Langfuse | None:
    """Return the singleton Langfuse client, creating it on first call.

    When ``public_key`` is empty the function returns ``None`` immediately -
    the app boots cleanly without Langfuse.  Subsequent calls return the
    cached instance.
    """
    global _client, _initialised

    if _initialised:
        return _client

    _initialised = True

    if not public_key:
        log.info("langfuse keys absent; AI tracing disabled")
        return None

    from langfuse import Langfuse  # deferred: only import when needed

    _client = Langfuse(
        public_key=public_key,
        secret_key=secret_key,
        host=host,
    )
    log.info("langfuse client initialised (host=%s)", host)
    return _client
```

**Why this shape:**

- Lazy import: `from langfuse import Langfuse` only runs when keys are present, so `langfuse` is an optional runtime dependency even though it is installed.
- No-op when unconfigured: the app boots cleanly in dev/CI without a Langfuse account.
- Process singleton: the Langfuse client batches traces and flushes on shutdown; one per process is correct.

**Usage (for Phase 7 reference):**

```python
from observability.langfuse_client import get_langfuse_client

langfuse = get_langfuse_client(
    public_key=settings.langfuse_public_key,
    secret_key=settings.langfuse_secret_key,
    host=settings.langfuse_host,
)
# langfuse is None when unconfigured; @observe is a no-op
```

### 3.4 Environment Variable Documentation

#### `.env.example` (append)

```
# Langfuse AI observability (plan-phase7-tracing-prep): LLM call tracing,
# cost metering, and quality evaluation. Both keys must be set together or
# both left empty (empty = tracing disabled, app boots normally).
#LANGFUSE_PUBLIC_KEY=sk-lf-...
#LANGFUSE_SECRET_KEY=sk-lf-...
#LANGFUSE_HOST=https://us.cloud.langfuse.com
```

#### `render.yaml` (append to envVars)

```yaml
# Langfuse AI observability: SDK keys for LLM call tracing. Set in the
# Render Dashboard during Langfuse account setup, never synced from repo.
# Both must be set together or left absent (absent = tracing disabled).
- key: LANGFUSE_PUBLIC_KEY
  sync: false
- key: LANGFUSE_SECRET_KEY
  sync: false
- key: LANGFUSE_HOST
  value: https://us.cloud.langfuse.com
```

### 3.5 AI Engineering Standard Update

**File:** `docs/standards/ai-engineering-standards.md`

Add new section after A6:

```markdown
### A7. Observability & Tracing

- Every LLM call flows through the AI gateway port and is traced via Langfuse SDK (`@observe` decorator from `observability.langfuse_client`).
- Trace captures: provider, model, task_type, input/output tokens, latency_ms, cost_paise, confidence score, status.
- **PHI is never sent to Langfuse** - only pseudonymous IDs and structured metadata (same boundary as `NFR-SEC-006`).
- Prompt versions are managed in Langfuse UI and deployed via API (extends A6 versioning).
- Quality evaluations run via Langfuse eval framework: confidence score distribution, doctor review outcomes.
- The Langfuse client is a no-op when `LANGFUSE_PUBLIC_KEY` is absent - tracing never blocks boot or the care loop.
- **Enforced by the `check-ai-tracing` pre-commit gate:** a concrete method on any `MOD-005` class named as the AI boundary (`*Gateway*`, `*Provider*`, `*LLM*`, `*AI*`) must reference `@observe` or the `langfuse` client, or the build fails. Abstract stubs and `_private` helpers are exempt.
```

### 3.6 AI-Gateway Tracing Gate

**What:** A repo-local pre-commit hook that makes the A7 rule a machine check, so Phase 7 code that skips Langfuse tracing fails lint.

**File:** `apps/backend/scripts/check_ai_tracing.py` (new, stdlib-only AST gate, mirrors `check_event_names.py`)
**Hook:** `.pre-commit-config.yaml` local hook `check-ai-tracing` (`pass_filenames: false`, `always_run: true`)
**Test:** `tests/unit/test_check_ai_tracing.py`

**Rule:** In `modules/intake/` only, a concrete method on a class whose name matches `gateway|provider|llm|\bai\b` must reference `@observe` or the `langfuse` client (`langfuse` / `get_langfuse_client`). Exempt: abstract stubs (`...`, `pass`, `raise NotImplementedError`), `_private` helpers, `@property`/`@staticmethod`, non-AI-boundary classes, non-`.py` files. Repo-wide invocation scans tracked intake files only.

**Why this shape:** A7 (via A6) mandates the gateway port as the single LLM chokepoint, so tracing one class per provider covers every call. Class-name detection keeps the scaffold tree clean today and bites the moment Phase 7 introduces a `*Gateway*`/`*Provider*` class.

## 4. What this plan does NOT cover

These items are correctly scoped to later phases and are NOT part of basic prep:

| Item                                        | Correct scope                        | Why deferred                                                        |
| ------------------------------------------- | ------------------------------------ | ------------------------------------------------------------------- |
| `observability` Supabase schema + migration | Phase 7 (when `ai_jobs` is built)    | No data to aggregate yet; schema would be empty                     |
| `@observe` decorators on AI gateway methods | Phase 7 (when gateway methods exist) | MOD-005 is a bare scaffold; methods don't exist yet                 |
| Nightly rollup cron job                     | Phase 7 or later                     | Nothing to aggregate until `ai_jobs` rows exist                     |
| `EXT-005` in system-context.md              | Post-Phase 14 or never               | Langfuse is an SDK dependency, not an external system with webhooks |
| Roadmap/module doc updates                  | Phase 7 (when scope is real)         | Premature until the pipeline exists                                 |
| Operator admin/non-admin split              | Post-Phase 14                        | Operator console feature                                            |
| Operator Settings/Observability tabs        | Post-Phase 14                        | UI features needing real data                                       |
| Langfuse evaluation suite                   | Post-Phase 14                        | Needs real traces to evaluate                                       |

## 5. Implementation order

| Step | What                                                                                                | Blocks | Estimated time |
| ---- | --------------------------------------------------------------------------------------------------- | ------ | -------------- |
| 1    | Add `langfuse>=2.0` to `pyproject.toml` + `uv lock`                                                 | 2      | 10 min         |
| 2    | Add Langfuse config fields to `config.py`                                                           | 3      | 20 min         |
| 3    | Create `observability/langfuse_client.py` singleton                                                 | 4, 5   | 20 min         |
| 4    | Update `.env.example` with Langfuse env vars                                                        | -      | 5 min          |
| 5    | Update `render.yaml` with Langfuse env vars                                                         | -      | 5 min          |
| 6    | Add section A7 to `ai-engineering-standards.md`                                                     | -      | 15 min         |
| 7    | Add `check-ai-tracing` pre-commit gate + tests                                                      | 8      | 60 min         |
| 8    | Verify: `npm run lint && npm run typecheck && npm run migration-check && npm run test:unit:backend` | -      | 15 min         |

**Total estimated time:** ~90 minutes

## 6. Verification checklist

- [ ] `langfuse>=2.0` added to `pyproject.toml` dependencies
- [ ] `uv lock` run successfully
- [ ] `langfuse_public_key`, `langfuse_secret_key`, `langfuse_host` fields in `Settings`
- [ ] `get_settings()` reads the three env vars
- [ ] `__post_init__` validates both keys present or both empty
- [ ] `observability/langfuse_client.py` exists with `get_langfuse_client()`
- [ ] Client returns `None` when keys are empty (no-op mode)
- [ ] Client returns `Langfuse` instance when keys are present
- [ ] `.env.example` documents the three env vars (commented out)
- [ ] `render.yaml` has the three env vars (sync: false for secrets)
- [ ] `docs/standards/ai-engineering-standards.md` has new section A7
- [ ] `apps/backend/scripts/check_ai_tracing.py` exists and passes `ruff` + strict mypy
- [ ] `check-ai-tracing` local hook in `.pre-commit-config.yaml` (`always_run: true`)
- [ ] `tests/unit/test_check_ai_tracing.py` covers: untraced gateway fails, `@observe` passes, client-ref passes, stub/private/property pass, non-gateway passes, repo clean, `main([])` fallback
- [ ] `npm run test:unit:backend` green (incl. new gate tests)
- [ ] `npm run lint` green (incl. `check-ai-tracing` hook)
- [ ] `npm run typecheck` green
- [ ] `npm run migration-check` green (no new migrations in this prep)

## 7. What Phase 7 inherits from this prep

When Phase 7 starts building `MOD-005`, it can immediately:

1. **Import the client:** `from observability.langfuse_client import get_langfuse_client`
2. **Use `@observe` decorators:** on gateway methods as they are written
3. **Record traces:** with provider, model, tokens, cost, latency, confidence
4. **Skip setup:** no SDK install, no config fields, no singleton to create

Phase 7 still builds:

- The AI gateway port methods (with `@observe` from day one)
- The `observability` schema migration (when `ai_jobs` is designed)
- The `intake` schema tables (`intakes`, `pre_summaries`, `ai_jobs`, `media_refs`)
- The nightly rollup cron (when there's data to aggregate)
- The `EXT-002` integration catalog entry in system-context.md
