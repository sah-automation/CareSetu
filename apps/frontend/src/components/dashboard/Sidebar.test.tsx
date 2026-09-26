// PHASE-2.6 T06 (#197): unit suite for the full-shell desktop sidebar -
// CSS-driven responsiveness, collapsed icon-only columns, Soon semantics.

import {
  render,
  screen,
  fireEvent,
  cleanup,
  within,
} from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { FolderOpen, Home } from "lucide-react";

import { Sidebar } from "./Sidebar";
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

// #538: the redesigned sidebar drops Logout into its lower group, so the
// component reads the shared logout seam at the module boundary like the
// AppShell suite does.
const mockLogout = vi.fn();

vi.mock("@/lib/auth/AuthContext", () => ({
  useAuth: () => ({ logout: mockLogout }),
}));

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.restoreAllMocks();
  mockPathname.mockReturnValue("/patient");
  mockLogout.mockClear();
});

afterEach(() => {
  cleanup();
});

describe("Sidebar", () => {
  it("renders the patient nav-config entries", () => {
    render(
      <Sidebar role="patient" collapsed={false} onToggleCollapse={vi.fn()} />,
    );

    ["nav-home", "nav-find", "nav-start", "nav-record", "nav-inbox"].forEach(
      (id) => expect(screen.getByTestId(id)).toBeInTheDocument(),
    );
  });

  it.each(["doctor", "partner", "operator"] as const)(
    "renders the %s nav-config entries",
    (role) => {
      mockPathname.mockReturnValue(`/${role}`);
      render(
        <Sidebar role={role} collapsed={false} onToggleCollapse={vi.fn()} />,
      );

      const first = {
        doctor: "nav-queue",
        partner: "nav-orders",
        operator: "nav-home",
      }[role];
      const last = {
        doctor: "nav-profile",
        partner: "nav-profile",
        operator: "nav-audit",
      }[role];
      expect(screen.getByTestId(first)).toBeInTheDocument();
      expect(screen.getByTestId(last)).toBeInTheDocument();
    },
  );

  it("shows Soon badges only on unbuilt entries", () => {
    render(
      <Sidebar role="partner" collapsed={false} onToggleCollapse={vi.fn()} />,
    );

    // Orders is the live landing entry; the rest carry the Soon convention.
    const soonBadges = screen.getAllByTestId("soon-badge");
    expect(soonBadges).toHaveLength(3);
    expect(screen.getByTestId("nav-orders").textContent).not.toContain("Soon");
  });

  it("hides labels and toggle text when collapsed", () => {
    render(
      <Sidebar role="patient" collapsed={true} onToggleCollapse={vi.fn()} />,
    );

    expect(screen.getByTestId("sidebar")).toHaveAttribute(
      "data-collapsed",
      "true",
    );
    expect(screen.queryByText("Home")).not.toBeInTheDocument();
    expect(screen.getByTestId("sidebar-toggle")).toHaveAttribute(
      "aria-label",
      "Expand sidebar",
    );
  });

  it("calls onToggleCollapse when the toggle button is clicked", () => {
    const onToggleCollapse = vi.fn();
    render(
      <Sidebar
        role="patient"
        collapsed={false}
        onToggleCollapse={onToggleCollapse}
      />,
    );

    fireEvent.click(screen.getByTestId("sidebar-toggle"));
    expect(onToggleCollapse).toHaveBeenCalledTimes(1);
  });

  it("highlights and links the live destination matching the pathname", () => {
    mockPathname.mockReturnValue("/patient");
    render(
      <Sidebar role="patient" collapsed={false} onToggleCollapse={vi.fn()} />,
    );

    const home = screen.getByTestId("nav-home");
    expect(home).toHaveAttribute("aria-current", "page");
    expect(home.getAttribute("href")).toBe("/patient");
  });

  it("renders Soon entries as non-interactive spans without hrefs", () => {
    render(
      <Sidebar role="operator" collapsed={false} onToggleCollapse={vi.fn()} />,
    );

    const disputes = screen.getByTestId("nav-disputes");
    expect(disputes.tagName).toBe("SPAN");
    expect(disputes).toHaveAttribute("aria-disabled", "true");
  });
});

// #538: the doctor-chrome sidebar redesign - labeled section groups, the
// collapsed hover flyouts (with the open-cases count), the icon-only collapse
// toggle, and Logout in the lower group. These are shared-chrome additions:
// the patient sidebar (a test-only surface) stays flat and label-free.
describe("Sidebar #538 redesigned chrome", () => {
  it("groups the full-shell nav into labeled sections", () => {
    mockPathname.mockReturnValue("/doctor");
    render(
      <Sidebar role="doctor" collapsed={false} onToggleCollapse={vi.fn()} />,
    );

    expect(screen.getByText("Work")).toBeInTheDocument();
    expect(screen.getByText("Account")).toBeInTheDocument();
    const workSection = screen.getByText("Work").parentElement;
    expect(workSection).not.toBeNull();
    expect(
      within(workSection as HTMLElement).getByTestId("nav-queue"),
    ).toBeInTheDocument();
    expect(
      within(workSection as HTMLElement).getByTestId("nav-cases"),
    ).toBeInTheDocument();
    const accountSection = screen.getByText("Account").parentElement;
    expect(
      within(accountSection as HTMLElement).getByTestId("nav-profile"),
    ).toBeInTheDocument();
  });

  it("renders the patient sidebar flat, without section labels", () => {
    render(
      <Sidebar role="patient" collapsed={false} onToggleCollapse={vi.fn()} />,
    );

    expect(screen.queryByText("Work")).not.toBeInTheDocument();
    expect(screen.queryByText("Account")).not.toBeInTheDocument();
  });

  it("keeps the collapsed rail icon-only - no labels, section headers, or toggle text leak", () => {
    mockPathname.mockReturnValue("/doctor");
    render(
      <Sidebar role="doctor" collapsed={true} onToggleCollapse={vi.fn()} />,
    );

    expect(screen.queryByText("Cases")).not.toBeInTheDocument();
    // #538 redesign: even the Work/Account section headers hide collapsed.
    expect(screen.queryByText("Work")).not.toBeInTheDocument();
    expect(screen.queryByText("Account")).not.toBeInTheDocument();
    expect(screen.queryByText("Collapse sidebar")).not.toBeInTheDocument();
    expect(screen.getByTestId("sidebar-toggle")).toHaveAttribute(
      "aria-label",
      "Expand sidebar",
    );
  });

  it("shows the label flyout with the open-cases count when a collapsed item is hovered", () => {
    mockPathname.mockReturnValue("/doctor");
    render(
      <Sidebar
        role="doctor"
        collapsed={true}
        onToggleCollapse={vi.fn()}
        items={[
          {
            key: "queue",
            labelKey: "queue",
            href: "/doctor",
            icon: Home,
            group: "work",
          },
          {
            key: "cases",
            labelKey: "cases",
            href: "/doctor/cases",
            icon: FolderOpen,
            count: 3,
            group: "work",
          },
        ]}
      />,
    );

    fireEvent.mouseEnter(screen.getByTestId("nav-cases"));

    const flyout = screen.getByTestId("sidebar-flyout");
    expect(flyout).toHaveTextContent("Cases");
    expect(within(flyout).getByTestId("count-pill")).toHaveTextContent("3");

    fireEvent.mouseLeave(screen.getByTestId("nav-cases"));
    expect(screen.queryByTestId("sidebar-flyout")).not.toBeInTheDocument();
  });

  it("renders Logout in the lower group and ends the session on click", () => {
    mockPathname.mockReturnValue("/doctor");
    render(
      <Sidebar role="doctor" collapsed={false} onToggleCollapse={vi.fn()} />,
    );

    const logout = screen.getByTestId("sidebar-logout");
    expect(logout).toHaveTextContent("Log out");
    fireEvent.click(logout);
    expect(mockLogout).toHaveBeenCalledTimes(1);
  });

  it("renders the lower-group Logout as icon-only when collapsed", () => {
    mockPathname.mockReturnValue("/doctor");
    render(
      <Sidebar role="doctor" collapsed={true} onToggleCollapse={vi.fn()} />,
    );

    const logout = screen.getByTestId("sidebar-logout");
    expect(logout).not.toHaveTextContent("Log out");
    expect(logout).toHaveAttribute("aria-label", "Log out");
  });
});

// #538 review: blueprint §9.4 "Labeled controls" - a hover-only flyout is not
// an accessible name. The collapsed rail must name every icon-only control on
// its own, and wire the visual flyout to it as a description.
describe("Sidebar #538 collapsed rail accessible names", () => {
  it("names every collapsed nav link with its own localized label", () => {
    mockPathname.mockReturnValue("/doctor");
    render(
      <Sidebar role="doctor" collapsed={true} onToggleCollapse={vi.fn()} />,
    );

    const nav = screen.getByTestId("sidebar-nav");
    expect(within(nav).getByRole("link", { name: "Queue" })).toHaveAttribute(
      "href",
      "/doctor",
    );
    expect(within(nav).getByRole("link", { name: "Cases" })).toHaveAttribute(
      "href",
      "/doctor/cases",
    );
    expect(within(nav).getByRole("link", { name: "Patients" })).toHaveAttribute(
      "href",
      "/doctor/patients",
    );
    expect(within(nav).getByRole("link", { name: "Profile" })).toHaveAttribute(
      "href",
      "/doctor/profile",
    );
  });

  it("does not leak the label text into the collapsed tree", () => {
    mockPathname.mockReturnValue("/doctor");
    render(
      <Sidebar role="doctor" collapsed={true} onToggleCollapse={vi.fn()} />,
    );

    // The names above are author-provided, not visible text.
    expect(screen.getByRole("link", { name: "Cases" })).toHaveTextContent("");
  });

  it("describes a collapsed link with the visible flyout instead of naming it by it", () => {
    mockPathname.mockReturnValue("/doctor");
    render(
      <Sidebar role="doctor" collapsed={true} onToggleCollapse={vi.fn()} />,
    );

    const cases = screen.getByRole("link", { name: "Cases" });
    // Nothing references the tooltip until it opens, and the name holds
    // without it.
    expect(cases).toHaveAccessibleName("Cases");
    expect(cases).toHaveAccessibleDescription("");

    fireEvent.mouseEnter(cases);
    const flyout = screen.getByRole("tooltip");
    expect(cases).toHaveAttribute("aria-describedby", flyout.id);
    expect(flyout.id).not.toBe("");
    expect(cases).toHaveAccessibleDescription("Cases");
    // The tooltip is an addition, never the name's only source.
    expect(cases).toHaveAccessibleName("Cases");
  });

  it("carries the open-cases count through the flyout description", () => {
    mockPathname.mockReturnValue("/doctor");
    render(
      <Sidebar
        role="doctor"
        collapsed={true}
        onToggleCollapse={vi.fn()}
        items={[
          {
            key: "queue",
            labelKey: "queue",
            href: "/doctor",
            icon: Home,
            group: "work",
          },
          {
            key: "cases",
            labelKey: "cases",
            href: "/doctor/cases",
            icon: FolderOpen,
            count: 3,
            group: "work",
          },
        ]}
      />,
    );

    const cases = screen.getByRole("link", { name: "Cases" });
    fireEvent.mouseEnter(cases);
    expect(cases).toHaveAccessibleDescription("Cases 3");
  });

  it("keeps the collapse toggle and Logout reachable by name when collapsed", () => {
    mockPathname.mockReturnValue("/doctor");
    const onToggleCollapse = vi.fn();
    render(
      <Sidebar
        role="doctor"
        collapsed={true}
        onToggleCollapse={onToggleCollapse}
      />,
    );

    const toggle = screen.getByRole("button", { name: "Expand sidebar" });
    fireEvent.click(toggle);
    expect(onToggleCollapse).toHaveBeenCalledTimes(1);

    const logout = screen.getByRole("button", { name: "Log out" });
    fireEvent.click(logout);
    expect(mockLogout).toHaveBeenCalledTimes(1);
  });

  it("names a collapsed Soon entry for AT without a prohibited aria-label", () => {
    mockPathname.mockReturnValue("/patient");
    render(
      <Sidebar role="patient" collapsed={true} onToggleCollapse={vi.fn()} />,
    );

    // A role-less span may not carry aria-label, so the label ships as
    // screen-reader-only text inside it.
    const inbox = screen.getByTestId("nav-inbox");
    expect(inbox).toHaveAttribute("aria-disabled", "true");
    expect(inbox).not.toHaveAttribute("aria-label");
    expect(within(inbox).getByText("Inbox")).toHaveClass("sr-only");
  });
});
