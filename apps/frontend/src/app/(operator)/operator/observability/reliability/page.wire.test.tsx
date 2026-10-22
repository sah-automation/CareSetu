// #738: the operator Reliability lens page rendered against the REAL read client
// and the REAL wire body.
//
// page.test.tsx mocks `fetchProviders`, `fetchThroughput`, `fetchReliability`,
// `fetchErrors` and `acknowledgeAlert`, so it starts above the wire->model
// boundary and could never see a decoding fault. This file holds that boundary.
// For the reliability lens it is the widest one in the console: SIX quoted
// decimals across the provider board, the throughput report and every point
// and route row nested inside it, every one of which reaches a formatter or a
// chart axis on this page. pydantic serialises each backend `Decimal` as a
// STRING, so a client that passed the body straight through would hand
// `formatPct` a string and take the panel down with "value.toFixed is not a
// function".
//
// The stub comes from the shared helper (#737), the session is a real operator
// written through `saveSession`, and the transport is the only thing faked - so
// this is the one place the lens pages agree on what "over the wire" means.

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

import ObservabilityReliabilityPage from "./page";

/**
 * The provider board: every rate and percentile QUOTED, as pydantic emits them.
 *
 * The rates are FRACTIONS, which is the real contract and the one this file
 * exists to pin: the integration round trip asserts `success_rate == "0.8750"`
 * for a provider that is 87.5% healthy. A fixture written as `"87.50"` would
 * decode just as cleanly and render "87.5%" while proving nothing about the
 * scale the API actually sends - so these carry the scale, and `formatRate`
 * carries the conversion.
 */
const PROVIDERS_WIRE = {
  last_rolled_date: "2026-10-12",
  providers: [
    {
      provider: "openai_compatible",
      status: "healthy",
      breaker_state: "closed",
      success_rate: "0.9920",
      sample_count: 900,
      timeout_count: 2,
      rate_limit_count: 0,
      p50_duration_ms: "1200.00",
      p95_duration_ms: "4100.00",
      p99_duration_ms: "7000.00",
      last_error: null,
      window_start: "2026-10-06T00:00:00Z",
      window_end: "2026-10-12T23:59:59Z",
    },
    {
      provider: "sarvam",
      status: "degraded",
      breaker_state: "open",
      success_rate: "0.6150",
      sample_count: 200,
      timeout_count: 40,
      rate_limit_count: 12,
      p50_duration_ms: "900.00",
      p95_duration_ms: "12000.00",
      p99_duration_ms: "30000.00",
      last_error: "rate_limit",
      window_start: "2026-10-06T00:00:00Z",
      window_end: "2026-10-12T23:59:59Z",
    },
  ],
};

/** The throughput report: two quoted rates, plus one per nested point and row. */
const THROUGHPUT_WIRE = {
  minutes: 60,
  from_ts: "2026-10-12T10:00:00Z",
  to_ts: "2026-10-12T11:00:00Z",
  requests: 300,
  errors: 3,
  error_rate: "0.0100",
  requests_per_minute: "5.0000",
  points: [
    {
      minute_ts: "2026-10-12T10:00:00Z",
      requests: 10,
      errors: 1,
      error_rate: "0.1000",
    },
    {
      minute_ts: "2026-10-12T10:01:00Z",
      requests: 8,
      errors: 2,
      error_rate: "0.2500",
    },
  ],
  routes: [
    {
      route_template: "/v1/ai/draft",
      method: "POST",
      requests: 120,
      errors: 3,
      error_rate: "0.0250",
    },
  ],
  routes_total: 34,
  capture: {
    capturing: true,
    requests_recorded: 300,
    last_recorded_at: "2026-10-12T10:59:00Z",
  },
};

/** The queue read carries no decimals - every figure is an observed integer. */
const RELIABILITY_WIRE = {
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
  outbox: [],
  outbox_backlog: 0,
  dead_letter_rows: 0,
  recent_active_actors: 12,
  activity_window_minutes: 60,
  concurrency_grafana_link:
    "https://acme.grafana.net/explore?left=%7B%22queries",
};

const ERRORS_WIRE = {
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

const ALERTS_WIRE = {
  alerts: [
    {
      id: "alert-1",
      severity: "critical",
      kind: "breaker_open",
      title: "OpenAI circuit breaker is open",
      payload: {},
      status: "open",
      created_at: "2026-10-12T10:00:00Z",
      acked_by: null,
      acked_at: null,
    },
  ],
  total_count: 1,
};

/** One configured vendor; the other two are ABSENT, as `exclude_none` sends them. */
const DEEPLINKS_WIRE = {
  sentry: {
    project_id: "4509",
    issues_url:
      "https://sentry.io/organizations/acme/issues/?query=service%3A%22caresetu-api%22",
    trace_url: "https://sentry.io/organizations/acme/traces/trace-abc/",
  },
};

function stubReliabilityWire(overrides: Record<string, unknown> = {}) {
  return stubRouteWire({
    "/observability/providers": PROVIDERS_WIRE,
    "/observability/throughput": THROUGHPUT_WIRE,
    "/observability/reliability": RELIABILITY_WIRE,
    "/observability/errors": ERRORS_WIRE,
    "/observability/alerts": ALERTS_WIRE,
    "/observability/deeplinks": DEEPLINKS_WIRE,
    ...overrides,
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

describe("ObservabilityReliabilityPage over the real wire", () => {
  it("renders the provider board's fractions as percentages", async () => {
    stubReliabilityWire();

    render(<ObservabilityReliabilityPage />);

    // `"0.6150"` is 61.5% of calls succeeding. Printed as a percentage-scale
    // figure it would read "0.6%", which is the opposite of the fact.
    await waitFor(() => {
      expect(
        screen.getByTestId("reliability-provider-sarvam").textContent,
      ).toContain("61.5%");
    });
    expect(
      screen.getByTestId("reliability-provider-sarvam").textContent,
    ).toContain("12s");
  });

  it("renders the throughput panel from quoted rates inside every nested row", async () => {
    stubReliabilityWire();

    render(<ObservabilityReliabilityPage />);

    await waitFor(() => {
      expect(
        screen.getByTestId("reliability-throughput-takeaway").textContent,
      ).toBe(
        "5 req/min · 300 requests · 3 errors · 1% error rate · last 60 minutes",
      );
    });
    expect(screen.queryByText(/NaN/)).toBeNull();
  });

  it("shows the error path rather than a NaN figure when a nested rate drifts", async () => {
    stubReliabilityWire({
      "/observability/throughput": {
        ...THROUGHPUT_WIRE,
        points: [{ ...THROUGHPUT_WIRE.points[0], error_rate: "not-a-number" }],
      },
    });

    render(<ObservabilityReliabilityPage />);

    await waitFor(() => {
      expect(screen.getByTestId("reliability-throughput-error")).toBeTruthy();
    });
    expect(screen.queryByText(/NaN/)).toBeNull();
  });

  it("sends the operator's bearer and asks for each route's own defaults", async () => {
    const fetchMock = stubReliabilityWire();

    render(<ObservabilityReliabilityPage />);

    await waitFor(() => {
      expect(
        screen.getByTestId("reliability-throughput-takeaway"),
      ).toBeTruthy();
    });

    // A real session, so the Authorization header went out and the reads were not
    // rejected for want of one.
    const first = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    const headers = new Headers(first[1].headers);
    expect(headers.get("Authorization")).toBe("Bearer operator.jwt.value");
    // No invented windows: each route's own default is the one authority.
    const asked = requestedUrls(fetchMock);
    expect(asked).toContain(
      "http://localhost:8000/v1/operator/observability/providers",
    );
    expect(asked).toContain(
      "http://localhost:8000/v1/operator/observability/throughput",
    );
    expect(asked).toContain(
      "http://localhost:8000/v1/operator/observability/reliability",
    );
  });

  it("filters and pages the error feed through real query strings", async () => {
    const fetchMock = stubReliabilityWire();

    render(<ObservabilityReliabilityPage />);

    await waitFor(() => {
      expect(screen.getByTestId("reliability-error-fp-1")).toBeTruthy();
    });
    // The open filter is the first question asked, and it is asked explicitly.
    expect(requestedUrls(fetchMock)).toContain(
      "http://localhost:8000/v1/operator/observability/errors?page=1&page_size=25&status=open",
    );

    fireEvent.click(screen.getByTestId("reliability-error-filter-resolved"));

    await waitFor(() => {
      expect(requestedUrls(fetchMock)).toContain(
        "http://localhost:8000/v1/operator/observability/errors?page=1&page_size=25&status=resolved",
      );
    });
  });

  it("scopes the feed's deep links to the newest failure's trace and code", async () => {
    const fetchMock = stubReliabilityWire();

    render(<ObservabilityReliabilityPage />);

    await waitFor(() => {
      expect(
        screen.getByTestId("reliability-error-deeplink-sentry.trace_url"),
      ).toBeTruthy();
    });
    const asked = requestedUrls(fetchMock);
    expect(
      asked.some((url) =>
        url.includes(
          "deeplinks?trace_id=trace-abc&error_type=ai_provider_timeout",
        ),
      ),
    ).toBe(true);
  });

  it("renders the configured vendor's links and omits the ones it has no filter for", async () => {
    stubReliabilityWire();

    render(<ObservabilityReliabilityPage />);

    await waitFor(() => {
      expect(
        screen.getByTestId("observability-deeplink-sentry.issues_url"),
      ).toBeTruthy();
    });
    // Grafana and Langfuse are absent from this body, so no link is rendered for
    // them - not a disabled placeholder pointing at a dashboard that would open
    // empty.
    expect(
      screen.queryByTestId("observability-deeplink-grafana.dashboard_url"),
    ).toBeNull();
    expect(
      screen.queryByTestId("observability-deeplink-langfuse.traces_url"),
    ).toBeNull();
  });

  it("acknowledges over the real wire and re-reads the open list", async () => {
    let alertReads = 0;
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const path = String(input);
      if (path.endsWith("/acknowledge")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              alert: {
                ...ALERTS_WIRE.alerts[0],
                status: "acknowledged",
                acked_by: 42,
              },
              already_acknowledged: false,
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          ),
        );
      }
      if (path.includes("/observability/alerts")) {
        alertReads += 1;
        return Promise.resolve(
          new Response(
            JSON.stringify(
              alertReads === 1 ? ALERTS_WIRE : { alerts: [], total_count: 0 },
            ),
            { status: 200, headers: { "Content-Type": "application/json" } },
          ),
        );
      }
      if (path.endsWith("/observability/errors")) {
        return Promise.resolve(
          new Response(JSON.stringify(ERRORS_WIRE), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      if (path.endsWith("/observability/providers")) {
        return Promise.resolve(
          new Response(JSON.stringify(PROVIDERS_WIRE), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      if (path.endsWith("/observability/throughput")) {
        return Promise.resolve(
          new Response(JSON.stringify(THROUGHPUT_WIRE), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      if (path.endsWith("/observability/reliability")) {
        return Promise.resolve(
          new Response(JSON.stringify(RELIABILITY_WIRE), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      return Promise.resolve(
        new Response(JSON.stringify(DEEPLINKS_WIRE), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ObservabilityReliabilityPage />);

    fireEvent.click(
      await screen.findByTestId("observability-alert-alert-1-acknowledge"),
    );

    await waitFor(() => {
      expect(screen.queryByTestId("observability-alert-alert-1")).toBeNull();
    });
    const write = fetchMock.mock.calls.find((call) =>
      String(call[0]).endsWith("/acknowledge"),
    ) as unknown as [string, RequestInit];
    expect(write[0]).toBe(
      "http://localhost:8000/v1/operator/observability/alerts/alert-1/acknowledge",
    );
    expect(write[1].method).toBe("POST");
    expect(new Headers(write[1].headers).get("Idempotency-Key")).toBeTruthy();
  });

  it("keeps the panels that read other routes working when one read fails", async () => {
    stubFailingRoute("/observability/throughput", {
      "/observability/providers": PROVIDERS_WIRE,
      "/observability/reliability": RELIABILITY_WIRE,
      "/observability/errors": ERRORS_WIRE,
      "/observability/alerts": ALERTS_WIRE,
      "/observability/deeplinks": DEEPLINKS_WIRE,
    });

    render(<ObservabilityReliabilityPage />);

    await waitFor(() => {
      expect(screen.getByTestId("reliability-throughput-error")).toBeTruthy();
    });
    expect(screen.getByTestId("reliability-throughput-retry")).toBeTruthy();
    // The provider board is a different route and kept working.
    expect(screen.getByTestId("reliability-provider-sarvam")).toBeTruthy();
    // And so did the queue panels, which share the OTHER read.
    expect(screen.getByTestId("reliability-queue-draft")).toBeTruthy();
  });
});
