"use client";

// #709 C2b: the operator Health panel page (plan-phase14-observability §9.2).
// Two C1 reads, two panels:
//   * "Latency percentiles"    <- GET /v1/operator/observability/latency
//   * "System health"          <- GET /v1/operator/observability/health
//
// The second panel is the one place the console reports reachability rather
// than rates, and its three sections answer the three questions an on-call
// operator asks in order: is each dependency reachable, are the outbox queues
// draining, and has any circuit tripped. It is a list, not a chart, on purpose
// - these are states to read, not magnitudes to compare, and a bar chart of
// "one dependency is down" would put a severity ordering on facts that do not
// have one.
//
// The latency chart lives here rather than on its own page because latency IS
// the health signal: plan §9.2 names four panel routes (cost, usage, quality,
// health) and the ticket's latency-percentiles chart is the health route's
// headline.

import { LatencyPercentileChart } from "@/components/observability/HealthCharts";
import {
  ObservabilityPanelPage,
  ReadPanel,
} from "@/components/observability/ObservabilityPanelPage";
import { fetchHealth, fetchLatency } from "@/lib/operator/observability";
import { formatDuration } from "@/lib/operator/observability-format";
import { usePanelRead } from "@/lib/operator/usePanelRead";

/** No latency sample has been rolled yet. */
const NO_LATENCY_BODY =
  "The nightly rollup has not recorded a latency sample yet.";

/** The health read came back with nothing in it at all. */
const NO_HEALTH_BODY =
  "The health read reported no dependencies, queues or breakers.";

/**
 * State pills, in the operator console's own idiom (lib/operator/badges.ts):
 * a token-coloured span rather than a component, because the console already
 * has that vocabulary and a second one is how two queues end up disagreeing
 * about what "rejected" looks like.
 */
const STATE_TONES: Record<string, string> = {
  up: "bg-success-soft text-success-text",
  closed: "bg-success-soft text-success-text",
  disabled: "bg-hairline-soft text-txt-muted",
};

/** Anything not named above is a state the read could not reach. */
const UNREACHABLE_TONE = "bg-danger-soft text-danger";

function stateTone(state: string): string {
  return STATE_TONES[state] ?? UNREACHABLE_TONE;
}

function StatePill({ state }: { state: string }) {
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-xs font-medium ${stateTone(
        state,
      )}`}
      data-testid={`health-state-${state}`}
    >
      {state}
    </span>
  );
}

export default function ObservabilityHealthPage() {
  const latency = usePanelRead(() => fetchLatency());
  const health = usePanelRead(() => fetchHealth());

  return (
    <ObservabilityPanelPage
      title="System health"
      description="How slow the AI is, and whether the dependencies behind it are up."
    >
      <div className="flex flex-col gap-4">
        <ReadPanel
          testId="health-latency"
          title="Latency percentiles by provider"
          read={latency}
          isEmpty={(report) => report.providers.length === 0}
          emptyTitle="No latency samples yet"
          emptyBody={NO_LATENCY_BODY}
          errorMessage="Could not load the AI latency percentiles."
          takeaway={
            latency.data
              ? latency.data.last_rolled_date
                ? `Percentiles are a snapshot as of ${latency.data.last_rolled_date}, not a live measurement.`
                : "The rollup has not run yet, so these percentiles are not from a completed window."
              : undefined
          }
        >
          {(report) => (
            <LatencyPercentileChart
              rows={report.providers}
              testId="health-latency-chart"
            />
          )}
        </ReadPanel>

        <ReadPanel
          testId="health-system"
          title="Dependencies, queues and circuit breakers"
          read={health}
          isEmpty={(report) =>
            report.dependencies.length === 0 &&
            report.outbox.length === 0 &&
            report.breakers.length === 0
          }
          emptyTitle="Nothing to report"
          emptyBody={NO_HEALTH_BODY}
          errorMessage="Could not load the system health read."
        >
          {(report) => (
            <div className="flex flex-col gap-6">
              <section data-testid="health-dependencies">
                <h3 className="mb-2 text-xs font-medium text-txt-sub">
                  Dependencies
                </h3>
                {report.dependencies.length === 0 ? (
                  <p className="text-sm text-txt-muted">
                    No dependency reported.
                  </p>
                ) : (
                  <ul className="flex flex-col gap-1.5">
                    {report.dependencies.map((dependency) => (
                      <li
                        key={dependency.name}
                        className="flex flex-wrap items-center gap-2 text-sm"
                        data-testid={`health-dependency-${dependency.name}`}
                      >
                        <span className="w-40 shrink-0 font-medium text-txt">
                          {dependency.name}
                        </span>
                        <StatePill state={dependency.status} />
                        <span className="tabular-nums text-txt-muted">
                          {formatDuration(dependency.latency_ms)}
                        </span>
                        {dependency.detail && (
                          <span className="text-txt-sub">
                            {dependency.detail}
                          </span>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              <section data-testid="health-outbox">
                <h3 className="mb-2 text-xs font-medium text-txt-sub">
                  Outbox queues
                </h3>
                {report.outbox.length === 0 ? (
                  <p className="text-sm text-txt-muted">
                    No outbox queue reported.
                  </p>
                ) : (
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-hairline text-left text-xs text-txt-muted">
                        <th scope="col" className="py-1.5 pr-3 font-medium">
                          Queue
                        </th>
                        <th
                          scope="col"
                          className="py-1.5 pr-3 text-right font-medium"
                        >
                          Pending
                        </th>
                        <th
                          scope="col"
                          className="py-1.5 pr-3 text-right font-medium"
                        >
                          In flight
                        </th>
                        <th
                          scope="col"
                          className="py-1.5 pr-3 text-right font-medium"
                        >
                          Dead letter
                        </th>
                        <th
                          scope="col"
                          className="py-1.5 text-right font-medium"
                        >
                          Backlog
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {report.outbox.map((queue) => (
                        <tr
                          key={`${queue.table_schema}.${queue.table}`}
                          className="border-b border-hairline-soft"
                          data-testid={`health-outbox-${queue.table}`}
                        >
                          <th
                            scope="row"
                            className="py-1.5 pr-3 text-left font-normal text-txt"
                          >
                            {queue.table_schema}.{queue.table}
                          </th>
                          <td className="py-1.5 pr-3 text-right tabular-nums text-txt-sub">
                            {queue.pending.toLocaleString("en-IN")}
                          </td>
                          <td className="py-1.5 pr-3 text-right tabular-nums text-txt-sub">
                            {queue.inflight.toLocaleString("en-IN")}
                          </td>
                          <td className="py-1.5 pr-3 text-right tabular-nums text-txt-sub">
                            {queue.dead_letter.toLocaleString("en-IN")}
                          </td>
                          <td className="py-1.5 text-right tabular-nums text-txt-sub">
                            {queue.backlog.toLocaleString("en-IN")}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </section>

              <section data-testid="health-breakers">
                <h3 className="mb-2 text-xs font-medium text-txt-sub">
                  Circuit breakers
                </h3>
                {report.breakers.length === 0 ? (
                  <p className="text-sm text-txt-muted">
                    No circuit breaker is registered.
                  </p>
                ) : (
                  <ul className="flex flex-wrap gap-2">
                    {report.breakers.map((breaker) => (
                      <li
                        key={breaker.provider}
                        className="flex items-center gap-2 text-sm"
                        data-testid={`health-breaker-${breaker.provider}`}
                      >
                        <span className="font-medium text-txt">
                          {breaker.provider}
                        </span>
                        <StatePill state={breaker.breaker_state} />
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            </div>
          )}
        </ReadPanel>
      </div>
    </ObservabilityPanelPage>
  );
}
