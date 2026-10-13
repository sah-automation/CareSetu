// #709 C2b: the operator Health panel page. Mocks the client at the
// lib/operator/observability seam and covers loading, populated, chart-render,
// empty, error and retry - plus the panel-independence this page depends on: a
// failed latency read must not blank the dependency state beside it.

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import {
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";

import {
  fetchHealth,
  fetchLatency,
  type LatencyReport,
  type SystemHealth,
} from "@/lib/operator/observability";
import { useChartDom, drawnChart } from "@/test/chartDom";

import ObservabilityHealthPage from "./page";

vi.mock("@/lib/operator/observability", async (importOriginal) => {
  const mod =
    await importOriginal<typeof import("@/lib/operator/observability")>();
  return { ...mod, fetchHealth: vi.fn(), fetchLatency: vi.fn() };
});

const mockFetchHealth = vi.mocked(fetchHealth);
const mockFetchLatency = vi.mocked(fetchLatency);

const LATENCY: LatencyReport = {
  last_rolled_date: "2026-10-12",
  providers: [
    {
      provider: "mock",
      sample_count: 100,
      p50_duration_ms: 900,
      p95_duration_ms: 4200,
      p99_duration_ms: 7800,
      window_start: "2026-09-13",
      window_end: "2026-10-12",
    },
    {
      provider: "openai_compatible",
      sample_count: 20,
      p50_duration_ms: null,
      p95_duration_ms: null,
      p99_duration_ms: null,
      window_start: null,
      window_end: null,
    },
  ],
};

const HEALTH: SystemHealth = {
  dependencies: [
    { name: "database", status: "up", latency_ms: 4, detail: null },
    { name: "redis", status: "up", latency_ms: 2, detail: null },
    {
      name: "redis_replica",
      status: "disabled",
      latency_ms: null,
      detail: null,
    },
  ],
  outbox: [
    {
      table_schema: "audit",
      table: "audit_events",
      pending: 12,
      inflight: 1,
      dead_letter: 0,
      backlog: 12,
    },
  ],
  outbox_backlog: 12,
  dead_letter_rows: 0,
  breakers: [{ provider: "mock", breaker_state: "closed" }],
  open_breakers: 0,
};

function resolveLatencyWith(data: LatencyReport | null) {
  mockFetchLatency.mockImplementation(() =>
    data === null
      ? Promise.reject(new Error("network down"))
      : Promise.resolve(data),
  );
}

function resolveHealthWith(data: SystemHealth | null) {
  mockFetchHealth.mockImplementation(() =>
    data === null
      ? Promise.reject(new Error("network down"))
      : Promise.resolve(data),
  );
}

beforeAll(() => useChartDom());

beforeEach(() => {
  resolveLatencyWith(LATENCY);
  resolveHealthWith(HEALTH);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("ObservabilityHealthPage", () => {
  it("shows a loading skeleton for both panels while the reads are in flight", () => {
    mockFetchLatency.mockImplementation(
      () => new Promise<LatencyReport>(() => {}),
    );
    mockFetchHealth.mockImplementation(
      () => new Promise<SystemHealth>(() => {}),
    );

    render(<ObservabilityHealthPage />);

    expect(screen.getByTestId("health-latency-loading")).toBeTruthy();
    expect(screen.getByTestId("health-system-loading")).toBeTruthy();
  });

  it("states that the percentiles are a snapshot of the last roll", async () => {
    render(<ObservabilityHealthPage />);

    await waitFor(() => {
      expect(screen.getByTestId("health-latency-takeaway").textContent).toBe(
        "Percentiles are a snapshot as of 2026-10-12, not a live measurement.",
      );
    });
  });

  it("says so plainly when the rollup has not run yet", async () => {
    resolveLatencyWith({
      last_rolled_date: null,
      providers: LATENCY.providers,
    });

    render(<ObservabilityHealthPage />);

    await waitFor(() => {
      expect(screen.getByTestId("health-latency-takeaway").textContent).toBe(
        "The rollup has not run yet, so these percentiles are not from a completed window.",
      );
    });
  });

  it("draws a p50/p95/p99 group per sampled provider and none for the unsampled one", async () => {
    render(<ObservabilityHealthPage />);

    const chart = await drawnChart("health-latency-chart");
    // One sampled provider x three percentiles. The provider with null
    // percentiles contributes no bars at all - a zero-height bar would report
    // "instantly fast" about a provider that was never sampled.
    expect(chart.querySelectorAll(".recharts-bar-rectangle").length).toBe(3);
    expect(
      [...chart.querySelectorAll(".recharts-cartesian-axis-tick-value")].map(
        (node) => node.textContent,
      ),
    ).toEqual(expect.arrayContaining(["mock", "openai_compatible"]));
  });

  it("lists each dependency's state, reachability time and queue depths", async () => {
    render(<ObservabilityHealthPage />);

    await waitFor(() => {
      expect(
        screen.getByTestId("health-system").getAttribute("data-status"),
      ).toBe("ready");
    });
    const dependencies = screen.getByTestId("health-dependencies");
    expect(dependencies.textContent).toContain("database");
    expect(dependencies.textContent).toContain("redis_replica");
    expect(dependencies.textContent).toContain("disabled");
    // Latency renders as a duration, not as raw milliseconds.
    expect(dependencies.textContent).toContain("4ms");

    const outbox = screen.getByTestId("health-outbox");
    expect(outbox.textContent).toContain("audit.audit_events");
    expect(outbox.textContent).toContain("12");

    const breakers = screen.getByTestId("health-breakers");
    expect(breakers.textContent).toContain("mock");
    expect(breakers.textContent).toContain("closed");
  });

  it("says nothing to report rather than rendering empty sections", async () => {
    resolveHealthWith({
      dependencies: [],
      outbox: [],
      outbox_backlog: 0,
      dead_letter_rows: 0,
      breakers: [],
      open_breakers: 0,
    });

    render(<ObservabilityHealthPage />);

    await waitFor(() => {
      expect(screen.getByTestId("empty-state-title").textContent).toBe(
        "Nothing to report",
      );
    });
    // The latency panel beside it is untouched.
    expect(screen.getByTestId("health-latency-chart")).toBeTruthy();
  });

  it("says no latency sample has been rolled yet", async () => {
    resolveLatencyWith({ last_rolled_date: null, providers: [] });

    render(<ObservabilityHealthPage />);

    await waitFor(() => {
      expect(screen.getByTestId("empty-state-title").textContent).toBe(
        "No latency samples yet",
      );
    });
    expect(screen.queryByTestId("health-latency-chart")).toBeNull();
  });

  it("keeps the dependency panel working when the latency read fails", async () => {
    resolveLatencyWith(null);
    render(<ObservabilityHealthPage />);

    await waitFor(() => {
      expect(screen.getByTestId("health-latency-error")).toBeTruthy();
    });
    expect(
      screen.getByText("Could not load the AI latency percentiles."),
    ).toBeTruthy();
    expect(screen.queryByTestId("health-system-error")).toBeNull();
    expect(screen.getByTestId("health-dependencies")).toBeTruthy();
  });

  it("retries only the panel that failed", async () => {
    resolveLatencyWith(null);
    render(<ObservabilityHealthPage />);
    await waitFor(() => {
      expect(screen.getByTestId("health-latency-error")).toBeTruthy();
    });

    resolveLatencyWith(LATENCY);
    fireEvent.click(screen.getByTestId("health-latency-retry"));

    await waitFor(() => {
      expect(screen.getByTestId("health-latency-chart")).toBeTruthy();
    });
    expect(mockFetchLatency).toHaveBeenCalledTimes(2);
    expect(mockFetchHealth).toHaveBeenCalledTimes(1);
  });

  it("marks the health tab as the current panel", () => {
    render(<ObservabilityHealthPage />);

    expect(screen.getByTestId("observability-tab-health")).toHaveAttribute(
      "aria-current",
      "page",
    );
  });
});
