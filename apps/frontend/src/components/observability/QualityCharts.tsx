"use client";

// #709 C2b: the operator Quality panel's charts (plan-phase14-observability
// §9.2), both over GET /v1/operator/observability/quality.
//
// The load-bearing rule in this file: a provider the rollup has no traffic
// sample for reports `success_rate: null` (facade.ProviderQualityRow), and
// that null is left null all the way into the chart. recharts draws no bar for
// a null, which is the honest shape - a bar of zero would say "this provider
// failed every call" about a provider that has not been called at all. The
// missing bar is explained in the panel's own words rather than left as a gap
// the reader has to interpret.

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ChartFigure,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
  LabelList,
  XAxis,
  YAxis,
} from "@/components/ui/chart";
import { DASH, formatPct } from "@/lib/operator/observability-format";
import type { ProviderQualityRow } from "@/lib/operator/observability";

/**
 * A whole-number call count, grouped for the axis and tooltip. recharts
 * positions a tick by its value, so grouping belongs in the formatter rather
 * than in the plotted number.
 */
const count = (value: number): string => value.toLocaleString("en-IN");

/**
 * The success-rate chart's text alternative. An unsampled provider is spelled
 * out as unmeasured rather than left to an absent bar, so the sentence does not
 * imply a 0% that was never measured.
 */
function rateDescription(data: ProviderRate[]): string {
  if (data.length === 0) return "No providers recorded.";
  return (
    "AI success rate by provider: " +
    data.map((row) => `${row.provider} ${formatPct(row.rate)}`).join("; ")
  );
}

/** The outcome chart's text alternative - the split of every call made. */
function outcomeDescription(
  success: number,
  failure: number,
  timeout: number,
): string {
  const total = success + failure + timeout;
  if (total === 0) return "No calls made in this window.";
  return `${count(total)} calls: ${count(success)} succeeded, ${count(
    failure,
  )} failed, ${count(timeout)} timed out.`;
}

/** One provider's success rate. `rate` stays `null` when unmeasured. */
interface ProviderRate {
  provider: string;
  rate: number | null;
}

/**
 * Success rate per provider, as a percentage. The null is preserved rather than
 * defaulted: `?? 0` here would turn "nobody has called this provider" into
 * "this provider fails 100% of calls" on the operator's screen.
 */
function providerRates(rows: ProviderQualityRow[]): ProviderRate[] {
  return rows.map((row) => ({
    provider: row.provider,
    rate: row.success_rate,
  }));
}

/**
 * Success rate by provider, in percent, on a 0-100 axis.
 *
 * The axis is pinned to 0-100 rather than scaled to the data. A success rate
 * lives in a fixed range, so an auto-scaled axis would magnify a 99.8-vs-99.6
 * spread into full-height bars that look like a collapse, and a rate well below
 * 100 is the normal state of any real AI system, not an alarm.
 */
export function ProviderSuccessRateChart({
  rows,
  testId,
}: {
  rows: ProviderQualityRow[];
  testId: string;
}) {
  const data = providerRates(rows);
  const config = {
    rate: { label: "Success rate", color: "var(--accent)" },
  };

  return (
    <ChartFigure
      config={config}
      testId={testId}
      ariaLabel="AI success rate by provider"
      description={rateDescription(data)}
    >
      <BarChart data={data} margin={{ left: 8, right: 8, top: 20 }}>
        <CartesianGrid vertical={false} />
        {/* interval={0}: recharts drops a provider label that will not fit,
            which would leave a bar the operator cannot attribute. */}
        <XAxis
          dataKey="provider"
          interval={0}
          tickLine={false}
          axisLine={false}
          fontSize={12}
        />
        <YAxis
          domain={[0, 100]}
          tickLine={false}
          axisLine={false}
          fontSize={12}
          width={44}
          tickFormatter={(value: number) => `${value}%`}
        />
        <ChartTooltip
          cursor={{ fill: "var(--hairline-soft)" }}
          content={
            <ChartTooltipContent
              formatter={(value) => formatPct(Number(value))}
            />
          }
        />
        <Bar dataKey="rate" radius={[4, 4, 0, 0]} isAnimationActive={false}>
          {data.map((row) => (
            <Cell key={row.provider} fill="var(--color-rate)" />
          ))}
          <LabelList
            dataKey="rate"
            position="top"
            // A provider with no samples has no label to draw, so the value
            // falls back to the em dash rather than a blank gap in the row.
            formatter={(label) =>
              typeof label === "number" ? formatPct(label) : DASH
            }
          />
        </Bar>
      </BarChart>
    </ChartFigure>
  );
}

/**
 * Outcome mix as a single stacked bar. Success, failure and timeout are three
 * disjoint outcomes the rollup counts separately, so stacking them is a
 * partition of the total and the bar's full width is every call made.
 *
 * The three outcomes are plotted as three SERIES on one category, not three
 * categories with one series: the partition is the whole claim, and a per-
 * category bar chart draws three independent bars whose lengths are only
 * comparable because the axis happens to be shared. A reader should see the
 * split of 100% of calls, so the bar runs to the window's total and each
 * segment's width is its share.
 *
 * `low_confidence_count` is deliberately NOT a fourth segment: the overview
 * divides it by total_calls, which is what a rate over all calls means, and
 * treating it as a peer slice would assert a subset relationship this chart has
 * not verified. It is shown as the panel's rate figure instead.
 */
export function OutcomeMixChart({
  successCount,
  failureCount,
  timeoutCount,
  testId,
}: {
  successCount: number;
  failureCount: number;
  timeoutCount: number;
  testId: string;
}) {
  const total = successCount + failureCount + timeoutCount;
  // One category: "every call made in the window". The segment labels live in
  // the legend rather than on a category axis, because with a single category
  // the axis has nothing to name.
  const data = [
    {
      scope: "All calls",
      success: successCount,
      failure: failureCount,
      timeout: timeoutCount,
    },
  ];
  const config = {
    success: { label: "Succeeded", color: "var(--accent)" },
    failure: { label: "Failed", color: "var(--danger)" },
    timeout: { label: "Timed out", color: "var(--warm)" },
  };

  return (
    <ChartFigure
      config={config}
      testId={testId}
      ariaLabel="AI call outcomes for the window"
      description={outcomeDescription(successCount, failureCount, timeoutCount)}
    >
      <BarChart
        data={data}
        layout="vertical"
        margin={{ left: 8, right: 8, top: 8 }}
      >
        <CartesianGrid horizontal={false} />
        {/* Domain pinned to the window's total so the stacked bar always fills
            the plot: a stacked bar's width IS the total, and an auto-scaled axis
            would round the last segment up and misstate the partition. */}
        <XAxis
          type="number"
          domain={[0, total]}
          tickFormatter={count}
          tickLine={false}
          axisLine={false}
          fontSize={12}
        />
        <YAxis
          type="category"
          dataKey="scope"
          interval={0}
          tickLine={false}
          axisLine={false}
          fontSize={12}
          width={88}
        />
        <ChartTooltip
          cursor={{ fill: "var(--hairline-soft)" }}
          content={
            <ChartTooltipContent formatter={(value) => count(Number(value))} />
          }
        />
        {/* The legend reads the payload through ChartLegendContent so the segments are
            named from the config ("Succeeded", "Failed", "Timed out") rather
            than by recharts' raw lowercase data keys - the key is the wire's
            field name, not something to show an operator. */}
        <ChartLegend align="left" content={<ChartLegendContent />} />
        {/* Same stackId on all three is what makes them one bar rather than
            three: recharts stacks the series that share an id within a
            category, so without it these would sit side by side and the
            "full width is every call" claim would be false. */}
        <Bar
          dataKey="success"
          stackId="outcome"
          fill="var(--color-success)"
          isAnimationActive={false}
        />
        <Bar
          dataKey="failure"
          stackId="outcome"
          fill="var(--color-failure)"
          isAnimationActive={false}
        />
        <Bar
          dataKey="timeout"
          stackId="outcome"
          fill="var(--color-timeout)"
          isAnimationActive={false}
        />
      </BarChart>
    </ChartFigure>
  );
}
