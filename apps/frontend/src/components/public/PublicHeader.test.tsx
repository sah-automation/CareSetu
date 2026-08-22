// PHASE-2.6 T09 (#200): suite for homepage section 1 - the sticky public
// header. Anchors + EN/Hindi toggle + the session-aware auth button that
// reads truthfully from root AuthContext (Login -> /login when signed out;
// Dashboard -> role dashboard when signed in, blueprint §3.2).

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

import { PublicHeader } from "./PublicHeader";
import type { StoredSession } from "@/lib/auth/session";
import { AuthProvider } from "@/lib/auth/AuthContext";
import { __resetLangForTests } from "@/lib/i18n/LangContext";

// Radix-free header, but AuthProvider pulls useRouter via next/navigation.
const mockReplace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mockReplace }),
  usePathname: () => "/",
}));

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
}

function meResponse(roles: string[]) {
  return new Response(
    JSON.stringify({ identity_id: 42, phone: "+911234567890", roles }),
    { status: 200 },
  );
}

function renderHeader() {
  return render(
    <AuthProvider>
      <PublicHeader />
    </AuthProvider>,
  );
}

beforeAll(() => {
  if (!window.PointerEvent) {
    class PointerEventStub extends MouseEvent {}
    window.PointerEvent = PointerEventStub as unknown as typeof PointerEvent;
  }
});

beforeEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
  mockReplace.mockReset();
  __resetLangForTests();
  document.documentElement.lang = "en";
});

afterEach(() => {
  cleanup();
});

describe("PublicHeader", () => {
  it("renders wordmark, anchor nav and language toggle", () => {
    renderHeader();

    const nav = screen.getByRole("navigation", { name: "Primary" });
    expect(nav).toBeInTheDocument();
    const anchors = [...nav.querySelectorAll("a")].map((a) =>
      a.getAttribute("href"),
    );
    expect(anchors).toEqual(["#doctors", "#labs", "#chemists"]);
    expect(screen.getByRole("group", { name: "Language" })).toBeInTheDocument();
    expect(screen.getByText("CareSetu").closest("a")).toHaveAttribute(
      "href",
      "/",
    );
  });

  it("reads Login -> /login for an anonymous visitor", () => {
    renderHeader();

    const button = screen.getByTestId("header-auth-button");
    expect(button).toHaveTextContent("Login");
    expect(button).toHaveAttribute("href", "/login");
  });

  it("reads Dashboard -> /patient for a signed-in patient", async () => {
    setStoredSession(VALID_SESSION);
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      meResponse(["patient"]),
    );

    renderHeader();

    await waitFor(() =>
      expect(screen.getByTestId("header-auth-button")).toHaveTextContent(
        "Dashboard",
      ),
    );
    expect(screen.getByTestId("header-auth-button")).toHaveAttribute(
      "href",
      "/patient",
    );
  });

  it("routes Dashboard to the selected staff role dashboard", async () => {
    setStoredSession(VALID_SESSION);
    localStorage.setItem("caresetu.selected_role", "partner");
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      meResponse(["partner"]),
    );

    renderHeader();

    await waitFor(() =>
      expect(screen.getByTestId("header-auth-button")).toHaveAttribute(
        "href",
        "/partner",
      ),
    );
  });

  it("flips its labels through the i18n engine and tracks html lang", async () => {
    renderHeader();

    fireEvent.click(screen.getByRole("button", { name: "\u0939\u093F\u0902" }));

    const nav = screen.getByRole("navigation", { name: "Primary" });
    await waitFor(() =>
      expect(nav.textContent).toContain("\u0921\u0949\u0915\u094D\u091F\u0930"),
    );
    expect(document.documentElement.lang).toBe("hi");
    expect(screen.getByTestId("header-auth-button")).toHaveTextContent(
      "\u0932\u0949\u0917\u093F\u0928",
    );

    fireEvent.click(screen.getByRole("button", { name: "EN" }));
    await waitFor(() => expect(document.documentElement.lang).toBe("en"));
  });
});
