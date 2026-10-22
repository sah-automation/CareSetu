"use client";

// #709 C2b: the operator Cost panel page (plan-phase14-observability §9.2).
// Two panels, two reads, two independent failures:
//   * "Spend against budget"  <- GET /v1/operator/observability/cost
//   * "Daily spend trend"     <- GET /v1/operator/observability/cost/trend
//
// They are separate panels rather than one page read because they answer
// different questions and can fail separately: a trend read that times out says
// nothing about the bill, and a page-level error over both would blank a
// budget figure that is right there and correct. Every state - loading, empty,
// failure with retry - belongs to the panel that owns the read (blueprint §9.1).

import {
  CostBudgetChart,
  DailyCostTrendChart,
} from "@/components/observability/CostCharts";
import {
  ObservabilityPanelPage,
  ReadPanel,
} from "@/components/observability/ObservabilityPanelPage";
import { fetchCost, fetchCostTrend } from "@/lib/operator/observability";
import { formatMoney, formatPct } from "@/lib/operator/observability-format";
import { usePanelRead } from "@/lib/operator/usePanelRead";

/** Nothing is budgeted for this deployment - a fact about config, not usage. */
const NO_BUDGET_BODY =
  "No provider/model budget is configured, so there is no cap to plot spend against.";

/** The rollup has recorded no billable AI day yet. */
const NO_TREND_BODY =
  "The nightly rollup has not recorded a billable AI day for this window.";

export default function ObservabilityCostPage() {
  const cost = usePanelRead(() => fetchCost());
  const trend = usePanelRead(() => fetchCostTrend());

  return (
    <ObservabilityPanelPage
      title="AI cost"
      description="Spend against the monthly cap, and how the bill has moved."
    >
      <div className="flex flex-col gap-4">
        <ReadPanel
          testId="cost-budget"
          title="Spend against budget"
          read={cost}
          isEmpty={(summary) => summary.budgets.length === 0}
          emptyTitle="No AI budget configured"
          emptyBody={NO_BUDGET_BODY}
          errorMessage="Could not load the AI budget."
          takeaway={
            cost.data
              ? `${formatMoney(cost.data.total_spend_paise)} of ${formatMoney(
                  cost.data.total_limit_paise,
                )} · ${formatPct(cost.data.utilization_pct)} used${
                  cost.data.exhausted
                    ? " · budget exhausted"
                    : ` · ${formatMoney(cost.data.remaining_paise)} remaining`
                }`
              : undefined
          }
        >
          {(summary) => (
            <CostBudgetChart
              budgets={summary.budgets}
              testId="cost-budget-chart"
            />
          )}
        </ReadPanel>

        <ReadPanel
          testId="cost-trend"
          title="Daily spend trend"
          read={trend}
          isEmpty={(series) => series.points.length === 0}
          emptyTitle="No spend recorded yet"
          emptyBody={NO_TREND_BODY}
          errorMessage="Could not load the daily AI spend trend."
          takeaway={
            trend.data
              ? `${trend.data.points.length} billable days over the last ${trend.data.days} days.`
              : undefined
          }
        >
          {(series) => (
            <DailyCostTrendChart
              points={series.points}
              testId="cost-trend-chart"
            />
          )}
        </ReadPanel>
      </div>
    </ObservabilityPanelPage>
  );
}
