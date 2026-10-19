"use client";

// #743: the operator Product lens page (spec #717, plan-phase14 §9.2).
// Three panels, THREE reads - unlike the Business lens, these are three
// different questions about three different grains, and no one of them can be
// derived from another:
//   * "Is adoption growing?"      <- DAU, WAU, MAU, stickiness and load per
//                                     head. GET .../product/active-users
//   * "Where do people leave?"    <- the stepped funnel and its outcomes, with
//                                     a filter that isolates one path.
//                                     GET .../product/funnel
//   * "Do they come back?"        <- seven- and thirty-day cohorts.
//                                     GET .../product/retention-cohorts
// Plus the shared deep-links panel, so the page is not a dead end.
//
// Each panel owns its read and therefore its own loading, empty, error and
// retry states (blueprint §9.1). The frame is ReadPanel, unchanged: this page
// contributes its reads, its copy, its tables and one chart, nothing else.
//
// The adoption panel prints MAU as the system of record computes it. The free
// vendor tier keeps fourteen days, so a vendor "monthly" figure is either a
// truncation or an invention; the product event ledger in Postgres is the one
// source that can answer a thirty-day question, and the panel says so beside
// the number rather than leaving an operator to assume it.

import { useEffect, useRef, useState } from "react";

import { DeeplinksPanel } from "@/components/observability/DeeplinksPanel";
import {
  ObservabilityPanelPage,
  ReadPanel,
} from "@/components/observability/ObservabilityPanelPage";
import {
  ActiveUsersTrendChart,
  FunnelStepsTable,
  OutcomeFilter,
  RetentionCohortsTable,
} from "@/components/observability/ProductCharts";
import {
  fetchActiveUsers,
  fetchDeeplinks,
  fetchFunnel,
  fetchRetentionCohorts,
  type ActiveUsersRead,
  type FunnelRead,
  type ProductOutcome,
  type RetentionCohortDay,
  type RetentionCohortsRead,
} from "@/lib/operator/observability";
import {
  DASH,
  formatCount,
  formatRate,
} from "@/lib/operator/observability-format";
import { usePanelRead, type PanelRead } from "@/lib/operator/usePanelRead";

/** No active actor in any window and no recorded day: nothing to plot. */
const NO_ACTIVE_USERS_BODY =
  "No qualifying clinical action was recorded in this window.";

/** The funnel saw no arrivals at all - a different fact from an empty path. */
const NO_FUNNEL_BODY =
  "No journey reached the funnel in this window, so there is no success or abandonment to report.";

/** The retention window covers no cohort dates. */
const NO_COHORTS_BODY =
  "The window covers no arrival dates, so there is no retention to report.";

/** How each outcome is named in copy, in the registry's vocabulary. */
const OUTCOME_LABELS: Record<ProductOutcome, string> = {
  completed: "completed",
  abandoned: "abandoned",
  errored: "errored",
  re_recorded: "re-recorded",
};

/**
 * A panel read that re-runs when the page changes the QUESTION it asked - here
 * the funnel's outcome filter.
 *
 * The same seam the Reliability lens uses, for the same reason: `usePanelRead`
 * fires once on mount and then only on Retry, because its loader is held in a
 * ref. A read whose parameters live in page state needs the ref to stay fresh
 * AND an effect that re-runs it when the key changes. The first render is
 * skipped explicitly - the hook's own mount effect has already fired, and a
 * second read there would double every request the page makes on load.
 */
function useKeyedRead<T>(load: () => Promise<T>, key: string): PanelRead<T> {
  const read = usePanelRead(load);
  const reload = read.reload;
  const mounted = useRef(false);

  useEffect(() => {
    if (!mounted.current) {
      mounted.current = true;
      return;
    }
    reload();
  }, [key, reload]);

  return read;
}

/**
 * The adoption panel's one line. All five figures, because they are one
 * question: the three counts are three actor sets, the stickiness is the daily
 * habit against the monthly base, and the per-head figure is the load those
 * people carried.
 */
function activeUsersTakeaway(read: ActiveUsersRead): string {
  const perHead =
    read.requests_per_active_user === null
      ? DASH
      : read.requests_per_active_user.toFixed(2);
  return (
    `${formatCount(read.daily_active_users.total)} DAU · ` +
    `${formatCount(read.weekly_active_users.total)} WAU · ` +
    `${formatCount(read.monthly_active_users.total)} MAU · ` +
    `${formatRate(read.stickiness)} stickiness · ` +
    `${formatCount(read.requests)} requests · ` +
    `${perHead} per active user`
  );
}

/** The funnel's headline pair, always quoted together over one denominator. */
function funnelTakeaway(read: FunnelRead): string {
  return (
    `${formatCount(read.outcomes.started)} started · ` +
    `${formatRate(read.outcomes.task_success_rate)} task success · ` +
    `${formatRate(read.outcomes.abandonment_rate)} abandonment`
  );
}

/**
 * The pooled retention over every cohort old enough to have been measured.
 *
 * Pooled, not a mean of rates: a cohort of nine and a cohort of nine thousand
 * cannot contribute equally to "how much of last month came back", and averaging
 * their rates would let the small one speak as loudly as the large one. A
 * horizon with no measured cohort is the dash, never 0%.
 */
function pooledRetention(
  cohorts: RetentionCohortDay[],
  horizon: 7 | 30,
): number | null {
  let retained = 0;
  let base = 0;
  for (const cohort of cohorts) {
    const count = horizon === 7 ? cohort.retained_7d : cohort.retained_30d;
    if (count === null || cohort.cohort_size === 0) continue;
    retained += count;
    base += cohort.cohort_size;
  }
  return base === 0 ? null : retained / base;
}

function retentionTakeaway(read: RetentionCohortsRead): string {
  return (
    `${read.cohorts.length} arrival dates · ` +
    `pooled 7-day ${formatRate(pooledRetention(read.cohorts, 7))} · ` +
    `pooled 30-day ${formatRate(pooledRetention(read.cohorts, 30))}`
  );
}

/** A window's dates, spelled out so a figure is never quoted windowless. */
function windowLine(from: string, to: string, detail: string): string {
  return `${from} to ${to} · ${detail}`;
}

/** The funnel's window stamps are datetimes; the operator reads the dates. */
function isoDate(timestamp: string): string {
  return timestamp.slice(0, 10);
}

export default function ObservabilityProductPage() {
  const activeUsers = usePanelRead(() => fetchActiveUsers());
  const retention = usePanelRead(() => fetchRetentionCohorts());
  const [outcome, setOutcome] = useState<ProductOutcome | null>(null);
  // The filter is panel-level state, not URL state: it changes the question
  // this panel asks, and a shared link is the IA work's job (#744). The
  // headline outcome block is NOT narrowed by it - the route is explicit about
  // that, and the note beside the control says so.
  const funnel = useKeyedRead(
    () => fetchFunnel(outcome === null ? {} : { outcome }),
    outcome ?? "all",
  );
  // The product reads carry no trace id of their own, so this panel asks with
  // no invented context and lets the vendors render their own default views.
  const deeplinks = usePanelRead(() => fetchDeeplinks());

  const adoption = activeUsers.data;
  const funnelRead = funnel.data;
  const retentionRead = retention.data;

  return (
    <ObservabilityPanelPage
      current="product"
      title="Product"
      description="Whether people arrive, keep coming back and finish what they start."
    >
      <div className="flex flex-col gap-4">
        <ReadPanel
          testId="product-active-users"
          title="Who is active, and how much they do"
          read={activeUsers}
          isEmpty={(data) =>
            data.daily_active_users.total === 0 &&
            data.weekly_active_users.total === 0 &&
            data.monthly_active_users.total === 0 &&
            data.trend.length === 0
          }
          emptyTitle="No active users in this window"
          emptyBody={NO_ACTIVE_USERS_BODY}
          errorMessage="Could not load active users and throughput."
          takeaway={adoption ? activeUsersTakeaway(adoption) : undefined}
        >
          {(data) => (
            <div className="flex flex-col gap-4">
              <p
                data-testid="product-active-users-window"
                className="text-xs text-txt-muted"
              >
                {windowLine(data.from_date, data.to_date, `${data.days} days`)}
              </p>
              <dl className="flex flex-col gap-1">
                <div className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
                  <dt className="text-txt-sub">
                    Daily active users ({data.daily_active_users.from_date} to{" "}
                    {data.daily_active_users.to_date})
                  </dt>
                  <dd
                    className="font-medium text-txt"
                    data-testid="product-active-users-dau"
                  >
                    {formatCount(data.daily_active_users.total)}
                  </dd>
                </div>
                <div className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
                  <dt className="text-txt-sub">
                    Weekly active users ({data.weekly_active_users.from_date} to{" "}
                    {data.weekly_active_users.to_date})
                  </dt>
                  <dd
                    className="font-medium text-txt"
                    data-testid="product-active-users-wau"
                  >
                    {formatCount(data.weekly_active_users.total)}
                  </dd>
                </div>
                <div className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
                  <dt className="text-txt-sub">
                    Monthly active users ({data.monthly_active_users.from_date}{" "}
                    to {data.monthly_active_users.to_date})
                  </dt>
                  <dd
                    className="font-medium text-txt"
                    data-testid="product-active-users-mau"
                  >
                    {formatCount(data.monthly_active_users.total)}
                  </dd>
                </div>
                <div className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
                  <dt className="text-txt-sub">Stickiness (DAU / MAU)</dt>
                  <dd
                    className="font-medium text-txt"
                    data-testid="product-active-users-stickiness"
                  >
                    {formatRate(data.stickiness)}
                  </dd>
                </div>
                <div className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
                  <dt className="text-txt-sub">Requests this window</dt>
                  <dd
                    className="font-medium text-txt"
                    data-testid="product-active-users-requests"
                  >
                    {formatCount(data.requests)}
                  </dd>
                </div>
                <div className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
                  <dt className="text-txt-sub">
                    Requests per active user (over the window,{" "}
                    {formatCount(data.window_active_users.total)} actors)
                  </dt>
                  <dd
                    className="font-medium text-txt"
                    data-testid="product-active-users-per-head"
                  >
                    {data.requests_per_active_user === null
                      ? DASH
                      : data.requests_per_active_user.toFixed(2)}
                  </dd>
                </div>
              </dl>
              <p
                data-testid="product-active-users-mau-source"
                className="text-xs text-txt-muted"
              >
                MAU is counted in Postgres, in the product event ledger, over
                the rolling thirty days above. It is not truncated to the
                fourteen-day retention of the vendor metrics tier.
              </p>
              <ActiveUsersTrendChart
                points={data.trend}
                testId="product-active-users-chart"
              />
            </div>
          )}
        </ReadPanel>

        <ReadPanel
          testId="product-funnel"
          title="Did the workflow finish?"
          read={funnel}
          isEmpty={(data) =>
            data.outcomes.started === 0 && data.steps.length === 0
          }
          emptyTitle="No journey reached the funnel in this window"
          emptyBody={NO_FUNNEL_BODY}
          errorMessage="Could not load the intake funnel."
          controls={
            <OutcomeFilter
              current={outcome}
              onSelect={setOutcome}
              testIdPrefix="product-funnel"
            />
          }
          takeaway={funnelRead ? funnelTakeaway(funnelRead) : undefined}
        >
          {(data) => (
            <div className="flex flex-col gap-4">
              <p
                data-testid="product-funnel-window"
                className="text-xs text-txt-muted"
              >
                {windowLine(
                  isoDate(data.window_start),
                  isoDate(data.window_end),
                  `${data.window_days} days`,
                )}
              </p>
              <dl
                data-testid="product-funnel-outcomes"
                className="flex flex-col gap-1"
              >
                <div className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
                  <dt className="text-txt-sub">Started</dt>
                  <dd className="font-medium text-txt">
                    {formatCount(data.outcomes.started)}
                  </dd>
                </div>
                <div className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
                  <dt className="text-txt-sub">Task success</dt>
                  <dd
                    className="font-medium text-txt"
                    data-testid="product-funnel-success-rate"
                  >
                    {formatRate(data.outcomes.task_success_rate)}
                  </dd>
                </div>
                <div className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
                  <dt className="text-txt-sub">Abandonment</dt>
                  <dd
                    className="font-medium text-txt"
                    data-testid="product-funnel-abandonment-rate"
                  >
                    {formatRate(data.outcomes.abandonment_rate)}
                  </dd>
                </div>
                <div className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
                  <dt className="text-txt-sub">
                    Issued e-prescriptions / cases closed
                  </dt>
                  <dd
                    className="font-medium text-txt"
                    data-testid="product-funnel-prescriptions"
                  >
                    {formatCount(data.outcomes.issued_e_prescriptions)} /{" "}
                    {formatCount(data.outcomes.cases_closed)}
                  </dd>
                </div>
                <div className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
                  <dt className="text-txt-sub">
                    Abandoned / errored / re-recorded
                  </dt>
                  <dd
                    className="font-medium text-txt"
                    data-testid="product-funnel-step-outcomes"
                  >
                    {formatCount(data.outcomes.abandoned)} /{" "}
                    {formatCount(data.outcomes.errored)} /{" "}
                    {formatCount(data.outcomes.re_recorded)}
                  </dd>
                </div>
              </dl>
              <p className="text-xs text-txt-muted">
                Both rates divide the same started count and are not
                complements: a journey can abandon, be re-recorded and still
                finish. An errored step is a degraded fallback, not a quiet
                abandonment.
              </p>
              {outcome !== null && (
                <p
                  data-testid="product-funnel-filter-note"
                  className="text-xs text-txt-muted"
                >
                  The filter narrows the steps below. The headline rates above
                  still cover the whole window.
                </p>
              )}
              {data.steps.length === 0 ? (
                <p
                  data-testid="product-funnel-no-steps"
                  className="text-sm text-txt-sub"
                >
                  No step in this window recorded the{" "}
                  {outcome === null ? "selected" : OUTCOME_LABELS[outcome]}{" "}
                  outcome.
                </p>
              ) : (
                <FunnelStepsTable
                  steps={data.steps}
                  testId="product-funnel-steps"
                />
              )}
            </div>
          )}
        </ReadPanel>

        <ReadPanel
          testId="product-retention"
          title="Do they come back?"
          read={retention}
          isEmpty={(data) => data.cohorts.length === 0}
          emptyTitle="No arrival dates in this window"
          emptyBody={NO_COHORTS_BODY}
          errorMessage="Could not load the retention cohorts."
          takeaway={
            retentionRead ? retentionTakeaway(retentionRead) : undefined
          }
        >
          {(data) => (
            <div className="flex flex-col gap-4">
              <p
                data-testid="product-retention-window"
                className="text-xs text-txt-muted"
              >
                {windowLine(
                  data.from_date,
                  data.to_date,
                  `${data.cohorts.length} arrival dates · day ${data.horizons[0]} and day ${data.horizons[1]}`,
                )}
              </p>
              <RetentionCohortsTable
                cohorts={data.cohorts}
                testId="product-retention-table"
              />
              <p
                data-testid="product-retention-maturity"
                className="text-xs text-txt-muted"
              >
                A dash is a horizon that has not arrived yet, or a date on which
                nobody arrived. It is never a zero: "not observed" and "nobody
                came back" are different facts.
              </p>
            </div>
          )}
        </ReadPanel>

        <DeeplinksPanel read={deeplinks} />
      </div>
    </ObservabilityPanelPage>
  );
}
