"use client";

// MOD-003 (FEAT-018 metrics), #549: the Health background zone's height/weight
// series - the append-only measurement record the patient keeps over time
// (US-23), on the owner's own endpoint from #535.
//
// Append-only is a clinical decision, not a missing feature. A measurement is a
// moment in the patient's history, so there is no edit and no delete: adding a
// corrected one is how a wrong number is fixed, and the old row stays as what
// was actually recorded. The consequence is that a lost response would write a
// second, wrong number the patient never intended - so the append carries an
// Idempotency-Key that is held across a failure and replayed on the retry, and
// cleared only once a row has actually landed.
//
// The list is server-paged. The first page is all the series this surface needs
// to be useful, but `total` says how many exist, so the rest is one tap away
// rather than silently absent.

import { useCallback, useEffect, useRef, useState } from "react";

import { HealthZoneFailureNotice } from "@/components/patient/profile/HealthZoneFailureNotice";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api-errors";
import { STRINGS, type Dictionary } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import {
  appendHealthMetric,
  fetchHealthMetrics,
  type HealthMetricEntry,
} from "@/lib/health-background/api";
import {
  HEIGHT_CM_MAX,
  HEIGHT_CM_MIN,
  WEIGHT_KG_MAX,
  WEIGHT_KG_MIN,
  parseMeasurement,
  type MeasurementComplaint,
  type MeasurementDraft,
  type MeasurementField,
} from "@/lib/health-background/form";

type ZoneStrings = Dictionary["profileZones"];

const labelClass = "text-sm font-medium text-txt";

const inputClass =
  "mt-1 block h-9 w-full rounded-md border border-input bg-background px-3 text-sm text-txt shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring";

/** Trace id off a failure so a support conversation can start from the alert. */
function traceIdOf(error: unknown): string | undefined {
  return error instanceof ApiError && error.traceId ? error.traceId : undefined;
}

/** Map a parse complaint onto the dictionary entry that names it. */
function complaintCopy(t: ZoneStrings, reason: MeasurementComplaint): string {
  switch (reason) {
    case "value-required":
      return t.metricValueRequired;
    case "value-not-a-number":
      return t.metricValueNotANumber;
    case "height-out-of-range":
      return t.metricHeightRange(HEIGHT_CM_MIN, HEIGHT_CM_MAX);
    case "weight-out-of-range":
      return t.metricWeightRange(WEIGHT_KG_MIN, WEIGHT_KG_MAX);
    // A missing date and an unreadable one are different mistakes, and telling
    // the patient to "pick it again" when they never picked one reads as a
    // broken screen.
    case "recorded-at-required":
      return t.metricRecordedAtRequired;
    case "recorded-at-invalid":
      return t.metricDateInvalid;
  }
}

function measurementFieldId(field: MeasurementField): string {
  return `ps-hb-metric-error-${field}`;
}

/** One day's rendering of a stored measurement, in the active locale. */
function entryDate(entry: HealthMetricEntry, lang: string): string {
  const parsed = new Date(entry.recorded_at);
  if (Number.isNaN(parsed.getTime())) return entry.recorded_at;
  return parsed.toLocaleDateString(lang === "hi" ? "hi-IN" : "en-IN", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

const BLANK_DRAFT: MeasurementDraft = {
  heightCm: "",
  weightKg: "",
  recordedAt: "",
};

/** One row per server-minted id, in the order they arrived. */
function dedupeById(rows: HealthMetricEntry[]): HealthMetricEntry[] {
  const seen = new Set<number>();
  return rows.filter((row) => {
    if (seen.has(row.entry_id)) return false;
    seen.add(row.entry_id);
    return true;
  });
}

export function HealthMetricsSeries() {
  const { lang } = useLang();
  const t: ZoneStrings = STRINGS[lang].profileZones;

  // `null` means "not read yet", which is a loading state, not an empty one.
  const [entries, setEntries] = useState<HealthMetricEntry[] | null>(null);
  // `null` means the series has never been read, so how much of it exists is
  // unknown. Counting on top of an unknown would report a total the API never
  // gave us and hide the rest of the series behind a button that thinks it is
  // not needed.
  const [total, setTotal] = useState<number | null>(null);
  const [page, setPage] = useState(1);
  const [loadFailure, setLoadFailure] = useState<{ traceId?: string } | null>(
    null,
  );
  const [loadingMore, setLoadingMore] = useState(false);
  const [moreFailure, setMoreFailure] = useState<{ traceId?: string } | null>(
    null,
  );

  const [draft, setDraft] = useState<MeasurementDraft>(BLANK_DRAFT);
  const [draftError, setDraftError] = useState<{
    field: MeasurementField;
    message: string;
  } | null>(null);
  const [appending, setAppending] = useState(false);
  const [appendFailure, setAppendFailure] = useState<{
    traceId?: string;
  } | null>(null);
  const [appended, setAppended] = useState(false);
  // The Idempotency-Key of the append in flight. Kept until a row has actually
  // landed, so retrying a lost response replays the same mutation instead of
  // writing a second measurement the patient never meant to record.
  const pendingAppendKey = useRef<string | undefined>(undefined);

  /**
   * Any edit to the draft spends the key. A key identifies ONE mutation: sent
   * again with a different body, the gateway replays the ORIGINAL result and
   * reports success, so an edited-and-retried measurement would silently go in
   * as the value the patient just corrected. Editing is therefore a new
   * attempt with a new key, and the trade is explicit - a lost response plus an
   * edit can leave a duplicate row, which the patient can see and reason about,
   * where a silently discarded correction cannot.
   */
  function editDraft(next: MeasurementDraft) {
    pendingAppendKey.current = undefined;
    setAppended(false);
    setDraftError(null);
    setDraft(next);
  }

  const loadFirstPage = useCallback(async () => {
    setLoadFailure(null);
    try {
      const result = await fetchHealthMetrics({ page: 1 });
      setEntries(result.items);
      setTotal(result.total);
      setPage(1);
    } catch (err) {
      setLoadFailure({ traceId: traceIdOf(err) });
    }
  }, []);

  useEffect(() => {
    void loadFirstPage();
  }, [loadFirstPage]);

  async function loadMore() {
    if (loadingMore) return;
    setMoreFailure(null);
    setLoadingMore(true);
    const next = page + 1;
    try {
      const result = await fetchHealthMetrics({ page: next });
      setEntries((current) => {
        const next_ =
          current === null ? result.items : [...current, ...result.items];
        // An append since the last page shifts the server's offset window by
        // one, so the boundary row can arrive twice. Keying on the id the API
        // minted keeps the list to one row per measurement.
        return dedupeById(next_);
      });
      setTotal(result.total);
      setPage(next);
    } catch (err) {
      setMoreFailure({ traceId: traceIdOf(err) });
    } finally {
      setLoadingMore(false);
    }
  }

  async function handleAdd() {
    if (appending) return;
    setAppendFailure(null);
    setAppended(false);
    const parsed = parseMeasurement(draft);
    if (!parsed.ok) {
      setDraftError({
        field: parsed.field,
        message: complaintCopy(t, parsed.reason),
      });
      return;
    }
    setDraftError(null);
    setAppending(true);
    const key = pendingAppendKey.current ?? crypto.randomUUID();
    pendingAppendKey.current = key;
    try {
      const entry = await appendHealthMetric(parsed.value, key);
      // The appended entry joins the list straight away: the series is the
      // patient's own record of their trend, and a read-back they have to wait
      // for is a read-back that looks broken. A full re-read is not needed - the
      // list is newest-first and this is the newest.
      setEntries((current) =>
        current === null ? [entry] : [entry, ...current],
      );
      setTotal((current) => (current === null ? null : current + 1));
      // Only now is the key spent: the row exists.
      pendingAppendKey.current = undefined;
      setDraft(BLANK_DRAFT);
      setAppended(true);
    } catch (err) {
      // The typed values and the key both stay, so the same tap retries the
      // same measurement rather than risking a duplicate.
      setAppendFailure({ traceId: traceIdOf(err) });
    } finally {
      setAppending(false);
    }
  }

  const hasMore = entries !== null && total !== null && entries.length < total;

  return (
    <div data-testid="ps-hb-metrics" className="border-t border-hairline pt-5">
      <h3 className="text-sm font-semibold text-txt">{t.metricsHeading}</h3>
      <p className="mt-0.5 text-xs text-txt-muted">{t.metricsSub}</p>

      <div className="mt-3 flex flex-col gap-4">
        <div>
          <label htmlFor="ps-hb-metric-height" className={labelClass}>
            {t.heightLabel}
          </label>
          <input
            id="ps-hb-metric-height"
            data-testid="ps-hb-metric-height"
            type="text"
            inputMode="decimal"
            className={inputClass}
            value={draft.heightCm}
            aria-describedby={
              draftError?.field === "height"
                ? measurementFieldId("height")
                : undefined
            }
            aria-invalid={draftError?.field === "height" ? true : undefined}
            onChange={(e) => {
              editDraft({ ...draft, heightCm: e.target.value });
            }}
          />
        </div>

        <div>
          <label htmlFor="ps-hb-metric-weight" className={labelClass}>
            {t.weightLabel}
          </label>
          <input
            id="ps-hb-metric-weight"
            data-testid="ps-hb-metric-weight"
            type="text"
            inputMode="decimal"
            className={inputClass}
            value={draft.weightKg}
            aria-describedby={
              draftError?.field === "weight"
                ? measurementFieldId("weight")
                : undefined
            }
            aria-invalid={draftError?.field === "weight" ? true : undefined}
            onChange={(e) => {
              editDraft({ ...draft, weightKg: e.target.value });
            }}
          />
        </div>

        <div>
          <label htmlFor="ps-hb-metric-recorded-at" className={labelClass}>
            {t.recordedAtLabel}
          </label>
          <input
            id="ps-hb-metric-recorded-at"
            data-testid="ps-hb-metric-recorded-at"
            type="datetime-local"
            className={inputClass}
            value={draft.recordedAt}
            aria-describedby={
              draftError?.field === "recordedAt"
                ? measurementFieldId("recordedAt")
                : undefined
            }
            aria-invalid={draftError?.field === "recordedAt" ? true : undefined}
            onChange={(e) => {
              editDraft({ ...draft, recordedAt: e.target.value });
            }}
          />
        </div>

        {draftError !== null && (
          <p
            role="alert"
            id={measurementFieldId(draftError.field)}
            data-testid={measurementFieldId(draftError.field)}
            className="text-xs font-medium text-danger"
          >
            {draftError.message}
          </p>
        )}

        <div className="flex justify-end">
          <Button
            type="button"
            variant="secondary"
            data-testid="ps-hb-metric-add"
            onClick={() => void handleAdd()}
            loading={appending}
          >
            {t.metricAdd}
          </Button>
        </div>
      </div>

      {entries === null && loadFailure === null && (
        <p
          data-testid="ps-hb-metrics-loading"
          className="mt-3 text-sm text-txt-muted"
          role="status"
        >
          {t.metricsLoading}
        </p>
      )}

      {loadFailure !== null && (
        <HealthZoneFailureNotice
          message={t.metricsLoadFailed}
          retryLabel={t.healthRetry}
          failure={loadFailure}
          onRetry={() => void loadFirstPage()}
          testId="ps-hb-metrics-failed"
          retryTestId="ps-hb-metrics-retry"
          className="mt-3"
        />
      )}

      {entries !== null && entries.length === 0 && loadFailure === null && (
        <p
          data-testid="ps-hb-metrics-empty"
          className="mt-3 text-sm text-txt-muted"
        >
          {t.metricsEmpty}
        </p>
      )}

      {appended && (
        <p
          role="status"
          data-testid="ps-hb-metric-added"
          className="mt-3 text-sm text-success-text"
        >
          {t.metricAdded}
        </p>
      )}

      {appendFailure !== null && (
        <p
          role="alert"
          data-testid="ps-hb-metric-add-failed"
          className="mt-3 rounded-md border border-danger-border bg-danger-soft px-3 py-2 text-sm text-danger"
        >
          {t.metricAddFailed}
          {appendFailure.traceId && (
            <span className="ml-1 font-mono text-xs">
              ({appendFailure.traceId})
            </span>
          )}
        </p>
      )}

      <ul className="mt-3 flex flex-col gap-2">
        {entries?.map((entry) => (
          <li
            key={entry.entry_id}
            data-testid={`ps-hb-metric-${entry.entry_id}`}
            className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-hairline bg-surface px-3 py-2"
          >
            {/* The unit alone names the value: a screen reader reads "170 cm"
                then "68.5 kg" and would otherwise hear two anonymous numbers
                with nothing saying which is which. */}
            <span
              className="text-sm text-txt"
              aria-label={t.heightUnit}
              data-testid={`ps-hb-metric-height-${entry.entry_id}`}
            >
              {entry.height_cm === null
                ? t.metricNotRecorded
                : `${entry.height_cm} ${t.heightUnit}`}
            </span>
            <span
              className="text-sm text-txt"
              aria-label={t.weightUnit}
              data-testid={`ps-hb-metric-weight-${entry.entry_id}`}
            >
              {entry.weight_kg === null
                ? t.metricNotRecorded
                : `${entry.weight_kg} ${t.weightUnit}`}
            </span>
            <span
              data-testid={`ps-hb-metric-date-${entry.entry_id}`}
              className="text-xs text-txt-muted"
            >
              {entryDate(entry, lang)}
            </span>
          </li>
        ))}
      </ul>

      {hasMore && (
        <div className="mt-3 flex flex-col items-start gap-2">
          <Button
            type="button"
            variant="ghost"
            data-testid="ps-hb-metrics-load-more"
            onClick={() => void loadMore()}
            loading={loadingMore}
          >
            {loadingMore ? t.metricsLoadingMore : t.metricsLoadMore}
          </Button>
          {moreFailure !== null && (
            <HealthZoneFailureNotice
              message={t.metricsMoreFailed}
              retryLabel={t.healthRetry}
              failure={moreFailure}
              onRetry={() => void loadMore()}
              testId="ps-hb-metrics-more-failed"
              retryTestId="ps-hb-metrics-more-retry"
            />
          )}
        </div>
      )}
    </div>
  );
}
