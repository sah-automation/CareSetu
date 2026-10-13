// #709 C2b: the shared Observability panel shell (tabs + read-scoped panel) and
// the load-state hook behind it. These are the pieces every C2b page composes,
// so their states are pinned once here rather than four times over in the pages.

import type { ReactElement } from "react";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api-errors";
import { usePanelRead } from "@/lib/operator/usePanelRead";

import { PanelTabs, ReadPanel } from "./ObservabilityPanelPage";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("PanelTabs", () => {
  it("renders the current panel as text and the rest as links", () => {
    render(<PanelTabs current="usage" />);

    expect(screen.getByTestId("observability-tab-usage")).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByTestId("observability-tab-usage").tagName).toBe("SPAN");
    expect(screen.getByTestId("observability-tab-cost")).toHaveAttribute(
      "href",
      "/operator/observability/cost",
    );
  });

  it("reaches every panel from every panel", () => {
    render(<PanelTabs current="overview" />);

    for (const key of ["overview", "cost", "usage", "quality", "health"]) {
      expect(screen.getByTestId(`observability-tab-${key}`)).toBeTruthy();
    }
  });
});

/** A stand-in page that hands `usePanelRead` a fetcher the test controls. */
function Probe({
  load,
  isEmpty = () => false,
  emptyTitle = "Nothing here",
}: {
  load: () => Promise<string>;
  isEmpty?: (data: string) => boolean;
  emptyTitle?: string;
}) {
  const read = usePanelRead(load);
  return (
    <ReadPanel
      testId="probe"
      title="Probe panel"
      read={read}
      isEmpty={isEmpty}
      emptyTitle={emptyTitle}
      emptyBody="No data for this window."
      errorMessage="Could not load the probe."
      takeaway={`Read: ${read.data ?? "none"}`}
    >
      {(data): ReactElement => <p>rendered {data}</p>}
    </ReadPanel>
  );
}

describe("ReadPanel", () => {
  it("keeps the panel's title in place through every state", async () => {
    render(<Probe load={() => new Promise<string>(() => {})} />);
    expect(screen.getByTestId("probe-title").textContent).toBe("Probe panel");
    expect(screen.getByTestId("probe-loading")).toBeTruthy();

    cleanup();
    render(<Probe load={() => Promise.resolve("ok")} />);
    await waitFor(() => {
      expect(screen.getByTestId("probe").getAttribute("data-status")).toBe(
        "ready",
      );
    });
    expect(screen.getByTestId("probe-title").textContent).toBe("Probe panel");
    expect(screen.queryByTestId("probe-loading")).toBeNull();
  });

  it("renders the loaded data and the takeaway", async () => {
    render(<Probe load={() => Promise.resolve("payload")} />);

    await waitFor(() => {
      expect(screen.getByText("rendered payload")).toBeTruthy();
    });
    expect(screen.getByTestId("probe-takeaway").textContent).toBe(
      "Read: payload",
    );
  });

  it("renders the empty state instead of the children", async () => {
    render(
      <Probe
        load={() => Promise.resolve("nothing")}
        isEmpty={() => true}
        emptyTitle="Nothing recorded"
      />,
    );

    await waitFor(() => {
      expect(screen.getByTestId("empty-state-title").textContent).toBe(
        "Nothing recorded",
      );
    });
    expect(screen.queryByText("rendered nothing")).toBeNull();
    expect(screen.queryByTestId("probe-takeaway")).toBeNull();
  });

  it("reports a failed read inline with the API trace id", async () => {
    render(
      <Probe
        load={() =>
          Promise.reject(
            new ApiError({
              code: "UPSTREAM_UNAVAILABLE",
              message: "boom",
              trace_id: "trace-abc",
              details: {},
            }),
          )
        }
      />,
    );

    await waitFor(() => {
      expect(screen.getByTestId("probe-error")).toBeTruthy();
    });
    expect(screen.getByTestId("probe-error-trace-id").textContent).toContain(
      "trace-abc",
    );
    expect(screen.queryByTestId("probe-loading")).toBeNull();
  });

  it("retries the same read", async () => {
    let attempt = 0;
    render(
      <Probe
        load={() => {
          attempt += 1;
          return attempt === 1
            ? Promise.reject(new Error("network down"))
            : Promise.resolve("second try");
        }}
      />,
    );
    await waitFor(() => {
      expect(screen.getByTestId("probe-error")).toBeTruthy();
    });

    fireEvent.click(screen.getByTestId("probe-retry"));

    await waitFor(() => {
      expect(screen.getByText("rendered second try")).toBeTruthy();
    });
    expect(attempt).toBe(2);
  });

  it("re-reads once on mount, not once per render", async () => {
    const load = vi.fn(() => Promise.resolve("payload"));
    const { rerender } = render(<Probe load={load} />);
    await waitFor(() => {
      expect(screen.getByTestId("probe").getAttribute("data-status")).toBe(
        "ready",
      );
    });

    // Callers pass `load` inline, so it is a fresh closure on every render.
    // Depending on it would re-fire the read forever.
    rerender(<Probe load={() => Promise.resolve("payload")} />);
    rerender(<Probe load={() => Promise.resolve("payload")} />);

    expect(load).toHaveBeenCalledTimes(1);
  });
});
