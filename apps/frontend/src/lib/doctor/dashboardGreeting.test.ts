// FEAT-008 (#678): the greeting helpers' focused unit suite. The time-of-day decision and
// the honorific strip are pure, so each is driven with explicit dates and names
// instead of fake timers at the page seam - the page-level suite only has to
// assert that the greeting renders a name or does not.

import { describe, expect, it } from "vitest";

import { STRINGS } from "@/lib/i18n/dictionaries";
import {
  formatGreetingDate,
  greetingFirstName,
  greetingPart,
  greetingTimeText,
} from "./dashboardGreeting";

describe("greetingPart (#678)", () => {
  it("says good morning before noon", () => {
    expect(greetingPart(new Date(2026, 9, 9, 6, 0))).toBe("morning");
    expect(greetingPart(new Date(2026, 9, 9, 11, 59))).toBe("morning");
  });

  it("says good afternoon from noon until before 5pm", () => {
    expect(greetingPart(new Date(2026, 9, 9, 12, 0))).toBe("afternoon");
    expect(greetingPart(new Date(2026, 9, 9, 16, 59))).toBe("afternoon");
  });

  it("says good evening from 5pm, including the first hours of the night", () => {
    expect(greetingPart(new Date(2026, 9, 9, 17, 0))).toBe("evening");
    expect(greetingPart(new Date(2026, 9, 9, 23, 59))).toBe("evening");
    // Midnight back to morning: the hour 0 belongs to morning, not the previous
    // evening.
    expect(greetingPart(new Date(2026, 9, 9, 0, 0))).toBe("morning");
  });
});

describe("greetingTimeText (#678)", () => {
  const en = STRINGS.en.doctorConsole;
  const hi = STRINGS.hi.doctorConsole;

  it("picks the morning copy before noon in both locales", () => {
    expect(greetingTimeText(en, new Date(2026, 9, 9, 6, 0))).toBe(
      "Good morning",
    );
    expect(greetingTimeText(hi, new Date(2026, 9, 9, 6, 0))).toBe("सुप्रभात");
  });

  it("picks the afternoon copy from noon in both locales", () => {
    expect(greetingTimeText(en, new Date(2026, 9, 9, 12, 0))).toBe(
      "Good afternoon",
    );
    expect(greetingTimeText(hi, new Date(2026, 9, 9, 12, 0))).toBe("शुभ दोपहर");
  });

  it("picks the evening copy from 5pm in both locales", () => {
    expect(greetingTimeText(en, new Date(2026, 9, 9, 17, 0))).toBe(
      "Good evening",
    );
    expect(greetingTimeText(hi, new Date(2026, 9, 9, 17, 0))).toBe(
      "शुभ संध्या",
    );
  });
});

describe("greetingFirstName (#678)", () => {
  it("returns null for a missing or blank name", () => {
    expect(greetingFirstName(null)).toBeNull();
    expect(greetingFirstName(undefined)).toBeNull();
    expect(greetingFirstName("   ")).toBeNull();
  });

  it("takes the first spoken token of a plain name", () => {
    expect(greetingFirstName("Anil Kumar")).toBe("Anil");
    expect(greetingFirstName("Meera")).toBe("Meera");
  });

  it("strips a leading English honorific", () => {
    expect(greetingFirstName("Dr. Anil Kumar")).toBe("Anil");
    expect(greetingFirstName("Dr Anil Kumar")).toBe("Anil");
    expect(greetingFirstName("Prof. Meera Iyer")).toBe("Meera");
  });

  it("strips a leading Hindi honorific", () => {
    expect(greetingFirstName("डॉ. अनिल कुमार")).toBe("अनिल");
    expect(greetingFirstName("श्री रमेश")).toBe("रमेश");
  });

  it("never eats a name that merely begins with an honorific's letters", () => {
    expect(greetingFirstName("Drishya Rao")).toBe("Drishya");
    expect(greetingFirstName("Modern Care Clinic")).toBe("Modern");
  });

  it("returns null rather than greeting a doctor by their bare title", () => {
    expect(greetingFirstName("Dr.")).toBeNull();
    expect(greetingFirstName("डॉ.")).toBeNull();
  });
});

describe("formatGreetingDate (#678)", () => {
  const now = new Date(2026, 9, 9, 12, 0);

  it("formats the date line in the locale's own long form", () => {
    expect(formatGreetingDate(now, "en")).toBe(
      new Intl.DateTimeFormat("en-IN", {
        day: "numeric",
        month: "long",
        year: "numeric",
      }).format(now),
    );
    expect(formatGreetingDate(now, "hi")).toBe(
      new Intl.DateTimeFormat("hi-IN", {
        day: "numeric",
        month: "long",
        year: "numeric",
      }).format(now),
    );
  });
});
