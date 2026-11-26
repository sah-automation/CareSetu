// #709 C2b: the operator Cost panel page rendered against the REAL read client
// and the REAL wire body.
//
// page.test.tsx mocks `fetchCost`, so it starts below the wire->model boundary
// and could never see a decoding fault. This file exists to hold that boundary:
// every body below is the exact JSON the routes emit - pydantic serialises each
// backend `Decimal` as a STRING - so a client that passes the wire straight
// through hands `formatPct` a string and takes the whole panel down with
// "value.toFixed is not a function".

import { cleanup, render, screen, waitFor } from "@testing-library/react";
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
  signInOperator,
  stubFailingRoute,
  stubRouteWire,
} from "@/test/observabilityWire";

import ObservabilityCostPage from "./page";

/** `/cost`: Decimals arrive quoted, exactly as facade.CostSummary serialises. */
const COST_WIRE = {
  period_start: "2026-10-01",
  period_end: "2026-10-31",
  total_spend_paise: 125000,
  total_limit_paise: 500000,
  remaining_paise: 375000,
  utilization_pct: "25.00",
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
      utilization_pct: "33.33",
      exhausted: false,
    },
  ],
};

/** `/cost/trend` carries no Decimal, so its wire body equals its domain shape. */
const TREND_WIRE = {
  days: 30,
  from_date: "2026-09-13",
  to_date: "2026-10-12",
  points: [
    { usage_date: "2026-10-01", calls: 4, cost_paise: 10000 },
    { usage_date: "2026-10-02", calls: 9, cost_paise: 25000 },
  ],
};

beforeAll(() => useChartDom());

beforeEach(() => {
  signInOperator();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  clearOperatorSession();
});

describe("ObservabilityCostPage over the real wire", () => {
  it("renders the budget takeaway from quoted wire decimals", async () => {
    stubRouteWire({
      "/observability/cost/trend": TREND_WIRE,
      "/observability/cost": COST_WIRE,
    });

    render(<ObservabilityCostPage />);

    // The reported crash: a string reaching `formatPct` blew up here. This
    // asserts the panel is still rendering, not merely that the promise settled.
    await waitFor(() => {
      expect(screen.getByTestId("cost-budget-takeaway").textContent).toBe(
        "₹1,250 of ₹5,000 · 25% used · ₹3,750 remaining",
      );
    });
  });

  it("does not blank the budget panel when the trend read fails", async () => {
    stubFailingRoute("/observability/cost/trend", {
      "/observability/cost": COST_WIRE,
    });

    render(<ObservabilityCostPage />);

    await waitFor(() => {
      expect(screen.getByTestId("cost-budget-takeaway").textContent).toContain(
        "25% used",
      );
    });
    expect(screen.getByTestId("cost-trend-error")).toBeTruthy();
  });

  it("shows the error path rather than a NaN figure when a decimal drifts", async () => {
    stubRouteWire({
      "/observability/cost/trend": TREND_WIRE,
      "/observability/cost": { ...COST_WIRE, utilization_pct: "not-a-number" },
    });

    render(<ObservabilityCostPage />);

    await waitFor(() => {
      expect(screen.getByTestId("cost-budget-error")).toBeTruthy();
    });
    expect(screen.queryByText(/NaN/)).toBeNull();
  });
});
