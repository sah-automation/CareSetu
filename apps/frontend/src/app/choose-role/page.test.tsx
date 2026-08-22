import {
  render,
  screen,
  fireEvent,
  waitFor,
  cleanup,
} from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

import ChooseRolePage from "./page";
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

function setStoredSession(session: StoredSession) {
  localStorage.setItem("caresetu.session", JSON.stringify(session));
  localStorage.setItem("caresetu.access_jwt", session.jwt);
  localStorage.setItem("caresetu.refresh_token", session.refresh_token);
}

function mockMeResponse(roles: string[]) {
  return vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
    new Response(
      JSON.stringify({
        identity_id: 42,
        phone: "+911234567890",
        roles,
      }),
      { status: 200 },
    ),
  );
}

// The page reads session state through the shared AuthProvider (mounted at
// the root layout in the app), so tests wrap it the same way.
function renderPage() {
  return render(
    <AuthProvider>
      <ChooseRolePage />
    </AuthProvider>,
  );
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

describe("ChooseRolePage", () => {
  it("redirects to /login when no session is stored", async () => {
    renderPage();

    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith("/login");
    });
  });

  it("redirects to /login when /v1/me fails", async () => {
    setStoredSession(VALID_SESSION);
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response("", { status: 401 }),
    );

    renderPage();

    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith("/login");
    });
  });

  it("redirects to /login on network error", async () => {
    setStoredSession(VALID_SESSION);
    vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(
      new TypeError("Failed to fetch"),
    );

    renderPage();

    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith("/login");
    });
  });

  it("redirects directly to /{role} when user has only one role", async () => {
    setStoredSession(VALID_SESSION);
    mockMeResponse(["patient"]);

    renderPage();

    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith("/patient");
      expect(localStorage.getItem("caresetu.selected_role")).toBe("patient");
    });
  });

  it("redirects to saved role when already selected", async () => {
    setStoredSession(VALID_SESSION);
    localStorage.setItem("caresetu.selected_role", "partner");
    mockMeResponse(["patient", "partner"]);

    renderPage();

    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith("/partner");
    });
  });

  it("shows role cards when multiple roles and no saved selection", async () => {
    setStoredSession(VALID_SESSION);
    mockMeResponse(["patient", "partner"]);

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Choose your role")).toBeInTheDocument();
    });

    expect(screen.getByText("Patient")).toBeInTheDocument();
    expect(
      screen.getByText("Access your health records and consultations"),
    ).toBeInTheDocument();
    expect(screen.getByText("Partner")).toBeInTheDocument();
    expect(
      screen.getByText("Manage partner clinic operations"),
    ).toBeInTheDocument();
  });

  it("clicking a role card saves role and redirects", async () => {
    setStoredSession(VALID_SESSION);
    mockMeResponse(["patient", "partner"]);

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Patient")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("Patient"));

    expect(localStorage.getItem("caresetu.selected_role")).toBe("patient");
    expect(mockReplace).toHaveBeenCalledWith("/patient");
  });

  it("redirects to /login when /v1/me returns empty roles", async () => {
    setStoredSession(VALID_SESSION);
    mockMeResponse([]);

    renderPage();

    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith("/login");
    });
  });

  it("renders fallback label for unknown role", async () => {
    setStoredSession(VALID_SESSION);
    mockMeResponse(["patient", "admin"]);

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Patient")).toBeInTheDocument();
    });

    expect(screen.getByText("Admin")).toBeInTheDocument();
    expect(screen.getByText("Access the admin dashboard")).toBeInTheDocument();
  });

  it("ignores saved role not present in user roles", async () => {
    setStoredSession(VALID_SESSION);
    localStorage.setItem("caresetu.selected_role", "nonexistent");
    mockMeResponse(["patient", "partner"]);

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Choose your role")).toBeInTheDocument();
    });

    expect(mockReplace).not.toHaveBeenCalled();
  });
});
