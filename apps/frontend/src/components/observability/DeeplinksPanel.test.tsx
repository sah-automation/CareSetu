// #710 C3, widened by #736: the operator deep-links panel. Pure component tests
// over fake PanelRead values, covering the states the tickets call out - every
// link of a link SET renders outbound with its filter, an absent vendor renders NO
// link rather than a broken one, a vendor with nothing to filter on drops just that
// link - plus the all-absent empty state, loading and error.

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Deeplinks } from "@/lib/operator/observability";
import { panelRead } from "@/test/panelRead";

import { DeeplinksPanel } from "./DeeplinksPanel";

const TRACE = "c7f2a1b0d3e4f5061728394a5b6c7d8e";

const FULL: Deeplinks = {
  trace_id: TRACE,
  grafana: {
    dashboard_uid: "caresetu-observability",
    dashboard_url:
      "https://acme.grafana.net/d/caresetu-observability/caresetu-observability?from=now-6h&to=now",
    explore_url: `https://acme.grafana.net/explore?left=%7B%22traceId%22%3A%22${TRACE}%22%7D`,
  },
  sentry: {
    project_id: "456",
    issues_url:
      "https://o123.sentry.io/issues/?project=456&query=service%3A%22caresetu-api%22",
    trace_url: `https://o123.sentry.io/issues/?project=456&query=trace_id%3A%22${TRACE}%22`,
  },
  langfuse: {
    traces_url:
      "https://cloud.langfuse.com/project/pk-lf-1/traces?model=gpt-4o",
    trace_url: `https://cloud.langfuse.com/project/pk-lf-1/trace/${TRACE}`,
    actor_url: "https://cloud.langfuse.com/project/pk-lf-1/users?userId=abc",
    session_url:
      "https://cloud.langfuse.com/project/pk-lf-1/sessions?sessionId=def",
  },
};

function renderPanel(data: Deeplinks) {
  render(<DeeplinksPanel read={panelRead<Deeplinks>({ data })} />);
}

function hrefOf(testId: string): string | null {
  return screen.getByTestId(testId).getAttribute("href");
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("DeeplinksPanel", () => {
  it("renders every link of every vendor's set, outbound", () => {
    renderPanel(FULL);

    const grafana = screen.getByTestId(
      "observability-deeplink-grafana.dashboard_url",
    );
    expect(grafana.getAttribute("target")).toBe("_blank");
    expect(grafana.getAttribute("rel")).toContain("noopener");
    expect(grafana.getAttribute("rel")).toContain("noreferrer");

    expect(hrefOf("observability-deeplink-grafana.dashboard_url")).toBe(
      FULL.grafana!.dashboard_url,
    );
    expect(hrefOf("observability-deeplink-grafana.explore_url")).toBe(
      FULL.grafana!.explore_url,
    );
    expect(hrefOf("observability-deeplink-sentry.issues_url")).toBe(
      FULL.sentry!.issues_url,
    );
    expect(hrefOf("observability-deeplink-sentry.trace_url")).toBe(
      FULL.sentry!.trace_url,
    );
    expect(hrefOf("observability-deeplink-langfuse.traces_url")).toBe(
      FULL.langfuse!.traces_url,
    );
    expect(hrefOf("observability-deeplink-langfuse.actor_url")).toBe(
      FULL.langfuse!.actor_url,
    );
    expect(hrefOf("observability-deeplink-langfuse.session_url")).toBe(
      FULL.langfuse!.session_url,
    );
  });

  it("carries the one trace identifier into every link that names a trace", () => {
    renderPanel(FULL);

    // The join key has to be the platform's own, in all three tools, or the links
    // open three different (and empty) places.
    for (const key of [
      "grafana.explore_url",
      "sentry.trace_url",
      "langfuse.trace_url",
    ]) {
      expect(hrefOf(`observability-deeplink-${key}`)).toContain(TRACE);
    }
  });

  it("renders no link for a vendor absent from the response", () => {
    // Absent means the key was never sent, not `null` - decision 44.
    renderPanel({
      grafana: FULL.grafana,
    });

    expect(
      screen.getByTestId("observability-deeplink-grafana.dashboard_url"),
    ).toBeTruthy();
    expect(
      screen.queryByTestId("observability-deeplink-sentry.issues_url"),
    ).toBeNull();
    expect(
      screen.queryByTestId("observability-deeplink-langfuse.traces_url"),
    ).toBeNull();
    // The panel is not empty just because two of three vendors are off.
    expect(screen.queryByTestId("empty-state-title")).toBeNull();
  });

  it("drops only the links a vendor has no context for", () => {
    renderPanel({
      grafana: {
        dashboard_uid: "caresetu-observability",
        dashboard_url: "https://acme.grafana.net/d/caresetu-observability",
      },
      langfuse: {
        traces_url:
          "https://cloud.langfuse.com/project/pk-lf-1/traces?model=gpt-4o",
      },
    });

    // No trace in this panel's context, so no Explore pane and no trace views.
    expect(hrefOf("observability-deeplink-grafana.dashboard_url")).toBeTruthy();
    expect(
      screen.queryByTestId("observability-deeplink-grafana.explore_url"),
    ).toBeNull();
    expect(hrefOf("observability-deeplink-langfuse.traces_url")).toBeTruthy();
    expect(
      screen.queryByTestId("observability-deeplink-langfuse.trace_url"),
    ).toBeNull();
    expect(
      screen.queryByTestId("observability-deeplink-langfuse.actor_url"),
    ).toBeNull();
    expect(
      screen.queryByTestId("observability-deeplink-langfuse.session_url"),
    ).toBeNull();
  });

  it("says no vendor links configured when every vendor is off", () => {
    renderPanel({});

    expect(screen.getByTestId("empty-state-title").textContent).toBe(
      "No vendor links configured",
    );
    expect(screen.queryByTestId("observability-deeplinks-list")).toBeNull();
  });

  it("shows a loading skeleton while the read is in flight", () => {
    render(<DeeplinksPanel read={panelRead<Deeplinks>({ data: null })} />);

    expect(screen.getByTestId("observability-deeplinks-loading")).toBeTruthy();
  });

  it("shows the inline error with the trace id and retries", () => {
    const reload = vi.fn();
    render(
      <DeeplinksPanel
        read={panelRead<Deeplinks>({
          data: null,
          status: "error",
          errorTraceId: "trace-456",
          reload,
        })}
      />,
    );

    expect(screen.getByTestId("observability-deeplinks-error")).toBeTruthy();
    expect(screen.getByText("Could not load the vendor links.")).toBeTruthy();

    fireEvent.click(screen.getByTestId("observability-deeplinks-retry"));
    expect(reload).toHaveBeenCalledTimes(1);
  });
});
