// #708 C2a: the operator Observability read client (plan-phase14-observability
// §9.1/§9.2, PHASE-14A BATCH 1). Nine operator-only GETs over the MOD-013
// telemetry the nightly rollup writes: the headline overview, the AI bill, the
// usage/quality/latency breakdowns, dependency health, the alert feed and the
// outbound vendor links. Batch 2 and 3 add the reliability lens's reads (#727
// throughput, #728 provider board, #729 queues, #730 error feed, #734/#735
// alerts) and the business read (#731/#732), plus the one acknowledgement
// write.
//
// The same thin `request` + `guardShape` seam as lib/operator/api.ts: every
// fetcher resolves the exact response model
// (modules/observability/facade.py - Overview, CostSummary, CostTrend,
// UsageReport, QualityReport, LatencyReport, SystemHealth, AlertPage,
// Deeplinks) and raises `ApiError` otherwise, so a page renders one error path
// for a network failure, a refused read and a body that drifted alike.
//
// Money is paise (api-standards §3), so it arrives as a plain `number`.
//
// Percentages and percentiles are a different story: the backend models them as
// Python `Decimal`s, and pydantic's JSON encoder serialises a `Decimal` as a
// STRING - `"73.33"`, not `73.33`. That is the wire contract (the round-trip
// integration tests assert it), so every one of those fields is decoded to a
// `number` here, at the one boundary where a wire body becomes a domain model.
// Skipping this decode does not merely mis-render a figure: `formatPct` calls
// `value.toFixed`, so a string takes down the whole panel.
//
// A rate whose denominator is empty stays `null` through the decode, which
// means "not yet measured" and never reads as zero.

import { IDEMPOTENCY_KEY_HEADER, idempotencyKey } from "@/lib/idempotency";
import { guardShape, request } from "@/lib/request";

/** The observability read routes' shared prefix (plan §9.1). */
const OBSERVABILITY_BASE = "/v1/operator/observability";

/**
 * The alert statuses the feed can be filtered to. A typo is not a filter, so
 * the union closes the set rather than accepting any string.
 *
 * `acknowledged` (#735) is a status an operator can now put a row into, so the
 * open list an operator works shrinks as they acknowledge and the answered ones
 * stay one filter away. The console renders that filter in #738.
 */
export type AlertStatus = "open" | "acknowledged" | "resolved";

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
 * What one acknowledgement wrote (#735).
 *
 * `already_acknowledged` is the idempotent answer, not an error: a repeat call
 * is a 200 whose first acknowledgement stands and cannot be overwritten. A
 * client that treated it as a failure would tell an operator their click did
 * nothing when in fact it was the second one.
 */
export interface AlertAcknowledgement {
  alert: AlertEntry;
  already_acknowledged: boolean;
}

/**
 * Whether the runtime capture is switched on and whether anything has landed in
 * it (#727). This is the panel's answer to "the numbers say zero - is that
 * quiet, or is the recorder off?", which a request count alone cannot give.
 */
export interface CaptureLiveness {
  capturing: boolean;
  requests_recorded: number;
  last_recorded_at: string | null;
}

/**
 * One minute of captured traffic. A minute with no traffic carries NO point at
 * all rather than a zero, so a gap in the series is an absence of traffic
 * instead of a dip drawn to the floor.
 */
export interface ThroughputPoint {
  minute_ts: string;
  requests: number;
  errors: number;
  error_rate: number | null;
}

/**
 * One route's share of the window. `error_rate` is null when the route served
 * no requests - "not measured", never "0% of nothing went wrong".
 */
export interface RouteThroughputRow {
  route_template: string;
  method: string;
  requests: number;
  errors: number;
  error_rate: number | null;
}

/**
 * Requests per minute and error rate over the capture window (#727).
 *
 * `requests_per_minute` and `error_rate` are null when nothing was recorded:
 * they are averages, and an average over no samples has no value. Rendering
 * that as `0` would say "the API served nothing, cleanly" - two claims at once,
 * neither of them measured.
 *
 * `routes` is capped by the route and `routes_total` is the untruncated count,
 * so a client can say how many of how many it is showing.
 */
export interface ThroughputReport {
  minutes: number;
  from_ts: string;
  to_ts: string;
  requests: number;
  errors: number;
  error_rate: number | null;
  requests_per_minute: number | null;
  points: ThroughputPoint[];
  routes: RouteThroughputRow[];
  routes_total: number;
  capture: CaptureLiveness;
}

/**
 * How one provider is doing, DERIVED at read time rather than stored (#728).
 *
 * `last_error` is the newest failure's sanitised reason in the window, and it is
 * deliberately NOT an input to `status`: a provider can be perfectly healthy
 * with one stale error message still sitting on the board, and reading the two
 * as the same fact turns a recovery into an incident.
 */
export type ProviderStatus = "healthy" | "degraded" | "down";

/** One provider's health row on the board (#728). */
export interface ProviderBoardRow {
  provider: string;
  status: ProviderStatus;
  breaker_state: string;
  success_rate: number | null;
  sample_count: number;
  timeout_count: number;
  rate_limit_count: number;
  p50_duration_ms: number | null;
  p95_duration_ms: number | null;
  p99_duration_ms: number | null;
  last_error: string | null;
  window_start: string | null;
  window_end: string | null;
}

/** The provider board, plus how fresh the rollup behind it is. */
export interface ProviderBoardReport {
  last_rolled_date: string | null;
  providers: ProviderBoardRow[];
}

/**
 * One AI pipeline leg's backlog (#729). `oldest_age_s` is null on an empty
 * queue - a queue with nothing in it has no oldest job, and printing `0s`
 * would make a drained queue look like the one thing it is not.
 */
export interface QueueDepthRow {
  queue: string;
  depth: number;
  oldest_enqueued_at: string | null;
  oldest_age_s: number | null;
}

/**
 * Queue depth, the age of the oldest queued job, and recent activity (#729).
 *
 * `recent_active_actors` is a DISTINCT-actor count over
 * `activity_window_minutes`, NOT simultaneous concurrency: true concurrency is
 * an OpenTelemetry gauge that lives in the tracing backend, and the only honest
 * way to show it is `concurrency_grafana_link`. Presenting the actor count under
 * a concurrency label would be a number the platform cannot stand behind
 * (spec #717 decision 17).
 */
export interface ReliabilityReport {
  queues: QueueDepthRow[];
  queue_depth: number;
  oldest_queued_age_s: number | null;
  outbox: OutboxHealthRow[];
  outbox_backlog: number;
  dead_letter_rows: number;
  recent_active_actors: number;
  activity_window_minutes: number;
  concurrency_grafana_link: string | null;
}

/**
 * The statuses the live error feed filters to (#730). NARROWER than
 * `AlertStatus` on purpose: an acknowledged FAILURE is not a resolved one -
 * the request still failed - so the route refuses `acknowledged` with a 422
 * rather than answering a filter the word does not support.
 */
export type ErrorFeedStatus = "open" | "resolved";

/**
 * One collapsed failure (#730). `occurrences` is how many times this exact
 * fingerprint was seen in the window, so a page of rows reports far more
 * failures than it lists.
 */
export interface ErrorFeedEntry {
  fingerprint: string;
  route_template: string;
  method: string;
  status_code: number;
  status_class: string;
  kind: string;
  code: string;
  trace_id: string;
  occurrences: number;
  first_seen_at: string;
  last_seen_at: string;
  status: string;
}

/**
 * One page of the collapsed feed, plus BOTH totals: `total_count` is the number
 * of distinct failures and `total_occurrences` is every occurrence behind them.
 * A panel that reported only the row count would understate an outage by the
 * repetition factor.
 */
export interface ErrorFeedPage {
  errors: ErrorFeedEntry[];
  total_count: number;
  total_occurrences: number;
  window_minutes: number;
}

/**
 * The window the business read reports on (#731). Every window ends today and
 * differs only in where it starts, so they are three views of one running month
 * rather than three unrelated reports - which is why the cap and the projection
 * ride every one of them unchanged.
 */
export type BusinessPeriod = "today" | "week_to_date" | "month_to_date";

/**
 * Why a margin figure is absent. The read reports a figure OR a reason, never a
 * zero: a deployment that has not written revenue yet has no gross margin, and
 * rendering that as 0% would read as "the AI costs nothing".
 */
export type MarginUnavailableReason = "revenue_not_captured" | "revenue_zero";

/** A percentage that is either measured or explained, never zero-by-default. */
export interface MarginPercent {
  value: number | null;
  reason: MarginUnavailableReason | null;
  detail: string | null;
}

/**
 * What the projection was extrapolated from. Carried on the wire rather than
 * assumed by the page: "₹32,000 by month end" is a claim, and the elapsed/total
 * day counts are what let an operator judge it.
 */
export interface ProjectionBasis {
  period_start: string;
  period_end: string;
  elapsed_days: number;
  period_days: number;
}

/** One scope's token bill. The shared shape of all three breakdowns. */
interface SpendBreakdownRow {
  jobs: number;
  spend_paise: number;
  input_tokens: number;
  output_tokens: number;
  paise_per_1k_input_tokens: number | null;
  paise_per_1k_output_tokens: number | null;
}

/** One provider's share of the bill. */
export interface ProviderSpend extends SpendBreakdownRow {
  provider: string;
}

/**
 * One model's share. `provider` repeats rather than nesting: the (provider, model)
 * pair is the key, and a nested object would make the axis label a lookup.
 */
export interface ModelSpend extends SpendBreakdownRow {
  provider: string;
  model: string;
}

/**
 * One task type's share. `task_type` is an OPEN vocabulary - the AI task legs are
 * added by features, not by a migration - so it is a string here and the axis
 * carries whatever the platform actually ran.
 */
export interface TaskTypeSpend extends SpendBreakdownRow {
  task_type: string;
}

/**
 * How heavy the actors are, over the WHOLE population. `actors` is the
 * population count, not the length of the capped top-N lists below it - a client
 * that read it as "how many rows I got" would report 10 actors for a deployment
 * with 400.
 */
export interface ActorSpendDistribution {
  actors: number;
  total_spend_paise: number;
  median_spend_paise: number | null;
  p95_spend_paise: number | null;
  max_spend_paise: number | null;
}

/**
 * One heavy patient. `patient_key` is the platform's own pseudonymous hash - an
 * identifier for joining, never an identity to display, and never a name.
 */
export interface PatientSpend {
  patient_key: string;
  /** Null when no edge settles it, or when a re-pick left two doctors. */
  attributed_doctor_key: string | null;
  jobs: number;
  completed_jobs: number;
  failed_jobs: number;
  spend_paise: number;
}

/** One heavy doctor. `patients` is null when no edge was recorded. */
export interface DoctorSpend {
  doctor_key: string;
  patients: number | null;
  jobs: number;
  completed_jobs: number;
  failed_jobs: number;
  spend_paise: number;
}

/**
 * The margin view. Today the platform captures no revenue, so the two headline
 * percentages arrive as `null` with a reason - which is why the page renders a
 * stated "not captured yet" rather than a figure.
 */
export interface MarginRead {
  revenue_paise: number;
  cost_of_goods_paise: number;
  headline_month_cost_of_goods_paise: number | null;
  revenue_captured: boolean;
  tiers_captured: boolean;
  tier_keys: string[];
  gross_margin: MarginPercent;
  ai_cost_pct_of_revenue: MarginPercent;
}

/**
 * The whole business read (#731 spend and breakdown, #732 unit costs and
 * attribution) over one window. One route, so one `usePanelRead` and one
 * failure: every panel on the Business page answers from the same numbers and
 * cannot disagree with each other.
 */
export interface BusinessRead {
  period: BusinessPeriod;
  period_start: string;
  period_end: string;
  spend_paise: number;
  jobs: number;
  completed_jobs: number;
  failed_jobs: number;
  input_tokens: number;
  output_tokens: number;
  paise_per_1k_input_tokens: number | null;
  paise_per_1k_output_tokens: number | null;
  monthly_cap_paise: number;
  cap_consumed_paise: number;
  cap_consumed_pct: number;
  projected_month_end_paise: number | null;
  /** Always present, even when there is no projection to compare it against. */
  projected_over_cap: boolean;
  projection_basis: ProjectionBasis | null;
  by_provider: ProviderSpend[];
  by_model: ModelSpend[];
  by_task_type: TaskTypeSpend[];
  cost_per_request_paise: number | null;
  cost_per_completed_task_paise: number | null;
  cost_per_patient_paise: number | null;
  cost_per_doctor_paise: number | null;
  cost_of_pass_paise: number | null;
  patient_spend: ActorSpendDistribution;
  doctor_spend: ActorSpendDistribution;
  /** Capped at the ten heaviest; NOT a page of a larger list. */
  top_patients: PatientSpend[];
  /** Capped at the ten heaviest; NOT a page of a larger list. */
  top_doctors: DoctorSpend[];
  margin: MarginRead;
}

// ------------------------------------------------ the product lenses (#740-#742)

/**
 * The funnel's outcome vocabulary, in the registry's closed order (#740).
 *
 * The route refuses anything else at the edge rather than answering 200 with an
 * empty funnel, because an empty funnel reads as "nobody abandons" rather than
 * as a bad query.
 */
export type ProductOutcome =
  | "completed"
  | "abandoned"
  | "errored"
  | "re_recorded";

/** One window's distinct actors, split by kind (#741). */
export interface ActiveUserWindow {
  window_days: number;
  from_date: string;
  to_date: string;
  patients: number;
  doctors: number;
  /** `patients + doctors`; the two kinds share no actor key. */
  total: number;
}

/**
 * One day of the adoption trend. A day with nothing recorded is ABSENT, not
 * zero-filled, so a quiet stretch and a stopped counter do not look alike.
 */
export interface ActiveUsersDayPoint {
  day: string;
  requests: number;
  active_users: number;
  requests_per_active_user: number | null;
}

/**
 * The adoption read: DAU, WAU, MAU, stickiness and load per head (#741).
 *
 * Every figure is computed in Postgres, in the product event ledger - the
 * system of record - rather than over a vendor window. That matters most for
 * `monthly_active_users`: the free metrics tier keeps fourteen days, so a
 * vendor answer to a thirty-day question does not exist, and the read must not
 * truncate itself to what the vendor still holds.
 *
 * `window_active_users` is the requested window's own set and the denominator
 * of `requests_per_active_user`; it is not a fourth DAU/WAU/MAU figure.
 */
export interface ActiveUsersRead {
  days: number;
  from_date: string;
  to_date: string;
  daily_active_users: ActiveUserWindow;
  weekly_active_users: ActiveUserWindow;
  monthly_active_users: ActiveUserWindow;
  window_active_users: ActiveUserWindow;
  /** DAU/MAU as a FRACTION at 4dp, or null when there is no monthly base. */
  stickiness: number | null;
  requests: number;
  requests_per_active_user: number | null;
  trend: ActiveUsersDayPoint[];
  window_convention: string;
  source_convention: string;
  stickiness_convention: string;
  requests_per_active_user_convention: string;
}

/**
 * One step of the walked funnel (#740).
 *
 * `entered` counts every row the step wrote and the four outcome counters split
 * it, so a row can never describe two populations. `completed` is the only one
 * of the four that counts as success; `errored` is a degraded fallback (not a
 * quiet abandonment) and `re_recorded` is a correction (not a failure).
 *
 * `conversion_from_previous` is a fraction over the nearest preceding
 * NON-TERMINAL step's `entered`, not over successes, so it can exceed 1 and is
 * `null` on the first step. `median_gap_from_previous_s` is thinking time, and a
 * null with any `gap_basis` other than `actor_key` is unmeasured rather than
 * instant.
 */
export interface FunnelStepRow {
  step: string;
  event_type: string;
  terminal: boolean;
  previous_step: string | null;
  entered: number;
  completed: number;
  abandoned: number;
  errored: number;
  re_recorded: number;
  conversion_from_previous: number | null;
  median_gap_from_previous_s: number | null;
  gap_samples: number;
  gap_basis: string;
  latest_trace_id: string | null;
}

/**
 * Did the workflows finish? Success and abandonment, over ONE denominator.
 *
 * The two rates ride one block because they must never be quoted apart: both
 * divide `started`, are deliberately not complementary, and can both count the
 * same journey (a re-record that carries on to an issued prescription).
 * `issued_e_prescriptions` and `cases_closed` are both legitimate successes and
 * are reported apart.
 */
export interface FunnelOutcomeTotals {
  started: number;
  task_success_rate: number | null;
  abandonment_rate: number | null;
  issued_e_prescriptions: number;
  cases_closed: number;
  abandoned: number;
  errored: number;
  re_recorded: number;
}

/**
 * The intake funnel, from the moment a patient opened the composer (#740).
 *
 * `outcome` narrows the STEPS to that path and each row's counts to it. It does
 * NOT narrow `outcomes`: success and abandonment are the whole window's verdict
 * and measuring one over a different population than the other is the failure
 * `FunnelOutcomeTotals` exists to prevent.
 */
export interface FunnelRead {
  funnel: string;
  window_start: string;
  window_end: string;
  window_days: number;
  outcome: ProductOutcome | null;
  denominator_convention: string;
  rate_convention: string;
  gap_convention: string;
  steps: FunnelStepRow[];
  outcomes: FunnelOutcomeTotals;
}

/**
 * One arrival date's cohort and how much of it was still here later (#742).
 *
 * `retained_*d` and `retention_*d` are null when that horizon has not arrived
 * yet, and null - never zero. Zero means observed and nobody came back; null
 * means the question cannot be asked yet. A cohort of size 0 is null for the
 * same reason: there is no such thing as a rate on an empty base.
 */
export interface RetentionCohortDay {
  cohort_date: string;
  cohort_size: number;
  retained_7d: number | null;
  retention_7d: number | null;
  retained_30d: number | null;
  retention_30d: number | null;
}

/**
 * Seven- and thirty-day retention, one row per arrival day (#742).
 *
 * A cohort is a GROUP, not a window: everyone whose first-ever qualifying
 * action fell on one date. Derived at read time from the nightly per-actor day
 * aggregate, so the thirty-day answer outlives the vendor's fourteen-day
 * retention and the raw ledger is never scanned.
 */
export interface RetentionCohortsRead {
  days: number;
  from_date: string;
  to_date: string;
  horizons: [number, number];
  cohorts: RetentionCohortDay[];
  window_convention: string;
  maturity_convention: string;
  source_convention: string;
  actor_convention: string;
}

/**
 * The Grafana views, each already carrying its own filter (#736). The dashboard
 * link always exists when the vendor is configured - it can always carry its range
 * and variables - while `explore_url` needs a trace, so it is optional.
 */
export interface GrafanaDeeplinks {
  dashboard_uid: string;
  dashboard_url: string;
  explore_url?: string;
}

/**
 * The Sentry views, pre-filtered to this service and (when the caller knew one) to
 * an error type. `project_id` is the label for the link; the URLs never carry the
 * DSN's key half.
 */
export interface SentryDeeplinks {
  project_id: string;
  issues_url: string;
  trace_url?: string;
}

/**
 * The Langfuse views, each filtered by the context the panel was showing. Every
 * key is optional because every view needs context - a model, a task, a trace, an
 * actor, a session - so a panel that has none simply has no Langfuse group.
 */
export interface LangfuseDeeplinks {
  traces_url?: string;
  trace_url?: string;
  actor_url?: string;
  session_url?: string;
}

/**
 * The outbound vendor link SETS (#736 - a wire change; decision 44). Three bare
 * base URLs became three groups of links that each land on the answer.
 *
 * A vendor that is switched off is **absent from the response**, not `null` in
 * it: the backend answers with `exclude_none`, so an unconfigured deployment's
 * payload has no `grafana` key at all and no link object full of nulls. Every key
 * is therefore optional and there is no such thing as a link here that points
 * nowhere - which is exactly what `isDeeplinks` holds the client to.
 *
 * `trace_id` echoes the platform's own stored identifier so every rendered link
 * can be labelled with the join key they all share.
 */
export interface Deeplinks {
  trace_id?: string;
  grafana?: GrafanaDeeplinks;
  sentry?: SentryDeeplinks;
  langfuse?: LangfuseDeeplinks;
}

/**
 * The context a panel can hand the read so its links point at what the operator
 * was looking at. Every field comes from a platform read - the error feed's
 * `trace_id`, a product row's pseudonymous `actor_key`, a usage row's
 * `model`/`task_type` - and is passed through untouched. Nothing here is derived
 * in the browser: a trace id this platform never stored opens a view with nothing
 * in it.
 */
export interface DeeplinkContext {
  trace_id?: string;
  actor_key?: string;
  session_key?: string;
  model?: string;
  task_type?: string;
  error_type?: string;
  window?: string;
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

/**
 * Decode one wire decimal to a `number`.
 *
 * pydantic serialises a backend `Decimal` as a JSON string (`"73.33"`), so a
 * numeric-string, a bare JSON number, or `null` are all legal on the wire and
 * all have to land as the `number`/`null` the declared model promises. A value
 * that is neither decodes to `NaN`, which `isWireDecimal` then rejects so the
 * guard raises `UNEXPECTED_ERROR` rather than a figure rendering as "NaN%".
 */
function wireDecimal(value: unknown): number | null {
  if (value === null) return null;
  if (typeof value === "number") return value;
  if (typeof value === "string" && value.trim() !== "") return Number(value);
  return Number.NaN;
}

/**
 * True when a `Decimal`-declared field is a number or `null`, or the numeric
 * string pydantic actually emits. Widening the guards to accept the wire's
 * string form is what lets the decode below run; a value that decodes to `NaN`
 * fails here and never reaches a formatter.
 */
function isWireDecimal(value: unknown): boolean {
  if (value === null) return true;
  const decoded = wireDecimal(value);
  return typeof decoded === "number" && Number.isFinite(decoded);
}

/**
 * Decode every `Decimal` field a model declares, in place on a shallow copy.
 *
 * The `Decimal`s on the wire are strings, so each named key is coerced to a
 * number here - the one place a wire body becomes the domain model. A `null`
 * rate stays `null` ("not yet measured").
 */
function withDecimals<T extends object>(model: T, keys: readonly string[]): T {
  if (keys.length === 0) return model;
  const copy = { ...model } as Record<string, unknown>;
  for (const key of keys) {
    if (key in copy) {
      copy[key] = wireDecimal(copy[key]);
    }
  }
  return copy as T;
}

/** Cost/quality/latency/overview/health `Decimal` fields, keyed by model. */
const COST_DECIMALS = ["utilization_pct"] as const;
const COST_BUDGET_DECIMALS = ["utilization_pct"] as const;
const OVERVIEW_DECIMALS = [
  "success_rate",
  "low_confidence_rate",
  "p95_duration_ms",
  "budget_utilization_pct",
] as const;
const QUALITY_DECIMALS = ["success_rate", "low_confidence_rate"] as const;
const PROVIDER_QUALITY_DECIMALS = ["success_rate"] as const;
const LATENCY_DECIMALS = [
  "p50_duration_ms",
  "p95_duration_ms",
  "p99_duration_ms",
] as const;
const DEPENDENCY_DECIMALS = ["latency_ms"] as const;

/**
 * The business read's `Decimal` fields (#731/#732) - EIGHT at the top level,
 * plus two more inside each of three breakdown rows and two interpolated
 * percentiles on each distribution.
 *
 * `cap_consumed_pct` is non-nullable on the wire even with no cap configured (the
 * read sends "0.00"), so it is the one field in this list that must decode rather
 * than stay `null`. Every other unit cost is nullable because the read divides at
 * read time and a zero denominator means "not measured", never zero.
 */
const BUSINESS_DECIMALS = [
  "paise_per_1k_input_tokens",
  "paise_per_1k_output_tokens",
  "cap_consumed_pct",
  "cost_per_request_paise",
  "cost_per_completed_task_paise",
  "cost_per_patient_paise",
  "cost_per_doctor_paise",
  "cost_of_pass_paise",
] as const;

/** The one percentage on a `MarginPercent`. */
const MARGIN_PERCENT_DECIMALS = ["value"] as const;

/** The token rates, shared by all three breakdowns. */
const SPEND_ROW_DECIMALS = [
  "paise_per_1k_input_tokens",
  "paise_per_1k_output_tokens",
] as const;

/**
 * The distribution percentiles. These come from rank interpolation, so they
 * carry NO fixed scale - the wire sends "20000", not "20000.0000" - which is why
 * `wireDecimal` takes a bare integer string and why they are not in the same
 * list as the 4dp unit costs.
 */
const DISTRIBUTION_DECIMALS = [
  "median_spend_paise",
  "p95_spend_paise",
] as const;

/** `max_spend_paise` is deliberately NOT here: it is an observed integer. */

/**
 * The reliability lens's quoted rates (#727 throughput, #728 provider board).
 * Every one of them is an average or a percentage the backend computes as a
 * `Decimal`, so all five arrive as JSON strings - and all five land on a
 * formatter or a chart axis on the Reliability page.
 */
const THROUGHPUT_DECIMALS = ["error_rate", "requests_per_minute"] as const;
const THROUGHPUT_POINT_DECIMALS = ["error_rate"] as const;
const THROUGHPUT_ROUTE_DECIMALS = ["error_rate"] as const;
const PROVIDER_BOARD_DECIMALS = [
  "success_rate",
  "p50_duration_ms",
  "p95_duration_ms",
  "p99_duration_ms",
] as const;

/**
 * The product lenses' quoted fields (#740-#742).
 *
 * Every rate here is a FRACTION the backend computes as a `Decimal`, so it
 * arrives as a JSON string and must reach `formatRate` as a number. The nulls
 * are the important half: stickiness has no base to divide by, a gap has no
 * shared key to pair on, and a retention horizon has not arrived yet - all are
 * "not measured", and a false zero would be a claim about the product.
 */
const ACTIVE_USERS_DECIMALS = [
  "stickiness",
  "requests_per_active_user",
] as const;
const ACTIVE_USERS_POINT_DECIMALS = ["requests_per_active_user"] as const;
const FUNNEL_STEP_DECIMALS = [
  "conversion_from_previous",
  "median_gap_from_previous_s",
] as const;
const FUNNEL_OUTCOME_DECIMALS = [
  "task_success_rate",
  "abandonment_rate",
] as const;
const RETENTION_COHORT_DECIMALS = ["retention_7d", "retention_30d"] as const;

function isBusinessCountView(value: unknown): value is BusinessCountView {
  return isRecord(value) && hasKeys(value, ["metric_key", "count"]);
}

/**
 * The key set every spend breakdown row shares. One declaration for all three
 * breakdowns: they differ only in how a row is NAMED, and restating these six
 * keys three times is how the task-type row quietly stops carrying its rates
 * while the panel still type-checks.
 *
 * This narrows to `Record<string, unknown>` rather than to one of the three row
 * types: it answers "does a breakdown row look right", and which row it is
 * depends on a key the three guards below each add.
 */
const SPEND_ROW_KEYS = [
  "jobs",
  "spend_paise",
  "input_tokens",
  "output_tokens",
  "paise_per_1k_input_tokens",
  "paise_per_1k_output_tokens",
] as const;

function isSpendBreakdownRow(value: unknown): value is Record<string, unknown> {
  return (
    isRecord(value) &&
    hasKeys(value, SPEND_ROW_KEYS) &&
    hasWireDecimals(value, SPEND_ROW_DECIMALS)
  );
}

function isProviderSpend(value: unknown): value is ProviderSpend {
  return isSpendBreakdownRow(value) && "provider" in value;
}

function isModelSpend(value: unknown): value is ModelSpend {
  return isSpendBreakdownRow(value) && hasKeys(value, ["provider", "model"]);
}

function isTaskTypeSpend(value: unknown): value is TaskTypeSpend {
  return isSpendBreakdownRow(value) && "task_type" in value;
}

function isProjectionBasis(value: unknown): value is ProjectionBasis {
  return (
    isRecord(value) &&
    hasKeys(value, [
      "period_start",
      "period_end",
      "elapsed_days",
      "period_days",
    ])
  );
}

/**
 * The distribution's own interpolations, decoded. `max_spend_paise` is left
 * alone: it is an observed figure, an integer the read did not interpolate.
 */
function isActorSpendDistribution(
  value: unknown,
): value is ActorSpendDistribution {
  return (
    isRecord(value) &&
    hasKeys(value, [
      "actors",
      "total_spend_paise",
      "median_spend_paise",
      "p95_spend_paise",
      "max_spend_paise",
    ]) &&
    hasWireDecimals(value, DISTRIBUTION_DECIMALS)
  );
}

function isPatientSpend(value: unknown): value is PatientSpend {
  return (
    isRecord(value) &&
    hasKeys(value, [
      "patient_key",
      "attributed_doctor_key",
      "jobs",
      "completed_jobs",
      "failed_jobs",
      "spend_paise",
    ])
  );
}

function isDoctorSpend(value: unknown): value is DoctorSpend {
  return (
    isRecord(value) &&
    hasKeys(value, [
      "doctor_key",
      "patients",
      "jobs",
      "completed_jobs",
      "failed_jobs",
      "spend_paise",
    ])
  );
}

/**
 * A margin percentage that must DECODE. It may be null - that is the
 * revenue-not-captured case - but it may not be an empty or unparseable string:
 * `""` is what a `Decimal` serialises to when the value was never set, and
 * letting it through would put `NaN` in a percentage an operator reads as fact.
 */
function isMarginPercent(value: unknown): value is MarginPercent {
  return (
    isRecord(value) &&
    hasKeys(value, ["value", "reason", "detail"]) &&
    hasWireDecimals(value, MARGIN_PERCENT_DECIMALS)
  );
}

function isMarginRead(value: unknown): value is MarginRead {
  return (
    isRecord(value) &&
    hasKeys(value, [
      "revenue_paise",
      "cost_of_goods_paise",
      "headline_month_cost_of_goods_paise",
      "revenue_captured",
      "tiers_captured",
      "tier_keys",
      "gross_margin",
      "ai_cost_pct_of_revenue",
    ]) &&
    isMarginPercent(value.gross_margin) &&
    isMarginPercent(value.ai_cost_pct_of_revenue)
  );
}

/**
 * The business read. Key presence plus decodability, like every other guard
 * here, with one addition: `cap_consumed_pct` must decode to a NUMBER rather
 * than to null. The route always sends it - "0.00" when nothing is capped - so a
 * null there is a wire this client cannot honestly model, and the model promises
 * `number` because the page prints it without a null check.
 */
function isBusinessRead(value: unknown): value is BusinessRead {
  return (
    isRecord(value) &&
    hasKeys(value, [
      "period",
      "period_start",
      "period_end",
      "spend_paise",
      "jobs",
      "completed_jobs",
      "failed_jobs",
      "input_tokens",
      "output_tokens",
      "paise_per_1k_input_tokens",
      "paise_per_1k_output_tokens",
      "monthly_cap_paise",
      "cap_consumed_paise",
      "cap_consumed_pct",
      "projected_month_end_paise",
      "projected_over_cap",
      "projection_basis",
      "by_provider",
      "by_model",
      "by_task_type",
      "cost_per_request_paise",
      "cost_per_completed_task_paise",
      "cost_per_patient_paise",
      "cost_per_doctor_paise",
      "cost_of_pass_paise",
      "patient_spend",
      "doctor_spend",
      "top_patients",
      "top_doctors",
      "margin",
    ]) &&
    hasWireDecimals(value, BUSINESS_DECIMALS) &&
    value.cap_consumed_pct !== null &&
    isArrayOf(value.by_provider, isProviderSpend) &&
    isArrayOf(value.by_model, isModelSpend) &&
    isArrayOf(value.by_task_type, isTaskTypeSpend) &&
    isActorSpendDistribution(value.patient_spend) &&
    isActorSpendDistribution(value.doctor_spend) &&
    isArrayOf(value.top_patients, isPatientSpend) &&
    isArrayOf(value.top_doctors, isDoctorSpend) &&
    isMarginRead(value.margin)
  );
}

function isActiveUserWindow(value: unknown): value is ActiveUserWindow {
  return (
    isRecord(value) &&
    hasKeys(value, [
      "window_days",
      "from_date",
      "to_date",
      "patients",
      "doctors",
      "total",
    ])
  );
}

function isActiveUsersDayPoint(value: unknown): value is ActiveUsersDayPoint {
  return (
    isRecord(value) &&
    hasKeys(value, ["day", "requests", "active_users"]) &&
    hasWireDecimals(value, ACTIVE_USERS_POINT_DECIMALS)
  );
}

function isActiveUsersRead(value: unknown): value is ActiveUsersRead {
  return (
    isRecord(value) &&
    hasKeys(value, [
      "days",
      "from_date",
      "to_date",
      "daily_active_users",
      "weekly_active_users",
      "monthly_active_users",
      "window_active_users",
      "requests",
      "trend",
      "window_convention",
      "source_convention",
      "stickiness_convention",
      "requests_per_active_user_convention",
    ]) &&
    hasWireDecimals(value, ACTIVE_USERS_DECIMALS) &&
    isActiveUserWindow(value.daily_active_users) &&
    isActiveUserWindow(value.weekly_active_users) &&
    isActiveUserWindow(value.monthly_active_users) &&
    isActiveUserWindow(value.window_active_users) &&
    isArrayOf(value.trend, isActiveUsersDayPoint)
  );
}

function isFunnelStepRow(value: unknown): value is FunnelStepRow {
  return (
    isRecord(value) &&
    hasKeys(value, [
      "step",
      "event_type",
      "terminal",
      "previous_step",
      "entered",
      "completed",
      "abandoned",
      "errored",
      "re_recorded",
      "gap_samples",
      "gap_basis",
      "latest_trace_id",
    ]) &&
    hasWireDecimals(value, FUNNEL_STEP_DECIMALS)
  );
}

function isFunnelOutcomeTotals(value: unknown): value is FunnelOutcomeTotals {
  return (
    isRecord(value) &&
    hasKeys(value, [
      "started",
      "issued_e_prescriptions",
      "cases_closed",
      "abandoned",
      "errored",
      "re_recorded",
    ]) &&
    hasWireDecimals(value, FUNNEL_OUTCOME_DECIMALS)
  );
}

function isFunnelRead(value: unknown): value is FunnelRead {
  return (
    isRecord(value) &&
    hasKeys(value, [
      "funnel",
      "window_start",
      "window_end",
      "window_days",
      "outcome",
      "denominator_convention",
      "rate_convention",
      "gap_convention",
      "steps",
    ]) &&
    isFunnelOutcomeTotals(value.outcomes) &&
    isArrayOf(value.steps, isFunnelStepRow)
  );
}

function isRetentionCohortDay(value: unknown): value is RetentionCohortDay {
  return (
    isRecord(value) &&
    hasKeys(value, [
      "cohort_date",
      "cohort_size",
      "retained_7d",
      "retained_30d",
    ]) &&
    hasWireDecimals(value, RETENTION_COHORT_DECIMALS)
  );
}

function isRetentionCohortsRead(value: unknown): value is RetentionCohortsRead {
  return (
    isRecord(value) &&
    hasKeys(value, [
      "days",
      "from_date",
      "to_date",
      "horizons",
      "cohorts",
      "window_convention",
      "maturity_convention",
      "source_convention",
      "actor_convention",
    ]) &&
    isArrayOf(value.cohorts, isRetentionCohortDay)
  );
}

/**
 * Key-presence PLUS decodability check for a model's `Decimal` fields. The one
 * place the guards are stricter than "is the key there": a decimal that will not
 * decode to a finite number is a body the client cannot honestly model, and
 * `guardShape` turns that into the same `UNEXPECTED_ERROR` every other shape
 * fault produces.
 */
function hasWireDecimals(
  value: Record<string, unknown>,
  keys: readonly string[],
): boolean {
  return keys.every((key) => key in value && isWireDecimal(value[key]));
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
    hasWireDecimals(value, OVERVIEW_DECIMALS) &&
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
    ]) &&
    hasWireDecimals(value, COST_BUDGET_DECIMALS)
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
    hasWireDecimals(value, COST_DECIMALS) &&
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
    ]) &&
    hasWireDecimals(value, PROVIDER_QUALITY_DECIMALS)
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
    hasWireDecimals(value, QUALITY_DECIMALS) &&
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
    ]) &&
    hasWireDecimals(value, LATENCY_DECIMALS)
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
    hasKeys(value, ["name", "status", "latency_ms", "detail"]) &&
    hasWireDecimals(value, DEPENDENCY_DECIMALS)
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

function isAlertAcknowledgement(value: unknown): value is AlertAcknowledgement {
  return (
    isRecord(value) &&
    hasKeys(value, ["alert", "already_acknowledged"]) &&
    isAlertEntry(value.alert)
  );
}

function isCaptureLiveness(value: unknown): value is CaptureLiveness {
  return (
    isRecord(value) &&
    hasKeys(value, ["capturing", "requests_recorded", "last_recorded_at"])
  );
}

function isThroughputPoint(value: unknown): value is ThroughputPoint {
  return (
    isRecord(value) &&
    hasKeys(value, ["minute_ts", "requests", "errors", "error_rate"]) &&
    hasWireDecimals(value, THROUGHPUT_POINT_DECIMALS)
  );
}

function isRouteThroughputRow(value: unknown): value is RouteThroughputRow {
  return (
    isRecord(value) &&
    hasKeys(value, [
      "route_template",
      "method",
      "requests",
      "errors",
      "error_rate",
    ]) &&
    hasWireDecimals(value, THROUGHPUT_ROUTE_DECIMALS)
  );
}

function isThroughputReport(value: unknown): value is ThroughputReport {
  return (
    isRecord(value) &&
    hasKeys(value, [
      "minutes",
      "from_ts",
      "to_ts",
      "requests",
      "errors",
      "error_rate",
      "requests_per_minute",
      "points",
      "routes",
      "routes_total",
      "capture",
    ]) &&
    hasWireDecimals(value, THROUGHPUT_DECIMALS) &&
    isArrayOf(value.points, isThroughputPoint) &&
    isArrayOf(value.routes, isRouteThroughputRow) &&
    isCaptureLiveness(value.capture)
  );
}

function isProviderBoardRow(value: unknown): value is ProviderBoardRow {
  return (
    isRecord(value) &&
    hasKeys(value, [
      "provider",
      "status",
      "breaker_state",
      "success_rate",
      "sample_count",
      "timeout_count",
      "rate_limit_count",
      "p50_duration_ms",
      "p95_duration_ms",
      "p99_duration_ms",
      "last_error",
      "window_start",
      "window_end",
    ]) &&
    hasWireDecimals(value, PROVIDER_BOARD_DECIMALS)
  );
}

function isProviderBoardReport(value: unknown): value is ProviderBoardReport {
  return (
    isRecord(value) &&
    hasKeys(value, ["last_rolled_date", "providers"]) &&
    isArrayOf(value.providers, isProviderBoardRow)
  );
}

function isQueueDepthRow(value: unknown): value is QueueDepthRow {
  return (
    isRecord(value) &&
    hasKeys(value, ["queue", "depth", "oldest_enqueued_at", "oldest_age_s"])
  );
}

function isReliabilityReport(value: unknown): value is ReliabilityReport {
  return (
    isRecord(value) &&
    hasKeys(value, [
      "queues",
      "queue_depth",
      "oldest_queued_age_s",
      "outbox",
      "outbox_backlog",
      "dead_letter_rows",
      "recent_active_actors",
      "activity_window_minutes",
      "concurrency_grafana_link",
    ]) &&
    isArrayOf(value.queues, isQueueDepthRow) &&
    isArrayOf(value.outbox, isOutboxHealthRow)
  );
}

function isErrorFeedEntry(value: unknown): value is ErrorFeedEntry {
  return (
    isRecord(value) &&
    hasKeys(value, [
      "fingerprint",
      "route_template",
      "method",
      "status_code",
      "status_class",
      "kind",
      "code",
      "trace_id",
      "occurrences",
      "first_seen_at",
      "last_seen_at",
      "status",
    ])
  );
}

function isErrorFeedPage(value: unknown): value is ErrorFeedPage {
  return (
    isRecord(value) &&
    hasKeys(value, [
      "errors",
      "total_count",
      "total_occurrences",
      "window_minutes",
    ]) &&
    isArrayOf(value.errors, isErrorFeedEntry)
  );
}

/**
 * One vendor's group, or absent because the deployment does not ship it.
 *
 * The required keys are the ones a group cannot be missing - a Grafana group with
 * no `dashboard_url`, or a Sentry group with no `issues_url`, would render nothing
 * while claiming a vendor is present. The optional keys are the contextual views,
 * and their absence is the normal case: no trace, no Explore pane.
 *
 * `undefined` is the only acceptable "not configured". The backend answers with
 * `exclude_none`, so a `null` here means the wire and the client disagree about
 * the contract, and refusing it is what turns that disagreement into an error the
 * page can show rather than an empty panel an operator has to interpret.
 */
function isOptionalLinks(value: unknown, required: readonly string[]): boolean {
  if (value === undefined) return true;
  return isRecord(value) && hasKeys(value, required);
}

function isDeeplinks(value: unknown): value is Deeplinks {
  return (
    isRecord(value) &&
    (value.trace_id === undefined || typeof value.trace_id === "string") &&
    isOptionalLinks(value.grafana, ["dashboard_uid", "dashboard_url"]) &&
    isOptionalLinks(value.sentry, ["project_id", "issues_url"]) &&
    isOptionalLinks(value.langfuse, [])
  );
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
  return withDecimals(
    guardShape(
      data,
      isOverview,
      "The API returned an unexpected observability overview shape",
    ),
    OVERVIEW_DECIMALS,
  );
}

/** AI spend against the current billing period's budget, per budget scope. */
export async function fetchCost(): Promise<CostSummary> {
  const data = await request<unknown>(`${OBSERVABILITY_BASE}/cost`);
  const summary = guardShape(
    data,
    isCostSummary,
    "The API returned an unexpected observability cost shape",
  );
  return {
    ...withDecimals(summary, COST_DECIMALS),
    budgets: summary.budgets.map((budget) =>
      withDecimals(budget, COST_BUDGET_DECIMALS),
    ),
  };
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

/**
 * The business read (#731 spend and breakdown, #732 unit costs and
 * attribution) over one window.
 *
 * The whole page is ONE read on purpose. Spend, cap, breakdown, unit costs and
 * attribution are five answers to five questions about the same month, and
 * splitting them across routes would let the panels disagree - a breakdown
 * that reconciles to a spend figure the headline no longer shows is worse than
 * one panel reporting a single honest failure.
 *
 * `period` is omitted when the caller has no preference, so the route's own
 * default is the one authority on what "no window asked for" means.
 */
export async function fetchBusiness(
  params: { period?: BusinessPeriod } = {},
): Promise<BusinessRead> {
  const search = new URLSearchParams();
  if (params.period !== undefined) search.set("period", params.period);
  const query = search.toString();
  const data = await request<unknown>(
    `${OBSERVABILITY_BASE}/business${query ? `?${query}` : ""}`,
  );
  const read = guardShape(
    data,
    isBusinessRead,
    "The API returned an unexpected observability business shape",
  );
  return {
    ...withDecimals(read, BUSINESS_DECIMALS),
    by_provider: read.by_provider.map((row) =>
      withDecimals(row, SPEND_ROW_DECIMALS),
    ),
    by_model: read.by_model.map((row) => withDecimals(row, SPEND_ROW_DECIMALS)),
    by_task_type: read.by_task_type.map((row) =>
      withDecimals(row, SPEND_ROW_DECIMALS),
    ),
    patient_spend: withDecimals(read.patient_spend, DISTRIBUTION_DECIMALS),
    doctor_spend: withDecimals(read.doctor_spend, DISTRIBUTION_DECIMALS),
    margin: {
      ...read.margin,
      gross_margin: withDecimals(
        read.margin.gross_margin,
        MARGIN_PERCENT_DECIMALS,
      ),
      ai_cost_pct_of_revenue: withDecimals(
        read.margin.ai_cost_pct_of_revenue,
        MARGIN_PERCENT_DECIMALS,
      ),
    },
  };
}

/**
 * DAU, WAU, MAU, stickiness and load per head over one window (#741).
 *
 * `days` is omitted when unset so the route's own default is the one authority
 * on what "no window asked for" means. The MAU figure is the system-of-record
 * answer, not a vendor-retention-truncated one - see `ActiveUsersRead`.
 */
export async function fetchActiveUsers(
  params: { days?: number } = {},
): Promise<ActiveUsersRead> {
  const data = await request<unknown>(
    `${OBSERVABILITY_BASE}/product/active-users${windowQuery(params.days)}`,
  );
  const read = guardShape(
    data,
    isActiveUsersRead,
    "The API returned an unexpected observability active users shape",
  );
  return {
    ...withDecimals(read, ACTIVE_USERS_DECIMALS),
    trend: read.trend.map((point) =>
      withDecimals(point, ACTIVE_USERS_POINT_DECIMALS),
    ),
  };
}

/**
 * The intake funnel and its outcome totals (#740), optionally narrowed to one
 * outcome's path.
 *
 * The filter narrows the STEPS, not the outcome block - the route is explicit
 * about that, and the page says so beside the control. `outcome` is omitted
 * when the caller wants the whole funnel.
 */
export async function fetchFunnel(
  params: { days?: number; outcome?: ProductOutcome } = {},
): Promise<FunnelRead> {
  const search = new URLSearchParams();
  if (params.days !== undefined) search.set("days", String(params.days));
  if (params.outcome !== undefined) search.set("outcome", params.outcome);
  const query = search.toString();
  const data = await request<unknown>(
    `${OBSERVABILITY_BASE}/product/funnel${query ? `?${query}` : ""}`,
  );
  const read = guardShape(
    data,
    isFunnelRead,
    "The API returned an unexpected observability funnel shape",
  );
  return {
    ...read,
    steps: read.steps.map((step) => withDecimals(step, FUNNEL_STEP_DECIMALS)),
    outcomes: withDecimals(read.outcomes, FUNNEL_OUTCOME_DECIMALS),
  };
}

/**
 * Seven- and thirty-day retention, one row per arrival date (#742).
 *
 * `days` counts COHORT DATES, not days of series, and the route's default is
 * sixty for that reason. A row whose horizon has not arrived is left `null`;
 * the page renders it as unmeasured rather than as a collapse to zero.
 */
export async function fetchRetentionCohorts(
  params: { days?: number } = {},
): Promise<RetentionCohortsRead> {
  const data = await request<unknown>(
    `${OBSERVABILITY_BASE}/product/retention-cohorts${windowQuery(
      params.days,
    )}`,
  );
  const read = guardShape(
    data,
    isRetentionCohortsRead,
    "The API returned an unexpected observability retention cohorts shape",
  );
  return {
    ...read,
    cohorts: read.cohorts.map((cohort) =>
      withDecimals(cohort, RETENTION_COHORT_DECIMALS),
    ),
  };
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
  const report = guardShape(
    data,
    isQualityReport,
    "The API returned an unexpected observability quality shape",
  );
  return {
    ...withDecimals(report, QUALITY_DECIMALS),
    providers: report.providers.map((provider) =>
      withDecimals(provider, PROVIDER_QUALITY_DECIMALS),
    ),
  };
}

/**
 * Per-provider p50/p95/p99 as of the last roll. Unwindowed on purpose: the
 * route derives no aggregate from a requested window (see facade.LatencyReport).
 */
export async function fetchLatency(): Promise<LatencyReport> {
  const data = await request<unknown>(`${OBSERVABILITY_BASE}/latency`);
  const report = guardShape(
    data,
    isLatencyReport,
    "The API returned an unexpected observability latency shape",
  );
  return {
    ...report,
    providers: report.providers.map((provider) =>
      withDecimals(provider, LATENCY_DECIMALS),
    ),
  };
}

/** Dependency reachability plus the outbox and circuit-breaker state. */
export async function fetchHealth(): Promise<SystemHealth> {
  const data = await request<unknown>(`${OBSERVABILITY_BASE}/health`);
  const health = guardShape(
    data,
    isSystemHealth,
    "The API returned an unexpected observability health shape",
  );
  return {
    ...health,
    dependencies: health.dependencies.map((dependency) =>
      withDecimals(dependency, DEPENDENCY_DECIMALS),
    ),
  };
}

/**
 * The degraded-provider board (#728): every provider the rollup knows about,
 * with its derived status, its failure counts and the newest failure's reason.
 *
 * Unwindowed, because the row's status is derived from the latest health row
 * rather than re-derived from a requested range - the same reasoning the
 * latency read gives.
 */
export async function fetchProviders(): Promise<ProviderBoardReport> {
  const data = await request<unknown>(`${OBSERVABILITY_BASE}/providers`);
  const report = guardShape(
    data,
    isProviderBoardReport,
    "The API returned an unexpected observability provider board shape",
  );
  return {
    ...report,
    providers: report.providers.map((provider) =>
      withDecimals(provider, PROVIDER_BOARD_DECIMALS),
    ),
  };
}

/**
 * Requests per minute and error rate over the capture window (#727).
 *
 * `minutes` is omitted when the caller has no preference, so the route's own
 * default is the one authority on what "no window asked for" means. The
 * `ge=1, le=1440` bounds are not restated here (coding-standards §9.2).
 */
export async function fetchThroughput(
  params: { minutes?: number } = {},
): Promise<ThroughputReport> {
  const search = new URLSearchParams();
  if (params.minutes !== undefined)
    search.set("minutes", String(params.minutes));
  const query = search.toString();
  const data = await request<unknown>(
    `${OBSERVABILITY_BASE}/throughput${query ? `?${query}` : ""}`,
  );
  const report = guardShape(
    data,
    isThroughputReport,
    "The API returned an unexpected observability throughput shape",
  );
  return {
    ...withDecimals(report, THROUGHPUT_DECIMALS),
    points: report.points.map((point) =>
      withDecimals(point, THROUGHPUT_POINT_DECIMALS),
    ),
    routes: report.routes.map((route) =>
      withDecimals(route, THROUGHPUT_ROUTE_DECIMALS),
    ),
  };
}

/**
 * Queue depth, the oldest queued job's age and recent actor activity (#729) -
 * the read behind the Reliability page's two queue panels.
 *
 * `minutes` narrows ONLY the recent-activity window; the queue figures are a
 * now-reading and are the same whatever window the caller asked for.
 */
export async function fetchReliability(
  params: { minutes?: number } = {},
): Promise<ReliabilityReport> {
  const search = new URLSearchParams();
  if (params.minutes !== undefined)
    search.set("minutes", String(params.minutes));
  const query = search.toString();
  const data = await request<unknown>(
    `${OBSERVABILITY_BASE}/reliability${query ? `?${query}` : ""}`,
  );
  return guardShape(
    data,
    isReliabilityReport,
    "The API returned an unexpected observability reliability shape",
  );
}

/**
 * One page of the collapsed live error feed (#730).
 *
 * `status` is narrow on purpose: the route takes `open` and `resolved` and
 * answers anything else with a 422, because an acknowledged FAILURE is still a
 * failure. `page` and `status` are omitted when unset so the route's own
 * defaults decide.
 */
export async function fetchErrors(
  params: {
    page?: number;
    page_size?: number;
    status?: ErrorFeedStatus;
    minutes?: number;
  } = {},
): Promise<ErrorFeedPage> {
  const search = new URLSearchParams();
  if (params.page !== undefined) search.set("page", String(params.page));
  if (params.page_size !== undefined) {
    search.set("page_size", String(params.page_size));
  }
  if (params.status) search.set("status", params.status);
  if (params.minutes !== undefined)
    search.set("minutes", String(params.minutes));
  const query = search.toString();
  const data = await request<unknown>(
    `${OBSERVABILITY_BASE}/errors${query ? `?${query}` : ""}`,
  );
  return guardShape(
    data,
    isErrorFeedPage,
    "The API returned an unexpected observability error feed shape",
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

/**
 * Acknowledge one alert (#735) and return the row as it now stands.
 *
 * A POST with NO body, deliberately: the route derives the acknowledging
 * operator from the caller's identity and would let a client write its own
 * `status` if one were sent. The caller still sends an `Idempotency-Key`
 * (api-standards §5) so a retry after a lost response cannot double-issue -
 * and the route is idempotent anyway, answering a repeat with
 * `already_acknowledged: true` rather than a second write.
 */
export async function acknowledgeAlert(
  alertId: string,
  retryKey?: string,
): Promise<AlertAcknowledgement> {
  const data = await request<unknown>(
    `${OBSERVABILITY_BASE}/alerts/${encodeURIComponent(alertId)}/acknowledge`,
    {
      method: "POST",
      headers: {
        [IDEMPOTENCY_KEY_HEADER]: idempotencyKey(retryKey),
      },
    },
  );
  return guardShape(
    data,
    isAlertAcknowledgement,
    "The API returned an unexpected alert acknowledgement shape",
  );
}

/**
 * The configured Grafana/Sentry/Langfuse link sets (#736). A vendor that is
 * switched off is absent from the response, and a vendor with nothing to filter on
 * is absent too - so a panel renders what it gets and never a broken href.
 *
 * `context` is optional and is passed straight through: the read derives every
 * filter from it, and nothing here reconstructs an identifier.
 */
export async function fetchDeeplinks(
  context: DeeplinkContext = {},
): Promise<Deeplinks> {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(context)) {
    if (value !== undefined) search.set(key, value);
  }
  const query = search.toString();
  const data = await request<unknown>(
    `${OBSERVABILITY_BASE}/deeplinks${query ? `?${query}` : ""}`,
  );
  return guardShape(
    data,
    isDeeplinks,
    "The API returned an unexpected observability deeplinks shape",
  );
}

// ------------------------------------------------ the security lens (#781)

/** One security signal kind's recent count and status. */
export interface SecuritySignalView {
  signal_kind: string;
  count_last_5m: number;
  threshold: number | null;
  alert_kind: string | null;
  is_deferred: boolean;
  deferred_reason: string | null;
}

/** One CSP directive's daily violation count. */
export interface CspAggregateView {
  directive: string;
  disposition: string;
  blocked_source: string;
  count: number;
}

/**
 * Operator security posture summary (PHASE-14B Batch 2, #781).
 *
 * Shows auth/lockout trends, consent/rate-limit anomalies, CSP violations,
 * prompt-injection counts, and webhook monitoring status.
 */
export interface SecuritySummary {
  signals: SecuritySignalView[];
  csp_aggregates: CspAggregateView[];
  prompt_injection_count: number;
  webhook_monitoring_status: string;
  webhook_monitoring_reason: string;
}

function isSecuritySignalView(value: unknown): value is SecuritySignalView {
  return (
    isRecord(value) &&
    hasKeys(value, [
      "signal_kind",
      "count_last_5m",
      "threshold",
      "alert_kind",
      "is_deferred",
      "deferred_reason",
    ])
  );
}

function isCspAggregateView(value: unknown): value is CspAggregateView {
  return (
    isRecord(value) &&
    hasKeys(value, ["directive", "disposition", "blocked_source", "count"])
  );
}

function isSecuritySummary(value: unknown): value is SecuritySummary {
  return (
    isRecord(value) &&
    hasKeys(value, [
      "signals",
      "csp_aggregates",
      "prompt_injection_count",
      "webhook_monitoring_status",
      "webhook_monitoring_reason",
    ]) &&
    isArrayOf(value.signals, isSecuritySignalView) &&
    isArrayOf(value.csp_aggregates, isCspAggregateView)
  );
}

/**
 * Read the operator security posture summary (#781).
 */
export async function fetchSecurity(): Promise<SecuritySummary> {
  const data = await request<unknown>(`${OBSERVABILITY_BASE}/security`);
  return guardShape(
    data,
    isSecuritySummary,
    "The API returned an unexpected security summary shape",
  );
}
