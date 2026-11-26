# Brief - Phase 14: Production-Readiness Remediation (carry-forward)

**Ticket:** Phase 14 (not yet numbered) · **Parent:** PHASE-14-E2E-RELEASE · **Created:** 2026-09-08
**Reading surface:** ~15K tokens (budget 32K) - within budget

## Scope

Phase 14 is split into `PHASE-14A` (Observability & Monitoring Platform, pulled forward) and `PHASE-14B` (E2E + Release Readiness). This brief carries forward the **production-readiness remediation** recommendations from the deleted `docs/plans/production-readiness-audit.md`. They are now maintained in `docs/plans/plan-phase14-observability.md` **Appendix A** (and its Batch 1 / Batch 2 / PHASE-14B routing). When the Phase 14 work is planned into tickets, fold these items in and link Appendix A as the source of truth - do not re-derive them from history.

The recommendations split into two tracks:

- **Ship-now** (additive hardening - structlog, Sentry, `/metrics` + cache counters, CSP report-only, XSS sanitizer, SQLAlchemy pool sizing, backend Dockerfile). Safe to thread into any phase; low risk, no schema changes. Batch 1 carries structlog, Sentry, and metrics/cache counters; CSP + sanitizer route to Batch 2 (Security & Guardrails); pool sizing + Dockerfile route to `PHASE-14B`.
- **Later** (needs real traffic / a scaling decision - Redis-backed rate limiter, per-user/per-route rate limiting, Redis idempotency store, horizontal scaling runbook, business metrics dashboard). Defer to after launch or to the Batch 2 operator observability workstream.

## Read-list (in order)

1. `docs/plans/plan-phase14-observability.md` Appendix A (Carried-forward hardening) - the full carried-forward plan and prioritised table (~8K)
2. Same file §1-§13 (Batch 1 scope: foundation, AI/cost/quality, operator dashboard) - overlaps with the metrics/business-dashboard items (~7K)
3. `docs/roadmap/implementation-roadmap.md` §2.14 (Phase 14) - the release gate these items feed (~2K)
4. `docs/plans/plan-phase7-tracing-prep.md` - tracing groundwork that must not be duplicated (~3K)

## Do NOT read

- `docs/archive`
- backend or frontend source code (not needed for planning; revisit per-item when implementing)

## Baseline verify (must pass before the first edit)

- `git status` - tree is NOT clean (unrelated untracked briefs + prototype + modified .gitignore exist); your edits must be isolated to the Phase-14 tickets / roadmap / this plan.

## Done-verify (acceptance criteria → commands)

- Phase 14 ticket breakdown references `plan-phase14-observability.md` Appendix A for the remediation items.
- No item from the deleted audit file is silently lost (all present in §7.1 table or §7.4 "already covered elsewhere").
- `docs/plans/production-readiness-audit.md` is deleted and not re-created.

## Handoff notes

- The original `production-readiness-audit.md` was deleted on 2026-09-08; its content lives only in the plan file §7.2/§7.3/§7.4. Do not resurrect the old file.
- All ship-now items must remain feature-flagged and disabled by default until explicitly enabled for a launch environment.
- Respect ADR-0007 (split-origin Vercel+Render) before any CSP / session / middleware change.
- `security_posture.py` live gate should gain a companion check for the CSP + sanitizer additions.
