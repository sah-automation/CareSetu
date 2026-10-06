// FEAT-008 / #651 (spec #645 "Shared doctor card"): the one card both doctor
// lists render. Pins the anatomy (avatar/name/age/chips/stage/meta/whole-card
// link), the single-focus-stop rule with a patient-bearing accessible name
// (US-66/67), the decorative avatar, and that a worded stage label passes
// through verbatim (US-18).

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

import { DoctorListCard, type DoctorListCardProps } from "./DoctorListCard";

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...rest
  }: {
    href: string;
    children?: ReactNode;
  }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

afterEach(() => {
  cleanup();
});

function card(overrides: Partial<DoctorListCardProps> = {}) {
  return (
    <DoctorListCard
      href="/doctor/patients/11"
      name="Asha Devi"
      ageText="45 yrs"
      chips={[
        { key: "consultations", label: "Consultations", testId: "scope-a" },
      ]}
      stage={{ label: "Pre-summary", tone: "bg-warn-soft text-warn-text" }}
      meta="Open"
      accessibleName="Open Asha Devi"
      nameTestId="card-name"
      stageTestId="card-stage"
      linkTestId="card-open"
      {...overrides}
    />
  );
}

describe("DoctorListCard", () => {
  it("renders the full anatomy: avatar, name, age, chips, stage, meta, link", () => {
    render(card());

    expect(screen.getByTestId("card-name")).toHaveTextContent("Asha Devi");
    expect(screen.getByText("45 yrs")).toBeInTheDocument();
    expect(screen.getByTestId("scope-a")).toHaveTextContent("Consultations");
    expect(screen.getByTestId("card-stage")).toHaveTextContent("Pre-summary");
    expect(screen.getByText("Open")).toBeInTheDocument();

    const link = screen.getByTestId("card-open");
    expect(link).toHaveAttribute("href", "/doctor/patients/11");

    const avatar = document.querySelector("span[aria-hidden='true']");
    expect(avatar).not.toBeNull();
    expect(avatar).toHaveTextContent("A");
  });

  it("renders the avatar as the decorative initials branch, never a photo", () => {
    render(card());

    const avatar = document.querySelector("span[aria-hidden='true']");
    expect(avatar).not.toBeNull();
    expect(avatar).not.toHaveAttribute("role");
    expect(document.querySelector("img")).toBeNull();
  });

  it("is a single focus stop whose accessible name includes the patient (#651 AC-2)", () => {
    render(card());

    const cardRoot = screen.getByTestId("card-open").parentElement;
    const focusables = cardRoot!.querySelectorAll(
      "a[href], button, input, select, textarea, [tabindex]",
    );
    expect(focusables).toHaveLength(1);

    expect(screen.getByTestId("card-open")).toHaveAttribute(
      "aria-label",
      "Open Asha Devi",
    );
  });

  it("renders the worded stage label and its tone verbatim (#651 AC-6)", () => {
    render(
      card({
        stage: { label: "No open case", tone: "bg-surface text-txt-muted" },
      }),
    );

    const stage = screen.getByTestId("card-stage");
    expect(stage).toHaveTextContent("No open case");
    expect(stage.textContent?.trim()).not.toBe("");
    expect(stage.className).toContain("bg-surface");
  });

  it("uses the Badge primitive for chips and the Card primitive for the shell", () => {
    render(card());

    const chip = screen.getByTestId("scope-a");
    expect(chip.tagName).toBe("DIV");
    expect(chip.className).toContain("rounded-full");
    expect(chip.className).toContain("bg-accent-soft");

    const shell = screen.getByTestId("card-open").parentElement;
    expect(shell?.className).toContain("rounded-lg");
    expect(shell?.className).toContain("shadow-card");
    expect(shell?.className).toContain("bg-surface");
  });
});
