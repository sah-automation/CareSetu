// PHASE-2.6 T06 (#197): unit suite for the full-shell desktop sidebar -
// CSS-driven responsiveness, collapsed icon-only columns, Soon semantics.

import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

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

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.restoreAllMocks();
  mockPathname.mockReturnValue("/patient");
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
