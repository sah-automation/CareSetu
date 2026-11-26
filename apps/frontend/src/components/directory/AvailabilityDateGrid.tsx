"use client";

import { useCallback, useState } from "react";
import { ChevronLeft, ChevronRight, Home, Truck, Video } from "lucide-react";

import {
  getCardAvailability,
  type DayCell,
} from "@/lib/directory/mockAvailability";
import type { ProviderType } from "@/lib/directory/links";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";

const MODE_ICON: Record<ProviderType, React.ElementType> = {
  doctor: Video,
  lab: Home,
  chemist: Truck,
};

const MODE_LABEL_KEY: Record<ProviderType, "appts" | "slots" | "windows"> = {
  doctor: "appts",
  lab: "slots",
  chemist: "windows",
};

/** Shared day-cell chrome (prototype `.date-cell`): 64px desktop / 56px
 *  ≤720px, radius var(--radius), .5rem .375rem padding, .125rem gap. */
const CELL_CLASS =
  "flex flex-col items-center justify-center gap-0.5 min-h-16 rounded py-2 px-1.5 text-center text-[0.75rem] font-medium transition-all cursor-pointer [@media_(max-width:720px)]:gap-1 [@media_(max-width:720px)]:min-h-[56px] [@media_(max-width:720px)]:py-1.5 [@media_(max-width:720px)]:px-1 [@media_(max-width:720px)]:text-[0.6875rem]";

interface DirectoryGridStrings {
  rangeLabel: (start: string, end: string) => string;
  prevWeek: string;
  nextWeek: string;
  more: string;
  viewAll: string;
  appts: (n: number) => string;
  slots: (n: number) => string;
  windows: (n: number) => string;
}

function startOfDay(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate());
}

function addDays(date: Date, days: number): Date {
  const result = new Date(date);
  result.setDate(result.getDate() + days);
  return result;
}

function monthDay(date: Date): string {
  return date.toLocaleString(undefined, { month: "short", day: "numeric" });
}

export function AvailabilityDateGrid({
  mode,
  partnerId,
}: {
  mode: ProviderType;
  partnerId: number;
}) {
  const { lang } = useLang();
  const t = STRINGS[lang].directory as unknown as DirectoryGridStrings;
  const today = startOfDay(new Date());
  const [weekStart, setWeekStart] = useState(startOfDay(new Date()));

  const cells: DayCell[] = getCardAvailability(
    partnerId,
    mode,
    weekStart,
    today,
  );

  const firstIso = cells[0]?.iso;
  const lastIso = cells[cells.length - 1]?.iso;
  const firstDate = firstIso ? new Date(`${firstIso}T00:00:00`) : today;
  const lastDate = lastIso ? new Date(`${lastIso}T00:00:00`) : today;

  const rangeLabel = t.rangeLabel(
    isSameDay(firstDate, today) ? "Today" : monthDay(firstDate),
    isSameDay(lastDate, today) ? "Today" : monthDay(lastDate),
  );

  const goPrev = useCallback(() => setWeekStart((d) => addDays(d, -7)), []);
  const goNext = useCallback(() => setWeekStart((d) => addDays(d, 7)), []);

  const canPrev = weekStart.getTime() > today.getTime();
  const Icon = MODE_ICON[mode];
  const labelFn = t[MODE_LABEL_KEY[mode] as keyof DirectoryGridStrings] as (
    n: number,
  ) => string;

  return (
    <div
      data-testid="availability-date-grid"
      className="flex flex-col gap-2 min-w-0"
    >
      <div
        data-testid="availability-header"
        className="flex items-center justify-between gap-2 border-b border-hairline-soft pb-1"
      >
        <span
          data-testid="availability-range"
          className="text-[0.8125rem] font-medium text-txt-sub whitespace-nowrap"
        >
          {rangeLabel}
        </span>
        <div data-testid="availability-nav" className="flex gap-1">
          <button
            type="button"
            data-testid="availability-prev"
            aria-label={t.prevWeek}
            disabled={!canPrev}
            onClick={goPrev}
            className="shrink-0 h-7 w-7 rounded-full border border-hairline bg-surface text-txt-sub flex items-center justify-center transition-colors hover:border-accent-border hover:bg-accent-soft hover:text-accent-strong disabled:opacity-40 disabled:pointer-events-none"
          >
            <ChevronLeft className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
          <button
            type="button"
            data-testid="availability-next"
            aria-label={t.nextWeek}
            onClick={goNext}
            className="shrink-0 h-7 w-7 rounded-full border border-hairline bg-surface text-txt-sub flex items-center justify-center transition-colors hover:border-accent-border hover:bg-accent-soft hover:text-accent-strong"
          >
            <ChevronRight className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
        </div>
      </div>
      <div
        data-testid="availability-grid"
        className="grid grid-cols-7 gap-1.5 min-w-0 [@media_(max-width:720px)]:gap-1 [@media_(max-width:480px)]:grid-cols-[repeat(7,48px)] [@media_(max-width:480px)]:overflow-x-auto [@media_(max-width:480px)]:pb-1"
      >
        {cells.map((cell) => {
          const isFirst = cell === cells[0];
          const weekdayLabel = isFirst && cell.isToday ? "Today" : cell.weekday;
          const isAvailable = cell.available;
          return (
            <button
              key={cell.iso}
              type="button"
              data-testid="date-cell"
              aria-label={
                isAvailable
                  ? `${weekdayLabel} ${cell.day}, ${labelFn(cell.count)}`
                  : `${weekdayLabel} ${cell.day}, unavailable`
              }
              disabled={!isAvailable}
              className={`${CELL_CLASS} ${
                isAvailable
                  ? "border border-accent-border bg-accent-soft text-accent-strong hover:bg-accent hover:text-on-accent"
                  : "border border-transparent bg-hairline-soft text-txt-muted"
              }`}
            >
              <span className="weekday text-[0.625rem] uppercase tracking-[0.04em] opacity-70">
                {weekdayLabel}
              </span>
              <span className="day text-[1rem] font-semibold leading-[1.2]">
                {cell.day}
              </span>
              {isAvailable && cell.count > 0 && (
                <span className="appt-info flex items-center justify-center gap-0.5 mt-0.5 text-[0.625rem] opacity-80">
                  {cell.icon && (
                    <Icon
                      className="h-2.5 w-2.5 shrink-0 [@media_(max-width:720px)]:h-[9px] [@media_(max-width:720px)]:w-[9px]"
                      aria-hidden="true"
                    />
                  )}
                  {labelFn(cell.count)}
                </span>
              )}
            </button>
          );
        })}
        <button
          type="button"
          data-testid="date-cell-more"
          className={`${CELL_CLASS} border border-dashed border-accent-border bg-transparent text-accent-strong hover:border-solid hover:bg-accent-soft`}
        >
          <span className="weekday text-[0.625rem] uppercase tracking-[0.04em] opacity-70">
            {t.more}
          </span>
          <span className="day text-[0.75rem] font-semibold leading-[1.2]">
            {t.viewAll}
          </span>
        </button>
      </div>
    </div>
  );
}

function isSameDay(a: Date, b: Date): boolean {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  );
}
