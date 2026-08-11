# AI Engineering Standards

**Scope:** Two audiences - (A) the **product's AI features** (LLM transcribe → structure → pre-summary, rx drafting) and (B) **agent-assisted development** of this codebase. Both optimized for scalability, production safety, cost (`NFR-001`), and context management.
**Upstream:** `MOD-005`, `FEAT-006/007/009`, `NFR-001`, `NFR-PERF-003`, `NFR-SEC-006`, `AMB-006`, `RISK-EVAL-006`.

---

## A. Product AI Features

### A1. Pipeline shape

- AI work is **async and never in the user-critical path**: capture ack `p95 < 2 s`; LLM call ≤ 30 s timeout (`NFR-PERF-003`).
- Pipeline: `transcribe → structure → pre-summary`; rx drafting is a separate, doctor-triggered call. Each step is a typed, idempotent outbox job.

### A2. Structured output (validate everything)

- Every LLM response is parsed into a Pydantic v2 model and **validated** - malformed output is a failed job, never a silent pass-through.
- Prompt contract is versioned alongside the schema; prompt changes are reviewed like code.
- Hindi + English are first-class; language selection is explicit in the request (`REQ-006`).

### A3. Confidence & the "never verified" rule

- Extraction confidence is computed and recorded; below the `AMB-006` threshold → `pre_summary.low_confidence` → **forced doctor review**.
- AI output is **never presented as verified**. The pre-summary is a draft for a licensed doctor; a prescription is never issued without doctor approval (`REQ-023`). This is the `CFL-002` baseline - a compliance decision, not a code shortcut.

### A4. Cost & budget metering

- Every AI call records provider, tokens, and ₹cost to `ai_jobs`; counters persist (`NFR-001`, `NFR-COST-001`).
- Hard monthly budget: when exhausted, AI degrades to its fallback (doctor-review) path - no overspend.
- Egress is **PHI-minimized and consent-gated** (`NFR-SEC-006`): only intake/prescription context leaves, never the full record; each egress is audited.

### A5. Degradation

- Timeout / failure / low confidence → degrade to doctor review. An LLM outage must never block the care loop (`NFR-PERF-003`). Every degradation is logged + audited + metered.

### A6. Advanced AI - gateway/router, fallback, caching, versioning

An abstract **AI gateway port** sits behind `MOD-005`. All LLM calls go through one typed interface; domain code never touches a concrete provider.

- **Routing & per-task model selection:** each task (transcribe / structure / draft) declares a model _tier_ (e.g. cheap-capable vs. strong). The gateway picks the cheapest model meeting the task's quality bar. Selection is config-driven.
- **Multi-provider fallback chains:** a task can list ordered fallback providers. On provider failure, budget cap, or timeout → try the next in the chain before degrading. Still bounded by the hard rule: never block the care loop (A5).
- **Cost-aware routing:** the gateway consults the budget meter and routes to the cheapest eligible provider; at budget exhaustion it degrades, never overspends (`NFR-001`).
- **Caching:** identical/near-identical prompts are served from cache (cache key = prompt version + normalized input). Invalidation on prompt or output-schema version change. Provider-level prompt caching may be used where supported - but never caches PHI outside consented, audited paths.
- **Versioning:** prompt contract and output schema are versioned together (A2). A model upgrade is a reviewed change gated by an A/B check against the previous model - never a silent swap in production.

---

## B. Agent-Assisted Development (how agents build here)

### B1. Cost & scale-aware choices

- Default to the cheapest correct option: Postgres over Redis where a SQL counter suffices; OSS over paid SaaS; reuse module facades over new services. Any choice that threatens `NFR-001` must be flagged, not silently absorbed.
- Design for the monolith-today / services-later seam: keep modules isolated so a future re-cut needs no redesign.

### B2. Context management

- Read before writing: `CONTEXT.md` (when present), the target module's spec in `internal-modules.md`, the feature's PRD section, and `docs/standards/*` before editing that area.
- Keep working sets small - match the roadmap's phase granularity; don't pull whole-file dumps when a section suffices.
- Reuse existing domain vocabulary and event names (whitebox §4.2); do not invent synonyms or new events without registering them.

### B3. Production-safe code

- Follow coding-standards (types, module isolation, state machines, tests per transition). A state change without its outbox event and its test is incomplete.
- Never silence errors to make a demo pass; if something is deliberately degraded, record the fallback path explicitly.
- No PHI in logs, comments, or test fixtures; use synthetic data.

### B4. Agent work conventions

- Verify with the repo's test/lint commands before declaring done (run the harness; don't assume).
- Reference files as `path:line` so review is fast.
- Surface open decisions (`CFL/GAP/AMB` ids) instead of silently resolving them; reopen an ADR if a change contradicts it (see `docs/agents/domain.md`).
