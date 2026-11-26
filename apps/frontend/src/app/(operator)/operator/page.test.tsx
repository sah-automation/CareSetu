// PHASE-5 T5 (#284): Operator verification queue list tests - real-API queue
// render (mocked at the api-client seam per the brief), sorting, empty/error
// states, and click-through to /operator/verification/[id].

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import OperatorDashboardPage from "./page";
import {
  fetchVerificationQueue,
  type PartnerQueue,
  type PartnerQueueItem,
} from "@/lib/operator/api";

vi.mock("@/lib/operator/api", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/operator/api")>();
  return { ...mod, fetchVerificationQueue: vi.fn() };
});

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  usePathname: () => "/operator",
}));

vi.mock("@/lib/auth/AuthContext", () => ({
  useAuth: () => ({
    user: { id: 1, phone: "+911234567890", roles: ["operator"] },
    selectedRole: "operator",
    switchRole: vi.fn(),
    logout: vi.fn(),
    isAuthenticated: true,
    isLoading: false,
  }),
}));

const mockFetchQueue = vi.mocked(fetchVerificationQueue);

function queueItem(overrides: Partial<PartnerQueueItem>): PartnerQueueItem {
  return {
    partner_id: 1,
    identity_id: 10,
    partner_type: "doctor",
    status: "Under Verification",
    practice_name: "Test Clinic",
    practice_address: "Test City",
    created_at: "2026-08-20T10:00:00Z",
    round: 1,
    ...overrides,
  };
}

const QUEUE_ITEMS: PartnerQueue = {
  items: [
    queueItem({
      partner_id: 1,
      partner_type: "lab",
      practice_name: "Pioneer Diagnostics",
      practice_address: "Court Rd, Daltonganj",
      created_at: "2026-08-19T14:15:00Z",
      round: 2,
    }),
    queueItem({
      partner_id: 2,
      partner_type: "chemist",
      practice_name: "Sharma Medical Store",
      practice_address: "Main Market",
      created_at: "2026-08-20T16:12:00Z",
      round: 1,
    }),
    queueItem({
      partner_id: 3,
      partner_type: "doctor",
      practice_name: "Dr. Meera Singh",
      practice_address: "Health Colony",
      created_at: "2026-08-21T10:03:00Z",
      round: 1,
    }),
  ],
};

function resolveWith(data: PartnerQueue | null) {
  mockFetchQueue.mockImplementation(() =>
    data === null
      ? Promise.reject(new Error("network down"))
      : (Promise.resolve(data) as Promise<PartnerQueue>),
  );
}

beforeEach(() => {
  resolveWith(QUEUE_ITEMS);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("OperatorDashboardPage", () => {
  it("shows a loading skeleton while fetching", () => {
    mockFetchQueue.mockImplementation(
      () => new Promise<PartnerQueue>(() => {}),
    );
    render(<OperatorDashboardPage />);
    expect(screen.getByTestId("queue-skeleton")).toBeTruthy();
  });

  it("renders the verification queue table", async () => {
    render(<OperatorDashboardPage />);
    await waitFor(() => {
      expect(screen.getByTestId("queue-table")).toBeTruthy();
    });
    expect(screen.getByText("Pioneer Diagnostics")).toBeTruthy();
    expect(screen.getByText("Sharma Medical Store")).toBeTruthy();
    expect(screen.getByText("Dr. Meera Singh")).toBeTruthy();
  });

  it("shows empty state when queue has no items", async () => {
    resolveWith({ items: [] });
    render(<OperatorDashboardPage />);
    await waitFor(() => {
      expect(screen.getByTestId("empty-state")).toBeTruthy();
    });
    expect(screen.getByText("No pending verifications")).toBeTruthy();
  });

  it("shows error banner on fetch failure", async () => {
    resolveWith(null);
    render(<OperatorDashboardPage />);
    await waitFor(() => {
      expect(screen.getByTestId("error-banner")).toBeTruthy();
    });
    expect(
      screen.getByText("Could not load the verification queue."),
    ).toBeTruthy();
  });

  it("retry reloads the queue", async () => {
    resolveWith(null);
    render(<OperatorDashboardPage />);
    await waitFor(() => {
      expect(screen.getByTestId("error-banner")).toBeTruthy();
    });
    resolveWith(QUEUE_ITEMS);
    fireEvent.click(screen.getByTestId("error-banner-retry"));
    await waitFor(() => {
      expect(screen.getByTestId("queue-table")).toBeTruthy();
    });
  });

  it("dismisses the error banner", async () => {
    resolveWith(null);
    render(<OperatorDashboardPage />);
    await waitFor(() => {
      expect(screen.getByTestId("error-banner")).toBeTruthy();
    });
    fireEvent.click(screen.getByTestId("error-banner-dismiss"));
    expect(screen.queryByTestId("error-banner")).toBeNull();
  });

  it("defaults to registration_age sort (oldest first)", async () => {
    render(<OperatorDashboardPage />);
    await waitFor(() => {
      expect(screen.getByTestId("queue-table")).toBeTruthy();
    });
    const rows = screen.getAllByTestId(/^queue-item-/);
    expect(rows[0]).toHaveAttribute("data-testid", "queue-item-1");
    expect(rows[1]).toHaveAttribute("data-testid", "queue-item-2");
    expect(rows[2]).toHaveAttribute("data-testid", "queue-item-3");
  });

  it("sorts by partner_type when clicked", async () => {
    render(<OperatorDashboardPage />);
    await waitFor(() => {
      expect(screen.getByTestId("queue-table")).toBeTruthy();
    });
    fireEvent.click(screen.getByTestId("sort-partner_type"));
    const rows = screen.getAllByTestId(/^queue-item-/);
    // chemist < doctor < lab (alphabetical)
    expect(rows[0]).toHaveAttribute("data-testid", "queue-item-2");
    expect(rows[1]).toHaveAttribute("data-testid", "queue-item-3");
    expect(rows[2]).toHaveAttribute("data-testid", "queue-item-1");
  });

  it("renders partner type badges", async () => {
    render(<OperatorDashboardPage />);
    await waitFor(() => {
      expect(screen.getByText("Lab")).toBeTruthy();
    });
    expect(screen.getByText("Chemist")).toBeTruthy();
    expect(screen.getByText("Doctor")).toBeTruthy();
  });

  it("renders status badges", async () => {
    render(<OperatorDashboardPage />);
    await waitFor(() => {
      expect(screen.getByTestId("queue-table")).toBeTruthy();
    });
    const statusBadges = screen.getAllByText("Under Verification");
    expect(statusBadges.length).toBe(3);
  });

  it("renders review links with correct hrefs", async () => {
    render(<OperatorDashboardPage />);
    await waitFor(() => {
      expect(screen.getByTestId("queue-table")).toBeTruthy();
    });
    const links = screen.getAllByText("Review");
    expect(links[0].closest("a")).toHaveAttribute(
      "href",
      "/operator/verification/1",
    );
    expect(links[1].closest("a")).toHaveAttribute(
      "href",
      "/operator/verification/2",
    );
    expect(links[2].closest("a")).toHaveAttribute(
      "href",
      "/operator/verification/3",
    );
  });

  it("shows practice address under practice name", async () => {
    render(<OperatorDashboardPage />);
    await waitFor(() => {
      expect(screen.getByText("Court Rd, Daltonganj")).toBeTruthy();
    });
    expect(screen.getByText("Main Market")).toBeTruthy();
    expect(screen.getByText("Health Colony")).toBeTruthy();
  });

  it("shows round number for each item", async () => {
    render(<OperatorDashboardPage />);
    await waitFor(() => {
      expect(screen.getByTestId("queue-table")).toBeTruthy();
    });
    const rows = screen.getAllByTestId(/^queue-item-/);
    // First item (Pioneer Diagnostics) has round 2
    expect(rows[0].querySelector("td:nth-child(5)")).toHaveTextContent("2");
    // Other items have round 1
    expect(rows[1].querySelector("td:nth-child(5)")).toHaveTextContent("1");
    expect(rows[2].querySelector("td:nth-child(5)")).toHaveTextContent("1");
  });

  it("falls back to partner ID when practice_name is null", async () => {
    resolveWith({
      items: [queueItem({ partner_id: 42, practice_name: null })],
    });
    render(<OperatorDashboardPage />);
    await waitFor(() => {
      expect(screen.getByText("Partner #42")).toBeTruthy();
    });
  });

  it("passes default params to fetchVerificationQueue", async () => {
    render(<OperatorDashboardPage />);
    await waitFor(() => {
      expect(mockFetchQueue).toHaveBeenCalledWith({
        status: "Under Verification",
        sort_by: "registration_age",
      });
    });
  });
});
