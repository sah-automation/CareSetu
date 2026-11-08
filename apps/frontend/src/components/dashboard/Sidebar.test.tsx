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

import { __resetLangForTests } from "@/lib/i18n/LangContext";

import { Sidebar } from "./Sidebar";

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
  useAuth: () => ({
    logout: mockLogout,
    user: { id: 1, phone: "+911234567890", roles: ["operator"], tier: "admin" },
  }),
}));

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.restoreAllMocks();
  mockPathname.mockReturnValue("/patient");
  mockLogout.mockClear();
  localStorage.clear();
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

  it("marks the flattened leaf current while inside its destination (#744/#889)", () => {
    mockPathname.mockReturnValue("/operator/observability/business");

    const { unmount } = render(
      <Sidebar role="operator" collapsed={false} onToggleCollapse={vi.fn()} />,
    );
    expect(screen.getByTestId("nav-business")).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(document.querySelectorAll('[aria-current="page"]')).toHaveLength(1);
    expect(screen.queryByTestId("nav-metrics")).toBeNull();
    unmount();

    render(
      <Sidebar role="operator" collapsed={true} onToggleCollapse={vi.fn()} />,
    );
    expect(screen.getByTestId("nav-business")).toHaveAttribute(
      "aria-current",
      "page",
    );
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
    const workSection = screen.getByTestId("sidebar-section-work-content");
    expect(workSection).not.toBeNull();
    expect(
      within(workSection as HTMLElement).getByTestId("nav-queue"),
    ).toBeInTheDocument();
    expect(
      within(workSection as HTMLElement).getByTestId("nav-cases"),
    ).toBeInTheDocument();
    const accountSection = screen.getByTestId(
      "sidebar-section-account-content",
    );
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
    // #604: the landing area's label is "Dashboard" now; the href asserted
    // alongside it is what proves the route did not move with the copy.
    expect(
      within(nav).getByRole("link", { name: "Dashboard" }),
    ).toHaveAttribute("href", "/doctor");
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

// #574: the collapse control is brand-header chrome, not a footer row. Paired
// with sign-out in one undivided stack it read as a nav item, and a nav item
// must never sit beside "Log out". The header and the footer carry test hooks
// because neither is otherwise addressable, so placement is asserted
// structurally - ancestry and absence. Only the two checks jsdom cannot resolve
// structurally (the 44px box, the header's alignment) reach for class strings.
describe("Sidebar #574 collapse control placement", () => {
  function renderDoctor(collapsed: boolean) {
    mockPathname.mockReturnValue("/doctor");
    return render(
      <Sidebar
        role="doctor"
        collapsed={collapsed}
        onToggleCollapse={vi.fn()}
      />,
    );
  }

  // Only this describe switches locale, so only it may reset the store - the
  // English assertions above it stay untouched, and no suite-wide reset is
  // added that would stop proving they still hold in the default locale.
  afterEach(() => {
    __resetLangForTests();
  });

  it.each([false, true])(
    "puts the collapse control inside the brand header (collapsed=%s)",
    (collapsed) => {
      renderDoctor(collapsed);

      expect(screen.getByTestId("sidebar-brand")).toContainElement(
        screen.getByTestId("sidebar-toggle"),
      );
    },
  );

  it("trails the control on the wordmark's edge, and centres it once collapsed", () => {
    const { unmount } = renderDoctor(false);
    // Expanded: the wordmark leads, the control is pushed to the far edge.
    expect(screen.getByTestId("sidebar-brand").className).toContain(
      "justify-between",
    );
    unmount();

    // Collapsed: the wordmark is gone, so a 44px control left on `px-4` would
    // sit 12px off-centre in the 64px rail. Drop the padding and centre it,
    // matching the collapsed footer's `justify-center px-0`.
    renderDoctor(true);
    const brand = screen.getByTestId("sidebar-brand").className;
    expect(brand).toContain("justify-center");
    expect(brand).toContain("px-0");
    expect(brand).not.toContain("px-4");
  });

  it.each([false, true])(
    "leaves the footer holding Log out alone, above the divider's edge (collapsed=%s)",
    (collapsed) => {
      renderDoctor(collapsed);

      const footer = screen.getByTestId("sidebar-footer");
      expect(footer).toContainElement(screen.getByTestId("sidebar-logout"));
      // Absent by structure: the navigation control is gone from the footer.
      expect(within(footer).queryByTestId("sidebar-toggle")).toBeNull();
    },
  );

  // Blueprint §9.4 line 597: touch targets >= 44px. Compactness is width, so
  // the control gives up `w-full` but keeps the 44px box in both states.
  it.each([false, true])(
    "keeps the control a 44px icon button, never a full-width row (collapsed=%s)",
    (collapsed) => {
      renderDoctor(collapsed);

      const toggle = screen.getByTestId("sidebar-toggle");
      expect(toggle.className).toContain("h-11");
      expect(toggle.className).toContain("w-11");
      expect(toggle.className).not.toContain("w-full");
    },
  );

  it("flips the chevron with the state, so the glyph is never stale", () => {
    const { unmount } = renderDoctor(false);
    // The name flips polarity for the same reason: it names the action, and
    // the glyph points the way the rail travels. The two states must not
    // render the same icon, or a stale chevron would invite the wrong click.
    const expanded = screen.getByTestId("sidebar-toggle").querySelector("svg")
      ?.innerHTML;
    expect(expanded).toBeTruthy();
    unmount();

    renderDoctor(true);
    const collapsed = screen.getByTestId("sidebar-toggle").querySelector("svg")
      ?.innerHTML;
    expect(collapsed).toBeTruthy();
    expect(collapsed).not.toBe(expanded);
  });

  // The two accessible names name the action, not the state, so they are two
  // flat keys rather than one conditional. Blueprint §9.2 line 578: no key
  // ships in one locale only.
  it.each([
    { collapsed: false, en: "Collapse sidebar", hi: "साइडबार संकुचित करें" },
    { collapsed: true, en: "Expand sidebar", hi: "साइडबार विस्तार करें" },
  ])(
    "names the control in both locales (collapsed=$collapsed)",
    ({ collapsed, en, hi }) => {
      const { unmount } = renderDoctor(collapsed);
      expect(screen.getByTestId("sidebar-toggle")).toHaveAccessibleName(en);
      unmount();

      // Same control, same state, second locale - the name rides the dictionary.
      localStorage.setItem("caresetu.lang", "hi");
      renderDoctor(collapsed);
      expect(screen.getByTestId("sidebar-toggle")).toHaveAccessibleName(hi);
    },
  );
});

// #745: the operator console's grouped sidebar. Work and Observability are two
// sections separated by a hairline divider; Observability is a hand-rolled
// disclosure whose sub-menu holds the nine decision-28 sub-destinations behind
// a hairline guide rail. The collapsed rail keeps a way into the group.
describe("Sidebar #745 operator groups and disclosure", () => {
  function renderOperator({
    collapsed = false,
    pathname = "/operator",
  }: {
    collapsed?: boolean;
    pathname?: string;
  } = {}) {
    mockPathname.mockReturnValue(pathname);
    return render(
      <Sidebar
        role="operator"
        collapsed={collapsed}
        onToggleCollapse={vi.fn()}
      />,
    );
  }

  it("labels the navigation landmark", () => {
    renderOperator();
    expect(screen.getByRole("navigation", { name: "Primary" })).toBe(
      screen.getByTestId("sidebar-nav"),
    );
  });

  it("separates every operator section with a hairline divider", () => {
    renderOperator();
    // #867/#868: Work, Observability and Account are three sections, so there
    // are two dividers between them.
    const dividers = screen.getAllByTestId("sidebar-section-divider");
    expect(dividers).toHaveLength(4);
    for (const divider of dividers) {
      expect(divider.className).toContain("border-hairline");
    }
  });

  it("flattens observability groups into direct destination rows under their section", () => {
    renderOperator({ pathname: "/operator/observability/business" });

    for (const [section, keys] of [
      ["metrics", ["business", "product", "usage"]],
      ["reliability", ["reliability", "health", "cost"]],
      ["qualitySecurity", ["quality", "security", "evals"]],
    ] as const) {
      const content = screen.getByTestId(`sidebar-section-${section}-content`);
      for (const key of keys) {
        expect(within(content).getByTestId(`nav-${key}`)).toBeInTheDocument();
      }
      expect(screen.queryByTestId(`sidebar-group-${section}`)).toBeNull();
    }
  });

  it("marks the current leaf current after flattening", () => {
    renderOperator({ pathname: "/operator/observability/business" });

    expect(screen.getByTestId("nav-business")).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(document.querySelectorAll('[aria-current="page"]')).toHaveLength(1);
    expect(screen.queryByTestId("nav-metrics")).toBeNull();
  });

  it("renders settings as a live link in the account section", () => {
    renderOperator({ pathname: "/operator" });

    const settings = screen.getByTestId("nav-settings");
    // #747: Settings is a live placeholder shell, not a coming-soon stub, so
    // it renders as a real link.
    expect(settings.tagName).toBe("A");
    expect(settings).toHaveAttribute("href", "/operator/settings");
  });

  it("keeps collapsed rail direct routes into flattened leaves", () => {
    renderOperator({ collapsed: true, pathname: "/operator" });

    for (const key of [
      "business",
      "product",
      "usage",
      "reliability",
      "health",
      "cost",
      "quality",
      "security",
      "evals",
    ]) {
      expect(screen.getByTestId(`nav-${key}`)).toBeInTheDocument();
    }
    expect(screen.queryByTestId("sidebar-group-metrics-collapsed")).toBeNull();
    expect(screen.queryByTestId("sidebar-flyout")).toBeNull();
  });

  it("renders settings as a live link", () => {
    renderOperator({ collapsed: false, pathname: "/operator" });

    const settings = screen.getByTestId("nav-settings");
    // #747: Settings un-sooned to a live placeholder shell, so navigation
    // carries it as a link too.
    expect(settings.tagName).toBe("A");
    expect(settings).toHaveAttribute("href", "/operator/settings");
  });
});
