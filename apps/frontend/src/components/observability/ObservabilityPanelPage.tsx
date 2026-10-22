"use client";

// #709 C2b: the Observability panel page shell and its one read-scoped panel
// frame (plan-phase14-observability §9.2, blueprint §9.1).
//
// Four pages owe the same three states and the same cross-links. Restating the
// loading/empty/failure logic per page is how the overview page and a panel end
// up disagreeing about what a failed read looks like, so the closure lives here
// once and each page contributes only its reads and its charts.
//
// The states, unchanged from the C2a overview page:
//   * loading -> a skeleton matching the panel's final footprint, never a
//     full-page spinner (§9.1);
//   * a panel with nothing in it -> an EmptyState saying so. "No telemetry yet"
//     is a different fact from "telemetry that says nothing is wrong";
//   * failure -> a quiet inline retry IN PLACE, with the API's trace_id
//     (§9.1 "inline - card/row-scoped failure ... quiet retry link in place").
//     Not a page banner: a panel reads one route of its own, so a page banner
//     over four panels would report one panel's failure as the whole page's and
//     leave the other three blank. It is the same reasoning that puts the
//     cost trend and the budget in two panels rather than one "Cost" read.

import type { ReactNode } from "react";

import { EmptyState } from "@/components/layout/EmptyState";
import { PageHeader } from "@/components/layout/PageHeader";
import { Skeleton } from "@/components/ui/skeleton";
import type { PanelRead } from "@/lib/operator/usePanelRead";
import { cn } from "@/lib/utils";

/**
 * The page frame: header, then the panels. Deliberately thin - every
 * state decision belongs to the panel that owns the read, not to the page.
 *
 * #747 (spec #717 decision 35): it no longer renders a page-level panel strip.
 * The observability destinations live once in the nav configuration's children
 * (`nav-config.ts`), which both the sidebar disclosure and the mobile More
 * sheet render, so the two navigations no longer duplicate each other and a
 * new panel adds a destination by declaring it there.
 */
export function ObservabilityPanelPage({
  title,
  description,
  children,
}: {
  title: ReactNode;
  description: ReactNode;
  children: ReactNode;
}) {
  return (
    <>
      <PageHeader title={title} description={description} />
      {children}
    </>
  );
}

interface ReadPanelProps<T> {
  /** Names the panel in tests; also the id its parts are numbered off. */
  testId: string;
  title: ReactNode;
  /** The one line an operator reads before the plot ("₹1,250 of ₹5,000"). */
  takeaway?: ReactNode;
  /**
   * The questions an operator can ask this panel - a status filter, a window
   * picker - rendered under the title in EVERY state.
   *
   * Not inside the body, and that is the whole point. A body renders only when
   * the read came back with something in it, so a filter living there
   * disappears exactly when its current slice is empty - which is the one
   * moment an operator most needs to switch to a different one. These are
   * questions about the read, not results of it, so they sit outside the
   * result.
   */
  controls?: ReactNode;
  read: PanelRead<T>;
  /** Whether this read came back with nothing worth plotting. */
  isEmpty: (data: T) => boolean;
  /** What is empty, in the panel's own terms ("No budget configured"). */
  emptyTitle: ReactNode;
  emptyBody: ReactNode;
  errorMessage: string;
  children: (data: T) => ReactNode;
}

/**
 * One panel: a titled frame whose body is the read's state. The title stays
 * put through every state, so the loading page reads as the same dashboard
 * rather than a different one, and an operator who has seen the panel once
 * knows where to look when it fails.
 */
export function ReadPanel<T>({
  testId,
  title,
  takeaway,
  controls,
  read,
  isEmpty,
  emptyTitle,
  emptyBody,
  errorMessage,
  children,
}: ReadPanelProps<T>) {
  const empty =
    read.status === "ready" && read.data !== null && isEmpty(read.data);
  const failed = read.status === "error";

  return (
    <section
      data-testid={testId}
      data-status={read.status}
      className={cn(
        "rounded-lg border border-hairline bg-surface p-4",
        failed && "border-danger-border",
      )}
    >
      <h2
        className="text-sm font-semibold text-txt"
        data-testid={`${testId}-title`}
      >
        {title}
      </h2>

      {controls && (
        <div className="mt-3" data-testid={`${testId}-controls`}>
          {controls}
        </div>
      )}

      {read.status === "loading" && (
        <div className="mt-3" data-testid={`${testId}-loading`}>
          <Skeleton className="aspect-video w-full" />
        </div>
      )}

      {failed && (
        <div
          role="alert"
          data-testid={`${testId}-error`}
          className="mt-3 rounded-md border border-danger-border bg-danger-soft px-3 py-2"
        >
          <p className="text-sm text-danger">{errorMessage}</p>
          {/* Per error-handling-observability §1 an operational failure (no
              trace id) is the one that needs support correlation, so its copy
              says so rather than leaving the operator with nothing to quote. */}
          {read.errorTraceId ? (
            <p
              className="mt-0.5 font-mono text-xs text-txt-muted"
              data-testid={`${testId}-error-trace-id`}
            >
              Trace: {read.errorTraceId}
            </p>
          ) : (
            <p
              className="mt-0.5 text-xs text-txt-muted"
              data-testid={`${testId}-error-no-trace`}
            >
              No trace id: the request did not reach the API.
            </p>
          )}
          {/* min-h-11 keeps the target at the 44px the blueprint's touch-target
              rule asks for; a text-sized button is under half that. */}
          <button
            type="button"
            onClick={read.reload}
            data-testid={`${testId}-retry`}
            className="mt-2 inline-flex min-h-11 items-center rounded-md border border-danger-border px-3 text-xs font-medium text-danger hover:bg-danger-soft/60"
          >
            Retry
          </button>
        </div>
      )}

      {read.status === "ready" && read.data !== null && !empty && (
        <>
          {takeaway && (
            <p
              className="mt-0.5 text-xs text-txt-muted"
              data-testid={`${testId}-takeaway`}
            >
              {takeaway}
            </p>
          )}
          <div className="mt-3">{children(read.data)}</div>
        </>
      )}

      {empty && (
        <div className="mt-3">
          <EmptyState title={emptyTitle} body={emptyBody} />
        </div>
      )}
    </section>
  );
}
