// #605: the reusable profile section shell's own suite. It renders the shell
// alone - no page, no provider, no network mock - and drives it with
// `fireEvent`, so the seven responsibilities it owns (title, help text, dirty
// state, its own save button, its own pending state, its own saved confirmation
// and its own error presentation with a retry action) are pinned directly
// rather than inferred from whatever page happens to embed it.

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ProfileSectionShell,
  type SectionSaveResult,
} from "./ProfileSectionShell";

const SAVE = {
  label: "Save changes",
  savedLabel: "Profile saved.",
  unsavedLabel: "Unsaved changes",
  failureMessage: "Could not save your profile.",
  dirty: false,
  edits: 0,
  buttonTestId: "practice-save",
  savedTestId: "practice-saved",
  unsavedTestId: "practice-unsaved",
};

const saved: SectionSaveResult = { status: "saved" };
const declined: SectionSaveResult = { status: "declined" };
const failed: SectionSaveResult = {
  status: "failed",
  failure: { traceId: "trace-section-605" },
};

interface HarnessProps {
  onSave?: () => Promise<SectionSaveResult>;
  dirty?: boolean;
  edits?: number;
  /** Renders the read-only shape: no save affordance at all. */
  readOnly?: boolean;
}

function Harness({
  onSave,
  dirty = false,
  edits = 0,
  readOnly = false,
}: HarnessProps) {
  return (
    <ProfileSectionShell
      title="Practice details"
      help="What patients see in the directory."
      testId="practice-shell"
      save={
        readOnly
          ? undefined
          : {
              ...SAVE,
              dirty,
              edits,
              onSave: onSave ?? (() => Promise.resolve(saved)),
            }
      }
    >
      <input data-testid="practice-name" defaultValue="Sunrise Clinic" />
    </ProfileSectionShell>
  );
}

/** A write held open, so "pending" is observable rather than a race. */
function deferred(): {
  promise: Promise<SectionSaveResult>;
  settle: (result: SectionSaveResult) => void;
} {
  let settle: (result: SectionSaveResult) => void = () => {};
  const promise = new Promise<SectionSaveResult>((resolve) => {
    settle = resolve;
  });
  return { promise, settle };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("ProfileSectionShell", () => {
  it("owns the section's title and help text", () => {
    render(<Harness readOnly />);

    expect(screen.getByText("Practice details")).toBeInTheDocument();
    expect(
      screen.getByText("What patients see in the directory."),
    ).toBeInTheDocument();
  });

  it("gives the page outline a real heading to skip between", () => {
    render(<Harness readOnly />);

    expect(
      screen.getByRole("heading", { level: 2, name: "Practice details" }),
    ).toBeInTheDocument();
  });

  it("renders the section's own fields", () => {
    render(<Harness readOnly />);

    expect(screen.getByTestId("practice-name")).toBeInTheDocument();
  });

  it("renders no save affordance at all for a section that has none", () => {
    render(<Harness readOnly />);

    expect(screen.queryByTestId("practice-save")).toBeNull();
    expect(screen.queryByTestId("practice-saved")).toBeNull();
    expect(screen.queryByTestId("error-banner")).toBeNull();
    // No form either: a read-only band has nothing to submit.
    expect(screen.getByTestId("practice-shell").tagName).toBe("DIV");
  });

  it("gives a section with a save its own save button", () => {
    render(<Harness />);

    expect(screen.getByTestId("practice-save")).toHaveTextContent(SAVE.label);
    expect(screen.getByTestId("practice-shell").tagName).toBe("FORM");
  });

  it("owns its pending state: a spinner inside the button, disabled while pending", async () => {
    const write = deferred();
    render(<Harness onSave={() => write.promise} />);

    fireEvent.click(screen.getByTestId("practice-save"));

    const button = screen.getByTestId("practice-save");
    expect(button).toBeDisabled();
    expect(screen.getByTestId("button-spinner")).toBeInTheDocument();

    write.settle(saved);
    await waitFor(() =>
      expect(screen.getByTestId("practice-save")).toBeEnabled(),
    );
  });

  it("shows its own saved confirmation after a saved attempt", async () => {
    render(<Harness onSave={() => Promise.resolve(saved)} />);

    fireEvent.click(screen.getByTestId("practice-save"));

    const confirmation = await screen.findByTestId("practice-saved");
    expect(confirmation).toHaveTextContent(SAVE.savedLabel);
    expect(screen.queryByTestId("error-banner")).toBeNull();
  });

  it("stays quiet when the section declines the attempt", async () => {
    render(<Harness onSave={() => Promise.resolve(declined)} />);

    fireEvent.click(screen.getByTestId("practice-save"));

    await waitFor(() =>
      expect(screen.getByTestId("practice-save")).toBeEnabled(),
    );
    expect(screen.queryByTestId("practice-saved")).toBeNull();
    expect(screen.queryByTestId("error-banner")).toBeNull();
  });

  it("presents a failed attempt in place, with the trace id and a retry action", async () => {
    render(<Harness onSave={() => Promise.resolve(failed)} />);

    fireEvent.click(screen.getByTestId("practice-save"));

    const banner = await screen.findByTestId("error-banner");
    expect(banner).toHaveTextContent(SAVE.failureMessage);
    expect(screen.getByTestId("error-banner-trace-id")).toHaveTextContent(
      "trace-section-605",
    );
    expect(screen.getByTestId("error-banner-retry")).toBeInTheDocument();
  });

  it("retries the same attempt from its own retry action", async () => {
    const onSave = vi
      .fn<() => Promise<SectionSaveResult>>()
      .mockResolvedValueOnce(failed)
      .mockResolvedValueOnce(saved);
    render(<Harness onSave={onSave} />);

    fireEvent.click(screen.getByTestId("practice-save"));
    await screen.findByTestId("error-banner");

    fireEvent.click(screen.getByTestId("error-banner-retry"));

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(2));
    // The retry replaces the failure rather than stacking a second banner.
    await waitFor(() =>
      expect(screen.queryByTestId("error-banner")).toBeNull(),
    );
    expect(screen.getByTestId("practice-saved")).toHaveTextContent(
      SAVE.savedLabel,
    );
  });

  it("drops the error presentation when it is dismissed", async () => {
    render(<Harness onSave={() => Promise.resolve(failed)} />);

    fireEvent.click(screen.getByTestId("practice-save"));
    await screen.findByTestId("error-banner");

    fireEvent.click(screen.getByTestId("error-banner-dismiss"));

    expect(screen.queryByTestId("error-banner")).toBeNull();
  });

  it("presents an unclassified throw as a failed attempt rather than letting it escape", async () => {
    render(
      <Harness onSave={() => Promise.reject(new Error("no classification"))} />,
    );

    fireEvent.click(screen.getByTestId("practice-save"));

    const banner = await screen.findByTestId("error-banner");
    expect(banner).toHaveTextContent(SAVE.failureMessage);
    await waitFor(() =>
      expect(screen.getByTestId("practice-save")).toBeEnabled(),
    );
  });

  it("shows the unsaved hint once the section is dirty", () => {
    const { rerender } = render(<Harness />);
    expect(screen.queryByTestId("practice-unsaved")).toBeNull();

    rerender(<Harness dirty edits={1} />);

    expect(screen.getByTestId("practice-unsaved")).toHaveTextContent(
      SAVE.unsavedLabel,
    );
  });

  it("never shows the unsaved hint beside a saved confirmation", async () => {
    // The dirty flag latches for the rest of the session by design, so the
    // shell cannot render it next to a confirmation without claiming the
    // section is saved and unsaved at the same time.
    render(<Harness onSave={() => Promise.resolve(saved)} dirty edits={1} />);

    fireEvent.click(screen.getByTestId("practice-save"));

    await screen.findByTestId("practice-saved");
    expect(screen.queryByTestId("practice-unsaved")).toBeNull();
  });

  it("brings the unsaved hint back when a later edit outdates the confirmation", async () => {
    const onSave = () => Promise.resolve(saved);
    const { rerender } = render(<Harness onSave={onSave} dirty edits={1} />);
    fireEvent.click(screen.getByTestId("practice-save"));
    await screen.findByTestId("practice-saved");

    rerender(<Harness onSave={onSave} dirty edits={2} />);

    expect(screen.queryByTestId("practice-saved")).toBeNull();
    expect(screen.getByTestId("practice-unsaved")).toHaveTextContent(
      SAVE.unsavedLabel,
    );
  });

  it("still reports a landed save whose reply outran the doctor", async () => {
    // The edit lands before the reply, so the reset never sees a confirmation to
    // clear: the save reports itself saved for the fields it actually sent.
    const write = deferred();
    const onSave = () => write.promise;
    const { rerender } = render(<Harness onSave={onSave} />);

    fireEvent.click(screen.getByTestId("practice-save"));
    rerender(<Harness onSave={onSave} dirty edits={1} />);
    write.settle(saved);

    await screen.findByTestId("practice-saved");
  });

  it("outdates its error presentation when the doctor keeps typing", async () => {
    const onSave = () => Promise.resolve(failed);
    const { rerender } = render(<Harness onSave={onSave} />);
    fireEvent.click(screen.getByTestId("practice-save"));
    await screen.findByTestId("error-banner");

    rerender(<Harness onSave={onSave} dirty edits={1} />);

    expect(screen.queryByTestId("error-banner")).toBeNull();
  });
});
