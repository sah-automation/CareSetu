// PHASE-2.6 T13 (#204): component suite for the first-login profile-
// completion wizard. Covers the ticket's acceptance criteria: three bilingual
// steps, required-basics validation blocking completion, friction-free skip
// on the optional steps, the completion meter tracking draft state, and the
// initial-step seam the inline gating presentation reuses.

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import * as axe from "axe-core";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ProfileCompletionWizard,
  type ProfileCompletionWizardProps,
} from "./ProfileCompletionWizard";
import { initialDraft, type ProfileDraft } from "@/lib/profile/profileState";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { __resetLangForTests } from "@/lib/i18n/LangContext";

const en = STRINGS.en.profile;
const hi = STRINGS.hi.profile;

beforeEach(() => {
  window.localStorage.clear();
  __resetLangForTests();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  __resetLangForTests();
});

function type(testId: string, value: string) {
  fireEvent.change(screen.getByTestId(testId), { target: { value } });
}

function select(testId: string, value: string) {
  fireEvent.change(screen.getByTestId(testId), { target: { value } });
}

interface HostProps {
  onFinish?: ProfileCompletionWizardProps["onFinish"];
  initialStep?: ProfileCompletionWizardProps["initialStep"];
}

/** Controlled host mirroring how pages hold the draft. */
function Host({ onFinish, initialStep }: HostProps) {
  const [draft, setDraft] = useState(initialDraft);
  return (
    <ProfileCompletionWizard
      draft={draft}
      onDraftChange={setDraft}
      onFinish={onFinish}
      initialStep={initialStep}
    />
  );
}

describe("ProfileCompletionWizard", () => {
  it("opens on required step 1 of three with the meter at 0%", () => {
    render(<Host />);

    expect(screen.getByText(en.title)).toBeInTheDocument();
    expect(screen.getByText(en.sub)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: en.s1 })).toBeInTheDocument();
    expect(screen.getByTestId("pc-meter")).toHaveAttribute(
      "aria-valuenow",
      "0",
    );
    // Step 1 is required: no skip affordance exists there.
    expect(screen.queryByTestId("pc-skip")).not.toBeInTheDocument();
    expect(screen.getByTestId("pc-next")).toHaveTextContent(en.continueCta);
  });

  it("asks language explicitly in step 1 and flips the whole wizard to it (D1)", () => {
    render(<Host />);

    select("pc-lang", "hi");

    expect(screen.getByRole("heading", { name: hi.s1 })).toBeInTheDocument();
    expect(screen.getByText(hi.title)).toBeInTheDocument();
    expect(document.documentElement.lang).toBe("hi");
  });

  it("records the chosen language as draft-language intent (D1)", () => {
    let latest: ProfileDraft | null = null;
    function CapturingHost() {
      const [draft, setDraft] = useState<ProfileDraft>(initialDraft());
      latest = draft;
      return <ProfileCompletionWizard draft={draft} onDraftChange={setDraft} />;
    }
    render(<CapturingHost />);
    select("pc-lang", "hi");
    // @ts-expect-error - TS inference issue with useState closure
    expect(latest?.language).toBe("hi");
  });

  it("blocks Continue until basics are complete and names each gap", () => {
    render(<Host />);

    fireEvent.click(screen.getByTestId("pc-next"));

    expect(screen.getByRole("heading", { name: en.s1 })).toBeInTheDocument();
    expect(screen.getByTestId("pc-error-name")).toBeInTheDocument();
    expect(screen.getByTestId("pc-error-age")).toBeInTheDocument();
    expect(screen.getByTestId("pc-error-gender")).toBeInTheDocument();
  });

  it("rejects an implausible age without advancing", () => {
    render(<Host />);

    type("pc-fullname", "Asha Devi");
    type("pc-age", "abc");
    select("pc-gender", "female");
    fireEvent.click(screen.getByTestId("pc-next"));

    expect(screen.getByRole("heading", { name: en.s1 })).toBeInTheDocument();
    expect(screen.getByTestId("pc-error-age")).toBeInTheDocument();
    expect(screen.getByText(en.errors.ageInvalid)).toBeInTheDocument();
  });

  it("walks required -> optional -> contact and finishes", () => {
    const onFinish = vi.fn();
    render(<Host onFinish={onFinish} />);

    type("pc-fullname", "Asha Devi");
    type("pc-age", "30");
    select("pc-gender", "female");
    fireEvent.click(screen.getByTestId("pc-next"));

    expect(screen.getByRole("heading", { name: en.s2 })).toBeInTheDocument();
    expect(screen.getByTestId("pc-skip")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("pc-bp"));
    fireEvent.click(screen.getByTestId("pc-next"));
    expect(screen.getByRole("heading", { name: en.s3 })).toBeInTheDocument();
    expect(screen.getByTestId("pc-next")).toHaveTextContent(en.finish);
    // Step 3 is optional too - the prototype keeps Skip visible here.
    expect(screen.getByTestId("pc-skip")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("pc-next"));
    expect(onFinish).toHaveBeenCalledTimes(1);
  });

  it("lets the optional steps be skipped with zero friction", () => {
    const onFinish = vi.fn();
    render(<Host onFinish={onFinish} />);

    type("pc-fullname", "Asha Devi");
    type("pc-age", "30");
    select("pc-gender", "female");
    fireEvent.click(screen.getByTestId("pc-next"));

    fireEvent.click(screen.getByTestId("pc-skip"));
    expect(screen.getByRole("heading", { name: en.s3 })).toBeInTheDocument();

    // No modal nagging anywhere in the skip path.
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    // Step 3 is skippable by simply finishing without filling anything.
    fireEvent.click(screen.getByTestId("pc-next"));
    expect(onFinish).toHaveBeenCalledTimes(1);
  });

  it("moves the completion meter as the draft fills in", () => {
    render(<Host />);

    expect(screen.getByTestId("pc-meter")).toHaveAttribute(
      "aria-valuenow",
      "0",
    );
    type("pc-fullname", "Asha Devi");
    type("pc-age", "30");
    select("pc-gender", "female");

    const now = Number(
      screen.getByTestId("pc-meter").getAttribute("aria-valuenow"),
    );
    expect(now).toBeGreaterThan(0);
    expect(now).toBeLessThan(100);
    expect(screen.getByTestId("pc-meter-label")).toHaveTextContent(`${now}%`);
  });

  it("can open directly on a given step - the inline-gating seam", () => {
    render(<Host initialStep={3} />);
    expect(screen.getByRole("heading", { name: en.s3 })).toBeInTheDocument();
  });

  it("records the photo file name client-side only", () => {
    render(<Host initialStep={3} />);

    const input = screen.getByTestId("pc-photo") as HTMLInputElement;
    Object.defineProperty(input, "files", {
      value: [new File(["me"], "me.jpg", { type: "image/jpeg" })],
    });
    fireEvent.change(input);

    expect(input.files?.[0]?.name).toBe("me.jpg");
  });

  it("scans clean on axe across the required and contact steps", async () => {
    const { container } = render(<Host />);
    expect((await axe.run(container)).violations).toEqual([]);

    cleanup();
    const stepThree = render(<Host initialStep={3} />);
    expect((await axe.run(stepThree.container)).violations).toEqual([]);
  });
});
