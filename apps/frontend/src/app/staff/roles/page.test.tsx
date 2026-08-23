// PHASE-2.6 T10 (#201): the scoped staff-role picker - staff-only scoping,
// single-role bounce, unauthenticated bounce, and honest selection behavior.
// The interim /choose-role entry is untouched; this is its §4.5 successor for
// multi-staff-role accounts only.

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import StaffRolesPage from "./page";
import { useAuth } from "@/lib/auth/AuthContext";
import { readSelectedRole, saveSelectedRole } from "@/lib/auth/session";

const mockReplace = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mockReplace }),
}));

vi.mock("@/lib/auth/AuthContext", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/auth/AuthContext")>();
  return { ...mod, useAuth: vi.fn() };
});

const switchRole = vi.fn();

function mockSession(roles: string[] | null) {
  vi.mocked(useAuth).mockReturnValue({
    user: roles === null ? null : { id: 7, phone: "+911234567890", roles },
    selectedRole: null,
    switchRole,
    logout: vi.fn(),
    isAuthenticated: roles !== null,
    isLoading: false,
  });
}

beforeEach(() => {
  window.localStorage.clear();
});

afterEach(() => {
  cleanup();
  mockReplace.mockReset();
  switchRole.mockReset();
  vi.clearAllMocks();
  window.localStorage.clear();
  mockSession(null);
});

mockSession(null);

describe("StaffRolesPage - scoped picker", () => {
  it("bounces an unauthenticated visitor back to the staff login surface", async () => {
    render(<StaffRolesPage />);
    await waitFor(() =>
      expect(mockReplace).toHaveBeenCalledWith("/staff/login"),
    );
  });

  it("bounces a session with no staff role to the interim choose-role entry", async () => {
    mockSession(["patient"]);
    render(<StaffRolesPage />);
    await waitFor(() =>
      expect(mockReplace).toHaveBeenCalledWith("/choose-role"),
    );
  });

  it("skips the picker entirely for a single staff role", async () => {
    mockSession(["operator"]);
    render(<StaffRolesPage />);
    await waitFor(() => expect(mockReplace).toHaveBeenCalledWith("/operator"));
    expect(readSelectedRole()).toBe("operator");
    expect(screen.queryByTestId("staff-role-picker")).not.toBeInTheDocument();
  });

  it("shows one card per staff role and never a patient card", () => {
    mockSession(["doctor", "partner", "operator", "patient"]);
    render(<StaffRolesPage />);
    expect(screen.getByTestId("staff-role-picker")).toBeInTheDocument();
    expect(screen.getByTestId("pick-doctor")).toBeInTheDocument();
    expect(screen.getByTestId("pick-partner")).toBeInTheDocument();
    expect(screen.getByTestId("pick-operator")).toBeInTheDocument();
    expect(screen.queryByTestId("pick-patient")).not.toBeInTheDocument();
  });

  it("routes through the chosen console on click and persists the choice", () => {
    mockSession(["doctor", "operator"]);
    render(<StaffRolesPage />);
    fireEvent.click(screen.getByTestId("pick-operator"));
    expect(switchRole).toHaveBeenCalledWith("operator");
    expect(mockReplace).toHaveBeenCalledWith("/operator");
  });

  it("short-circuits to a previously saved valid staff choice", async () => {
    saveSelectedRole("partner");
    mockSession(["doctor", "partner"]);
    render(<StaffRolesPage />);
    await waitFor(() => expect(mockReplace).toHaveBeenCalledWith("/partner"));
    expect(switchRole).not.toHaveBeenCalled();
  });
});
