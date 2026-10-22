// #709 C2b: the operator Cost panel page. Mocks the client at the
// lib/operator/observability seam and covers the states the panels owe an
// operator: loading, populated, chart-render, empty, error and retry - and the
// one thing this page exists to get right, that a failed trend read leaves the
// budget figure alone.

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
  fetchCost,
  fetchCostTrend,
  type CostSummary,
  type CostTrend,
} from "@/lib/operator/observability";
import { useChartDom, drawnChart } from "@/test/chartDom";

import ObservabilityCostPage from "./page";

vi.mock("@/lib/operator/observability", async (importOriginal) => {
  const mod =
    await importOriginal<typeof import("@/lib/operator/observability")>();
  return { ...mod, fetchCost: vi.fn(), fetchCostTrend: vi.fn() };
});

const mockFetchCost = vi.mocked(fetchCost);
const mockFetchCostTrend = vi.mocked(fetchCostTrend);

const BUDGETED: CostSummary = {
  period_start: "2026-10-01",
  period_end: "2026-10-31",
  total_spend_paise: 125000,
  total_limit_paise: 500000,
  remaining_paise: 375000,
  utilization_pct: 25,
  exhausted: false,
  budgets: [
    {
      provider: "mock",
      model: "s1",
      monthly_limit_paise: 300000,
      alert_threshold_pct: 80,
      current_spend_paise: 100000,
      billing_period_start: "2026-10-01",
      billing_period_end: "2026-10-31",
      remaining_paise: 200000,
      utilization_pct: 33.3,
      exhausted: false,
    },
    {
      provider: "openai_compatible",
      model: "gpt-4o-mini",
      monthly_limit_paise: 200000,
      alert_threshold_pct: 80,
      current_spend_paise: 25000,
      billing_period_start: "2026-10-01",
      billing_period_end: "2026-10-31",
      remaining_paise: 175000,
      utilization_pct: 12.5,
      exhausted: false,
    },
  ],
};

const TREND: CostTrend = {
  days: 30,
  from_date: "2026-09-13",
  to_date: "2026-10-12",
  points: [
    { usage_date: "2026-10-01", calls: 4, cost_paise: 10000 },
    { usage_date: "2026-10-02", calls: 9, cost_paise: 25000 },
    { usage_date: "2026-10-03", calls: 2, cost_paise: 5000 },
  ],
};

function resolveCostWith(data: CostSummary | null) {
  mockFetchCost.mockImplementation(() =>
    data === null
      ? Promise.reject(new Error("network down"))
      : Promise.resolve(data),
  );
}

function resolveTrendWith(data: CostTrend | null) {
  mockFetchCostTrend.mockImplementation(() =>
    data === null
      ? Promise.reject(new Error("network down"))
      : Promise.resolve(data),
  );
}

beforeAll(() => useChartDom());

beforeEach(() => {
  resolveCostWith(BUDGETED);
  resolveTrendWith(TREND);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("ObservabilityCostPage", () => {
  it("shows a loading skeleton for both panels while the reads are in flight", () => {
    mockFetchCost.mockImplementation(() => new Promise<CostSummary>(() => {}));
    mockFetchCostTrend.mockImplementation(
      () => new Promise<CostTrend>(() => {}),
    );

    render(<ObservabilityCostPage />);

    expect(screen.getByTestId("cost-budget-loading")).toBeTruthy();
    expect(screen.getByTestId("cost-trend-loading")).toBeTruthy();
  });

  it("states the period spend in rupees against the cap", async () => {
    render(<ObservabilityCostPage />);

    await waitFor(() => {
      expect(screen.getByTestId("cost-budget-takeaway").textContent).toBe(
        "₹1,250 of ₹5,000 · 25% used · ₹3,750 remaining",
      );
    });
  });

  it("says the budget is exhausted rather than reporting negative headroom", async () => {
    resolveCostWith({
      ...BUDGETED,
      remaining_paise: -50000,
      utilization_pct: 110,
      exhausted: true,
    });

    render(<ObservabilityCostPage />);

    await waitFor(() => {
      expect(screen.getByTestId("cost-budget-takeaway").textContent).toContain(
        "budget exhausted",
      );
    });
  });

  it("draws the budget chart, one cap/spent bar pair per budget scope", async () => {
    render(<ObservabilityCostPage />);

    const chart = await drawnChart("cost-budget-chart");
    // Two scopes x two bars. A chart that measured 0x0 would draw nothing here.
    expect(chart.querySelectorAll(".recharts-bar-rectangle").length).toBe(4);
    // Every scope is named on the axis. recharts squeezes whitespace out of a
    // tick label to fit, so the axis reads "mock·s1"; the panel's own takeaway
    // and the scopes' full names are asserted where they are spelled out.
    expect(
      [...chart.querySelectorAll(".recharts-cartesian-axis-tick-value")].map(
        (node) => node.textContent,
      ),
    ).toEqual(
      expect.arrayContaining(["mock·s1", "openai_compatible·gpt-4o-mini"]),
    );
  });

  it("draws the daily trend chart with one point per recorded day", async () => {
    render(<ObservabilityCostPage />);

    const chart = await drawnChart("cost-trend-chart", ".recharts-area");
    // recharts squeezes the whitespace out of a tick label to fit, so the axis
    // reads "1Oct" for the day 2026-10-01.
    expect(
      [...chart.querySelectorAll(".recharts-cartesian-axis-tick-value")].map(
        (node) => node.textContent,
      ),
    ).toEqual(expect.arrayContaining(["1Oct", "2Oct", "3Oct"]));
  });

  it("states how many billable days the trend covers", async () => {
    render(<ObservabilityCostPage />);

    await waitFor(() => {
      expect(screen.getByTestId("cost-trend-takeaway").textContent).toBe(
        "3 billable days over the last 30 days.",
      );
    });
  });

  it("says nothing is budgeted, rather than drawing an empty axis", async () => {
    resolveCostWith({ ...BUDGETED, budgets: [] });

    render(<ObservabilityCostPage />);

    await waitFor(() => {
      expect(screen.getByTestId("empty-state-title").textContent).toBe(
        "No AI budget configured",
      );
    });
    expect(screen.getByTestId("cost-budget").querySelector("svg")).toBeNull();
  });

  it("says no spend has been recorded, and still plots the budget", async () => {
    resolveTrendWith({ ...TREND, points: [] });

    render(<ObservabilityCostPage />);

    await waitFor(() => {
      expect(screen.getByTestId("empty-state-title").textContent).toBe(
        "No spend recorded yet",
      );
    });
    // The other panel is unaffected - it read its own route.
    expect(screen.getByTestId("cost-budget-takeaway")).toBeTruthy();
  });

  it("shows the failure inline, with the API trace id", async () => {
    resolveCostWith(null);

    render(<ObservabilityCostPage />);

    await waitFor(() => {
      expect(screen.getByTestId("cost-budget-error")).toBeTruthy();
    });
    expect(screen.getByText("Could not load the AI budget.")).toBeTruthy();
    // The trend panel keeps working; one route's failure is not the page's.
    expect(screen.queryByTestId("cost-trend-error")).toBeNull();
    expect(screen.getByTestId("cost-trend-takeaway")).toBeTruthy();
  });

  it("retries only the panel that failed", async () => {
    resolveCostWith(null);
    render(<ObservabilityCostPage />);
    await waitFor(() => {
      expect(screen.getByTestId("cost-budget-error")).toBeTruthy();
    });

    resolveCostWith(BUDGETED);
    fireEvent.click(screen.getByTestId("cost-budget-retry"));

    const chart = await drawnChart("cost-budget-chart");
    expect(mockFetchCost).toHaveBeenCalledTimes(2);
    // The trend read was not re-run: retry re-reads the panel, not the page.
    expect(mockFetchCostTrend).toHaveBeenCalledTimes(1);
    expect(chart.querySelectorAll(".recharts-bar-rectangle").length).toBe(4);
  });

  it("renders the panel without the page-level tab strip (#747)", () => {
    render(<ObservabilityCostPage />);

    // The strip is replaced by the sub-menu, which the nav configuration
    // renders; the page keeps only its header and its panels.
    expect(screen.getByTestId("page-header")).toBeInTheDocument();
    expect(screen.queryByTestId("observability-panel-tabs")).toBeNull();
    expect(screen.queryByTestId("observability-tab-cost")).toBeNull();
  });
});
