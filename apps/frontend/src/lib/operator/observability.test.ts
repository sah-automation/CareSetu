// #708 C2a: operator observability HTTP client contract. Mirrors
// lib/operator/api.test.ts - each fetcher resolves the C1 response shape, sends
// the query params the route declares, and raises ApiError (NETWORK_ERROR on
// fetch failure, UNEXPECTED_ERROR on a body the guards reject) so a page can
// show one error path for every read.

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  fetchAlerts,
  fetchCost,
  fetchCostTrend,
  fetchDeeplinks,
  fetchHealth,
  fetchLatency,
  fetchOverview,
  fetchQuality,
  fetchUsage,
  type AlertPage,
  type CostSummary,
  type CostTrend,
  type Deeplinks,
  type LatencyReport,
  type Overview,
  type QualityReport,
  type SystemHealth,
  type UsageReport,
} from "./observability";

const BASE = "http://localhost:8000/v1/operator/observability";

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

const DEEPLINKS: Deeplinks = {
  grafana: "https://grafana.example/d/caresetu",
  sentry: null,
  langfuse: null,
};

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
  it("resolves the configured vendor links", async () => {
    const fetchMock = stubFetch(DEEPLINKS);

    await expect(fetchDeeplinks()).resolves.toEqual(DEEPLINKS);
    expect(requestedUrl(fetchMock)).toBe(`${BASE}/deeplinks`);
  });

  it("resolves an entirely unconfigured deployment", async () => {
    stubFetch({ grafana: null, sentry: null, langfuse: null });

    await expect(fetchDeeplinks()).resolves.toEqual({
      grafana: null,
      sentry: null,
      langfuse: null,
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
