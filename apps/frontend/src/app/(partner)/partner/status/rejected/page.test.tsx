// PHASE-2.6 T10 (#201) / PHASE-5 FE T3 (#281): the rejected state screen -
// full-shell mounting, real rejection reason from the API, the appeal CTA
// wired to POST /v1/partner/appeal with success/error feedback.

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import PartnerStatusRejectedPage from "./page";
import PartnerGroupLayout from "@/app/(partner)/layout";
import { useAuth } from "@/lib/auth/AuthContext";
import { STRINGS } from "@/lib/i18n/dictionaries";

const mockReplace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mockReplace }),
  usePathname: () => "/partner/status/rejected",
}));

vi.mock("@/lib/auth/AuthContext", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/auth/AuthContext")>();
  return { ...mod, useAuth: vi.fn() };
});

vi.mock("@/lib/partner/api", () => ({
  fetchPartnerMe: vi.fn(),
  fetchRejectionReason: vi.fn(),
  appealRejection: vi.fn(),
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

describe("PartnerStatusRejectedPage (inside the full shell)", () => {
  it("mounts within the partner AppShell", async () => {
    const { fetchPartnerMe, fetchRejectionReason } = await import(
      "@/lib/partner/api"
    );
    vi.mocked(fetchPartnerMe).mockResolvedValue({
      partner_id: 1,
      status: "Rejected",
      partner_type: "chemist",
      round: 1,
    });
    vi.mocked(fetchRejectionReason).mockResolvedValue({
      partner_id: 1,
      rejection_reason: "The drug license photo is unreadable.",
      round: 1,
    });

    render(
      <PartnerGroupLayout>
        <PartnerStatusRejectedPage />
      </PartnerGroupLayout>,
    );
    expect(screen.getByTestId("app-shell")).toBeInTheDocument();
    expect(screen.getByTestId("topbar")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByTestId("partner-rejected-card")).toBeInTheDocument();
    });
  });

  it("shows loading skeletons while fetching", async () => {
    const { fetchPartnerMe, fetchRejectionReason } = await import(
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
    vi.mocked(fetchRejectionReason).mockResolvedValue({
      partner_id: 1,
      rejection_reason: "reason",
      round: 1,
    });

    render(<PartnerStatusRejectedPage />);
    expect(screen.getByTestId("partner-rejected-loading")).toBeInTheDocument();

    resolveMe!({
      partner_id: 1,
      status: "Rejected",
      partner_type: "chemist",
      round: 1,
    });
    await waitFor(() => {
      expect(
        screen.queryByTestId("partner-rejected-loading"),
      ).not.toBeInTheDocument();
    });
  });

  it("shows real rejection reason from the API", async () => {
    const { fetchPartnerMe, fetchRejectionReason } = await import(
      "@/lib/partner/api"
    );
    vi.mocked(fetchPartnerMe).mockResolvedValue({
      partner_id: 1,
      status: "Rejected",
      partner_type: "chemist",
      round: 1,
    });
    vi.mocked(fetchRejectionReason).mockResolvedValue({
      partner_id: 1,
      rejection_reason:
        "The drug license photo is unreadable - the license number is cut off.",
      round: 1,
    });

    render(<PartnerStatusRejectedPage />);
    await waitFor(() => {
      expect(screen.getByTestId("partner-status-badge")).toHaveTextContent(
        STRINGS.en.staffAuth.rejected.badge,
      );
    });
    const reason = screen.getByTestId("partner-rejection-reason");
    expect(reason).toHaveTextContent(
      STRINGS.en.staffAuth.rejected.reasonHeading,
    );
    expect(reason).toHaveTextContent(
      "The drug license photo is unreadable - the license number is cut off.",
    );
  });

  it("shows error banner when fetch fails and recovers on retry", async () => {
    const { fetchPartnerMe, fetchRejectionReason } = await import(
      "@/lib/partner/api"
    );
    vi.mocked(fetchPartnerMe).mockRejectedValue(new Error("network down"));
    vi.mocked(fetchRejectionReason).mockResolvedValue({
      partner_id: 1,
      rejection_reason: "reason",
      round: 1,
    });

    render(<PartnerStatusRejectedPage />);
    await waitFor(() => {
      expect(screen.getByTestId("error-banner")).toBeInTheDocument();
    });

    // Retry succeeds
    vi.mocked(fetchPartnerMe).mockResolvedValue({
      partner_id: 1,
      status: "Rejected",
      partner_type: "lab",
      round: 2,
    });
    vi.mocked(fetchRejectionReason).mockResolvedValue({
      partner_id: 1,
      rejection_reason: "Accreditation expired.",
      round: 2,
    });

    screen.getByTestId("error-banner-retry").click();
    await waitFor(() => {
      expect(screen.queryByTestId("error-banner")).not.toBeInTheDocument();
    });
    expect(screen.getByText("Accreditation expired.")).toBeInTheDocument();
  });

  it("appeal CTA calls appealRejection and shows success on completion", async () => {
    const { fetchPartnerMe, fetchRejectionReason, appealRejection } =
      await import("@/lib/partner/api");
    vi.mocked(fetchPartnerMe).mockResolvedValue({
      partner_id: 1,
      status: "Rejected",
      partner_type: "chemist",
      round: 1,
    });
    vi.mocked(fetchRejectionReason).mockResolvedValue({
      partner_id: 1,
      rejection_reason: "reason",
      round: 1,
    });
    vi.mocked(appealRejection).mockResolvedValue({
      partner_id: 1,
      status: "Under Verification",
      round: 2,
    });

    render(<PartnerStatusRejectedPage />);
    await waitFor(() => {
      expect(screen.getByTestId("partner-resubmit-cta")).toBeEnabled();
    });

    screen.getByTestId("partner-resubmit-cta").click();

    // Button should eventually be disabled (pending or done)
    await waitFor(() => {
      expect(screen.getByTestId("partner-resubmit-cta")).toBeDisabled();
    });

    // Success message should appear
    await waitFor(() => {
      expect(screen.getByTestId("partner-appeal-success")).toHaveTextContent(
        STRINGS.en.staffAuth.rejected.appealSuccess,
      );
    });
    expect(appealRejection).toHaveBeenCalledOnce();
  });

  it("shows error when appeal fails", async () => {
    const { fetchPartnerMe, fetchRejectionReason, appealRejection } =
      await import("@/lib/partner/api");
    const { ApiError } = await import("@/lib/api-errors");
    vi.mocked(fetchPartnerMe).mockResolvedValue({
      partner_id: 1,
      status: "Rejected",
      partner_type: "chemist",
      round: 1,
    });
    vi.mocked(fetchRejectionReason).mockResolvedValue({
      partner_id: 1,
      rejection_reason: "reason",
      round: 1,
    });
    vi.mocked(appealRejection).mockRejectedValue(
      new ApiError({
        code: "ALREADY_APPEALED",
        message: "Already appealed",
        trace_id: "abc123",
        details: {},
      }),
    );

    render(<PartnerStatusRejectedPage />);
    await waitFor(() => {
      expect(screen.getByTestId("partner-resubmit-cta")).toBeEnabled();
    });

    screen.getByTestId("partner-resubmit-cta").click();
    await waitFor(() => {
      expect(screen.getByTestId("partner-appeal-error")).toHaveTextContent(
        "Already appealed",
      );
    });
    // CTA should be re-enabled after failure
    expect(screen.getByTestId("partner-resubmit-cta")).toBeEnabled();
  });

  it("carries the help contact affordance", async () => {
    const { fetchPartnerMe, fetchRejectionReason } = await import(
      "@/lib/partner/api"
    );
    vi.mocked(fetchPartnerMe).mockResolvedValue({
      partner_id: 1,
      status: "Rejected",
      partner_type: "chemist",
      round: 1,
    });
    vi.mocked(fetchRejectionReason).mockResolvedValue({
      partner_id: 1,
      rejection_reason: "reason",
      round: 1,
    });

    render(<PartnerStatusRejectedPage />);
    await waitFor(() => {
      expect(screen.getByTestId("partner-help-link")).toHaveTextContent(
        STRINGS.en.staffAuth.rejected.helpCta,
      );
    });
  });

  it("redirects to pending when the application moves back under verification", async () => {
    const { fetchPartnerMe, fetchRejectionReason } = await import(
      "@/lib/partner/api"
    );
    vi.mocked(fetchPartnerMe).mockResolvedValue({
      partner_id: 1,
      status: "Under Verification",
      partner_type: "chemist",
      round: 2,
    });
    vi.mocked(fetchRejectionReason).mockResolvedValue({
      partner_id: 1,
      rejection_reason: "reason",
      round: 2,
    });

    render(<PartnerStatusRejectedPage />);
    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith("/partner/status/pending");
    });
  });

  it("redirects to the partner home when polling finds the operator activated it", async () => {
    const { fetchPartnerMe, fetchRejectionReason } = await import(
      "@/lib/partner/api"
    );
    vi.mocked(fetchPartnerMe).mockResolvedValue({
      partner_id: 1,
      status: "Active",
      partner_type: "chemist",
      round: 2,
    });
    vi.mocked(fetchRejectionReason).mockResolvedValue({
      partner_id: 1,
      rejection_reason: "reason",
      round: 2,
    });

    render(<PartnerStatusRejectedPage />);
    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith("/partner");
    });
  });
});
