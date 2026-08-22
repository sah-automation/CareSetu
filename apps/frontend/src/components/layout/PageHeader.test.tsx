// PHASE-2.6 T08 (#199): suite for the PageHeader chassis block and the
// Breadcrumbs depth rules (blueprint §2.5) - H1/description/action anatomy,
// crumbs only at depth 2+, plain-text last crumb, mobile back-link collapse.

import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi, afterEach } from "vitest";

import { Breadcrumbs, PageHeader } from "./PageHeader";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  usePathname: () => "/records",
}));

afterEach(() => {
  cleanup();
});

describe("PageHeader", () => {
  it("renders the H1 title", () => {
    render(<PageHeader title="Records" />);

    expect(
      screen.getByRole("heading", { level: 1, name: "Records" }),
    ).toBeInTheDocument();
  });

  it("renders the optional description under the title", () => {
    render(
      <PageHeader
        title="Ramesh Kumar · 46 M"
        description="Case CS-C-2081 · Pre-summary finalized"
      />,
    );

    expect(
      screen.getByText("Case CS-C-2081 · Pre-summary finalized"),
    ).toBeInTheDocument();
  });

  it("renders the optional primary action right of the text block", () => {
    const onClick = vi.fn();
    render(
      <PageHeader
        title="Cases"
        action={<button onClick={onClick}>Mark consult complete</button>}
      />,
    );

    fireEvent.click(
      screen.getByRole("button", { name: "Mark consult complete" }),
    );
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("omits the description and action slots when not provided", () => {
    const { container } = render(<PageHeader title="Home" />);

    expect(container.querySelector("p")).toBeNull();
    expect(container.querySelector("button")).toBeNull();
  });
});

describe("Breadcrumbs", () => {
  it("renders nothing below depth 2 (home/root pages have none)", () => {
    const { container } = render(<Breadcrumbs items={[{ label: "Home" }]} />);

    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when no crumbs are passed", () => {
    const { container } = render(<Breadcrumbs items={[]} />);

    expect(container).toBeEmptyDOMElement();
  });

  it("at depth 2 renders the trail with a linked parent and a plain-text current page", () => {
    render(
      <Breadcrumbs
        items={[
          { label: "Records", href: "/patient/record" },
          { label: "Consent log" },
        ]}
      />,
    );

    const trail = screen.getByTestId("breadcrumb-trail");
    expect(trail).toBeInTheDocument();
    // Parent crumb is a link...
    expect(screen.getByRole("link", { name: "Records" })).toBeInTheDocument();
    // ...and the last crumb is plain text, never a link (§2.5).
    const current = screen.getByTestId("breadcrumb-current");
    expect(current).toHaveTextContent("Consent log");
    expect(current.closest("a")).toBeNull();
  });

  it("mirrors URL structure across depth 3 with separators between crumbs", () => {
    render(
      <Breadcrumbs
        items={[
          { label: "Cases", href: "/doctor/cases" },
          { label: "Ramesh Kumar", href: "/doctor/cases/2081" },
          { label: "Prescription" },
        ]}
      />,
    );

    expect(screen.getAllByText("/")).toHaveLength(2);
    expect(screen.getByRole("link", { name: "Cases" })).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Ramesh Kumar" }),
    ).toBeInTheDocument();
  });

  it("collapses to a single mobile back-link labeled with the parent section", () => {
    render(
      <Breadcrumbs
        items={[
          { label: "Cases", href: "/doctor/cases" },
          { label: "Prescription" },
        ]}
      />,
    );

    const back = screen.getByTestId("breadcrumb-back");
    expect(back).toHaveTextContent("← Cases");
    expect(back.getAttribute("href")).toBe("/doctor/cases");
  });

  it("is exposed as a breadcrumb-labelled navigation landmark", () => {
    render(
      <Breadcrumbs items={[{ label: "A", href: "/a" }, { label: "B" }]} />,
    );

    expect(
      screen.getByRole("navigation", { name: "Breadcrumb" }),
    ).toBeInTheDocument();
  });
});
