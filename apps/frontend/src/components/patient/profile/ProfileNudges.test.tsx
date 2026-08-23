// PHASE-2.6 T13 (#204): component suite for the Home-surface nudge cards
// and completion meter. Cards are dismissible per missing group without
// modals; meter reflects the draft completeness percentage.

import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import * as axe from "axe-core";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ProfileCompletionMeter, ProfileNudgeCards } from "./ProfileNudges";
import { initialDraft, type ProfileDraft } from "@/lib/profile/profileState";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { __resetLangForTests, useLang } from "@/lib/i18n/LangContext";
import {
  dismissNudge,
  isNudgeDismissed,
  __resetNudgeDismissalsForTests,
} from "@/lib/profile/profileState";

const en = STRINGS.en.profile;
const hi = STRINGS.hi.profile;

beforeEach(() => {
  window.localStorage.clear();
  __resetLangForTests();
  __resetNudgeDismissalsForTests();
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

function LangFlip() {
  const { lang, setLang } = useLang();
  return (
    <button
      type="button"
      data-testid="lang-flip"
      onClick={() => setLang(lang === "en" ? "hi" : "en")}
    >
      flip
    </button>
  );
}

interface HostProps {
  draft?: ProfileDraft;
  onCompleteHref?: string;
}

function Host({
  draft = initialDraft(),
  onCompleteHref = "/patient/profile/complete",
}: HostProps) {
  return (
    <div>
      <ProfileCompletionMeter draft={draft} />
      <ProfileNudgeCards draft={draft} onCompleteHref={onCompleteHref} />
    </div>
  );
}

function HostWithLangFlip({
  draft = initialDraft(),
  onCompleteHref = "/patient/profile/complete",
}: HostProps) {
  return (
    <>
      <Host draft={draft} onCompleteHref={onCompleteHref} />
      <LangFlip />
    </>
  );
}

describe("ProfileCompletionMeter", () => {
  it("shows 0% with the label when the draft is empty", () => {
    render(<Host />);

    expect(screen.getByTestId("pc-meter")).toHaveAttribute(
      "aria-valuenow",
      "0",
    );
    expect(screen.getByTestId("pc-meter-label")).toHaveTextContent("0%");
    expect(screen.getByText(en.meterLabel)).toBeInTheDocument();
  });

  it("moves toward 100% as the draft fills", () => {
    render(<Host draft={initialDraft()} />);
    expect(screen.getByTestId("pc-meter")).toHaveAttribute(
      "aria-valuenow",
      "0",
    );

    // We can't mutate the passed draft prop directly; a parent would re-render.
    // So we simulate by re-rendering with a filled draft.
    cleanup();
    const filled = {
      ...initialDraft(),
      name: "Asha",
      age: "30",
      gender: "female" as const,
    };
    render(<Host draft={filled} />);
    const pct = Number(
      screen.getByTestId("pc-meter").getAttribute("aria-valuenow"),
    );
    expect(pct).toBeGreaterThan(0);
    expect(pct).toBeLessThan(100);
  });

  it("shows 100% for a fully complete draft", () => {
    const full = {
      ...initialDraft(),
      name: "Asha",
      age: "30",
      gender: "female" as const,
      trackBp: true,
      photoFileName: "me.jpg",
      area: "Bishrampur",
      emergencyContact: "+91",
    };
    render(<Host draft={full} />);
    expect(screen.getByTestId("pc-meter")).toHaveAttribute(
      "aria-valuenow",
      "100",
    );
  });
});

describe("ProfileNudgeCards", () => {
  it("renders one card per missing group when the draft is empty", () => {
    render(<Host />);

    expect(screen.getByText(en.nudges.basicsTitle)).toBeInTheDocument();
    expect(screen.getByText(en.nudges.trackingTitle)).toBeInTheDocument();
    expect(screen.getByText(en.nudges.photoTitle)).toBeInTheDocument();
    expect(screen.getByText(en.nudges.areaTitle)).toBeInTheDocument();
    expect(screen.getByText(en.nudges.emergencyTitle)).toBeInTheDocument();
  });

  it("omits a group once its item is filled", () => {
    render(<Host draft={{ ...initialDraft(), trackSugar: true }} />);
    expect(screen.queryByText(en.nudges.trackingTitle)).not.toBeInTheDocument();
    expect(screen.getByText(en.nudges.basicsTitle)).toBeInTheDocument();

    cleanup();
    render(<Host draft={{ ...initialDraft(), area: "Bishrampur" }} />);
    expect(screen.queryByText(en.nudges.areaTitle)).not.toBeInTheDocument();
    expect(screen.getByText(en.nudges.basicsTitle)).toBeInTheDocument();
  });

  it("lets a card be dismissed without a modal", () => {
    render(<Host />);

    // Debug: see all dismiss buttons
    const allDismiss = screen.getAllByTestId(/pc-dismiss/);
    console.log(
      "Dismiss buttons found:",
      allDismiss.map((b) => b.getAttribute("data-testid")),
    );

    // Click dismiss on the area card
    const dismissBtn = screen.getByTestId("pc-dismiss-area");
    fireEvent.click(dismissBtn);

    expect(screen.queryByText(en.nudges.areaTitle)).not.toBeInTheDocument();
    expect(screen.getByText(en.nudges.basicsTitle)).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("renders the Complete profile CTA linking to the wizard route", () => {
    render(<Host />);
    const links = screen.getAllByTestId("pc-complete-cta");
    expect(links.length).toBeGreaterThan(0);
    expect(links[0]).toHaveAttribute("href", "/patient/profile/complete");
    expect(links[0]).toHaveTextContent(en.nudges.completeCta);
  });

  it("flips to Hindi when the app locale changes", () => {
    render(<HostWithLangFlip />);

    // Flip language using the test helper
    fireEvent.click(screen.getByTestId("lang-flip"));

    // Card titles now come from hi dict
    expect(screen.getByText(hi.nudges.basicsTitle)).toBeInTheDocument();
  });

  it("renders nothing when the draft is fully complete", () => {
    const full = {
      ...initialDraft(),
      name: "Asha",
      age: "30",
      gender: "female" as const,
      trackBp: true,
      photoFileName: "me.jpg",
      area: "Bishrampur",
      emergencyContact: "+91",
    };
    render(<Host draft={full} />);
    expect(screen.queryByTestId("pc-nudge-card")).not.toBeInTheDocument();
  });

  it("scans clean on axe", async () => {
    const { container } = render(<Host />);
    expect((await axe.run(container)).violations).toEqual([]);
  });
});
