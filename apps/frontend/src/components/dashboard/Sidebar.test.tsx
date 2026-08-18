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
  it("renders patient nav items", () => {
    render(<Sidebar role="patient" collapsed={false} onToggle={vi.fn()} />);

    expect(screen.getByTestId("nav-home")).toBeInTheDocument();
    expect(screen.getByTestId("nav-my-records")).toBeInTheDocument();
    expect(screen.getByTestId("nav-appointments")).toBeInTheDocument();
    expect(screen.getByTestId("nav-medicines")).toBeInTheDocument();
    expect(screen.getByTestId("nav-consent")).toBeInTheDocument();
    expect(screen.getByTestId("nav-notifications")).toBeInTheDocument();
  });

  it("renders partner nav items", () => {
    render(<Sidebar role="partner" collapsed={false} onToggle={vi.fn()} />);

    expect(screen.getByTestId("nav-home")).toBeInTheDocument();
    expect(screen.getByTestId("nav-active-cases")).toBeInTheDocument();
    expect(screen.getByTestId("nav-my-profile")).toBeInTheDocument();
    expect(screen.getByTestId("nav-settlements")).toBeInTheDocument();
  });

  it("renders operator nav items", () => {
    render(<Sidebar role="operator" collapsed={false} onToggle={vi.fn()} />);

    expect(screen.getByTestId("nav-home")).toBeInTheDocument();
    expect(screen.getByTestId("nav-user-management")).toBeInTheDocument();
    expect(screen.getByTestId("nav-moderation")).toBeInTheDocument();
    expect(screen.getByTestId("nav-audit-trail")).toBeInTheDocument();
  });

  it("shows Soon badges on non-Home items", () => {
    render(<Sidebar role="patient" collapsed={false} onToggle={vi.fn()} />);

    const soonBadges = screen.getAllByText("Soon");
    expect(soonBadges.length).toBe(5);

    const homeItem = screen.getByTestId("nav-home");
    expect(homeItem.textContent).not.toContain("Soon");
  });

  it("hides nav labels when collapsed", () => {
    render(<Sidebar role="patient" collapsed={true} onToggle={vi.fn()} />);

    expect(screen.getByTestId("nav-home")).toBeInTheDocument();
    expect(screen.queryByText("My Records")).not.toBeInTheDocument();
  });

  it("calls onToggle when toggle button is clicked", () => {
    const onToggle = vi.fn();
    render(<Sidebar role="patient" collapsed={false} onToggle={onToggle} />);

    fireEvent.click(screen.getByTestId("sidebar-toggle"));
    expect(onToggle).toHaveBeenCalledTimes(1);
  });

  it("highlights active nav item based on pathname", () => {
    mockPathname.mockReturnValue("/patient");
    render(<Sidebar role="patient" collapsed={false} onToggle={vi.fn()} />);

    const homeLink = screen.getByTestId("nav-home");
    expect(homeLink.className).toContain("bg-accent-soft");
  });

  it("links non-Soon items to correct href", () => {
    render(<Sidebar role="patient" collapsed={false} onToggle={vi.fn()} />);

    const homeLink = screen.getByTestId("nav-home");
    expect(homeLink.getAttribute("href")).toBe("/patient");
  });

  it("links Soon items to # and disables them", () => {
    render(<Sidebar role="patient" collapsed={false} onToggle={vi.fn()} />);

    const recordsLink = screen.getByTestId("nav-my-records");
    expect(recordsLink.getAttribute("href")).toBe("#");
    expect(recordsLink.getAttribute("aria-disabled")).toBe("true");
  });
});
