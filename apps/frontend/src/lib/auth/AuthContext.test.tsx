import { render, screen, waitFor, cleanup } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import type { ReactNode } from "react";

import { AuthProvider, useAuth, type AuthContextValue } from "./AuthContext";
import type { StoredSession } from "./session";

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

const ME_RESPONSE = {
  identity_id: 42,
  phone: "+911234567890",
  roles: ["patient", "partner"],
};

const REFRESH_RESPONSE = {
  jwt: "refreshed-jwt",
  refresh_token: "refreshed-refresh",
};

function setStoredSession(session: StoredSession) {
  localStorage.setItem("caresetu.session", JSON.stringify(session));
  localStorage.setItem("caresetu.access_jwt", session.jwt);
  localStorage.setItem("caresetu.refresh_token", session.refresh_token);
}

function TestConsumer() {
  const auth = useAuth();
  return (
    <div>
      <span data-testid="is-loading">{String(auth.isLoading)}</span>
      <span data-testid="is-authenticated">{String(auth.isAuthenticated)}</span>
      <span data-testid="user-id">{auth.user?.id ?? "null"}</span>
      <span data-testid="user-phone">{auth.user?.phone ?? "null"}</span>
      <span data-testid="roles">{auth.user?.roles?.join(",") ?? "none"}</span>
      <span data-testid="selected-role">{auth.selectedRole ?? "none"}</span>
      <button onClick={() => auth.switchRole("partner")}>switch</button>
      <button onClick={auth.logout}>logout</button>
    </div>
  );
}

function renderWithAuth(ui?: ReactNode) {
  return render(<AuthProvider>{ui ?? <TestConsumer />}</AuthProvider>);
}

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockReplace = vi.fn();
const stableRouter = { replace: mockReplace };

vi.mock("next/navigation", () => ({
  useRouter: () => stableRouter,
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

describe("AuthProvider", () => {
  it("shows loading then unauthenticated when no session is stored", async () => {
    renderWithAuth();

    await waitFor(() => {
      expect(screen.getByTestId("is-loading").textContent).toBe("false");
    });

    expect(screen.getByTestId("is-authenticated").textContent).toBe("false");
    expect(screen.getByTestId("user-id").textContent).toBe("null");
  });

  it("validates session via GET /v1/me and populates user", async () => {
    setStoredSession(VALID_SESSION);

    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(ME_RESPONSE), { status: 200 }),
    );

    renderWithAuth();

    await waitFor(() => {
      expect(screen.getByTestId("is-loading").textContent).toBe("false");
    });

    expect(screen.getByTestId("is-authenticated").textContent).toBe("true");
    expect(screen.getByTestId("user-id").textContent).toBe("42");
    expect(screen.getByTestId("user-phone").textContent).toBe("+911234567890");
    expect(screen.getByTestId("roles").textContent).toBe("patient,partner");
    expect(screen.getByTestId("selected-role").textContent).toBe("patient");

    expect(globalThis.fetch).toHaveBeenCalledWith(
      "http://localhost:8000/v1/me",
      { headers: { Authorization: "Bearer test-jwt-token" } },
    );
  });

  it("refreshes JWT when /v1/me returns 401 then retries", async () => {
    setStoredSession(VALID_SESSION);

    const fetchSpy = vi.spyOn(globalThis, "fetch");

    // First call: /v1/me returns 401
    fetchSpy.mockResolvedValueOnce(new Response("", { status: 401 }));
    // Second call: /v1/auth/refresh succeeds
    fetchSpy.mockResolvedValueOnce(
      new Response(JSON.stringify(REFRESH_RESPONSE), { status: 200 }),
    );
    // Third call: /v1/me with new JWT succeeds
    fetchSpy.mockResolvedValueOnce(
      new Response(JSON.stringify(ME_RESPONSE), { status: 200 }),
    );

    renderWithAuth();

    await waitFor(() => {
      expect(screen.getByTestId("is-authenticated").textContent).toBe("true");
    });

    expect(fetchSpy).toHaveBeenCalledTimes(3);
    expect(fetchSpy.mock.calls[1][0]).toBe(
      "http://localhost:8000/v1/auth/refresh",
    );

    // New tokens should be in localStorage
    expect(localStorage.getItem("caresetu.access_jwt")).toBe("refreshed-jwt");
    expect(localStorage.getItem("caresetu.refresh_token")).toBe(
      "refreshed-refresh",
    );
  });

  it("redirects to /login when refresh also fails", async () => {
    setStoredSession(VALID_SESSION);

    const fetchSpy = vi.spyOn(globalThis, "fetch");

    // /v1/me fails
    fetchSpy.mockResolvedValueOnce(new Response("", { status: 401 }));
    // refresh also fails
    fetchSpy.mockResolvedValueOnce(new Response("", { status: 401 }));

    renderWithAuth();

    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith("/login");
    });

    // Session should be cleared
    expect(localStorage.getItem("caresetu.session")).toBeNull();
  });

  it("redirects to /login when GET /v1/me returns 500 and refresh fails", async () => {
    setStoredSession(VALID_SESSION);

    const fetchSpy = vi.spyOn(globalThis, "fetch");

    fetchSpy.mockResolvedValueOnce(new Response("", { status: 500 }));
    fetchSpy.mockResolvedValueOnce(new Response("", { status: 500 }));

    renderWithAuth();

    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith("/login");
    });
  });

  it("switchRole updates the selected role", async () => {
    setStoredSession(VALID_SESSION);

    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(ME_RESPONSE), { status: 200 }),
    );

    renderWithAuth();

    await waitFor(() => {
      expect(screen.getByTestId("selected-role").textContent).toBe("patient");
    });

    await waitFor(() => {
      screen.getByText("switch").click();
    });

    await waitFor(() => {
      expect(screen.getByTestId("selected-role").textContent).toBe("partner");
    });
  });

  it("logout clears session, cookie, and redirects to /", async () => {
    setStoredSession(VALID_SESSION);

    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(ME_RESPONSE), { status: 200 }),
    );

    renderWithAuth();

    await waitFor(() => {
      expect(screen.getByTestId("is-authenticated").textContent).toBe("true");
    });

    await waitFor(() => {
      screen.getByText("logout").click();
    });

    await waitFor(() => {
      expect(localStorage.getItem("caresetu.session")).toBeNull();
      expect(localStorage.getItem("caresetu.access_jwt")).toBeNull();
      expect(screen.getByTestId("is-authenticated").textContent).toBe("false");
      expect(mockReplace).toHaveBeenCalledWith("/");
    });
  });

  it("handles network errors on /v1/me gracefully by trying refresh", async () => {
    setStoredSession(VALID_SESSION);

    const fetchSpy = vi.spyOn(globalThis, "fetch");

    // Network error on /v1/me
    fetchSpy.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    // Refresh also fails with network error
    fetchSpy.mockRejectedValueOnce(new TypeError("Failed to fetch"));

    renderWithAuth();

    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith("/login");
    });
  });

  it("defaults roles to first role when user has roles", async () => {
    setStoredSession(VALID_SESSION);

    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ ...ME_RESPONSE, roles: ["partner"] }), {
        status: 200,
      }),
    );

    renderWithAuth();

    await waitFor(() => {
      expect(screen.getByTestId("selected-role").textContent).toBe("partner");
    });
  });
});
