// PHASE-2.6 T07 (#198): the login surface owns the proxy's `return` param.
// Covered here: the sanitized target is passed down to the wizard, an
// already-authenticated visitor is routed to the return target, and off-site
// or missing values fall back to the patient home.

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import LoginPage from "./page";
import { useAuth } from "@/lib/auth/AuthContext";

vi.mock("@/components/auth/otp/PatientAuthWizard", () => ({
  PatientAuthWizard: vi.fn(({ returnTo }: { returnTo?: string }) => (
    <div data-testid="wizard" data-return-to={returnTo} />
  )),
}));

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

vi.mocked(useAuth).mockReturnValue({
  user: null,
  selectedRole: null,
  switchRole: vi.fn(),
  logout: vi.fn(),
  isAuthenticated: false,
  isLoading: false,
});

afterEach(() => {
  cleanup();
  mockReplace.mockReset();
  searchParamsValue = new URLSearchParams();
  vi.clearAllMocks();
  vi.mocked(useAuth).mockReturnValue({
    user: null,
    selectedRole: null,
    switchRole: vi.fn(),
    logout: vi.fn(),
    isAuthenticated: false,
    isLoading: false,
  });
});

describe("LoginPage - return param handling", () => {
  it.each([
    ["/patient/bookings", "/patient/bookings"],
    ["", "/patient"],
    ["https://evil.example", "/patient"],
    ["//evil.example", "/patient"],
    ["/\\evil.example", "/patient"],
  ])("return=%p passes %p down to the wizard", (raw, expected) => {
    searchParamsValue = new URLSearchParams({ return: raw });
    render(<LoginPage />);
    expect(screen.getByTestId("wizard").getAttribute("data-return-to")).toBe(
      expected,
    );
    expect(mockReplace).not.toHaveBeenCalled();
  });

  it("routes an authenticated visitor to the return target", async () => {
    vi.mocked(useAuth).mockReturnValue({
      user: null,
      selectedRole: null,
      switchRole: vi.fn(),
      logout: vi.fn(),
      isAuthenticated: true,
      isLoading: false,
    });
    searchParamsValue = new URLSearchParams({ return: "/patient/record" });

    render(<LoginPage />);

    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith("/patient/record");
    });
  });
});
