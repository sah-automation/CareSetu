"use client";

// PHASE-8.1 T13/T14/T15 (#451/#452/#453): case workspace for the open-cases
// entry path. The console's "Open cases" deep-links to /doctor/cases/[caseId]
// (one per active care case). This page shows the case stage, the forced-
// review requirement (if any), the patient's consented health history, and
// the consult-complete handshake for pre_summary-stage cases. For
// prescription-pending cases it hosts prescription drafting (US-18): request
// an AI draft, edit the rx items, and save the working revision. A hard
// refresh of a pending case reloads the in-progress revision from the
// working-rx read so a navigation mistake is not data loss. Issuance and
// closure (US-19..22): approve the reviewed prescription only behind the
// verification declaration, render the issued prescription after approval,
// reject a draft with a patient-understandable reason, and close the case
// without prescribing. Every care mutation here sends the idempotency-key
// header via the shared client helper (#446).
//
// All copy bilingual en/hi (REQ-006).

import type { FormEvent } from "react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { ConsentedHistory } from "@/components/case/ConsentedHistory";
import { ErrorBanner } from "@/components/layout/ErrorBanner";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { ApiError } from "@/lib/api-errors";
import {
  approvePrescription,
  closeCaseWithoutRx,
  createRxDraft,
  fetchCareCase,
  fetchWorkingPrescription,
  markConsultComplete,
  rejectPrescription,
  saveRxRevision,
  type CareCaseStage,
  type CaseDetailView,
  type CloseReason,
  type PrescriptionDetailView,
  type RxItemInput,
  type RxItemView,
} from "@/lib/care/api";
import { fetchPartnerMe, type PartnerMeView } from "@/lib/partner/api";
import { STRINGS, type Dictionary } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";

// The editor's row shape: form fields are plain strings (empty = not set),
// while the API layer speaks nullable dose/duration. One mapping keeps the
// two representations from drifting apart.
type EditorRxItem = { name: string; dose: string; duration: string };

function toEditorItems(items: RxItemView[]): EditorRxItem[] {
  return items.map((i) => ({
    name: i.name,
    dose: i.dose ?? "",
    duration: i.duration ?? "",
  }));
}

function stageDisplayName(
  stage: CareCaseStage,
  t: Dictionary["doctorConsole"],
): string {
  switch (stage) {
    case "pre_summary":
      return t.stagePreSummary;
    case "prescription_pending":
      return t.stagePrescriptionPending;
    case "closed":
      return t.stageClosed;
    default:
      return stage;
  }
}

function rxStatusDisplayName(
  status: PrescriptionDetailView["status"],
  t: Dictionary["caseWorkspace"],
): string {
  switch (status) {
    case "draft":
      return t.rxStatusDraft;
    case "doctor_reviewed":
      return t.rxStatusReviewed;
    case "rejected":
      return t.rxStatusRejected;
    case "issued":
      return t.rxStatusIssued;
    case "fulfilled":
      return t.rxStatusFulfilled;
    default:
      return status;
  }
}

function formatDateTime(iso: string, lang: "en" | "hi"): string {
  return new Intl.DateTimeFormat(lang === "hi" ? "hi-IN" : "en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(iso));
}

function LoadingSkeleton() {
  return (
    <div className="space-y-3" data-testid="case-skeleton">
      {Array.from({ length: 2 }).map((_, i) => (
        <div
          key={i}
          className="rounded-lg border border-hairline bg-surface p-4"
        >
          <div className="h-4 w-1/2 rounded bg-muted-soft" />
          <div className="mt-2 h-3 w-1/4 rounded bg-muted-soft" />
        </div>
      ))}
    </div>
  );
}

export default function CaseWorkspacePage({
  params,
}: {
  params: { caseId: string };
}) {
  const caseId = Number(params.caseId);
  const { lang } = useLang();
  const t = STRINGS[lang].caseWorkspace;
  const consoleT = STRINGS[lang].doctorConsole;

  const [loadStatus, setLoadStatus] = useState<"loading" | "ready" | "error">(
    "loading",
  );
  const [errorTraceId, setErrorTraceId] = useState<string | undefined>();
  const [bannerOpen, setBannerOpen] = useState(false);

  const [careCase, setCareCase] = useState<CaseDetailView | null>(null);
  const [doctorMe, setDoctorMe] = useState<PartnerMeView | null>(null);

  const [handshaking, setHandshaking] = useState(false);
  const [handshakeError, setHandshakeError] = useState(false);
  const [handshakeDone, setHandshakeDone] = useState(false);

  // Prescription drafting state (US-18).
  const [rxLoadState, setRxLoadState] = useState<
    "loading" | "ready" | "empty" | "error"
  >("loading");
  const [workingRx, setWorkingRx] = useState<PrescriptionDetailView | null>(
    null,
  );
  const [rxItems, setRxItems] = useState<EditorRxItem[]>([]);
  const [drafting, setDrafting] = useState(false);
  const [draftError, setDraftError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);

  // Issuance + closure state (US-19..22, #453). The approve request is only
  // ever sent once the doctor ticks the verification declaration; rejection
  // carries a plain-language reason; close-without-prescription ends the case.
  const [approving, setApproving] = useState(false);
  const [approveError, setApproveError] = useState(false);
  const [declaration, setDeclaration] = useState(false);
  const [rejecting, setRejecting] = useState(false);
  const [rejectError, setRejectError] = useState(false);
  const [rejectReason, setRejectReason] = useState("");
  const [closing, setClosing] = useState(false);
  const [closeError, setCloseError] = useState(false);
  const [closeReason, setCloseReason] = useState<CloseReason | "">("");

  function resetDecisionState() {
    setDeclaration(false);
    setRejectReason("");
  }

  // Load the doctor's in-progress working revision for a pending case. This
  // is the refresh-reload seam: a hard refresh lands back here and the editor
  // is repopulated from the working-rx read, never from the immutable draft
  // snapshot (backend delta 5). A CARE_NOT_FOUND read means no draft yet.
  const loadWorkingRx = useCallback(async () => {
    setRxLoadState("loading");
    setDraftError(null);
    resetDecisionState();
    try {
      const rx = await fetchWorkingPrescription(caseId);
      setWorkingRx(rx);
      setRxItems(toEditorItems(rx.items));
      setRxLoadState("ready");
    } catch (err) {
      if (err instanceof ApiError && err.code === "CARE_NOT_FOUND") {
        setRxLoadState("empty");
      } else {
        setRxLoadState("error");
      }
    }
  }, [caseId]);

  const load = useCallback(() => {
    setLoadStatus("loading");
    setBannerOpen(false);
    setHandshakeError(false);

    Promise.all([fetchCareCase(caseId), fetchPartnerMe()])
      .then(([c, me]) => {
        setCareCase(c);
        setDoctorMe(me);
        setLoadStatus("ready");
        if (c.stage === "prescription_pending") {
          void loadWorkingRx();
        }
      })
      .catch((err: unknown) => {
        setErrorTraceId(err instanceof ApiError ? err.traceId : undefined);
        setLoadStatus("error");
        setBannerOpen(true);
      });
  }, [caseId, loadWorkingRx]);

  useEffect(() => {
    load();
  }, [load]);

  async function handleHandshake(e: FormEvent) {
    e.preventDefault();
    if (!careCase) return;
    setHandshaking(true);
    setHandshakeError(false);
    try {
      const result = await markConsultComplete(careCase.case_id);
      setCareCase(result);
      setHandshakeDone(true);
      void loadWorkingRx();
    } catch {
      setHandshakeError(true);
    } finally {
      setHandshaking(false);
    }
  }

  async function handleRequestDraft() {
    if (!careCase) return;
    setDrafting(true);
    setDraftError(null);
    resetDecisionState();
    try {
      const rx = await createRxDraft(careCase.case_id, {
        source: "ai_draft",
      });
      setWorkingRx(rx);
      setRxItems(toEditorItems(rx.items));
      setRxLoadState("ready");
    } catch (err) {
      // The backend enforces the drafting cap; surface it in-language so the
      // UX explains why a new AI draft is refused.
      setDraftError(
        err instanceof ApiError &&
          err.code === "ILLEGAL_PRESCRIPTION_TRANSITION"
          ? t.draftCapReached
          : t.requestDraftFail,
      );
    } finally {
      setDrafting(false);
    }
  }

  async function handleSaveRevision(e: FormEvent) {
    e.preventDefault();
    if (!careCase || !workingRx) return;
    const items: RxItemInput[] = rxItems
      .map((r) => ({
        name: r.name.trim(),
        dose: r.dose.trim() || null,
        duration: r.duration.trim() || null,
      }))
      .filter((r) => r.name !== "");
    setSaving(true);
    setSaveError(false);
    setSaveSuccess(false);
    resetDecisionState();
    try {
      const rx = await saveRxRevision(
        careCase.case_id,
        workingRx.prescription_id,
        { rx_items: items },
      );
      setWorkingRx(rx);
      setRxItems(toEditorItems(rx.items));
      setSaveSuccess(true);
    } catch {
      setSaveError(true);
    } finally {
      setSaving(false);
    }
  }

  // Approval never fires without the verification declaration: the UI keeps
  // the declare-then-approve sequence and only sends the request once the
  // checkbox is true (mirrors the backend's declaration gate - #453). The
  // issued prescription renders from the approve response so the doctor sees
  // exactly what the patient receives after issuance.
  async function handleApprove() {
    if (!careCase || !workingRx || !declaration) return;
    setApproving(true);
    setApproveError(false);
    try {
      const rx = await approvePrescription(
        careCase.case_id,
        workingRx.prescription_id,
      );
      setWorkingRx(rx);
      resetDecisionState();
    } catch {
      setApproveError(true);
    } finally {
      setApproving(false);
    }
  }

  // Rejection records a plain-language reason for the patient; the draft is
  // never approved and the case stays open for a new draft or a close.
  async function handleReject(e: FormEvent) {
    e.preventDefault();
    if (!careCase || !workingRx) return;
    const reason = rejectReason.trim();
    if (reason === "") return;
    setRejecting(true);
    setRejectError(false);
    try {
      const rx = await rejectPrescription(
        careCase.case_id,
        workingRx.prescription_id,
        { reason },
      );
      setWorkingRx(rx);
    } catch {
      setRejectError(true);
    } finally {
      setRejecting(false);
    }
  }

  // Close-without-prescription is the doctor's deliberate terminal action:
  // it moves the case to Closed (recorded with a reason) so it leaves the
  // pending list, per the close-without-prescription glossary term.
  async function handleClose(e: FormEvent) {
    e.preventDefault();
    if (!careCase || closeReason === "") return;
    setClosing(true);
    setCloseError(false);
    try {
      const updated = await closeCaseWithoutRx(careCase.case_id, {
        close_reason: closeReason,
      });
      setCareCase(updated);
    } catch {
      setCloseError(true);
    } finally {
      setClosing(false);
    }
  }

  function updateRxItem(
    index: number,
    field: "name" | "dose" | "duration",
    value: string,
  ) {
    setRxItems((prev) =>
      prev.map((row, i) => (i === index ? { ...row, [field]: value } : row)),
    );
    setSaveSuccess(false);
  }

  function addRxItem() {
    setRxItems((prev) => [...prev, { name: "", dose: "", duration: "" }]);
    setSaveSuccess(false);
  }

  function removeRxItem(index: number) {
    setRxItems((prev) =>
      prev.length <= 1 ? prev : prev.filter((_, i) => i !== index),
    );
    setSaveSuccess(false);
  }

  const sourceDisplayName = (source: PrescriptionDetailView["source"]) =>
    source === "ai_draft" ? t.sourceAiDraft : t.sourceManual;

  const isReady = loadStatus === "ready" && careCase !== null;
  const currentStage = careCase?.stage ?? "pre_summary";
  const isPreSummaryStage = currentStage === "pre_summary";
  const isPrescriptionPending =
    currentStage === "prescription_pending" ||
    (handshakeDone && currentStage !== "closed");
  const showHandshake = isPreSummaryStage && !handshakeDone;

  const rxStatus = workingRx?.status;
  const isReviewableRx = rxStatus === "draft" || rxStatus === "doctor_reviewed";
  const isIssuedRx = rxStatus === "issued" || rxStatus === "fulfilled";
  const isRejectedRx = rxStatus === "rejected";

  const closeReasons: Array<{ value: CloseReason; label: string }> = [
    { value: "patient_withdrawn", label: t.closeReasons.patientWithdrawn },
    { value: "doctor_rejected", label: t.closeReasons.doctorRejected },
    { value: "no_show", label: t.closeReasons.noShow },
    { value: "duplicate", label: t.closeReasons.duplicate },
  ];

  return (
    <>
      <Link
        href="/doctor"
        className="mb-4 inline-flex items-center gap-1 text-sm text-accent hover:underline"
        data-testid="back-to-console"
      >
        <span aria-hidden="true">&larr;</span> {t.backToConsole}
      </Link>

      <PageHeader
        title={t.title}
        description={careCase ? consoleT.caseItemMeta(caseId) : undefined}
      />

      {loadStatus === "error" && bannerOpen && (
        <ErrorBanner
          message={t.loadFailed}
          traceId={errorTraceId}
          onRetry={load}
          onDismiss={() => setBannerOpen(false)}
        />
      )}

      {loadStatus === "loading" && <LoadingSkeleton />}

      {isReady && (
        <div className="space-y-6" data-testid="case-content">
          {/* Stage + forced-review requirement */}
          <section
            className="rounded-lg border border-hairline bg-bg p-4"
            data-testid="case-stage"
          >
            <div className="flex items-center gap-3">
              <span
                className="text-xs font-medium text-txt-muted"
                data-testid="stage-label"
              >
                {t.stageLabel}
              </span>
              <span
                data-testid="stage-chip"
                className={cn(
                  "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium",
                  currentStage === "pre_summary"
                    ? "bg-warning-soft text-warning-text"
                    : "bg-accent-soft text-accent-strong",
                )}
              >
                {stageDisplayName(currentStage, consoleT)}
              </span>
            </div>

            {careCase.forced_review && (
              <div
                className="mt-3 rounded-md border border-warning/30 bg-warning-soft/40 px-3 py-2"
                data-testid="forced-review-banner"
              >
                <span className="inline-flex items-center gap-1 text-xs font-semibold text-warning-text">
                  {t.forcedReviewChip}
                </span>
                <p className="mt-1 text-xs text-txt-muted">
                  {t.forcedReviewDetail}
                </p>
              </div>
            )}
          </section>

          {/* Consented history */}
          {doctorMe != null && (
            <section
              className="rounded-lg border border-border bg-bg p-4"
              data-testid="case-history"
            >
              <h2 className="text-sm font-semibold text-txt">
                {t.historyHeading}
              </h2>
              <p className="mt-1 text-xs text-txt-muted">
                {t.historyConsentNote}
              </p>
              <div className="mt-3">
                <ConsentedHistory
                  patientId={careCase.patient_id}
                  partnerId={doctorMe.partner_id}
                />
              </div>
            </section>
          )}

          {/* Handshake action - pre_summary stage only */}
          {showHandshake && (
            <section
              className="rounded-lg border border-hairline bg-bg p-4"
              data-testid="case-handshake"
            >
              <form onSubmit={handleHandshake}>
                <p className="text-xs text-txt-muted">{t.handshakeHelp}</p>
                <Button
                  type="submit"
                  size="sm"
                  disabled={handshaking}
                  loading={handshaking}
                  className="mt-2"
                  data-testid="handshake-action"
                >
                  {t.handshakeAction}
                </Button>
                {handshakeError && (
                  <p className="mt-1 text-sm text-danger" role="alert">
                    {t.handshakeFail}
                  </p>
                )}
              </form>
            </section>
          )}

          {/* Handshake success / prescription-pending state */}
          {isPrescriptionPending && (
            <div
              className="rounded-md bg-success-soft/30 px-3 py-3 text-sm text-success"
              data-testid="handshake-success"
            >
              <p>{t.handshakeSuccess}</p>
              <p className="mt-1 text-xs text-txt-muted">
                {t.prescriptionPendingCta}
              </p>
            </div>
          )}

          {/* Prescription drafting (US-18) - pending cases only */}
          {isPrescriptionPending && careCase != null && (
            <section
              className="rounded-lg border border-border bg-bg p-4"
              data-testid="case-prescription"
            >
              <h2 className="text-sm font-semibold text-txt">
                {t.prescriptionHeading}
              </h2>
              <p className="mt-1 text-xs text-txt-muted">
                {t.prescriptionHelp}
              </p>

              <div className="mt-3">
                {rxLoadState === "loading" && (
                  <div className="space-y-2" data-testid="prescription-loading">
                    <div className="h-4 w-1/3 rounded bg-muted-soft" />
                    <div className="h-4 w-1/2 rounded bg-muted-soft" />
                  </div>
                )}

                {rxLoadState === "error" && (
                  <div
                    className="flex items-center gap-3"
                    data-testid="prescription-load-error"
                  >
                    <p className="text-xs text-txt-muted">
                      {t.workingRxLoadFail}
                    </p>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => void loadWorkingRx()}
                      data-testid="prescription-load-retry"
                    >
                      {t.retry}
                    </Button>
                  </div>
                )}

                {rxLoadState === "empty" && (
                  <div data-testid="prescription-empty">
                    <p className="text-xs text-txt-muted">{t.noDraftYet}</p>
                    <Button
                      type="button"
                      size="sm"
                      className="mt-2"
                      disabled={drafting}
                      loading={drafting}
                      onClick={() => void handleRequestDraft()}
                      data-testid="request-draft-action"
                    >
                      {drafting ? t.requestingDraft : t.requestDraftAction}
                    </Button>
                    {draftError && (
                      <p
                        className="mt-2 text-sm text-danger"
                        role="alert"
                        data-testid="draft-error"
                      >
                        {draftError}
                      </p>
                    )}
                  </div>
                )}

                {rxLoadState === "ready" && workingRx != null && (
                  <div className="mt-3" data-testid="prescription-review">
                    <div className="flex items-center gap-4">
                      <span className="text-xs font-medium text-txt-muted">
                        {t.sourceLabel}:{" "}
                        <span className="text-txt" data-testid="rx-source">
                          {sourceDisplayName(workingRx.source)}
                        </span>
                      </span>
                      <span className="text-xs font-medium text-txt-muted">
                        {t.rxStatusLabel}:{" "}
                        <span className="text-txt" data-testid="rx-status">
                          {rxStatusDisplayName(workingRx.status, t)}
                        </span>
                      </span>
                    </div>

                    {/* Editor - drafting/reviewed states only, rejected rows
                        are not editable (#452/#453). */}
                    {isReviewableRx && (
                      <form
                        onSubmit={handleSaveRevision}
                        className="mt-3"
                        data-testid="prescription-editor"
                      >
                        <span className="text-xs font-medium text-txt-muted">
                          {t.rxItemsLabel}
                        </span>
                        {rxItems.length === 0 ? (
                          <p className="mt-1 text-xs text-txt-muted">
                            {t.rxEmptyItems}
                          </p>
                        ) : (
                          <ul className="mt-2 space-y-2">
                            {rxItems.map((row, idx) => (
                              <li
                                key={idx}
                                className="flex flex-wrap items-center gap-2"
                                data-testid="rx-item-row"
                              >
                                <label className="flex-1 min-w-40">
                                  <span className="sr-only">
                                    {t.rxNameLabel}: {idx + 1}
                                  </span>
                                  <input
                                    type="text"
                                    value={row.name}
                                    onChange={(e) =>
                                      updateRxItem(idx, "name", e.target.value)
                                    }
                                    placeholder={t.rxNameLabel}
                                    className="h-9 w-full rounded-md border border-hairline bg-surface px-3 text-sm text-txt focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
                                    data-testid={`rx-item-name-${idx}`}
                                  />
                                </label>
                                <label className="flex-1 min-w-28">
                                  <span className="sr-only">
                                    {t.rxDoseLabel}: {idx + 1}
                                  </span>
                                  <input
                                    type="text"
                                    value={row.dose}
                                    onChange={(e) =>
                                      updateRxItem(idx, "dose", e.target.value)
                                    }
                                    placeholder={t.rxDoseLabel}
                                    className="h-9 w-full rounded-md border border-hairline bg-surface px-3 text-sm text-txt focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
                                    data-testid={`rx-item-dose-${idx}`}
                                  />
                                </label>
                                <label className="flex-1 min-w-28">
                                  <span className="sr-only">
                                    {t.rxDurationLabel}: {idx + 1}
                                  </span>
                                  <input
                                    type="text"
                                    value={row.duration}
                                    onChange={(e) =>
                                      updateRxItem(
                                        idx,
                                        "duration",
                                        e.target.value,
                                      )
                                    }
                                    placeholder={t.rxDurationLabel}
                                    className="h-9 w-full rounded-md border border-hairline bg-surface px-3 text-sm text-txt focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
                                    data-testid={`rx-item-duration-${idx}`}
                                  />
                                </label>
                                <Button
                                  type="button"
                                  size="sm"
                                  variant="ghost"
                                  disabled={rxItems.length <= 1}
                                  onClick={() => removeRxItem(idx)}
                                  data-testid={`rx-item-remove-${idx}`}
                                >
                                  {t.removeItemAction}
                                </Button>
                              </li>
                            ))}
                          </ul>
                        )}

                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          className="mt-2"
                          onClick={addRxItem}
                          data-testid="add-rx-item"
                        >
                          {t.addItemAction}
                        </Button>

                        <div className="mt-4 flex items-center gap-3">
                          <Button
                            type="submit"
                            size="sm"
                            disabled={saving}
                            loading={saving}
                            data-testid="save-revision-action"
                          >
                            {saving ? t.savingRevision : t.saveRevisionAction}
                          </Button>
                          {saveSuccess && (
                            <p
                              className="text-sm text-success"
                              data-testid="revision-saved"
                            >
                              {t.revisionSaved}
                            </p>
                          )}
                          {saveError && (
                            <p
                              className="text-sm text-danger"
                              role="alert"
                              data-testid="revision-save-error"
                            >
                              {t.saveRevisionFail}
                            </p>
                          )}
                        </div>
                      </form>
                    )}

                    {/* Issued e-prescription after approval (US-20) - rendered
                        from the approve response so the doctor sees what the
                        patient receives. */}
                    {isIssuedRx && (
                      <div
                        className="mt-3 rounded-md border border-hairline bg-surface p-3"
                        data-testid="issued-rx"
                      >
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <h3 className="text-sm font-semibold text-success">
                            {t.issuedHeading}
                          </h3>
                          {workingRx.issued_at != null && (
                            <span
                              className="text-xs text-txt-muted"
                              data-testid="issued-at"
                            >
                              {t.issuedAtLabel}:{" "}
                              {formatDateTime(workingRx.issued_at, lang)}
                            </span>
                          )}
                        </div>
                        <p className="mt-1 text-xs text-txt-muted">
                          {t.issuedImmutableNote}
                        </p>
                        <ul className="mt-2 space-y-1">
                          {workingRx.items.map((item) => (
                            <li
                              key={item.rx_item_id}
                              className="text-sm text-txt"
                              data-testid="issued-rx-item"
                            >
                              {item.name}
                              {item.dose != null ? ` - ${item.dose}` : ""}
                              {item.duration != null
                                ? ` - ${item.duration}`
                                : ""}
                            </li>
                          ))}
                        </ul>
                        <p
                          className="mt-2 text-xs text-txt-muted"
                          data-testid="issued-attribution"
                        >
                          {t.issuedAttributedTo}
                        </p>
                      </div>
                    )}

                    {/* Rejected-draft state (US-21): reason recorded for the
                        patient, case stays open for a re-draft or a close. */}
                    {isRejectedRx && (
                      <div
                        className="mt-3 rounded-md border border-warning/30 bg-warning-soft/40 p-3"
                        data-testid="rx-rejected"
                      >
                        <h3 className="text-sm font-semibold text-warning-text">
                          {t.rejectedHeading}
                        </h3>
                        <p className="mt-1 text-xs text-txt-muted">
                          {t.rejectedHelp}
                        </p>
                        {rejectReason !== "" && (
                          <p
                            className="mt-2 text-xs text-txt-muted"
                            data-testid="recorded-reason"
                          >
                            {t.rejectedReasonLabel}: {rejectReason}
                          </p>
                        )}
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          className="mt-2"
                          disabled={drafting}
                          loading={drafting}
                          onClick={() => void handleRequestDraft()}
                          data-testid="reject-redraft-action"
                        >
                          {drafting ? t.requestingDraft : t.requestDraftAction}
                        </Button>
                      </div>
                    )}

                    {/* Doctor decision (US-19..21): approve gated on the
                        verification declaration, plus reject-with-reason. */}
                    {isReviewableRx && (
                      <div
                        className="mt-4 rounded-md border border-hairline bg-surface p-3"
                        data-testid="review-decision"
                      >
                        <h3 className="text-sm font-semibold text-txt">
                          {t.decisionHeading}
                        </h3>

                        <div className="mt-2" data-testid="approval-gate">
                          <p className="text-xs text-txt-muted">
                            {t.approvalGateTitle}. {t.approvalGateHelp}
                          </p>
                          <label className="mt-2 flex items-start gap-2 text-sm text-txt">
                            <input
                              type="checkbox"
                              checked={declaration}
                              onChange={(e) => setDeclaration(e.target.checked)}
                              className="mt-0.5 h-4 w-4"
                              data-testid="verification-declaration"
                            />
                            <span>{t.verificationDeclaration}</span>
                          </label>
                          {!declaration && (
                            <p
                              className="mt-1 text-xs text-txt-muted"
                              data-testid="approve-blocked-help"
                            >
                              {t.approveBlockedHelp}
                            </p>
                          )}
                          <Button
                            type="button"
                            size="sm"
                            className="mt-2"
                            disabled={!declaration}
                            loading={approving}
                            onClick={() => void handleApprove()}
                            data-testid="approve-issue-action"
                          >
                            {approving
                              ? t.approvingIssuance
                              : t.approveIssueAction}
                          </Button>
                          {approveError && (
                            <p
                              className="mt-1 text-sm text-danger"
                              role="alert"
                              data-testid="approve-error"
                            >
                              {t.approveFail}
                            </p>
                          )}
                        </div>

                        <form onSubmit={handleReject} className="mt-4">
                          <label
                            htmlFor="reject-reason"
                            className="block text-xs font-medium text-txt-muted"
                          >
                            {t.rejectReasonLabel}
                          </label>
                          <textarea
                            id="reject-reason"
                            value={rejectReason}
                            onChange={(e) => setRejectReason(e.target.value)}
                            rows={2}
                            placeholder={t.rejectReasonPlaceholder}
                            className="mt-1 w-full rounded-md border border-hairline bg-bg px-3 py-2 text-sm text-txt focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
                            data-testid="reject-reason"
                          />
                          <Button
                            type="submit"
                            size="sm"
                            variant="outline"
                            className="mt-2"
                            disabled={rejecting || rejectReason.trim() === ""}
                            loading={rejecting}
                            data-testid="reject-action"
                          >
                            {rejecting ? t.rejectingDraft : t.rejectAction}
                          </Button>
                          {rejectError && (
                            <p
                              className="mt-1 text-sm text-danger"
                              role="alert"
                              data-testid="reject-error"
                            >
                              {t.rejectFail}
                            </p>
                          )}
                        </form>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </section>
          )}

          {/* Close-without-prescription (US-22) - pending cases only */}
          {isPrescriptionPending && careCase != null && (
            <section
              className="rounded-lg border border-hairline bg-bg p-4"
              data-testid="case-close"
            >
              <h2 className="text-sm font-semibold text-txt">
                {t.closeWithoutRxHeading}
              </h2>
              <p className="mt-1 text-xs text-txt-muted">
                {t.closeWithoutRxHelp}
              </p>
              <form
                onSubmit={handleClose}
                className="mt-3 flex flex-wrap items-end gap-3"
              >
                <label className="flex-1 min-w-48">
                  <span className="sr-only">{t.closeReasonLabel}</span>
                  <select
                    value={closeReason}
                    onChange={(e) =>
                      setCloseReason(e.target.value as CloseReason | "")
                    }
                    className="h-9 w-full rounded-md border border-hairline bg-surface px-3 text-sm text-txt focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
                    data-testid="close-reason-input"
                  >
                    <option value="">{t.closeReasonLabel}</option>
                    {closeReasons.map(({ value, label }) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                </label>
                <Button
                  type="submit"
                  size="sm"
                  variant="destructive"
                  disabled={closing || closeReason === ""}
                  loading={closing}
                  data-testid="close-case-action"
                >
                  {closing ? t.closingCase : t.closeCaseAction}
                </Button>
                {closeError && (
                  <p
                    className="w-full text-sm text-danger"
                    role="alert"
                    data-testid="close-error"
                  >
                    {t.closeFail}
                  </p>
                )}
              </form>
            </section>
          )}

          {/* Closed state */}
          {currentStage === "closed" && (
            <div
              className="rounded-md bg-muted-soft px-3 py-3 text-sm text-txt-muted"
              data-testid="closed-state"
            >
              <p>{consoleT.stageClosed}</p>
            </div>
          )}
        </div>
      )}
    </>
  );
}
