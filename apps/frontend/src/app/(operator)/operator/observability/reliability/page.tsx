"use client";

// #738: the operator Reliability lens page (spec #717, plan-phase14 §9.2).
// Six panels on one route, answering the questions an on-call operator asks in
// order: who is failing, what is failing, how much is failing, is anything
// piling up, is anyone working, and what is on fire.
//   * the degraded-provider board   <- GET .../providers        (#728)
//   * the live collapsed error feed <- GET .../errors           (#730)
//   * throughput and error rate     <- GET .../throughput       (#727)
//   * queue depth, age and backlog <- GET .../reliability      (#729)
//   * recent activity              <- GET .../reliability      (#729)
//   * the alert feed, acknowledge  <- GET/POST .../alerts      (#734/#735)
// Plus the deep links, so the page is not a dead end.
//
// FIVE reads, not six, and the two queue panels share one on purpose: queue
// depth and recent activity are two answers about the same instant, so a page
// that re-read them separately could show a drained queue beside a burst of
// actors and leave the operator to work out which one moved first.
//
// Four things the page refuses to do:
//
//   * call `recent_active_actors` concurrency. True concurrency is an
//     OpenTelemetry gauge that lives in the tracing backend, and the read hands
//     this page a link to it. The actor count is derived from the module's own
//     consumed-event ledger, so the panel says "recent activity" in its title,
//     its figure and its copy - and the gauge link is what completes it
//     (spec #717 decision 17). The panel is never EMPTY, precisely so the link
//     cannot disappear at the one moment an operator most wants to check it.
//   * report the error feed by its row count. `total_count` is the number of
//     DISTINCT failures and `total_occurrences` is how many times they actually
//     happened; a panel showing only the first understates an outage by the
//     repetition factor.
//   * let an empty feed read as a healthy system. Spec #717 story 35 asks for
//     exactly this: the feed's empty state borrows the capture read's own
//     liveness, so "nothing failing" and "nothing was watching" are different
//     sentences.
//   * render an unconfigured vendor as a placeholder. A panel renders the links
//     it has CONTEXT for - the error feed hands the read its newest failure's
//     trace and error code - and a vendor that is switched off, or a view it has
//     no filter for, is simply absent (#736).
//
// Every state - loading, empty, failure with retry - belongs to the panel that
// owns the read (blueprint §9.1). The frame is ReadPanel, unchanged.

import { useCallback, useEffect, useRef, useState } from "react";
import { ExternalLink } from "lucide-react";

import { AlertsFeed } from "@/components/observability/AlertsFeed";
import { DeeplinksPanel } from "@/components/observability/DeeplinksPanel";
import {
  ObservabilityPanelPage,
  ReadPanel,
} from "@/components/observability/ObservabilityPanelPage";
import { ThroughputPerMinuteChart } from "@/components/observability/ReliabilityCharts";
import {
  ErrorRow,
  OutboxTable,
  ProviderBoardTable,
  QueueTable,
  StatusFilter,
} from "@/components/observability/ReliabilityPanels";
import { idempotencyKey } from "@/lib/idempotency";
import { ApiError } from "@/lib/api-errors";
import {
  acknowledgeAlert,
  fetchAlerts,
  fetchDeeplinks,
  fetchErrors,
  fetchProviders,
  fetchReliability,
  fetchThroughput,
  type AlertStatus,
  type ErrorFeedPage,
  type ErrorFeedStatus,
  type ReliabilityReport,
  type ThroughputReport,
} from "@/lib/operator/observability";
import {
  DASH,
  formatCount,
  formatDuration,
  formatRate,
} from "@/lib/operator/observability-format";
import { usePanelRead, type PanelRead } from "@/lib/operator/usePanelRead";

/** No provider has ever been rolled up, so the board has nothing to say. */
const NO_PROVIDERS_BODY =
  "The nightly rollup has not recorded any provider health yet.";

/**
 * Nothing was captured in the window. Distinct from a window with zero
 * requests: a recorder that is switched OFF reads as "nothing is wrong" until
 * an operator knows it was never listening, which is the more dangerous of the
 * two.
 */
const NO_TRAFFIC_BODY =
  "No request has been captured in this window, so there is no throughput to report.";

/** The recorder is off, which is a fact about the deployment, not about traffic. */
const CAPTURE_OFF_BODY =
  "The request recorder is switched off for this deployment, so nothing on this panel was measured.";

/**
 * The error feed's quiet-state copy when the recorder IS on (the common case).
 *
 * A DIFFERENT sentence is used when the capture read says the recorder is off -
 * see `captureOffEmptyBody` - because "no failure was captured" and "nothing
 * was being watched" are not the same reassurance (spec #717 story 35).
 */
const NO_ERRORS_BODY =
  "No captured failure matches this filter in the window. The recorder is running, so this slice is genuinely quiet.";

function captureOffEmptyBody(): string {
  return "The request recorder is switched off for this deployment, so an empty feed means nothing was captured rather than nothing failing.";
}

/** Every AI leg is drained and nothing is queued anywhere. */
const NO_BACKLOG_BODY = "Every AI queue is empty and nothing is waiting.";

/** Rows requested per feed page. The route caps this at 100. */
const FEED_PAGE_SIZE = 25;

/**
 * A panel read that re-runs when the page changes the QUESTION it asked - a
 * filter, a page number, the trace the newest failure carries.
 *
 * `usePanelRead` fires once on mount and then only on Retry, because its loader
 * is held in a ref. A read whose parameters live in page state needs both: the
 * ref keeps the loader fresh, and this effect re-runs it when the key changes.
 * The first render is skipped explicitly - `usePanelRead`'s own mount effect has
 * already fired, and a second read there would double every request the page
 * makes on load.
 */
function useKeyedRead<T>(load: () => Promise<T>, key: string): PanelRead<T> {
  const read = usePanelRead(load);
  const reload = read.reload;
  const mounted = useRef(false);

  useEffect(() => {
    if (!mounted.current) {
      mounted.current = true;
      return;
    }
    reload();
  }, [key, reload]);

  return read;
}

/** The statuses the alert feed offers as a filter. `acknowledged` is #735's. */
const ALERT_FILTERS: { id: AlertStatus; label: string }[] = [
  { id: "open", label: "Open" },
  { id: "acknowledged", label: "Acknowledged" },
  { id: "resolved", label: "Resolved" },
];

/** The error feed takes NARROWER statuses than the alert feed - see the type. */
const ERROR_FILTERS: { id: ErrorFeedStatus; label: string }[] = [
  { id: "open", label: "Open" },
  { id: "resolved", label: "Resolved" },
];

/** The provider board's one line: how many are well, and how many are not. */
function providerTakeaway(report: {
  providers: { status: string }[];
  last_rolled_date: string | null;
}): string {
  const counts = report.providers.reduce<Record<string, number>>(
    (tally, row) => ({ ...tally, [row.status]: (tally[row.status] ?? 0) + 1 }),
    {},
  );
  const tally =
    Object.keys(counts)
      .map((status) => `${counts[status]} ${status}`)
      .join(" · ") || "no providers";
  return `${tally} · ${
    report.last_rolled_date
      ? `as of the ${report.last_rolled_date} roll`
      : "no roll has run yet"
  }`;
}

/**
 * The throughput panel's one line: the rate, the errors and the error rate,
 * which are three different questions. `null` prints as the dash rather than as
 * zero - "no samples" is not "a clean window".
 */
function throughputTakeaway(read: ThroughputReport): string {
  const rate =
    read.requests_per_minute === null
      ? DASH
      : `${read.requests_per_minute} req/min`;
  const parts = [
    `${rate} · ${formatCount(read.requests)} requests · ${formatCount(
      read.errors,
    )} errors`,
    `${formatRate(read.error_rate)} error rate`,
    `last ${read.minutes} minutes`,
  ];
  if (!read.capture.capturing) parts.push("the recorder is off");
  return parts.join(" · ");
}

function queueTakeaway(read: ReliabilityReport): string {
  const oldest =
    read.oldest_queued_age_s === null
      ? "nothing queued"
      : `oldest waiting ${formatDuration(read.oldest_queued_age_s * 1000)}`;
  return (
    `${formatCount(read.queue_depth)} queued · ${oldest} · ` +
    `${formatCount(read.outbox_backlog)} in the outbox · ` +
    `${formatCount(read.dead_letter_rows)} dead-lettered`
  );
}

/**
 * The feed's one line: distinct failures, and every occurrence behind them.
 *
 * Both numbers, always. `total_count` alone reads as "12 problems" for an
 * outage that threw twelve thousand requests, and an operator triaging on it
 * would size the incident wrongly.
 */
function errorTakeaway(page: ErrorFeedPage): string {
  const shown = page.errors.length;
  const distinct =
    page.total_count > shown
      ? `Showing ${shown} of ${page.total_count} distinct failures`
      : `${page.total_count} distinct ${
          page.total_count === 1 ? "failure" : "failures"
        }`;
  return `${distinct} · ${formatCount(
    page.total_occurrences,
  )} occurrences · last ${page.window_minutes} minutes`;
}

/** What a failed acknowledgement says, per the two error classes (standards §1). */
function acknowledgeError(thrown: unknown): string {
  if (thrown instanceof ApiError && thrown.traceId) {
    return `Could not acknowledge that alert. It may already have been resolved. Trace: ${thrown.traceId}`;
  }
  return "Could not acknowledge that alert: the request did not reach the API. It may already have been resolved.";
}

export default function ObservabilityReliabilityPage() {
  const [errorStatus, setErrorStatus] = useState<ErrorFeedStatus>("open");
  const [errorPage, setErrorPage] = useState(1);
  const [alertStatus, setAlertStatus] = useState<AlertStatus>("open");
  const [pendingAck, setPendingAck] = useState<string | null>(null);
  const [ackError, setAckError] = useState<string | null>(null);

  const providers = usePanelRead(() => fetchProviders());
  const throughput = usePanelRead(() => fetchThroughput());
  // ONE read behind two panels - see the header.
  const reliability = usePanelRead(() => fetchReliability());

  const errors = useKeyedRead(
    () =>
      fetchErrors({
        page: errorPage,
        page_size: FEED_PAGE_SIZE,
        status: errorStatus,
      }),
    `${errorStatus}:${errorPage}`,
  );

  const alerts = useKeyedRead(
    () => fetchAlerts({ page_size: FEED_PAGE_SIZE, status: alertStatus }),
    alertStatus,
  );

  const deeplinks = usePanelRead(() => fetchDeeplinks());

  /**
   * The error feed's own links, scoped to the newest captured failure: its
   * trace opens that trace in Explore and Sentry, and its error code narrows
   * the Sentry query to the class of failure being looked at.
   *
   * ONE read for the whole feed, not one per row - twenty-five rows would be
   * twenty-five requests to fetch twenty-five links that mostly say the same
   * thing. When there is no failure to point at, the read resolves empty and the
   * panel below is not rendered at all: absent, not a broken link.
   */
  const newest = errors.data?.errors[0] ?? null;
  const errorLinks = useKeyedRead(
    () =>
      newest === null
        ? Promise.resolve({})
        : fetchDeeplinks({
            trace_id: newest.trace_id,
            error_type: newest.code,
          }),
    newest === null ? "" : `${newest.trace_id}:${newest.code}`,
  );

  /**
   * The acknowledgement key for an alert, held across a failed attempt.
   *
   * The key is minted on the FIRST click and reused by the operator's retry, so
   * a retry after a lost response cannot double-issue (api-standards §5). It is
   * released the moment the write succeeds - the alert is acknowledged, and a
   * fresh key belongs to the next, different attempt.
   */
  const ackKeys = useRef(new Map<string, string>());
  const reloadAlerts = alerts.reload;

  const acknowledge = useCallback(
    async (alertId: string) => {
      setPendingAck(alertId);
      setAckError(null);
      const key = ackKeys.current.get(alertId) ?? idempotencyKey();
      ackKeys.current.set(alertId, key);
      try {
        await acknowledgeAlert(alertId, key);
        ackKeys.current.delete(alertId);
        // Re-read rather than patch the row in place. The feed is FILTERED, so
        // an acknowledged alert must leave the open list on the server's terms -
        // a locally-patched row would still be sitting there claiming to be
        // open until the next unrelated read.
        reloadAlerts();
      } catch (thrown) {
        setAckError(acknowledgeError(thrown));
      } finally {
        setPendingAck(null);
      }
    },
    [reloadAlerts],
  );

  const errorRead = errors.data;
  const queueRead = reliability.data;
  const captureOff = throughput.data?.capture.capturing === false;
  const totalErrorPages = errorRead
    ? Math.max(1, Math.ceil(errorRead.total_count / FEED_PAGE_SIZE))
    : 1;

  return (
    <ObservabilityPanelPage
      current="reliability"
      title="Reliability"
      description="Which providers are failing, what is failing, how fast it is arriving and what is piling up."
    >
      <div className="flex flex-col gap-4">
        <ReadPanel
          testId="reliability-providers"
          title="Provider board"
          read={providers}
          isEmpty={(report) => report.providers.length === 0}
          emptyTitle="No provider telemetry yet"
          emptyBody={NO_PROVIDERS_BODY}
          errorMessage="Could not load the provider board."
          takeaway={
            providers.data ? providerTakeaway(providers.data) : undefined
          }
        >
          {(report) => (
            <div className="flex flex-col gap-4">
              {report.last_rolled_date && (
                <p
                  data-testid="reliability-providers-window"
                  className="text-xs text-txt-muted"
                >
                  Health is a snapshot as of the {report.last_rolled_date} roll,
                  not a live measurement.
                </p>
              )}
              <ProviderBoardTable
                report={report}
                testId="reliability-providers-table"
              />
            </div>
          )}
        </ReadPanel>

        <ReadPanel
          testId="reliability-error-feed"
          title="Live error feed"
          read={errors}
          isEmpty={(page) => page.errors.length === 0}
          emptyTitle="No captured failures"
          emptyBody={captureOff ? captureOffEmptyBody() : NO_ERRORS_BODY}
          errorMessage="Could not load the live error feed."
          takeaway={errorRead ? errorTakeaway(errorRead) : undefined}
          controls={
            <div className="flex flex-wrap items-center justify-between gap-2">
              <StatusFilter
                filters={ERROR_FILTERS}
                current={errorStatus}
                onSelect={(id) => {
                  setErrorStatus(id);
                  setErrorPage(1);
                }}
                testIdPrefix="reliability-error"
              />
              <div
                className="flex items-center gap-2"
                data-testid="reliability-error-pager"
              >
                <button
                  type="button"
                  onClick={() =>
                    setErrorPage((current) => Math.max(1, current - 1))
                  }
                  disabled={errorPage <= 1}
                  data-testid="reliability-error-prev"
                  className="inline-flex min-h-11 items-center rounded-md border border-hairline px-3 text-xs font-medium text-txt-sub hover:bg-hairline-soft disabled:opacity-50"
                >
                  Previous
                </button>
                <span className="text-xs tabular-nums text-txt-muted">
                  <span data-testid="reliability-error-page">{errorPage}</span>
                  {" of "}
                  {totalErrorPages}
                </span>
                <button
                  type="button"
                  onClick={() => setErrorPage((current) => current + 1)}
                  disabled={errorPage >= totalErrorPages}
                  data-testid="reliability-error-next"
                  className="inline-flex min-h-11 items-center rounded-md border border-hairline px-3 text-xs font-medium text-txt-sub hover:bg-hairline-soft disabled:opacity-50"
                >
                  Next
                </button>
              </div>
            </div>
          }
        >
          {(page) => (
            <ul className="flex flex-col" data-testid="reliability-error-list">
              {page.errors.map((entry) => (
                <ErrorRow key={entry.fingerprint} entry={entry} />
              ))}
            </ul>
          )}
        </ReadPanel>

        {/* The feed's own links, scoped to the newest failure it is showing. */}
        {newest !== null && (
          <DeeplinksPanel
            read={errorLinks}
            testId="reliability-error-deeplinks"
            linkIdPrefix="reliability-error-deeplink"
            title="Open the newest failure in your tools"
            emptyTitle="No vendor links for this failure"
            emptyBody="This failure has no trace or error type a vendor can be filtered by."
          />
        )}

        <ReadPanel
          testId="reliability-throughput"
          title="Throughput and error rate"
          read={throughput}
          isEmpty={(report) => report.points.length === 0}
          emptyTitle={
            captureOff ? "The request recorder is off" : "No traffic captured"
          }
          emptyBody={captureOff ? CAPTURE_OFF_BODY : NO_TRAFFIC_BODY}
          errorMessage="Could not load throughput and error rate."
          takeaway={
            throughput.data ? throughputTakeaway(throughput.data) : undefined
          }
        >
          {(report) => (
            <div className="flex flex-col gap-4">
              <p
                data-testid="reliability-throughput-window"
                className="text-xs text-txt-muted"
              >
                {report.from_ts} to {report.to_ts}
              </p>
              <ThroughputPerMinuteChart
                points={report.points}
                testId="reliability-throughput-chart"
              />
            </div>
          )}
        </ReadPanel>

        <ReadPanel
          testId="reliability-queues"
          title="Queue depth and age"
          read={reliability}
          isEmpty={(report) => report.queue_depth === 0}
          emptyTitle="Nothing queued"
          emptyBody={NO_BACKLOG_BODY}
          errorMessage="Could not load the AI queue depths."
          takeaway={queueRead ? queueTakeaway(queueRead) : undefined}
        >
          {(report) => (
            <div className="flex flex-col gap-6">
              <QueueTable
                queues={report.queues}
                testId="reliability-queues-table"
              />
              <OutboxTable outbox={report.outbox} testId="reliability-outbox" />
            </div>
          )}
        </ReadPanel>

        <ReadPanel
          testId="reliability-concurrency"
          title="Recent activity, not simultaneous concurrency"
          read={reliability}
          // NEVER empty, and that is the point. The gauge link below is how an
          // operator sees true concurrency; an empty state would hide it at
          // exactly the moment they most doubt the number below it. A quiet
          // platform reads as zero actors, which is a fact, not an absence.
          isEmpty={() => false}
          emptyTitle="No recent activity"
          emptyBody="No patient, doctor or system actor has been active in this window."
          errorMessage="Could not load recent activity."
          takeaway={
            queueRead
              ? `${formatCount(
                  queueRead.recent_active_actors,
                )} distinct actors in the last ${
                  queueRead.activity_window_minutes
                } minutes`
              : undefined
          }
        >
          {(report) => (
            <div className="flex flex-col gap-3">
              <p
                data-testid="reliability-concurrency-figures"
                className="text-2xl font-semibold tabular-nums text-txt"
              >
                {formatCount(report.recent_active_actors)}
              </p>
              <p
                className="text-sm text-txt-sub"
                data-testid="reliability-concurrency-explanation"
              >
                Distinct actors active in the last{" "}
                {report.activity_window_minutes} minutes, counted from the
                platform&apos;s own consumed-event ledger. This is how many
                people and systems have been here recently - not how many
                requests were in flight at once, which this platform cannot
                measure.
              </p>
              {report.concurrency_grafana_link ? (
                <a
                  href={report.concurrency_grafana_link}
                  target="_blank"
                  rel="noopener noreferrer"
                  data-testid="reliability-concurrency-gauge-link"
                  className="inline-flex min-h-11 w-fit items-center gap-1.5 self-start rounded-md border border-hairline bg-surface px-3 text-sm font-medium text-txt-sub transition-colors hover:border-accent-border hover:bg-accent-soft hover:text-accent-strong"
                >
                  Simultaneous requests right now in Grafana
                  <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
                </a>
              ) : (
                <p
                  data-testid="reliability-concurrency-gauge-absent"
                  className="text-sm text-txt-muted"
                >
                  The tracing backend is not configured for this deployment, so
                  there is no live concurrency gauge to open.
                </p>
              )}
            </div>
          )}
        </ReadPanel>

        <AlertsFeed
          read={alerts}
          controls={
            <StatusFilter
              filters={ALERT_FILTERS}
              current={alertStatus}
              onSelect={setAlertStatus}
              testIdPrefix="reliability-alerts"
            />
          }
          onAcknowledge={(alertId) => void acknowledge(alertId)}
          pendingId={pendingAck}
          writeError={ackError}
        />

        <DeeplinksPanel read={deeplinks} />
      </div>
    </ObservabilityPanelPage>
  );
}
