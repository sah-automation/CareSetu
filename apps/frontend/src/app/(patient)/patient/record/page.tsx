"use client";

// PROTO-3.1 (#511): My Record redesign (two-zone timeline). The flat card
// list becomes a "snapshot answers what you should know, timeline carries the
// story" page. Below lg (1024px) it stacks: a snapshot strip of count tiles
// that double as jump-filters, a sticky single-line filter bar, a reverse-
// chronological timeline grouped by local calendar day (Today / Yesterday /
// Month Year), then privacy cards below the feed. At lg the same columns sit
// beside a sticky 300px rail (at-a-glance summary, health snapshot, who-
// accessed accordion with the consent-log entry, consent-log link). The
// snapshot strip renders at every width - interactive tiles (jump-filters)
// on mobile, a static read-only copy on the desktop where the rail carries
// the same counts. Every count, micro-label and flag is derived from the
// record payload; a failed read never renders as a calm empty state. Zones
// duplicate DOM nodes toggled by Tailwind classes only - no JS breakpoint
// detection.

import { ChevronDown, ChevronRight } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { PageHeader } from "@/components/layout/PageHeader";
import { EmptyState } from "@/components/layout/EmptyState";
import { ErrorBanner } from "@/components/layout/ErrorBanner";
import { HealthSnapshotCard } from "@/components/patient/home/HealthSnapshotCard";
import { ApiError } from "@/lib/api-errors";
import { fetchAccessHistory, type AccessHistoryEntry } from "@/lib/audit/api";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { STRINGS, type Lang } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import { cn } from "@/lib/utils";
import {
  fetchOwnRecord,
  RecordApiError,
  type RecordEntryView,
  type RecordTimeline,
} from "@/lib/record/api";
import {
  BADGE_TONE,
  ENTRY_TONE,
  MORE_OVERFLOW_FILTERS,
  applyRecordFilter,
  countByType,
  describeEntry,
  entryFlagRows,
  flaggedValues,
  formatOccurredAt,
  groupTimeline,
  issuedPrescriptionCount,
  sortTimelineDesc,
  type LabFlagSummary,
  type RecordCounts,
  type RecordFilter,
} from "@/lib/record/timelineView";

type RecordStrings = (typeof STRINGS)["en"]["record"];

const CHIP_BASE =
  "inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-sm font-medium whitespace-nowrap leading-[1.4] transition-colors max-[720px]:justify-center max-[720px]:px-2";
const CHIP_ACTIVE = "border-accent bg-accent text-on-accent";
const CHIP_IDLE =
  "border-hairline bg-surface text-txt-sub shadow-sm hover:border-accent-border hover:bg-accent-soft hover:text-accent-strong";

// Filter values are API snake_case; dictionary filter keys are camelCase.
const FILTER_LABEL_KEY = {
  all: "all",
  consultation: "consultation",
  prescription: "prescription",
  lab_report: "labReport",
  metric: "metric",
} as const;

// Snapshot strip tile order (Everything + the four filterable types).
const SNAPSHOT_TILES: readonly RecordFilter[] = [
  "all",
  "consultation",
  "prescription",
  "lab_report",
  "metric",
];

// PROTO-3.1 (#511): the snapshot strip - a horizontal row of count tiles that
// answer "what should I know". Numbers/labels follow the prototype tokens
// (number 1.375rem/700, label 0.8125rem/500). The mobile copy doubles as
// jump-filters (interactive buttons with aria-pressed); the desktop copy is
// the same counts as static read-only tiles - never a second control set, so
// the rail stays the desktop surface for jumping. The "n issued" micro-label
// always renders on the prescription tile (truthful zero); the "n flagged"
// pill only exists while the payload actually documents out-of-range rows.
function snapshotStripRow({
  interactive,
  filter,
  onSelect,
  counts,
  issuedCount,
  flagged,
  t,
  testId,
  className,
}: {
  interactive: boolean;
  filter: RecordFilter;
  onSelect?: (next: RecordFilter) => void;
  counts: RecordCounts;
  issuedCount: number;
  flagged: LabFlagSummary;
  t: RecordStrings;
  testId: string;
  className: string;
}) {
  return (
    <div
      role="group"
      aria-label={t.summaryLabel}
      data-testid={testId}
      className={className}
    >
      {SNAPSHOT_TILES.map((key) => {
        const isPrescription = key === "prescription";
        const isLab = key === "lab_report";
        const body = (
          <>
            <span className="text-[1.375rem] font-bold leading-[1.15]">
              {counts[key]}
            </span>
            <span className="text-[0.8125rem] font-medium text-txt-muted">
              {key === "all" ? t.snapshot.all : t.filter[FILTER_LABEL_KEY[key]]}
            </span>
            {isPrescription && (
              <span
                data-testid={interactive ? "snapshot-issued" : undefined}
                className="text-xs font-medium text-txt-muted"
              >
                {t.snapshotIssued(issuedCount)}
              </span>
            )}
            {isLab && flagged.entries > 0 && (
              <span
                data-testid={interactive ? "snapshot-flagged" : undefined}
                className="text-xs font-medium text-warn-text"
              >
                {t.snapshotFlagged(flagged.entries)}
              </span>
            )}
          </>
        );
        const tileClassName =
          "flex min-w-0 flex-col gap-0.5 rounded-lg border border-hairline bg-surface px-3.5 py-3 text-left";
        if (interactive) {
          return (
            <button
              key={key}
              type="button"
              onClick={() => onSelect?.(key)}
              aria-pressed={filter === key}
              data-testid={`snapshot-${key}`}
              className={cn(
                tileClassName,
                "cursor-pointer transition-colors hover:border-accent-border",
              )}
            >
              {body}
            </button>
          );
        }
        return (
          <div key={key} className={tileClassName}>
            {body}
          </div>
        );
      })}
    </div>
  );
}

// Single-line chip row: All | Consultations | Prescriptions always, Lab at
// 720px+. Metrics is never a chip - it lives in the More menu at every width.
const CHIP_ROW: readonly RecordFilter[] = [
  "all",
  "consultation",
  "prescription",
  "lab_report",
];

type LoadStatus = "loading" | "ready" | "error";

export default function RecordPage() {
  const { lang } = useLang();
  const t = STRINGS[lang].record;

  const [timeline, setTimeline] = useState<RecordTimeline | null>(null);
  const [status, setStatus] = useState<LoadStatus>("loading");
  const [filter, setFilter] = useState<RecordFilter>("all");
  // Kept from the failed read for the banner's support-correlation line;
  // the banner shows a client-local trace id when the API could not be
  // reached (error-handling-observability §3).
  const [errorTraceId, setErrorTraceId] = useState<string | undefined>(
    undefined,
  );
  // Dismissal is separate from load state: closing the banner must never
  // silently re-fire the failing request.
  const [bannerOpen, setBannerOpen] = useState(false);

  // Snapshot tiles scroll this into view when acting as jump-filters.
  const filterBarRef = useRef<HTMLDivElement>(null);

  // One load path for mount and Retry alike.
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
  // so it fetches only once the timeline has resolved.
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

  const sorted = useMemo(
    () => sortTimelineDesc(timeline?.entries ?? []),
    [timeline],
  );

  const visibleEntries: RecordEntryView[] = useMemo(
    () => applyRecordFilter(sorted, filter),
    [sorted, filter],
  );

  // Payload-derived counts - the snapshot/rail source of truth (honest zero).
  const counts = useMemo(() => countByType(sorted), [sorted]);

  // "n issued" = prescriptions with a non-delivered status; "n flagged" and
  // the rail footnote come from out-of-range lab rows only when a payload
  // documents them (they degrade to zero until the backend produces
  // `results`).
  const issuedCount = useMemo(() => issuedPrescriptionCount(sorted), [sorted]);

  const flagged = useMemo(() => flaggedValues(sorted), [sorted]);

  const groups = useMemo(
    () =>
      groupTimeline(
        visibleEntries,
        { today: t.today, yesterday: t.yesterday },
        lang,
      ),
    [visibleEntries, t.today, t.yesterday, lang],
  );

  const moreActive = filter === "lab_report" || filter === "metric";
  const moreLabel = moreActive
    ? t.filter[FILTER_LABEL_KEY[filter]]
    : t.filter.more;

  const jumpToFilter = (next: RecordFilter) => {
    setFilter(next);
    // Snapshot tiles double as jump-filters: pull the sticky filter bar into
    // view so the scoped feed is directly actionable.
    filterBarRef.current?.scrollIntoView?.({
      behavior: "smooth",
      block: "start",
    });
  };

  const snapshotReady = status === "ready";

  // Shared props for both zone copies of the who-accessed section, so the
  // mobile card and the desktop rail can never drift apart on fetch state.
  const accessProps = {
    accessStatus,
    accessHistory,
    accessBannerOpen,
    accessTraceId,
    onRetry: () => {
      if (timeline?.patient_id) loadAccessHistory(timeline.patient_id);
    },
    onDismiss: () => setAccessBannerOpen(false),
  };

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

      <div className="lg:grid lg:grid-cols-[minmax(0,1fr)_300px] lg:items-start lg:gap-6">
        {/* ============ MAIN COLUMN ============ */}
        <div className="min-w-0">
          {/* Snapshot strip - one copy per zone, rendered once the timeline
              is ready so it never flashes artificial zeros. The mobile copy is
              interactive (tiles double as jump-filters); the desktop copy is a
              static read-only view of the same counts. */}
          {snapshotReady && (
            <div className="mb-3">
              {snapshotStripRow({
                interactive: true,
                filter,
                onSelect: jumpToFilter,
                counts,
                issuedCount,
                flagged,
                t,
                testId: "snapshot-strip",
                className:
                  "grid grid-flow-col auto-cols-[minmax(6.5rem,auto)] gap-2.5 overflow-x-auto pb-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden lg:hidden",
              })}
              {snapshotStripRow({
                interactive: false,
                filter,
                counts,
                issuedCount,
                flagged,
                t,
                testId: "snapshot-strip-desktop",
                className:
                  "hidden grid-flow-col auto-cols-[minmax(6.5rem,auto)] gap-2.5 overflow-x-auto pb-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden lg:grid",
              })}
            </div>
          )}

          {/* Sticky single-line filter bar: bleeds to the shell's content edge
              so rows align with the cards below. */}
          <div
            ref={filterBarRef}
            data-testid="record-filters-wrap"
            className="sticky top-14 z-30 -mx-4 bg-page-bg px-4 pb-1 pt-2"
          >
            <div
              role="group"
              aria-label={t.filterGroupLabel}
              data-testid="record-filters"
              className="flex flex-nowrap items-center gap-2 min-[721px]:mb-8 max-[720px]:mb-4 max-[374px]:overflow-x-auto max-[374px]:[scrollbar-width:none] max-[374px]:[&::-webkit-scrollbar]:hidden"
            >
              {CHIP_ROW.map((key) => {
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
                      overflow && "max-[720px]:hidden",
                      !overflow && "max-[720px]:flex-1",
                    )}
                  >
                    {t.filter[FILTER_LABEL_KEY[key]]}
                  </button>
                );
              })}
              {/* More dropdown at all widths: Lab folds in below 720px (the
                  chip hides), Metrics lives here only - never a chip. */}
              <span
                data-testid="filter-more-wrap"
                className="flex min-w-0 max-[720px]:flex-1"
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
                      onValueChange={(value) =>
                        setFilter(value as RecordFilter)
                      }
                    >
                      {MORE_OVERFLOW_FILTERS.map((key) => (
                        <DropdownMenuRadioItem
                          key={key}
                          value={key}
                          className={cn(
                            key === "lab_report" && "hidden max-[720px]:block",
                          )}
                        >
                          {t.filter[FILTER_LABEL_KEY[key]]}
                        </DropdownMenuRadioItem>
                      ))}
                    </DropdownMenuRadioGroup>
                  </DropdownMenuContent>
                </DropdownMenu>
              </span>
            </div>
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
            <div data-testid="record-timeline">
              {groups.map((group) => (
                <section key={group.key}>
                  <h2
                    data-testid={`group-${group.key}`}
                    className="mt-5 flex items-center gap-2.5 text-[0.75rem] font-semibold uppercase tracking-wide text-txt-muted first:mt-0"
                  >
                    <span>{group.label}</span>
                    <span
                      data-testid={`group-count-${group.key}`}
                      className="font-medium normal-case tracking-normal"
                    >
                      · {group.entries.length}
                    </span>
                    <span
                      aria-hidden="true"
                      className="h-px flex-1 bg-hairline"
                    />
                  </h2>
                  <ul className="mt-2 space-y-2">
                    {group.entries.map((item) => renderEntry(item, t, lang))}
                  </ul>
                </section>
              ))}
            </div>
          )}

          {/* Mobile-only privacy section below the feed (lg:hidden): the home
              health-snapshot card, then who-accessed with its consent-log
              entry point. */}
          {snapshotReady && (
            <div
              className="mt-8 space-y-4 lg:hidden"
              data-testid="record-privacy-mobile"
            >
              <HealthSnapshotCard />
              {renderAccessSection({
                zone: "mobile",
                ...accessProps,
                t,
                lang,
              })}
            </div>
          )}
        </div>

        {/* ============ DESKTOP RAIL ============ */}
        {snapshotReady && (
          <aside
            className="hidden lg:block"
            data-testid="record-rail"
            aria-label={t.summaryLabel}
          >
            <div className="sticky top-[4.5rem] space-y-5">
              <section
                className="rounded-lg border border-hairline bg-surface p-4 shadow-card"
                data-testid="record-rail-summary"
              >
                <h2 className="mb-3 text-xs font-semibold uppercase tracking-wide text-txt-muted">
                  {t.summaryLabel}
                </h2>
                <ul className="flex flex-col gap-1">
                  {[
                    {
                      label: t.filter.consultation,
                      value: counts.consultation,
                      sub: null as null | string,
                    },
                    {
                      label: t.filter.prescription,
                      value: counts.prescription,
                      sub: t.snapshotIssued(issuedCount),
                    },
                    {
                      label: t.filter.labReport,
                      value: counts.lab_report,
                      sub:
                        flagged.entries > 0
                          ? t.snapshotFlagged(flagged.entries)
                          : null,
                    },
                    {
                      label: t.filter.metric,
                      value: counts.metric,
                      sub: null,
                    },
                  ].map((row) => (
                    <li
                      key={row.label}
                      className="flex items-center justify-between gap-2 border-b border-hairline-soft py-2 text-[0.9375rem] text-txt-sub last:border-0"
                    >
                      <span>{row.label}</span>
                      <span className="flex items-center gap-2 text-[1.125rem] font-bold text-txt">
                        {row.value}
                        {row.sub && (
                          <span className="text-[0.8125rem] font-medium text-txt-muted">
                            {row.sub}
                          </span>
                        )}
                      </span>
                    </li>
                  ))}
                </ul>
                {flagged.values > 0 && (
                  <p
                    className="mt-3 text-xs text-txt-muted"
                    data-testid="record-rail-flag-footnote"
                  >
                    {t.outOfRange.footnote(flagged.values)}
                  </p>
                )}
              </section>

              <HealthSnapshotCard />

              {renderAccessSection({
                zone: "rail",
                ...accessProps,
                t,
                lang,
              })}
            </div>
          </aside>
        )}
      </div>
    </>
  );
}

function renderEntry(item: RecordEntryView, t: RecordStrings, lang: Lang) {
  const card = describeEntry(item, t, lang);
  const tone = ENTRY_TONE[item.entry_type];
  const flags = entryFlagRows(item);
  return (
    <li key={item.entry_id} data-testid={`entry-${item.entry_id}`}>
      <Link
        href={`/patient/record/${item.entry_id}`}
        data-testid={`entry-link-${item.entry_id}`}
        className={cn(
          "block rounded-lg border border-l-4 border-hairline bg-surface p-4 shadow-card transition-colors hover:border-accent-border",
          tone.stripe,
        )}
      >
        <div className="flex items-start gap-3">
          <span
            aria-hidden="true"
            className={cn(
              "flex h-11 w-11 shrink-0 items-center justify-center rounded-full text-xl",
              tone.chip,
            )}
          >
            {card.icon}
          </span>
          <span className="min-w-0 flex-1">
            <span className="flex items-start gap-2">
              <span className="min-w-0 flex-1 text-base font-semibold text-txt">
                {card.title}
              </span>
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
            </span>
            {card.subtitle && (
              <span className="mt-0.5 block text-[0.8125rem] text-txt-muted">
                {card.subtitle}
              </span>
            )}
            {flags.length > 0 && (
              <span className="mt-2 flex flex-wrap gap-1.5">
                {flags.map((flag, idx) => (
                  <span
                    key={idx}
                    data-testid={`lab-flag-${item.entry_id}-${idx}`}
                    className="inline-flex items-center rounded-full bg-warn-soft px-2 py-0.5 text-xs font-medium text-warn-text"
                  >
                    {`${flag.test} ${flag.value} \u00b7 ${
                      flag.status === "below_range"
                        ? t.outOfRange.below
                        : t.outOfRange.above
                    }`}
                  </span>
                ))}
              </span>
            )}
          </span>
          <ChevronRight
            size={20}
            aria-hidden="true"
            className="mt-1 shrink-0 text-txt-muted opacity-60"
          />
        </div>
      </Link>
    </li>
  );
}

// Who-accessed accordion, reused per responsive zone with its own testid set
// so a test can scope copy to the mobile card or the desktop rail. The error
// banner lives in the mobile card only (ErrorBanner owns `error-banner`); the
// rail shows a lighter inline error so desktop users still get Retry without
// duplicating testids across the two zones.
// PROTO-3.1 (#511): only the 5 most recent rows render inline; the badge shows
// the full count and the consent-log link routes to the complete audit.
const ACCESS_MOST_RECENT_COUNT = 5;

interface AccessSectionProps {
  zone: "mobile" | "rail";
  accessStatus: LoadStatus;
  accessHistory: AccessHistoryEntry[] | null;
  accessBannerOpen: boolean;
  accessTraceId: string | undefined;
  onRetry: () => void;
  onDismiss: () => void;
  t: RecordStrings;
  lang: Lang;
}

function renderAccessSection({
  zone,
  accessStatus,
  accessHistory,
  accessBannerOpen,
  accessTraceId,
  onRetry,
  onDismiss,
  t,
  lang,
}: AccessSectionProps) {
  const isMobile = zone === "mobile";
  const listId = isMobile ? "access-history-list" : "access-history-rail-list";
  const loadingId = isMobile ? "access-loading" : "access-loading-rail";
  const entryPrefix = isMobile ? "access-entry-" : "access-entry-rail-";
  const keyPrefix = isMobile ? "entry" : "rail";
  const consentLinkId = isMobile
    ? "access-consent-log-link"
    : "access-consent-log-link-rail";
  const hasEntries =
    accessStatus === "ready" && !!accessHistory && accessHistory.length > 0;

  return (
    <section
      data-testid={isMobile ? "access-history" : "access-history-rail"}
      className="rounded-lg border border-hairline bg-surface p-4 shadow-card"
    >
      <div className="flex items-center justify-between gap-2">
        {/* <h2> keeps the existing heading role on mobile; the rail uses a
              <strong> so the two zone copies never duplicate a heading
              level. */}
        {isMobile ? (
          <h2 className="text-base font-semibold text-txt">
            {t.accessHistory.heading}
          </h2>
        ) : (
          <strong className="text-base font-semibold text-txt">
            {t.accessHistory.heading}
          </strong>
        )}
        {hasEntries && (
          <span className="rounded-full bg-hairline-soft px-2 py-0.5 text-xs font-medium text-txt-muted">
            {accessHistory.length}
          </span>
        )}
      </div>
      <details className="mt-2">
        <summary className="cursor-pointer list-none text-sm text-txt-muted">
          <span className="flex items-center justify-between gap-2">
            {t.accessAccordionHint}
            <span aria-hidden="true" className="text-txt-muted">
              ▾
            </span>
          </span>
        </summary>
        <div className="mt-3">
          {accessBannerOpen &&
            (isMobile ? (
              <ErrorBanner
                message={t.accessHistory.loadError}
                traceId={accessTraceId}
                onRetry={onRetry}
                onDismiss={onDismiss}
              />
            ) : (
              <p
                className="mb-2 flex items-center justify-between gap-2 text-sm text-danger"
                data-testid="access-rail-error"
              >
                <span>{t.accessHistory.loadError}</span>
                <button
                  type="button"
                  onClick={onRetry}
                  data-testid="access-rail-retry"
                  className="shrink-0 rounded-md border border-danger-border px-2 py-1 text-xs font-medium text-danger hover:bg-danger-soft/60"
                >
                  Retry
                </button>
              </p>
            ))}
          {accessStatus === "loading" ? (
            <ul className="space-y-2" data-testid={loadingId}>
              {[0, 1, 2].map((row) => (
                <li
                  key={row}
                  className="h-10 animate-pulse rounded-lg border border-hairline bg-hairline-soft/60"
                />
              ))}
            </ul>
          ) : accessStatus === "error" ||
            accessHistory === null ? null : accessHistory.length === 0 ? (
            <div className="space-y-1">
              <p className="text-sm font-medium text-txt">
                {t.accessHistory.emptyTitle}
              </p>
              <p className="text-sm text-txt-muted">
                {t.accessHistory.emptyBody}
              </p>
            </div>
          ) : (
            <ul className="space-y-2" data-testid={listId}>
              {accessHistory
                .slice(0, ACCESS_MOST_RECENT_COUNT)
                .map((entry, index) => {
                  const identity = entry.actor_type || `ID ${entry.actor_id}`;
                  const scope = entry.scope
                    ? `, ${t.accessHistory.scopePrefix}${entry.scope}`
                    : "";
                  return (
                    <li
                      key={`${keyPrefix}-${entry.actor_id}-${entry.accessed_at}-${index}`}
                      data-testid={`${entryPrefix}${index}`}
                    >
                      <div>
                        <span className="flex items-start gap-2">
                          <strong className="text-[0.9375rem] text-txt">
                            {identity}
                          </strong>
                          {entry.denied && (
                            <span className="ml-auto shrink-0 rounded-full bg-danger-soft px-2 py-0.5 text-xs font-medium text-danger">
                              {t.accessHistory.deniedLabel}
                            </span>
                          )}
                        </span>
                        <p className="mt-0.5 text-[0.8125rem] text-txt-muted">
                          {formatOccurredAt(entry.accessed_at, lang)}
                          {scope}
                        </p>
                        {entry.denied && entry.denial_reason ? (
                          <p className="mt-0.5 text-xs text-txt-muted">
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
        </div>
      </details>

      {/* "Open consent log" is a permanent entry point at the bottom of the
          section, visible without expanding the audit (prototype posture). */}
      <footer className="mt-3">
        <Link
          href="/patient/record/consent-log"
          data-testid={consentLinkId}
          className="inline-flex items-center gap-1 text-xs font-medium tracking-wide text-accent-strong hover:underline"
        >
          {t.openConsentLog}
          <ChevronRight size={14} aria-hidden="true" />
        </Link>
      </footer>
    </section>
  );
}
