"use client";

// #709 C2b: the operator Usage panel page (plan-phase14-observability §9.2),
// over GET /v1/operator/observability/usage.
//
// One read, one panel, three views of it - calls, tokens, and the per-scope
// money line. They are one panel rather than three because they are one read:
// there is no state in which the call chart is stale and the token chart is
// fresh, and splitting them would give the operator three panels to wait for
// one answer. Loading, empty and failure all belong to the read that produces
// them (blueprint §9.1).

import {
  ObservabilityPanelPage,
  ReadPanel,
} from "@/components/observability/ObservabilityPanelPage";
import {
  CallsByScopeChart,
  ScopeCostTable,
  TokensByScopeChart,
} from "@/components/observability/UsageCharts";
import { fetchUsage } from "@/lib/operator/observability";
import { formatMoney } from "@/lib/operator/observability-format";
import { usePanelRead } from "@/lib/operator/usePanelRead";

/** The rollup has no AI activity for this window. */
const NO_USAGE_BODY =
  "No AI calls were recorded for this window, so there is nothing to break down.";

export default function ObservabilityUsagePage() {
  const usage = usePanelRead(() => fetchUsage());

  return (
    <ObservabilityPanelPage
      title="AI usage"
      description="Where the AI calls, tokens and rupees are going."
    >
      <ReadPanel
        testId="usage-breakdown"
        title="Calls and tokens by provider and task"
        read={usage}
        isEmpty={(report) => report.rows.length === 0}
        emptyTitle="No AI calls yet"
        emptyBody={NO_USAGE_BODY}
        errorMessage="Could not load the AI usage breakdown."
        takeaway={
          usage.data
            ? `${usage.data.total_calls.toLocaleString("en-IN")} calls · ${(
                usage.data.total_input_tokens + usage.data.total_output_tokens
              ).toLocaleString("en-IN")} tokens · ${formatMoney(
                usage.data.total_cost_paise,
              )} · last ${usage.data.days} days`
            : undefined
        }
      >
        {(report) => (
          <div className="flex flex-col gap-6">
            <div>
              <h3 className="mb-1 text-xs font-medium text-txt-sub">
                AI calls by scope
              </h3>
              <CallsByScopeChart
                rows={report.rows}
                testId="usage-calls-chart"
              />
            </div>
            <div>
              <h3 className="mb-1 text-xs font-medium text-txt-sub">
                Tokens by scope
              </h3>
              <TokensByScopeChart
                rows={report.rows}
                testId="usage-tokens-chart"
              />
            </div>
            <div>
              <h3 className="mb-1 text-xs font-medium text-txt-sub">
                Spend by scope
              </h3>
              <ScopeCostTable rows={report.rows} />
            </div>
          </div>
        )}
      </ReadPanel>
    </ObservabilityPanelPage>
  );
}
