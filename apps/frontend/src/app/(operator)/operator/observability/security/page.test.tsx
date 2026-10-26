// #783: the operator Security panel page. Mocks the client at the
// lib/operator/observability seam and covers loading, populated, empty, error
// and retry - plus the panel-independence this page depends on: a failed
// signals read must not blank the CSP violations beside it.

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
  fetchSecurity,
  type SecuritySummary,
} from "@/lib/operator/observability";

import ObservabilitySecurityPage from "./page";

vi.mock("@/lib/operator/observability", async (importOriginal) => {
  const mod =
    await importOriginal<typeof import("@/lib/operator/observability")>();
  return { ...mod, fetchSecurity: vi.fn() };
});

const mockFetchSecurity = vi.mocked(fetchSecurity);

const SECURITY: SecuritySummary = {
  signals: [
    {
      signal_kind: "auth_failure",
      count_last_5m: 12,
      threshold: 10,
      alert_kind: "auth_failure_alert",
      is_deferred: false,
      deferred_reason: null,
    },
    {
      signal_kind: "rate_limit_exceeded",
      count_last_5m: 3,
      threshold: 5,
      alert_kind: "rate_limit_alert",
      is_deferred: false,
      deferred_reason: null,
    },
    {
      signal_kind: "consent_anomaly",
      count_last_5m: 0,
      threshold: 2,
      alert_kind: null,
      is_deferred: true,
      deferred_reason: "Below minimum threshold for anomaly detection",
    },
  ],
  csp_aggregates: [
    {
      directive: "script-src",
      disposition: "blocked",
      blocked_source: "https://evil.example.com",
      count: 42,
    },
    {
      directive: "style-src",
      disposition: "report-only",
      blocked_source: "inline",
      count: 7,
    },
  ],
  prompt_injection_count: 5,
  webhook_monitoring_status: "active",
  webhook_monitoring_reason:
    "Reserved event webhook_signature_failure is registered; monitoring activates on first inbound webhook.",
};

function resolveSecurityWith(data: SecuritySummary | null) {
  mockFetchSecurity.mockImplementation(() =>
    data === null
      ? Promise.reject(new Error("network down"))
      : Promise.resolve(data),
  );
}

beforeAll(() => {});

beforeEach(() => {
  resolveSecurityWith(SECURITY);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("ObservabilitySecurityPage", () => {
  it("shows a loading skeleton for all panels while the read is in flight", () => {
    mockFetchSecurity.mockImplementation(
      () => new Promise<SecuritySummary>(() => {}),
    );

    render(<ObservabilitySecurityPage />);

    expect(screen.getByTestId("security-signals-loading")).toBeTruthy();
    expect(screen.getByTestId("security-csp-loading")).toBeTruthy();
    expect(
      screen.getByTestId("security-prompt-injection-loading"),
    ).toBeTruthy();
    expect(screen.getByTestId("security-webhook-loading")).toBeTruthy();
  });

  it("renders the security signals table with counts, thresholds and alert kinds", async () => {
    render(<ObservabilitySecurityPage />);

    await waitFor(() => {
      expect(
        screen.getByTestId("security-signals").getAttribute("data-status"),
      ).toBe("ready");
    });

    // Check the table headers
    expect(screen.getByText("Signal kind")).toBeInTheDocument();
    expect(screen.getByText("Count (5m)")).toBeInTheDocument();
    expect(screen.getByText("Threshold")).toBeInTheDocument();
    expect(screen.getByText("Alert kind")).toBeInTheDocument();

    // Check signal rows
    expect(screen.getByTestId("signal-row-auth_failure")).toBeInTheDocument();
    expect(
      screen.getByTestId("signal-row-rate_limit_exceeded"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("signal-row-consent_anomaly"),
    ).toBeInTheDocument();

    // Check counts
    expect(screen.getByText("12")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByText("0")).toBeInTheDocument();

    // Check thresholds
    expect(screen.getByText("10")).toBeInTheDocument();
    expect(screen.getByText("5")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();

    // Check alert kinds
    expect(screen.getByText("auth_failure_alert")).toBeInTheDocument();
    expect(screen.getByText("rate_limit_alert")).toBeInTheDocument();
    expect(screen.getByText("-")).toBeInTheDocument(); // null alert_kind

    // Check deferred badge
    expect(screen.getByTestId("signal-badge-active")).toBeInTheDocument();
    expect(screen.getByTestId("signal-badge-deferred")).toBeInTheDocument();
    expect(screen.getByText("Deferred")).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();

    // Check deferred reason
    expect(
      screen.getByText("Below minimum threshold for anomaly detection"),
    ).toBeInTheDocument();
  });

  it("shows the webhook monitoring status in the signals panel takeaway", async () => {
    render(<ObservabilitySecurityPage />);

    await waitFor(() => {
      expect(
        screen.getByTestId("security-signals-takeaway").textContent,
      ).toContain("Webhook monitoring: active");
    });
  });

  it("renders the CSP violations table with directives, dispositions and counts", async () => {
    render(<ObservabilitySecurityPage />);

    await waitFor(() => {
      expect(
        screen.getByTestId("security-csp").getAttribute("data-status"),
      ).toBe("ready");
    });

    // Check the table headers
    expect(screen.getByText("Directive")).toBeInTheDocument();
    expect(screen.getByText("Disposition")).toBeInTheDocument();
    expect(screen.getByText("Blocked source")).toBeInTheDocument();
    expect(screen.getByText("Count")).toBeInTheDocument();

    // Check CSP rows
    expect(
      screen.getByTestId("csp-row-script-src-blocked"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("csp-row-style-src-report-only"),
    ).toBeInTheDocument();

    // Check data
    expect(screen.getByText("script-src")).toBeInTheDocument();
    expect(screen.getByText("blocked")).toBeInTheDocument();
    expect(screen.getByText("https://evil.example.com")).toBeInTheDocument();
    expect(screen.getByText("42")).toBeInTheDocument();

    expect(screen.getByText("style-src")).toBeInTheDocument();
    expect(screen.getByText("report-only")).toBeInTheDocument();
    expect(screen.getByText("inline")).toBeInTheDocument();
    expect(screen.getByText("7")).toBeInTheDocument();
  });

  it("renders the prompt-injection count panel", async () => {
    render(<ObservabilitySecurityPage />);

    await waitFor(() => {
      expect(
        screen
          .getByTestId("security-prompt-injection")
          .getAttribute("data-status"),
      ).toBe("ready");
    });

    expect(screen.getByText("5")).toBeInTheDocument();
    expect(
      screen.getByText("Total findings in the current scan window"),
    ).toBeInTheDocument();
  });

  it("renders the webhook monitoring panel with status and reason", async () => {
    render(<ObservabilitySecurityPage />);

    await waitFor(() => {
      expect(
        screen.getByTestId("security-webhook").getAttribute("data-status"),
      ).toBe("ready");
    });

    expect(screen.getByText("Active")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Reserved event webhook_signature_failure is registered; monitoring activates on first inbound webhook.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Reference: ADR-0032 (accepted risk)"),
    ).toBeInTheDocument();
  });

  it("shows empty state when there are no security signals", async () => {
    resolveSecurityWith({
      ...SECURITY,
      signals: [],
    });

    render(<ObservabilitySecurityPage />);

    await waitFor(() => {
      expect(screen.getByTestId("empty-state-title").textContent).toBe(
        "No security signals",
      );
    });
    expect(
      screen.getByText("The security scan has not recorded any signals yet."),
    ).toBeInTheDocument();
  });

  it("shows empty state when there are no CSP violations", async () => {
    resolveSecurityWith({
      ...SECURITY,
      csp_aggregates: [],
    });

    render(<ObservabilitySecurityPage />);

    await waitFor(() => {
      expect(screen.getByTestId("empty-state-title").textContent).toBe(
        "No CSP violations",
      );
    });
    expect(
      screen.getByText(
        "The CSP report collector has not received any violations yet.",
      ),
    ).toBeInTheDocument();
  });

  it("shows empty state when there are no prompt-injection findings", async () => {
    resolveSecurityWith({
      ...SECURITY,
      prompt_injection_count: 0,
    });

    render(<ObservabilitySecurityPage />);

    await waitFor(() => {
      expect(screen.getByTestId("empty-state-title").textContent).toBe(
        "No prompt-injection findings",
      );
    });
    expect(
      screen.getByText(
        "The pre-egress screen has not detected any injection attempts.",
      ),
    ).toBeInTheDocument();
  });

  it("shows the failure inline, with the API trace id", async () => {
    resolveSecurityWith(null);

    render(<ObservabilitySecurityPage />);

    await waitFor(() => {
      expect(screen.getByTestId("security-signals-error")).toBeTruthy();
    });
    expect(screen.getByText("Could not load security signals.")).toBeTruthy();
    // Other panels keep working; one route's failure is not the page's.
    expect(screen.queryByTestId("security-csp-error")).toBeNull();
    expect(screen.queryByTestId("security-prompt-injection-error")).toBeNull();
    expect(screen.queryByTestId("security-webhook-error")).toBeNull();
  });

  it("retries only the panel that failed", async () => {
    resolveSecurityWith(null);
    render(<ObservabilitySecurityPage />);
    await waitFor(() => {
      expect(screen.getByTestId("security-signals-error")).toBeTruthy();
    });

    resolveSecurityWith(SECURITY);
    fireEvent.click(screen.getByTestId("security-signals-retry"));

    await waitFor(() => {
      expect(
        screen.getByTestId("security-signals").getAttribute("data-status"),
      ).toBe("ready");
    });
    expect(mockFetchSecurity).toHaveBeenCalledTimes(2);
  });

  it("renders the page header with title and description", () => {
    render(<ObservabilitySecurityPage />);

    expect(screen.getByTestId("page-header")).toBeInTheDocument();
    expect(screen.getByText("Security")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Auth trends, lockout signals, CSP violations, and webhook monitoring status.",
      ),
    ).toBeInTheDocument();
  });

  it("renders the panel without the page-level tab strip (#747)", () => {
    render(<ObservabilitySecurityPage />);

    expect(screen.getByTestId("page-header")).toBeInTheDocument();
    expect(screen.queryByTestId("observability-panel-tabs")).toBeNull();
    expect(screen.queryByTestId("observability-tab-security")).toBeNull();
  });
});
