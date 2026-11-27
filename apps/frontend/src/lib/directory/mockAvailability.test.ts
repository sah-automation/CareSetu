// PHASE-6 card redesign (#965): deterministic availability stand-ins.
// Pins the prototype's dayInfo rules per mode, the past/today/closed/open
// cell states, and the determinism contract week/month navigation relies on:
// same inputs -> identical output, shifted windows -> different but stable
// data, overlapping dates -> identical cells across windows.

import { describe, expect, it } from "vitest";

import { getCardAvailability, getMonthAvailability } from "./mockAvailability";

// Pinned clock: Tuesday, 24 November 2026 (local).
const NOW = new Date(2026, 10, 24);

describe("getCardAvailability", () => {
  it("returns 14 consecutive days starting at weekStart", () => {
    const cells = getCardAvailability(1, "doctor", new Date(2026, 10, 21), NOW);
    expect(cells).toHaveLength(14);
    expect(cells[0].iso).toBe("2026-11-21");
    expect(cells[13].iso).toBe("2026-12-04");
    for (let index = 1; index < cells.length; index += 1) {
      const previous = new Date(cells[index - 1].iso);
      const current = new Date(cells[index].iso);
      expect(current.getTime() - previous.getTime()).toBe(86_400_000);
    }
  });

  it("is pure: same inputs produce identical cells", () => {
    const weekStart = new Date(2026, 10, 21);
    expect(getCardAvailability(5, "lab", weekStart, NOW)).toEqual(
      getCardAvailability(5, "lab", weekStart, NOW),
    );
  });

  it("ignores the time component of weekStart", () => {
    expect(
      getCardAvailability(1, "doctor", new Date(2026, 10, 21, 15, 45), NOW),
    ).toEqual(getCardAvailability(1, "doctor", new Date(2026, 10, 21), NOW));
  });

  it("marks past days unavailable and flags exactly one today", () => {
    const cells = getCardAvailability(1, "doctor", new Date(2026, 10, 21), NOW);
    const byIso = new Map(cells.map((cell) => [cell.iso, cell]));

    for (const iso of ["2026-11-21", "2026-11-22", "2026-11-23"]) {
      const cell = byIso.get(iso);
      expect(cell?.available).toBe(false);
      expect(cell?.count).toBe(0);
      expect(cell?.icon).toBeNull();
    }

    expect(cells.filter((cell) => cell.isToday)).toHaveLength(1);
    expect(byIso.get("2026-11-24")?.isToday).toBe(true);
  });

  it("never opens a doctor on Sunday and keeps counts in the doctor range", () => {
    const cells = getCardAvailability(3, "doctor", new Date(2026, 10, 21), NOW);
    for (const cell of cells) {
      if (cell.weekday === "Sun") {
        expect(cell.available).toBe(false);
        expect(cell.count).toBe(0);
      }
      if (cell.available) {
        expect(cell.count).toBeGreaterThanOrEqual(1);
        expect(cell.count).toBeLessThanOrEqual(8);
        expect(["video", null]).toContain(cell.icon);
      } else {
        expect(cell.icon).toBeNull();
      }
    }
    // The window covers two Sundays, so at least the past/today/closed mix
    // is non-trivial.
    expect(cells.some((cell) => cell.available)).toBe(true);
  });

  it("keeps lab counts in the lab range with tray icons only when open", () => {
    const cells = getCardAvailability(3, "lab", new Date(2026, 10, 21), NOW);
    for (const cell of cells) {
      if (cell.available) {
        expect(cell.count).toBeGreaterThanOrEqual(1);
        expect(cell.count).toBeLessThanOrEqual(6);
        expect(["tray", null]).toContain(cell.icon);
      } else {
        expect(cell.icon).toBeNull();
      }
    }
  });

  it("regenerates deterministically when the window shifts", () => {
    const first = getCardAvailability(
      9,
      "chemist",
      new Date(2026, 10, 21),
      NOW,
    );
    const second = getCardAvailability(
      9,
      "chemist",
      new Date(2026, 10, 28),
      NOW,
    );

    // Overlapping dates (Nov 28 - Dec 4) are cells 7..13 of the first window
    // and 0..6 of the shifted one - identical by construction.
    expect(second.slice(0, 7)).toEqual(first.slice(7));

    // The windows themselves are different data (different date ranges).
    expect(second).not.toEqual(first);
  });

  it("gives different providers different grids for the same window", () => {
    const weekStart = new Date(2026, 10, 21);
    const a = getCardAvailability(1, "doctor", weekStart, NOW);
    const b = getCardAvailability(2, "doctor", weekStart, NOW);
    expect(a).not.toEqual(b);
  });
});

describe("getMonthAvailability", () => {
  const NOVEMBER_2026 = { year: 2026, month: 10 };

  it("lays out whole weeks covering the month with padding cells", () => {
    const cells = getMonthAvailability(
      1,
      "doctor",
      NOVEMBER_2026.year,
      NOVEMBER_2026.month,
      null,
      NOW,
    );
    expect(cells).toHaveLength(35); // 30 days starting Sunday -> 5 weeks
    expect(cells[0].iso).toBe("2026-11-01");
    expect(cells[0].inMonth).toBe(true);
    expect(cells[29].iso).toBe("2026-11-30");
    expect(cells[29].inMonth).toBe(true);
    expect(cells.slice(30).every((cell) => !cell.inMonth)).toBe(true);
    expect(cells.slice(30).map((cell) => cell.iso)).toEqual([
      "2026-12-01",
      "2026-12-02",
      "2026-12-03",
      "2026-12-04",
      "2026-12-05",
    ]);
  });

  it("is pure: same inputs produce identical cells", () => {
    expect(getMonthAvailability(4, "lab", 2026, 10, null, NOW)).toEqual(
      getMonthAvailability(4, "lab", 2026, 10, null, NOW),
    );
  });

  it("marks past days past, flags exactly today, and never mixes states", () => {
    const cells = getMonthAvailability(
      1,
      "doctor",
      NOVEMBER_2026.year,
      NOVEMBER_2026.month,
      null,
      NOW,
    );
    const byIso = new Map(cells.map((cell) => [cell.iso, cell]));

    expect(byIso.get("2026-11-23")?.state).toBe("past");
    expect(byIso.get("2026-11-23")?.count).toBe(0);
    expect(byIso.get("2026-11-24")?.isToday).toBe(true);
    expect(cells.filter((cell) => cell.isToday)).toHaveLength(1);

    const future = byIso.get("2026-11-25");
    expect(future?.state === "open" || future?.state === "closed").toBe(true);
    if (future?.state === "open") {
      expect(future.count).toBeGreaterThanOrEqual(1);
      expect(future.count).toBeLessThanOrEqual(8);
    } else {
      expect(future?.count).toBe(0);
    }
  });

  it("closes every doctor Sunday (prototype rule)", () => {
    const cells = getMonthAvailability(
      1,
      "doctor",
      NOVEMBER_2026.year,
      NOVEMBER_2026.month,
      null,
      NOW,
    );
    const sundays = cells.filter(
      (cell) => cell.inMonth && cell.weekday === "Sun" && cell.state !== "past",
    );
    expect(sundays.length).toBeGreaterThanOrEqual(1);
    for (const cell of sundays) {
      expect(cell.state).toBe("closed");
      expect(cell.count).toBe(0);
    }
  });

  it("marks the selected date and only that date", () => {
    const cells = getMonthAvailability(
      1,
      "doctor",
      NOVEMBER_2026.year,
      NOVEMBER_2026.month,
      "2026-11-24",
      NOW,
    );
    const selected = cells.filter((cell) => cell.isSelected);
    expect(selected).toHaveLength(1);
    expect(selected[0].iso).toBe("2026-11-24");
  });

  it("regenerates deterministically when the month shifts", () => {
    const november = getMonthAvailability(7, "chemist", 2026, 10, null, NOW);
    const december = getMonthAvailability(7, "chemist", 2026, 11, null, NOW);

    // November 30 appears as a December padding cell - the shared date must
    // hash to the same state and count in both grids.
    const nov30InNovember = november.find((cell) => cell.iso === "2026-11-30");
    const nov30InDecember = december.find((cell) => cell.iso === "2026-11-30");
    expect(nov30InNovember).toBeDefined();
    expect(nov30InDecember).toBeDefined();
    expect(nov30InDecember?.state).toBe(nov30InNovember?.state);
    expect(nov30InDecember?.count).toBe(nov30InNovember?.count);

    expect(december).not.toEqual(november);
  });

  it("keeps lab open counts in the lab range", () => {
    const cells = getMonthAvailability(
      2,
      "lab",
      NOVEMBER_2026.year,
      NOVEMBER_2026.month,
      null,
      NOW,
    );
    for (const cell of cells) {
      if (cell.state === "open") {
        expect(cell.count).toBeGreaterThanOrEqual(1);
        expect(cell.count).toBeLessThanOrEqual(6);
      } else {
        expect(cell.count).toBe(0);
      }
    }
    expect(cells.some((cell) => cell.state === "open")).toBe(true);
  });
});
