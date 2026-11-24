"use client";

// PHASE-6 profile redesign (#968): the right rail's whole-month availability
// grid, ported from the finalized prototype (prototype/phase-6/doctor-profile
// .html and partner-profile.html, `.pp-month-*`). Weekday strip Sun-Sat, month
// nav (prev disabled on the current month), one cell per day with open/closed/
// past/today/selected states, a legend, and the selection callout.
//
// The cells come from `mockAvailability.getMonthAvailability` - the single swap
// point until the real availability backend lands, so week/month navigation just
// re-calls it with the shifted window and gets fresh-but-deterministic cells.
// The clock is read once per render (never stored in state), so a month boundary
// crossed while the card is open does not freeze the grid on yesterday.
//
// Per-type wording (consultation slots / home-collection windows / delivery
// windows) lives in the dictionary, keyed by the same `ProviderType` the cells
// are computed for, so a cell and its legend and its callout can never disagree
// about what an "open" day means for this provider.

import { useMemo, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";

import {
  getMonthAvailability,
  type MonthCell,
} from "@/lib/directory/mockAvailability";
import type { ProviderType } from "@/lib/directory/links";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"] as const;

function startOfDay(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate());
}

function isoOf(date: Date): string {
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}

const CELL_BASE =
  "flex min-h-[56px] flex-col items-center justify-center gap-0.5 rounded-lg border px-1 py-1.5 text-center text-[0.75rem] font-medium transition-colors";
const CELL_TODAY = "shadow-[inset_0_0_0_2px_var(--accent-strong)]";

function cellClass(cell: MonthCell, isSelected: boolean): string {
  if (isSelected) {
    return `${CELL_BASE} ${CELL_TODAY} border-accent bg-accent text-on-accent`;
  }
  if (cell.state === "open") {
    return `${CELL_BASE} border-accent-border bg-accent-soft text-accent-strong hover:bg-accent hover:text-on-accent`;
  }
  if (cell.state === "closed") {
    return `${CELL_BASE} border-transparent bg-hairline-soft text-txt-muted`;
  }
  return `${CELL_BASE} ${CELL_TODAY} border-transparent text-txt-muted opacity-50`;
}

export function ProfileMonthGrid({
  partnerId,
  mode,
  hours,
}: {
  partnerId: number;
  mode: ProviderType;
  /** The provider's own consulting hours prose, quoted in the callout when set. */
  hours: string | null;
}) {
  const { lang } = useLang();
  const t = STRINGS[lang].providerProfile.availability;

  const today = startOfDay(new Date());
  const [view, setView] = useState(() => ({
    year: today.getFullYear(),
    month: today.getMonth(),
  }));
  const [selectedIso, setSelectedIso] = useState(() => isoOf(today));

  const cells = useMemo(
    () =>
      getMonthAvailability(
        partnerId,
        mode,
        view.year,
        view.month,
        selectedIso,
        today,
      ),
    [partnerId, mode, view.year, view.month, selectedIso, today],
  );

  // The callout describes the SELECTED day, which may sit in a month the grid
  // has since navigated away from - so it is resolved from the selection's own
  // month rather than from the visible cells, the way the prototype's
  // `updateSelection` did.
  const selectedCell = useMemo(() => {
    const [year, month, day] = selectedIso.split("-").map(Number);
    const selectedDate = new Date(year, month - 1, day);
    return getMonthAvailability(
      partnerId,
      mode,
      selectedDate.getFullYear(),
      selectedDate.getMonth(),
      selectedIso,
      today,
    ).find((cell) => cell.iso === selectedIso);
  }, [partnerId, mode, selectedIso, today]);

  const monthTitle = new Date(view.year, view.month, 1).toLocaleDateString(
    lang === "hi" ? "hi-IN" : "en-IN",
    { month: "long", year: "numeric" },
  );
  const isCurrentMonth =
    view.year === today.getFullYear() && view.month === today.getMonth();

  const selectedLabel = selectedCell
    ? new Date(
        Number(selectedCell.iso.slice(0, 4)),
        Number(selectedCell.iso.slice(5, 7)) - 1,
        Number(selectedCell.iso.slice(8, 10)),
      ).toLocaleDateString(lang === "hi" ? "hi-IN" : "en-IN", {
        weekday: "long",
        month: "short",
        day: "numeric",
      })
    : "";

  const selectedNote = !selectedCell
    ? ""
    : selectedCell.state === "open"
      ? t.selectedOpen[mode](selectedLabel, selectedCell.count, hours)
      : selectedCell.state === "closed"
        ? t.selectedClosed[mode](selectedLabel)
        : t.selectedPast(selectedLabel);

  const stepMonth = (delta: number) =>
    setView((current) => {
      const next = new Date(current.year, current.month + delta, 1);
      return { year: next.getFullYear(), month: next.getMonth() };
    });

  return (
    <div data-testid="profile-month-grid">
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0">
          <h2 className="text-base font-semibold text-txt">{t.heading}</h2>
          <p className="mt-0.5 text-xs text-txt-muted">
            {t.sub(t.kinds[mode])}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <span
            data-testid="profile-month-title"
            className="text-sm font-semibold text-txt"
          >
            {monthTitle}
          </span>
          <div className="flex gap-1">
            <button
              type="button"
              data-testid="profile-month-prev"
              aria-label={t.prevMonth}
              disabled={isCurrentMonth}
              onClick={() => stepMonth(-1)}
              className="flex h-7 w-7 items-center justify-center rounded-full border border-hairline bg-surface text-txt-sub transition-colors hover:border-accent-border hover:bg-accent-soft hover:text-accent-strong disabled:opacity-40 disabled:pointer-events-none"
            >
              <ChevronLeft className="h-3.5 w-3.5" aria-hidden="true" />
            </button>
            <button
              type="button"
              data-testid="profile-month-next"
              aria-label={t.nextMonth}
              onClick={() => stepMonth(1)}
              className="flex h-7 w-7 items-center justify-center rounded-full border border-hairline bg-surface text-txt-sub transition-colors hover:border-accent-border hover:bg-accent-soft hover:text-accent-strong"
            >
              <ChevronRight className="h-3.5 w-3.5" aria-hidden="true" />
            </button>
          </div>
        </div>
      </div>

      <div
        className="mt-3 grid grid-cols-7 gap-1.5 pb-1"
        aria-hidden="true"
        data-testid="profile-month-weekdays"
      >
        {WEEKDAYS.map((weekday) => (
          <span
            key={weekday}
            className="text-center text-[0.625rem] font-semibold uppercase tracking-wide text-txt-muted"
          >
            {weekday}
          </span>
        ))}
      </div>

      <div
        data-testid="profile-month-cells"
        className="grid grid-cols-7 gap-1.5"
      >
        {cells.map((cell) => {
          if (!cell.inMonth) {
            return (
              <div
                key={cell.iso}
                aria-hidden="true"
                className="min-h-[56px] rounded-lg opacity-30"
              />
            );
          }
          const isSelected = cell.iso === selectedIso;
          const state = cell.state;
          const status =
            state === "open"
              ? t.cellOpen[mode](cell.count)
              : state === "closed"
                ? t.cellClosed[mode]
                : "";
          const aria = `${new Date(
            Number(cell.iso.slice(0, 4)),
            Number(cell.iso.slice(5, 7)) - 1,
            Number(cell.iso.slice(8, 10)),
          ).toLocaleDateString(lang === "hi" ? "hi-IN" : "en-IN", {
            weekday: "long",
            month: "short",
            day: "numeric",
          })}, ${
            state === "open"
              ? t.cellAriaOpen[mode](cell.count)
              : state === "closed"
                ? t.cellAriaClosed[mode]
                : t.cellAriaPast
          }`;

          const inner = (
            <>
              <span className="text-[0.9375rem] font-semibold leading-tight">
                {cell.day}
              </span>
              {status ? (
                <span className="text-[0.5625rem] leading-tight opacity-85">
                  {status}
                </span>
              ) : null}
            </>
          );

          if (state === "past") {
            return (
              <div
                key={cell.iso}
                data-testid="profile-month-cell"
                data-state="past"
                aria-label={aria}
                className={cellClass(cell, isSelected)}
              >
                {inner}
              </div>
            );
          }

          return (
            <button
              key={cell.iso}
              type="button"
              data-testid="profile-month-cell"
              data-state={state}
              aria-label={aria}
              onClick={() => setSelectedIso(cell.iso)}
              className={cellClass(cell, isSelected)}
            >
              {inner}
            </button>
          );
        })}
      </div>

      <div
        className="mt-3 flex flex-wrap gap-3 text-[0.6875rem] text-txt-muted"
        data-testid="profile-month-legend"
      >
        <span className="inline-flex items-center gap-1">
          <i className="inline-block h-2.5 w-2.5 rounded-[3px] border border-accent-border bg-accent-soft" />
          {t.legendOpen[mode]}
        </span>
        <span className="inline-flex items-center gap-1">
          <i className="inline-block h-2.5 w-2.5 rounded-[3px] bg-hairline-soft" />
          {t.legendClosed[mode]}
        </span>
        <span className="inline-flex items-center gap-1">
          <i
            className={`inline-block h-2.5 w-2.5 rounded-[3px] border border-transparent ${CELL_TODAY}`}
          />
          {t.legendToday}
        </span>
      </div>

      <div
        data-testid="profile-month-selected"
        aria-live="polite"
        className="mt-3 rounded-lg border border-accent-border bg-accent-soft px-3 py-2 text-xs text-txt-sub"
      >
        {selectedNote}
      </div>
    </div>
  );
}
