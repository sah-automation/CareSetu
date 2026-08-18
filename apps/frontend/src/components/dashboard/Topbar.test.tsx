import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

import { Topbar } from "./Topbar";
import { AuthProvider } from "@/lib/auth/AuthContext";
import type { StoredSession } from "@/lib/auth/session";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const VALID_SESSION: StoredSession = {
  jwt: "test-jwt-token",
  refresh_token: "test-refresh-token",
  jti: "jti-1",
  scope: "patient",
  identity_id: 42,
  phone: "+911234567890",
};

const ME_RESPONSE_MULTI_ROLE = {
  identity_id: 42,
  phone: "+911234567890",
  roles: ["patient", "partner"],
};

const ME_RESPONSE_SINGLE_ROLE = {
  identity_id: 42,
  phone: "+911234567890",
  roles: ["patient"],
};

function setStoredSession(session: StoredSession) {
  localStorage.setItem("caresetu.session", JSON.stringify(session));
  localStorage.setItem("caresetu.access_jwt", session.jwt);
  localStorage.setItem("caresetu.refresh_token", session.refresh_token);
}

function renderWithAuth(ui: React.ReactNode) {
  return render(<AuthProvider>{ui}</AuthProvider>);
}

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockReplace = vi.fn();
const stableRouter = { replace: mockReplace };

vi.mock("next/navigation", () => ({
  useRouter: () => stableRouter,
  usePathname: () => "/patient",
}));

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
  mockReplace.mockReset();
});

afterEach(() => {
  cleanup();
});

describe("Topbar", () => {
  it("displays user phone after auth loads", async () => {
    setStoredSession(VALID_SESSION);
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(ME_RESPONSE_SINGLE_ROLE), { status: 200 }),
    );

    renderWithAuth(<Topbar />);

    const { waitFor } = await import("@testing-library/react");
    await waitFor(() => {
      expect(screen.getByTestId("topbar")).toBeInTheDocument();
    });

    expect(screen.getByText("+911234567890")).toBeInTheDocument();
  });

  it("shows current role badge", async () => {
    setStoredSession(VALID_SESSION);
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(ME_RESPONSE_SINGLE_ROLE), { status: 200 }),
    );

    renderWithAuth(<Topbar />);

    const { waitFor } = await import("@testing-library/react");
    await waitFor(() => {
      expect(screen.getByText("Patient")).toBeInTheDocument();
    });
  });

  it("shows role switcher when user has multiple roles", async () => {
    setStoredSession(VALID_SESSION);
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(ME_RESPONSE_MULTI_ROLE), { status: 200 }),
    );

    renderWithAuth(<Topbar />);

    const { waitFor } = await import("@testing-library/react");
    await waitFor(() => {
      expect(screen.getByTestId("role-switcher")).toBeInTheDocument();
    });
  });

  it("does not show role switcher when user has single role", async () => {
    setStoredSession(VALID_SESSION);
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(ME_RESPONSE_SINGLE_ROLE), { status: 200 }),
    );

    renderWithAuth(<Topbar />);

    const { waitFor } = await import("@testing-library/react");
    await waitFor(() => {
      expect(screen.getByText("+911234567890")).toBeInTheDocument();
    });

    expect(screen.queryByTestId("role-switcher")).not.toBeInTheDocument();
  });

  it("logout button calls logout and redirects to /", async () => {
    setStoredSession(VALID_SESSION);
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(ME_RESPONSE_SINGLE_ROLE), { status: 200 }),
    );

    renderWithAuth(<Topbar />);

    const { waitFor } = await import("@testing-library/react");
    await waitFor(() => {
      expect(screen.getByTestId("logout-button")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("logout-button"));

    await waitFor(() => {
      expect(localStorage.getItem("caresetu.session")).toBeNull();
      expect(mockReplace).toHaveBeenCalledWith("/");
    });
  });

  it("shows role options in dropdown when opened", async () => {
    setStoredSession(VALID_SESSION);
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(ME_RESPONSE_MULTI_ROLE), { status: 200 }),
    );

    renderWithAuth(<Topbar />);

    const { waitFor } = await import("@testing-library/react");
    await waitFor(() => {
      expect(screen.getByTestId("role-switcher")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("role-switcher"));

    expect(screen.getByTestId("switch-to-partner")).toBeInTheDocument();
  });

  it("switching role updates the displayed badge", async () => {
    setStoredSession(VALID_SESSION);
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(ME_RESPONSE_MULTI_ROLE), { status: 200 }),
    );

    renderWithAuth(<Topbar />);

    const { waitFor } = await import("@testing-library/react");
    await waitFor(() => {
      expect(screen.getByText("Patient")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("role-switcher"));
    fireEvent.click(screen.getByTestId("switch-to-partner"));

    await waitFor(() => {
      expect(screen.getByText("Partner")).toBeInTheDocument();
    });
  });
});
