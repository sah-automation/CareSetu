// #743: the operator Product lens page rendered against the REAL read client
// and the REAL wire bodies.
//
// page.test.tsx mocks the three fetchers, so it starts above the wire->model
// boundary and could never see a decoding fault. This file holds that boundary:
// pydantic serialises every backend `Decimal` as a STRING, and every product
// figure the page renders - stickiness, load per head, the funnel's conversion
// and gap, both headline rates, and each retention horizon - arrives quoted. A
// client that passed the body through would hand `formatRate` a string and take
// the panel down.
//
// The stub comes from the shared helper (#737 AC4), the session is a real
// operator written through `saveSession`, and the transport is the only thing
// faked - so all three lens pages agree on what "over the wire" means.

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

import { useChartDom } from "@/test/chartDom";
import {
  clearOperatorSession,
  requestedUrls,
  signInOperator,
  stubFailingRoute,
  stubRouteWire,
} from "@/test/observabilityWire";

import ObservabilityProductPage from "./page";

/**
 * `/v1/operator/observability/product/active-users` for a rolling thirty-day
 * window: counts are integers, and both rates are quoted `Decimal`s.
 */
const ACTIVE_USERS_WIRE = {
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
  stickiness: "0.0833",
  requests: 3000,
  requests_per_active_user: "20.00",
  trend: [
    {
      day: "2026-10-12",
      requests: 120,
      active_users: 10,
      requests_per_active_user: "12.00",
    },
  ],
  window_convention: "window",
  source_convention: "source",
  stickiness_convention: "stickiness",
  requests_per_active_user_convention: "per head",
};

/**
 * `/product/funnel`: the first step's conversion and gap are null (there is no
 * predecessor to measure from), the second's are quoted, and both headline
 * rates are quoted.
 */
const FUNNEL_WIRE = {
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
      conversion_from_previous: "0.8000",
      median_gap_from_previous_s: "45.0000",
      gap_samples: 70,
      gap_basis: "actor_key",
      latest_trace_id: null,
    },
  ],
  outcomes: {
    started: 100,
    task_success_rate: "0.7200",
    abandonment_rate: "0.1000",
    issued_e_prescriptions: 60,
    cases_closed: 12,
    abandoned: 10,
    errored: 4,
    re_recorded: 4,
  },
};

/**
 * `/product/retention-cohorts`: a mature cohort with quoted rates, and a young
 * cohort whose horizons are still in the future - `retained` and `retention`
 * both null, never zero.
 */
const RETENTION_WIRE = {
  days: 60,
  from_date: "2026-08-14",
  to_date: "2026-10-12",
  horizons: [7, 30],
  cohorts: [
    {
      cohort_date: "2026-09-01",
      cohort_size: 40,
      retained_7d: 12,
      retention_7d: "0.3000",
      retained_30d: 6,
      retention_30d: "0.1500",
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

const DEEPLINKS_WIRE = {
  grafana: {
    dashboard_uid: "caresetu-observability",
    dashboard_url:
      "https://acme.grafana.net/d/caresetu-observability?from=now-30d&to=now",
  },
};

/** All three product routes plus the deep links, so nothing 200s an empty `{}`. */
function stubProductWire(overrides: Record<string, unknown> = {}) {
  return stubRouteWire({
    "/observability/product/active-users":
      overrides.activeUsers ?? ACTIVE_USERS_WIRE,
    "/observability/product/funnel": overrides.funnel ?? FUNNEL_WIRE,
    "/observability/product/retention-cohorts":
      overrides.retention ?? RETENTION_WIRE,
    "/observability/deeplinks": DEEPLINKS_WIRE,
  });
}

beforeAll(() => useChartDom());

beforeEach(() => {
  signInOperator();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  clearOperatorSession();
});

describe("ObservabilityProductPage over the real wire", () => {
  it("renders adoption from quoted decimals as numbers", async () => {
    stubProductWire();

    render(<ObservabilityProductPage />);

    await waitFor(() => {
      expect(
        screen.getByTestId("product-active-users-takeaway").textContent,
      ).toBe(
        "10 DAU · 42 WAU · 120 MAU · 8.3% stickiness · 3,000 requests · 20.00 per active user",
      );
    });
    expect(screen.getByTestId("product-active-users-chart")).toBeTruthy();
  });

  it("quotes both funnel rates and measures conversion from quoted steps", async () => {
    stubProductWire();

    render(<ObservabilityProductPage />);

    await waitFor(() => {
      expect(screen.getByTestId("product-funnel-takeaway").textContent).toBe(
        "100 started · 72% task success · 10% abandonment",
      );
    });
    expect(
      screen.getByTestId("product-funnel-steps-row-consult_complete-conversion")
        .textContent,
    ).toBe("80%");
    expect(
      screen.getByTestId("product-funnel-steps-row-consult_complete")
        .textContent,
    ).toContain("45s");
    // The first step's null conversion is unmeasured, not a zero.
    expect(
      screen.getByTestId("product-funnel-steps-row-composer_opened-conversion")
        .textContent,
    ).toBe("\u2014");
  });

  it("renders a mature cohort's quoted rates and a young cohort's null horizons", async () => {
    stubProductWire();

    render(<ObservabilityProductPage />);

    await waitFor(() => {
      expect(
        screen.getByTestId("product-retention-table-row-2026-09-01-day7")
          .textContent,
      ).toBe("12 · 30%");
    });
    expect(
      screen.getByTestId("product-retention-table-row-2026-09-01-day30")
        .textContent,
    ).toBe("6 · 15%");
    // Null on the wire stays null, and the cell says "not observed" with a dash
    // rather than fabricating a 0% collapse at the newest end of the table.
    expect(
      screen.getByTestId("product-retention-table-row-2026-10-10-day7")
        .textContent,
    ).toBe("\u2014");
    expect(
      screen.getByTestId("product-retention-table-row-2026-10-10-day30")
        .textContent,
    ).toBe("\u2014");
  });

  it("sends the operator's bearer and asks each route's default window", async () => {
    const fetchMock = stubProductWire();

    render(<ObservabilityProductPage />);

    await waitFor(() => {
      expect(screen.getByTestId("product-active-users-takeaway")).toBeTruthy();
    });

    const request = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    const headers = new Headers(request[1].headers);
    expect(headers.get("Authorization")).toBe("Bearer operator.jwt.value");

    const urls = requestedUrls(fetchMock);
    expect(urls).toContain(
      "http://localhost:8000/v1/operator/observability/product/active-users",
    );
    // The funnel's default is the whole funnel; the retention route owns its
    // own sixty-date default rather than the other reads' thirty.
    expect(urls).toContain(
      "http://localhost:8000/v1/operator/observability/product/funnel",
    );
    expect(urls).toContain(
      "http://localhost:8000/v1/operator/observability/product/retention-cohorts",
    );
  });

  it("sends the outcome filter as a query and re-reads only the funnel", async () => {
    const fetchMock = stubProductWire();

    render(<ObservabilityProductPage />);
    await waitFor(() => {
      expect(screen.getByTestId("product-funnel-takeaway")).toBeTruthy();
    });

    fireEvent.click(screen.getByTestId("product-funnel-filter-abandoned"));

    await waitFor(() => {
      expect(requestedUrls(fetchMock)).toContain(
        "http://localhost:8000/v1/operator/observability/product/funnel?outcome=abandoned",
      );
    });
    const urls = requestedUrls(fetchMock);
    expect(
      urls.filter((url) => url.includes("/product/active-users")),
    ).toHaveLength(1);
    expect(
      urls.filter((url) => url.includes("/product/retention-cohorts")),
    ).toHaveLength(1);
    expect(screen.getByTestId("product-funnel-filter-note")).toBeTruthy();
  });

  it("keeps every panel's error path when the product reads fail", async () => {
    // One suffix matches all three product routes, so every panel takes the
    // same expected-error path an operator would see on a misrouted read.
    stubFailingRoute("/observability/product", {
      "/observability/deeplinks": DEEPLINKS_WIRE,
    });

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
    }
    // The deep-links read is a separate route and kept working.
    expect(
      screen.getByTestId("observability-deeplink-grafana.dashboard_url"),
    ).toBeTruthy();
  });

  it("fails one panel without taking the other two down", async () => {
    stubFailingRoute("/observability/product/funnel", {
      "/observability/product/active-users": ACTIVE_USERS_WIRE,
      "/observability/product/retention-cohorts": RETENTION_WIRE,
      "/observability/deeplinks": DEEPLINKS_WIRE,
    });

    render(<ObservabilityProductPage />);

    await waitFor(() => {
      expect(screen.getByTestId("product-funnel-error")).toBeTruthy();
    });
    expect(screen.getByTestId("product-active-users-takeaway")).toBeTruthy();
    expect(screen.getByTestId("product-retention-takeaway")).toBeTruthy();
  });

  it("shows the error path rather than a NaN figure when a decimal drifts", async () => {
    stubProductWire({
      activeUsers: { ...ACTIVE_USERS_WIRE, stickiness: "not-a-number" },
    });

    render(<ObservabilityProductPage />);

    await waitFor(() => {
      expect(screen.getByTestId("product-active-users-error")).toBeTruthy();
    });
    expect(screen.queryByText(/NaN/)).toBeNull();
  });
});
