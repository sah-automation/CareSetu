// PHASE-2.6 T10 (#201): the /staff/login surface - composition distinct from
// the patient wizard, registration CTAs, and the authenticated-visitor
// routing through the §4.5 matrix (single role -> home; multi-role ->
// scoped picker; no staff role -> stays on the form).

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import StaffLoginPage from "./page";
import { useAuth } from "@/lib/auth/AuthContext";

const mockReplace = vi.fn();
let searchParamsValue = new URLSearchParams();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mockReplace }),
  useSearchParams: () => searchParamsValue,
}));

vi.mock("@/lib/auth/AuthContext", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/auth/AuthContext")>();
  return { ...mod, useAuth: vi.fn() };
});

const mockFetchPartnerMe = vi.fn();
vi.mock("@/lib/partner/api", () => ({
  fetchPartnerMe: (...args: unknown[]) => mockFetchPartnerMe(...args),
}));

function mockSession(roles: string[] | null) {
  vi.mocked(useAuth).mockReturnValue({
    user: roles === null ? null : { id: 1, phone: "+911234567890", roles },
    selectedRole: null,
    switchRole: vi.fn(),
    logout: vi.fn(),
    isAuthenticated: roles !== null,
    isLoading: false,
  });
}

beforeEach(() => {
  // Default an already-active partner so non-state tests route by role alone.
  mockFetchPartnerMe.mockReset().mockResolvedValue({
    partner_id: 1,
    partner_type: "doctor",
    round: 1,
    status: "Active",
  });
});

afterEach(() => {
  cleanup();
  mockReplace.mockReset();
  searchParamsValue = new URLSearchParams();
  vi.clearAllMocks();
  mockSession(null);
});

// Default session for the first render of every suite.
mockSession(null);

describe("StaffLoginPage", () => {
  it("renders the staff sign-in card for a signed-out visitor", () => {
    render(<StaffLoginPage />);
    expect(screen.getByTestId("staff-login-form")).toBeInTheDocument();
    expect(screen.getByText(/Staff sign-in/)).toBeInTheDocument();
    expect(mockReplace).not.toHaveBeenCalled();
  });

  it("renders the partner phone-OTP form by default - no email, password, or operator fields", () => {
    render(<StaffLoginPage />);
    expect(screen.getByTestId("partner-phone")).toBeInTheDocument();
    expect(screen.queryByTestId("staff-email")).not.toBeInTheDocument();
    expect(screen.queryByTestId("staff-password")).not.toBeInTheDocument();
    expect(screen.queryByTestId("staff-phone")).not.toBeInTheDocument();
    expect(screen.queryByTestId("staff-totp")).not.toBeInTheDocument();
  });

  it("renders the operator form when role=operator is passed", () => {
    searchParamsValue = new URLSearchParams({ role: "operator" });
    render(<StaffLoginPage />);
    expect(screen.getByTestId("staff-phone")).toBeInTheDocument();
    expect(screen.getByTestId("staff-totp")).toBeInTheDocument();
    expect(screen.queryByTestId("staff-email")).not.toBeInTheDocument();
    expect(screen.queryByTestId("staff-password")).not.toBeInTheDocument();
  });

  it("falls back to partner mode for an unknown role param", () => {
    searchParamsValue = new URLSearchParams({ role: "doctor" });
    render(<StaffLoginPage />);
    expect(screen.getByTestId("partner-phone")).toBeInTheDocument();
    expect(screen.queryByTestId("staff-email")).not.toBeInTheDocument();
    expect(screen.queryByTestId("staff-phone")).not.toBeInTheDocument();
  });

  it("links the type-preset registration CTAs to the wizard route", () => {
    render(<StaffLoginPage />);
    expect(screen.getByTestId("register-doctor")).toHaveAttribute(
      "href",
      "/staff/register?type=doctor",
    );
    expect(screen.getByTestId("register-lab")).toHaveAttribute(
      "href",
      "/staff/register?type=lab",
    );
    expect(screen.getByTestId("register-chemist")).toHaveAttribute(
      "href",
      "/staff/register?type=chemist",
    );
  });

  it("keeps the interim choose-role entry reachable", () => {
    render(<StaffLoginPage />);
    expect(screen.getByTestId("choose-role-link")).toHaveAttribute(
      "href",
      "/choose-role",
    );
  });

  it("routes an already-signed-in single-staff-role session to its home", async () => {
    mockSession(["operator"]);
    render(<StaffLoginPage />);
    await waitFor(() => expect(mockReplace).toHaveBeenCalledWith("/operator"));
  });

  it("routes a multi-staff-role session to the scoped picker", async () => {
    mockSession(["doctor", "partner"]);
    searchParamsValue = new URLSearchParams({ return: "/staff/roles" });
    render(<StaffLoginPage />);
    await waitFor(() =>
      expect(mockReplace).toHaveBeenCalledWith("/staff/roles"),
    );
  });

  it("does not bounce a patient-only session off the form", () => {
    mockSession(["patient"]);
    render(<StaffLoginPage />);
    expect(mockReplace).not.toHaveBeenCalled();
    expect(screen.getByTestId("staff-login-form")).toBeInTheDocument();
  });

  it("honors a return deep link into the owned territory", async () => {
    mockSession(["doctor"]);
    searchParamsValue = new URLSearchParams({ return: "/doctor/cases/9" });
    render(<StaffLoginPage />);
    await waitFor(() =>
      expect(mockReplace).toHaveBeenCalledWith("/doctor/cases/9"),
    );
  });

  it.each([
    ["Registered", "/partner/status/pending"],
    ["Under Verification", "/partner/status/pending"],
    ["Rejected", "/partner/status/rejected"],
  ] as const)(
    "routes an already-signed-in %s partner to its status screen",
    async (status, expected) => {
      mockFetchPartnerMe.mockResolvedValue({
        partner_id: 1,
        partner_type: "doctor",
        round: 1,
        status,
      });
      mockSession(["partner"]);
      render(<StaffLoginPage />);
      await waitFor(() => expect(mockReplace).toHaveBeenCalledWith(expected));
      expect(mockFetchPartnerMe).toHaveBeenCalled();
    },
  );

  it("routes an already-signed-in active partner to the partner home", async () => {
    mockFetchPartnerMe.mockResolvedValue({
      partner_id: 1,
      partner_type: "doctor",
      round: 1,
      status: "Active",
    });
    mockSession(["partner"]);
    render(<StaffLoginPage />);
    await waitFor(() => expect(mockReplace).toHaveBeenCalledWith("/partner"));
  });

  it("routes an already-signed-in active partner to the return deep link (F014-T09b)", async () => {
    mockFetchPartnerMe.mockResolvedValue({
      partner_id: 1,
      partner_type: "doctor",
      round: 1,
      status: "Active",
    });
    mockSession(["partner"]);
    searchParamsValue = new URLSearchParams({ return: "/partner/orders/42" });
    render(<StaffLoginPage />);
    await waitFor(() =>
      expect(mockReplace).toHaveBeenCalledWith("/partner/orders/42"),
    );
  });

  it("lets a partner-state override win over a stale return target", async () => {
    mockFetchPartnerMe.mockResolvedValue({
      partner_id: 1,
      partner_type: "doctor",
      round: 1,
      status: "Rejected",
    });
    mockSession(["partner", "operator"]);
    searchParamsValue = new URLSearchParams({ return: "/operator" });
    render(<StaffLoginPage />);
    await waitFor(() =>
      expect(mockReplace).toHaveBeenCalledWith("/partner/status/rejected"),
    );
  });

  it("falls back to role-based routing when the partner status read fails", async () => {
    mockFetchPartnerMe.mockRejectedValue(new TypeError("Failed to fetch"));
    mockSession(["partner"]);
    render(<StaffLoginPage />);
    await waitFor(() => expect(mockReplace).toHaveBeenCalledWith("/partner"));
  });

  it("does not read partner status for a non-partner staff session", async () => {
    mockSession(["doctor"]);
    render(<StaffLoginPage />);
    await waitFor(() => expect(mockReplace).toHaveBeenCalledWith("/doctor"));
    expect(mockFetchPartnerMe).not.toHaveBeenCalled();
  });
});
