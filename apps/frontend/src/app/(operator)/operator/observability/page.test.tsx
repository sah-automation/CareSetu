// #708 C2a: the operator Observability overview page. Mocks the client at the
// lib/operator/observability seam (per the brief) and covers the five states the
// page owes an operator: loading, populated, empty (nothing has ever rolled),
// error, and retry out of an error.

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  fetchAlerts,
  fetchDeeplinks,
  fetchOverview,
  type AlertPage,
  type Deeplinks,
  type Overview,
} from "@/lib/operator/observability";

import ObservabilityOverviewPage from "./page";

vi.mock("@/lib/operator/observability", async (importOriginal) => {
  const mod =
    await importOriginal<typeof import("@/lib/operator/observability")>();
  return {
    ...mod,
    fetchOverview: vi.fn(),
    fetchAlerts: vi.fn(),
    fetchDeeplinks: vi.fn(),
  };
});

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  usePathname: () => "/operator/observability",
}));

vi.mock("@/lib/auth/AuthContext", () => ({
  useAuth: () => ({
    user: { id: 1, phone: "+911234567890", roles: ["operator"] },
    selectedRole: "operator",
    switchRole: vi.fn(),
    logout: vi.fn(),
    isAuthenticated: true,
    isLoading: false,
  }),
}));

const mockFetchOverview = vi.mocked(fetchOverview);
const mockFetchAlerts = vi.mocked(fetchAlerts);
const mockFetchDeeplinks = vi.mocked(fetchDeeplinks);

/** What the page renders for a rate the rollup has no sample for. */
const UNMEASURED = "\u2014";

const ROLLED_OVERVIEW: Overview = {
  days: 30,
  from_date: "2026-09-13",
  to_date: "2026-10-12",
  total_calls: 120,
  success_count: 114,
  success_rate: 95,
  low_confidence_count: 3,
  low_confidence_rate: 2.6,
  p95_duration_ms: 4200,
  spend_paise: 125000,
  budget_paise: 500000,
  budget_utilization_pct: 25,
  budget_exhausted: false,
  open_alerts: 2,
  critical_open_alerts: 1,
  open_breakers: 0,
  business_counts: [{ metric_key: "case_closed", count: 7 }],
  last_rolled_date: "2026-10-12",
};

/** Nothing has ever rolled: no date, no calls, every rate unmeasured. */
const NEVER_ROLLED: Overview = {
  ...ROLLED_OVERVIEW,
  total_calls: 0,
  success_count: 0,
  success_rate: null,
  low_confidence_count: 0,
  low_confidence_rate: null,
  p95_duration_ms: null,
  spend_paise: 0,
  budget_utilization_pct: 0,
  open_alerts: 0,
  critical_open_alerts: 0,
  business_counts: [],
  last_rolled_date: null,
};

function resolveWith(data: Overview | null) {
  mockFetchOverview.mockImplementation(() =>
    data === null
      ? Promise.reject(new Error("network down"))
      : (Promise.resolve(data) as Promise<Overview>),
  );
}

/** One alert, so the feed renders populated by default. */
const OPEN_ALERTS: AlertPage = {
  alerts: [
    {
      id: "11111111-1111-1111-1111-111111111111",
      severity: "critical",
      kind: "audit_tamper",
      title: "Audit tamper attempt blocked",
      payload: { source: "audit" },
      status: "open",
      created_at: "2026-10-12T10:00:00Z",
      acked_by: null,
      acked_at: null,
    },
  ],
  total_count: 1,
};

/** All three vendors configured, so the links panel renders populated. */
const DEEPLINKS: Deeplinks = {
  grafana: "https://acme.grafana.net",
  sentry: "https://o123.sentry.io/issues/?project=456",
  langfuse: "https://cloud.langfuse.com/project/pk-lf-1",
};

function resolveAlertsWith(data: AlertPage | null) {
  mockFetchAlerts.mockImplementation(() =>
    data === null
      ? Promise.reject(new Error("network down"))
      : Promise.resolve(data),
  );
}

function resolveDeeplinksWith(data: Deeplinks | null) {
  mockFetchDeeplinks.mockImplementation(() =>
    data === null
      ? Promise.reject(new Error("network down"))
      : Promise.resolve(data),
  );
}

beforeEach(() => {
  resolveWith(ROLLED_OVERVIEW);
  resolveAlertsWith(OPEN_ALERTS);
  resolveDeeplinksWith(DEEPLINKS);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("ObservabilityOverviewPage", () => {
  it("shows pending KPI tiles while the read is in flight", () => {
    mockFetchOverview.mockImplementation(() => new Promise<Overview>(() => {}));

    render(<ObservabilityOverviewPage />);

    expect(screen.getByTestId("observability-kpis")).toBeTruthy();
    expect(screen.getByTestId("kpi-ai-spend-value")).toBeTruthy();
    // A pending tile shows a skeleton bar, never a zero or an em dash.
    expect(screen.getByTestId("kpi-ai-spend-value").textContent).toBe("");
  });

  it("renders every headline KPI from the API", async () => {
    render(<ObservabilityOverviewPage />);

    await waitFor(() => {
      expect(screen.getByTestId("observability-kpis")).toBeTruthy();
    });
    expect(screen.getByTestId("kpi-ai-spend-value").textContent).toBe("₹1,250");
    expect(screen.getByTestId("kpi-budget-used-value").textContent).toBe("25%");
    expect(screen.getByTestId("kpi-ai-calls-value").textContent).toBe("120");
    expect(screen.getByTestId("kpi-success-rate-value").textContent).toBe(
      "95%",
    );
    expect(screen.getByTestId("kpi-low-confidence-value").textContent).toBe(
      "2.6%",
    );
    expect(screen.getByTestId("kpi-p95-latency-value").textContent).toBe(
      "4.2s",
    );
    expect(screen.getByTestId("kpi-open-alerts-value").textContent).toBe("2");
    expect(screen.getByTestId("kpi-open-breakers-value").textContent).toBe("0");
  });

  it("states the window the figures cover and how fresh the roll is", async () => {
    render(<ObservabilityOverviewPage />);

    await waitFor(() => {
      expect(screen.getByTestId("observability-rollup-age").textContent).toBe(
        "Telemetry as of 2026-10-12",
      );
    });
    expect(screen.getByTestId("page-header").textContent).toContain(
      "last 30 days",
    );
  });

  it("shows an em dash, never a fabricated zero, for an unmeasured rate", async () => {
    resolveWith({
      ...ROLLED_OVERVIEW,
      success_rate: null,
      low_confidence_rate: null,
    });

    render(<ObservabilityOverviewPage />);

    await waitFor(() => {
      expect(screen.getByTestId("kpi-success-rate-value").textContent).toBe(
        UNMEASURED,
      );
    });
    expect(screen.getByTestId("kpi-low-confidence-value").textContent).toBe(
      UNMEASURED,
    );
  });

  it("marks an exhausted budget as critical on the spend tiles", async () => {
    resolveWith({
      ...ROLLED_OVERVIEW,
      budget_utilization_pct: 100,
      budget_exhausted: true,
    });

    render(<ObservabilityOverviewPage />);

    await waitFor(() => {
      expect(screen.getByTestId("kpi-budget-used")).toHaveAttribute(
        "data-tone",
        "critical",
      );
    });
    expect(screen.getByTestId("kpi-ai-spend")).toHaveAttribute(
      "data-tone",
      "critical",
    );
    expect(screen.getByText("exhausted")).toBeTruthy();
  });

  it("leaves the non-spend tiles untone when the budget is exhausted", async () => {
    resolveWith({
      ...ROLLED_OVERVIEW,
      budget_utilization_pct: 100,
      budget_exhausted: true,
    });

    render(<ObservabilityOverviewPage />);

    await waitFor(() => {
      expect(screen.getByTestId("kpi-budget-used")).toHaveAttribute(
        "data-tone",
        "critical",
      );
    });
    // A healthy success rate must not be painted red because the bill is over.
    for (const testId of [
      "kpi-ai-calls",
      "kpi-success-rate",
      "kpi-low-confidence",
      "kpi-p95-latency",
      "kpi-open-alerts",
      "kpi-open-breakers",
    ]) {
      expect(screen.getByTestId(testId).hasAttribute("data-tone")).toBe(false);
    }
  });

  it("leaves the spend tiles untone while the budget holds", async () => {
    render(<ObservabilityOverviewPage />);

    await waitFor(() => {
      expect(screen.getByTestId("kpi-budget-used-value")).toBeTruthy();
    });
    expect(
      screen.getByTestId("kpi-budget-used").hasAttribute("data-tone"),
    ).toBe(false);
  });

  it("shows the empty state when no telemetry has ever been rolled", async () => {
    resolveWith(NEVER_ROLLED);

    render(<ObservabilityOverviewPage />);

    await waitFor(() => {
      expect(screen.getByTestId("empty-state")).toBeTruthy();
    });
    expect(screen.getByTestId("empty-state-title").textContent).toBe(
      "No telemetry yet",
    );
    // A page of em dashes is not a dashboard: no KPI row behind the empty state.
    expect(screen.queryByTestId("kpi-ai-spend")).toBeNull();
  });

  it("shows the error banner when the read fails", async () => {
    resolveWith(null);

    render(<ObservabilityOverviewPage />);

    await waitFor(() => {
      expect(screen.getByTestId("error-banner")).toBeTruthy();
    });
    expect(
      screen.getByText("Could not load the observability overview."),
    ).toBeTruthy();
    expect(screen.queryByTestId("observability-kpis")).toBeNull();
  });

  it("retry reloads the overview after a failure", async () => {
    resolveWith(null);
    render(<ObservabilityOverviewPage />);
    await waitFor(() => {
      expect(screen.getByTestId("error-banner")).toBeTruthy();
    });

    resolveWith(ROLLED_OVERVIEW);
    fireEvent.click(screen.getByTestId("error-banner-retry"));

    await waitFor(() => {
      expect(screen.getByTestId("kpi-ai-spend-value").textContent).toBe(
        "₹1,250",
      );
    });
    expect(screen.queryByTestId("error-banner")).toBeNull();
    expect(mockFetchOverview).toHaveBeenCalledTimes(2);
  });

  it("dismisses the error banner without leaving the page broken", async () => {
    resolveWith(null);
    render(<ObservabilityOverviewPage />);
    await waitFor(() => {
      expect(screen.getByTestId("error-banner")).toBeTruthy();
    });

    fireEvent.click(screen.getByTestId("error-banner-dismiss"));

    expect(screen.queryByTestId("error-banner")).toBeNull();
  });

  // #710 C3: the landing page also carries the inline alert feed and the
  // vendor deep-links. Their detailed states live in the component tests; here
  // we prove the page owns the reads.
  it("renders the alert feed from the alerts route", async () => {
    render(<ObservabilityOverviewPage />);

    await waitFor(() => {
      expect(screen.getByTestId("observability-alerts-list")).toBeTruthy();
    });
    expect(screen.getByText("Audit tamper attempt blocked")).toBeTruthy();
    expect(mockFetchAlerts).toHaveBeenCalledTimes(1);
  });

  it("renders a deep-link per configured vendor and omits absent ones", async () => {
    resolveDeeplinksWith({
      grafana: "https://acme.grafana.net",
      sentry: null,
      langfuse: null,
    });

    render(<ObservabilityOverviewPage />);

    await waitFor(() => {
      expect(screen.getByTestId("observability-deeplink-grafana")).toBeTruthy();
    });
    expect(screen.queryByTestId("observability-deeplink-sentry")).toBeNull();
    expect(screen.queryByTestId("observability-deeplink-langfuse")).toBeNull();
  });

  it("shows the alert feed's empty state when there are no alerts", async () => {
    resolveAlertsWith({ alerts: [], total_count: 0 });

    render(<ObservabilityOverviewPage />);

    await waitFor(() => {
      expect(screen.getByTestId("empty-state-title").textContent).toBe(
        "No alerts",
      );
    });
  });
});
