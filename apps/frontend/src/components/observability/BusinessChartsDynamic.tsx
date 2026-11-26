"use client";

// #737: the Business lens page's CHART components only. Split out to enable
// dynamic import and keep the recharts runtime out of the initial page bundle.
// This module is dynamically imported by the business page via next/dynamic.

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
  BUSINESS_PERIOD_LABEL_KEY,
  STRINGS,
  type OperatorBusinessStrings,
} from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import {
  DASH,
  formatCount,
  formatRupees,
  rupeesFromPaise,
} from "@/lib/operator/observability-format";
import type {
  BusinessPeriod,
  BusinessRead,
  ModelSpend,
  ProviderSpend,
} from "@/lib/operator/observability";

const rupeesTick = (value: number) => formatRupees(value);
const countTick = (value: number) => formatCount(value);

interface BudgetBar {
  label: string;
  consumed: number;
  cap: number;
  projected: number | null;
  overCap: boolean;
}

function budgetBars(read: BusinessRead, consumedLabel: string): BudgetBar[] {
  return [
    {
      label: consumedLabel,
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

function budgetDescription(
  rows: BudgetBar[],
  t: OperatorBusinessStrings,
): string {
  return rows
    .map((row) => {
      const projected =
        row.projected === null
          ? t.spend.chart.noProjection
          : row.overCap
            ? t.spend.chart.projectedAtOverCap(formatRupees(row.projected))
            : t.spend.chart.projectedAt(formatRupees(row.projected));
      return t.spend.chart.description(
        formatRupees(row.consumed),
        formatRupees(row.cap),
        projected,
      );
    })
    .join("; ");
}

export function SpendAgainstCapChart({
  read,
  testId,
}: {
  read: BusinessRead;
  testId: string;
}) {
  const { lang } = useLang();
  const t = STRINGS[lang].operatorBusiness;
  const rows = budgetBars(read, t.spend.chart.consumed);
  const config = {
    consumed: { label: t.spend.chart.consumed, color: "var(--accent)" },
    cap: { label: t.spend.chart.monthlyCap, color: "var(--txt-muted)" },
    projected: {
      label: t.spend.chart.projectedMonthEnd,
      color: "var(--txt-sub)",
    },
    overspent: {
      label: t.spend.chart.projectedOverCap,
      color: "var(--danger)",
    },
  };

  return (
    <ChartFigure
      config={config}
      testId={testId}
      ariaLabel={t.spend.chart.ariaLabel}
      description={budgetDescription(rows, t)}
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

interface TaskTypeBar {
  task: string;
  rupees: number;
}

export function SpendByTaskTypeChart({
  rows,
  testId,
}: {
  rows: BusinessRead["by_task_type"];
  testId: string;
}) {
  const { lang } = useLang();
  const t = STRINGS[lang].operatorBusiness;
  const bars: TaskTypeBar[] = rows.map((row) => ({
    task: row.task_type,
    rupees: rupeesFromPaise(row.spend_paise),
  }));
  const config = {
    spend: { label: t.breakdown.chart.series, color: "var(--accent)" },
  };

  return (
    <ChartFigure
      config={config}
      testId={testId}
      ariaLabel={t.breakdown.chart.ariaLabel}
      description={
        bars.length === 0
          ? t.breakdown.chart.emptyDescription
          : t.breakdown.chart.description(
              bars
                .map((row) => `${row.task} ${formatRupees(row.rupees)}`)
                .join("; "),
            )
      }
    >
      <BarChart data={bars} margin={{ left: 8, right: 8, top: 8 }}>
        <CartesianGrid vertical={false} />
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

export function TokenVolumeChart({
  rows,
  testId,
}: {
  rows: ProviderSpend[];
  testId: string;
}) {
  const { lang } = useLang();
  const t = STRINGS[lang].operatorBusiness;
  const bars = rows.map((row) => ({
    provider: row.provider,
    input: row.input_tokens,
    output: row.output_tokens,
  }));
  const config = {
    input: { label: t.tokens.chart.input, color: "var(--accent)" },
    output: { label: t.tokens.chart.output, color: "var(--txt-muted)" },
  };

  return (
    <ChartFigure
      config={config}
      testId={testId}
      ariaLabel={t.tokens.chart.ariaLabel}
      description={
        bars.length === 0
          ? t.tokens.chart.ariaLabel
          : t.tokens.chart.description(
              bars
                .map(
                  (bar) =>
                    `${bar.provider} ${formatCount(bar.input)} / ${formatCount(
                      bar.output,
                    )}`,
                )
                .join("; "),
            )
      }
    >
      <BarChart data={bars} margin={{ left: 8, right: 8, top: 8 }}>
        <CartesianGrid vertical={false} />
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
          width={64}
          tickFormatter={countTick}
        />
        <ChartTooltip
          cursor={{ fill: "var(--hairline-soft)" }}
          content={
            <ChartTooltipContent
              formatter={(value) => formatCount(Number(value))}
            />
          }
        />
        <Bar
          dataKey="input"
          fill="var(--color-input)"
          radius={[4, 4, 0, 0]}
          isAnimationActive={false}
        />
        <Bar
          dataKey="output"
          fill="var(--color-output)"
          radius={[4, 4, 0, 0]}
          isAnimationActive={false}
        />
      </BarChart>
    </ChartFigure>
  );
}
