"use client";

// #743: the Product lens page's CHART components only. Split out to enable
// dynamic import and keep the recharts runtime out of the initial page bundle.
// This module is dynamically imported by the product page via next/dynamic.

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
import type { ActiveUsersDayPoint } from "@/lib/operator/observability";

const DAY_FORMAT = new Intl.DateTimeFormat("en-GB", {
  day: "2-digit",
  month: "short",
  timeZone: "UTC",
});

function dayLabel(day: string): string {
  return DAY_FORMAT.format(new Date(`${day}T00:00:00Z`));
}

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
