// #737: the operator Business lens page. Mocks the client at the
// lib/operator/observability seam and covers the states every panel owes an
// operator: loading, populated, empty, error and retry - by test id, exactly as
// the four panel pages do.
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
  fetchBusiness,
  fetchDeeplinks,
  type BusinessRead,
  type Deeplinks,
} from "@/lib/operator/observability";
import { DASH } from "@/lib/operator/observability-format";
import { useChartDom, drawnChart } from "@/test/chartDom";

import ObservabilityBusinessPage from "./page";

vi.mock("@/lib/operator/observability", async (importOriginal) => {
  const mod =
    await importOriginal<typeof import("@/lib/operator/observability")>();
  return { ...mod, fetchBusiness: vi.fn(), fetchDeeplinks: vi.fn() };
});

const mockFetchBusiness = vi.mocked(fetchBusiness);
const mockFetchDeeplinks = vi.mocked(fetchDeeplinks);

/** Revenue captured, so the margin panel has a ready state to render. */
const CAPTURED_REVENUE = true;

const MEASURED: BusinessRead = {
  period: "month_to_date",
  period_start: "2026-10-01",
  period_end: "2026-10-12",
  spend_paise: 125000,
  jobs: 120,
  completed_jobs: 114,
  failed_jobs: 6,
  input_tokens: 100000,
  output_tokens: 40000,
  paise_per_1k_input_tokens: 90,
  paise_per_1k_output_tokens: 300,
  monthly_cap_paise: 500000,
  cap_consumed_paise: 125000,
  cap_consumed_pct: 25,
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
      paise_per_1k_input_tokens: 90,
      paise_per_1k_output_tokens: 300,
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
      paise_per_1k_input_tokens: 90,
      paise_per_1k_output_tokens: 300,
    },
  ],
  by_task_type: [
    {
      task_type: "transcribe",
      jobs: 120,
      spend_paise: 100000,
      input_tokens: 80000,
      output_tokens: 30000,
      paise_per_1k_input_tokens: 90,
      paise_per_1k_output_tokens: 300,
    },
    {
      task_type: "draft",
      jobs: 0,
      spend_paise: 25000,
      input_tokens: 20000,
      output_tokens: 10000,
      paise_per_1k_input_tokens: 90,
      paise_per_1k_output_tokens: 300,
    },
  ],
  cost_per_request_paise: 1041.6667,
  cost_per_completed_task_paise: 1096.4912,
  cost_per_patient_paise: 25000,
  cost_per_doctor_paise: 41666.6667,
  cost_of_pass_paise: 1096.4912,
  patient_spend: {
    actors: 5,
    total_spend_paise: 90000,
    median_spend_paise: 20000,
    p95_spend_paise: 56000,
    max_spend_paise: 56000,
  },
  doctor_spend: {
    actors: 3,
    total_spend_paise: 125000,
    median_spend_paise: 40000,
    p95_spend_paise: 80000,
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
    {
      patient_key: "sha256:patient-b",
      attributed_doctor_key: null,
      jobs: 10,
      completed_jobs: 10,
      failed_jobs: 0,
      spend_paise: 20000,
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
    revenue_paise: 5000000,
    cost_of_goods_paise: 125000,
    headline_month_cost_of_goods_paise: 125000,
    revenue_captured: CAPTURED_REVENUE,
    tiers_captured: true,
    tier_keys: ["general"],
    gross_margin: {
      value: 97.5,
      reason: null,
      detail: null,
    },
    ai_cost_pct_of_revenue: {
      value: 2.5,
      reason: null,
      detail: null,
    },
  },
};

const NO_VENDORS: Deeplinks = {
  grafana: {
    dashboard_uid: "caresetu-observability",
    dashboard_url: "https://acme.grafana.net/d/caresetu-observability",
  },
};

function resolveWith(data: BusinessRead | null) {
  mockFetchBusiness.mockImplementation(() =>
    data === null
      ? Promise.reject(new Error("network down"))
      : Promise.resolve(data),
  );
}

/** Nothing has run in this window: every panel has a distinct empty reason. */
const NOTHING_RUN: BusinessRead = {
  ...MEASURED,
  spend_paise: 0,
  jobs: 0,
  completed_jobs: 0,
  failed_jobs: 0,
  input_tokens: 0,
  output_tokens: 0,
  paise_per_1k_input_tokens: null,
  paise_per_1k_output_tokens: null,
  cap_consumed_paise: 0,
  cap_consumed_pct: 0,
  projected_month_end_paise: null,
  by_provider: [],
  by_model: [],
  by_task_type: [],
  cost_per_request_paise: null,
  cost_per_completed_task_paise: null,
  cost_per_patient_paise: null,
  cost_per_doctor_paise: null,
  cost_of_pass_paise: null,
  patient_spend: {
    actors: 0,
    total_spend_paise: 0,
    median_spend_paise: null,
    p95_spend_paise: null,
    max_spend_paise: null,
  },
  doctor_spend: {
    actors: 0,
    total_spend_paise: 0,
    median_spend_paise: null,
    p95_spend_paise: null,
    max_spend_paise: null,
  },
  top_patients: [],
  top_doctors: [],
  margin: {
    revenue_paise: 0,
    cost_of_goods_paise: 0,
    headline_month_cost_of_goods_paise: 0,
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

/** Spend recorded, but no revenue - the read's null-with-a-reason case. */
const NO_REVENUE: BusinessRead = {
  ...MEASURED,
  margin: {
    ...MEASURED.margin,
    revenue_paise: 0,
    revenue_captured: false,
    gross_margin: {
      value: null,
      reason: "revenue_not_captured",
      detail: "No revenue has been recorded yet.",
    },
    ai_cost_pct_of_revenue: {
      value: null,
      reason: "revenue_zero",
      detail: "Revenue recorded this month is zero.",
    },
  },
};

beforeAll(() => useChartDom());

beforeEach(() => {
  resolveWith(MEASURED);
  mockFetchDeeplinks.mockImplementation(() => Promise.resolve(NO_VENDORS));
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("ObservabilityBusinessPage", () => {
  it("shows a loading skeleton for every panel while the read is in flight", () => {
    mockFetchBusiness.mockImplementation(
      () => new Promise<BusinessRead>(() => {}),
    );

    render(<ObservabilityBusinessPage />);

    for (const panel of [
      "business-spend",
      "business-breakdown",
      "business-unit-costs",
      "business-margin",
      "business-heavy-actors",
    ]) {
      expect(screen.getByTestId(`${panel}-loading`)).toBeTruthy();
    }
  });

  it("states the window, the spend and the projection in one line", async () => {
    render(<ObservabilityBusinessPage />);

    await waitFor(() => {
      expect(screen.getByTestId("business-spend-takeaway").textContent).toBe(
        "₹1,250 spent · 25% of ₹5,000 cap · ₹3,200 projected by month end",
      );
    });
    // The window is not implied by the panel title: a figure with no window on
    // screen is a figure an operator cannot compare against yesterday.
    expect(screen.getByTestId("business-spend-window").textContent).toBe(
      "Month to date, 2026-10-01 to 2026-10-12",
    );
  });

  it("says the projection is over the cap rather than reporting headroom", async () => {
    resolveWith({
      ...MEASURED,
      projected_month_end_paise: 620000,
      projected_over_cap: true,
    });

    render(<ObservabilityBusinessPage />);

    await waitFor(() => {
      expect(
        screen.getByTestId("business-spend-takeaway").textContent,
      ).toContain("over cap");
    });
  });

  it("omits the projection when there is no stamped period to extrapolate from", async () => {
    resolveWith({
      ...MEASURED,
      projected_month_end_paise: null,
      projection_basis: null,
    });

    render(<ObservabilityBusinessPage />);

    await waitFor(() => {
      expect(screen.getByTestId("business-spend-takeaway").textContent).toBe(
        "₹1,250 spent · 25% of ₹5,000 cap",
      );
    });
  });

  it("draws one bar per task type, in rupees", async () => {
    render(<ObservabilityBusinessPage />);

    const chart = await drawnChart("business-breakdown-chart");
    // Two task types. A chart that measured 0x0 would draw nothing here.
    expect(chart.querySelectorAll(".recharts-bar-rectangle").length).toBe(2);
    expect(
      [...chart.querySelectorAll(".recharts-cartesian-axis-tick-value")].map(
        (node) => node.textContent,
      ),
    ).toEqual(expect.arrayContaining(["transcribe", "draft"]));
  });

  it("names the task type carrying the most spend", async () => {
    render(<ObservabilityBusinessPage />);

    await waitFor(() => {
      expect(
        screen.getByTestId("business-breakdown-takeaway").textContent,
      ).toBe("2 task types · the largest is transcribe at ₹1,000");
    });
  });

  it("prices every unit of value at paise precision", async () => {
    render(<ObservabilityBusinessPage />);

    await waitFor(() => {
      expect(
        screen.getByTestId("business-unit-costs-list-per-request").textContent,
      ).toBe("₹10.42");
    });
    // A per-patient cost keeps its paise too: the whole-rupee price rule would
    // print these as ₹250 and ₹11 and lose the precision that prices a unit.
    expect(
      screen.getByTestId("business-unit-costs-list-per-patient").textContent,
    ).toBe("₹250.00");
    expect(
      screen.getByTestId("business-unit-costs-list-cost-of-pass").textContent,
    ).toBe("₹10.96");
  });

  it("prices an unmeasured unit as a dash, never as zero", async () => {
    resolveWith({ ...MEASURED, cost_per_patient_paise: null });

    render(<ObservabilityBusinessPage />);

    await waitFor(() => {
      expect(
        screen.getByTestId("business-unit-costs-list-per-patient").textContent,
      ).toBe(DASH);
    });
    expect(
      screen.getByTestId("business-unit-costs-list-per-request").textContent,
    ).not.toBe("₹0.00");
  });

  it("names who is heavy, with the population and not just the capped rows", async () => {
    render(<ObservabilityBusinessPage />);

    await waitFor(() => {
      expect(
        screen.getByTestId("business-heavy-actors-takeaway").textContent,
      ).toBe("5 patients · 3 doctors attributed");
    });
    expect(
      screen.getByTestId("business-heavy-actors-patients-row-sha256:patient-a"),
    ).toBeTruthy();
    expect(
      screen.getByTestId("business-heavy-actors-doctors-row-sha256:doctor-a")
        .textContent,
    ).toContain("₹1,250");
  });

  it("prices an unmeasured distribution as a dash, never as zero", async () => {
    // Too few actors to interpolate a percentile. `median ₹0` would read as
    // "every patient cost nothing" rather than "there is no median yet".
    resolveWith({
      ...MEASURED,
      patient_spend: {
        ...MEASURED.patient_spend,
        actors: 1,
        median_spend_paise: null,
        p95_spend_paise: null,
      },
    });

    render(<ObservabilityBusinessPage />);

    await waitFor(() => {
      expect(
        screen.getByTestId("business-heavy-actors-patients").textContent,
      ).toContain(`median ${DASH}, p95 ${DASH}`);
    });
  });

  it("says a patient has no single doctor rather than naming a wrong one", async () => {
    render(<ObservabilityBusinessPage />);

    await waitFor(() => {
      expect(
        screen.getByTestId(
          "business-heavy-actors-patients-row-sha256:patient-b",
        ),
      ).toBeTruthy();
    });
    expect(
      screen.getByTestId("business-heavy-actors-patients-row-sha256:patient-b")
        .textContent,
    ).toContain("no doctor attributed");
  });

  it("says a doctor with no recorded patients is unknown, not doctorless", async () => {
    // Two different missing facts, two different sentences. Reusing the
    // patient's wording here would say "no doctor attributed" on a doctor row.
    resolveWith({
      ...MEASURED,
      top_doctors: [{ ...MEASURED.top_doctors[0], patients: null }],
    });

    render(<ObservabilityBusinessPage />);

    await waitFor(() => {
      expect(
        screen.getByTestId("business-heavy-actors-doctors").textContent,
      ).toContain("no patients recorded");
    });
    expect(
      screen.getByTestId("business-heavy-actors-doctors").textContent,
    ).not.toContain("no doctor attributed");
  });

  it("states revenue-not-captured as the reason, never as a zero margin", async () => {
    resolveWith(NO_REVENUE);

    render(<ObservabilityBusinessPage />);

    await waitFor(() => {
      expect(screen.getByTestId("empty-state-title").textContent).toBe(
        "Revenue not captured yet",
      );
    });
    // 0% gross margin is a claim about the business; "not captured" is the truth.
    expect(screen.queryByText(/0%/)).toBeNull();
  });

  it("reports a captured margin", async () => {
    render(<ObservabilityBusinessPage />);

    await waitFor(() => {
      expect(screen.getByTestId("business-margin-takeaway").textContent).toBe(
        "₹50,000 revenue · ₹1,250 AI cost of goods · 97.5% gross margin",
      );
    });
  });

  it("says nothing ran, in each panel's own terms", async () => {
    resolveWith(NOTHING_RUN);

    render(<ObservabilityBusinessPage />);

    await waitFor(() => {
      expect(screen.getByTestId("business-spend").dataset.status).toBe("ready");
    });
    expect(screen.getByTestId("business-spend").textContent).toContain(
      "No AI spend recorded in this window",
    );
    expect(screen.getByTestId("business-breakdown").textContent).toContain(
      "No AI spend by task type in this window",
    );
    expect(screen.getByTestId("business-heavy-actors").textContent).toContain(
      "No attributed patients or doctors in this window",
    );
    // An empty panel draws no chart.
    expect(
      screen.getByTestId("business-spend").querySelector("svg"),
    ).toBeNull();
  });

  it("shows the failure inline on every panel, with a retry", async () => {
    resolveWith(null);

    render(<ObservabilityBusinessPage />);

    await waitFor(() => {
      expect(screen.getByTestId("business-spend-error")).toBeTruthy();
    });
    expect(screen.getByTestId("business-spend-retry")).toBeTruthy();
    expect(screen.getByTestId("business-breakdown-error")).toBeTruthy();
    // A transport failure reaches no API, so it carries no trace id - and the
    // panel says so rather than leaving an operator with nothing to quote.
    expect(screen.getByTestId("business-spend-error-no-trace")).toBeTruthy();
  });

  it("retries the failed read rather than the page", async () => {
    resolveWith(null);
    render(<ObservabilityBusinessPage />);
    await waitFor(() => {
      expect(screen.getByTestId("business-spend-error")).toBeTruthy();
    });

    resolveWith(MEASURED);
    fireEvent.click(screen.getByTestId("business-spend-retry"));

    await waitFor(() => {
      expect(
        screen.getByTestId("business-spend-takeaway").textContent,
      ).toContain("₹1,250 spent");
    });
    expect(mockFetchBusiness).toHaveBeenCalledTimes(2);
    // The deep-links read is a different route and was not re-run.
    expect(mockFetchDeeplinks).toHaveBeenCalledTimes(1);
  });

  it("deep-links onward into the vendor traces", async () => {
    render(<ObservabilityBusinessPage />);

    await waitFor(() => {
      expect(
        screen.getByTestId("observability-deeplink-grafana.dashboard_url"),
      ).toBeTruthy();
    });
  });

  it("marks the current panel tab and links the others", () => {
    render(<ObservabilityBusinessPage />);

    expect(screen.getByTestId("observability-tab-business")).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByTestId("observability-tab-cost")).toHaveAttribute(
      "href",
      "/operator/observability/cost",
    );
  });
});
