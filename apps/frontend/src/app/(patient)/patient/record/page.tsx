"use client";

// PHASE-3 T7 (#216): My Record (blueprint §5.5, binding prototype
// prototype/phase-3/record.html) - one reverse-chronological timeline of
// everything (consultations, prescriptions, lab results, metrics), filterable
// by type. The filter bar carries the ratified responsive outcome (PLAN.md):
// desktop/tablet a wrapped pill row; below 720px a single-line row where Lab
// results + Metrics collapse into the More dropdown whose trigger renames
// itself to the active filter; at 374px and under the row scrolls. Access-
// audit and health-tracking stay §2.7 Soon placeholders (Phases 4/12).
// Timeline data comes from the real GET /v1/records owner read (T2 #211);
// entry cards render only what the payload actually documents.

import { useCallback, useEffect, useMemo, useState } from "react";
import { ChevronDown } from "lucide-react";

import { PageHeader } from "@/components/layout/PageHeader";
import { EmptyState } from "@/components/layout/EmptyState";
import { ErrorBanner } from "@/components/layout/ErrorBanner";
import { SoonBadge } from "@/components/dashboard/NavItemLink";
import { ApiError } from "@/lib/api-errors";
import { fetchAccessHistory, type AccessHistoryEntry } from "@/lib/audit/api";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import { cn } from "@/lib/utils";
import {
  fetchOwnRecord,
  RecordApiError,
  type RecordEntryView,
  type RecordTimeline,
} from "@/lib/record/api";
import {
  MORE_OVERFLOW_FILTERS,
  RECORD_FILTERS,
  applyRecordFilter,
  describeEntry,
  formatOccurredAt,
  sortTimelineDesc,
  type BadgeTone,
  type RecordFilter,
} from "@/lib/record/timelineView";

const CHIP_BASE =
  "inline-flex items-center rounded-full border px-3 py-1.5 text-sm font-medium whitespace-nowrap leading-[1.4] transition-colors max-[719px]:justify-center max-[719px]:px-2 max-[359px]:px-1.5 max-[359px]:text-[0.8125rem]";
const CHIP_ACTIVE = "border-accent bg-accent text-on-accent";
const CHIP_IDLE =
  "border-hairline bg-surface text-txt-sub shadow-sm hover:border-accent-border hover:bg-accent-soft hover:text-accent-strong";

const BADGE_TONE: Record<BadgeTone, string> = {
  success: "bg-success-soft text-success-text",
  accent: "bg-accent-soft text-accent-strong",
  warm: "bg-warm-soft text-txt-sub",
  muted: "bg-hairline-soft text-txt-muted",
};

// Filter values are API snake_case; dictionary filter keys are camelCase.
const FILTER_LABEL_KEY = {
  all: "all",
  consultation: "consultation",
  prescription: "prescription",
  lab_report: "labReport",
  metric: "metric",
} as const;

type LoadStatus = "loading" | "ready" | "error";

export default function RecordPage() {
  const { lang } = useLang();
  const t = STRINGS[lang].record;

  const [timeline, setTimeline] = useState<RecordTimeline | null>(null);
  const [status, setStatus] = useState<LoadStatus>("loading");
  const [filter, setFilter] = useState<RecordFilter>("all");
  // Kept from the failed read for the banner's support-correlation line
  // (error-handling-observability §3); ErrorBanner generates a local one
  // when the API could not be reached at all.
  const [errorTraceId, setErrorTraceId] = useState<string | undefined>(
    undefined,
  );
  // Dismissal is separate from load state: closing the banner must never
  // silently re-fire the failing request (blueprint §9.1).
  const [bannerOpen, setBannerOpen] = useState(false);

  // One load path for mount and Retry alike (blueprint §9.1 banner pattern).
  const load = useCallback(() => {
    setStatus("loading");
    fetchOwnRecord()
      .then((data) => {
        setTimeline(data);
        setStatus("ready");
        setBannerOpen(false);
      })
      .catch((error: unknown) => {
        setErrorTraceId(
          error instanceof RecordApiError ? error.traceId : undefined,
        );
        setStatus("error");
        setBannerOpen(true);
      });
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // Access history is a secondary section that needs the record's patient id,
  // so it fetches only once the timeline has resolved (own uses record.patient_id).
  const [accessHistory, setAccessHistory] = useState<
    AccessHistoryEntry[] | null
  >(null);
  const [accessStatus, setAccessStatus] = useState<LoadStatus>("loading");
  const [accessTraceId, setAccessTraceId] = useState<string | undefined>(
    undefined,
  );
  const [accessBannerOpen, setAccessBannerOpen] = useState(false);

  const loadAccessHistory = useCallback((patientId: number) => {
    setAccessStatus("loading");
    fetchAccessHistory(patientId)
      .then((data) => {
        // Newest-first by accessed_at for a stable reading order.
        const sorted = [...data.entries].sort(
          (a, b) =>
            new Date(b.accessed_at).getTime() -
            new Date(a.accessed_at).getTime(),
        );
        setAccessHistory(sorted);
        setAccessStatus("ready");
        setAccessBannerOpen(false);
      })
      .catch((error: unknown) => {
        setAccessTraceId(error instanceof ApiError ? error.traceId : undefined);
        setAccessStatus("error");
        setAccessBannerOpen(true);
      });
  }, []);

  useEffect(() => {
    if (status === "ready" && timeline?.patient_id) {
      loadAccessHistory(timeline.patient_id);
    }
  }, [status, timeline, loadAccessHistory]);

  const visibleEntries: RecordEntryView[] = useMemo(() => {
    if (!timeline) return [];
    return applyRecordFilter(sortTimelineDesc(timeline.entries), filter);
  }, [timeline, filter]);

  const moreActive = filter === "lab_report" || filter === "metric";
  const moreLabel = moreActive
    ? t.filter[FILTER_LABEL_KEY[filter]]
    : t.filter.more;

  return (
    <>
      <PageHeader title={t.title} description={t.description} />

      {status === "error" && bannerOpen && (
        <ErrorBanner
          message={t.loadError}
          traceId={errorTraceId}
          onRetry={load}
          onDismiss={() => setBannerOpen(false)}
        />
      )}

      <div
        role="group"
        aria-label={t.filterGroupLabel}
        data-testid="record-filters"
        className="mb-4 flex flex-wrap items-center gap-2 min-[721px]:mb-8 max-[719px]:flex-nowrap max-[374px]:overflow-x-auto max-[374px]:[scrollbar-width:none] max-[374px]:[&::-webkit-scrollbar]:hidden"
      >
        {RECORD_FILTERS.map((key) => {
          const overflow = MORE_OVERFLOW_FILTERS.includes(key);
          return (
            <button
              key={key}
              type="button"
              onClick={() => setFilter(key)}
              aria-pressed={filter === key}
              data-testid={`filter-chip-${key}`}
              className={cn(
                CHIP_BASE,
                filter === key ? CHIP_ACTIVE : CHIP_IDLE,
                overflow && "max-[719px]:hidden",
                !overflow && "max-[719px]:flex-1",
              )}
            >
              {t.filter[FILTER_LABEL_KEY[key]]}
            </button>
          );
        })}
        {/* Mobile-only More dropdown (<720px); renames to the active filter */}
        <span
          data-testid="filter-more-wrap"
          className="relative hidden min-w-0 max-[719px]:block max-[719px]:flex-1"
        >
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                aria-label={`${t.moreMenuLabel}: ${moreLabel}`}
                data-testid="filter-more-btn"
                className={cn(
                  CHIP_BASE,
                  "w-full",
                  moreActive ? CHIP_ACTIVE : CHIP_IDLE,
                )}
              >
                <span data-testid="filter-more-label">{moreLabel}</span>
                <ChevronDown size={14} aria-hidden="true" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="min-w-44">
              <DropdownMenuRadioGroup
                value={filter}
                onValueChange={(value) => setFilter(value as RecordFilter)}
              >
                {MORE_OVERFLOW_FILTERS.map((key) => (
                  <DropdownMenuRadioItem key={key} value={key}>
                    {t.filter[FILTER_LABEL_KEY[key]]}
                  </DropdownMenuRadioItem>
                ))}
              </DropdownMenuRadioGroup>
            </DropdownMenuContent>
          </DropdownMenu>
        </span>
      </div>

      {status === "loading" ? (
        <ul className="space-y-2" data-testid="record-loading">
          {[0, 1, 2].map((row) => (
            <li
              key={row}
              className="h-16 animate-pulse rounded-lg border border-hairline bg-hairline-soft/60"
            />
          ))}
        </ul>
      ) : status === "error" ? null : visibleEntries.length === 0 ? (
        // A failed read never renders as a calm empty state - the banner
        // above stays the honest surface until Retry succeeds.
        <EmptyState title={t.empty.title} body={t.empty.body} />
      ) : (
        <ul className="space-y-2" data-testid="record-timeline">
          {visibleEntries.map((entry) => {
            const card = describeEntry(entry, t, lang);
            return (
              <li key={entry.entry_id} data-testid={`entry-${entry.entry_id}`}>
                <div className="rounded-lg border border-hairline bg-surface p-4 shadow-card">
                  <div className="flex items-start gap-2">
                    <span aria-hidden="true">{card.icon}</span>
                    <strong className="min-w-0 flex-1 text-base">
                      {card.title}
                    </strong>
                    {card.badge && (
                      <span
                        className={cn(
                          "ml-auto shrink-0 rounded-full px-2 py-0.5 text-xs font-medium",
                          BADGE_TONE[card.badge.tone],
                        )}
                      >
                        {card.badge.label}
                      </span>
                    )}
                  </div>
                  {card.subtitle && (
                    <p className="mt-1 text-sm text-txt-muted">
                      {card.subtitle}
                    </p>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {/* Access history (Phase 4, #283): rendered only once the timeline is
          ready because it needs the record's patient id. Its own loading,
          error, empty and data states follow the record page's patterns. */}
      {status === "ready" && (
        <section className="mt-6" data-testid="access-history">
          <h2 className="mb-3 text-lg font-semibold text-txt">
            {t.accessHistory.heading}
          </h2>
          {accessBannerOpen && (
            <ErrorBanner
              message={t.accessHistory.loadError}
              traceId={accessTraceId}
              onRetry={() => loadAccessHistory(timeline!.patient_id)}
              onDismiss={() => setAccessBannerOpen(false)}
            />
          )}
          {accessStatus === "loading" ? (
            <ul className="space-y-2" data-testid="access-loading">
              {[0, 1, 2].map((row) => (
                <li
                  key={row}
                  className="h-16 animate-pulse rounded-lg border border-hairline bg-hairline-soft/60"
                />
              ))}
            </ul>
          ) : accessStatus === "error" ||
            accessHistory === null ? null : accessHistory.length === 0 ? (
            <EmptyState
              title={t.accessHistory.emptyTitle}
              body={t.accessHistory.emptyBody}
            />
          ) : (
            <ul className="space-y-2" data-testid="access-history-list">
              {accessHistory.map((entry, index) => {
                const identity = entry.actor_type || `ID ${entry.actor_id}`;
                const scope = entry.scope
                  ? `, ${t.accessHistory.scopePrefix}${entry.scope}`
                  : "";
                return (
                  <li
                    key={`${entry.actor_id}-${entry.accessed_at}-${index}`}
                    data-testid={`access-entry-${index}`}
                  >
                    <div className="rounded-lg border border-hairline bg-surface p-4 shadow-card">
                      <div className="flex items-start gap-2">
                        <strong className="min-w-0 flex-1 text-base">
                          {identity}
                        </strong>
                        {entry.denied && (
                          <span className="ml-auto shrink-0 rounded-full px-2 py-0.5 text-xs font-medium bg-danger-soft text-danger">
                            {t.accessHistory.deniedLabel}
                          </span>
                        )}
                      </div>
                      <p className="mt-1 text-sm text-txt-muted">
                        {formatOccurredAt(entry.accessed_at, lang)}
                        {scope}
                      </p>
                      {entry.denied && entry.denial_reason ? (
                        <p className="mt-1 text-xs text-txt-muted">
                          {t.accessHistory.deniedReasonPrefix}
                          {entry.denial_reason}
                        </p>
                      ) : null}
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </section>
      )}

      {/* Forward-scope placeholder per §2.7 Soon convention (Phase 12) */}
      <section
        aria-disabled="true"
        data-testid="placeholder-health"
        className="mt-2 space-y-1 rounded-lg border border-dashed border-hairline bg-hairline-soft/40 p-4 opacity-70"
      >
        <span className="flex items-center gap-2">
          <strong>{t.placeholder.healthTitle}</strong>
          <SoonBadge />
        </span>
        <p className="text-sm text-txt-muted">{t.placeholder.healthBody}</p>
      </section>
    </>
  );
}
