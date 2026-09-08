"use client";

// PHASE-7 T18 (#362): pre-summary review page (blueprint §5.4/§6.4; the
// finalized PROTO-PHASE-7/8 pre-summary-review.html +
// pre-summary-low-confidence.html pages are the binding copy spec). Shows the
// AI draft to the patient under the honesty cue "AI draft - doctor will
// verify" (never "AI diagnosis", ADR-0001), with the structuring confidence
// value + a light indicator and - for a low_confidence draft - a calm amber
// doctor-must-check notice with the forced-review framing (warn, never red;
// the draft cannot advance past the doctor without review). On the
// low_confidence variant the amber notice replaces the separate honesty banner
// as the sole framing (binding pre-summary-low-confidence.html copy spec). The structured
// fields render read-only; "Edit this summary" turns them into inputs and
// "Save edits" persists the changes via the patient-edits route, where they
// merge as informational corrections to the doctor (never mutating the AI
// fields, FEAT-007 / US-14). "Confirm & continue" opens the continuation CTA
// toward consultation booking. Bilingual EN/HI.

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ErrorBanner } from "@/components/layout/ErrorBanner";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api-errors";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import {
  fetchPreSummary,
  savePatientEdits,
  type PatientEditsResult,
  type PreSummaryView,
} from "@/lib/intake/api";

type LoadStage = "loading" | "ready" | "error";
type SaveStage = "idle" | "pending";
type BannerState = {
  title: string;
  body: string;
  traceId?: string;
} | null;

// Preferred display order for the free-form structured_fields record; any
// keys the backend adds later still render (after the known ones).
const FIELD_ORDER = ["chief_complaints", "symptoms", "duration"];

/** Format a structured value for display and as the initial edit text. */
function formatFieldValue(value: unknown): string {
  if (Array.isArray(value)) {
    return value.join(", ");
  }
  if (value === null || value === undefined) {
    return "";
  }
  if (typeof value === "object") {
    return JSON.stringify(value);
  }
  return String(value);
}

function orderedFieldKeys(fields: Record<string, unknown>): string[] {
  const known = FIELD_ORDER.filter((key) => key in fields);
  const rest = Object.keys(fields).filter((key) => !FIELD_ORDER.includes(key));
  return [...known, ...rest];
}

export default function PreSummaryReviewPage() {
  const params = useParams<{ intakeId: string }>();
  const intakeId = Number(params.intakeId);
  const { lang } = useLang();
  const dict = STRINGS[lang].intake;
  const t = dict.preSummary;
  const nav = STRINGS[lang].nav;

  const [summary, setSummary] = useState<PreSummaryView | null>(null);
  const [loadStage, setLoadStage] = useState<LoadStage>("loading");
  const [loadError, setLoadError] = useState<BannerState>(null);
  const [editing, setEditing] = useState(false);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [corrections, setCorrections] = useState<Record<string, unknown>>({});
  const [saveStage, setSaveStage] = useState<SaveStage>("idle");
  const [saveError, setSaveError] = useState<BannerState>(null);
  const [confirmed, setConfirmed] = useState(false);

  // load is keyed only on intakeId so a locale flip never re-fetches the
  // pre-summary; the error copy is resolved at failure time instead.
  const langRef = useRef(lang);
  useEffect(() => {
    langRef.current = lang;
  }, [lang]);

  const load = useCallback(() => {
    // No synchronous setState here: only the async continuations mutate
    // state, so the mount effect below stays a pure "subscribe" (the
    // react-hooks lint only grows loud when setState runs synchronously in
    // an effect body).
    fetchPreSummary(intakeId)
      .then((next) => {
        setSummary(next);
        setCorrections(next.patient_edits ?? {});
        setLoadStage("ready");
      })
      .catch((error: unknown) => {
        setLoadStage("error");
        const preSummary = STRINGS[langRef.current].intake.preSummary;
        setLoadError({
          title: preSummary.loadFailedTitle,
          body: preSummary.loadFailedBody,
          traceId: error instanceof ApiError ? error.traceId : undefined,
        });
      });
  }, [intakeId]);

  useEffect(() => {
    load();
  }, [load]);

  // One reload path for banner Retry: flips back to loading (event handler,
  // not an effect) and re-reads the pre-summary.
  const reload = useCallback(() => {
    setLoadStage("loading");
    setLoadError(null);
    load();
  }, [load]);

  const lowConfidence = summary?.low_confidence === true;
  const fieldKeys = useMemo(
    () => (summary ? orderedFieldKeys(summary.structured_fields ?? {}) : []),
    [summary],
  );

  /** The value a field shows right now: patient correction wins over AI. */
  const displayValueFor = useCallback(
    (fieldKey: string): string => {
      if (!summary) return "";
      const merged =
        corrections[fieldKey] ?? summary.structured_fields[fieldKey];
      return formatFieldValue(merged);
    },
    [summary, corrections],
  );

  const fieldLabel = (fieldKey: string): string =>
    (t.fields as Record<string, string>)[fieldKey] ?? fieldKey;

  const enterEdit = useCallback(() => {
    const seeded: Record<string, string> = {};
    for (const key of fieldKeys) {
      seeded[key] = displayValueFor(key);
    }
    setDrafts(seeded);
    setSaveError(null);
    setEditing(true);
  }, [fieldKeys, displayValueFor]);

  const handleSave = useCallback(async () => {
    if (!summary) return;
    // Only changed fields are corrections; unchanged rows never ride along.
    const diffs: Record<string, unknown> = {};
    for (const key of fieldKeys) {
      if (!(key in drafts)) continue;
      const original = displayValueFor(key);
      if (drafts[key].trim() !== original) {
        diffs[key] = drafts[key];
      }
    }
    if (Object.keys(diffs).length === 0) {
      setEditing(false);
      setSaveError(null);
      return;
    }

    setSaveStage("pending");
    setSaveError(null);
    try {
      const result: PatientEditsResult = await savePatientEdits(
        intakeId,
        diffs,
      );
      setCorrections(result.patient_edits ?? {});
      setEditing(false);
    } catch (error) {
      setSaveError({
        title: t.saveFailedTitle,
        body: t.saveFailedBody,
        traceId: error instanceof ApiError ? error.traceId : undefined,
      });
    } finally {
      setSaveStage("idle");
    }
  }, [summary, fieldKeys, drafts, displayValueFor, intakeId, t]);

  const handleConfirm = useCallback(() => {
    setConfirmed(true);
  }, []);

  if (loadStage === "loading" || (loadStage === "ready" && !summary)) {
    return (
      <>
        <PageHeader
          title={t.title}
          breadcrumbs={[
            { label: nav.home, href: "/patient" },
            { label: dict.breadcrumb, href: "/patient/intake" },
            { label: t.breadcrumb },
          ]}
        />
        <p
          className="inline-flex items-center gap-2 text-sm text-txt-muted"
          data-testid="load-pending"
        >
          <span
            className="h-3.5 w-3.5 shrink-0 animate-spin rounded-full border-2 border-hairline border-t-accent"
            aria-hidden="true"
          />
          {t.loading}
        </p>
      </>
    );
  }

  if (loadStage === "error" || !summary) {
    return (
      <>
        <PageHeader
          title={t.title}
          breadcrumbs={[
            { label: nav.home, href: "/patient" },
            { label: dict.breadcrumb, href: "/patient/intake" },
            { label: t.breadcrumb },
          ]}
        />
        {loadError && (
          <ErrorBanner
            message={
              <>
                <strong className="font-semibold">{loadError.title}</strong>
                <span className="block">{loadError.body}</span>
              </>
            }
            traceId={loadError.traceId}
            onRetry={reload}
            onDismiss={() => setLoadError(null)}
          />
        )}
      </>
    );
  }

  const confidencePct =
    summary.structuring_confidence != null
      ? Math.round(summary.structuring_confidence * 100)
      : 0;
  const confidenceText =
    summary.structuring_confidence != null
      ? summary.structuring_confidence.toFixed(2)
      : "–";
  const hasFields = fieldKeys.length > 0;
  const fieldCount = fieldKeys.length;
  const changedCount = fieldKeys.filter(
    (key) => key in drafts && drafts[key].trim() !== displayValueFor(key),
  ).length;

  return (
    <>
      <PageHeader
        title={t.title}
        description={t.description}
        breadcrumbs={[
          { label: nav.home, href: "/patient" },
          { label: dict.breadcrumb, href: "/patient/intake" },
          { label: t.breadcrumb },
        ]}
      />

      <div
        className="mx-auto flex max-w-xl flex-col gap-4"
        data-testid="pre-summary-page"
      >
        {/*** Honesty cue - unmissable, never "AI diagnosis" (ADR-0001); on a
            low_confidence draft the amber notice below replaces it as the
            sole framing (binding pre-summary-low-confidence.html copy spec) */}
        {!lowConfidence && (
          <div
            className="flex items-start gap-3 rounded-lg border border-accent-border bg-accent-soft px-4 py-3"
            role="status"
            data-testid="honesty-banner"
          >
            <svg
              width="20"
              height="20"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              aria-hidden="true"
              className="mt-0.5 shrink-0 text-accent-strong"
            >
              <path d="M12 2L2 7l10 5 10-5-10-5z" />
              <path d="M2 17l10 5 10-5" />
              <path d="M2 12l10 5 10-5" />
            </svg>
            <div className="min-w-0">
              <p
                className="font-semibold text-accent-strong"
                data-testid="honesty-cue"
              >
                {t.bannerLine1}
              </p>
              <p className="text-sm text-txt-sub">{t.bannerLine2}</p>
            </div>
          </div>
        )}

        {/*** Low-confidence notice - calm amber, forced doctor review (§6.4) */}
        {lowConfidence && (
          <div
            className="flex items-start gap-3 rounded-lg border border-warn-text bg-warn-soft px-4 py-3"
            role="status"
            data-testid="lowconf-banner"
          >
            <svg
              width="20"
              height="20"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              aria-hidden="true"
              className="mt-0.5 shrink-0 text-warn-text"
            >
              <circle cx="12" cy="12" r="10" />
              <path d="M12 8v4M12 16h.01" />
            </svg>
            <div className="min-w-0">
              <p
                className="font-semibold text-warn-text"
                data-testid="lowconf-title"
              >
                {t.lowBannerLine1}
              </p>
              <p className="text-sm text-txt-sub">{t.lowBannerLine2}</p>
              <p
                className="mt-1.5 flex items-start gap-1.5 text-xs font-medium text-warn-text"
                data-testid="lowconf-verify"
              >
                <svg
                  width="14"
                  height="14"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden="true"
                  className="mt-0.5 shrink-0"
                >
                  <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
                </svg>
                <span>{t.lowVerifyLine}</span>
              </p>
            </div>
          </div>
        )}

        {/*** Confidence value + light indicator (clean: accent, low: amber) */}
        <div
          className={`flex items-center gap-3 rounded-md border px-3.5 py-2.5 ${
            lowConfidence
              ? "border-warn-text bg-warn-soft"
              : "border-hairline bg-bg-subtle"
          }`}
          data-testid="confidence-row"
        >
          <span className="text-sm whitespace-nowrap text-txt-sub">
            {t.confidence}
          </span>
          <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-hairline">
            <div
              className={`h-full rounded-full ${
                lowConfidence ? "bg-warn-text" : "bg-accent"
              }`}
              style={{ width: `${confidencePct}%` }}
              data-testid="confidence-bar-fill"
            />
          </div>
          <span
            className="text-sm font-semibold tabular-nums text-txt"
            data-testid="confidence-value"
          >
            {confidenceText}
          </span>
        </div>

        {/*** Structured fields - read-only cards; inputs while editing */}
        <section
          className={`rounded-lg border bg-surface p-0 shadow-card ${
            lowConfidence
              ? "border-l-4 border-l-warn-text border-hairline"
              : "border-hairline"
          }`}
          data-testid="fields-card"
        >
          <header className="flex items-center justify-between gap-2 border-b border-hairline bg-bg-subtle px-4 py-3">
            <h2 className="text-sm font-semibold text-txt">{t.groupTitle}</h2>
            {lowConfidence && (
              <span
                className="rounded-full border border-warn-text bg-warn-soft px-2 py-0.5 text-[0.6875rem] font-semibold tracking-wide text-warn-text"
                data-testid="low-tag"
              >
                {t.lowTag}
              </span>
            )}
          </header>

          {hasFields ? (
            <ul>
              {fieldKeys.map((key, index) => {
                const label = fieldLabel(key);
                const isCorrection = key in corrections;
                return (
                  <li
                    key={key}
                    className={`flex items-center justify-between gap-3 px-4 py-2.5 ${
                      index < fieldCount - 1
                        ? "border-b border-hairline-soft"
                        : ""
                    }`}
                    data-testid={`field-row-${key}`}
                  >
                    <span className="flex min-w-0 items-center gap-1.5 text-sm text-txt-muted">
                      {lowConfidence && (
                        <span
                          className="h-1.5 w-1.5 shrink-0 rounded-full bg-warn-text"
                          aria-hidden="true"
                        />
                      )}
                      <span className="truncate">{label}</span>
                    </span>

                    {editing ? (
                      <input
                        type="text"
                        value={drafts[key] ?? ""}
                        onChange={(event) =>
                          setDrafts((current) => ({
                            ...current,
                            [key]: event.target.value,
                          }))
                        }
                        aria-label={label}
                        data-testid={`field-input-${key}`}
                        className="min-w-0 max-w-[16rem] flex-1 rounded-md border border-hairline bg-surface px-2.5 py-1.5 text-right text-sm text-txt transition-[border-color,box-shadow] focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
                      />
                    ) : isCorrection ? (
                      <span
                        className="flex min-w-0 items-center justify-end gap-1.5"
                        data-testid={`field-value-${key}`}
                      >
                        <span
                          className="shrink-0 rounded-full bg-accent-soft px-2 py-0.5 text-[0.6875rem] font-semibold text-accent-strong"
                          data-testid={`correction-tag-${key}`}
                        >
                          {t.correctionsTag}
                        </span>
                        <span className="truncate text-right text-sm font-medium text-txt">
                          {displayValueFor(key)}
                        </span>
                      </span>
                    ) : (
                      <span
                        className="truncate text-right text-sm font-medium text-txt"
                        data-testid={`field-value-${key}`}
                      >
                        {displayValueFor(key)}
                      </span>
                    )}
                  </li>
                );
              })}
            </ul>
          ) : (
            <div className="px-4 py-4" data-testid="fields-empty">
              <p className="text-sm font-semibold text-txt">{t.emptyTitle}</p>
              <p className="text-sm text-txt-muted">{t.emptyBody}</p>
            </div>
          )}
        </section>

        {/*** Edit note + actions (idle) */}
        {!editing && !confirmed && (
          <>
            {hasFields && (
              <p
                className="flex items-start gap-1.5 text-xs text-txt-muted"
                data-testid="edit-note"
              >
                <svg
                  width="14"
                  height="14"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.8"
                  strokeLinecap="round"
                  aria-hidden="true"
                  className="mt-0.5 shrink-0"
                >
                  <circle cx="12" cy="12" r="10" />
                  <path d="M12 16v-4M12 8h.01" />
                </svg>
                <span>{t.editNote}</span>
              </p>
            )}
            <div className="flex flex-col gap-2">
              {hasFields && (
                <Button
                  type="button"
                  variant="secondary"
                  size="lg"
                  className="w-full"
                  data-testid="btn-edit"
                  onClick={enterEdit}
                >
                  {t.editBtn}
                </Button>
              )}
              <Button
                type="button"
                size="lg"
                className="w-full"
                data-testid="btn-confirm"
                onClick={handleConfirm}
              >
                {lowConfidence ? t.confirmBtnLow : t.confirmBtn}
              </Button>
            </div>
          </>
        )}

        {/*** Edit-mode actions */}
        {editing && (
          <>
            {saveError && (
              <ErrorBanner
                message={
                  <>
                    <strong className="font-semibold">{saveError.title}</strong>
                    <span className="block">{saveError.body}</span>
                  </>
                }
                traceId={saveError.traceId}
                onRetry={() => void handleSave()}
                onDismiss={() => setSaveError(null)}
              />
            )}
            <div className="flex flex-col gap-2">
              <Button
                type="button"
                variant="secondary"
                size="lg"
                className="w-full"
                data-testid="btn-cancel"
                onClick={() => {
                  setEditing(false);
                  setSaveError(null);
                }}
                disabled={saveStage === "pending"}
              >
                {t.cancelEdit}
              </Button>
              <Button
                type="button"
                size="lg"
                className="w-full"
                data-testid="btn-save"
                onClick={() => void handleSave()}
                disabled={changedCount === 0}
                loading={saveStage === "pending"}
              >
                {saveStage === "pending" ? t.savingEdit : t.saveEdit}
              </Button>
            </div>
          </>
        )}

        {/*** Confirmed - continuation toward consultation booking */}
        {confirmed && !editing && (
          <div className="flex flex-col gap-3" data-testid="confirmed-zone">
            <p className="flex items-center justify-center gap-2 rounded-lg bg-success-soft p-3 font-medium text-success-text">
              <span aria-hidden="true">✓</span>
              <span data-testid="done-line">
                {lowConfidence ? t.doneLow : t.doneClean}
              </span>
            </p>
            <Button asChild size="lg" className="w-full" data-testid="btn-book">
              <Link href={`/doctors?intake=${intakeId}`}>{t.bookTitle}</Link>
            </Button>
            <p className="mb-0 text-sm text-txt-muted" data-testid="book-sub">
              {lowConfidence ? t.bookSubLow : t.bookSub}
            </p>
          </div>
        )}
      </div>
    </>
  );
}
