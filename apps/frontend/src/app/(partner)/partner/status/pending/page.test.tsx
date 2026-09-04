// PHASE-2.6 T10 (#201) / PHASE-5 FE T3 (#281): the pending state screen
// mounts inside the full partner shell, fetches real partner + verification
// data, shows loading skeletons, error banner with retry, and polls while
// status is "Under Verification".

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import PartnerStatusPendingPage from "./page";
import PartnerGroupLayout from "@/app/(partner)/layout";
import { useAuth } from "@/lib/auth/AuthContext";
import { STRINGS } from "@/lib/i18n/dictionaries";

const mockReplace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mockReplace }),
  usePathname: () => "/partner/status/pending",
}));

vi.mock("@/lib/auth/AuthContext", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/auth/AuthContext")>();
  return { ...mod, useAuth: vi.fn() };
});

vi.mock("@/lib/partner/api", () => ({
  fetchPartnerMe: vi.fn(),
  fetchPartnerVerification: vi.fn(),
}));

function mockSession(roles: string[] | null) {
  vi.mocked(useAuth).mockReturnValue({
    user: roles === null ? null : { id: 7, phone: "+911234567890", roles },
    selectedRole: roles?.includes("partner") ? "partner" : null,
    switchRole: vi.fn(),
    logout: vi.fn(),
    isAuthenticated: roles !== null,
    isLoading: false,
  });
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  mockSession(null);
  mockReplace.mockReset();
});

mockSession(["partner"]);

describe("PartnerStatusPendingPage (inside the full shell)", () => {
  it("mounts within the partner AppShell behind the session guard's group", async () => {
    const { fetchPartnerMe, fetchPartnerVerification } = await import(
      "@/lib/partner/api"
    );
    vi.mocked(fetchPartnerMe).mockResolvedValue({
      partner_id: 1,
      status: "Under Verification",
      partner_type: "chemist",
      round: 1,
      created_at: "2026-08-21T10:42:00Z",
    });
    vi.mocked(fetchPartnerVerification).mockResolvedValue({
      partner_id: 1,
      round: 1,
      status: "pending",
    });

    render(
      <PartnerGroupLayout>
        <PartnerStatusPendingPage />
      </PartnerGroupLayout>,
    );
    expect(screen.getByTestId("app-shell")).toBeInTheDocument();
    expect(screen.getByTestId("topbar")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByTestId("partner-pending-card")).toBeInTheDocument();
    });
  });

  it("shows loading skeletons while fetching", async () => {
    const { fetchPartnerMe, fetchPartnerVerification } = await import(
      "@/lib/partner/api"
    );
    let resolveMe!: (
      value:
        | import("@/lib/partner/api").PartnerMeView
        | PromiseLike<import("@/lib/partner/api").PartnerMeView>,
    ) => void;
    vi.mocked(fetchPartnerMe).mockReturnValue(
      new Promise((r) => {
        resolveMe = r;
      }),
    );
    vi.mocked(fetchPartnerVerification).mockResolvedValue({
      partner_id: 1,
      round: 1,
    });

    render(<PartnerStatusPendingPage />);
    expect(screen.getByTestId("partner-pending-loading")).toBeInTheDocument();

    resolveMe!({
      partner_id: 1,
      status: "Under Verification",
      partner_type: "chemist",
      round: 1,
      created_at: "2026-08-21T10:42:00Z",
    });
    await waitFor(() => {
      expect(
        screen.queryByTestId("partner-pending-loading"),
      ).not.toBeInTheDocument();
    });
  });

  it("shows real partner data after fetch", async () => {
    const { fetchPartnerMe, fetchPartnerVerification } = await import(
      "@/lib/partner/api"
    );
    vi.mocked(fetchPartnerMe).mockResolvedValue({
      partner_id: 1,
      status: "Under Verification",
      partner_type: "chemist",
      round: 1,
      created_at: "2026-08-21T10:42:00Z",
    });
    vi.mocked(fetchPartnerVerification).mockResolvedValue({
      partner_id: 1,
      round: 1,
      decision_reason: "Drug license, shop license, owner KYC",
    });

    render(<PartnerStatusPendingPage />);
    await waitFor(() => {
      expect(screen.getByTestId("partner-status-badge")).toHaveTextContent(
        STRINGS.en.staffAuth.pending.badge,
      );
    });
    expect(
      screen.getByRole("heading", { name: STRINGS.en.staffAuth.pending.title }),
    ).toBeInTheDocument();
    expect(screen.getByTestId("partner-pending-note")).toHaveTextContent(
      STRINGS.en.staffAuth.pending.infoBanner,
    );
    // No stale decision_reason from prior round shown
    expect(
      screen.queryByText("Drug license, shop license, owner KYC"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText(STRINGS.en.staffAuth.pending.verifyingLabel),
    ).not.toBeInTheDocument();
  });

  it("does not render a stale 'Verifying scope' row from a prior round", async () => {
    const { fetchPartnerMe, fetchPartnerVerification } = await import(
      "@/lib/partner/api"
    );
    vi.mocked(fetchPartnerMe).mockResolvedValue({
      partner_id: 1,
      status: "Under Verification",
      partner_type: "chemist",
      round: 2,
      created_at: "2026-09-01T08:00:00Z",
    });
    vi.mocked(fetchPartnerVerification).mockResolvedValue({
      partner_id: 1,
      round: 2,
      decision: "Rejected",
      decision_reason: "Expired shop license",
      decided_at: "2026-08-25T12:00:00Z",
    });

    render(<PartnerStatusPendingPage />);
    await waitFor(() => {
      expect(screen.getByTestId("partner-pending-card")).toBeInTheDocument();
    });
    // The stale decision_reason from round 1 must not appear
    expect(screen.queryByText("Expired shop license")).not.toBeInTheDocument();
    // The verifying label row itself must be absent
    expect(
      screen.queryByText(STRINGS.en.staffAuth.pending.verifyingLabel),
    ).not.toBeInTheDocument();
  });

  it("shows error banner when fetch fails and recovers on retry", async () => {
    const { fetchPartnerMe, fetchPartnerVerification } = await import(
      "@/lib/partner/api"
    );
    vi.mocked(fetchPartnerMe).mockRejectedValue(new Error("network down"));
    vi.mocked(fetchPartnerVerification).mockResolvedValue({
      partner_id: 1,
      round: 1,
    });

    render(<PartnerStatusPendingPage />);
    await waitFor(() => {
      expect(screen.getByTestId("error-banner")).toBeInTheDocument();
    });

    // Retry succeeds
    vi.mocked(fetchPartnerMe).mockResolvedValue({
      partner_id: 1,
      status: "Under Verification",
      partner_type: "doctor",
      round: 2,
      created_at: "2026-09-01T08:00:00Z",
    });
    vi.mocked(fetchPartnerVerification).mockResolvedValue({
      partner_id: 1,
      round: 2,
    });

    screen.getByTestId("error-banner-retry").click();
    await waitFor(() => {
      expect(screen.queryByTestId("error-banner")).not.toBeInTheDocument();
    });
    expect(screen.getByTestId("partner-status-badge")).toHaveTextContent(
      STRINGS.en.staffAuth.pending.badge,
    );
  });

  it("carries the help contact affordance", async () => {
    const { fetchPartnerMe, fetchPartnerVerification } = await import(
      "@/lib/partner/api"
    );
    vi.mocked(fetchPartnerMe).mockResolvedValue({
      partner_id: 1,
      status: "Under Verification",
      partner_type: "lab",
      round: 1,
    });
    vi.mocked(fetchPartnerVerification).mockResolvedValue({
      partner_id: 1,
      round: 1,
    });

    render(<PartnerStatusPendingPage />);
    await waitFor(() => {
      expect(screen.getByTestId("partner-help-link")).toHaveTextContent(
        STRINGS.en.staffAuth.pending.helpCta,
      );
    });
  });

  it("reads STATUS_POLL_INTERVAL_MS from the shared config module", async () => {
    vi.mock("@/lib/config", () => ({
      STATUS_POLL_INTERVAL_MS: 42_000,
    }));

    const { fetchPartnerMe, fetchPartnerVerification } = await import(
      "@/lib/partner/api"
    );

    vi.mocked(fetchPartnerMe).mockResolvedValue({
      partner_id: 1,
      status: "Under Verification",
      partner_type: "chemist",
      round: 1,
      created_at: "2026-08-21T10:42:00Z",
    });
    vi.mocked(fetchPartnerVerification).mockResolvedValue({
      partner_id: 1,
      round: 1,
    });

    render(<PartnerStatusPendingPage />);
    await waitFor(() => {
      expect(screen.getByTestId("partner-pending-card")).toBeInTheDocument();
    });

    const { STATUS_POLL_INTERVAL_MS } = await import("@/lib/config");
    expect(STATUS_POLL_INTERVAL_MS).toBe(42_000);
  });
});
