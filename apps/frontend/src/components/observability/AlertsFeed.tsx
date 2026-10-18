"use client";

// #710 C3: the inline operator alert feed (plan-phase14-observability §9.2,
// §11). One panel on the overview landing page reads GET
// /v1/operator/observability/alerts and renders the standing alert record,
// newest first - severity, kind, title and when it fired.
//
// The feed is read-only unless a page hands it an `onAcknowledge`. #735 added
// the acknowledgement write and #738 added the panel that performs it, so the
// affordance lives here - on the one feed - rather than in a second component
// the two pages would drift apart on. The Overview page passes no callback and
// keeps exactly the read-only feed it has always had.
//
// The panel takes the read as a prop (the page owns the fetch) and renders
// through the shared ReadPanel, so the loading skeleton, the inline error with
// the API's trace id, the retry and the empty state are the same ones every
// other observability panel owes an operator.

import type { ReactNode } from "react";

import { cn } from "@/lib/utils";
import type { AlertEntry, AlertPage } from "@/lib/operator/observability";
import { formatAge } from "@/lib/operator/observability-format";
import type { PanelRead } from "@/lib/operator/usePanelRead";
import { ReadPanel } from "@/components/observability/ObservabilityPanelPage";

/**
 * Severity tones in the console's token vocabulary. `critical` is the audit
 * tamper / breaker-open / dead-letter class, `warning` the budget and backlog
 * class. Anything else - `info`, or a severity a later producer adds - falls to
 * the neutral tone, so an unknown value renders plainly rather than as an
 * un-styled or, worse, falsely alarming row.
 */
const SEVERITY_TONES: Record<string, string> = {
  critical: "bg-danger-soft text-danger",
  warning: "bg-warn-soft text-warn-text",
  info: "bg-accent-soft text-accent-strong",
};

const SEVERITY_FALLBACK_TONE = "bg-hairline-soft text-txt-muted";

/**
 * Who took this alert, and when.
 *
 * #735 writes `acked_by` (the acknowledging operator's identity) and
 * `acked_at`, and spec #717 story 52 asks for both on screen: an acknowledgement
 * nobody can attribute is not a response, only a state change. The identity is
 * an integer reference and is printed as one - the read does not carry a
 * display name, and inventing one here would put a fabricated human next to a
 * real audit column.
 */
function acknowledgedBy(alert: AlertEntry): string | null {
  if (alert.acked_by === null || alert.acked_at === null) return null;
  return `operator ${alert.acked_by} · ${formatAge(alert.acked_at)} ago`;
}

function SeverityBadge({
  severity,
  testId,
}: {
  severity: string;
  testId: string;
}) {
  return (
    <span
      data-testid={testId}
      className={cn(
        "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium",
        SEVERITY_TONES[severity] ?? SEVERITY_FALLBACK_TONE,
      )}
    >
      {severity}
    </span>
  );
}

function AlertRow({
  alert,
  onAcknowledge,
  pending,
}: {
  alert: AlertEntry;
  onAcknowledge: ((alertId: string) => void) | undefined;
  pending: boolean;
}) {
  const acked = alert.status !== "open";
  const ack = acknowledgedBy(alert);
  return (
    <li
      data-testid={`observability-alert-${alert.id}`}
      data-severity={alert.severity}
      data-status={alert.status}
      className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-hairline-soft py-2.5 last:border-0"
    >
      <SeverityBadge
        severity={alert.severity}
        testId={`observability-alert-${alert.id}-severity`}
      />
      <span className="font-mono text-xs text-txt-muted">{alert.kind}</span>
      <span className="min-w-0 flex-1 text-sm text-txt">{alert.title}</span>
      <span
        className="text-xs text-txt-muted"
        data-testid={`observability-alert-${alert.id}-status`}
      >
        {alert.status}
      </span>
      <time
        dateTime={alert.created_at}
        title={alert.created_at}
        className="text-xs tabular-nums text-txt-muted"
      >
        {formatAge(alert.created_at)}
      </time>
      {ack && (
        <span
          data-testid={`observability-alert-${alert.id}-acked-by`}
          className="text-xs text-txt-muted"
        >
          {ack}
        </span>
      )}
      {/* min-h-11 keeps the target at the 44px the blueprint's touch-target rule
          asks for; a text-sized button is under half that. */}
      {onAcknowledge && !acked && (
        <button
          type="button"
          onClick={() => onAcknowledge(alert.id)}
          disabled={pending}
          data-testid={`observability-alert-${alert.id}-acknowledge`}
          className="inline-flex min-h-11 items-center rounded-md border border-hairline px-3 text-xs font-medium text-txt-sub hover:bg-hairline-soft disabled:opacity-60"
        >
          {pending ? "Acknowledging…" : "Acknowledge"}
        </button>
      )}
    </li>
  );
}

/**
 * The alert feed. A single unpaged route answer, so the takeaway is honest
 * about truncation: `total_count` is every matching row, and when the route
 * capped the page the heading says how many of the total are shown.
 */
function feedTakeaway(page: AlertPage): string {
  const shown = page.alerts.length;
  if (page.total_count <= shown) {
    return `${page.total_count} ${page.total_count === 1 ? "alert" : "alerts"}`;
  }
  return `Showing the latest ${shown} of ${page.total_count} alerts`;
}

export function AlertsFeed({
  read,
  controls,
  onAcknowledge,
  pendingId,
  writeError,
}: {
  read: PanelRead<AlertPage>;
  /**
   * The page's status filter, rendered above the rows.
   *
   * The filter is a QUESTION about the read - which slice of the feed is this -
   * so the page that owns the read owns the control, and this feed renders it
   * where an operator looks. A page that wants no filter simply omits it.
   */
  controls?: ReactNode;
  /**
   * Acknowledge an open alert, or omit it for a read-only feed.
   *
   * The write is the caller's: this component never decides to re-read, because
   * only the page knows that the feed it feeds is one of several. Passing it in
   * is also what keeps the Overview page read-only - it renders the same rows
   * without the affordance, rather than a second, subtly different feed.
   */
  onAcknowledge?: (alertId: string) => void;
  /** The alert whose acknowledgement is in flight, so only its row disables. */
  pendingId?: string | null;
  /** What a failed acknowledgement says, if one has failed. */
  writeError?: string | null;
}) {
  const writeFailure = writeError ? (
    <p
      role="alert"
      data-testid="observability-alerts-acknowledge-error"
      className="mt-2 rounded-md border border-danger-border bg-danger-soft px-3 py-2 text-xs text-danger"
    >
      {writeError}
    </p>
  ) : null;

  // Controls and the write's own failure both ride the `controls` slot rather
  // than the body: a successful acknowledgement is exactly the case where the
  // open list goes EMPTY, and a failure message that vanished with the row it
  // was about would be the worst possible place for it to disappear.
  const header =
    controls || writeFailure ? (
      <div className="flex flex-col">
        {controls}
        {writeFailure}
      </div>
    ) : undefined;

  return (
    <ReadPanel
      testId="observability-alerts"
      title="Recent alerts"
      read={read}
      controls={header}
      isEmpty={(page) => page.alerts.length === 0}
      emptyTitle="No alerts"
      emptyBody="No significant events have been recorded yet."
      errorMessage="Could not load the alert feed."
      takeaway={read.data ? feedTakeaway(read.data) : undefined}
    >
      {(page) => (
        <ul className="flex flex-col" data-testid="observability-alerts-list">
          {page.alerts.map((alert) => (
            <AlertRow
              key={alert.id}
              alert={alert}
              onAcknowledge={onAcknowledge}
              pending={pendingId === alert.id}
            />
          ))}
        </ul>
      )}
    </ReadPanel>
  );
}
