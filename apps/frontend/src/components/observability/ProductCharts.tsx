"use client";

// #743: the Product lens page's presentational parts. Split out of the page for
// the reason BusinessCharts.tsx exists: the page owns which read feeds which
// panel, and the charts and tables own how one loaded read is read.
//
// Three deliberate choices, all about not inventing a fact:
//   * The adoption trend plots ONE field - active users per day - because
//     requests and people are different quantities and a second axis would let
//     a traffic spike or a quiet day look like an adoption change. The load per
//     head lives in the panel's figures, where it carries its own denominator.
//   * A day with nothing recorded is ABSENT from the series (the facade's own
//     rule), so a quiet stretch is a gap rather than a drawn dip to zero.
//   * A retention horizon that has not arrived prints the dash, never "0%". A
//     three-day-old cohort has not been given the chance to return on day
//     thirty; writing zero would fabricate a collapse at the newest end of the
//     only table where a real decline would be read next to it.
//
// Every import here is a named re-export from components/ui/chart.tsx, never
// `recharts` directly: the boundary is what stops two panels growing two
// palettes (chart.tsx §"the bundle boundary").

import {
  Bar,
  BarChart,
  CartesianGrid,
  ChartFigure,
  ChartTooltip,
  ChartTooltipContent,
  XAxis,
  YAxis,
} from "@/components/ui/chart";
import { cn } from "@/lib/utils";
import {
  DASH,
  formatCount,
  formatRate,
} from "@/lib/operator/observability-format";
import type {
  ActiveUsersDayPoint,
  FunnelStepRow,
  ProductOutcome,
  RetentionCohortDay,
} from "@/lib/operator/observability";

/**
 * The day label on the x-axis. Formatted at UTC for the same reason the
 * throughput chart is: the API stamps UTC, and a server-local reading would
 * shift the bars against the deployment's own logs.
 */
const DAY_FORMAT = new Intl.DateTimeFormat("en-GB", {
  day: "2-digit",
  month: "short",
  timeZone: "UTC",
});

function dayLabel(day: string): string {
  return DAY_FORMAT.format(new Date(`${day}T00:00:00Z`));
}

/**
 * The trend's text alternative. It says how many days were recorded and how
 * many were absent, because a short series and a sparse one read the same to a
 * screen reader otherwise.
 */
function trendDescription(points: ActiveUsersDayPoint[]): string {
  if (points.length === 0) return "No days with recorded activity to plot.";
  const total = points.reduce((sum, point) => sum + point.active_users, 0);
  return (
    `Daily active users over ${points.length} recorded day(s): ${formatCount(
      total,
    )} actor-days in total. Days with no recorded activity are absent from the ` +
    "series rather than plotted as zero."
  );
}

/** Daily active users, one bar per recorded day. */
export function ActiveUsersTrendChart({
  points,
  testId,
}: {
  points: ActiveUsersDayPoint[];
  testId: string;
}) {
  const data = points.map((point) => ({
    label: dayLabel(point.day),
    active: point.active_users,
  }));
  const config = {
    active: { label: "Active users", color: "var(--accent)" },
  };

  return (
    <ChartFigure
      config={config}
      testId={testId}
      ariaLabel="Daily active users"
      description={trendDescription(points)}
    >
      <BarChart data={data} margin={{ left: 8, right: 8, top: 8 }}>
        <CartesianGrid vertical={false} />
        <XAxis
          dataKey="label"
          interval="preserveStartEnd"
          tickLine={false}
          axisLine={false}
          fontSize={12}
        />
        <YAxis
          tickLine={false}
          axisLine={false}
          fontSize={12}
          width={40}
          allowDecimals={false}
        />
        <ChartTooltip
          cursor={{ fill: "var(--hairline-soft)" }}
          content={<ChartTooltipContent />}
        />
        <Bar
          dataKey="active"
          fill="var(--color-active)"
          radius={[4, 4, 0, 0]}
          isAnimationActive={false}
        />
      </BarChart>
    </ChartFigure>
  );
}

/** The outcomes the funnel control offers, in the registry's closed order. */
export const OUTCOME_FILTERS: { id: ProductOutcome | "all"; label: string }[] =
  [
    { id: "all", label: "All outcomes" },
    { id: "completed", label: "Completed" },
    { id: "abandoned", label: "Abandoned" },
    { id: "errored", label: "Errored" },
    { id: "re_recorded", label: "Re-recorded" },
  ];

/**
 * The funnel's outcome filter. `null` is the whole funnel; anything else asks
 * the route to narrow the STEPS to that path (the headline outcome block stays
 * whole-window, which the page says beside this control).
 */
export function OutcomeFilter({
  current,
  onSelect,
  testIdPrefix,
}: {
  current: ProductOutcome | null;
  onSelect: (outcome: ProductOutcome | null) => void;
  testIdPrefix: string;
}) {
  return (
    <div
      role="group"
      aria-label="Filter the funnel by outcome"
      className="flex flex-wrap gap-2"
      data-testid={`${testIdPrefix}-filter`}
    >
      {OUTCOME_FILTERS.map((filter) => {
        const selected =
          filter.id === "all" ? current === null : filter.id === current;
        return (
          <button
            key={filter.id}
            type="button"
            aria-pressed={selected}
            onClick={() =>
              onSelect(
                filter.id === "all" ? null : (filter.id as ProductOutcome),
              )
            }
            data-testid={`${testIdPrefix}-filter-${filter.id}`}
            className={cn(
              "inline-flex min-h-11 items-center rounded-md border px-3 text-xs font-medium",
              selected
                ? "border-accent-border bg-accent-soft text-accent-strong"
                : "border-hairline bg-surface text-txt-sub hover:bg-hairline-soft",
            )}
          >
            {filter.label}
          </button>
        );
      })}
    </div>
  );
}

/** The funnel table's shared header rule. */
const HEAD_CELL =
  "border-b border-hairline py-1.5 pr-3 text-left text-xs font-medium text-txt-muted";
const NUMBER_CELL = "py-1.5 pr-3 text-right tabular-nums";

/**
 * One step of the walk: how many arrived, how they left it, and how long they
 * thought between this step and the last.
 *
 * Every counter is printed even when zero, because "0 abandoned here" is a
 * fact about this step and a column an operator can compare across steps. The
 * conversion is a fraction; the first step has none and shows the dash.
 */
export function FunnelStepsTable({
  steps,
  testId,
}: {
  steps: FunnelStepRow[];
  testId: string;
}) {
  return (
    <table className="w-full text-sm" data-testid={testId}>
      <caption className="sr-only">
        Funnel steps: arrivals, outcomes, conversion from the previous step and
        median thinking time
      </caption>
      <thead>
        <tr>
          <th scope="col" className={HEAD_CELL}>
            Step
          </th>
          <th scope="col" className={cn(HEAD_CELL, "text-right")}>
            Entered
          </th>
          <th scope="col" className={cn(HEAD_CELL, "text-right")}>
            Completed
          </th>
          <th scope="col" className={cn(HEAD_CELL, "text-right")}>
            Abandoned
          </th>
          <th scope="col" className={cn(HEAD_CELL, "text-right")}>
            Errored
          </th>
          <th scope="col" className={cn(HEAD_CELL, "text-right")}>
            Re-recorded
          </th>
          <th scope="col" className={cn(HEAD_CELL, "text-right")}>
            From previous
          </th>
          <th scope="col" className={cn(HEAD_CELL, "text-right")}>
            Median gap
          </th>
        </tr>
      </thead>
      <tbody>
        {steps.map((step) => (
          <tr
            key={step.step}
            data-testid={`${testId}-row-${step.step}`}
            className="border-b border-hairline-soft last:border-0"
          >
            <th
              scope="row"
              className="py-1.5 pr-3 text-left font-medium text-txt"
            >
              {step.step}
            </th>
            <td
              className={NUMBER_CELL}
              data-testid={`${testId}-row-${step.step}-entered`}
            >
              {formatCount(step.entered)}
            </td>
            <td className={NUMBER_CELL}>{formatCount(step.completed)}</td>
            <td className={NUMBER_CELL}>{formatCount(step.abandoned)}</td>
            <td className={NUMBER_CELL}>{formatCount(step.errored)}</td>
            <td className={NUMBER_CELL}>{formatCount(step.re_recorded)}</td>
            <td
              className={NUMBER_CELL}
              data-testid={`${testId}-row-${step.step}-conversion`}
            >
              {formatRate(step.conversion_from_previous)}
            </td>
            <td className={NUMBER_CELL}>
              {step.median_gap_from_previous_s === null
                ? DASH
                : `${formatCount(step.median_gap_from_previous_s)}s`}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/**
 * One cell of the retention table. A null horizon is unmeasured, never zero;
 * an empty cohort is called out in its title rather than plotted as a total
 * loss of the cohort that was never there.
 */
function RetentionCell({
  retained,
  rate,
  cohortSize,
  horizon,
}: {
  retained: number | null;
  rate: number | null;
  cohortSize: number;
  horizon: number;
}) {
  if (cohortSize === 0) {
    return <span title="no arrivals on this date">{DASH}</span>;
  }
  if (retained === null || rate === null) {
    return <span title={`day ${horizon} not yet observed`}>{DASH}</span>;
  }
  return (
    <>
      {formatCount(retained)} · {formatRate(rate)}
    </>
  );
}

/** One row per arrival date, with both measured horizons beside their base. */
export function RetentionCohortsTable({
  cohorts,
  testId,
}: {
  cohorts: RetentionCohortDay[];
  testId: string;
}) {
  return (
    <table className="w-full text-sm" data-testid={testId}>
      <caption className="sr-only">
        Retention cohorts: actors who arrived on each date, and how many were
        active again on day seven and day thirty
      </caption>
      <thead>
        <tr>
          <th scope="col" className={HEAD_CELL}>
            Arrival date
          </th>
          <th scope="col" className={cn(HEAD_CELL, "text-right")}>
            New actors
          </th>
          <th scope="col" className={cn(HEAD_CELL, "text-right")}>
            Day 7
          </th>
          <th scope="col" className={cn(HEAD_CELL, "text-right")}>
            Day 30
          </th>
        </tr>
      </thead>
      <tbody>
        {cohorts.map((cohort) => (
          <tr
            key={cohort.cohort_date}
            data-testid={`${testId}-row-${cohort.cohort_date}`}
            className="border-b border-hairline-soft last:border-0"
          >
            <th
              scope="row"
              className="py-1.5 pr-3 text-left font-medium text-txt"
            >
              {cohort.cohort_date}
            </th>
            <td className={NUMBER_CELL}>{formatCount(cohort.cohort_size)}</td>
            <td
              className={NUMBER_CELL}
              data-testid={`${testId}-row-${cohort.cohort_date}-day7`}
            >
              <RetentionCell
                retained={cohort.retained_7d}
                rate={cohort.retention_7d}
                cohortSize={cohort.cohort_size}
                horizon={7}
              />
            </td>
            <td
              className={NUMBER_CELL}
              data-testid={`${testId}-row-${cohort.cohort_date}-day30`}
            >
              <RetentionCell
                retained={cohort.retained_30d}
                rate={cohort.retention_30d}
                cohortSize={cohort.cohort_size}
                horizon={30}
              />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
