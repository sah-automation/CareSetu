// #737: the operator Business lens page rendered against the REAL read client and
// the REAL wire body.
//
// page.test.tsx mocks `fetchBusiness`, so it starts above the wire->model
// boundary and could never see a decoding fault. This file holds that boundary -
// and for the business read it is the widest one in the console: NINE quoted
// decimals at the top level, two more inside each of three breakdown rows and
// two interpolated percentiles per distribution, every one of which reaches a
// formatter on this page. pydantic serialises each backend `Decimal` as a STRING,
// so a client that passed the body straight through would hand `formatPct` a
// string and take the panel down with "value.toFixed is not a function".
//
// The stub comes from the shared helper (#737 AC4), the session is a real
// operator written through `saveSession`, and the transport is the only thing
// faked - so this is the one place the lens pages agree on what "over the wire"
// means.

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
  requestedUrls,
  signInOperator,
  stubFailingRoute,
  stubRouteWire,
} from "@/test/observabilityWire";

import ObservabilityBusinessPage from "./page";

/**
 * The exact JSON `/v1/operator/observability/business` emits for a month-to-date
 * window: money as integer paise, every `Decimal` QUOTED, the two margin
 * percentages as the null-with-a-reason pair a deployment that has not written
 * revenue gets, and the distribution percentiles as the bare integer strings
 * rank interpolation produces (no fixed scale).
 */
const BUSINESS_WIRE = {
  period: "month_to_date",
  period_start: "2026-10-01",
  period_end: "2026-10-12",
  spend_paise: 125000,
  jobs: 120,
  completed_jobs: 114,
  failed_jobs: 6,
  input_tokens: 100000,
  output_tokens: 40000,
  paise_per_1k_input_tokens: "90.0000",
  paise_per_1k_output_tokens: "300.0000",
  monthly_cap_paise: 500000,
  cap_consumed_paise: 125000,
  cap_consumed_pct: "25.00",
  projected_month_end_paise: 320000,
  projected_over_cap: false,
  projection_basis: {
    period_start: "2026-10-01",
    period_end: "2026-10-31",
    elapsed_days: 12,
    period_days: 31,
  },
  by_provider: [
    {
      provider: "openai_compatible",
      jobs: 120,
      spend_paise: 125000,
      input_tokens: 100000,
      output_tokens: 40000,
      paise_per_1k_input_tokens: "90.0000",
      paise_per_1k_output_tokens: "300.0000",
    },
  ],
  by_model: [
    {
      provider: "openai_compatible",
      model: "gpt-4o-mini",
      jobs: 120,
      spend_paise: 125000,
      input_tokens: 100000,
      output_tokens: 40000,
      paise_per_1k_input_tokens: "90.0000",
      paise_per_1k_output_tokens: "300.0000",
    },
  ],
  by_task_type: [
    {
      task_type: "transcribe",
      jobs: 120,
      spend_paise: 100000,
      input_tokens: 80000,
      output_tokens: 30000,
      paise_per_1k_input_tokens: "90.0000",
      paise_per_1k_output_tokens: "300.0000",
    },
  ],
  cost_per_request_paise: "1041.6667",
  cost_per_completed_task_paise: "1096.4912",
  cost_per_patient_paise: "25000.0000",
  cost_per_doctor_paise: "41666.6667",
  cost_of_pass_paise: "1096.4912",
  patient_spend: {
    actors: 5,
    total_spend_paise: 90000,
    median_spend_paise: "20000",
    p95_spend_paise: "56000",
    max_spend_paise: 56000,
  },
  doctor_spend: {
    actors: 3,
    total_spend_paise: 125000,
    median_spend_paise: "40000",
    p95_spend_paise: "80000",
    max_spend_paise: 80000,
  },
  top_patients: [
    {
      patient_key: "sha256:patient-a",
      attributed_doctor_key: "sha256:doctor-a",
      jobs: 40,
      completed_jobs: 38,
      failed_jobs: 2,
      spend_paise: 56000,
    },
  ],
  top_doctors: [
    {
      doctor_key: "sha256:doctor-a",
      patients: 5,
      jobs: 120,
      completed_jobs: 114,
      failed_jobs: 6,
      spend_paise: 125000,
    },
  ],
  margin: {
    revenue_paise: 0,
    cost_of_goods_paise: 125000,
    headline_month_cost_of_goods_paise: 125000,
    revenue_captured: false,
    tiers_captured: false,
    tier_keys: [],
    gross_margin: {
      value: null,
      reason: "revenue_not_captured",
      detail: "No revenue has been recorded yet.",
    },
    ai_cost_pct_of_revenue: {
      value: null,
      reason: "revenue_not_captured",
      detail: "No revenue has been recorded yet.",
    },
  },
};

/** One configured vendor; the other two are ABSENT, as `exclude_none` sends them. */
const DEEPLINKS_WIRE = {
  grafana: {
    dashboard_uid: "caresetu-observability",
    dashboard_url:
      "https://acme.grafana.net/d/caresetu-observability?from=now-30d&to=now",
  },
};

/** Both routes the page reads, so a page that asked for something else would 200 `{}`. */
function stubBusinessWire(business: unknown = BUSINESS_WIRE) {
  return stubRouteWire({
    "/observability/business": business,
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

describe("ObservabilityBusinessPage over the real wire", () => {
  it("renders the spend panel from quoted wire decimals", async () => {
    stubBusinessWire();

    render(<ObservabilityBusinessPage />);

    // The reported crash class: a string reaching `formatPct` blew up here. This
    // asserts the panel is still rendering, not merely that the promise settled.
    await waitFor(() => {
      expect(screen.getByTestId("business-spend-takeaway").textContent).toBe(
        "₹1,250 spent · 25% of ₹5,000 cap · ₹3,200 projected by month end",
      );
    });
  });

  it("prices each unit from the quoted 4dp unit costs", async () => {
    stubBusinessWire();

    render(<ObservabilityBusinessPage />);

    await waitFor(() => {
      expect(
        screen.getByTestId("business-unit-costs-list-per-request").textContent,
      ).toBe("₹10.42");
    });
    expect(
      screen.getByTestId("business-unit-costs-list-per-patient").textContent,
    ).toBe("₹250.00");
  });

  it("draws the breakdown chart from the quoted rates inside each row", async () => {
    stubBusinessWire();

    render(<ObservabilityBusinessPage />);

    await waitFor(() => {
      expect(
        screen.getByTestId("business-breakdown-takeaway").textContent,
      ).toBe("1 task types · the largest is transcribe at ₹1,000");
    });
  });

  it("reports the interpolated percentiles as numbers, at their bare scale", async () => {
    stubBusinessWire();

    render(<ObservabilityBusinessPage />);

    await waitFor(() => {
      expect(
        screen.getByTestId("business-heavy-actors-takeaway").textContent,
      ).toBe("5 patients · 3 doctors attributed");
    });
    // "20000", not "20000.0000" - the guard has to take the bare integer string
    // or the panel never renders at all.
    expect(screen.getByTestId("business-heavy-actors").textContent).toContain(
      "median ₹200",
    );
    expect(screen.getByTestId("business-heavy-actors").textContent).toContain(
      "p95 ₹560",
    );
  });

  it("sends the operator's bearer and asks for the route's default window", async () => {
    const fetchMock = stubBusinessWire();

    render(<ObservabilityBusinessPage />);

    await waitFor(() => {
      expect(screen.getByTestId("business-spend-takeaway")).toBeTruthy();
    });

    // A real session, so the Authorization header went out and the read was not
    // rejected for want of one.
    const request = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    const headers = new Headers(request[1].headers);
    expect(headers.get("Authorization")).toBe("Bearer operator.jwt.value");
    // No invented window: the route's own default is the one authority.
    expect(requestedUrls(fetchMock)).toContain(
      "http://localhost:8000/v1/operator/observability/business",
    );
  });

  it("states revenue-not-captured rather than printing a zero margin", async () => {
    stubBusinessWire();

    render(<ObservabilityBusinessPage />);

    await waitFor(() => {
      expect(screen.getByTestId("empty-state-title").textContent).toBe(
        "Revenue not captured yet",
      );
    });
    expect(screen.queryByTestId("business-margin-takeaway")).toBeNull();
  });

  it("deep-links onward into the vendor traces", async () => {
    stubBusinessWire();

    render(<ObservabilityBusinessPage />);

    await waitFor(() => {
      expect(
        screen.getByTestId("observability-deeplink-grafana.dashboard_url"),
      ).toBeTruthy();
    });
    expect(
      screen
        .getByTestId("observability-deeplink-grafana.dashboard_url")
        .getAttribute("href"),
    ).toContain("caresetu-observability");
  });

  it("keeps every panel's error path when the business read fails", async () => {
    // A 404 with an envelope code to match, so the panel takes the same
    // expected-error path an operator would see on a misrouted read.
    stubFailingRoute("/observability/business", {
      "/observability/deeplinks": DEEPLINKS_WIRE,
    });

    render(<ObservabilityBusinessPage />);

    await waitFor(() => {
      expect(screen.getByTestId("business-spend-error")).toBeTruthy();
    });
    for (const panel of [
      "business-spend",
      "business-breakdown",
      "business-unit-costs",
      "business-margin",
      "business-heavy-actors",
    ]) {
      expect(screen.getByTestId(`${panel}-error`)).toBeTruthy();
      expect(screen.getByTestId(`${panel}-retry`)).toBeTruthy();
    }
    // The deep-links read is a separate route and kept working.
    expect(
      screen.getByTestId("observability-deeplink-grafana.dashboard_url"),
    ).toBeTruthy();
  });

  it("shows the error path rather than a NaN figure when a decimal drifts", async () => {
    stubBusinessWire({
      ...BUSINESS_WIRE,
      cap_consumed_pct: "not-a-number",
    });

    render(<ObservabilityBusinessPage />);

    await waitFor(() => {
      expect(screen.getByTestId("business-spend-error")).toBeTruthy();
    });
    expect(screen.queryByText(/NaN/)).toBeNull();
  });
});
