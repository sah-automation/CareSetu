// #709 C2b: the operator Quality panel page. Mocks the client at the
// lib/operator/observability seam and covers loading, populated, chart-render,
// empty, error and retry - and the two figures this page must never guess at: a
// rate with no denominator and a provider with no traffic sample.

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

import { fetchQuality, type QualityReport } from "@/lib/operator/observability";
import { useChartDom, drawnChart } from "@/test/chartDom";

import ObservabilityQualityPage from "./page";

vi.mock("@/lib/operator/observability", async (importOriginal) => {
  const mod =
    await importOriginal<typeof import("@/lib/operator/observability")>();
  return { ...mod, fetchQuality: vi.fn() };
});

const mockFetchQuality = vi.mocked(fetchQuality);

/** What the page renders for a rate the rollup has no sample for. */
const UNMEASURED = "\u2014";

const REPORT: QualityReport = {
  days: 30,
  from_date: "2026-09-13",
  to_date: "2026-10-12",
  total_calls: 120,
  success_count: 114,
  failure_count: 4,
  timeout_count: 2,
  low_confidence_count: 3,
  success_rate: 95,
  low_confidence_rate: 2.6,
  providers: [
    {
      provider: "mock",
      sample_count: 100,
      success_rate: 96,
      breaker_state: "closed",
    },
    {
      provider: "openai_compatible",
      sample_count: 20,
      success_rate: 85,
      breaker_state: "closed",
    },
  ],
};

function resolveWith(data: QualityReport | null) {
  mockFetchQuality.mockImplementation(() =>
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

describe("ObservabilityQualityPage", () => {
  it("shows a loading skeleton while the read is in flight", () => {
    mockFetchQuality.mockImplementation(
      () => new Promise<QualityReport>(() => {}),
    );

    render(<ObservabilityQualityPage />);

    expect(screen.getByTestId("quality-report-loading")).toBeTruthy();
  });

  it("states the success and low-confidence rates over the window", async () => {
    render(<ObservabilityQualityPage />);

    await waitFor(() => {
      expect(screen.getByTestId("quality-success-rate").textContent).toBe(
        "95%",
      );
    });
    expect(screen.getByTestId("quality-low-confidence-rate").textContent).toBe(
      "2.6%",
    );
    expect(screen.getByTestId("quality-rates").textContent).toContain(
      "114 of 120 calls",
    );
    expect(screen.getByTestId("quality-rates").textContent).toContain(
      "3 completions flagged for review",
    );
  });

  it("shows an em dash, never a fabricated zero, for an unmeasured rate", async () => {
    resolveWith({
      ...REPORT,
      total_calls: 0,
      success_count: 0,
      success_rate: null,
      low_confidence_count: 0,
      low_confidence_rate: null,
    });

    render(<ObservabilityQualityPage />);

    await waitFor(() => {
      expect(screen.getByTestId("quality-success-rate").textContent).toBe(
        UNMEASURED,
      );
    });
    expect(screen.getByTestId("quality-low-confidence-rate").textContent).toBe(
      UNMEASURED,
    );
  });

  it("draws a success-rate bar per provider that has traffic", async () => {
    render(<ObservabilityQualityPage />);

    const chart = await drawnChart("quality-success-rate-chart");
    expect(chart.querySelectorAll(".recharts-bar-rectangle").length).toBe(2);
    expect(
      [...chart.querySelectorAll(".recharts-cartesian-axis-tick-value")].map(
        (node) => node.textContent,
      ),
    ).toEqual(expect.arrayContaining(["mock", "openai_compatible"]));
  });

  it("draws no bar for a provider the rollup has no sample for", async () => {
    resolveWith({
      ...REPORT,
      providers: [
        REPORT.providers[0],
        {
          provider: "never_called",
          sample_count: 0,
          success_rate: null,
          breaker_state: "closed",
        },
      ],
    });

    render(<ObservabilityQualityPage />);

    const chart = await drawnChart("quality-success-rate-chart");
    // Two providers on the axis, one bar drawn. A zero-height bar for the
    // unsampled provider would report "fails every call" about a provider
    // nobody has called.
    expect(chart.querySelectorAll(".recharts-bar-rectangle").length).toBe(1);
    expect(
      [...chart.querySelectorAll(".recharts-cartesian-axis-tick-value")].map(
        (node) => node.textContent,
      ),
    ).toEqual(expect.arrayContaining(["never_called"]));
  });

  it("draws the call outcomes as one stacked bar partitioning every call", async () => {
    render(<ObservabilityQualityPage />);

    const chart = await drawnChart("quality-outcome-chart");
    // One bar, three segments. Three INDEPENDENT bars would be a different
    // claim: their lengths are only comparable by accident of a shared axis,
    // whereas a stacked bar's full width is every call made.
    expect(chart.querySelectorAll(".recharts-bar-rectangle").length).toBe(3);
    expect(chart.querySelectorAll(".recharts-layer.recharts-bar").length).toBe(
      3,
    );
    // The single category is named on the axis - recharts squeezes the
    // whitespace out of a tick label, so it reads "Allcalls". The segment
    // names live in the legend, because with one category an axis has nothing
    // else to label.
    expect(
      [...chart.querySelectorAll(".recharts-cartesian-axis-tick-value")].map(
        (node) => node.textContent,
      ),
    ).toEqual(expect.arrayContaining(["Allcalls"]));
    const legend = chart.querySelector(".recharts-legend-wrapper");
    expect(legend?.textContent).toContain("Succeeded");
    expect(legend?.textContent).toContain("Failed");
    expect(legend?.textContent).toContain("Timed out");
  });

  it("says nothing has completed yet instead of charting empty rates", async () => {
    resolveWith({
      ...REPORT,
      total_calls: 0,
      success_count: 0,
      failure_count: 0,
      timeout_count: 0,
      low_confidence_count: 0,
      success_rate: null,
      low_confidence_rate: null,
      providers: [],
    });

    render(<ObservabilityQualityPage />);

    await waitFor(() => {
      expect(screen.getByTestId("empty-state-title").textContent).toBe(
        "No AI completions yet",
      );
    });
  });

  it("explains an unsampled provider in words rather than an empty plot", async () => {
    resolveWith({ ...REPORT, providers: [] });

    render(<ObservabilityQualityPage />);

    await waitFor(() => {
      expect(screen.getByTestId("quality-no-providers")).toBeTruthy();
    });
    expect(screen.queryByTestId("quality-success-rate-chart")).toBeNull();
    // The outcome mix still has data to show.
    expect(screen.getByTestId("quality-outcome-chart")).toBeTruthy();
  });

  it("shows the failure inline and retries the panel", async () => {
    resolveWith(null);
    render(<ObservabilityQualityPage />);
    await waitFor(() => {
      expect(screen.getByTestId("quality-report-error")).toBeTruthy();
    });
    expect(
      screen.getByText("Could not load the AI quality report."),
    ).toBeTruthy();

    resolveWith(REPORT);
    fireEvent.click(screen.getByTestId("quality-report-retry"));

    await waitFor(() => {
      expect(screen.getByTestId("quality-success-rate").textContent).toBe(
        "95%",
      );
    });
    expect(mockFetchQuality).toHaveBeenCalledTimes(2);
    expect(screen.queryByTestId("quality-report-error")).toBeNull();
  });

  it("renders the panel without the page-level tab strip (#747)", () => {
    render(<ObservabilityQualityPage />);

    expect(screen.getByTestId("page-header")).toBeInTheDocument();
    expect(screen.queryByTestId("observability-panel-tabs")).toBeNull();
    expect(screen.queryByTestId("observability-tab-quality")).toBeNull();
  });
});
