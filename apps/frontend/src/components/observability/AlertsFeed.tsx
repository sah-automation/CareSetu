"use client";

// #710 C3: the inline operator alert feed (plan-phase14-observability §9.2,
// §11). One panel on the overview landing page reads GET
// /v1/operator/observability/alerts and renders the standing alert record,
// newest first - severity, kind, title and when it fired.
//
// Alert acknowledgement is Batch 2, so the feed is read-only by design: no ack
// action, no status write, and no open/resolved filter - the route answers the
// record and a resolved alert stays reviewable until a later pass adds ack. The
// data contract is `obs_alert_events`
// (severity/kind/title/payload/status/created_at/acked_by); `severity` is the
// one column the row styles on.
//
// The panel takes the read as a prop (the page owns the fetch) and renders
// through the shared ReadPanel, so the loading skeleton, the inline error with
// the API's trace id, the retry and the empty state are the same ones every
// other observability panel owes an operator.

import { cn } from "@/lib/utils";
import type { AlertEntry, AlertPage } from "@/lib/operator/observability";
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
 * How long ago an alert fired, in the operator queue's register ("2h", "3
 * days"). A feed reads as a timeline, and "when" is the question an operator
 * asks before "what"; the exact timestamp stays in the element's `title`/`dateTime`
 * for anyone who needs it. No PHI is involved - `created_at` is a clock time.
 */
function alertAge(createdAt: string): string {
  const ms = Date.now() - new Date(createdAt).getTime();
  if (ms < 60_000) return "< 1m";
  const minutes = Math.floor(ms / 60_000);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h`;
  const days = Math.floor(hours / 24);
  return days === 1 ? "1 day" : `${days} days`;
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

function AlertRow({ alert }: { alert: AlertEntry }) {
  return (
    <li
      data-testid={`observability-alert-${alert.id}`}
      data-severity={alert.severity}
      className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-hairline-soft py-2.5 last:border-0"
    >
      <SeverityBadge
        severity={alert.severity}
        testId={`observability-alert-${alert.id}-severity`}
      />
      <span className="font-mono text-xs text-txt-muted">{alert.kind}</span>
      <span className="min-w-0 flex-1 text-sm text-txt">{alert.title}</span>
      <time
        dateTime={alert.created_at}
        title={alert.created_at}
        className="text-xs tabular-nums text-txt-muted"
      >
        {alertAge(alert.created_at)}
      </time>
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

export function AlertsFeed({ read }: { read: PanelRead<AlertPage> }) {
  return (
    <ReadPanel
      testId="observability-alerts"
      title="Recent alerts"
      read={read}
      isEmpty={(page) => page.alerts.length === 0}
      emptyTitle="No alerts"
      emptyBody="No significant events have been recorded yet."
      errorMessage="Could not load the alert feed."
      takeaway={read.data ? feedTakeaway(read.data) : undefined}
    >
      {(page) => (
        <ul className="flex flex-col" data-testid="observability-alerts-list">
          {page.alerts.map((alert) => (
            <AlertRow key={alert.id} alert={alert} />
          ))}
        </ul>
      )}
    </ReadPanel>
  );
}
