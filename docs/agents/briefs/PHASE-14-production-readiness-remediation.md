# Brief - Phase 14: Production-Readiness Remediation (carry-forward)

**Ticket:** Phase 14 (not yet numbered) · **Parent:** PHASE-14-E2E-RELEASE · **Created:** 2026-09-08
**Reading surface:** ~15K tokens (budget 32K) - within budget

## Scope

Phase 14 is the release-readiness gate ("End-to-End Integration, Observability & Release"). This brief carries forward the **production-readiness remediation** recommendations from the deleted `docs/plans/production-readiness-audit.md`. They are now maintained in `docs/plans/plan-post-phase14-observability.md` **section 7**. When Phase 14 is planned into tickets, fold these items in and link section 7 as the source of truth - do not re-derive them from history.

The recommendations split into two tracks:

- **Ship-now** (additive hardening - structlog, Sentry, `/metrics` + cache counters, CSP report-only, XSS sanitizer, SQLAlchemy pool sizing, backend Dockerfile). Safe to thread into any phase before or during Phase 14; low risk, no schema changes.
- **Later** (needs real traffic / a scaling decision - Redis-backed rate limiter, per-user/per-route rate limiting, Redis idempotency store, horizontal scaling runbook, business metrics dashboard). Defer to after launch or to the operator observability workstream (Workstream 1, same plan file, sections 1-6).

## Read-list (in order)

1. `docs/plans/plan-post-phase14-observability.md` §7 (Production-Readiness Audit Remediation) - the full carried-forward plan and prioritised table (~8K)
2. Same file §1-§6 (Workstream 1: operator admin/settings + observability dashboard) - overlaps with §7.2.3/7.3 (metrics, business dashboard) (~7K)
3. `docs/roadmap/implementation-roadmap.md` §2.14 (Phase 14) - the release gate these items feed (~2K)
4. `docs/plans/plan-phase7-tracing-prep.md` - tracing groundwork that must not be duplicated (~3K)

## Do NOT read

- `docs/archive`
- backend or frontend source code (not needed for planning; revisit per-item when implementing)

## Baseline verify (must pass before the first edit)

- `git status` - tree is NOT clean (unrelated untracked briefs + prototype + modified .gitignore exist); your edits must be isolated to the Phase-14 tickets / roadmap / this plan.

## Done-verify (acceptance criteria → commands)

- Phase 14 ticket breakdown references `plan-post-phase14-observability.md` §7 for the remediation items.
- No item from the deleted audit file is silently lost (all present in §7.1 table or §7.4 "already covered elsewhere").
- `docs/plans/production-readiness-audit.md` is deleted and not re-created.

## Handoff notes

- The original `production-readiness-audit.md` was deleted on 2026-09-08; its content lives only in the plan file §7.2/§7.3/§7.4. Do not resurrect the old file.
- All ship-now items must remain feature-flagged and disabled by default until explicitly enabled for a launch environment.
- Respect ADR-0007 (split-origin Vercel+Render) before any CSP / session / middleware change.
- `security_posture.py` live gate should gain a companion check for the CSP + sanitizer additions.
