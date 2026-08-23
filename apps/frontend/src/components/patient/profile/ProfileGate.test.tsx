// PHASE-2.6 T13 (#204): component suite for the inline gating presentation.
// Covers the ticket's acceptance criteria: browse actions never gated;
// intake/booking gated on basics; medicine-delivery checkout gated on
// area; the gate presents the exact missing step inline.

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ProfileGate, ProfileGateDemo } from "./ProfileGate";
import { loadDraft } from "@/lib/profile/profileState";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { __resetLangForTests } from "@/lib/i18n/LangContext";

const en = STRINGS.en.profile;

beforeEach(() => {
  window.localStorage.clear();
  __resetLangForTests();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function type(testId: string, value: string) {
  fireEvent.change(screen.getByTestId(testId), { target: { value } });
}

function select(testId: string, value: string) {
  fireEvent.change(screen.getByTestId(testId), { target: { value } });
}

interface HostProps {
  action: "findCare" | "intake" | "booking" | "medicineCheckout";
}

function Host({ action }: HostProps) {
  return (
    <ProfileGate action={action}>
      <span data-testid="action-btn">Action</span>
    </ProfileGate>
  );
}

describe("ProfileGate", () => {
  it("never gates findCare - renders children directly", () => {
    render(<Host action="findCare" />);
    expect(screen.getByTestId("action-btn")).toBeInTheDocument();
    expect(
      screen.queryByTestId("gate-wizard-findCare"),
    ).not.toBeInTheDocument();
  });

  it("never gates viewRecord - renders children directly", () => {
    const HostView = () => (
      <ProfileGate action="viewRecord">
        <button data-testid="action-btn">Action</button>
      </ProfileGate>
    );
    render(<HostView />);
    expect(screen.getByTestId("action-btn")).toBeInTheDocument();
  });

  it("gates intake on basics and opens wizard on step 1", () => {
    render(<Host action="intake" />);

    // Click the trigger button
    fireEvent.click(screen.getByTestId("gate-trigger-intake"));

    // Wizard should open on step 1 (About you)
    expect(screen.getByTestId("gate-wizard-intake")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: en.s1 })).toBeInTheDocument();
  });

  it("gates booking on basics and opens wizard on step 1", () => {
    render(<Host action="booking" />);

    fireEvent.click(screen.getByTestId("gate-trigger-booking"));

    expect(screen.getByTestId("gate-wizard-booking")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: en.s1 })).toBeInTheDocument();
  });

  it("gates medicineCheckout on area and opens wizard on step 3", () => {
    render(<Host action="medicineCheckout" />);

    fireEvent.click(screen.getByTestId("gate-trigger-medicineCheckout"));

    expect(
      screen.getByTestId("gate-wizard-medicineCheckout"),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: en.s3 })).toBeInTheDocument();
  });

  it("shows gate explanation text", () => {
    render(<Host action="intake" />);

    fireEvent.click(screen.getByTestId("gate-trigger-intake"));

    expect(screen.getByText(en.gate.basicsExplain)).toBeInTheDocument();
  });

  it("shows area gate explanation for medicineCheckout", () => {
    render(<Host action="medicineCheckout" />);

    fireEvent.click(screen.getByTestId("gate-trigger-medicineCheckout"));

    expect(screen.getByText(en.gate.areaExplain)).toBeInTheDocument();
  });

  it("lets user complete basics in inline wizard and closes", () => {
    render(<Host action="intake" />);

    fireEvent.click(screen.getByTestId("gate-trigger-intake"));

    // Wizard opens on step 1 - verify it renders with all step 1 fields
    expect(screen.getByTestId("gate-wizard-intake")).toBeInTheDocument();
    expect(screen.getByTestId("pc-fullname")).toBeInTheDocument();
    expect(screen.getByTestId("pc-age")).toBeInTheDocument();
    expect(screen.getByTestId("pc-gender")).toBeInTheDocument();
    expect(screen.getByTestId("pc-next")).toBeInTheDocument();

    // Fill basics and advance
    type("pc-fullname", "Asha Devi");
    type("pc-age", "30");
    select("pc-gender", "female");

    fireEvent.click(screen.getByTestId("pc-next"));

    // Should advance to step 2
    expect(screen.getByRole("heading", { name: en.s2 })).toBeInTheDocument();
    expect(screen.getByTestId("pc-skip")).toBeInTheDocument();

    // Skip to step 3
    fireEvent.click(screen.getByTestId("pc-skip"));
    expect(screen.getByRole("heading", { name: en.s3 })).toBeInTheDocument();

    // Finish
    fireEvent.click(screen.getByTestId("pc-next"));

    // Wizard should close
    expect(screen.queryByTestId("gate-wizard-intake")).not.toBeInTheDocument();
  });

  it("persists draft to localStorage", () => {
    render(<Host action="intake" />);

    fireEvent.click(screen.getByTestId("gate-trigger-intake"));
    type("pc-fullname", "Asha Devi");
    type("pc-age", "30");
    select("pc-gender", "female");

    expect(loadDraft().name).toBe("Asha Devi");
  });
});

describe("ProfileGateDemo", () => {
  it("renders three demo gates for intake, booking, checkout", () => {
    render(<ProfileGateDemo />);

    expect(screen.getByText(en.demo.intake)).toBeInTheDocument();
    expect(screen.getByText(en.demo.booking)).toBeInTheDocument();
    expect(screen.getByText(en.demo.checkout)).toBeInTheDocument();
  });
});
