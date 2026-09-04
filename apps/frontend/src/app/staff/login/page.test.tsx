// PHASE-2.6 T10 (#201): the /staff/login surface - composition distinct from
// the patient wizard, registration CTAs, and the authenticated-visitor
// routing through the §4.5 matrix (single role -> home; multi-role ->
// scoped picker; no staff role -> stays on the form).

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

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

  it("renders the partner form by default - no phone or TOTP fields", () => {
    render(<StaffLoginPage />);
    expect(screen.getByTestId("staff-email")).toBeInTheDocument();
    expect(screen.getByTestId("staff-password")).toBeInTheDocument();
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
    expect(screen.getByTestId("staff-email")).toBeInTheDocument();
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
});
