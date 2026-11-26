// #708 C2a: operator observability HTTP client contract. Mirrors
// lib/operator/api.test.ts - each fetcher resolves the C1 response shape, sends
// the query params the route declares, and raises ApiError (NETWORK_ERROR on
// fetch failure, UNEXPECTED_ERROR on a body the guards reject) so a page can
// show one error path for every read.

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  acknowledgeAlert,
  fetchActiveUsers,
  fetchAlerts,
  fetchBusiness,
  fetchCost,
  fetchCostTrend,
  fetchDeeplinks,
  fetchErrors,
  fetchFunnel,
  fetchHealth,
  fetchLatency,
  fetchOverview,
  fetchProviders,
  fetchQuality,
  fetchReliability,
  fetchRetentionCohorts,
  fetchThroughput,
  fetchUsage,
  type ActiveUsersRead,
  type AlertPage,
  type BusinessRead,
  type CostSummary,
  type CostTrend,
  type Deeplinks,
  type ErrorFeedPage,
  type FunnelRead,
  type LatencyReport,
  type Overview,
  type ProviderBoardReport,
  type QualityReport,
  type ReliabilityReport,
  type RetentionCohortsRead,
  type SystemHealth,
  type ThroughputReport,
  type UsageReport,
} from "./observability";

const BASE = "http://localhost:8000/v1/operator/observability";
const BASE_ORIGIN = "http://localhost:8000";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function stubFetch(body: unknown, status = 200) {
  const fetchMock = vi.fn().mockResolvedValue(jsonResponse(body, status));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function requestedUrl(fetchMock: ReturnType<typeof vi.fn>): string {
  return fetchMock.mock.calls[0][0] as string;
}

const OVERVIEW: Overview = {
  days: 30,
  from_date: "2026-09-12",
  to_date: "2026-10-12",
  total_calls: 120,
  success_count: 114,
  success_rate: 95.0,
  low_confidence_count: 3,
  low_confidence_rate: 2.6,
  p95_duration_ms: 4200,
  spend_paise: 125000,
  budget_paise: 500000,
  budget_utilization_pct: 25.0,
  budget_exhausted: false,
  open_alerts: 2,
  critical_open_alerts: 1,
  open_breakers: 0,
  business_counts: [{ metric_key: "case_closed", count: 7 }],
  last_rolled_date: "2026-10-11",
};

const COST: CostSummary = {
  period_start: "2026-10-01",
  period_end: "2026-10-31",
  total_spend_paise: 125000,
  total_limit_paise: 500000,
  remaining_paise: 375000,
  utilization_pct: 25.0,
  exhausted: false,
  budgets: [],
};

const COST_TREND: CostTrend = {
  days: 7,
  from_date: "2026-10-06",
  to_date: "2026-10-12",
  points: [{ usage_date: "2026-10-12", calls: 4, cost_paise: 900 }],
};

const USAGE: UsageReport = {
  days: 30,
  from_date: "2026-09-12",
  to_date: "2026-10-12",
  total_calls: 120,
  total_input_tokens: 1000,
  total_output_tokens: 400,
  total_cost_paise: 125000,
  rows: [],
};

const QUALITY: QualityReport = {
  days: 30,
  from_date: "2026-09-12",
  to_date: "2026-10-12",
  total_calls: 120,
  success_count: 114,
  failure_count: 4,
  timeout_count: 2,
  low_confidence_count: 3,
  success_rate: 95.0,
  low_confidence_rate: 2.6,
  providers: [],
};

const LATENCY: LatencyReport = {
  last_rolled_date: "2026-10-11",
  providers: [
    {
      provider: "openai_compatible",
      sample_count: 30,
      p50_duration_ms: 900,
      p95_duration_ms: 4200,
      p99_duration_ms: 5100,
      window_start: "2026-09-12T00:00:00Z",
      window_end: "2026-10-12T00:00:00Z",
    },
  ],
};

const HEALTH: SystemHealth = {
  dependencies: [
    { name: "database", status: "up", latency_ms: 3.2, detail: null },
  ],
  outbox: [
    {
      table_schema: "app",
      table: "outbox",
      pending: 0,
      inflight: 0,
      dead_letter: 0,
      backlog: 0,
    },
  ],
  outbox_backlog: 0,
  dead_letter_rows: 0,
  breakers: [],
  open_breakers: 0,
};

const ALERTS: AlertPage = {
  alerts: [
    {
      id: "6f1b0a2c-0000-4000-8000-000000000001",
      severity: "critical",
      kind: "ai_budget",
      title: "AI budget above 80%",
      payload: { used_paise: 420000 },
      status: "open",
      created_at: "2026-10-12T09:00:00Z",
      acked_by: null,
      acked_at: null,
    },
  ],
  total_count: 1,
};

/**
 * The widened wire shape (#736, decision 44): three bare base URLs became three
 * link SETS, each carrying its own filters, and an unconfigured vendor is absent
 * from the object rather than `null` in it.
 */
const DEEPLINKS: Deeplinks = {
  trace_id: "c7f2a1b0d3e4f5061728394a5b6c7d8e",
  grafana: {
    dashboard_uid: "caresetu-observability",
    dashboard_url:
      "https://grafana.example/d/caresetu-observability/caresetu-observability?from=now-6h&to=now",
    explore_url:
      "https://grafana.example/explore?left=%7B%22traceId%22%3A%22c7f2a1b0%22%7D",
  },
  sentry: {
    project_id: "7654321",
    issues_url:
      "https://o4242.sentry.io/issues/?project=7654321&query=service%3A%22api%22",
  },
  langfuse: {
    traces_url:
      "https://lf.example/project/pk/traces?model=gpt-4o&name=ai_structure",
  },
};

/** What the backend answers for a deployment with nothing configured at all. */
const NO_VENDORS_CONFIGURED = {};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("fetchOverview", () => {
  it("resolves the headline KPI payload from the overview route", async () => {
    const fetchMock = stubFetch(OVERVIEW);

    await expect(fetchOverview()).resolves.toEqual(OVERVIEW);
    expect(requestedUrl(fetchMock)).toBe(`${BASE}/overview`);
  });

  it("encodes the days window when one is given", async () => {
    const fetchMock = stubFetch(OVERVIEW);

    await fetchOverview({ days: 7 });

    expect(requestedUrl(fetchMock)).toBe(`${BASE}/overview?days=7`);
  });

  it("omits days when it is not given, so the route applies its own default", async () => {
    const fetchMock = stubFetch(OVERVIEW);

    await fetchOverview();

    expect(requestedUrl(fetchMock)).not.toContain("days=");
  });

  it("throws UNEXPECTED_ERROR when a KPI key is missing", async () => {
    const { last_rolled_date: _dropped, ...partial } = OVERVIEW;
    stubFetch(partial);

    await expect(fetchOverview()).rejects.toMatchObject({
      code: "UNEXPECTED_ERROR",
    });
  });

  it("throws UNEXPECTED_ERROR when business_counts is not an array", async () => {
    stubFetch({ ...OVERVIEW, business_counts: { metric_key: "x", count: 1 } });

    await expect(fetchOverview()).rejects.toMatchObject({
      code: "UNEXPECTED_ERROR",
    });
  });
});

describe("fetchCost", () => {
  it("resolves spend against budget for the current period", async () => {
    const fetchMock = stubFetch(COST);

    await expect(fetchCost()).resolves.toEqual(COST);
    expect(requestedUrl(fetchMock)).toBe(`${BASE}/cost`);
  });

  it("accepts a nullable period bound", async () => {
    stubFetch({
      ...COST,
      period_start: null,
      period_end: null,
      total_spend_paise: 0,
    });

    await expect(fetchCost()).resolves.toMatchObject({ period_start: null });
  });
});

describe("fetchCostTrend", () => {
  it("resolves the daily series and encodes the window", async () => {
    const fetchMock = stubFetch(COST_TREND);

    await expect(fetchCostTrend({ days: 7 })).resolves.toEqual(COST_TREND);
    expect(requestedUrl(fetchMock)).toBe(`${BASE}/cost/trend?days=7`);
  });

  it("rejects a point series that is not an array", async () => {
    stubFetch({ ...COST_TREND, points: null });

    await expect(fetchCostTrend()).rejects.toMatchObject({
      code: "UNEXPECTED_ERROR",
    });
  });
});

describe("fetchUsage", () => {
  it("resolves calls and tokens by provider scope", async () => {
    const fetchMock = stubFetch(USAGE);

    await expect(fetchUsage({ days: 14 })).resolves.toEqual(USAGE);
    expect(requestedUrl(fetchMock)).toBe(`${BASE}/usage?days=14`);
  });
});

describe("fetchQuality", () => {
  it("resolves success and low-confidence rates plus provider health", async () => {
    const fetchMock = stubFetch(QUALITY);

    await expect(fetchQuality()).resolves.toEqual(QUALITY);
    expect(requestedUrl(fetchMock)).toBe(`${BASE}/quality`);
  });

  it("accepts a null rate, which means an empty denominator not zero", async () => {
    stubFetch({ ...QUALITY, success_rate: null, low_confidence_rate: null });

    await expect(fetchQuality()).resolves.toMatchObject({ success_rate: null });
  });
});

describe("fetchLatency", () => {
  it("resolves per-provider percentiles", async () => {
    const fetchMock = stubFetch(LATENCY);

    await expect(fetchLatency()).resolves.toEqual(LATENCY);
    expect(requestedUrl(fetchMock)).toBe(`${BASE}/latency`);
  });
});

describe("fetchHealth", () => {
  it("resolves dependency, outbox and breaker state", async () => {
    const fetchMock = stubFetch(HEALTH);

    await expect(fetchHealth()).resolves.toEqual(HEALTH);
    expect(requestedUrl(fetchMock)).toBe(`${BASE}/health`);
  });

  it("rejects a dependency row missing its status", async () => {
    stubFetch({
      ...HEALTH,
      dependencies: [{ name: "database", latency_ms: 3.2, detail: null }],
    });

    await expect(fetchHealth()).rejects.toMatchObject({
      code: "UNEXPECTED_ERROR",
    });
  });
});

describe("fetchAlerts", () => {
  it("resolves one page of the feed with its total count", async () => {
    const fetchMock = stubFetch(ALERTS);

    await expect(fetchAlerts()).resolves.toEqual(ALERTS);
    expect(requestedUrl(fetchMock)).toBe(`${BASE}/alerts`);
  });

  it("encodes page, page_size and the status filter", async () => {
    const fetchMock = stubFetch(ALERTS);

    await fetchAlerts({ page: 2, page_size: 50, status: "open" });

    expect(requestedUrl(fetchMock)).toBe(
      `${BASE}/alerts?page=2&page_size=50&status=open`,
    );
  });

  it("rejects an alert entry missing its severity", async () => {
    stubFetch({
      alerts: [{ ...ALERTS.alerts[0], severity: undefined }],
      total_count: 1,
    });

    await expect(fetchAlerts()).rejects.toMatchObject({
      code: "UNEXPECTED_ERROR",
    });
  });
});

describe("fetchDeeplinks", () => {
  it("resolves the parameterised vendor link sets", async () => {
    const fetchMock = stubFetch(DEEPLINKS);

    await expect(fetchDeeplinks()).resolves.toEqual(DEEPLINKS);
    expect(requestedUrl(fetchMock)).toBe(`${BASE}/deeplinks`);
  });

  it("resolves an entirely unconfigured deployment as an empty object", async () => {
    // Every vendor key is ABSENT rather than null: the backend answers with
    // `exclude_none`, so there is no `null` here for a client to interpret as
    // "a link that goes nowhere".
    stubFetch(NO_VENDORS_CONFIGURED);

    await expect(fetchDeeplinks()).resolves.toEqual(NO_VENDORS_CONFIGURED);
  });

  it("passes a panel's context straight through as query params", async () => {
    const fetchMock = stubFetch(DEEPLINKS);

    await fetchDeeplinks({
      trace_id: "c7f2a1b0d3e4f5061728394a5b6c7d8e",
      model: "gpt-4o",
      task_type: "structure",
    });

    const url = new URL(requestedUrl(fetchMock)!, BASE_ORIGIN);
    expect(url.pathname).toBe("/v1/operator/observability/deeplinks");
    expect(Object.fromEntries(url.searchParams)).toEqual({
      trace_id: "c7f2a1b0d3e4f5061728394a5b6c7d8e",
      model: "gpt-4o",
      task_type: "structure",
    });
  });

  it("omits context a panel does not have, leaving the route's defaults in charge", async () => {
    const fetchMock = stubFetch(DEEPLINKS);

    await fetchDeeplinks({ model: "gpt-4o" });

    expect(requestedUrl(fetchMock)).toBe(`${BASE}/deeplinks?model=gpt-4o`);
  });

  it("refuses a body whose vendor group is not a link set", async () => {
    // The guard's whole job now that no vendor key is required: `{}` is a valid
    // all-off answer, but `{"grafana": 42}` is a contract mismatch and has to say so
    // rather than render a silently empty panel.
    stubFetch({ grafana: 42 });

    await expect(fetchDeeplinks()).rejects.toMatchObject({
      code: "UNEXPECTED_ERROR",
    });
  });

  it("refuses a vendor group that is missing a link it must have", async () => {
    stubFetch({ sentry: { project_id: "1" } });

    await expect(fetchDeeplinks()).rejects.toMatchObject({
      code: "UNEXPECTED_ERROR",
    });
  });

  it("refuses a null vendor, which the exclude-none wire can never send", async () => {
    stubFetch({ langfuse: null });

    await expect(fetchDeeplinks()).rejects.toMatchObject({
      code: "UNEXPECTED_ERROR",
    });
  });
});

/**
 * The business read as the DOMAIN model: every rate and unit cost a number,
 * every not-yet-measured figure a `null`. #731/#732 built it so the page never
 * has to know a `Decimal` crossed the wire.
 */
const BUSINESS: BusinessRead = {
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
      spend_paise: 125000,
      input_tokens: 100000,
      output_tokens: 40000,
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
      detail: "No revenue recorded yet.",
    },
    ai_cost_pct_of_revenue: {
      value: null,
      reason: "revenue_not_captured",
      detail: "No revenue recorded yet.",
    },
  },
};

describe("fetchBusiness", () => {
  it("resolves the spend, unit-cost and attribution read", async () => {
    const fetchMock = stubFetch(BUSINESS);

    await expect(fetchBusiness()).resolves.toEqual(BUSINESS);
    expect(requestedUrl(fetchMock)).toBe(`${BASE}/business`);
  });

  it("names the window it wants, and leaves the default to the route when none is asked for", async () => {
    const fetchMock = stubFetch(BUSINESS);

    await fetchBusiness({ period: "today" });

    expect(requestedUrl(fetchMock)).toBe(`${BASE}/business?period=today`);
  });

  it("rejects a read that is missing a breakdown it must have", async () => {
    stubFetch({ ...BUSINESS, by_provider: undefined });

    await expect(fetchBusiness()).rejects.toMatchObject({
      code: "UNEXPECTED_ERROR",
    });
  });

  it("rejects a provider row whose rate is not a number, rather than rendering NaN", async () => {
    stubFetch({
      ...BUSINESS,
      by_provider: [
        {
          ...BUSINESS.by_provider[0],
          paise_per_1k_input_tokens: "not-a-number",
        },
      ],
    });

    await expect(fetchBusiness()).rejects.toMatchObject({
      code: "UNEXPECTED_ERROR",
    });
  });
});

// #737: the business read carries NINE quoted decimals across four models -
// more than any read before it - and every one of them reaches a formatter on
// the Business page. The wire bodies below are exactly what `/business` emits.
describe("business decimal wire values", () => {
  const BUSINESS_WIRE = {
    ...BUSINESS,
    paise_per_1k_input_tokens: "90.0000",
    paise_per_1k_output_tokens: "300.0000",
    cap_consumed_pct: "25.00",
    cost_per_request_paise: "1041.6667",
    cost_per_completed_task_paise: "1096.4912",
    cost_per_patient_paise: "25000.0000",
    cost_per_doctor_paise: "41666.6667",
    cost_of_pass_paise: "1096.4912",
    by_provider: [
      {
        ...BUSINESS.by_provider[0],
        paise_per_1k_input_tokens: "90.0000",
        paise_per_1k_output_tokens: "300.0000",
      },
    ],
    by_model: [
      {
        ...BUSINESS.by_model[0],
        paise_per_1k_input_tokens: "90.0000",
        paise_per_1k_output_tokens: "300.0000",
      },
    ],
    by_task_type: [
      {
        ...BUSINESS.by_task_type[0],
        paise_per_1k_input_tokens: "90.0000",
        paise_per_1k_output_tokens: "300.0000",
      },
    ],
    patient_spend: {
      ...BUSINESS.patient_spend,
      median_spend_paise: "20000",
      p95_spend_paise: "56000",
    },
    doctor_spend: {
      ...BUSINESS.doctor_spend,
      median_spend_paise: "40000",
      p95_spend_paise: "80000",
    },
  };

  it("resolves the headline rates as numbers, not quoted strings", async () => {
    stubFetch(BUSINESS_WIRE);

    const read = await fetchBusiness();

    expect(typeof read.paise_per_1k_input_tokens).toBe("number");
    expect(read.paise_per_1k_input_tokens).toBe(90);
    expect(read.paise_per_1k_output_tokens).toBe(300);
    expect(read.cap_consumed_pct).toBe(25);
  });

  it("resolves every unit cost, which is what the page's headline figures are", async () => {
    stubFetch(BUSINESS_WIRE);

    const read = await fetchBusiness();

    expect(read.cost_per_request_paise).toBeCloseTo(1041.6667, 4);
    expect(read.cost_per_completed_task_paise).toBeCloseTo(1096.4912, 4);
    expect(read.cost_per_patient_paise).toBe(25000);
    expect(read.cost_per_doctor_paise).toBeCloseTo(41666.6667, 4);
    expect(read.cost_of_pass_paise).toBeCloseTo(1096.4912, 4);
  });

  it("resolves the per-token rates inside every breakdown row", async () => {
    stubFetch(BUSINESS_WIRE);

    const read = await fetchBusiness();

    for (const row of [
      read.by_provider[0],
      read.by_model[0],
      read.by_task_type[0],
    ]) {
      expect(typeof row.paise_per_1k_input_tokens).toBe("number");
      expect(row.paise_per_1k_input_tokens).toBe(90);
      expect(row.paise_per_1k_output_tokens).toBe(300);
    }
  });

  it("resolves the interpolated percentiles, which carry no fixed scale", async () => {
    stubFetch(BUSINESS_WIRE);

    const read = await fetchBusiness();

    // Rank interpolation emits "20000", not "20000.0000" - the guard has to take
    // the bare integer string too or the distribution panel never renders.
    expect(read.patient_spend.median_spend_paise).toBe(20000);
    expect(read.patient_spend.p95_spend_paise).toBe(56000);
    expect(read.doctor_spend.median_spend_paise).toBe(40000);
    expect(read.doctor_spend.p95_spend_paise).toBe(80000);
  });

  it("keeps an unmeasured unit cost null rather than coercing it to zero", async () => {
    // A patient with no recorded AI job divides by zero; "not yet measured" and
    // "free" are different facts and only the first one is true.
    stubFetch({
      ...BUSINESS_WIRE,
      cost_per_patient_paise: null,
      cost_per_doctor_paise: null,
      patient_spend: {
        ...BUSINESS.patient_spend,
        median_spend_paise: null,
        p95_spend_paise: null,
      },
    });

    const read = await fetchBusiness();

    expect(read.cost_per_patient_paise).toBeNull();
    expect(read.cost_per_doctor_paise).toBeNull();
    expect(read.patient_spend.median_spend_paise).toBeNull();
    expect(read.patient_spend.p95_spend_paise).toBeNull();
  });

  it("rejects a margin percentage that is neither a figure nor null", async () => {
    stubFetch({
      ...BUSINESS_WIRE,
      margin: {
        ...BUSINESS.margin,
        gross_margin: { value: "", reason: null, detail: null },
      },
    });

    await expect(fetchBusiness()).rejects.toMatchObject({
      code: "UNEXPECTED_ERROR",
    });
  });
});

describe("fetchActiveUsers", () => {
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

  const ACTIVE_USERS_WIRE = {
    ...ACTIVE_USERS,
    stickiness: "0.0833",
    requests_per_active_user: "20.00",
    trend: ACTIVE_USERS.trend.map((point) => ({
      ...point,
      requests_per_active_user: `${point.requests_per_active_user}`,
    })),
  };

  it("lets the route own its default window when none is asked for", async () => {
    const fetchMock = stubFetch(ACTIVE_USERS_WIRE);

    await fetchActiveUsers();

    expect(requestedUrl(fetchMock)).toBe(`${BASE}/product/active-users`);
  });

  it("sends the window it is given", async () => {
    const fetchMock = stubFetch(ACTIVE_USERS_WIRE);

    await fetchActiveUsers({ days: 7 });

    expect(requestedUrl(fetchMock)).toBe(`${BASE}/product/active-users?days=7`);
  });

  it("decodes stickiness, load per head and the nested daily figure", async () => {
    stubFetch(ACTIVE_USERS_WIRE);

    const read = await fetchActiveUsers();

    expect(read.stickiness).toBeCloseTo(0.0833, 5);
    expect(read.requests_per_active_user).toBe(20);
    expect(read.trend[0].requests_per_active_user).toBe(12);
    expect(read.monthly_active_users.total).toBe(120);
  });

  it("keeps an absent monthly base and a quiet actor set null, not zero", async () => {
    stubFetch({
      ...ACTIVE_USERS_WIRE,
      stickiness: null,
      requests_per_active_user: null,
      trend: [
        { ...ACTIVE_USERS_WIRE.trend[0], requests_per_active_user: null },
      ],
    });

    const read = await fetchActiveUsers();

    expect(read.stickiness).toBeNull();
    expect(read.requests_per_active_user).toBeNull();
    expect(read.trend[0].requests_per_active_user).toBeNull();
  });

  it("rejects a nested per-head figure that will not decode", async () => {
    stubFetch({
      ...ACTIVE_USERS_WIRE,
      trend: [
        { ...ACTIVE_USERS_WIRE.trend[0], requests_per_active_user: "nope" },
      ],
    });

    await expect(fetchActiveUsers()).rejects.toMatchObject({
      code: "UNEXPECTED_ERROR",
    });
  });
});

describe("fetchFunnel", () => {
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

  const FUNNEL_WIRE = {
    ...FUNNEL,
    steps: FUNNEL.steps.map((step) => ({
      ...step,
      conversion_from_previous:
        step.conversion_from_previous === null
          ? null
          : `${step.conversion_from_previous}`,
      median_gap_from_previous_s:
        step.median_gap_from_previous_s === null
          ? null
          : `${step.median_gap_from_previous_s}`,
    })),
    outcomes: {
      ...FUNNEL.outcomes,
      task_success_rate: "0.7200",
      abandonment_rate: "0.1000",
    },
  };

  it("lets the route own its default window and the whole funnel", async () => {
    const fetchMock = stubFetch(FUNNEL_WIRE);

    await fetchFunnel();

    expect(requestedUrl(fetchMock)).toBe(`${BASE}/product/funnel`);
  });

  it("sends the window and the outcome filter together", async () => {
    const fetchMock = stubFetch(FUNNEL_WIRE);

    await fetchFunnel({ days: 14, outcome: "abandoned" });

    expect(requestedUrl(fetchMock)).toBe(
      `${BASE}/product/funnel?days=14&outcome=abandoned`,
    );
  });

  it("decodes the step conversion and gap and both headline rates", async () => {
    stubFetch(FUNNEL_WIRE);

    const read = await fetchFunnel();

    expect(read.steps[1].conversion_from_previous).toBeCloseTo(0.8, 5);
    expect(read.steps[1].median_gap_from_previous_s).toBe(45);
    expect(read.outcomes.task_success_rate).toBeCloseTo(0.72, 5);
    expect(read.outcomes.abandonment_rate).toBeCloseTo(0.1, 5);
  });

  it("keeps the first step's absent conversion and unmeasured gap null", async () => {
    stubFetch(FUNNEL_WIRE);

    const read = await fetchFunnel();

    expect(read.steps[0].conversion_from_previous).toBeNull();
    expect(read.steps[0].median_gap_from_previous_s).toBeNull();
  });

  it("rejects a step gap that will not decode rather than rendering NaN", async () => {
    stubFetch({
      ...FUNNEL_WIRE,
      steps: [
        { ...FUNNEL_WIRE.steps[1], median_gap_from_previous_s: "a while" },
      ],
    });

    await expect(fetchFunnel()).rejects.toMatchObject({
      code: "UNEXPECTED_ERROR",
    });
  });
});

describe("fetchRetentionCohorts", () => {
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
      {
        cohort_date: "2026-10-11",
        cohort_size: 0,
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

  const RETENTION_WIRE = {
    ...RETENTION,
    cohorts: RETENTION.cohorts.map((cohort) => ({
      ...cohort,
      retention_7d:
        cohort.retention_7d === null ? null : `${cohort.retention_7d}`,
      retention_30d:
        cohort.retention_30d === null ? null : `${cohort.retention_30d}`,
    })),
  };

  it("lets the route own its sixty-date default", async () => {
    const fetchMock = stubFetch(RETENTION_WIRE);

    await fetchRetentionCohorts();

    expect(requestedUrl(fetchMock)).toBe(`${BASE}/product/retention-cohorts`);
  });

  it("sends the cohort-date window it is given", async () => {
    const fetchMock = stubFetch(RETENTION_WIRE);

    await fetchRetentionCohorts({ days: 7 });

    expect(requestedUrl(fetchMock)).toBe(
      `${BASE}/product/retention-cohorts?days=7`,
    );
  });

  it("decodes both horizons' rates beside their retained counts", async () => {
    stubFetch(RETENTION_WIRE);

    const read = await fetchRetentionCohorts();

    expect(read.cohorts[0].retention_7d).toBeCloseTo(0.3, 5);
    expect(read.cohorts[0].retention_30d).toBeCloseTo(0.15, 5);
    expect(read.cohorts[0].retained_30d).toBe(6);
  });

  it("keeps an unarrived horizon null, never zero", async () => {
    stubFetch(RETENTION_WIRE);

    const read = await fetchRetentionCohorts();

    expect(read.cohorts[1].retained_7d).toBeNull();
    expect(read.cohorts[1].retention_7d).toBeNull();
    expect(read.cohorts[1].retention_30d).toBeNull();
  });

  it("rejects a retention rate that will not decode", async () => {
    stubFetch({
      ...RETENTION_WIRE,
      cohorts: [{ ...RETENTION_WIRE.cohorts[0], retention_7d: "three tenths" }],
    });

    await expect(fetchRetentionCohorts()).rejects.toMatchObject({
      code: "UNEXPECTED_ERROR",
    });
  });
});

describe("shared transport", () => {
  it("throws NETWORK_ERROR when the API is unreachable", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("Failed to fetch")),
    );

    await expect(fetchOverview()).rejects.toMatchObject({
      code: "NETWORK_ERROR",
    });
  });

  it("surfaces the envelope code when the API refuses the caller", async () => {
    stubFetch(
      { code: "FORBIDDEN", message: "operator role required", trace_id: "t-1" },
      403,
    );

    await expect(fetchOverview()).rejects.toMatchObject({ code: "FORBIDDEN" });
  });
});

// The backend models every rate, utilization and latency as a Python `Decimal`,
// which pydantic's JSON encoder serialises as a STRING ("73.33"), not a number.
// These bodies are the wire shape the routes actually emit; the models above are
// the DOMAIN shape the console renders. A client that passes the wire body
// through unchecked hands a string to every formatter, and `formatPct` dies on
// `value.toFixed is not a function` - the /operator/observability/cost crash.
describe("decimal wire values", () => {
  const COST_WIRE = {
    ...COST,
    utilization_pct: "25.00",
    budgets: [
      {
        provider: "openai",
        model: "gpt-4o-mini",
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

  const OVERVIEW_WIRE = {
    ...OVERVIEW,
    success_rate: "95.00",
    low_confidence_rate: "2.60",
    p95_duration_ms: "4200.00",
    budget_utilization_pct: "25.00",
  };

  it("resolves cost utilizations as numbers the formatters can take", async () => {
    stubFetch(COST_WIRE);

    const summary = await fetchCost();

    expect(summary.utilization_pct).toBe(25);
    expect(summary.budgets[0].utilization_pct).toBeCloseTo(33.33, 2);
    expect(typeof summary.utilization_pct).toBe("number");
  });

  it("resolves overview rates and latencies as numbers", async () => {
    stubFetch(OVERVIEW_WIRE);

    const overview = await fetchOverview();

    expect(overview.success_rate).toBe(95);
    expect(overview.low_confidence_rate).toBeCloseTo(2.6, 5);
    expect(overview.p95_duration_ms).toBe(4200);
    expect(overview.budget_utilization_pct).toBe(25);
  });

  it("keeps an unmeasured rate null rather than coercing it to a number", async () => {
    stubFetch({ ...OVERVIEW_WIRE, success_rate: null, p95_duration_ms: null });

    const overview = await fetchOverview();

    expect(overview.success_rate).toBeNull();
    expect(overview.p95_duration_ms).toBeNull();
  });

  it("still accepts a decimal the wire sends as a bare JSON number", async () => {
    stubFetch({ ...COST_WIRE, utilization_pct: 25 });

    const summary = await fetchCost();

    expect(summary.utilization_pct).toBe(25);
  });

  it("rejects a decimal that is not a number rather than rendering NaN", async () => {
    stubFetch({ ...COST_WIRE, utilization_pct: "not-a-number" });

    await expect(fetchCost()).rejects.toMatchObject({
      code: "UNEXPECTED_ERROR",
    });
  });
});

// #738: the Reliability lens client reads. Four new GETs and the one write, and
// the same decimal contract as every other read here - the reliability page's
// rates all reach a formatter or a chart axis, so a quoted Decimal that is not
// decoded is a panel that does not render.
describe("fetchProviders", () => {
  const PROVIDERS: ProviderBoardReport = {
    last_rolled_date: "2026-10-11",
    providers: [
      {
        provider: "openai_compatible",
        status: "healthy",
        breaker_state: "closed",
        success_rate: 99.2,
        sample_count: 900,
        timeout_count: 0,
        rate_limit_count: 3,
        p50_duration_ms: 1200,
        p95_duration_ms: 4100,
        p99_duration_ms: 7000,
        last_error: null,
        window_start: "2026-10-05T00:00:00Z",
        window_end: "2026-10-11T23:59:59Z",
      },
      {
        provider: "sarvam",
        status: "degraded",
        breaker_state: "open",
        success_rate: 61.5,
        sample_count: 200,
        timeout_count: 40,
        rate_limit_count: 0,
        p50_duration_ms: 900,
        p95_duration_ms: 12000,
        p99_duration_ms: 30000,
        last_error: "rate_limit",
        window_start: "2026-10-05T00:00:00Z",
        window_end: "2026-10-11T23:59:59Z",
      },
    ],
  };

  const PROVIDERS_WIRE = {
    ...PROVIDERS,
    providers: PROVIDERS.providers.map((row) => ({
      ...row,
      success_rate: row.success_rate === null ? null : `${row.success_rate}`,
      p50_duration_ms: `${row.p50_duration_ms}`,
      p95_duration_ms: `${row.p95_duration_ms}`,
      p99_duration_ms: `${row.p99_duration_ms}`,
    })),
  };

  it("asks the board route with no window to invent", async () => {
    const fetchMock = stubFetch(PROVIDERS_WIRE);

    await fetchProviders();

    expect(requestedUrl(fetchMock)).toBe(`${BASE}/providers`);
  });

  it("decodes each row's quoted rates and percentiles", async () => {
    stubFetch(PROVIDERS_WIRE);

    const report = await fetchProviders();

    expect(report.providers[1].success_rate).toBeCloseTo(61.5, 5);
    expect(report.providers[1].p95_duration_ms).toBe(12000);
    expect(report.providers[1].status).toBe("degraded");
  });

  it("keeps an unsampled provider's rates null rather than zero", async () => {
    stubFetch({
      ...PROVIDERS_WIRE,
      providers: [
        {
          ...PROVIDERS_WIRE.providers[0],
          success_rate: null,
          p50_duration_ms: null,
          p95_duration_ms: null,
          p99_duration_ms: null,
        },
      ],
    });

    const report = await fetchProviders();

    expect(report.providers[0].success_rate).toBeNull();
    expect(report.providers[0].p99_duration_ms).toBeNull();
  });

  it("rejects a provider row whose rate is not a number", async () => {
    stubFetch({
      ...PROVIDERS_WIRE,
      providers: [{ ...PROVIDERS_WIRE.providers[0], success_rate: "NaN-ish" }],
    });

    await expect(fetchProviders()).rejects.toMatchObject({
      code: "UNEXPECTED_ERROR",
    });
  });
});

describe("fetchThroughput", () => {
  const THROUGHPUT: ThroughputReport = {
    minutes: 60,
    from_ts: "2026-10-12T10:00:00Z",
    to_ts: "2026-10-12T11:00:00Z",
    requests: 300,
    errors: 3,
    error_rate: 1,
    requests_per_minute: 5,
    points: [
      {
        minute_ts: "2026-10-12T10:00:00Z",
        requests: 10,
        errors: 0,
        error_rate: 0,
      },
      {
        minute_ts: "2026-10-12T10:01:00Z",
        requests: 8,
        errors: 3,
        error_rate: 37.5,
      },
    ],
    routes: [
      {
        route_template: "/v1/ai/draft",
        method: "POST",
        requests: 120,
        errors: 3,
        error_rate: 2.5,
      },
    ],
    routes_total: 34,
    capture: {
      capturing: true,
      requests_recorded: 300,
      last_recorded_at: "2026-10-12T10:59:00Z",
    },
  };

  const THROUGHPUT_WIRE = {
    ...THROUGHPUT,
    error_rate: "1.0000",
    requests_per_minute: "5.0000",
    points: THROUGHPUT.points.map((point) => ({
      ...point,
      error_rate: `${point.error_rate}`,
    })),
    routes: THROUGHPUT.routes.map((route) => ({
      ...route,
      error_rate: `${route.error_rate}`,
    })),
  };

  it("lets the route own its default window when none is asked for", async () => {
    const fetchMock = stubFetch(THROUGHPUT_WIRE);

    await fetchThroughput();

    expect(requestedUrl(fetchMock)).toBe(`${BASE}/throughput`);
  });

  it("sends the window it is given", async () => {
    const fetchMock = stubFetch(THROUGHPUT_WIRE);

    await fetchThroughput({ minutes: 15 });

    expect(requestedUrl(fetchMock)).toBe(`${BASE}/throughput?minutes=15`);
  });

  it("decodes the report's rate, its per-minute average and both nested rates", async () => {
    stubFetch(THROUGHPUT_WIRE);

    const report = await fetchThroughput();

    expect(report.error_rate).toBe(1);
    expect(report.requests_per_minute).toBe(5);
    expect(report.points[1].error_rate).toBeCloseTo(37.5, 5);
    expect(report.routes[0].error_rate).toBeCloseTo(2.5, 5);
  });

  it("keeps an unrecorded window's averages null rather than zero", async () => {
    stubFetch({
      ...THROUGHPUT_WIRE,
      requests: 0,
      errors: 0,
      error_rate: null,
      requests_per_minute: null,
      points: [],
    });

    const report = await fetchThroughput();

    expect(report.requests_per_minute).toBeNull();
    expect(report.error_rate).toBeNull();
    expect(report.capture.capturing).toBe(true);
  });

  it("rejects a nested point rate that will not decode", async () => {
    stubFetch({
      ...THROUGHPUT_WIRE,
      points: [{ ...THROUGHPUT_WIRE.points[0], error_rate: "one percent" }],
    });

    await expect(fetchThroughput()).rejects.toMatchObject({
      code: "UNEXPECTED_ERROR",
    });
  });
});

describe("fetchReliability", () => {
  const RELIABILITY: ReliabilityReport = {
    queues: [
      {
        queue: "draft",
        depth: 4,
        oldest_enqueued_at: "2026-10-12T10:30:00Z",
        oldest_age_s: 900,
      },
    ],
    queue_depth: 4,
    oldest_queued_age_s: 900,
    outbox: [
      {
        table_schema: "billing",
        table: "ai_usage_outbox",
        pending: 2,
        inflight: 0,
        dead_letter: 0,
        backlog: 2,
      },
    ],
    outbox_backlog: 2,
    dead_letter_rows: 0,
    recent_active_actors: 12,
    activity_window_minutes: 60,
    concurrency_grafana_link:
      "https://acme.grafana.net/explore?left=%7B%22queries%22%3A%5B%7B%22expr%22",
  };

  it("reads the queue report and keeps the concurrency gauge link whole", async () => {
    const fetchMock = stubFetch(RELIABILITY);

    const report = await fetchReliability();

    expect(requestedUrl(fetchMock)).toBe(`${BASE}/reliability`);
    expect(report.recent_active_actors).toBe(12);
    expect(report.oldest_queued_age_s).toBe(900);
    expect(report.concurrency_grafana_link).toBe(
      RELIABILITY.concurrency_grafana_link,
    );
  });

  it("sends the activity window when the caller narrows it", async () => {
    const fetchMock = stubFetch(RELIABILITY);

    await fetchReliability({ minutes: 5 });

    expect(requestedUrl(fetchMock)).toBe(`${BASE}/reliability?minutes=5`);
  });

  it("keeps a drained queue's oldest age null and an absent gauge null", async () => {
    stubFetch({
      ...RELIABILITY,
      queues: [],
      queue_depth: 0,
      oldest_queued_age_s: null,
      concurrency_grafana_link: null,
    });

    const report = await fetchReliability();

    expect(report.oldest_queued_age_s).toBeNull();
    expect(report.concurrency_grafana_link).toBeNull();
  });
});

describe("fetchErrors", () => {
  const ERRORS: ErrorFeedPage = {
    errors: [
      {
        fingerprint: "fp-1",
        route_template: "/v1/ai/draft",
        method: "POST",
        status_code: 500,
        status_class: "5xx",
        kind: "unhandled_exception",
        code: "ai_provider_timeout",
        trace_id: "trace-abc",
        occurrences: 42,
        first_seen_at: "2026-10-12T09:00:00Z",
        last_seen_at: "2026-10-12T10:55:00Z",
        status: "open",
      },
    ],
    total_count: 1,
    total_occurrences: 42,
    window_minutes: 60,
  };

  it("lets the route own its paging defaults", async () => {
    const fetchMock = stubFetch(ERRORS);

    await fetchErrors();

    expect(requestedUrl(fetchMock)).toBe(`${BASE}/errors`);
  });

  it("sends the page, the size, the status and the window together", async () => {
    const fetchMock = stubFetch(ERRORS);

    await fetchErrors({
      page: 3,
      page_size: 10,
      status: "resolved",
      minutes: 15,
    });

    expect(requestedUrl(fetchMock)).toBe(
      `${BASE}/errors?page=3&page_size=10&status=resolved&minutes=15`,
    );
  });

  it("keeps the occurrence total beside the row count", async () => {
    stubFetch(ERRORS);

    const page = await fetchErrors();

    expect(page.total_count).toBe(1);
    expect(page.total_occurrences).toBe(42);
    expect(page.errors[0].occurrences).toBe(42);
  });

  it("rejects a page missing the occurrence total", async () => {
    const { total_occurrences, ...withoutTotals } = ERRORS;

    stubFetch(withoutTotals);

    await expect(fetchErrors()).rejects.toMatchObject({
      code: "UNEXPECTED_ERROR",
    });
  });
});

describe("acknowledgeAlert", () => {
  const OPEN_ALERT: AlertPage["alerts"][number] = {
    id: "6f1c0f0e-0b1a-4a5e-9a1f-2b3c4d5e6f70",
    severity: "critical",
    kind: "breaker_open",
    title: "OpenAI circuit breaker is open",
    payload: { provider: "openai_compatible" },
    status: "open",
    created_at: "2026-10-12T10:00:00Z",
    acked_by: null,
    acked_at: null,
  };

  it("posts to the alert's acknowledge route with no body", async () => {
    const fetchMock = stubFetch({
      alert: { ...OPEN_ALERT, status: "acknowledged", acked_by: 42 },
      already_acknowledged: false,
    });

    await acknowledgeAlert(OPEN_ALERT.id);

    const [url, init] = fetchMock.mock.calls[0] as unknown as [
      string,
      RequestInit,
    ];
    expect(url).toBe(`${BASE}/alerts/${OPEN_ALERT.id}/acknowledge`);
    expect(init.method).toBe("POST");
    // No body: the route derives the acknowledging operator from the caller's
    // identity, and a body would let a client write its own status.
    expect(init.body).toBeUndefined();
  });

  it("carries an Idempotency-Key, and the caller's key across a retry", async () => {
    // A fresh Response per call: the shared `stubFetch` hands back one body, and
    // a second `.json()` on it throws before the key is ever compared.
    const fetchMock = vi
      .fn()
      .mockImplementation(() =>
        Promise.resolve(
          jsonResponse({ alert: OPEN_ALERT, already_acknowledged: false }),
        ),
      );
    vi.stubGlobal("fetch", fetchMock);

    await acknowledgeAlert(OPEN_ALERT.id, "retry-key-1");
    await acknowledgeAlert(OPEN_ALERT.id, "retry-key-1");

    // `authedFetch` rebuilds the headers as a `Headers` object, so that is what
    // a test reads - the key travels, but not as the plain object handed in.
    const first = new Headers(
      (fetchMock.mock.calls[0][1] as RequestInit).headers,
    );
    const second = new Headers(
      (fetchMock.mock.calls[1][1] as RequestInit).headers,
    );
    expect(first.get("Idempotency-Key")).toBe("retry-key-1");
    expect(second.get("Idempotency-Key")).toBe("retry-key-1");
  });

  it("mints a fresh Idempotency-Key for a new acknowledgement", async () => {
    const fetchMock = vi
      .fn()
      .mockImplementation(() =>
        Promise.resolve(
          jsonResponse({ alert: OPEN_ALERT, already_acknowledged: false }),
        ),
      );
    vi.stubGlobal("fetch", fetchMock);

    await acknowledgeAlert(OPEN_ALERT.id);
    await acknowledgeAlert(OPEN_ALERT.id);

    const first = new Headers(
      (fetchMock.mock.calls[0][1] as RequestInit).headers,
    ).get("Idempotency-Key");
    const second = new Headers(
      (fetchMock.mock.calls[1][1] as RequestInit).headers,
    ).get("Idempotency-Key");
    expect(first).not.toBe(second);
  });

  it("returns the idempotent repeat rather than treating it as a failure", async () => {
    stubFetch({
      alert: { ...OPEN_ALERT, status: "acknowledged", acked_by: 42 },
      already_acknowledged: true,
    });

    const result = await acknowledgeAlert(OPEN_ALERT.id);

    expect(result.already_acknowledged).toBe(true);
    expect(result.alert.status).toBe("acknowledged");
  });

  it("escapes the alert id into the path", async () => {
    const fetchMock = stubFetch({
      alert: OPEN_ALERT,
      already_acknowledged: false,
    });

    await acknowledgeAlert("id with/slash");

    expect(requestedUrl(fetchMock)).toBe(
      `${BASE}/alerts/id%20with%2Fslash/acknowledge`,
    );
  });
});
