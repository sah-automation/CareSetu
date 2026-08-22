// PHASE-2.6 T06 (#197): suite for the shared density-aware top bar - light
// top-nav derivation, full page-title slot, §2.6 account cluster behaviors
// against the real AuthProvider, and the language toggle.

import {
  render,
  screen,
  fireEvent,
  cleanup,
  waitFor,
} from "@testing-library/react";
import {
  describe,
  it,
  expect,
  vi,
  beforeAll,
  beforeEach,
  afterEach,
} from "vitest";

import { Topbar } from "./Topbar";
import type { Role } from "./types";
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

function renderTopbar(density: "light" | "full", role: Role = "patient") {
  return render(
    <AuthProvider>
      <Topbar density={density} role={role} />
    </AuthProvider>,
  );
}

// Radix popper relies on ResizeObserver and opens menus on real pointer
// events, neither of which jsdom implements fully. Vitest isolates each test
// file in its own jsdom environment, so these stubs cannot leak elsewhere.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}

beforeAll(() => {
  window.ResizeObserver =
    window.ResizeObserver ??
    (ResizeObserverStub as unknown as typeof ResizeObserver);
  if (!window.PointerEvent) {
    class PointerEventStub extends MouseEvent {}
    window.PointerEvent = PointerEventStub as unknown as typeof PointerEvent;
  }
});

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

describe("Topbar densities", () => {
  it("light shell carries the brand wordmark and the slim desktop top-nav", async () => {
    setStoredSession(VALID_SESSION);
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(ME_RESPONSE_SINGLE_ROLE), { status: 200 }),
    );

    renderTopbar("light");

    await waitFor(() =>
      expect(screen.getByTestId("topnav")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("topbar")).toHaveAttribute(
      "data-density",
      "light",
    );
    expect(screen.getByTestId("topnav").textContent).toContain("Find Care");
    // The center accent slot never duplicates into the top-nav.
    expect(screen.getByTestId("topnav").textContent).not.toContain("Start");
  });

  it("full shell exposes the page-title slot instead of a top-nav", async () => {
    setStoredSession(VALID_SESSION);
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(ME_RESPONSE_SINGLE_ROLE), { status: 200 }),
    );

    renderTopbar("full", "operator");

    await waitFor(() =>
      expect(screen.getByTestId("topbar-page-slot")).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("topnav")).not.toBeInTheDocument();
  });
});

describe("Topbar account cluster", () => {
  function openAccountMenu() {
    fireEvent.pointerDown(screen.getByTestId("account-menu"));
    fireEvent.click(screen.getByTestId("account-menu"));
  }

  it("shows the user phone inside the opened account menu", async () => {
    setStoredSession(VALID_SESSION);
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(ME_RESPONSE_SINGLE_ROLE), { status: 200 }),
    );

    renderTopbar("light");
    await waitFor(() =>
      expect(screen.getByTestId("account-menu")).toBeInTheDocument(),
    );

    openAccountMenu();

    expect(screen.getByText("+911234567890")).toBeInTheDocument();
  });

  it("shows the current role badge inside the opened account menu", async () => {
    setStoredSession(VALID_SESSION);
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(ME_RESPONSE_SINGLE_ROLE), { status: 200 }),
    );

    renderTopbar("light");
    await waitFor(() =>
      expect(screen.getByTestId("account-menu")).toBeInTheDocument(),
    );

    openAccountMenu();

    expect(screen.getByTestId("account-menu-role-badge")).toHaveTextContent(
      "Patient",
    );
  });

  it("language toggle flips nav labels through the i18n engine", async () => {
    setStoredSession(VALID_SESSION);
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(ME_RESPONSE_SINGLE_ROLE), { status: 200 }),
    );

    renderTopbar("light");
    await waitFor(() =>
      expect(screen.getByTestId("lang-toggle")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("nav-home")).toHaveTextContent("Home");

    fireEvent.click(screen.getByRole("button", { name: "हिं" }));

    await waitFor(() =>
      expect(screen.getByTestId("nav-home")).toHaveTextContent("होम"),
    );
    expect(localStorage.getItem("caresetu.lang")).toBe("hi");
  });

  it("opens the account menu with switch-role options for multi-role users", async () => {
    setStoredSession(VALID_SESSION);
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(ME_RESPONSE_MULTI_ROLE), { status: 200 }),
    );

    renderTopbar("light");
    await waitFor(() =>
      expect(screen.getByTestId("account-menu")).toBeInTheDocument(),
    );

    fireEvent.pointerDown(screen.getByTestId("account-menu"));
    fireEvent.click(screen.getByTestId("account-menu"));

    expect(screen.getByTestId("switch-to-partner")).toBeInTheDocument();
  });

  it("switching role updates the displayed badge", async () => {
    setStoredSession(VALID_SESSION);
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(JSON.stringify(ME_RESPONSE_MULTI_ROLE), { status: 200 }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(ME_RESPONSE_MULTI_ROLE), { status: 200 }),
      );

    renderTopbar("light");
    await waitFor(() =>
      expect(screen.getByTestId("account-menu")).toBeInTheDocument(),
    );

    openAccountMenu();
    fireEvent.click(screen.getByTestId("switch-to-partner"));

    // The menu closes on selection; reopening shows the flipped badge.
    await waitFor(() =>
      expect(screen.queryByRole("menu")).not.toBeInTheDocument(),
    );
    openAccountMenu();

    await waitFor(() =>
      expect(screen.getByTestId("account-menu-role-badge")).toHaveTextContent(
        "Partner",
      ),
    );
  });

  it("logout clears the session and redirects home", async () => {
    setStoredSession(VALID_SESSION);
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(ME_RESPONSE_SINGLE_ROLE), { status: 200 }),
    );

    renderTopbar("light");
    await waitFor(() =>
      expect(screen.getByTestId("account-menu")).toBeInTheDocument(),
    );

    fireEvent.pointerDown(screen.getByTestId("account-menu"));
    fireEvent.click(screen.getByTestId("account-menu"));
    fireEvent.click(screen.getByTestId("logout-button"));

    await waitFor(() => {
      expect(localStorage.getItem("caresetu.session")).toBeNull();
      expect(mockReplace).toHaveBeenCalledWith("/");
    });
  });

  it("PHASE-2.6 T08: the same account cluster serves the full-shell density", async () => {
    const operatorSession = { ...VALID_SESSION, scope: "operator" };
    setStoredSession(operatorSession);
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          identity_id: 42,
          phone: "+911234567890",
          roles: ["operator"],
        }),
        { status: 200 },
      ),
    );

    renderTopbar("full", "operator");
    await waitFor(() =>
      expect(screen.getByTestId("account-menu")).toBeInTheDocument(),
    );

    openAccountMenu();

    expect(screen.getByText("+911234567890")).toBeInTheDocument();
    expect(screen.getByTestId("account-menu-role-badge")).toHaveTextContent(
      "Operator",
    );
    expect(
      screen.getByRole("menuitem", { name: "Logout" }),
    ).toBeInTheDocument();
  });
});
