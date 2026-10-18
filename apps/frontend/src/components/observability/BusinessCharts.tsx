"use client";

// #737: the Business lens page's three charts. All three plot one field of the
// single `/business` read (#731 spend and breakdown, #732 unit costs and
// attribution).
//
// Three deliberate chart choices, all about not hiding a bad number:
//   * The cap is a GROUPED pair of bars - consumed against cap - not a stacked
//     [consumed|remaining] bar, for the reason CostCharts gives: a stacked bar's
//     length IS the cap, so the overspend has to be clamped and disappears
//     exactly when the operator needs it. Grouped, a consumed bar running past
//     its cap is the overspend, with no special case.
//   * The projected month-end burn is a THIRD bar beside the two, not a line
//     drawn over them. A projection is a claim about a day that has not
//     happened; plotting it in the same ink as a measured bar would let an
//     operator read a guess as a fact. It is toned differently and labelled in
//     the text alternative as projected.
//   * Money is paise on the wire and rupees on screen, divided before plotting -
//     an axis reading "1250000" is the bug this avoids.
//
// Every import here is a named re-export from components/ui/chart.tsx, never
// `recharts` directly: the boundary is what stops two panels growing two
// palettes (chart.tsx §"the bundle boundary").

import {
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
  DASH,
  formatRupees,
  formatUnitCost,
  rupeesFromPaise,
} from "@/lib/operator/observability-format";
import type { BusinessRead } from "@/lib/operator/observability";

/**
 * The y-axis formatter. recharts positions a tick by its value, so this is the
 * only place the axis's currency appears - and it goes through `formatRupees`
 * like the tooltip does, so the axis and the tooltip cannot drift into two
 * renderings of one currency.
 */
const rupeesTick = (value: number) => formatRupees(value);

interface BudgetBar {
  label: string;
  /** What the billing month has consumed so far. */
  consumed: number;
  /** The cap for the billing month. Zero when nothing is capped. */
  cap: number;
  /** The projected month-end burn, or null when there is no stamped period. */
  projected: number | null;
  /** True when the projection lands past the cap - the danger fill. */
  overCap: boolean;
}

function budgetBars(read: BusinessRead): BudgetBar[] {
  return [
    {
      label: "Consumed",
      consumed: rupeesFromPaise(read.cap_consumed_paise),
      cap: rupeesFromPaise(read.monthly_cap_paise),
      projected:
        read.projected_month_end_paise === null
          ? null
          : rupeesFromPaise(read.projected_month_end_paise),
      overCap: read.projected_over_cap,
    },
  ];
}

/**
 * The bar chart's text alternative. It says which bar is measured and which is
 * projected, because that distinction is the one an operator most needs and the
 * one a bar's geometry cannot carry.
 */
function budgetDescription(rows: BudgetBar[]): string {
  return rows
    .map((row) => {
      const projected =
        row.projected === null
          ? "no projection for this period"
          : `projected month end ${formatRupees(row.projected)}`;
      return (
        `${row.label}: ${formatRupees(row.consumed)} consumed against a ` +
        `${formatRupees(row.cap)} cap, ${projected}` +
        (row.overCap ? " - over cap" : "")
      );
    })
    .join("; ");
}

/**
 * Spend against the monthly cap, with the month-end projection beside it.
 *
 * The cap row is empty when nothing is budgeted, and the consumed bar is still
 * drawn: "nothing is capped" and "nothing was spent" are different facts, and a
 * scope with neither would look like the other.
 */
export function SpendAgainstCapChart({
  read,
  testId,
}: {
  read: BusinessRead;
  testId: string;
}) {
  const rows = budgetBars(read);
  const config = {
    consumed: { label: "Consumed", color: "var(--accent)" },
    cap: { label: "Monthly cap", color: "var(--txt-muted)" },
    projected: { label: "Projected month end", color: "var(--txt-sub)" },
    overspent: { label: "Projected over cap", color: "var(--danger)" },
  };

  return (
    <ChartFigure
      config={config}
      testId={testId}
      ariaLabel="AI spend against the monthly cap, with the projected month-end burn"
      description={budgetDescription(rows)}
    >
      <BarChart data={rows} margin={{ left: 8, right: 8, top: 8 }}>
        <CartesianGrid vertical={false} />
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
        <Bar dataKey="consumed" radius={[4, 4, 0, 0]} isAnimationActive={false}>
          {rows.map((row) => (
            <Cell key={row.label} fill="var(--color-consumed)" />
          ))}
        </Bar>
        {/* The projection only carries a bar when there is a stamped period to
            extrapolate from; a zero-length "projection" would read as a forecast
            of no spend at all. */}
        {rows.some((row) => row.projected !== null) && (
          <Bar
            dataKey="projected"
            radius={[4, 4, 0, 0]}
            isAnimationActive={false}
          >
            {rows.map((row) => (
              <Cell
                key={row.label}
                fill={
                  row.overCap
                    ? "var(--color-overspent)"
                    : "var(--color-projected)"
                }
              />
            ))}
          </Bar>
        )}
      </BarChart>
    </ChartFigure>
  );
}

/** One task type's share of the bill, in rupees. */
interface TaskTypeBar {
  task: string;
  rupees: number;
}

/**
 * Spend by task type. Task type is the axis rather than provider because it is
 * the one grain an operator can act on: "transcribe is 80% of the bill" is a
 * product conversation, while "openai_compatible is 80% of the bill" is a fact
 * about a vendor the operator already chose.
 */
export function SpendByTaskTypeChart({
  rows,
  testId,
}: {
  rows: BusinessRead["by_task_type"];
  testId: string;
}) {
  const bars: TaskTypeBar[] = rows.map((row) => ({
    task: row.task_type,
    rupees: rupeesFromPaise(row.spend_paise),
  }));
  const config = {
    spend: { label: "AI spend", color: "var(--accent)" },
  };

  return (
    <ChartFigure
      config={config}
      testId={testId}
      ariaLabel="AI spend by task type"
      description={
        bars.length === 0
          ? "No AI spend by task type in this window."
          : "AI spend by task type: " +
            bars
              .map((row) => `${row.task} ${formatRupees(row.rupees)}`)
              .join("; ")
      }
    >
      <BarChart data={bars} margin={{ left: 8, right: 8, top: 8 }}>
        <CartesianGrid vertical={false} />
        {/* interval={0}: recharts' default drops a label that will not fit, and a
            bar with no name cannot be traced back to the task it belongs to. */}
        <XAxis
          dataKey="task"
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
          dataKey="rupees"
          fill="var(--color-spend)"
          radius={[4, 4, 0, 0]}
          isAnimationActive={false}
        />
      </BarChart>
    </ChartFigure>
  );
}

/**
 * The two heavy-actor tables, as a list rather than a plot.
 *
 * A ranked table is the honest form for this panel: the question is "who is
 * heavy", and the answer is a name, a figure and a job count read against the
 * population - none of which a bar encodes better than a row of text. A chart
 * here would also have to plot pseudonymous hashes on an axis, which reads as
 * identity rather than as the join key it is.
 *
 * Keys are rendered as SHOWN - the platform's own pseudonymous hashes - because
 * they are the join key an operator hands the deep-links panel, and inventing a
 * display name for a hash is how PHI ends up in a console.
 */
export function HeavyActorList({
  title,
  rows,
  testId,
}: {
  title: string;
  rows: { key: string; detail: string; spend_paise: number }[];
  testId: string;
}) {
  return (
    <div data-testid={testId}>
      <h3 className="text-xs font-medium uppercase tracking-wide text-txt-sub">
        {title}
      </h3>
      {rows.length === 0 ? (
        <p className="mt-1 text-sm text-txt-muted">
          No attributed actors in this window.
        </p>
      ) : (
        <ul className="mt-1 flex flex-col gap-1">
          {rows.map((row) => (
            <li
              key={row.key}
              data-testid={`${testId}-row-${row.key}`}
              className="flex flex-wrap items-baseline justify-between gap-2 text-sm"
            >
              <span className="font-mono text-xs text-txt">{row.key}</span>
              <span className="text-txt-muted">{row.detail}</span>
              <span className="font-medium text-txt">
                {formatRupees(rupeesFromPaise(row.spend_paise))}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/**
 * The unit-cost line, as text rather than a plot. Five rates of different
 * magnitudes ("₹10.42 per request", "₹250.00 per patient") on one shared axis
 * would put four of them on the baseline, and a bar chart whose bars are all
 * effectively zero tells the operator nothing they could not get wrong.
 *
 * `formatUnitCost`, not `formatMoney`: these are rates, and the whole-rupee
 * price rule would print a real per-request cost as "₹0".
 */
export function UnitCostsList({
  read,
  testId,
}: {
  read: BusinessRead;
  testId: string;
}) {
  const units: { label: string; paise: number | null }[] = [
    { label: "Per request", paise: read.cost_per_request_paise },
    { label: "Per completed task", paise: read.cost_per_completed_task_paise },
    { label: "Per patient", paise: read.cost_per_patient_paise },
    { label: "Per doctor", paise: read.cost_per_doctor_paise },
    { label: "Cost of pass", paise: read.cost_of_pass_paise },
  ];

  return (
    <dl data-testid={testId} className="flex flex-col gap-1">
      {units.map((unit) => (
        <div
          key={unit.label}
          className="flex flex-wrap items-baseline justify-between gap-2 text-sm"
        >
          <dt className="text-txt-sub">{unit.label}</dt>
          {/* An unmeasured unit cost is the dash, never ₹0.00: a division with a
              zero denominator means "not measured", and "free" is a claim. */}
          <dd
            data-testid={`${testId}-${slug(unit.label)}`}
            className="font-medium text-txt"
          >
            {unit.paise === null ? DASH : formatUnitCost(unit.paise)}
          </dd>
        </div>
      ))}
    </dl>
  );
}

/** A stable test id for a unit-cost row: "Per completed task" -> `per-completed-task`. */
function slug(label: string): string {
  return label
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/(^-|-$)/g, "");
}
