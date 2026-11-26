// PHASE-2.6 T11 (#202): /staff/register mounts the wizard in the public
// carve-out of the staff group and feeds it the raw ?type= preset carried by
// the homepage providers band and staff-login CTAs (ticket 09's hrefs).

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import StaffRegisterPage from "./page";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { __resetLangForTests } from "@/lib/i18n/LangContext";

let searchParamsValue = new URLSearchParams();

vi.mock("next/navigation", () => ({
  useSearchParams: () => searchParamsValue,
}));

function renderPage(type?: string) {
  searchParamsValue = type
    ? new URLSearchParams({ type })
    : new URLSearchParams();
  return render(<StaffRegisterPage />);
}

afterEach(() => {
  cleanup();
  __resetLangForTests();
});

describe("StaffRegisterPage (?type= preset flow)", () => {
  const t = STRINGS.en.staffAuth.register;

  it("carries each CTA preset into the wizard's application type", () => {
    for (const applicationType of ["doctor", "lab", "chemist"] as const) {
      const { unmount } = renderPage(applicationType);
      expect(screen.getByTestId("pr-type-badge")).toHaveTextContent(
        t.typeBadge[applicationType],
      );
      unmount();
    }
  });

  it("defaults to doctor when the param is missing or junk", () => {
    const { unmount } = renderPage();
    expect(screen.getByTestId("pr-type-badge")).toHaveTextContent(
      t.typeBadge.doctor,
    );
    unmount();

    renderPage("operator");
    expect(screen.getByTestId("pr-type-badge")).toHaveTextContent(
      t.typeBadge.doctor,
    );
  });

  it("renders the public chrome: home wordmark, subtitle, and step 1", () => {
    renderPage("doctor");
    expect(screen.getByRole("link", { name: /CareSetu/ })).toHaveAttribute(
      "href",
      "/",
    );
    expect(screen.getByText(t.subtitle)).toBeInTheDocument();
    expect(screen.getByTestId("pr-step-1")).toBeInTheDocument();
  });
});
