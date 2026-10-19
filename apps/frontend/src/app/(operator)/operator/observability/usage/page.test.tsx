// #709 C2b: the operator Usage panel page. Mocks the client at the
// lib/operator/observability seam and covers loading, populated, chart-render,
// empty, error and retry.

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

import { fetchUsage, type UsageReport } from "@/lib/operator/observability";
import { useChartDom, drawnChart } from "@/test/chartDom";

import ObservabilityUsagePage from "./page";

vi.mock("@/lib/operator/observability", async (importOriginal) => {
  const mod =
    await importOriginal<typeof import("@/lib/operator/observability")>();
  return { ...mod, fetchUsage: vi.fn() };
});

const mockFetchUsage = vi.mocked(fetchUsage);

const REPORT: UsageReport = {
  days: 30,
  from_date: "2026-09-13",
  to_date: "2026-10-12",
  total_calls: 49,
  total_input_tokens: 120000,
  total_output_tokens: 45000,
  total_cost_paise: 125000,
  rows: [
    {
      provider: "mock",
      model: "s1",
      task_type: "transcribe",
      calls: 40,
      success_count: 38,
      failure_count: 1,
      timeout_count: 1,
      input_tokens: 90000,
      output_tokens: 30000,
      cost_paise: 100000,
    },
    {
      provider: "openai_compatible",
      model: "gpt-4o-mini",
      task_type: "structure",
      calls: 9,
      success_count: 9,
      failure_count: 0,
      timeout_count: 0,
      input_tokens: 30000,
      output_tokens: 15000,
      cost_paise: 25000,
    },
  ],
};

function resolveWith(data: UsageReport | null) {
  mockFetchUsage.mockImplementation(() =>
    data === null
      ? Promise.reject(new Error("network down"))
      : Promise.resolve(data),
  );
}

beforeAll(() => useChartDom());

beforeEach(() => resolveWith(REPORT));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("ObservabilityUsagePage", () => {
  it("shows a loading skeleton while the read is in flight", () => {
    mockFetchUsage.mockImplementation(() => new Promise<UsageReport>(() => {}));

    render(<ObservabilityUsagePage />);

    expect(screen.getByTestId("usage-breakdown-loading")).toBeTruthy();
  });

  it("states the window totals in the panel's takeaway", async () => {
    render(<ObservabilityUsagePage />);

    await waitFor(() => {
      expect(screen.getByTestId("usage-breakdown-takeaway").textContent).toBe(
        // en-IN groups in lakhs: 165,000 tokens reads as 1,65,000.
        "49 calls · 1,65,000 tokens · ₹1,250 · last 30 days",
      );
    });
  });

  it("draws one bar per usage scope, busiest first", async () => {
    render(<ObservabilityUsagePage />);

    const chart = await drawnChart("usage-calls-chart");
    // Two scopes. Nothing at all would mean the container never measured,
    // which is the failure this assertion exists to catch.
    expect(chart.querySelectorAll(".recharts-bar-rectangle").length).toBe(2);
    // Both scopes are named on the axis - a bar with no label cannot be traced
    // back to the provider/model/task it belongs to.
    expect(
      [...chart.querySelectorAll(".recharts-cartesian-axis-tick-value")].map(
        (node) => node.textContent,
      ),
    ).toEqual(
      expect.arrayContaining([
        "mock·s1·transcribe",
        "openai_compatible·gpt-4o-mini·structure",
      ]),
    );
  });

  it("stacks input against output tokens per scope", async () => {
    render(<ObservabilityUsagePage />);

    const chart = await drawnChart("usage-tokens-chart");
    // Two scopes x two stacked token segments.
    expect(chart.querySelectorAll(".recharts-bar-rectangle").length).toBe(4);
  });

  it("lists the exact scope names and spend in a table beside the charts", async () => {
    render(<ObservabilityUsagePage />);

    await waitFor(() => {
      expect(screen.getByTestId("usage-scope-costs")).toBeTruthy();
    });
    const table = screen.getByTestId("usage-scope-costs");
    expect(table.textContent).toContain("mock · s1 · transcribe");
    expect(table.textContent).toContain(
      "openai_compatible · gpt-4o-mini · structure",
    );
    expect(table.textContent).toContain("₹1,000");
    expect(table.textContent).toContain("₹250");
  });

  it("says no AI calls were recorded rather than charting an empty axis", async () => {
    resolveWith({
      ...REPORT,
      total_calls: 0,
      total_input_tokens: 0,
      total_output_tokens: 0,
      total_cost_paise: 0,
      rows: [],
    });

    render(<ObservabilityUsagePage />);

    await waitFor(() => {
      expect(screen.getByTestId("empty-state-title").textContent).toBe(
        "No AI calls yet",
      );
    });
  });

  it("shows the failure inline with a retry that re-reads the panel", async () => {
    resolveWith(null);
    render(<ObservabilityUsagePage />);
    await waitFor(() => {
      expect(screen.getByTestId("usage-breakdown-error")).toBeTruthy();
    });
    expect(
      screen.getByText("Could not load the AI usage breakdown."),
    ).toBeTruthy();

    resolveWith(REPORT);
    fireEvent.click(screen.getByTestId("usage-breakdown-retry"));

    await waitFor(() => {
      expect(screen.getByTestId("usage-scope-costs")).toBeTruthy();
    });
    expect(mockFetchUsage).toHaveBeenCalledTimes(2);
    expect(screen.queryByTestId("usage-breakdown-error")).toBeNull();
  });

  it("renders the panel without the page-level tab strip (#747)", () => {
    render(<ObservabilityUsagePage />);

    expect(screen.getByTestId("page-header")).toBeInTheDocument();
    expect(screen.queryByTestId("observability-panel-tabs")).toBeNull();
    expect(screen.queryByTestId("observability-tab-usage")).toBeNull();
  });
});
