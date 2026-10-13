// #710 C3: the operator deep-links panel. Pure component tests over fake
// PanelRead values, covering the two states the ticket calls out - present
// links render outbound, and an absent vendor renders NO link rather than a
// broken one - plus the all-absent empty state, loading and error.

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Deeplinks } from "@/lib/operator/observability";
import { panelRead } from "@/test/panelRead";

import { DeeplinksPanel } from "./DeeplinksPanel";

const GRAFANA = "https://acme.grafana.net";
const SENTRY = "https://o123.sentry.io/issues/?project=456";
const LANGFUSE = "https://cloud.langfuse.com/project/pk-lf-1";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("DeeplinksPanel", () => {
  it("renders one outbound link per configured vendor", () => {
    render(
      <DeeplinksPanel
        read={panelRead<Deeplinks>({
          data: { grafana: GRAFANA, sentry: SENTRY, langfuse: LANGFUSE },
        })}
      />,
    );

    const grafana = screen.getByTestId("observability-deeplink-grafana");
    expect(grafana.getAttribute("href")).toBe(GRAFANA);
    expect(grafana.getAttribute("target")).toBe("_blank");
    expect(grafana.getAttribute("rel")).toContain("noopener");
    expect(grafana.getAttribute("rel")).toContain("noreferrer");

    expect(
      screen.getByTestId("observability-deeplink-sentry").getAttribute("href"),
    ).toBe(SENTRY);
    expect(
      screen
        .getByTestId("observability-deeplink-langfuse")
        .getAttribute("href"),
    ).toBe(LANGFUSE);
  });

  it("renders no link for an absent vendor rather than a broken one", () => {
    render(
      <DeeplinksPanel
        read={panelRead<Deeplinks>({
          data: { grafana: GRAFANA, sentry: null, langfuse: null },
        })}
      />,
    );

    expect(screen.getByTestId("observability-deeplink-grafana")).toBeTruthy();
    expect(screen.queryByTestId("observability-deeplink-sentry")).toBeNull();
    expect(screen.queryByTestId("observability-deeplink-langfuse")).toBeNull();
    // The panel is not empty just because two of three vendors are off.
    expect(screen.queryByTestId("empty-state-title")).toBeNull();
  });

  it("says no vendor links configured when every vendor is off", () => {
    render(
      <DeeplinksPanel
        read={panelRead<Deeplinks>({
          data: { grafana: null, sentry: null, langfuse: null },
        })}
      />,
    );

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
