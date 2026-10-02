// #605: the per-section edit buffer's own suite. It renders tiny harnesses that
// each own one buffer and are driven with `fireEvent`, so the rules the buffer
// exists to keep - seed once per distinct server answer, never reseed a dirty
// buffer, never let a save's own reply discard keystrokes, and keep two
// sections' buffers independent - are pinned here without the doctor profile
// page, its provider or its network mocks. The page suite keeps the end-to-end
// proof that the page still behaves; this suite pins the rule.

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useSectionEditBuffer } from "./useSectionEditBuffer";

/** The server's whole answer, the one every section's mapper is handed. */
interface Answer {
  practice_name: string;
  about: string;
}

/** One section's slice of that answer - the only thing its buffer holds. */
interface Slice {
  name: string;
}

const FIRST: Answer = {
  practice_name: "Sunrise Clinic",
  about: "Twelve years of primary care.",
};

/** A genuinely different answer: a new object, moved fields. */
const SECOND: Answer = {
  practice_name: "Sunrise Clinic, moved",
  about: "Now on the second floor.",
};

const practiceSlice = (answer: Answer): Slice => ({
  name: answer.practice_name,
});

const aboutSlice = (answer: Answer): Slice => ({ name: answer.about });

interface SectionProps {
  label: string;
  answer: Answer | null;
  toSlice: (answer: Answer) => Slice;
  onAdopt: (next: Answer) => void;
  write?: () => Promise<Answer>;
}

function Section({ label, answer, toSlice, onAdopt, write }: SectionProps) {
  const buffer = useSectionEditBuffer(answer, toSlice);
  const [saved, setSaved] = useState(false);

  // A save's reply is adopted through the same seam every other answer uses,
  // because that is exactly what it is: another server answer.
  async function runSave() {
    setSaved(false);
    const reply = await write?.();
    if (reply) onAdopt(reply);
    setSaved(true);
  }

  return (
    <section data-testid={label}>
      <input
        data-testid={`${label}-name`}
        value={buffer.value?.name ?? ""}
        onChange={(event) => buffer.change({ name: event.target.value })}
      />
      <span data-testid={`${label}-dirty`}>{String(buffer.dirty)}</span>
      <span data-testid={`${label}-edits`}>{String(buffer.edits)}</span>
      {saved && <span data-testid={`${label}-saved`}>saved</span>}
      <button type="button" data-testid={`${label}-save`} onClick={runSave}>
        save
      </button>
    </section>
  );
}

interface HostProps {
  toSlice: (answer: Answer) => Slice;
  write?: () => Promise<Answer>;
}

/**
 * One section inside a host that owns the answer, so a test can put a fresh
 * server answer in front of the buffer on demand, and can re-render the very
 * same answer object as often as it likes.
 */
function Host({ toSlice, write }: HostProps) {
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [renderCount, setRenderCount] = useState(0);

  return (
    <>
      <button
        type="button"
        data-testid="first-answer"
        onClick={() => setAnswer(FIRST)}
      >
        first
      </button>
      {/* The same object back: only the render changes. */}
      <button
        type="button"
        data-testid="same-answer"
        onClick={() => setRenderCount((count) => count + 1)}
      >
        same
      </button>
      <button
        type="button"
        data-testid="second-answer"
        onClick={() => setAnswer(SECOND)}
      >
        second
      </button>
      <span data-testid="render-count">{renderCount}</span>
      <Section
        label="section"
        answer={answer}
        toSlice={toSlice}
        onAdopt={setAnswer}
        write={write}
      />
    </>
  );
}

/** Two sections sharing one answer object - the four-independent-sections shape. */
function TwoSectionHost() {
  const [answer, setAnswer] = useState<Answer | null>(null);

  return (
    <>
      <button
        type="button"
        data-testid="first-answer"
        onClick={() => setAnswer(FIRST)}
      >
        first
      </button>
      <button
        type="button"
        data-testid="second-answer"
        onClick={() => setAnswer(SECOND)}
      >
        second
      </button>
      <Section
        label="practice"
        answer={answer}
        toSlice={practiceSlice}
        onAdopt={setAnswer}
      />
      <Section
        label="about"
        answer={answer}
        toSlice={aboutSlice}
        onAdopt={setAnswer}
      />
    </>
  );
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("useSectionEditBuffer", () => {
  it("seeds the section's slice from the server answer", () => {
    render(<Host toSlice={practiceSlice} />);

    fireEvent.click(screen.getByTestId("first-answer"));

    expect(screen.getByTestId("section-name")).toHaveValue("Sunrise Clinic");
    expect(screen.getByTestId("section-dirty")).toHaveTextContent("false");
    expect(screen.getByTestId("section-edits")).toHaveTextContent("0");
  });

  // #623: `change` used to set the dirty ref before folding the patch, so an edit
  // that arrived before the buffer's first answer was dropped AND armed rule 2
  // against the answer that was about to seed it. The buffer then stayed empty for
  // the rest of the session: the flag claimed the doctor was mid-edit while the
  // field held nothing, and the reseed guard honoured the flag. This is the exact
  // sequence - the host starts with no answer at all.
  it("still seeds after an edit that landed before the first answer", () => {
    render(<Host toSlice={practiceSlice} />);

    // No answer yet, so there is no slice to fold into.
    fireEvent.change(screen.getByTestId("section-name"), {
      target: { value: "typed too early" },
    });
    // The dropped edit must not have latched the flag or counted as an edit.
    expect(screen.getByTestId("section-dirty")).toHaveTextContent("false");
    expect(screen.getByTestId("section-edits")).toHaveTextContent("0");

    fireEvent.click(screen.getByTestId("first-answer"));

    // The seed lands and renders - the section is alive, not silently dead.
    expect(screen.getByTestId("section-name")).toHaveValue("Sunrise Clinic");
    expect(screen.getByTestId("section-dirty")).toHaveTextContent("false");
  });

  it("latches and counts an edit that lands after the first answer", () => {
    render(<Host toSlice={practiceSlice} />);

    fireEvent.click(screen.getByTestId("first-answer"));
    fireEvent.change(screen.getByTestId("section-name"), {
      target: { value: "Sunrise Clinic, typed" },
    });

    // The mirror above is only correct for the seeded path; a real edit folds and
    // latches exactly as it always did.
    expect(screen.getByTestId("section-name")).toHaveValue(
      "Sunrise Clinic, typed",
    );
    expect(screen.getByTestId("section-dirty")).toHaveTextContent("true");
    expect(screen.getByTestId("section-edits")).toHaveTextContent("1");

    // And two edits compose rather than the second replacing the first.
    fireEvent.change(screen.getByTestId("section-name"), {
      target: { value: "Sunrise Clinic, typed more" },
    });
    expect(screen.getByTestId("section-name")).toHaveValue(
      "Sunrise Clinic, typed more",
    );
    expect(screen.getByTestId("section-edits")).toHaveTextContent("2");
  });

  it("seeds again for a distinct answer while the buffer is clean", () => {
    render(<Host toSlice={practiceSlice} />);

    fireEvent.click(screen.getByTestId("first-answer"));
    fireEvent.click(screen.getByTestId("second-answer"));

    // Object identity is the mechanism, so a different answer does reseed.
    expect(screen.getByTestId("section-name")).toHaveValue(
      "Sunrise Clinic, moved",
    );
  });

  it("never reseeds for the same answer object, however often the page re-renders", () => {
    render(<Host toSlice={practiceSlice} />);
    fireEvent.click(screen.getByTestId("first-answer"));

    fireEvent.change(screen.getByTestId("section-name"), {
      target: { value: "Sunrise Clinic, typing" },
    });
    fireEvent.click(screen.getByTestId("same-answer"));
    fireEvent.click(screen.getByTestId("same-answer"));

    expect(screen.getByTestId("render-count")).toHaveTextContent("2");
    expect(screen.getByTestId("section-name")).toHaveValue(
      "Sunrise Clinic, typing",
    );
  });

  it("never reseeds a dirty buffer when a late answer lands", () => {
    render(<Host toSlice={practiceSlice} />);
    fireEvent.click(screen.getByTestId("first-answer"));

    fireEvent.change(screen.getByTestId("section-name"), {
      target: { value: "Sunrise Clinic, typing" },
    });
    fireEvent.click(screen.getByTestId("second-answer"));

    expect(screen.getByTestId("section-name")).toHaveValue(
      "Sunrise Clinic, typing",
    );
    expect(screen.getByTestId("section-dirty")).toHaveTextContent("true");
    expect(screen.getByTestId("section-edits")).toHaveTextContent("1");
  });

  it("keeps in-progress typing when a save's own reply lands after it", async () => {
    // The write is held open so the reply provably lands after the keystrokes; a
    // write that resolved on the spot would be adopted before the typing and
    // would prove nothing.
    let settle: (next: Answer) => void = () => {};
    const write = () =>
      new Promise<Answer>((resolve) => {
        settle = resolve;
      });
    render(<Host toSlice={practiceSlice} write={write} />);
    fireEvent.click(screen.getByTestId("first-answer"));

    fireEvent.click(screen.getByTestId("section-save"));
    fireEvent.change(screen.getByTestId("section-name"), {
      target: { value: "Sunrise Clinic, typing" },
    });

    // The save's reply carries the name as it was when the button was clicked.
    settle(SECOND);
    await waitFor(() =>
      expect(screen.getByTestId("section-saved")).toBeInTheDocument(),
    );

    expect(screen.getByTestId("section-name")).toHaveValue(
      "Sunrise Clinic, typing",
    );
  });

  it("keeps two buffers side by side without one section's answer reseeding the other", () => {
    render(<TwoSectionHost />);
    fireEvent.click(screen.getByTestId("first-answer"));

    fireEvent.change(screen.getByTestId("about-name"), {
      target: { value: "Mid-sentence edit." },
    });
    fireEvent.click(screen.getByTestId("second-answer"));

    // The about buffer was dirty, so it holds the doctor's typing...
    expect(screen.getByTestId("about-name")).toHaveValue("Mid-sentence edit.");
    // ...while the practice buffer, clean, took the new answer as its own.
    expect(screen.getByTestId("practice-name")).toHaveValue(
      "Sunrise Clinic, moved",
    );
  });

  it("keeps the practice buffer's typing while the same answer reseeds the about buffer", () => {
    render(<TwoSectionHost />);
    fireEvent.click(screen.getByTestId("first-answer"));

    fireEvent.change(screen.getByTestId("practice-name"), {
      target: { value: "Sunrise Clinic, typing" },
    });
    fireEvent.click(screen.getByTestId("second-answer"));

    expect(screen.getByTestId("practice-name")).toHaveValue(
      "Sunrise Clinic, typing",
    );
    expect(screen.getByTestId("about-name")).toHaveValue(
      "Now on the second floor.",
    );
  });

  it("holds no value until the first answer arrives", () => {
    render(<Host toSlice={aboutSlice} />);

    expect(screen.getByTestId("section-name")).toHaveValue("");
    expect(screen.getByTestId("section-dirty")).toHaveTextContent("false");
  });
});
