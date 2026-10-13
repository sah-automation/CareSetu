// #708 C2a: the operator Observability read client (plan-phase14-observability
// §9.1/§9.2, PHASE-14A BATCH 1). Nine operator-only GETs over the MOD-013
// telemetry the nightly rollup writes: the headline overview, the AI bill, the
// usage/quality/latency breakdowns, dependency health, the alert feed and the
// outbound vendor links.
//
// The same thin `request` + `guardShape` seam as lib/operator/api.ts: every
// fetcher resolves the exact response model
// (modules/observability/facade.py - Overview, CostSummary, CostTrend,
// UsageReport, QualityReport, LatencyReport, SystemHealth, AlertPage,
// Deeplinks) and raises `ApiError` otherwise, so a page renders one error path
// for a network failure, a refused read and a body that drifted alike.
//
// Money is paise (api-standards §3) and percentages/percentiles are backend
// `Decimal`s, which FastAPI's encoder serializes as JSON numbers - never
// strings - so both arrive as plain `number`s here. A rate whose denominator is
// empty is `null`, which means "not yet measured" and never reads as zero.

import { guardShape, request } from "@/lib/request";

/** The observability read routes' shared prefix (plan §9.1). */
const OBSERVABILITY_BASE = "/v1/operator/observability";

/**
 * The alert statuses the feed can be filtered to. A typo is not a filter, so
 * the union closes the set rather than accepting any string.
 */
export type AlertStatus = "open" | "resolved";

/**
 * One registry-driven business event's count over the window. A metric with no
 * event in the window is ABSENT from the list rather than present as zero.
 */
export interface BusinessCountView {
  metric_key: string;
  count: number;
}

/**
 * The landing page's headline KPIs (facade.Overview): is the bill on plan, is
 * the AI working, is anything broken, and how stale the telemetry itself is.
 * The windowed figures cover `[from_date, to_date]`; spend and the alert counts
 * do not, because a budget is a billing-period figure and an alert stays open
 * until a later roll resolves it.
 */
export interface Overview {
  days: number;
  from_date: string;
  to_date: string;
  total_calls: number;
  success_count: number;
  success_rate: number | null;
  low_confidence_count: number;
  low_confidence_rate: number | null;
  p95_duration_ms: number | null;
  spend_paise: number;
  budget_paise: number;
  budget_utilization_pct: number;
  budget_exhausted: boolean;
  open_alerts: number;
  critical_open_alerts: number;
  open_breakers: number;
  business_counts: BusinessCountView[];
  last_rolled_date: string | null;
}

/** One `(provider, model)` budget scope: spend against the cap. */
export interface CostBudgetView {
  provider: string;
  model: string;
  monthly_limit_paise: number;
  alert_threshold_pct: number;
  current_spend_paise: number;
  billing_period_start: string | null;
  billing_period_end: string | null;
  remaining_paise: number;
  utilization_pct: number;
  exhausted: boolean;
}

/**
 * Spend across the current billing period, plus the per-scope breakdown. A
 * `null` period means nothing is budgeted yet - distinct from "spent nothing".
 */
export interface CostSummary {
  period_start: string | null;
  period_end: string | null;
  total_spend_paise: number;
  total_limit_paise: number;
  remaining_paise: number;
  utilization_pct: number;
  exhausted: boolean;
  budgets: CostBudgetView[];
}

/** One day of the cost series. A day with no AI job carries no point at all. */
export interface CostTrendPoint {
  usage_date: string;
  calls: number;
  cost_paise: number;
}

/** The daily cost series, oldest day first, over the requested window. */
export interface CostTrend {
  days: number;
  from_date: string;
  to_date: string;
  points: CostTrendPoint[];
}

/** One `(provider, model, task_type)` scope's usage over the window. */
export interface UsageRow {
  provider: string;
  model: string;
  task_type: string;
  calls: number;
  success_count: number;
  failure_count: number;
  timeout_count: number;
  input_tokens: number;
  output_tokens: number;
  cost_paise: number;
}

/** Calls and tokens by provider and task over the window, plus the totals. */
export interface UsageReport {
  days: number;
  from_date: string;
  to_date: string;
  total_calls: number;
  total_input_tokens: number;
  total_output_tokens: number;
  total_cost_paise: number;
  rows: UsageRow[];
}

/**
 * One provider's rolled-up health. A `null` success rate is a provider the
 * rollup has no traffic sample for, not one failing every call.
 */
export interface ProviderQualityRow {
  provider: string;
  sample_count: number;
  success_rate: number | null;
  breaker_state: string;
}

/** Output quality over the window, plus the per-provider breakdown. */
export interface QualityReport {
  days: number;
  from_date: string;
  to_date: string;
  total_calls: number;
  success_count: number;
  failure_count: number;
  timeout_count: number;
  low_confidence_count: number;
  success_rate: number | null;
  low_confidence_rate: number | null;
  providers: ProviderQualityRow[];
}

/**
 * One provider's rolled latency distribution. Percentiles are "as of the last
 * roll", which `window_start`/`window_end` state - the route takes no window
 * because these are snapshots, not re-derivable aggregates.
 */
export interface LatencyRow {
  provider: string;
  sample_count: number;
  p50_duration_ms: number | null;
  p95_duration_ms: number | null;
  p99_duration_ms: number | null;
  window_start: string | null;
  window_end: string | null;
}

/** Per-provider p50/p95/p99, plus how fresh those percentiles are. */
export interface LatencyReport {
  last_rolled_date: string | null;
  providers: LatencyRow[];
}

/**
 * One dependency's state as the read observed it: `up` means the read reached
 * it (or, for the cache, that the deployment has it configured), `disabled`
 * means it is switched off.
 */
export interface DependencyHealth {
  name: string;
  status: string;
  latency_ms: number | null;
  detail: string | null;
}

/** One outbox table's queue depth: pending, in flight, and terminally failed. */
export interface OutboxHealthRow {
  table_schema: string;
  table: string;
  pending: number;
  inflight: number;
  dead_letter: number;
  backlog: number;
}

/** One provider's circuit-breaker state. */
export interface BreakerHealthRow {
  provider: string;
  breaker_state: string;
}

/** Dependency reachability plus the outbox and circuit-breaker state. */
export interface SystemHealth {
  dependencies: DependencyHealth[];
  outbox: OutboxHealthRow[];
  outbox_backlog: number;
  dead_letter_rows: number;
  breakers: BreakerHealthRow[];
  open_breakers: number;
}

/**
 * One `observability_alert_events` row. `payload` is the PHI-free map the
 * producers wrote, passed through rather than reshaped.
 */
export interface AlertEntry {
  id: string;
  severity: string;
  kind: string;
  title: string;
  payload: Record<string, unknown>;
  status: string;
  created_at: string;
  acked_by: number | null;
  acked_at: string | null;
}

/**
 * One page of the feed, newest first, plus `total_count` over every matching
 * row - so a client can tell a full page from the end of the feed.
 */
export interface AlertPage {
  alerts: AlertEntry[];
  total_count: number;
}

/**
 * The outbound vendor links. Every key is independently nullable: a deployment
 * with Sentry but no Grafana answers with a Sentry link and an absent one.
 */
export interface Deeplinks {
  grafana: string | null;
  sentry: string | null;
  langfuse: string | null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * Key-presence check for an already-narrowed response object. A guard reads the
 * keys the page renders and nothing more: re-stating every value constraint
 * here would pin a wire format the backend is free to widen (a new nullable
 * field, a rate that starts arriving where it was `null`) and turn a harmless
 * addition into a broken console. What the guard owes the page is that the
 * value is an object carrying those keys; everything below then type-checks
 * against the declared model.
 */
function hasKeys(
  value: Record<string, unknown>,
  keys: readonly string[],
): boolean {
  return keys.every((key) => key in value);
}

function isArrayOf<T>(
  value: unknown,
  guard: (item: unknown) => item is T,
): boolean {
  return Array.isArray(value) && value.every(guard);
}

function isBusinessCountView(value: unknown): value is BusinessCountView {
  return isRecord(value) && hasKeys(value, ["metric_key", "count"]);
}

function isOverview(value: unknown): value is Overview {
  return (
    isRecord(value) &&
    hasKeys(value, [
      "days",
      "from_date",
      "to_date",
      "total_calls",
      "success_count",
      "success_rate",
      "low_confidence_count",
      "low_confidence_rate",
      "p95_duration_ms",
      "spend_paise",
      "budget_paise",
      "budget_utilization_pct",
      "budget_exhausted",
      "open_alerts",
      "critical_open_alerts",
      "open_breakers",
      "business_counts",
      "last_rolled_date",
    ]) &&
    isArrayOf(value.business_counts, isBusinessCountView)
  );
}

function isCostBudgetView(value: unknown): value is CostBudgetView {
  return (
    isRecord(value) &&
    hasKeys(value, [
      "provider",
      "model",
      "monthly_limit_paise",
      "alert_threshold_pct",
      "current_spend_paise",
      "billing_period_start",
      "billing_period_end",
      "remaining_paise",
      "utilization_pct",
      "exhausted",
    ])
  );
}

function isCostSummary(value: unknown): value is CostSummary {
  return (
    isRecord(value) &&
    hasKeys(value, [
      "period_start",
      "period_end",
      "total_spend_paise",
      "total_limit_paise",
      "remaining_paise",
      "utilization_pct",
      "exhausted",
      "budgets",
    ]) &&
    isArrayOf(value.budgets, isCostBudgetView)
  );
}

function isCostTrendPoint(value: unknown): value is CostTrendPoint {
  return (
    isRecord(value) && hasKeys(value, ["usage_date", "calls", "cost_paise"])
  );
}

function isCostTrend(value: unknown): value is CostTrend {
  return (
    isRecord(value) &&
    hasKeys(value, ["days", "from_date", "to_date", "points"]) &&
    isArrayOf(value.points, isCostTrendPoint)
  );
}

function isUsageRow(value: unknown): value is UsageRow {
  return (
    isRecord(value) &&
    hasKeys(value, [
      "provider",
      "model",
      "task_type",
      "calls",
      "success_count",
      "failure_count",
      "timeout_count",
      "input_tokens",
      "output_tokens",
      "cost_paise",
    ])
  );
}

function isUsageReport(value: unknown): value is UsageReport {
  return (
    isRecord(value) &&
    hasKeys(value, [
      "days",
      "from_date",
      "to_date",
      "total_calls",
      "total_input_tokens",
      "total_output_tokens",
      "total_cost_paise",
      "rows",
    ]) &&
    isArrayOf(value.rows, isUsageRow)
  );
}

function isProviderQualityRow(value: unknown): value is ProviderQualityRow {
  return (
    isRecord(value) &&
    hasKeys(value, [
      "provider",
      "sample_count",
      "success_rate",
      "breaker_state",
    ])
  );
}

function isQualityReport(value: unknown): value is QualityReport {
  return (
    isRecord(value) &&
    hasKeys(value, [
      "days",
      "from_date",
      "to_date",
      "total_calls",
      "success_count",
      "failure_count",
      "timeout_count",
      "low_confidence_count",
      "success_rate",
      "low_confidence_rate",
      "providers",
    ]) &&
    isArrayOf(value.providers, isProviderQualityRow)
  );
}

function isLatencyRow(value: unknown): value is LatencyRow {
  return (
    isRecord(value) &&
    hasKeys(value, [
      "provider",
      "sample_count",
      "p50_duration_ms",
      "p95_duration_ms",
      "p99_duration_ms",
      "window_start",
      "window_end",
    ])
  );
}

function isLatencyReport(value: unknown): value is LatencyReport {
  return (
    isRecord(value) &&
    hasKeys(value, ["last_rolled_date", "providers"]) &&
    isArrayOf(value.providers, isLatencyRow)
  );
}

function isDependencyHealth(value: unknown): value is DependencyHealth {
  return (
    isRecord(value) &&
    hasKeys(value, ["name", "status", "latency_ms", "detail"])
  );
}

function isOutboxHealthRow(value: unknown): value is OutboxHealthRow {
  return (
    isRecord(value) &&
    hasKeys(value, [
      "table_schema",
      "table",
      "pending",
      "inflight",
      "dead_letter",
      "backlog",
    ])
  );
}

function isBreakerHealthRow(value: unknown): value is BreakerHealthRow {
  return isRecord(value) && hasKeys(value, ["provider", "breaker_state"]);
}

function isSystemHealth(value: unknown): value is SystemHealth {
  return (
    isRecord(value) &&
    hasKeys(value, [
      "dependencies",
      "outbox",
      "outbox_backlog",
      "dead_letter_rows",
      "breakers",
      "open_breakers",
    ]) &&
    isArrayOf(value.dependencies, isDependencyHealth) &&
    isArrayOf(value.outbox, isOutboxHealthRow) &&
    isArrayOf(value.breakers, isBreakerHealthRow)
  );
}

function isAlertEntry(value: unknown): value is AlertEntry {
  return (
    isRecord(value) &&
    hasKeys(value, [
      "id",
      "severity",
      "kind",
      "title",
      "payload",
      "status",
      "created_at",
      "acked_by",
      "acked_at",
    ])
  );
}

function isAlertPage(value: unknown): value is AlertPage {
  return (
    isRecord(value) &&
    hasKeys(value, ["alerts", "total_count"]) &&
    isArrayOf(value.alerts, isAlertEntry)
  );
}

function isDeeplinks(value: unknown): value is Deeplinks {
  return isRecord(value) && hasKeys(value, ["grafana", "sentry", "langfuse"]);
}

/**
 * Render a windowed read's query string, omitting `days` when unset so the
 * route applies its own default. The `ge=1, le=365` bounds are NOT restated
 * here (coding-standards §9.2): one authority for the window's range, and the
 * route's 422 is the honest answer to an out-of-range window.
 */
function windowQuery(days?: number): string {
  const search = new URLSearchParams();
  if (days !== undefined) search.set("days", String(days));
  const query = search.toString();
  return query ? `?${query}` : "";
}

/** The headline KPIs the operator landing page opens with. */
export async function fetchOverview(
  params: { days?: number } = {},
): Promise<Overview> {
  const data = await request<unknown>(
    `${OBSERVABILITY_BASE}/overview${windowQuery(params.days)}`,
  );
  return guardShape(
    data,
    isOverview,
    "The API returned an unexpected observability overview shape",
  );
}

/** AI spend against the current billing period's budget, per budget scope. */
export async function fetchCost(): Promise<CostSummary> {
  const data = await request<unknown>(`${OBSERVABILITY_BASE}/cost`);
  return guardShape(
    data,
    isCostSummary,
    "The API returned an unexpected observability cost shape",
  );
}

/** The daily cost series over the window, oldest day first. */
export async function fetchCostTrend(
  params: { days?: number } = {},
): Promise<CostTrend> {
  const data = await request<unknown>(
    `${OBSERVABILITY_BASE}/cost/trend${windowQuery(params.days)}`,
  );
  return guardShape(
    data,
    isCostTrend,
    "The API returned an unexpected observability cost trend shape",
  );
}

/** Calls, tokens and cost by provider, model and task over the window. */
export async function fetchUsage(
  params: { days?: number } = {},
): Promise<UsageReport> {
  const data = await request<unknown>(
    `${OBSERVABILITY_BASE}/usage${windowQuery(params.days)}`,
  );
  return guardShape(
    data,
    isUsageReport,
    "The API returned an unexpected observability usage shape",
  );
}

/** Success and low-confidence rates over the window, plus provider health. */
export async function fetchQuality(
  params: { days?: number } = {},
): Promise<QualityReport> {
  const data = await request<unknown>(
    `${OBSERVABILITY_BASE}/quality${windowQuery(params.days)}`,
  );
  return guardShape(
    data,
    isQualityReport,
    "The API returned an unexpected observability quality shape",
  );
}

/**
 * Per-provider p50/p95/p99 as of the last roll. Unwindowed on purpose: the
 * route derives no aggregate from a requested window (see facade.LatencyReport).
 */
export async function fetchLatency(): Promise<LatencyReport> {
  const data = await request<unknown>(`${OBSERVABILITY_BASE}/latency`);
  return guardShape(
    data,
    isLatencyReport,
    "The API returned an unexpected observability latency shape",
  );
}

/** Dependency reachability plus the outbox and circuit-breaker state. */
export async function fetchHealth(): Promise<SystemHealth> {
  const data = await request<unknown>(`${OBSERVABILITY_BASE}/health`);
  return guardShape(
    data,
    isSystemHealth,
    "The API returned an unexpected observability health shape",
  );
}

/** The paged alert feed, newest first. */
export async function fetchAlerts(
  params: { page?: number; page_size?: number; status?: AlertStatus } = {},
): Promise<AlertPage> {
  const search = new URLSearchParams();
  if (params.page !== undefined) search.set("page", String(params.page));
  if (params.page_size !== undefined) {
    search.set("page_size", String(params.page_size));
  }
  if (params.status) search.set("status", params.status);
  const query = search.toString();
  const data = await request<unknown>(
    `${OBSERVABILITY_BASE}/alerts${query ? `?${query}` : ""}`,
  );
  return guardShape(
    data,
    isAlertPage,
    "The API returned an unexpected observability alerts shape",
  );
}

/** The configured Grafana/Sentry/Langfuse links; every key is nullable. */
export async function fetchDeeplinks(): Promise<Deeplinks> {
  const data = await request<unknown>(`${OBSERVABILITY_BASE}/deeplinks`);
  return guardShape(
    data,
    isDeeplinks,
    "The API returned an unexpected observability deeplinks shape",
  );
}
