// FEAT-008 (#676 / #652): the shared relative "updated" line. One helper for the cases
// index and the dashboard's open-cases section, so the two surfaces date the
// same case the same way. Pins every granularity bucket, the sub-minute case,
// an unparseable timestamp (drops the line rather than lying), and Hindi.

import { describe, expect, it } from "vitest";

import { STRINGS } from "@/lib/i18n/dictionaries";

import { caseUpdatedText, minutesSince } from "./caseTime";

const t = STRINGS.en.doctorConsole;
const hiT = STRINGS.hi.doctorConsole;

const NOW = Date.parse("2026-09-12T12:00:00Z");
const at = (minutesAgo: number) =>
  new Date(NOW - minutesAgo * 60_000).toISOString();

describe("minutesSince", () => {
  it("returns whole minutes since the timestamp", () => {
    expect(minutesSince(at(90), NOW)).toBe(90);
  });

  it("clamps a future timestamp to zero rather than going negative", () => {
    expect(minutesSince(at(-30), NOW)).toBe(0);
  });

  it("returns null for an unparseable timestamp", () => {
    expect(minutesSince("not-a-date", NOW)).toBeNull();
  });
});

describe("caseUpdatedText", () => {
  it("says just-now for less than a minute", () => {
    expect(caseUpdatedText(at(0), t, NOW)).toBe(t.caseUpdatedJustNow);
  });

  it("counts minutes below an hour", () => {
    expect(caseUpdatedText(at(5), t, NOW)).toBe(
      t.caseUpdatedAgo(t.timeAgoMinutes(5)),
    );
  });

  it("counts hours below a day", () => {
    expect(caseUpdatedText(at(180), t, NOW)).toBe(
      t.caseUpdatedAgo(t.timeAgoHours(3)),
    );
  });

  it("counts days beyond a day", () => {
    expect(caseUpdatedText(at(60 * 24 * 2), t, NOW)).toBe(
      t.caseUpdatedAgo(t.timeAgoDays(2)),
    );
  });

  it("drops the line on an unparseable timestamp", () => {
    expect(caseUpdatedText("not-a-date", t, NOW)).toBeNull();
  });

  it("renders the units in Hindi", () => {
    expect(caseUpdatedText(at(180), hiT, NOW)).toBe(
      hiT.caseUpdatedAgo(hiT.timeAgoHours(3)),
    );
  });
});
