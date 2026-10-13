"use client";

// #709 C2b: the operator Quality panel page (plan-phase14-observability §9.2),
// over GET /v1/operator/observability/quality.
//
// One read, one panel: the window's two headline rates, then the per-provider
// success rate, then the outcome mix. All three views come from the same
// response, so they are one panel with one state rather than three panels an
// operator waits on separately.
//
// The two rates the ticket names - low-confidence and success - are stated as
// figures before the charts, because both are nullable and a rate with no
// denominator is the one number on this page that must not be guessed at. They
// read as an em dash with the count beside them ("0 flagged", "0 of 0 calls"),
// so an operator can tell "nothing was flagged" from "nothing has run".

import {
  ObservabilityPanelPage,
  ReadPanel,
} from "@/components/observability/ObservabilityPanelPage";
import {
  OutcomeMixChart,
  ProviderSuccessRateChart,
} from "@/components/observability/QualityCharts";
import { fetchQuality } from "@/lib/operator/observability";
import { formatPct } from "@/lib/operator/observability-format";
import { usePanelRead } from "@/lib/operator/usePanelRead";

/** No AI output to score in this window. */
const NO_QUALITY_BODY =
  "No AI completions were recorded for this window, so there is nothing to score.";

export default function ObservabilityQualityPage() {
  const quality = usePanelRead(() => fetchQuality());

  return (
    <ObservabilityPanelPage
      current="quality"
      title="AI quality"
      description="Whether the AI is completing work, and how often its output needs a second look."
    >
      <ReadPanel
        testId="quality-report"
        title="Success and low-confidence rates"
        read={quality}
        isEmpty={(report) =>
          report.total_calls === 0 && report.providers.length === 0
        }
        emptyTitle="No AI completions yet"
        emptyBody={NO_QUALITY_BODY}
        errorMessage="Could not load the AI quality report."
      >
        {(report) => (
          <div className="flex flex-col gap-6">
            <dl
              className="grid grid-cols-2 gap-3 sm:grid-cols-3"
              data-testid="quality-rates"
            >
              <div className="rounded-lg border border-hairline p-3">
                <dt className="text-xs text-txt-muted">Success rate</dt>
                <dd
                  className="text-xl font-semibold text-txt"
                  data-testid="quality-success-rate"
                >
                  {formatPct(report.success_rate)}
                </dd>
                <p className="text-xs text-txt-sub">
                  {report.success_count.toLocaleString("en-IN")} of{" "}
                  {report.total_calls.toLocaleString("en-IN")} calls
                </p>
              </div>
              <div className="rounded-lg border border-hairline p-3">
                <dt className="text-xs text-txt-muted">Low-confidence rate</dt>
                <dd
                  className="text-xl font-semibold text-txt"
                  data-testid="quality-low-confidence-rate"
                >
                  {formatPct(report.low_confidence_rate)}
                </dd>
                <p className="text-xs text-txt-sub">
                  {report.low_confidence_count.toLocaleString("en-IN")}{" "}
                  completions flagged for review
                </p>
              </div>
              <div className="rounded-lg border border-hairline p-3">
                <dt className="text-xs text-txt-muted">Window</dt>
                <dd className="text-xl font-semibold text-txt">
                  {report.days} days
                </dd>
                <p className="text-xs text-txt-sub">
                  {report.from_date} to {report.to_date}
                </p>
              </div>
            </dl>

            <div>
              <h3 className="mb-1 text-xs font-medium text-txt-sub">
                Success rate by provider
              </h3>
              {report.providers.length === 0 ? (
                <p
                  className="rounded-md border border-hairline bg-hairline-soft px-3 py-2 text-sm text-txt-muted"
                  data-testid="quality-no-providers"
                >
                  No provider has been sampled in this window, so there is no
                  per-provider rate to plot.
                </p>
              ) : (
                <ProviderSuccessRateChart
                  rows={report.providers}
                  testId="quality-success-rate-chart"
                />
              )}
            </div>

            <div>
              <h3 className="mb-1 text-xs font-medium text-txt-sub">
                Call outcomes
              </h3>
              {report.total_calls === 0 ? (
                <p
                  className="rounded-md border border-hairline bg-hairline-soft px-3 py-2 text-sm text-txt-muted"
                  data-testid="quality-no-outcomes"
                >
                  No AI call has been made in this window, so there are no
                  outcomes to split.
                </p>
              ) : (
                <OutcomeMixChart
                  successCount={report.success_count}
                  failureCount={report.failure_count}
                  timeoutCount={report.timeout_count}
                  testId="quality-outcome-chart"
                />
              )}
            </div>
          </div>
        )}
      </ReadPanel>
    </ObservabilityPanelPage>
  );
}
