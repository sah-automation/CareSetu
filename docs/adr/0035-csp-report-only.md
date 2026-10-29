# ADR-0035: CSP report-only - Content-Security-Policy-Report-Only header with collector

**Status:** accepted
**Date:** 2026-10-29
**Decides:** That the platform adds a `Content-Security-Policy-Report-Only` header to API responses and the frontend, with `Reporting-Endpoints` and `report-uri` directives pointing to a public, rate-limited CSP report collector. The collector accepts both CSP report formats (legacy `csp-report` and modern `Reporting API`), normalizes the report, aggregates daily by directive/disposition/blocked-source/document-path, returns 204, and never stores raw reports. The reporting directives are omitted when the build-time collector URL is unset.
**Traceability:** `plan-phase14-observability.md` §10, §13, Appendix A; spec #761; parent #761; tickets #775, #776, #777, #782, #783. Related: `ADR-0007` (split-origin deployment), `ADR-0030` (SLOs), `ADR-0032` (webhook deferral), `internal-modules.md` §3.1 (MOD-001 gateway), §3.14 (MOD-013 observability).

## Context

The production-readiness audit (Appendix A of `plan-phase14-observability.md`) names CSP header (report-only first) as a High-priority item for Batch 2 (Security & Guardrails). The plan states: "CSP report-only -> Batch 2. `Content-Security-Policy-Report-Only` in `app/gateway/security_headers.py` behind `CSP_REPORT_ONLY`; enforce-mode flip verified against the deployed Vercel frontend (`ADR-0007`)." The frontend (Vercel) and API (Render) are split-origin, so CSP must be configured on both sides and the collector must be reachable from both.

## Decision

### D1 - Report-only first, enforced by config gate

- The API gateway adds `Content-Security-Policy-Report-Only` header via a new middleware in `app/gateway/security_headers.py`, gated by `CSP_REPORT_ONLY` environment variable (default unset = header omitted).
- The frontend (Next.js) adds the same header via `next.config.js` headers config, also gated by the same build-time variable.
- When `CSP_REPORT_ONLY` is set, the header includes:
  - A restrictive policy appropriate for the surface (API vs frontend)
  - `Reporting-Endpoints default="<COLLECTOR_URL>"` (modern Reporting API)
  - `report-uri <COLLECTOR_URL>` (legacy fallback)
- When `CSP_REPORT_ONLY` is unset, the header is omitted entirely (no report-only, no enforce). This allows local dev and CI to run without a collector.

### D2 - Public CSP report collector

A new public endpoint `POST /v1/csp-report` (no auth, rate-limited) in `MOD-001` (IAM gateway area) or a new minimal collector module:

- Accepts both CSP report formats:
  - Legacy: `Content-Type: application/csp-report` with JSON body `{ "csp-report": { ... } }`
  - Modern: `Content-Type: application/reports+json` with JSON body `[{ "type": "csp-violation", "body": { ... }, ... }]`
- Normalizes both into a common internal shape: directive, disposition (enforce/report), blocked-source (URI or `inline`/`eval`), document-path, referrer, script-sample (truncated).
- Aggregates daily in `MOD-013` `observability` schema (new table `observability_csp_violations_daily` or reuses `observability_business_daily` with metric_key prefix `csp.`) by directive, disposition, blocked-source, document-path.
- Returns 204 No Content immediately (no body).
- Rate-limited: 100 req/min per IP (Redis-backed, graceful degradation to in-memory if Redis unavailable).
- Request body capped at 16 KB (rejects larger with 413).
- **Never stores raw reports** - only the daily aggregates. Raw reports are processed in-memory and discarded.

### D3 - Collector URL configuration

- The collector URL is a build-time / deploy-time configuration (`CSP_REPORT_COLLECTOR_URL` in `Settings`).
- If unset, the `Reporting-Endpoints` and `report-uri` directives are omitted from the header (the policy is still sent but without reporting).
- The collector URL must be an absolute HTTPS URL. On the split-origin deployment (`ADR-0007`), the same collector URL is used for both Vercel (frontend) and Render (API) because the collector is a public endpoint on the API domain.

### D4 - Enforce-mode flip

- The report-only period is a validation window. Once violations are acceptably low (operator decision via the Security page in the operator console), the `Content-Security-Policy` (enforce) header replaces `Content-Security-Policy-Report-Only`.
- The enforce-mode flip is a separate config gate (`CSP_ENFORCE`), not automatic.
- The Security page (`/operator/observability/security`) shows live CSP violation aggregates from the collector, so the operator can decide when to flip.

### D5 - Integration with Security page and alerting

- Daily CSP violation aggregates feed the Security page in the operator console (#783).
- A `csp_violation_high` alert kind is added to `ALERT_KINDS` in `ops/domain/settings.py` and the rollup evaluates it against a threshold (e.g., violations per day > baseline).
- The alert feeds the `observability_alert_events` feed and the Security page.

## Considered options

- **Enforce mode from day one.** Rejected - would risk breaking the deployed frontend (Vercel) with inline scripts, styles, or third-party resources that the policy doesn't allow. Report-only validates first.
- **No collector, just log violations to console.** Rejected - browser console logs are not accessible to the operator. A collector with daily aggregates in the system of record (`MOD-013`) makes violations visible and actionable.
- **Store raw reports for debugging.** Rejected - raw reports can contain sensitive URLs, referrers, and script samples. The PHI/no-secrets rule (`NFR-SEC-006`) and the accepted-risk posture (`ADR-0031`) require that nothing sensitive leaves the platform boundary. Daily aggregates by directive/source/path are sufficient for remediation.
- **Separate collector per origin.** Rejected - the split-origin deployment means the frontend (Vercel) and API (Render) have different origins, but the collector is a single public endpoint on the API domain that both can post to. CORS is configured to allow the frontend origin.

## Consequences

- The API gateway and frontend gain a new security header when `CSP_REPORT_ONLY` is set.
- A new public endpoint `POST /v1/csp-report` is added (rate-limited, capped, no auth).
- Daily CSP violation aggregates are visible in the operator Security page.
- The enforce-mode flip is an operator decision, not automatic, and is verified against the deployed Vercel frontend.
- The `csp_violation_high` alert kind provides proactive notification of policy regressions.
