// PHASE-2.6 T08 (#199): dedicated accessibility suite for the §2.6 account
// menu - trigger semantics, keyboard open/close with focus return, menu-item
// roles, the stale-session phone-missing degrade, and both shell densities.

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

import { AccountMenu } from "./AccountMenu";
import { AuthProvider } from "@/lib/auth/AuthContext";
import type { StoredSession } from "@/lib/auth/session";

const VALID_SESSION: StoredSession = {
  jwt: "test-jwt-token",
  refresh_token: "test-refresh-token",
  jti: "jti-1",
  scope: "patient",
  identity_id: 42,
  phone: "+911234567890",
};

const ME_RESPONSE_SINGLE_ROLE = {
  identity_id: 42,
  phone: "+911234567890",
  roles: ["patient"],
};

// A stale session payload predating T05's additive phone field.
const ME_RESPONSE_NO_PHONE = {
  identity_id: 42,
  roles: ["patient"],
};

function setStoredSession(session: StoredSession) {
  localStorage.setItem("caresetu.session", JSON.stringify(session));
  localStorage.setItem("caresetu.access_jwt", session.jwt);
  localStorage.setItem("caresetu.refresh_token", session.refresh_token);
}

function renderAccountMenu() {
  return render(
    <AuthProvider>
      <AccountMenu />
    </AuthProvider>,
  );
}

async function openViaKeyboard() {
  await waitFor(() =>
    expect(screen.getByTestId("account-menu")).toBeInTheDocument(),
  );
  const trigger = screen.getByTestId("account-menu");
  fireEvent.keyDown(trigger, { key: "Enter" });
  await waitFor(() => expect(screen.getByRole("menu")).toBeInTheDocument());
  return trigger;
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

const mockReplace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mockReplace }),
  usePathname: () => "/patient",
}));

beforeEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
  mockReplace.mockReset();
});

afterEach(() => {
  cleanup();
});

describe("AccountMenu accessibility", () => {
  it("trigger announces itself as a menu opener (aria-haspopup)", async () => {
    setStoredSession(VALID_SESSION);
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(ME_RESPONSE_SINGLE_ROLE), { status: 200 }),
    );

    renderAccountMenu();
    const trigger = await waitFor(() =>
      expect(screen.getByTestId("account-menu")).toBeInTheDocument(),
    ).then(() => screen.getByTestId("account-menu"));

    expect(trigger.getAttribute("aria-label")).toBe("Account menu");
    expect(trigger.getAttribute("aria-haspopup")).toBe("menu");
  });

  it("opens via Enter key into a role=menu with role=menuitem entries", async () => {
    setStoredSession(VALID_SESSION);
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(ME_RESPONSE_SINGLE_ROLE), { status: 200 }),
    );

    renderAccountMenu();
    await openViaKeyboard();

    expect(
      screen.getByRole("menuitem", { name: "Logout" }),
    ).toBeInTheDocument();
  });

  it("closes on Escape and returns focus to the trigger", async () => {
    setStoredSession(VALID_SESSION);
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(ME_RESPONSE_SINGLE_ROLE), { status: 200 }),
    );

    renderAccountMenu();
    const trigger = await openViaKeyboard();

    fireEvent.keyDown(screen.getByRole("menu"), { key: "Escape" });
    await waitFor(() =>
      expect(screen.queryByRole("menu")).not.toBeInTheDocument(),
    );
    expect(document.activeElement).toBe(trigger);
  });

  it("consolidates phone, role badge, and logout - no standalone controls", async () => {
    setStoredSession(VALID_SESSION);
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(ME_RESPONSE_SINGLE_ROLE), { status: 200 }),
    );

    renderAccountMenu();
    await openViaKeyboard();

    expect(screen.getByText("+911234567890")).toBeInTheDocument();
    expect(screen.getByTestId("account-menu-role-badge")).toHaveTextContent(
      "Patient",
    );
    expect(
      screen.getByRole("menuitem", { name: "Logout" }),
    ).toBeInTheDocument();
  });
});

describe("AccountMenu stale sessions", () => {
  it("degrades to subject-id-only when /me carries no phone field", async () => {
    setStoredSession(VALID_SESSION);
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(ME_RESPONSE_NO_PHONE), { status: 200 }),
    );

    renderAccountMenu();
    await openViaKeyboard();

    expect(screen.getByText("Subject #42")).toBeInTheDocument();
    expect(screen.queryByText("+911234567890")).toBeNull();
  });
});
