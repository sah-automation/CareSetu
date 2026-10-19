// #738: the operator Reliability lens page. Mocks the client at the
// lib/operator/observability seam and covers the states every panel owes an
// operator: loading, populated, empty, error and retry - by test id, exactly as
// the other panel pages do.
//
// page.wire.test.tsx holds the boundary below this one. This file starts ABOVE
// the wire->model boundary, so it can prove the page renders, distinguishes and
// recovers from each state, pages and filters the feeds, and moves an
// acknowledged alert out of the open list - and could never have caught a
// client that decoded a quoted Decimal wrong.

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
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
  acknowledgeAlert,
  fetchAlerts,
  fetchDeeplinks,
  fetchErrors,
  fetchProviders,
  fetchReliability,
  fetchThroughput,
  type AlertPage,
  type Deeplinks,
  type ErrorFeedPage,
  type ProviderBoardReport,
  type ReliabilityReport,
  type ThroughputReport,
} from "@/lib/operator/observability";
import { DASH } from "@/lib/operator/observability-format";
import { useChartDom, drawnChart } from "@/test/chartDom";

import ObservabilityReliabilityPage from "./page";

vi.mock("@/lib/operator/observability", async (importOriginal) => {
  const mod =
    await importOriginal<typeof import("@/lib/operator/observability")>();
  return {
    ...mod,
    acknowledgeAlert: vi.fn(),
    fetchAlerts: vi.fn(),
    fetchDeeplinks: vi.fn(),
    fetchErrors: vi.fn(),
    fetchProviders: vi.fn(),
    fetchReliability: vi.fn(),
    fetchThroughput: vi.fn(),
  };
});

const mockAcknowledge = vi.mocked(acknowledgeAlert);
const mockFetchAlerts = vi.mocked(fetchAlerts);
const mockFetchDeeplinks = vi.mocked(fetchDeeplinks);
const mockFetchErrors = vi.mocked(fetchErrors);
const mockFetchProviders = vi.mocked(fetchProviders);
const mockFetchReliability = vi.mocked(fetchReliability);
const mockFetchThroughput = vi.mocked(fetchThroughput);

const PROVIDERS: ProviderBoardReport = {
  last_rolled_date: "2026-10-12",
  providers: [
    {
      provider: "openai_compatible",
      status: "healthy",
      breaker_state: "closed",
      success_rate: 0.992,
      sample_count: 900,
      timeout_count: 2,
      rate_limit_count: 0,
      p50_duration_ms: 1200,
      p95_duration_ms: 4100,
      p99_duration_ms: 7000,
      last_error: null,
      window_start: "2026-10-06T00:00:00Z",
      window_end: "2026-10-12T23:59:59Z",
    },
    {
      provider: "sarvam",
      status: "degraded",
      breaker_state: "open",
      success_rate: 0.615,
      sample_count: 200,
      timeout_count: 40,
      rate_limit_count: 12,
      p50_duration_ms: 900,
      p95_duration_ms: 12000,
      p99_duration_ms: 30000,
      last_error: "rate_limit",
      window_start: "2026-10-06T00:00:00Z",
      window_end: "2026-10-12T23:59:59Z",
    },
  ],
};

const THROUGHPUT: ThroughputReport = {
  minutes: 60,
  from_ts: "2026-10-12T10:00:00Z",
  to_ts: "2026-10-12T11:00:00Z",
  requests: 300,
  errors: 3,
  error_rate: 0.01,
  requests_per_minute: 5,
  points: [
    {
      minute_ts: "2026-10-12T10:00:00Z",
      requests: 10,
      errors: 1,
      error_rate: 0.1,
    },
    {
      minute_ts: "2026-10-12T10:01:00Z",
      requests: 8,
      errors: 3,
      error_rate: 0.375,
    },
  ],
  routes: [
    {
      route_template: "/v1/ai/draft",
      method: "POST",
      requests: 120,
      errors: 3,
      error_rate: 0.025,
    },
  ],
  routes_total: 34,
  capture: {
    capturing: true,
    requests_recorded: 300,
    last_recorded_at: "2026-10-12T10:59:00Z",
  },
};

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
  outbox: [],
  outbox_backlog: 0,
  dead_letter_rows: 0,
  recent_active_actors: 12,
  activity_window_minutes: 60,
  concurrency_grafana_link:
    "https://acme.grafana.net/explore?left=%7B%22queries",
};

/** One collapsed failure repeated 42 times - the collapse under test. */
function errorPage(overrides: Partial<ErrorFeedPage> = {}): ErrorFeedPage {
  return {
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
    ...overrides,
  };
}

function alertPage(overrides: Partial<AlertPage> = {}): AlertPage {
  return {
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
    ...overrides,
  };
}

const LINKS: Deeplinks = {
  grafana: {
    dashboard_uid: "caresetu-observability",
    dashboard_url: "https://acme.grafana.net/d/caresetu-observability",
  },
};

beforeAll(() => useChartDom());

beforeEach(() => {
  mockFetchProviders.mockImplementation(() => Promise.resolve(PROVIDERS));
  mockFetchThroughput.mockImplementation(() => Promise.resolve(THROUGHPUT));
  mockFetchReliability.mockImplementation(() => Promise.resolve(RELIABILITY));
  mockFetchErrors.mockImplementation(() => Promise.resolve(errorPage()));
  mockFetchAlerts.mockImplementation(() => Promise.resolve(alertPage()));
  mockFetchDeeplinks.mockImplementation(() => Promise.resolve(LINKS));
  mockAcknowledge.mockImplementation((alertId) =>
    Promise.resolve({
      alert: {
        ...alertPage().alerts[0],
        id: alertId,
        status: "acknowledged",
        acked_by: 42,
        acked_at: "2026-10-12T10:30:00Z",
      },
      already_acknowledged: false,
    }),
  );
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

/** The five panels the page always renders, plus the shared alert panel. */
const PANELS = [
  "reliability-providers",
  "reliability-error-feed",
  "reliability-throughput",
  "reliability-queues",
  "reliability-concurrency",
  "observability-alerts",
];

describe("ObservabilityReliabilityPage", () => {
  it("shows a loading skeleton for every panel while the reads are in flight", () => {
    // Five reads, none of which settles: every panel must show its skeleton.
    mockFetchProviders.mockImplementation(() => new Promise(() => {}));
    mockFetchThroughput.mockImplementation(() => new Promise(() => {}));
    mockFetchReliability.mockImplementation(() => new Promise(() => {}));
    mockFetchErrors.mockImplementation(() => new Promise(() => {}));
    mockFetchAlerts.mockImplementation(() => new Promise(() => {}));

    render(<ObservabilityReliabilityPage />);

    for (const panel of PANELS) {
      expect(screen.getByTestId(`${panel}-loading`)).toBeTruthy();
    }
  });

  it("names each provider's status, its failures and its newest failure reason", async () => {
    render(<ObservabilityReliabilityPage />);

    await waitFor(() => {
      expect(
        screen.getByTestId("reliability-providers-takeaway").textContent,
      ).toBe("1 healthy · 1 degraded · as of the 2026-10-12 roll");
    });
    expect(
      screen.getByTestId("reliability-provider-sarvam-status").textContent,
    ).toBe("degraded");
    expect(
      screen.getByTestId("reliability-provider-sarvam").textContent,
    ).toContain("rate_limit");
    // The board is a snapshot, and says so rather than reading as live.
    expect(
      screen.getByTestId("reliability-providers-window").textContent,
    ).toContain("as of the 2026-10-12 roll");
  });

  it("renders the board's fractions as percentages, not as tenths", async () => {
    render(<ObservabilityReliabilityPage />);

    // `success_rate` is 0.615 - 61.5% of calls succeeding. A percentage-scale
    // formatter would report "0.6%", which is the opposite of the fact.
    await waitFor(() => {
      expect(
        screen.getByTestId("reliability-provider-sarvam").textContent,
      ).toContain("61.5%");
    });
  });

  it("shows the breaker state beside the status it derives", async () => {
    render(<ObservabilityReliabilityPage />);

    await waitFor(() => {
      expect(
        screen.getByTestId("reliability-provider-sarvam-breaker").textContent,
      ).toBe("open");
    });
    expect(
      screen.getByTestId("reliability-provider-openai_compatible-breaker")
        .textContent,
    ).toBe("closed");
  });

  it("shows p50, p95 and p99 so a slow provider is distinguishable from a refusing one", async () => {
    render(<ObservabilityReliabilityPage />);

    await waitFor(() => {
      const row = screen.getByTestId("reliability-provider-sarvam").textContent;
      expect(row).toContain("900ms");
      expect(row).toContain("12s");
      expect(row).toContain("30s");
    });
  });

  it("says a healthy provider recorded no failure rather than printing nothing", async () => {
    render(<ObservabilityReliabilityPage />);

    await waitFor(() => {
      expect(
        screen.getByTestId("reliability-provider-openai_compatible")
          .textContent,
      ).toContain("none in this window");
    });
  });

  it("prints an unsampled provider's success rate as a dash, not a zero", async () => {
    mockFetchProviders.mockImplementation(() =>
      Promise.resolve({
        ...PROVIDERS,
        providers: [{ ...PROVIDERS.providers[0], success_rate: null }],
      }),
    );

    render(<ObservabilityReliabilityPage />);

    await waitFor(() => {
      expect(
        screen.getByTestId("reliability-provider-openai_compatible")
          .textContent,
      ).toContain(DASH);
    });
  });

  it("says no provider telemetry rather than an empty board", async () => {
    mockFetchProviders.mockImplementation(() =>
      Promise.resolve({ ...PROVIDERS, providers: [] }),
    );

    render(<ObservabilityReliabilityPage />);

    await waitFor(() => {
      expect(screen.getByTestId("empty-state-title").textContent).toBe(
        "No provider telemetry yet",
      );
    });
  });

  it("collapses repeats with their occurrence count beside the distinct total", async () => {
    render(<ObservabilityReliabilityPage />);

    await waitFor(() => {
      expect(
        screen.getByTestId("reliability-error-feed-takeaway").textContent,
      ).toBe("1 distinct failure · 42 occurrences · last 60 minutes");
    });
    // One row, not forty-two: the feed is already collapsed server-side.
    expect(screen.getAllByTestId(/^reliability-error-fp-\d+$/)).toHaveLength(1);
    expect(
      screen.getByTestId("reliability-error-fp-1-occurrences").textContent,
    ).toBe("42×");
  });

  it("pages the feed and asks for the page it is on", async () => {
    mockFetchErrors.mockImplementation((params) =>
      Promise.resolve(
        params?.page === 2
          ? errorPage({
              errors: [
                {
                  ...errorPage().errors[0],
                  fingerprint: "fp-2",
                  status: "resolved",
                },
              ],
              total_count: 30,
            })
          : errorPage({ total_count: 30 }),
      ),
    );

    render(<ObservabilityReliabilityPage />);

    await waitFor(() => {
      expect(screen.getByTestId("reliability-error-next")).not.toBeDisabled();
    });
    fireEvent.click(screen.getByTestId("reliability-error-next"));

    await waitFor(() => {
      expect(screen.getByTestId("reliability-error-fp-2")).toBeTruthy();
    });
    expect(mockFetchErrors).toHaveBeenLastCalledWith(
      expect.objectContaining({ page: 2, status: "open" }),
    );
    expect(screen.getByTestId("reliability-error-page").textContent).toBe("2");
  });

  it("will not page before the first page", async () => {
    render(<ObservabilityReliabilityPage />);

    await waitFor(() => {
      expect(screen.getByTestId("reliability-error-prev")).toBeDisabled();
    });
  });

  it("filters the feed by open and resolved, asking the read for the slice", async () => {
    mockFetchErrors.mockImplementation((params) =>
      Promise.resolve(
        params?.status === "resolved"
          ? errorPage({
              errors: [
                {
                  ...errorPage().errors[0],
                  fingerprint: "fp-resolved",
                  status: "resolved",
                },
              ],
              total_count: 4,
            })
          : errorPage(),
      ),
    );

    render(<ObservabilityReliabilityPage />);

    await waitFor(() => {
      expect(screen.getByTestId("reliability-error-fp-1")).toBeTruthy();
    });
    fireEvent.click(screen.getByTestId("reliability-error-filter-resolved"));

    await waitFor(() => {
      expect(mockFetchErrors).toHaveBeenLastCalledWith(
        expect.objectContaining({ status: "resolved" }),
      );
    });
    expect(screen.getByTestId("reliability-error-fp-resolved")).toBeTruthy();
    expect(screen.queryByTestId("reliability-error-fp-1")).toBeNull();
  });

  it("returns to the first page when the filter changes", async () => {
    mockFetchErrors.mockImplementation((params) =>
      Promise.resolve(errorPage({ total_count: 30 })),
    );

    render(<ObservabilityReliabilityPage />);

    await waitFor(() => {
      expect(screen.getByTestId("reliability-error-next")).not.toBeDisabled();
    });
    fireEvent.click(screen.getByTestId("reliability-error-next"));
    await waitFor(() => {
      expect(screen.getByTestId("reliability-error-page").textContent).toBe(
        "2",
      );
    });

    fireEvent.click(screen.getByTestId("reliability-error-filter-resolved"));

    await waitFor(() => {
      expect(screen.getByTestId("reliability-error-page").textContent).toBe(
        "1",
      );
    });
  });

  it("scopes the feed's deep links to the newest failure it is showing", async () => {
    render(<ObservabilityReliabilityPage />);

    await waitFor(() => {
      expect(mockFetchDeeplinks).toHaveBeenCalledWith({
        trace_id: "trace-abc",
        error_type: "ai_provider_timeout",
      });
    });
    expect(screen.getByTestId("reliability-error-deeplinks")).toBeTruthy();
  });

  it("renders no scoped link panel at all when there is no failure to point at", async () => {
    mockFetchErrors.mockImplementation(() =>
      Promise.resolve(errorPage({ errors: [], total_count: 0 })),
    );

    render(<ObservabilityReliabilityPage />);

    await waitFor(() => {
      expect(screen.getByTestId("empty-state-title")).toBeTruthy();
    });
    // Absent, not a panel of links that go nowhere.
    expect(screen.queryByTestId("reliability-error-deeplinks")).toBeNull();
  });

  it("says the error feed is quiet, and says the recorder was watching", async () => {
    mockFetchErrors.mockImplementation(() =>
      Promise.resolve(errorPage({ errors: [], total_count: 0 })),
    );

    render(<ObservabilityReliabilityPage />);

    await waitFor(() => {
      expect(
        screen.getByTestId("reliability-error-feed").textContent,
      ).toContain("recorder is running");
    });
  });

  it("will not let an empty feed read as a healthy system when the recorder is off", async () => {
    mockFetchErrors.mockImplementation(() =>
      Promise.resolve(errorPage({ errors: [], total_count: 0 })),
    );
    mockFetchThroughput.mockImplementation(() =>
      Promise.resolve({
        ...THROUGHPUT,
        requests: 0,
        errors: 0,
        error_rate: null,
        requests_per_minute: null,
        points: [],
        capture: { ...THROUGHPUT.capture, capturing: false },
      }),
    );

    render(<ObservabilityReliabilityPage />);

    await waitFor(() => {
      expect(
        screen.getByTestId("reliability-error-feed").textContent,
      ).toContain("nothing failing");
    });
  });

  it("keeps the status filter reachable while a slice is empty", async () => {
    mockFetchErrors.mockImplementation(() =>
      Promise.resolve(errorPage({ errors: [], total_count: 0 })),
    );

    render(<ObservabilityReliabilityPage />);

    await waitFor(() => {
      expect(screen.getByTestId("empty-state-title").textContent).toBe(
        "No captured failures",
      );
    });
    // The empty state is exactly when an operator wants to switch slices, so the
    // filter must not live inside the body it replaces.
    expect(screen.getByTestId("reliability-error-filter")).toBeTruthy();
    fireEvent.click(screen.getByTestId("reliability-error-filter-resolved"));

    await waitFor(() => {
      expect(mockFetchErrors).toHaveBeenLastCalledWith(
        expect.objectContaining({ status: "resolved" }),
      );
    });
  });

  it("renders throughput as a request rate, an error count and an error rate", async () => {
    render(<ObservabilityReliabilityPage />);

    await waitFor(() => {
      expect(
        screen.getByTestId("reliability-throughput-takeaway").textContent,
      ).toBe(
        "5 req/min · 300 requests · 3 errors · 1% error rate · last 60 minutes",
      );
    });
    expect(
      screen.getByTestId("reliability-throughput-window").textContent,
    ).toBe("2026-10-12T10:00:00Z to 2026-10-12T11:00:00Z");
  });

  it("draws one request bar and one error bar per captured minute", async () => {
    render(<ObservabilityReliabilityPage />);

    const chart = await drawnChart("reliability-throughput-chart");
    // Two minutes with traffic, two series each.
    expect(chart.querySelectorAll(".recharts-bar-rectangle").length).toBe(4);
  });

  it("distinguishes a switched-off recorder from a quiet window", async () => {
    mockFetchThroughput.mockImplementation(() =>
      Promise.resolve({
        ...THROUGHPUT,
        requests: 0,
        errors: 0,
        error_rate: null,
        requests_per_minute: null,
        points: [],
        capture: { ...THROUGHPUT.capture, capturing: false },
      }),
    );

    render(<ObservabilityReliabilityPage />);

    await waitFor(() => {
      expect(screen.getByTestId("empty-state-title").textContent).toBe(
        "The request recorder is off",
      );
    });
    expect(screen.getByTestId("empty-state").textContent).toContain(
      "switched off",
    );
  });

  it("says no traffic rather than a clean window when nothing was captured", async () => {
    mockFetchThroughput.mockImplementation(() =>
      Promise.resolve({
        ...THROUGHPUT,
        requests: 0,
        errors: 0,
        error_rate: null,
        requests_per_minute: null,
        points: [],
      }),
    );

    render(<ObservabilityReliabilityPage />);

    await waitFor(() => {
      expect(screen.getByTestId("empty-state-title").textContent).toBe(
        "No traffic captured",
      );
    });
  });

  it("prints the queue depth beside the age of the oldest waiting job", async () => {
    render(<ObservabilityReliabilityPage />);

    await waitFor(() => {
      expect(
        screen.getByTestId("reliability-queues-takeaway").textContent,
      ).toBe(
        "4 queued · oldest waiting 900s · 0 in the outbox · 0 dead-lettered",
      );
    });
    expect(screen.getByTestId("reliability-queue-draft").textContent).toContain(
      "2026-10-12T10:30:00Z",
    );
  });

  it("says nothing queued rather than an age of zero", async () => {
    mockFetchReliability.mockImplementation(() =>
      Promise.resolve({
        ...RELIABILITY,
        queues: [],
        queue_depth: 0,
        oldest_queued_age_s: null,
      }),
    );

    render(<ObservabilityReliabilityPage />);

    await waitFor(() => {
      expect(screen.getByTestId("empty-state-title").textContent).toBe(
        "Nothing queued",
      );
    });
  });

  it("breaks the outbox backlog out per module so a stuck one is identifiable", async () => {
    mockFetchReliability.mockImplementation(() =>
      Promise.resolve({
        ...RELIABILITY,
        outbox_backlog: 5,
        outbox: [
          {
            table_schema: "billing",
            table: "ai_usage_outbox",
            pending: 1,
            inflight: 0,
            dead_letter: 0,
            backlog: 1,
          },
          {
            table_schema: "cases",
            table: "case_events_outbox",
            pending: 4,
            inflight: 0,
            dead_letter: 0,
            backlog: 4,
          },
        ],
      }),
    );

    render(<ObservabilityReliabilityPage />);

    await waitFor(() => {
      expect(
        screen.getByTestId("reliability-outbox-case_events_outbox").textContent,
      ).toContain("4");
    });
    expect(
      screen.getByTestId("reliability-outbox-ai_usage_outbox").textContent,
    ).toContain("1");
    // The sum is in the takeaway too, so the breakdown reconciles with it.
    expect(
      screen.getByTestId("reliability-queues-takeaway").textContent,
    ).toContain("5 in the outbox");
  });

  it("renders no outbox section when no module outbox has a backlog", async () => {
    render(<ObservabilityReliabilityPage />);

    await waitFor(() => {
      expect(screen.getByTestId("reliability-queues-table")).toBeTruthy();
    });
    expect(screen.queryByTestId("reliability-outbox")).toBeNull();
  });

  it("names recent activity as recent activity, and links to the true gauge", async () => {
    render(<ObservabilityReliabilityPage />);

    await waitFor(() => {
      expect(
        screen.getByTestId("reliability-concurrency-takeaway").textContent,
      ).toBe("12 distinct actors in the last 60 minutes");
    });
    expect(
      screen.getByTestId("reliability-concurrency-title").textContent,
    ).toBe("Recent activity, not simultaneous concurrency");
    expect(
      screen.getByTestId("reliability-concurrency-figures").textContent,
    ).toBe("12");
    expect(screen.getByTestId("reliability-concurrency").textContent).toContain(
      "not how many requests were in flight at once",
    );
    expect(
      screen
        .getByTestId("reliability-concurrency-gauge-link")
        .getAttribute("href"),
    ).toBe(RELIABILITY.concurrency_grafana_link);
  });

  it("states the gauge is absent rather than rendering a link that goes nowhere", async () => {
    mockFetchReliability.mockImplementation(() =>
      Promise.resolve({
        ...RELIABILITY,
        concurrency_grafana_link: null,
      }),
    );

    render(<ObservabilityReliabilityPage />);

    await waitFor(() => {
      expect(
        screen.getByTestId("reliability-concurrency-gauge-absent").textContent,
      ).toContain("not configured");
    });
    expect(
      screen.queryByTestId("reliability-concurrency-gauge-link"),
    ).toBeNull();
  });

  it("reports zero recent actors as a fact, keeping the gauge link reachable", async () => {
    mockFetchReliability.mockImplementation(() =>
      Promise.resolve({ ...RELIABILITY, recent_active_actors: 0 }),
    );

    render(<ObservabilityReliabilityPage />);

    await waitFor(() => {
      expect(
        screen.getByTestId("reliability-concurrency-figures").textContent,
      ).toBe("0");
    });
    // Never empty: the gauge link is how an operator checks the real number, and
    // hiding it at zero activity is hiding it exactly when they doubt the zero.
    expect(
      screen.getByTestId("reliability-concurrency-gauge-link"),
    ).toBeTruthy();
    expect(screen.queryByTestId("reliability-concurrency-error")).toBeNull();
  });

  it("filters the alert feed by status", async () => {
    render(<ObservabilityReliabilityPage />);

    await waitFor(() => {
      expect(mockFetchAlerts).toHaveBeenCalledWith(
        expect.objectContaining({ status: "open" }),
      );
    });
    fireEvent.click(
      screen.getByTestId("reliability-alerts-filter-acknowledged"),
    );

    await waitFor(() => {
      expect(mockFetchAlerts).toHaveBeenLastCalledWith(
        expect.objectContaining({ status: "acknowledged" }),
      );
    });
  });

  it("acknowledges an alert and takes it out of the open list", async () => {
    // The server decides what "acknowledged" means: it stops answering the open
    // filter with that row. Staged here as exactly that - the alert is there
    // until the re-read, and gone after it.
    let served = 0;
    mockFetchAlerts.mockImplementation(() => {
      served += 1;
      return Promise.resolve(
        served === 1 ? alertPage() : alertPage({ alerts: [], total_count: 0 }),
      );
    });

    render(<ObservabilityReliabilityPage />);

    await waitFor(() => {
      expect(
        screen.getByTestId("observability-alert-alert-1-acknowledge"),
      ).toBeTruthy();
    });

    fireEvent.click(
      screen.getByTestId("observability-alert-alert-1-acknowledge"),
    );

    await waitFor(() => {
      expect(screen.queryByTestId("observability-alert-alert-1")).toBeNull();
    });
    expect(mockAcknowledge).toHaveBeenCalledTimes(1);
    // The list emptied, which is the open filter reporting nothing left.
    expect(screen.getByTestId("empty-state-title").textContent).toBe(
      "No alerts",
    );
  });

  it("re-reads the feed after an acknowledgement rather than patching the row", async () => {
    render(<ObservabilityReliabilityPage />);

    await waitFor(() => {
      expect(
        screen.getByTestId("observability-alert-alert-1-acknowledge"),
      ).toBeTruthy();
    });
    const before = mockFetchAlerts.mock.calls.length;

    fireEvent.click(
      screen.getByTestId("observability-alert-alert-1-acknowledge"),
    );

    await waitFor(() => {
      expect(mockFetchAlerts.mock.calls.length).toBeGreaterThan(before);
    });
  });

  it("replays the same idempotency key when an acknowledgement is retried", async () => {
    mockAcknowledge.mockImplementation(() =>
      Promise.reject(new Error("network down")),
    );

    render(<ObservabilityReliabilityPage />);

    const button = await screen.findByTestId(
      "observability-alert-alert-1-acknowledge",
    );
    fireEvent.click(button);
    await waitFor(() => {
      expect(
        screen.getByTestId("observability-alerts-acknowledge-error"),
      ).toBeTruthy();
    });
    fireEvent.click(
      screen.getByTestId("observability-alert-alert-1-acknowledge"),
    );

    await waitFor(() => {
      expect(mockAcknowledge).toHaveBeenCalledTimes(2);
    });
    const first = mockAcknowledge.mock.calls[0][1];
    const second = mockAcknowledge.mock.calls[1][1];
    expect(first).toBeDefined();
    expect(second).toBe(first);
  });

  it("says a failed acknowledgement rather than leaving the row looking done", async () => {
    mockAcknowledge.mockImplementation(() =>
      Promise.reject(new Error("network down")),
    );

    render(<ObservabilityReliabilityPage />);

    fireEvent.click(
      await screen.findByTestId("observability-alert-alert-1-acknowledge"),
    );

    await waitFor(() => {
      expect(
        screen.getByTestId("observability-alerts-acknowledge-error")
          .textContent,
      ).toContain("Could not acknowledge");
    });
    expect(screen.getByTestId("observability-alert-alert-1")).toBeTruthy();
  });

  it("offers no acknowledge on a row that is already answered, and names who answered it", async () => {
    mockFetchAlerts.mockImplementation(() =>
      Promise.resolve(
        alertPage({
          alerts: [
            {
              ...alertPage().alerts[0],
              status: "acknowledged",
              acked_by: 42,
              acked_at: "2026-10-12T10:05:00Z",
            },
          ],
        }),
      ),
    );

    render(<ObservabilityReliabilityPage />);

    await waitFor(() => {
      expect(screen.getByTestId("observability-alert-alert-1")).toBeTruthy();
    });
    expect(
      screen.queryByTestId("observability-alert-alert-1-acknowledge"),
    ).toBeNull();
    expect(
      screen.getByTestId("observability-alert-alert-1-status").textContent,
    ).toBe("acknowledged");
    // An acknowledgement nobody can attribute is a state change, not a response.
    expect(
      screen.getByTestId("observability-alert-alert-1-acked-by").textContent,
    ).toContain("operator 42");
  });

  it("keeps the alert filter reachable after the open list empties", async () => {
    mockFetchAlerts.mockImplementation(() =>
      Promise.resolve(alertPage({ alerts: [], total_count: 0 })),
    );

    render(<ObservabilityReliabilityPage />);

    await waitFor(() => {
      expect(screen.getByTestId("empty-state-title").textContent).toBe(
        "No alerts",
      );
    });
    // The acknowledgement the operator just made is what emptied the list, so
    // "Acknowledged" has to still be one click away.
    expect(screen.getByTestId("reliability-alerts-filter")).toBeTruthy();
    fireEvent.click(
      screen.getByTestId("reliability-alerts-filter-acknowledged"),
    );

    await waitFor(() => {
      expect(mockFetchAlerts).toHaveBeenLastCalledWith(
        expect.objectContaining({ status: "acknowledged" }),
      );
    });
  });

  it("renders the page-level vendor links alongside the scoped ones", async () => {
    render(<ObservabilityReliabilityPage />);

    await waitFor(() => {
      expect(
        screen.getByTestId("observability-deeplink-grafana.dashboard_url"),
      ).toBeTruthy();
    });
    expect(mockFetchDeeplinks).toHaveBeenCalledWith();
  });

  it("renders an unconfigured vendor as absent rather than a broken link", async () => {
    mockFetchDeeplinks.mockImplementation(() => Promise.resolve({}));

    render(<ObservabilityReliabilityPage />);

    await waitFor(() => {
      // #747 removed the page-level strip and shifted render timing. The feed's
      // own deep-links panel shares the generic `empty-state-title` id, so
      // removing the strip turned a latent ambiguity into a reliable failure;
      // scope the assertion to the page-level panel rather than the first title.
      expect(
        within(screen.getByTestId("reliability-deeplinks")).getByTestId(
          "empty-state-title",
        ).textContent,
      ).toBe("No vendor links configured");
    });
  });

  it("keeps every panel's error path and retry when the reads fail", async () => {
    mockFetchProviders.mockImplementation(() =>
      Promise.reject(new Error("network down")),
    );
    mockFetchThroughput.mockImplementation(() =>
      Promise.reject(new Error("network down")),
    );
    mockFetchReliability.mockImplementation(() =>
      Promise.reject(new Error("network down")),
    );
    mockFetchErrors.mockImplementation(() =>
      Promise.reject(new Error("network down")),
    );
    mockFetchAlerts.mockImplementation(() =>
      Promise.reject(new Error("network down")),
    );

    render(<ObservabilityReliabilityPage />);

    await waitFor(() => {
      expect(screen.getByTestId("reliability-providers-error")).toBeTruthy();
    });
    for (const panel of PANELS) {
      expect(screen.getByTestId(`${panel}-error`)).toBeTruthy();
      expect(screen.getByTestId(`${panel}-retry`)).toBeTruthy();
    }
  });

  it("re-runs a failed read when the operator retries the panel", async () => {
    mockFetchProviders.mockImplementation(() =>
      Promise.reject(new Error("network down")),
    );

    render(<ObservabilityReliabilityPage />);

    await waitFor(() => {
      expect(screen.getByTestId("reliability-providers-retry")).toBeTruthy();
    });
    mockFetchProviders.mockImplementation(() => Promise.resolve(PROVIDERS));
    fireEvent.click(screen.getByTestId("reliability-providers-retry"));

    await waitFor(() => {
      expect(screen.getByTestId("reliability-provider-sarvam")).toBeTruthy();
    });
  });
});
