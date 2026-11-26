"use client";

// #738: the Reliability lens page's one chart. It plots the `/throughput` read
// (#727) - requests and errors per minute over the capture window.
//
// Three deliberate choices, all about not inventing a shape:
//
//   * Requests and errors are GROUPED bars on ONE count axis, never a stacked
//     bar. A stacked bar's height would be the request total with the errors
//     sitting inside it, which reads as "these errors are extra requests"; and
//     an error-rate line on a second axis would need two scales against each
//     other, the one chart shape that can make a 0.4% blip look like an
//     outage. The rate lives in the panel's takeaway and in the chart's text
//     alternative instead, where it cannot be mis-scaled.
//   * A minute with no traffic carries NO point at all (facade.ThroughputPoint),
//     so the series has real gaps. A zero-filled minute would draw a dip to the
//     floor for a window in which nothing happened.
//   * The x-axis is thinned with `preserveStartEnd` rather than dropped: with a
//     60-point series recharts' default drops most of the labels, and an
//     unattributable bar is not a chart an operator can read an incident off.
//
// Every import here is a named re-export from components/ui/chart.tsx, never
// `recharts` directly: the boundary is what stops two panels growing two
// palettes, and it is what keeps the page inside the NFR-003 page budget.

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
import type { ThroughputPoint } from "@/lib/operator/observability";

/**
 * The minute label on the x-axis: the clock, without the date or the zone.
 *
 * Formatted through `Intl` at UTC rather than by slicing the ISO string, and
 * pinned to UTC deliberately. The capture stamps come from the API in UTC, and a
 * server-local reading would shift every bar against the deployment's own logs -
 * and would shift them again on a deployment in another zone. The axis says the
 * zone it is in by being fixed to it; `timeZoneName` is left off because an
 * hour is wide enough on a 60-tick axis already.
 */
const MINUTE_FORMAT = new Intl.DateTimeFormat("en-GB", {
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
  timeZone: "UTC",
});

function minuteLabel(minuteTs: string): string {
  return MINUTE_FORMAT.format(new Date(minuteTs));
}

interface MinutePoint {
  label: string;
  requests: number;
  errors: number;
}

function minutePoints(points: ThroughputPoint[]): MinutePoint[] {
  return points.map((point) => ({
    label: minuteLabel(point.minute_ts),
    requests: point.requests,
    errors: point.errors,
  }));
}

/**
 * The chart's text alternative. It carries the rate and the occurrence counts,
 * because a bar's geometry cannot say how many minutes were quiet - and a
 * series with gaps reads to a screen reader as a series that is short.
 */
function throughputDescription(points: ThroughputPoint[]): string {
  if (points.length === 0) return "No minutes with traffic to plot.";
  const errors = points.reduce((total, point) => total + point.errors, 0);
  const requests = points.reduce((total, point) => total + point.requests, 0);
  return (
    `Requests and errors per minute over ${points.length} minute(s) with ` +
    `traffic: ${requests} requests, ${errors} errors. Minutes with no traffic ` +
    "are absent from the series rather than plotted as zero."
  );
}

/** Requests and errors per minute, grouped on one count axis. */
export function ThroughputPerMinuteChart({
  points,
  testId,
}: {
  points: ThroughputPoint[];
  testId: string;
}) {
  const data = minutePoints(points);
  const config = {
    requests: { label: "Requests", color: "var(--accent)" },
    errors: { label: "Errors", color: "var(--danger)" },
  };

  return (
    <ChartFigure
      config={config}
      testId={testId}
      ariaLabel="Requests and errors per minute"
      description={throughputDescription(points)}
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
        <ChartLegend content={<ChartLegendContent />} />
        <Bar
          dataKey="requests"
          fill="var(--color-requests)"
          radius={[4, 4, 0, 0]}
          isAnimationActive={false}
        />
        <Bar
          dataKey="errors"
          fill="var(--color-errors)"
          radius={[4, 4, 0, 0]}
          isAnimationActive={false}
        />
      </BarChart>
    </ChartFigure>
  );
}
