"use client";

// #709 C2b: the operator Cost panel's two charts (plan-phase14-observability
// §9.2).
//   * GET /v1/operator/observability/cost       -> spend against the cap, per
//     budget scope.
//   * GET /v1/operator/observability/cost/trend -> the daily spend series.
//
// Two deliberate chart choices, both about not hiding a bad number:
//   * The budget is a GROUPED pair of bars - the cap and what was spent - not a
//     stacked [spent|remaining] bar. A stacked bar's length is the cap, so an
//     over-budget scope has to be clamped and the overspend disappears exactly
//     when the operator most needs to see it; side by side, a spent bar that
//     runs past its cap IS the overspend, with no special case at all.
//   * The spent bar turns danger-coloured on an exhausted scope. Only the spend
//     bar is toned: an exhausted budget says nothing about whether latency is
//     fine or the alert feed is empty, and painting those red too reads as
//     "everything is broken" when the truth is "the bill is over".
//
// Money is paise on the wire (api-standards §3) and rupees everywhere on
// screen: every chart row is divided by 100 before it is plotted, and the axis
// and tooltip format rupees. A y-axis reading "1250000" is the bug this avoids.

import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ChartFigure,
  ChartTooltip,
  ChartTooltipContent,
  XAxis,
  YAxis,
} from "@/components/ui/chart";
import {
  formatRupees,
  rupeesFromPaise,
} from "@/lib/operator/observability-format";
import type {
  CostBudgetView,
  CostTrendPoint,
} from "@/lib/operator/observability";

/** One budget scope's two bars, in rupees. */
interface BudgetBar {
  scope: string;
  /** The cap for this period; 0 when nothing is budgeted for the scope. */
  cap: number;
  /** What the scope has actually spent. */
  spent: number;
  /** True when spend is at or past the cap - the danger fill. */
  exhausted: boolean;
}

/**
 * The scope's label. A budget scope is a `(provider, model)` pair, so both
 * halves name it; the provider alone is ambiguous across a model change and
 * the model alone is unreadable.
 */
function scopeLabel(budget: CostBudgetView): string {
  return `${budget.provider} · ${budget.model}`;
}

function budgetBars(budgets: CostBudgetView[]): BudgetBar[] {
  return budgets.map((budget) => ({
    scope: scopeLabel(budget),
    cap: rupeesFromPaise(budget.monthly_limit_paise),
    spent: rupeesFromPaise(budget.current_spend_paise),
    exhausted: budget.exhausted,
  }));
}

/**
 * Spend against the cap per scope. A scope with no cap plots a zero-length cap
 * bar and only its spend - "nothing is budgeted" and "nothing was spent" are
 * different facts, and drawing them as the same empty pair would invent a
 * budget that does not exist.
 */
export function CostBudgetChart({
  budgets,
  testId,
}: {
  budgets: CostBudgetView[];
  testId: string;
}) {
  const rows = budgetBars(budgets);
  const config = {
    cap: { label: "Budget cap", color: "var(--txt-muted)" },
    spent: { label: "Spent", color: "var(--accent)" },
    overspent: { label: "Overspent", color: "var(--danger)" },
  };

  return (
    <ChartFigure
      config={config}
      testId={testId}
      ariaLabel="AI spend against budget by scope"
      description={budgetDescription(rows)}
    >
      <BarChart data={rows} margin={{ left: 8, right: 8, top: 8 }}>
        <CartesianGrid vertical={false} />
        {/* interval={0}: recharts' default drops a category label that will not
            fit, which leaves a bar with no name - and an unnamed bar cannot be
            traced back to the provider/model it belongs to. */}
        <XAxis
          dataKey="scope"
          interval={0}
          tickLine={false}
          axisLine={false}
          fontSize={12}
        />
        <YAxis
          tickLine={false}
          axisLine={false}
          fontSize={12}
          width={64}
          tickFormatter={rupeesTick}
        />
        <ChartTooltip
          cursor={{ fill: "var(--hairline-soft)" }}
          content={
            <ChartTooltipContent
              formatter={(value) => formatRupees(Number(value))}
            />
          }
        />
        <Bar
          dataKey="cap"
          fill="var(--color-cap)"
          radius={[4, 4, 0, 0]}
          isAnimationActive={false}
        />
        <Bar dataKey="spent" radius={[4, 4, 0, 0]} isAnimationActive={false}>
          {rows.map((row) => (
            <Cell
              key={row.scope}
              fill={
                row.exhausted ? "var(--color-overspent)" : "var(--color-spent)"
              }
            />
          ))}
        </Bar>
      </BarChart>
    </ChartFigure>
  );
}

/** One day of the series, in rupees. */
interface TrendPoint {
  label: string;
  rupees: number;
}

/**
 * The y-axis ticks. recharts positions a tick by its value, so this formatter
 * is the only place the axis's currency appears - and it goes through
 * `formatRupees` rather than composing a symbol here, so the axis and the
 * tooltip cannot drift into two different renderings of one currency.
 */
const rupeesTick = (value: number) => formatRupees(value);

/**
 * The chart's text alternative: what is plotted and where each scope sits,
 * because a bar's length encodes a spend figure no screen reader can read off
 * the geometry.
 */
function budgetDescription(rows: BudgetBar[]): string {
  if (rows.length === 0) return "No budget scopes recorded.";
  return rows
    .map(
      (row) =>
        `${row.scope}: ${formatRupees(
          row.spent,
        )} spent against a ${formatRupees(row.cap)} cap` +
        (row.exhausted ? " - over budget" : ""),
    )
    .join("; ");
}

/** The trend chart's text alternative, in series order. */
function trendDescription(rows: TrendPoint[]): string {
  if (rows.length === 0) return "No spend recorded in this window.";
  return (
    "Daily AI spend: " +
    rows.map((row) => `${row.label} ${formatRupees(row.rupees)}`).join("; ")
  );
}

/**
 * `2026-10-12` -> `12 Oct`. The wire's ISO date is not a locale's date.
 *
 * recharts squeezes the whitespace out of a tick label to make it fit, so an
 * operator reads this as "12Oct". That is deliberate on recharts' part and is
 * why the separator is a plain space: a label with no space in it survives the
 * squeeze unchanged, and one with a `/` would come back half-stripped.
 *
 * Month names are spelled out rather than taken from `Intl.DateTimeFormat`:
 * an axis wants "Oct" in a fixed width, and a locale switch would change both
 * the width and the script mid-chart. The panel's own date range is where the
 * operator reads a full date.
 */
const MONTHS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
];

function trendLabel(usageDate: string): string {
  const [, month, day] = usageDate.split("-");
  return `${Number(day)} ${MONTHS[Number(month) - 1] ?? month}`;
}

/**
 * Daily AI spend over the window. Only the days the rollup actually recorded
 * carry a point (facade.CostTrend: "a day with no AI job carries no point at
 * all"), so the series draws the spend that happened and never invents a zero
 * for a gap - a zero-spiked line reads as "spend stopped" on a day the job
 * simply did not run.
 */
export function DailyCostTrendChart({
  points,
  testId,
}: {
  points: CostTrendPoint[];
  testId: string;
}) {
  const rows: TrendPoint[] = points.map((point) => ({
    label: trendLabel(point.usage_date),
    rupees: rupeesFromPaise(point.cost_paise),
  }));
  const config = {
    spend: { label: "Daily spend", color: "var(--accent)" },
  };

  return (
    <ChartFigure
      config={config}
      testId={testId}
      ariaLabel="Daily AI spend over the reporting window"
      description={trendDescription(rows)}
    >
      <AreaChart data={rows} margin={{ left: 8, right: 8, top: 8 }}>
        <CartesianGrid vertical={false} />
        {/* interval={0}: recharts' default drops a day label that will not
            fit, and a spend line with an unnamed point is a line the operator
            cannot date. */}
        <XAxis
          dataKey="label"
          interval={0}
          tickLine={false}
          axisLine={false}
          fontSize={12}
        />
        <YAxis
          tickLine={false}
          axisLine={false}
          fontSize={12}
          width={64}
          tickFormatter={rupeesTick}
        />
        <ChartTooltip
          cursor={{ stroke: "var(--hairline)" }}
          content={
            <ChartTooltipContent
              formatter={(value) => formatRupees(Number(value))}
            />
          }
        />
        <Area
          dataKey="rupees"
          type="monotone"
          stroke="var(--color-spend)"
          strokeWidth={2}
          fill="var(--color-spend)"
          fillOpacity={0.12}
          isAnimationActive={false}
        />
      </AreaChart>
    </ChartFigure>
  );
}
