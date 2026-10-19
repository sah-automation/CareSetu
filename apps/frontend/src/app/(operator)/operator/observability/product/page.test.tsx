// #743: the operator Product lens page. Mocks the client at the
// lib/operator/observability seam and covers the states every panel owes an
// operator: loading, populated, empty, error and retry - by test id, exactly as
// the other lens pages do.
//
// page.wire.test.tsx holds the boundary below this one. This file starts ABOVE
// the wire->model boundary, so it can prove the page renders, distinguishes and
// recovers from each state, and never could have caught a client that decoded a
// quoted Decimal wrong.

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
  fetchActiveUsers,
  fetchDeeplinks,
  fetchFunnel,
  fetchRetentionCohorts,
  type ActiveUsersRead,
  type Deeplinks,
  type FunnelRead,
  type ProductOutcome,
  type RetentionCohortsRead,
} from "@/lib/operator/observability";
import { DASH } from "@/lib/operator/observability-format";
import { useChartDom } from "@/test/chartDom";

import ObservabilityProductPage from "./page";

vi.mock("@/lib/operator/observability", async (importOriginal) => {
  const mod =
    await importOriginal<typeof import("@/lib/operator/observability")>();
  return {
    ...mod,
    fetchActiveUsers: vi.fn(),
    fetchFunnel: vi.fn(),
    fetchRetentionCohorts: vi.fn(),
    fetchDeeplinks: vi.fn(),
  };
});

const mockFetchActiveUsers = vi.mocked(fetchActiveUsers);
const mockFetchFunnel = vi.mocked(fetchFunnel);
const mockFetchRetentionCohorts = vi.mocked(fetchRetentionCohorts);
const mockFetchDeeplinks = vi.mocked(fetchDeeplinks);

const NO_VENDORS: Deeplinks = {
  grafana: {
    dashboard_uid: "caresetu-observability",
    dashboard_url: "https://acme.grafana.net/d/caresetu-observability",
  },
};

const ACTIVE_USERS: ActiveUsersRead = {
  days: 30,
  from_date: "2026-09-13",
  to_date: "2026-10-12",
  daily_active_users: {
    window_days: 1,
    from_date: "2026-10-12",
    to_date: "2026-10-12",
    patients: 8,
    doctors: 2,
    total: 10,
  },
  weekly_active_users: {
    window_days: 7,
    from_date: "2026-10-06",
    to_date: "2026-10-12",
    patients: 34,
    doctors: 8,
    total: 42,
  },
  monthly_active_users: {
    window_days: 30,
    from_date: "2026-09-13",
    to_date: "2026-10-12",
    patients: 96,
    doctors: 24,
    total: 120,
  },
  window_active_users: {
    window_days: 30,
    from_date: "2026-09-13",
    to_date: "2026-10-12",
    patients: 120,
    doctors: 30,
    total: 150,
  },
  stickiness: 0.0833,
  requests: 3000,
  requests_per_active_user: 20,
  trend: [
    {
      day: "2026-10-11",
      requests: 90,
      active_users: 8,
      requests_per_active_user: 11.25,
    },
    {
      day: "2026-10-12",
      requests: 120,
      active_users: 10,
      requests_per_active_user: 12,
    },
  ],
  window_convention: "window",
  source_convention: "source",
  stickiness_convention: "stickiness",
  requests_per_active_user_convention: "per head",
};

const FUNNEL: FunnelRead = {
  funnel: "intake",
  window_start: "2026-10-12T00:00:00Z",
  window_end: "2026-10-12T23:59:59Z",
  window_days: 1,
  outcome: null,
  denominator_convention: "denominator",
  rate_convention: "rates",
  gap_convention: "gaps",
  steps: [
    {
      step: "composer_opened",
      event_type: "composer_opened",
      terminal: false,
      previous_step: null,
      entered: 100,
      completed: 90,
      abandoned: 6,
      errored: 2,
      re_recorded: 2,
      conversion_from_previous: null,
      median_gap_from_previous_s: null,
      gap_samples: 0,
      gap_basis: "no_predecessor",
      latest_trace_id: "trace-a",
    },
    {
      step: "consult_complete",
      event_type: "consult_complete",
      terminal: true,
      previous_step: "composer_opened",
      entered: 80,
      completed: 72,
      abandoned: 4,
      errored: 2,
      re_recorded: 2,
      conversion_from_previous: 0.8,
      median_gap_from_previous_s: 45,
      gap_samples: 70,
      gap_basis: "actor_key",
      latest_trace_id: null,
    },
  ],
  outcomes: {
    started: 100,
    task_success_rate: 0.72,
    abandonment_rate: 0.1,
    issued_e_prescriptions: 60,
    cases_closed: 12,
    abandoned: 10,
    errored: 4,
    re_recorded: 4,
  },
};

const RETENTION: RetentionCohortsRead = {
  days: 60,
  from_date: "2026-08-14",
  to_date: "2026-10-12",
  horizons: [7, 30],
  cohorts: [
    {
      cohort_date: "2026-09-01",
      cohort_size: 40,
      retained_7d: 12,
      retention_7d: 0.3,
      retained_30d: 6,
      retention_30d: 0.15,
    },
    {
      cohort_date: "2026-10-10",
      cohort_size: 5,
      retained_7d: null,
      retention_7d: null,
      retained_30d: null,
      retention_30d: null,
    },
  ],
  window_convention: "window",
  maturity_convention: "maturity",
  source_convention: "source",
  actor_convention: "actors",
};

function resolveAllWith(data: {
  activeUsers?: ActiveUsersRead | null;
  funnel?: FunnelRead | null;
  retention?: RetentionCohortsRead | null;
}) {
  const resolve = <T,>(value: T | null | undefined) =>
    value === null
      ? Promise.reject(new Error("network down"))
      : Promise.resolve(value as T);
  mockFetchActiveUsers.mockImplementation(() =>
    resolve("activeUsers" in data ? data.activeUsers : ACTIVE_USERS),
  );
  mockFetchFunnel.mockImplementation((params = {}) =>
    resolve(
      data.funnel === null
        ? null
        : params.outcome
          ? { ...FUNNEL, outcome: params.outcome as ProductOutcome, steps: [] }
          : data.funnel ?? FUNNEL,
    ),
  );
  mockFetchRetentionCohorts.mockImplementation(() =>
    resolve("retention" in data ? data.retention : RETENTION),
  );
}

beforeAll(() => useChartDom());

beforeEach(() => {
  resolveAllWith({});
  mockFetchDeeplinks.mockImplementation(() => Promise.resolve(NO_VENDORS));
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("ObservabilityProductPage", () => {
  it("shows a loading skeleton for every panel while the reads are in flight", () => {
    mockFetchActiveUsers.mockImplementation(
      () => new Promise<ActiveUsersRead>(() => {}),
    );
    mockFetchFunnel.mockImplementation(() => new Promise<FunnelRead>(() => {}));
    mockFetchRetentionCohorts.mockImplementation(
      () => new Promise<RetentionCohortsRead>(() => {}),
    );

    render(<ObservabilityProductPage />);

    for (const panel of [
      "product-active-users",
      "product-funnel",
      "product-retention",
    ]) {
      expect(screen.getByTestId(`${panel}-loading`)).toBeTruthy();
    }
  });

  it("states DAU, WAU, MAU, stickiness and load per head together", async () => {
    render(<ObservabilityProductPage />);

    await waitFor(() => {
      expect(
        screen.getByTestId("product-active-users-takeaway").textContent,
      ).toBe(
        "10 DAU · 42 WAU · 120 MAU · 8.3% stickiness · 3,000 requests · 20.00 per active user",
      );
    });
    expect(screen.getByTestId("product-active-users-dau").textContent).toBe(
      "10",
    );
    expect(screen.getByTestId("product-active-users-wau").textContent).toBe(
      "42",
    );
    expect(screen.getByTestId("product-active-users-mau").textContent).toBe(
      "120",
    );
    expect(
      screen.getByTestId("product-active-users-stickiness").textContent,
    ).toBe("8.3%");
    expect(
      screen.getByTestId("product-active-users-per-head").textContent,
    ).toBe("20.00");
  });

  it("says MAU comes from the system of record, not the vendor's short window", async () => {
    render(<ObservabilityProductPage />);

    await waitFor(() => {
      expect(
        screen.getByTestId("product-active-users-mau-source").textContent,
      ).toContain("Postgres");
    });
    expect(
      screen.getByTestId("product-active-users-mau-source").textContent,
    ).toContain("fourteen-day retention");
    // The date range is the rolling thirty days, shown next to the figure.
    expect(screen.getByTestId("product-active-users").textContent).toContain(
      "2026-09-13 to 2026-10-12",
    );
  });

  it("quotes success and abandonment together over one started count", async () => {
    render(<ObservabilityProductPage />);

    await waitFor(() => {
      expect(screen.getByTestId("product-funnel-takeaway").textContent).toBe(
        "100 started · 72% task success · 10% abandonment",
      );
    });
    expect(screen.getByTestId("product-funnel-success-rate").textContent).toBe(
      "72%",
    );
    expect(
      screen.getByTestId("product-funnel-abandonment-rate").textContent,
    ).toBe("10%");
    expect(screen.getByTestId("product-funnel-prescriptions").textContent).toBe(
      "60 / 12",
    );
  });

  it("walks the steps with their conversion and median thinking time", async () => {
    render(<ObservabilityProductPage />);

    await waitFor(() => {
      expect(
        screen.getByTestId("product-funnel-steps-row-consult_complete"),
      ).toBeTruthy();
    });
    expect(
      screen.getByTestId("product-funnel-steps-row-consult_complete-conversion")
        .textContent,
    ).toBe("80%");
    expect(
      screen.getByTestId("product-funnel-steps-row-consult_complete")
        .textContent,
    ).toContain("45s");
    // The first step has no predecessor, so its conversion is unmeasured.
    expect(
      screen.getByTestId("product-funnel-steps-row-composer_opened-conversion")
        .textContent,
    ).toBe(DASH);
  });

  it("re-reads the funnel when the operator isolates an outcome", async () => {
    render(<ObservabilityProductPage />);
    await waitFor(() => {
      expect(screen.getByTestId("product-funnel-takeaway")).toBeTruthy();
    });

    // The controls survive every state, so they are present before the slice.
    expect(screen.getByTestId("product-funnel-filter-abandoned")).toBeTruthy();
    fireEvent.click(screen.getByTestId("product-funnel-filter-abandoned"));

    await waitFor(() => {
      expect(mockFetchFunnel).toHaveBeenLastCalledWith({
        outcome: "abandoned",
      });
    });
    await waitFor(() => {
      expect(
        screen.getByTestId("product-funnel-filter-note").textContent,
      ).toContain("whole window");
    });
    expect(screen.getByTestId("product-funnel-no-steps").textContent).toContain(
      "abandoned",
    );
    // The headline pair is still the whole window's, not the slice's.
    expect(screen.getByTestId("product-funnel-takeaway").textContent).toBe(
      "100 started · 72% task success · 10% abandonment",
    );
  });

  it("reports retention pooled over measured cohorts, with their base", async () => {
    render(<ObservabilityProductPage />);

    await waitFor(() => {
      expect(screen.getByTestId("product-retention-takeaway").textContent).toBe(
        "2 arrival dates · pooled 7-day 30% · pooled 30-day 15%",
      );
    });
    expect(
      screen.getByTestId("product-retention-table-row-2026-09-01-day7")
        .textContent,
    ).toBe("12 · 30%");
    expect(
      screen.getByTestId("product-retention-table-row-2026-09-01-day30")
        .textContent,
    ).toBe("6 · 15%");
  });

  it("prints an unarrived horizon as the dash, never as zero", async () => {
    render(<ObservabilityProductPage />);

    await waitFor(() => {
      expect(
        screen.getByTestId("product-retention-table-row-2026-10-10-day7"),
      ).toBeTruthy();
    });
    const young = screen.getByTestId(
      "product-retention-table-row-2026-10-10-day7",
    );
    expect(young.textContent).toBe(DASH);
    expect(young.textContent).not.toContain("0%");
    expect(
      screen.getByTestId("product-retention-table-row-2026-10-10-day30")
        .textContent,
    ).toBe(DASH);
  });

  it("gives each panel its own empty reason", async () => {
    resolveAllWith({
      activeUsers: {
        ...ACTIVE_USERS,
        daily_active_users: { ...ACTIVE_USERS.daily_active_users, total: 0 },
        weekly_active_users: { ...ACTIVE_USERS.weekly_active_users, total: 0 },
        monthly_active_users: {
          ...ACTIVE_USERS.monthly_active_users,
          total: 0,
        },
        trend: [],
      },
      funnel: {
        ...FUNNEL,
        steps: [],
        outcomes: {
          ...FUNNEL.outcomes,
          started: 0,
          task_success_rate: null,
          abandonment_rate: null,
        },
      },
      retention: { ...RETENTION, cohorts: [] },
    });

    render(<ObservabilityProductPage />);

    await waitFor(() => {
      expect(screen.getByTestId("product-active-users").dataset.status).toBe(
        "ready",
      );
    });
    expect(screen.getByTestId("product-active-users").textContent).toContain(
      "No active users in this window",
    );
    expect(screen.getByTestId("product-funnel").textContent).toContain(
      "No journey reached the funnel in this window",
    );
    expect(screen.getByTestId("product-retention").textContent).toContain(
      "No arrival dates in this window",
    );
    // The filters are questions about the read, so they survive emptiness.
    expect(screen.getByTestId("product-funnel-filter-abandoned")).toBeTruthy();
    expect(
      screen.getByTestId("product-active-users").querySelector("svg"),
    ).toBe(null);
  });

  it("shows the failure inline on every panel, with a retry", async () => {
    resolveAllWith({ activeUsers: null, funnel: null, retention: null });

    render(<ObservabilityProductPage />);

    await waitFor(() => {
      expect(screen.getByTestId("product-active-users-error")).toBeTruthy();
    });
    for (const panel of [
      "product-active-users",
      "product-funnel",
      "product-retention",
    ]) {
      expect(screen.getByTestId(`${panel}-error`)).toBeTruthy();
      expect(screen.getByTestId(`${panel}-retry`)).toBeTruthy();
      expect(screen.getByTestId(`${panel}-error-no-trace`)).toBeTruthy();
    }
  });

  it("retries the failed read rather than the page", async () => {
    resolveAllWith({ activeUsers: null });
    render(<ObservabilityProductPage />);
    await waitFor(() => {
      expect(screen.getByTestId("product-active-users-error")).toBeTruthy();
    });

    resolveAllWith({});
    fireEvent.click(screen.getByTestId("product-active-users-retry"));

    await waitFor(() => {
      expect(
        screen.getByTestId("product-active-users-takeaway").textContent,
      ).toContain("10 DAU");
    });
    expect(mockFetchActiveUsers).toHaveBeenCalledTimes(2);
    // The other reads are different routes and were not re-run.
    expect(mockFetchFunnel).toHaveBeenCalledTimes(1);
    expect(mockFetchRetentionCohorts).toHaveBeenCalledTimes(1);
  });

  it("deep-links onward into the vendor traces", async () => {
    render(<ObservabilityProductPage />);

    await waitFor(() => {
      expect(
        screen.getByTestId("observability-deeplink-grafana.dashboard_url"),
      ).toBeTruthy();
    });
  });

  it("marks the current panel tab and links the others", () => {
    render(<ObservabilityProductPage />);

    expect(screen.getByTestId("observability-tab-product")).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByTestId("observability-tab-business")).toHaveAttribute(
      "href",
      "/operator/observability/business",
    );
  });
});
