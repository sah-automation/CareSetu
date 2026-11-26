// #710 C3: the inline operator alert feed. Pure component tests over fake
// PanelRead values (the overview page owns the fetch), covering the states the
// ticket calls out: populated rows with severity styling, empty, loading and
// the inline error + retry.

import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AlertEntry, AlertPage } from "@/lib/operator/observability";
import { panelRead } from "@/test/panelRead";

import { AlertsFeed } from "./AlertsFeed";

const CRITICAL: AlertEntry = {
  id: "11111111-1111-1111-1111-111111111111",
  severity: "critical",
  kind: "audit_tamper",
  title: "Audit tamper attempt blocked",
  payload: { source: "audit" },
  status: "open",
  created_at: "2026-10-12T10:00:00Z",
  acked_by: null,
  acked_at: null,
};

const WARNING: AlertEntry = {
  id: "22222222-2222-2222-2222-222222222222",
  severity: "warning",
  kind: "ai_budget",
  title: "AI budget over threshold",
  payload: { scope: "bill" },
  status: "open",
  created_at: "2026-10-12T09:00:00Z",
  acked_by: null,
  acked_at: null,
};

function page(alerts: AlertEntry[], total = alerts.length): AlertPage {
  return { alerts, total_count: total };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("AlertsFeed", () => {
  it("renders a row per alert with severity, kind and title", () => {
    render(
      <AlertsFeed read={panelRead({ data: page([CRITICAL, WARNING]) })} />,
    );

    const list = screen.getByTestId("observability-alerts-list");
    expect(within(list).getByText("Audit tamper attempt blocked")).toBeTruthy();
    expect(within(list).getByText("AI budget over threshold")).toBeTruthy();
    // The machine-readable category reads as-is, not renamed.
    expect(within(list).getByText("audit_tamper")).toBeTruthy();
    expect(within(list).getByText("ai_budget")).toBeTruthy();
    expect(
      screen.getByTestId("observability-alerts-takeaway").textContent,
    ).toBe("2 alerts");
  });

  it("says how many of the total are shown when the page is capped", () => {
    render(<AlertsFeed read={panelRead({ data: page([CRITICAL], 26) })} />);

    expect(
      screen.getByTestId("observability-alerts-takeaway").textContent,
    ).toBe("Showing the latest 1 of 26 alerts");
  });

  it("styles each severity with its own tone", () => {
    render(
      <AlertsFeed read={panelRead({ data: page([CRITICAL, WARNING]) })} />,
    );

    const critical = screen.getByTestId(
      `observability-alert-${CRITICAL.id}-severity`,
    );
    expect(critical.className).toContain("bg-danger-soft");
    expect(critical.textContent).toBe("critical");

    const warning = screen.getByTestId(
      `observability-alert-${WARNING.id}-severity`,
    );
    expect(warning.className).toContain("bg-warn-soft");
  });

  it("falls back to a neutral tone for an unknown severity", () => {
    render(
      <AlertsFeed
        read={panelRead({
          data: page([{ ...WARNING, severity: "someday" }]),
        })}
      />,
    );

    const badge = screen.getByTestId(
      `observability-alert-${WARNING.id}-severity`,
    );
    expect(badge.className).toContain("bg-hairline-soft");
    expect(badge.textContent).toBe("someday");
  });

  it("says there are no alerts rather than drawing an empty list", () => {
    render(<AlertsFeed read={panelRead({ data: page([]) })} />);

    expect(screen.getByTestId("empty-state-title").textContent).toBe(
      "No alerts",
    );
    expect(screen.queryByTestId("observability-alerts-list")).toBeNull();
  });

  it("shows a loading skeleton while the read is in flight", () => {
    render(<AlertsFeed read={panelRead<AlertPage>({ data: null })} />);

    expect(screen.getByTestId("observability-alerts-loading")).toBeTruthy();
  });

  it("shows the inline error with the trace id and retries", () => {
    const reload = vi.fn();
    render(
      <AlertsFeed
        read={panelRead<AlertPage>({
          data: null,
          status: "error",
          errorTraceId: "trace-123",
          reload,
        })}
      />,
    );

    expect(screen.getByTestId("observability-alerts-error")).toBeTruthy();
    expect(screen.getByText("Could not load the alert feed.")).toBeTruthy();
    expect(
      screen.getByTestId("observability-alerts-error-trace-id").textContent,
    ).toContain("trace-123");

    fireEvent.click(screen.getByTestId("observability-alerts-retry"));
    expect(reload).toHaveBeenCalledTimes(1);
  });
});
