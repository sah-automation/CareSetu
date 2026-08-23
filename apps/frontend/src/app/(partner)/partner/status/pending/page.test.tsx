// PHASE-2.6 T10 (#201): the pending state screen mounts inside the full
// partner shell, shows the §4.4 status card, and stays honest about the
// verification data that only Phase 5 can supply.

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import PartnerStatusPendingPage from "./page";
import PartnerGroupLayout from "@/app/(partner)/layout";
import { useAuth } from "@/lib/auth/AuthContext";
import { STRINGS } from "@/lib/i18n/dictionaries";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  usePathname: () => "/partner/status/pending",
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

describe("PartnerStatusPendingPage (inside the full shell)", () => {
  it("mounts within the partner AppShell behind the session guard's group", () => {
    render(
      <PartnerGroupLayout>
        <PartnerStatusPendingPage />
      </PartnerGroupLayout>,
    );
    // Full-shell chrome + the status card are both present.
    expect(screen.getByTestId("app-shell")).toBeInTheDocument();
    expect(screen.getByTestId("topbar")).toBeInTheDocument();
    expect(screen.getByTestId("partner-pending-card")).toBeInTheDocument();
  });

  it("shows the under-verification state card per blueprint §4.4", () => {
    render(<PartnerStatusPendingPage />);
    const t = STRINGS.en.staffAuth.pending;
    expect(screen.getByTestId("partner-status-badge")).toHaveTextContent(
      t.badge,
    );
    expect(screen.getByRole("heading", { name: t.title })).toBeInTheDocument();
    expect(screen.getByTestId("partner-pending-note")).toHaveTextContent(
      t.infoBanner,
    );
  });

  it("keeps Phase 5 data fields as honest placeholders, not fabricated values", () => {
    render(<PartnerStatusPendingPage />);
    const t = STRINGS.en.staffAuth.pending;
    const placeholders = screen.getAllByText(t.detailPlaceholder);
    // Submitted-at, application identity, verifying-scope all defer to Phase 5.
    expect(placeholders).toHaveLength(3);
    expect(screen.getByText(t.windowValue)).toBeInTheDocument();
  });

  it("carries the help contact affordance", () => {
    render(<PartnerStatusPendingPage />);
    expect(screen.getByTestId("partner-help-link")).toHaveTextContent(
      STRINGS.en.staffAuth.pending.helpCta,
    );
  });
});
