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
      className="flex flex-col gap-0.5 min-w-0"
    >
      <div
        data-testid="availability-header"
        className="flex items-center justify-between gap-0.5 border-b border-hairline-soft pb-0.5"
      >
        <span
          data-testid="availability-range"
          className="text-[0.8125rem] font-medium text-txt-sub whitespace-nowrap"
        >
          {rangeLabel}
        </span>
        <div data-testid="availability-nav" className="flex gap-0.25">
          <button
            type="button"
            data-testid="availability-prev"
            aria-label={t.prevWeek}
            disabled={!canPrev}
            onClick={goPrev}
            className="shrink-0 h-7 w-7 rounded-full border border-hairline bg-surface text-txt-sub flex items-center justify-center transition-colors hover:bg-accent-soft hover:text-accent-strong disabled:opacity-40 disabled:pointer-events-none"
          >
            <ChevronLeft className="h-4 w-4" aria-hidden="true" />
          </button>
          <button
            type="button"
            data-testid="availability-next"
            aria-label={t.nextWeek}
            onClick={goNext}
            className="shrink-0 h-7 w-7 rounded-full border border-hairline bg-surface text-txt-sub flex items-center justify-center transition-colors hover:bg-accent-soft hover:text-accent-strong"
          >
            <ChevronRight className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>
      </div>
      <div
        data-testid="availability-grid"
        className="grid grid-cols-7 gap-0.375 [&_button]:min-h-[56px] [&_button]:rounded-lg [&_button]:flex [&_button]:flex-col [&_button]:items-center [&_button]:justify-center [&_button]:gap-0.125 [&_button]:p-0.5 [&_button]:text-center [&_button]:text-[0.75rem] [&_button]:font-medium [&_button]:transition-all [&_button]:hover:border [&_button]:cursor-pointer"
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
              className={
                isAvailable
                  ? "border border-accent-border bg-accent-soft text-accent-strong"
                  : "border border-transparent bg-hairline-soft text-txt-muted"
              }
            >
              <span className="weekday text-[0.625rem] uppercase tracking-[0.04em] opacity-70">
                {weekdayLabel}
              </span>
              <span className="day text-[1rem] leading-1.2">{cell.day}</span>
              {isAvailable && cell.count > 0 && (
                <span className="appt-info flex items-center justify-center gap-0.125 mt-0.125 text-[0.625rem] opacity-80">
                  {cell.icon && (
                    <Icon className="h-3 w-3 shrink-0" aria-hidden="true" />
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
          className="border border-dashed border-accent-border bg-transparent text-accent-strong hover:bg-accent-soft"
        >
          <span className="weekday text-[0.625rem] uppercase tracking-[0.04em] opacity-70">
            {t.more}
          </span>
          <span className="day text-[0.75rem] leading-1.2">{t.viewAll}</span>
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
