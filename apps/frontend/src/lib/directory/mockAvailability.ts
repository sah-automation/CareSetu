// PHASE-6 card redesign (#965): deterministic hash-based availability
// stand-ins - single swap point until the availability backends land.
//
// Ported from the prototype's `dayInfo` (prototype/phase-6/doctor-profile.html
// and partner-profile.html): same avalanche hash, same per-mode rules
// (doctors: no Sunday clinic, 1-in-9 random closure; labs/chemists: most
// Sundays closed, 1-in-13 weekday closure). The hash is seeded with
// `partner_id`, so each provider keeps a stable grid while week/month
// navigation simply calls these functions with a shifted window and gets
// fresh-but-deterministic cells.
//
// Every export is pure and synchronous. The clock is read only through the
// optional `now` argument (defaults to the current date), so tests pin time
// explicitly and there are no side effects.
//
// TODO(BACKEND): real availability APIs for the 14-day card grid and the
// profile month grid; consumers swap their import and nothing else changes.

import type { ProviderType } from "./links";

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"] as const;

/** One mode icon shown on an available day cell (consumer maps to SVG). */
export type DayCellIcon = "video" | "tray" | "delivery";

/** One cell of the 14-day card grid: date parts plus count + icon. */
export interface DayCell {
  /** Local calendar date, "YYYY-MM-DD". */
  iso: string;
  /** Day of month (1-31). */
  day: number;
  /** Short weekday label ("Sun".."Sat"); consumers relabel today's cell. */
  weekday: string;
  isToday: boolean;
  available: boolean;
  /** Slot/window count when available; 0 for closed and past days. */
  count: number;
  /** Mode icon when available and the day's hash bit says so; else null. */
  icon: DayCellIcon | null;
}

/** Month-grid cell state (prototype rules: past beats open/closed). */
export type MonthCellState = "past" | "open" | "closed";

/** One cell of the profile month grid. */
export interface MonthCell {
  /** Local calendar date, "YYYY-MM-DD". */
  iso: string;
  /** Day of month within its own month (1-31). */
  day: number;
  /** Short weekday label ("Sun".."Sat"). */
  weekday: string;
  /** False for the leading/trailing padding cells outside the month. */
  inMonth: boolean;
  state: MonthCellState;
  isToday: boolean;
  isSelected: boolean;
  /** Slot/window count when open; 0 for closed and past days. */
  count: number;
}

function pad2(value: number): string {
  return String(value).padStart(2, "0");
}

function toIso(year: number, month: number, day: number): string {
  return `${year}-${pad2(month + 1)}-${pad2(day)}`;
}

function startOfDay(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate());
}

/** Prototype `hash`: a 32-bit avalanche mix over partner_id + calendar date,
 * so the same provider/day always hashes the same and different days differ. */
function hashDay(partnerId: number, date: Date): number {
  let h =
    (Math.imul(partnerId, 31) +
      date.getFullYear() * 10000 +
      (date.getMonth() + 1) * 100 +
      date.getDate()) |
    0;
  h = Math.imul(h ^ (h >>> 15), 2246822519);
  h = Math.imul(h ^ (h >>> 13), 3266489917);
  return (h ^ (h >>> 16)) >>> 0;
}

interface DayInfo {
  state: "past" | "open" | "closed";
  count: number;
  hash: number;
}

/** Prototype `dayInfo` rules per mode. Doctors never open on Sunday and
 * close outright on 1-in-9 hashed weekdays; labs/chemists open most Sundays
 * (1-in-5, short counts) and close 1-in-13 hashed weekdays. Past days are
 * always unavailable. */
function dayInfo(
  mode: ProviderType,
  partnerId: number,
  date: Date,
  today: Date,
): DayInfo {
  if (date.getTime() < today.getTime()) {
    return { state: "past", count: 0, hash: 0 };
  }
  const hash = hashDay(partnerId, date);
  if (mode === "doctor") {
    if (date.getDay() === 0) return { state: "closed", count: 0, hash };
    if (hash % 9 === 0) return { state: "closed", count: 0, hash };
    return { state: "open", count: 1 + (hash % 8), hash };
  }
  // lab + chemist share the prototype partner-profile rules.
  if (date.getDay() === 0) {
    return hash % 5 === 0
      ? { state: "open", count: 1 + (hash % 3), hash }
      : { state: "closed", count: 0, hash };
  }
  if (hash % 13 === 0) return { state: "closed", count: 0, hash };
  return { state: "open", count: 1 + (hash % 6), hash };
}

function iconFor(mode: ProviderType, info: DayInfo): DayCellIcon | null {
  if (info.state !== "open") return null;
  // Half the open days carry the mode icon (prototype's per-day video/home/
  // delivery flags), picked from a different hash slice than the count.
  if (((info.hash >>> 11) & 1) === 0) return null;
  if (mode === "doctor") return "video";
  if (mode === "lab") return "tray";
  return "delivery";
}

/** 14 cells starting at `weekStart` (its time component is ignored), for the
 * card's date grid. Navigation shifts `weekStart`; the same date always
 * yields the same cell for a given provider. `now` pins "today" for tests. */
export function getCardAvailability(
  partnerId: number,
  mode: ProviderType,
  weekStart: Date,
  now: Date = new Date(),
): DayCell[] {
  const today = startOfDay(now);
  const base = startOfDay(weekStart);
  const cells: DayCell[] = [];
  for (let index = 0; index < 14; index += 1) {
    const date = new Date(
      base.getFullYear(),
      base.getMonth(),
      base.getDate() + index,
    );
    const info = dayInfo(mode, partnerId, date, today);
    cells.push({
      iso: toIso(date.getFullYear(), date.getMonth(), date.getDate()),
      day: date.getDate(),
      weekday: WEEKDAYS[date.getDay()],
      isToday: date.getTime() === today.getTime(),
      available: info.state === "open",
      count: info.count,
      icon: iconFor(mode, info),
    });
  }
  return cells;
}

/** Full month grid (leading/trailing cells included so the grid is always a
 * whole number of weeks). `month` is 0-based (JS Date convention, 0 =
 * January). `selectedIso` marks the selected day; `now` pins "today". */
export function getMonthAvailability(
  partnerId: number,
  mode: ProviderType,
  year: number,
  month: number,
  selectedIso: string | null = null,
  now: Date = new Date(),
): MonthCell[] {
  const today = startOfDay(now);
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const firstDow = new Date(year, month, 1).getDay();
  const totalCells = Math.ceil((firstDow + daysInMonth) / 7) * 7;

  const cells: MonthCell[] = [];
  for (let index = 0; index < totalCells; index += 1) {
    // Normalization pushes the leading/trailing padding into the adjacent
    // months, exactly like the prototype's renderMonth.
    const date = new Date(year, month, index - firstDow + 1);
    const info = dayInfo(mode, partnerId, date, today);
    const iso = toIso(date.getFullYear(), date.getMonth(), date.getDate());
    cells.push({
      iso,
      day: date.getDate(),
      weekday: WEEKDAYS[date.getDay()],
      inMonth: date.getMonth() === month,
      state: info.state,
      isToday: date.getTime() === today.getTime(),
      isSelected: selectedIso !== null && iso === selectedIso,
      count: info.count,
    });
  }
  return cells;
}
