"use client";

// #709 C2b: the operator Usage panel's two charts (plan-phase14-observability
// §9.2), both over GET /v1/operator/observability/usage.
//
// ONE bar per usage scope, not a stack coloured by task. That is the load-
// bearing decision here: `task_type` is a bare `String(30)` in
// `obs_ai_usage_daily` with no CHECK constraint, so observability carries
// whatever the producer published and a new AI task appears here without a
// frontend change. A stacked chart would need a colour per task, and a palette
// that runs out silently re-colours two tasks the same shade - the reader then
// reads two different tasks as one. One scope per bar and one colour cannot lie
// that way: the scope label on the axis names exactly what the bar is.
//
// Scopes are `(provider, model, task_type)` triples, so all three name the bar.
// Sorted by calls descending, because the question this panel answers is "where
// is the volume going", and the busiest scope belongs at the top.

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

import { formatMoney } from "@/lib/operator/observability-format";
import type { UsageRow } from "@/lib/operator/observability";

/**
 * A whole-number count, grouped for the axis and tooltip.
 *
 * recharts positions a tick by its value, so grouping has to happen in the
 * formatter rather than in the plotted number - plotting a pre-grouped string
 * would make recharts treat the axis as categorical and lose the scale. Counts
 * on this panel are integers by nature (calls, tokens), so there is no
 * fractional case to lose.
 */
const count = (value: number): string => value.toLocaleString("en-IN");

/** One usage scope's row, flattened for plotting. */
interface ScopeRow {
  scope: string;
  calls: number;
  inputTokens: number;
  outputTokens: number;
  /** Kept in paise: only the table formats it, and a plot needs rupees. */
  costPaise: number;
}

function scopeLabel(row: UsageRow): string {
  return `${row.provider} · ${row.model} · ${row.task_type}`;
}

function scopeRows(rows: UsageRow[]): ScopeRow[] {
  return (
    rows
      .map((row) => ({
        scope: scopeLabel(row),
        calls: row.calls,
        inputTokens: row.input_tokens,
        outputTokens: row.output_tokens,
        costPaise: row.cost_paise,
      }))
      // Busiest first. A stable tiebreak on the label keeps two equal-count
      // scopes from swapping places between renders.
      .sort((a, b) => b.calls - a.calls || a.scope.localeCompare(b.scope))
  );
}

/**
 * The calls chart's text alternative. The scope label is spelled out in full
 * rather than abbreviated the way a squeezed axis tick is, because this is the
 * one rendering of the chart a screen reader gets.
 */
function callsDescription(data: ScopeRow[]): string {
  if (data.length === 0) return "No usage recorded in this window.";
  return (
    "AI calls by scope: " +
    data.map((row) => `${row.scope} ${count(row.calls)} calls`).join("; ")
  );
}

/** The tokens chart's text alternative, input and output per scope. */
function tokensDescription(data: ScopeRow[]): string {
  if (data.length === 0) return "No usage recorded in this window.";
  return (
    "AI tokens by scope: " +
    data
      .map(
        (row) =>
          `${row.scope} ${count(row.inputTokens)} input, ${count(
            row.outputTokens,
          )} output`,
      )
      .join("; ")
  );
}

/**
 * Calls per usage scope. Laid out horizontally because the scope labels are
 * long triples - on a vertical bar chart they would be rotated or truncated,
 * and a truncated scope name is a wrong scope name.
 */
export function CallsByScopeChart({
  rows,
  testId,
}: {
  rows: UsageRow[];
  testId: string;
}) {
  const data = scopeRows(rows);
  const config = {
    calls: { label: "AI calls", color: "var(--accent)" },
  };

  return (
    <ChartFigure
      config={config}
      testId={testId}
      ariaLabel="AI calls by provider, model and task"
      description={callsDescription(data)}
    >
      <BarChart
        data={data}
        layout="vertical"
        margin={{ left: 8, right: 16, top: 8 }}
      >
        <CartesianGrid horizontal={false} />
        <XAxis type="number" tickLine={false} axisLine={false} fontSize={12} />
        <YAxis
          type="category"
          dataKey="scope"
          interval={0}
          tickLine={false}
          axisLine={false}
          fontSize={12}
          width={168}
        />
        <ChartTooltip
          cursor={{ fill: "var(--hairline-soft)" }}
          content={
            <ChartTooltipContent formatter={(value) => count(Number(value))} />
          }
        />
        <Bar
          dataKey="calls"
          fill="var(--color-calls)"
          radius={[0, 4, 4, 0]}
          isAnimationActive={false}
        />
      </BarChart>
    </ChartFigure>
  );
}

/**
 * Tokens per scope, input against output. Two bounded series, so the stacked
 * pair is honest here: the rollup counts them independently and their sum is
 * the scope's total token spend. The bars share one row order with the calls
 * chart above, so an operator reading down the page compares the same scope in
 * the same position.
 */
export function TokensByScopeChart({
  rows,
  testId,
}: {
  rows: UsageRow[];
  testId: string;
}) {
  const data = scopeRows(rows);
  const config = {
    input: { label: "Input tokens", color: "var(--accent)" },
    output: { label: "Output tokens", color: "var(--warm)" },
  };

  return (
    <ChartFigure
      config={config}
      testId={testId}
      ariaLabel="AI tokens by provider, model and task"
      description={tokensDescription(data)}
    >
      <BarChart
        data={data}
        layout="vertical"
        margin={{ left: 8, right: 16, top: 8 }}
      >
        <CartesianGrid horizontal={false} />
        <XAxis
          type="number"
          tickLine={false}
          axisLine={false}
          fontSize={12}
          tickFormatter={(value: number) => `${Math.round(value / 1000)}k`}
        />
        <YAxis
          type="category"
          dataKey="scope"
          interval={0}
          tickLine={false}
          axisLine={false}
          fontSize={12}
          width={168}
        />
        <ChartTooltip
          cursor={{ fill: "var(--hairline-soft)" }}
          content={
            <ChartTooltipContent formatter={(value) => count(Number(value))} />
          }
        />
        <Bar
          dataKey="inputTokens"
          stackId="tokens"
          fill="var(--color-input)"
          isAnimationActive={false}
        />
        <Bar
          dataKey="outputTokens"
          stackId="tokens"
          fill="var(--color-output)"
          radius={[0, 4, 4, 0]}
          isAnimationActive={false}
        />
      </BarChart>
    </ChartFigure>
  );
}

/**
 * The per-scope money line under the charts. Cost is shown here rather than as
 * a third chart on purpose: it is the one figure that is always a handful of
 * rows wide and always already carried on the Cost panel, so a whole plot
 * devoted to it would be the page's biggest element for its least-new
 * information.
 */
export function ScopeCostTable({ rows }: { rows: UsageRow[] }) {
  const data = scopeRows(rows);

  return (
    <table className="w-full text-sm" data-testid="usage-scope-costs">
      <caption className="sr-only">
        AI spend by provider, model and task
      </caption>
      <thead>
        <tr className="border-b border-hairline text-left text-xs text-txt-muted">
          <th scope="col" className="py-1.5 pr-3 font-medium">
            Scope
          </th>
          <th scope="col" className="py-1.5 pr-3 text-right font-medium">
            Calls
          </th>
          <th scope="col" className="py-1.5 text-right font-medium">
            Spend
          </th>
        </tr>
      </thead>
      <tbody>
        {data.map((row) => (
          <tr key={row.scope} className="border-b border-hairline-soft">
            <th
              scope="row"
              className="py-1.5 pr-3 text-left font-normal text-txt"
            >
              {row.scope}
            </th>
            <td className="py-1.5 pr-3 text-right tabular-nums text-txt-sub">
              {count(row.calls)}
            </td>
            <td className="py-1.5 text-right tabular-nums text-txt-sub">
              {formatMoney(row.costPaise)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
