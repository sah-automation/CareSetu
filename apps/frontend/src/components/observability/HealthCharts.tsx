"use client";

// #709 C2b: the operator Health panel's latency chart (plan-phase14-observability
// §9.2), over GET /v1/operator/observability/latency.
//
// Three bounded series - p50, p95, p99 - so a grouped bar is honest here and
// the percentile ordering reads left to right. Two rules the chart keeps:
//
//   * A provider the rollup has no sample for reports null percentiles
//     (facade.LatencyRow). The null reaches recharts untouched, which draws no
//     bar. Coercing it to zero would render a provider as "instantly fast",
//     the one reading that would make an outage look healthy.
//   * The window is stated in the chart's own caption rather than inferred from
//     the axis. These are snapshots "as of the last roll" - the route takes no
//     window because it re-derives no aggregate - so a latency chart with no
//     stated window is a number nobody can act on.
//
// Latency is in whole milliseconds on the wire and rendered in milliseconds
// here; seconds only appear in the prose rates, where a human reads them.

import {
  Bar,
  BarChart,
  CartesianGrid,
  ChartFigure,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
  XAxis,
  YAxis,
} from "@/components/ui/chart";
import { formatDuration } from "@/lib/operator/observability-format";
import type { LatencyRow } from "@/lib/operator/observability";

/** One provider's three percentiles. `null` stays `null`. */
interface ProviderPercentiles {
  provider: string;
  p50: number | null;
  p95: number | null;
  p99: number | null;
}

function percentiles(rows: LatencyRow[]): ProviderPercentiles[] {
  return rows.map((row) => ({
    provider: row.provider,
    p50: row.p50_duration_ms,
    p95: row.p95_duration_ms,
    p99: row.p99_duration_ms,
  }));
}

/**
 * The latency chart's text alternative. An unsampled provider is named as
 * unmeasured rather than omitted, so the sentence does not imply a zero
 * millisecond response that was never recorded.
 */
function latencyDescription(data: ProviderPercentiles[]): string {
  if (data.length === 0) return "No providers recorded.";
  return (
    "AI latency by provider: " +
    data
      .map(
        (row) =>
          `${row.provider} p50 ${formatDuration(row.p50)}, p95 ${formatDuration(
            row.p95,
          )}, p99 ${formatDuration(row.p99)}`,
      )
      .join("; ")
  );
}

/** Latency percentiles by provider, in milliseconds, grouped p50/p95/p99. */
export function LatencyPercentileChart({
  rows,
  testId,
}: {
  rows: LatencyRow[];
  testId: string;
}) {
  const data = percentiles(rows);
  const config = {
    p50: { label: "p50 (typical)", color: "var(--accent)" },
    p95: { label: "p95", color: "var(--warm)" },
    p99: { label: "p99 (worst)", color: "var(--danger)" },
  };

  return (
    <ChartFigure
      config={config}
      testId={testId}
      ariaLabel="AI latency percentiles by provider"
      description={latencyDescription(data)}
    >
      <BarChart data={data} margin={{ left: 8, right: 8, top: 8 }}>
        <CartesianGrid vertical={false} />
        {/* interval={0}: recharts drops a provider label that will not fit,
            which would leave three unattributable bars. */}
        <XAxis
          dataKey="provider"
          interval={0}
          tickLine={false}
          axisLine={false}
          fontSize={12}
        />
        <YAxis
          tickLine={false}
          axisLine={false}
          fontSize={12}
          width={56}
          tickFormatter={(value: number) => formatDuration(value)}
        />
        <ChartTooltip
          cursor={{ fill: "var(--hairline-soft)" }}
          content={
            <ChartTooltipContent
              formatter={(value) => formatDuration(Number(value))}
            />
          }
        />
        <ChartLegend content={<ChartLegendContent />} />
        <Bar
          dataKey="p50"
          fill="var(--color-p50)"
          radius={[4, 4, 0, 0]}
          isAnimationActive={false}
        />
        <Bar
          dataKey="p95"
          fill="var(--color-p95)"
          radius={[4, 4, 0, 0]}
          isAnimationActive={false}
        />
        <Bar
          dataKey="p99"
          fill="var(--color-p99)"
          radius={[4, 4, 0, 0]}
          isAnimationActive={false}
        />
      </BarChart>
    </ChartFigure>
  );
}
