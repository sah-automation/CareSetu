// PHASE-2.6 T06 (#197): AppShell variant suite - light density never renders
// a sidebar, full density collapses with per-role persistence, both densities
// render nav-config-driven tabs/top-nav with Soon semantics and bilingual
// labels; the retired matchMedia mechanics stay gone via source scan.

import {
  render,
  screen,
  fireEvent,
  cleanup,
  waitFor,
  within,
} from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

import { __resetLangForTests } from "@/lib/i18n/LangContext";
import { listOpenCases, type CaseDetailView } from "@/lib/care/api";

import { AppShell } from "./AppShell";
import type { Role } from "./types";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockPathname = vi.fn();

vi.mock("next/navigation", () => ({
  usePathname: () => mockPathname(),
}));

vi.mock("next/link", () => ({
  default({
    href,
    children,
    ...props
  }: {
    href: string;
    children: React.ReactNode;
    [key: string]: unknown;
  }) {
    return (
      <a href={href} {...props}>
        {children}
      </a>
    );
  },
}));

const switchRole = vi.fn();
const logout = vi.fn();

vi.mock("@/lib/auth/AuthContext", () => ({
  useAuth: () => ({
    user: { id: 1, phone: "+911234567890", roles: ["patient", "operator"] },
    selectedRole: "operator",
    switchRole,
    logout,
    isAuthenticated: true,
    isLoading: false,
  }),
}));

// PHASE-8.1 T8 (#483): the doctor shell's Cases count pill reads the existing
// open-cases feed; the whole care module is mocked so shell tests stay unit
// scoped.
vi.mock("@/lib/care/api", () => ({
  listOpenCases: vi.fn(),
}));

const getOpenCases = vi.mocked(listOpenCases);

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
  __resetLangForTests();
  mockPathname.mockReturnValue("/patient");
  getOpenCases.mockResolvedValue([]);
});

afterEach(() => {
  cleanup();
});

describe("AppShell light density (patient)", () => {
  it("never renders a sidebar at any width - topbar carries the desktop top-nav", () => {
    render(
      <AppShell role="patient">
        <h1>Patient home</h1>
      </AppShell>,
    );

    expect(screen.queryByTestId("sidebar")).not.toBeInTheDocument();
    expect(screen.getByTestId("topbar")).toHaveAttribute(
      "data-density",
      "light",
    );
    expect(screen.getByTestId("topnav")).toBeInTheDocument();
    expect(screen.getByTestId("app-shell")).toHaveAttribute(
      "data-density",
      "light",
    );
  });

  it("derives the desktop top-nav from the patient nav-config, minus the center slot", () => {
    render(
      <AppShell role="patient">
        <h1>Patient home</h1>
      </AppShell>,
    );

    const topnav = screen.getByTestId("topnav");
    expect(topnav).toHaveTextContent("Home");
    expect(topnav).toHaveTextContent("Find Care");
    expect(topnav).toHaveTextContent("My Record");
    expect(topnav).toHaveTextContent("Inbox");
    // Start Visit lives only in the center accent column of the tab bar;
    // Profile & Settings stays in the More sheet / account cluster.
    expect(topnav).not.toHaveTextContent("Start");
    expect(topnav.textContent).toContain("Bookings & Orders");
    expect(topnav.textContent).toContain("Soon");
    expect(topnav.textContent).not.toContain("Profile & Settings");
    // PHASE-3 T7 (#216) un-sooned My Record: it renders as a live link on
    // every surface via the single source.
    expect(screen.getByTestId("nav-record")).toHaveAttribute(
      "href",
      "/patient/record",
    );
    // PHASE-8.1 T11 (#485): Inbox is coming-soon until Phase 13, so the
    // top-nav renders it (and Bookings) as dimmed non-interactive spans -
    // never a navigation to a dead page.
    expect(screen.getByTestId("nav-inbox")).toHaveAttribute(
      "data-soon",
      "true",
    );
    expect(screen.getByTestId("nav-inbox").tagName).toBe("SPAN");
    expect(screen.getByTestId("nav-bookings")).toHaveAttribute(
      "data-soon",
      "true",
    );
    // The finalized view also carries the language switch in this cluster.
    expect(screen.getByTestId("lang-toggle")).toBeInTheDocument();
  });

  it("renders Soon entries dimmed and non-interactive", () => {
    render(
      <AppShell role="patient">
        <h1>Patient home</h1>
      </AppShell>,
    );

    const bookings = screen.getByTestId("nav-bookings");
    expect(bookings.tagName).toBe("SPAN");
    expect(bookings).toHaveAttribute("aria-disabled", "true");

    const inbox = screen.getByTestId("nav-inbox");
    expect(inbox.tagName).toBe("SPAN");
    expect(inbox).toHaveAttribute("aria-disabled", "true");
  });

  it("marks the live destination matching the pathname as current", () => {
    render(
      <AppShell role="patient">
        <h1>Patient home</h1>
      </AppShell>,
    );

    expect(screen.getByTestId("nav-home")).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it("carries the five-column bottom bar with Start Visit pinned as the center accent", () => {
    render(
      <AppShell role="patient">
        <h1>Patient home</h1>
      </AppShell>,
    );

    const bar = screen.getByTestId("bottom-tabs");
    expect(bar.className).toContain("lg:hidden");

    const keys = ["home", "find", "start", "record"];
    keys.forEach((key) =>
      expect(screen.getByTestId(`tab-${key}`)).toBeInTheDocument(),
    );
    // Ratified five columns (#210): Home | Find | Start(center) | Record |
    // More - exactly five children, no sixth Inbox column.
    expect(screen.queryByTestId("tab-inbox")).not.toBeInTheDocument();
    expect(
      Array.from(bar.children).map((child) =>
        child.getAttribute("data-testid"),
      ),
    ).toEqual([
      "tab-home",
      "tab-find",
      "tab-start",
      "tab-record",
      "more-trigger",
    ]);
    // The center accent renders as a circular accent FAB inside its column.
    expect(
      screen
        .getByTestId("tab-start")
        .querySelector("span.rounded-full.bg-accent"),
    ).not.toBeNull();
    // PHASE-3 T7 (#216) un-sooned My Record: the tab column is a live link.
    expect(screen.getByTestId("tab-record")).toHaveAttribute(
      "href",
      "/patient/record",
    );
  });

  it("moves overflow destinations into the More sheet with Soon badges", () => {
    render(
      <AppShell role="patient">
        <h1>Patient home</h1>
      </AppShell>,
    );

    expect(screen.queryByTestId("more-sheet")).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId("more-trigger"));

    const sheet = screen.getByTestId("more-sheet");
    // Inbox folds into More (#210) and joins Bookings as coming-soon (#485):
    // every overflow destination is a dimmed non-interactive row, so none of
    // them navigates to a dead page.
    expect(sheet).toHaveTextContent("Inbox");
    expect(sheet).toHaveTextContent("Bookings & Orders");
    expect(sheet).toHaveTextContent("Profile & Settings");

    const overflowKeys = [
      "more-inbox",
      "more-bookings",
      "more-profile-settings",
    ];
    for (const testid of overflowKeys) {
      expect(screen.getByTestId(testid).tagName).toBe("SPAN");
      expect(screen.getByTestId(testid)).toHaveAttribute(
        "aria-disabled",
        "true",
      );
    }
    expect(within(sheet).getAllByTestId("soon-badge")).toHaveLength(3);
  });

  it("renders nav labels bilingually through the i18n engine", () => {
    localStorage.setItem("caresetu.lang", "hi");
    render(
      <AppShell role="patient">
        <h1>Patient home</h1>
      </AppShell>,
    );

    expect(screen.getByTestId("tab-home")).toHaveTextContent("होम");
    expect(screen.getByTestId("tab-start")).toHaveTextContent("शुरू करें");
    expect(screen.getByTestId("nav-home")).toHaveTextContent("होम");
  });
});

describe.each(["doctor", "partner", "operator"] as const)(
  "AppShell full density (%s)",
  (role) => {
    function setup(pathname: string) {
      mockPathname.mockReturnValue(pathname);
      return render(
        <AppShell role={role}>
          <h1>Workspace</h1>
        </AppShell>,
      );
    }

    it("shows a collapsible sidebar plus topbar, with bottom tabs for phones", () => {
      setup(`/${role}`);

      const sidebar = screen.getByTestId("sidebar");
      expect(sidebar).toBeInTheDocument();
      // Responsiveness is CSS-driven: removed from layout below lg entirely.
      expect(sidebar.className).toContain("hidden");
      expect(sidebar.className).toContain("lg:flex");
      expect(screen.getByTestId("topbar-page-slot")).toBeInTheDocument();
      expect(screen.getByTestId("bottom-tabs")).toBeInTheDocument();
    });

    it("renders the role's nav-config entries with active highlighting", () => {
      setup(`/${role}`);

      const expected = {
        doctor: ["queue", "cases", "patients", "profile"],
        partner: ["orders", "history", "settlements", "profile"],
        operator: ["home", "verifications", "disputes", "audit"],
      }[role];

      expected.forEach((key) => {
        expect(screen.getByTestId(`nav-${key}`)).toBeInTheDocument();
        expect(screen.getByTestId(`tab-${key}`)).toBeInTheDocument();
      });
      expect(screen.getByTestId(`nav-${expected[0]}`)).toHaveAttribute(
        "aria-current",
        "page",
      );
    });

    it("keeps staff secondary entries dimmed, non-interactive, and badged", () => {
      setup(`/${role}`);

      const soonItems = screen
        .getAllByTestId(/^nav-/)
        .filter((el) => el.getAttribute("data-soon") === "true");
      expect(soonItems.length).toBeGreaterThan(0);
      for (const item of soonItems) {
        expect(item).toHaveAttribute("aria-disabled", "true");
        expect(item.tagName).toBe("SPAN");
      }
      expect(screen.getAllByTestId("soon-badge").length).toBe(soonItems.length);
    });
  },
);

describe("AppShell doctor Cases count pill (PHASE-8.1 T8, #483)", () => {
  function openCase(id: number) {
    return {
      case_id: id,
      patient_id: 3,
      doctor_id: 7,
      pre_summary_id: 5,
      stage: "prescription_pending",
      forced_review: false,
      closed_at: null,
      close_reason: null,
      created_at: "2026-09-12T10:00:00Z",
      updated_at: "2026-09-12T10:00:00Z",
    } as CaseDetailView;
  }

  function renderDoctor() {
    mockPathname.mockReturnValue("/doctor");
    return render(
      <AppShell role="doctor">
        <h1>Workspace</h1>
      </AppShell>,
    );
  }

  it("renders the Cases tab as a live link with the open-cases count pill", async () => {
    getOpenCases.mockResolvedValue([openCase(11), openCase(12)]);
    renderDoctor();

    await waitFor(() =>
      expect(screen.getByTestId("nav-cases")).toHaveAttribute(
        "href",
        "/doctor/cases",
      ),
    );
    expect(screen.getByTestId("nav-cases").tagName).toBe("A");
    expect(
      within(screen.getByTestId("nav-cases")).getByTestId("count-pill"),
    ).toHaveTextContent("2");
    // The phone tab bar carries the same count badge (same config entry).
    expect(
      within(screen.getByTestId("tab-cases")).getByTestId("count-pill"),
    ).toHaveTextContent("2");
  });

  it("marks the Cases tab current when on /doctor/cases", async () => {
    mockPathname.mockReturnValue("/doctor/cases");
    getOpenCases.mockResolvedValue([openCase(11)]);
    render(
      <AppShell role="doctor">
        <h1>Workspace</h1>
      </AppShell>,
    );

    await waitFor(() =>
      expect(screen.getByTestId("nav-cases")).toHaveAttribute(
        "aria-current",
        "page",
      ),
    );
    expect(screen.getByTestId("tab-cases")).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it("shows no count pill when there are no open cases", async () => {
    getOpenCases.mockResolvedValue([]);
    renderDoctor();

    await waitFor(() =>
      expect(screen.getByTestId("nav-cases")).toHaveAttribute(
        "href",
        "/doctor/cases",
      ),
    );
    expect(screen.queryByTestId("count-pill")).not.toBeInTheDocument();
  });

  it("shows no count pill when the cases feed fails", async () => {
    getOpenCases.mockRejectedValue(new Error("boom"));
    renderDoctor();

    await waitFor(() =>
      expect(screen.getByTestId("nav-cases")).toHaveAttribute(
        "href",
        "/doctor/cases",
      ),
    );
    expect(screen.queryByTestId("count-pill")).not.toBeInTheDocument();
  });

  it("keeps doctor Patients and Profile coming-soon while Cases is live", async () => {
    renderDoctor();

    await waitFor(() =>
      expect(screen.getByTestId("nav-cases")).toHaveAttribute(
        "href",
        "/doctor/cases",
      ),
    );
    expect(screen.getByTestId("nav-patients")).toHaveAttribute(
      "data-soon",
      "true",
    );
    expect(screen.getByTestId("nav-profile")).toHaveAttribute(
      "data-soon",
      "true",
    );
    expect(screen.getByTestId("nav-patients").tagName).toBe("SPAN");
    expect(screen.getByTestId("nav-profile").tagName).toBe("SPAN");
  });
});

describe("full-shell collapse preference persistence", () => {
  function renderOperator() {
    mockPathname.mockReturnValue("/operator");
    return render(
      <AppShell role="operator">
        <h1>Operator</h1>
      </AppShell>,
    );
  }

  it("defaults expanded, collapses on toggle, and persists per role", () => {
    const { unmount } = renderOperator();

    const sidebar = screen.getByTestId("sidebar");
    expect(sidebar.getAttribute("data-collapsed")).toBeNull();
    expect(sidebar.className).toContain("w-60");

    fireEvent.click(screen.getByTestId("sidebar-toggle"));

    expect(sidebar.getAttribute("data-collapsed")).toBe("true");
    expect(sidebar.className).toContain("w-16");
    expect(localStorage.getItem("caresetu.sidebar.operator")).toBe("collapsed");
    unmount();
  });

  it("adopts the stored preference on the next visit", () => {
    localStorage.setItem("caresetu.sidebar.operator", "collapsed");
    renderOperator();

    const sidebar = screen.getByTestId("sidebar");
    expect(sidebar.getAttribute("data-collapsed")).toBe("true");
    expect(sidebar.className).toContain("w-16");
  });

  it("keeps preferences independent between roles", () => {
    localStorage.setItem("caresetu.sidebar.operator", "collapsed");
    mockPathname.mockReturnValue("/partner");
    render(
      <AppShell role="partner">
        <h1>Partner</h1>
      </AppShell>,
    );

    // The partner shell ignores the operator's stored choice and starts
    // expanded, persisting its own default under its own key.
    expect(localStorage.getItem("caresetu.sidebar.partner")).toBe("expanded");
    expect(screen.getByTestId("sidebar").className).toContain("w-60");
  });

  it("labels toggle accessibly in both states", () => {
    const { unmount } = renderOperator();

    const toggle = screen.getByTestId("sidebar-toggle");
    expect(toggle).toHaveAttribute("aria-label", "Collapse sidebar");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-label", "Expand sidebar");
    unmount();
  });
});

describe("retired icon-rail / matchMedia mechanics", () => {
  const dashboardDir = join(__dirname);

  function dashboardSources(): string[] {
    return readdirSync(dashboardDir)
      .filter(
        (name) =>
          /\.(tsx|ts)$/.test(name) &&
          !name.endsWith(".test.tsx") &&
          !name.endsWith(".test.ts"),
      )
      .map((name) => readFileSync(join(dashboardDir, name), "utf8"));
  }

  it("no dashboard shell code consults matchMedia any more", () => {
    for (const source of dashboardSources()) {
      expect(source).not.toMatch(/matchMedia/);
    }
  });

  // PHASE-2.6 T07 (#198): the generic dashboard group split into per-role
  // route groups - each group layout pins one fixed role into the shared
  // AppShell instead of resolving it from the session.
  it("each per-role group layout wires its role through AppShell", () => {
    const roles = ["patient", "doctor", "partner", "operator"] as const;
    for (const role of roles) {
      const layout = readFileSync(
        join(__dirname, `../../app/(${role})/layout.tsx`),
        "utf8",
      );
      expect(layout).toContain("<AppShell");
      expect(layout).toContain(`role="${role}"`);
    }
  });
});
