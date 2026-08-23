// PHASE-2.6 T10 (#201): the rejected state screen - full-shell mounting, the
// reason block per FEAT-014 scenario 2, and the resubmission edge stubbed
// honestly (no navigation, no fake submission).

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import PartnerStatusRejectedPage from "./page";
import PartnerGroupLayout from "@/app/(partner)/layout";
import { useAuth } from "@/lib/auth/AuthContext";
import { STRINGS } from "@/lib/i18n/dictionaries";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  usePathname: () => "/partner/status/rejected",
}));

vi.mock("@/lib/auth/AuthContext", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/auth/AuthContext")>();
  return { ...mod, useAuth: vi.fn() };
});

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
});

mockSession(["partner"]);

describe("PartnerStatusRejectedPage (inside the full shell)", () => {
  it("mounts within the partner AppShell", () => {
    render(
      <PartnerGroupLayout>
        <PartnerStatusRejectedPage />
      </PartnerGroupLayout>,
    );
    expect(screen.getByTestId("app-shell")).toBeInTheDocument();
    expect(screen.getByTestId("topbar")).toBeInTheDocument();
    expect(screen.getByTestId("partner-rejected-card")).toBeInTheDocument();
  });

  it("presents the rejected badge and reason block", () => {
    render(<PartnerStatusRejectedPage />);
    const t = STRINGS.en.staffAuth.rejected;
    expect(screen.getByTestId("partner-status-badge")).toHaveTextContent(
      t.badge,
    );
    const reason = screen.getByTestId("partner-rejection-reason");
    expect(reason).toHaveTextContent(t.reasonHeading);
    expect(reason).toHaveTextContent(t.reasonPlaceholder);
    expect(reason).toHaveTextContent(t.reasonPlaceholder);
  });

  it("stubs the resubmission edge with honest Phase 5 feedback", () => {
    render(<PartnerStatusRejectedPage />);
    const t = STRINGS.en.staffAuth.rejected;
    expect(
      screen.queryByTestId("partner-resubmit-stub"),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId("partner-resubmit-cta"));
    const stub = screen.getByRole("status");
    expect(stub).toHaveTextContent(t.resubmitStubNotice);
    expect(stub).toHaveTextContent(/Phase 5/);
  });

  it("never fakes a successful resubmission", () => {
    render(<PartnerStatusRejectedPage />);
    fireEvent.click(screen.getByTestId("partner-resubmit-cta"));
    expect(screen.queryByTestId("partner-resubmitted")).not.toBeInTheDocument();
    expect(screen.getByTestId("partner-resubmit-cta")).toBeEnabled();
  });
});
