"use client";

// #738: the Reliability lens page's presentational parts.
//
// Split out of the page beside `BusinessCharts.tsx` for the reason that module
// exists: a page that owns seven panels ends up owning the markup of all seven,
// and the page's own job - which read feeds which panel, and what one write does
// to the list - gets buried under table headers. Everything here is a pure
// function of one already-loaded read; none of it fetches.
//
// Three vocabulary decisions live here rather than in the page, because they
// are states to READ rather than magnitudes to compare - the health page's rule
// applied to the board:
//
//   * Provider status wears the same tone map the console's breaker rows use, so
//     a "degraded" provider and a "degraded" dependency look the same thing.
//   * `breaker_state` is printed beside the status it derives, never folded into
//     it: the status says how the provider is doing, the breaker says whether
//     the system is still trying.
//   * An unmeasured figure is the dash and a never-recorded failure says so in
//     words. Neither is ever rendered as a zero.

import type { ReactNode } from "react";

import { cn } from "@/lib/utils";
import {
  DASH,
  formatAge,
  formatCount,
  formatDuration,
  formatRate,
} from "@/lib/operator/observability-format";
import type {
  ErrorFeedEntry,
  OutboxHealthRow,
  ProviderBoardReport,
  QueueDepthRow,
} from "@/lib/operator/observability";

/**
 * Provider status tones, in the console's token vocabulary (the health page's
 * `STATE_TONES`, not a second idiom). `degraded` is the middle state and reads
 * as a warning rather than as a fault: a provider losing a tenth of its calls
 * is not the same event as one that has stopped.
 */
const PROVIDER_TONES: Record<string, string> = {
  healthy: "bg-success-soft text-success-text",
  degraded: "bg-warn-soft text-warn-text",
  down: "bg-danger-soft text-danger",
};

/**
 * Anything not named above - a feed row's own `status`, a response class, a
 * breaker state a later producer invents - renders plainly rather than falsely
 * alarming. An unknown value is not an emergency.
 */
const NEUTRAL_TONE = "bg-hairline-soft text-txt-muted";

export function StatusPill({
  value,
  testId,
}: {
  value: string;
  testId: string;
}) {
  return (
    <span
      data-testid={testId}
      className={cn(
        "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium",
        PROVIDER_TONES[value] ?? NEUTRAL_TONE,
      )}
    >
      {value}
    </span>
  );
}

/** The table shell every board on this page shares. */
function BoardTable({
  caption,
  testId,
  headers,
  children,
}: {
  caption: string;
  testId: string;
  headers: { label: string; right?: boolean }[];
  children: ReactNode;
}) {
  return (
    <table className="w-full text-sm" data-testid={testId}>
      <caption className="sr-only">{caption}</caption>
      <thead>
        <tr className="border-b border-hairline text-left text-xs text-txt-muted">
          {headers.map((header, index) => (
            <th
              key={header.label}
              scope="col"
              className={cn(
                "py-1.5 font-medium",
                header.right && "text-right",
                index < headers.length - 1 && "pr-3",
              )}
            >
              {header.label}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>{children}</tbody>
    </table>
  );
}

/**
 * The degraded-provider board (spec #717 stories 36-42).
 *
 * Every column a story names is here and none is dropped: the derived status
 * (37), the rate-limit and timeout counts (38, 39), the success rate with p50,
 * p95 and p99 (40), the breaker state (41) and the newest failure's reason (42).
 * p50 and p99 are the point of the three - a provider rejecting calls and a
 * provider answering them slowly look identical on a single percentile.
 */
export function ProviderBoardTable({
  report,
  testId,
}: {
  report: ProviderBoardReport;
  testId: string;
}) {
  return (
    <BoardTable
      testId={testId}
      caption="Provider health, with each provider's failure counts, response percentiles, circuit-breaker state and newest failure reason."
      headers={[
        { label: "Provider" },
        { label: "Status" },
        { label: "Breaker" },
        { label: "Success", right: true },
        { label: "Timeouts", right: true },
        { label: "Rate limits", right: true },
        { label: "p50", right: true },
        { label: "p95", right: true },
        { label: "p99", right: true },
        { label: "Last failure" },
      ]}
    >
      {report.providers.map((provider) => (
        <tr
          key={provider.provider}
          data-testid={`reliability-provider-${provider.provider}`}
          data-status={provider.status}
          className="border-b border-hairline-soft"
        >
          <th
            scope="row"
            className="py-1.5 pr-3 text-left font-normal text-txt"
          >
            {provider.provider}
          </th>
          <td className="py-1.5 pr-3">
            <StatusPill
              value={provider.status}
              testId={`reliability-provider-${provider.provider}-status`}
            />
          </td>
          <td
            className="py-1.5 pr-3 text-xs text-txt-sub"
            data-testid={`reliability-provider-${provider.provider}-breaker`}
          >
            {provider.breaker_state}
          </td>
          <td className="py-1.5 pr-3 text-right tabular-nums text-txt-sub">
            {formatRate(provider.success_rate)}
          </td>
          <td className="py-1.5 pr-3 text-right tabular-nums text-txt-sub">
            {formatCount(provider.timeout_count)}
          </td>
          <td className="py-1.5 pr-3 text-right tabular-nums text-txt-sub">
            {formatCount(provider.rate_limit_count)}
          </td>
          <td className="py-1.5 pr-3 text-right tabular-nums text-txt-sub">
            {formatDuration(provider.p50_duration_ms)}
          </td>
          <td className="py-1.5 pr-3 text-right tabular-nums text-txt-sub">
            {formatDuration(provider.p95_duration_ms)}
          </td>
          <td className="py-1.5 pr-3 text-right tabular-nums text-txt-sub">
            {formatDuration(provider.p99_duration_ms)}
          </td>
          <td className="py-1.5 text-txt-sub">
            {/* No failure recorded is its own words: an empty cell here reads as
                "we did not look", which is a different claim from "none". */}
            {provider.last_error ?? "none in this window"}
          </td>
        </tr>
      ))}
    </BoardTable>
  );
}

/** One collapsed failure, with the repeat count that justifies the collapse. */
export function ErrorRow({ entry }: { entry: ErrorFeedEntry }) {
  return (
    <li
      data-testid={`reliability-error-${entry.fingerprint}`}
      data-status={entry.status}
      className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-hairline-soft py-2.5 last:border-0"
    >
      <StatusPill
        value={entry.status_class}
        testId={`reliability-error-${entry.fingerprint}-status-class`}
      />
      <span className="font-mono text-xs text-txt-muted">
        {entry.method} {entry.route_template}
      </span>
      <span className="min-w-0 flex-1 text-sm text-txt">
        {entry.kind} · {entry.code}
      </span>
      {/* The collapse, stated. Without it a page of rows understates the outage
          by however many times each failure actually happened. */}
      <span
        data-testid={`reliability-error-${entry.fingerprint}-occurrences`}
        className="text-xs font-medium tabular-nums text-txt"
      >
        {formatCount(entry.occurrences)}×
      </span>
      <span
        data-testid={`reliability-error-${entry.fingerprint}-status`}
        className="text-xs text-txt-muted"
      >
        {entry.status}
      </span>
      <span
        className="font-mono text-xs text-txt-muted"
        title={entry.trace_id}
        data-testid={`reliability-error-${entry.fingerprint}-trace`}
      >
        {entry.trace_id}
      </span>
      <time
        dateTime={entry.last_seen_at}
        title={`First seen ${entry.first_seen_at}`}
        className="text-xs tabular-nums text-txt-muted"
      >
        {formatAge(entry.last_seen_at)}
      </time>
    </li>
  );
}

/**
 * The AI pipeline legs' depth and the age of their oldest waiting job (stories
 * 46, 47). An empty queue reports the dash rather than an age of zero: nothing
 * queued has no oldest job, and "0s waiting" would read as "waiting just
 * happened to arrive now".
 */
export function QueueTable({
  queues,
  testId,
}: {
  queues: QueueDepthRow[];
  testId: string;
}) {
  return (
    <BoardTable
      testId={testId}
      caption="Each AI pipeline leg's queued depth and the age of its oldest waiting job."
      headers={[
        { label: "Queue" },
        { label: "Depth", right: true },
        { label: "Oldest waiting", right: true },
        { label: "Enqueued at", right: true },
      ]}
    >
      {queues.map((queue) => (
        <tr
          key={queue.queue}
          data-testid={`reliability-queue-${queue.queue}`}
          className="border-b border-hairline-soft"
        >
          <th
            scope="row"
            className="py-1.5 pr-3 text-left font-normal text-txt"
          >
            {queue.queue}
          </th>
          <td className="py-1.5 pr-3 text-right tabular-nums text-txt-sub">
            {formatCount(queue.depth)}
          </td>
          <td className="py-1.5 pr-3 text-right tabular-nums text-txt-sub">
            {formatDuration(
              queue.oldest_age_s === null ? null : queue.oldest_age_s * 1000,
            )}
          </td>
          <td className="py-1.5 text-right text-xs text-txt-muted">
            {queue.oldest_enqueued_at ?? DASH}
          </td>
        </tr>
      ))}
    </BoardTable>
  );
}

/**
 * The per-module outbox backlog (spec #717 story 49), broken out by table.
 *
 * This breakdown is the whole reason the read carries the rows rather than just
 * the sum: a single backlog figure averages a stuck module into a healthy
 * system, and the question story 49 asks is WHICH module is stuck.
 */
export function OutboxTable({
  outbox,
  testId,
}: {
  outbox: OutboxHealthRow[];
  testId: string;
}) {
  if (outbox.length === 0) return null;
  return (
    <section data-testid={testId}>
      <h3 className="mb-2 text-xs font-medium text-txt-sub">
        Backlog by module outbox
      </h3>
      <BoardTable
        testId={`${testId}-table`}
        caption="Each module outbox's pending, in-flight, dead-lettered and total backlog rows."
        headers={[
          { label: "Outbox" },
          { label: "Pending", right: true },
          { label: "In flight", right: true },
          { label: "Dead letter", right: true },
          { label: "Backlog", right: true },
        ]}
      >
        {outbox.map((row) => (
          <tr
            key={`${row.table_schema}.${row.table}`}
            data-testid={`reliability-outbox-${row.table}`}
            className="border-b border-hairline-soft"
          >
            <th
              scope="row"
              className="py-1.5 pr-3 text-left font-normal text-txt"
            >
              {row.table_schema}.{row.table}
            </th>
            <td className="py-1.5 pr-3 text-right tabular-nums text-txt-sub">
              {formatCount(row.pending)}
            </td>
            <td className="py-1.5 pr-3 text-right tabular-nums text-txt-sub">
              {formatCount(row.inflight)}
            </td>
            <td className="py-1.5 pr-3 text-right tabular-nums text-txt-sub">
              {formatCount(row.dead_letter)}
            </td>
            <td className="py-1.5 text-right tabular-nums text-txt-sub">
              {formatCount(row.backlog)}
            </td>
          </tr>
        ))}
      </BoardTable>
    </section>
  );
}

/**
 * The questions this panel can be asked - a status filter, a page number.
 *
 * `T` is the status the panel's read actually accepts, so a filter control
 * cannot offer the read a value it will reject with a 422. The current filter
 * is plain text with `aria-pressed`: it is a state, not a destination, so it is
 * not a link to itself.
 */
export function StatusFilter<T extends string>({
  filters,
  current,
  onSelect,
  testIdPrefix,
}: {
  filters: { id: T; label: string }[];
  current: T;
  onSelect: (id: T) => void;
  testIdPrefix: string;
}) {
  return (
    <div
      role="group"
      aria-label="Filter by status"
      className="flex flex-wrap gap-2"
      data-testid={`${testIdPrefix}-filter`}
    >
      {filters.map((filter) => {
        const selected = filter.id === current;
        return (
          <button
            key={filter.id}
            type="button"
            aria-pressed={selected}
            onClick={() => onSelect(filter.id)}
            data-testid={`${testIdPrefix}-filter-${filter.id}`}
            className={cn(
              "inline-flex min-h-11 items-center rounded-md border px-3 text-xs font-medium",
              selected
                ? "border-accent-border bg-accent-soft text-accent-strong"
                : "border-hairline bg-surface text-txt-sub hover:bg-hairline-soft",
            )}
          >
            {filter.label}
          </button>
        );
      })}
    </div>
  );
}
