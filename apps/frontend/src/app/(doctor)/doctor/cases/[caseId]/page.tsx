"use client";

// PHASE-8.1 T13/T14/T15 (#451/#452/#453): case workspace for the open-cases
// entry path. The console's "Open cases" deep-links to /doctor/cases/[caseId]
// (one per active care case). This page shows the case stage, the forced-
// review requirement (if any), and splits the workspace into three inner tabs
// (US-14, #484): Pre-summary - the original intake transcript + recording
// playback plus the finalized AI summary and the consult-complete handshake
// for pre_summary-stage cases; History - the patient's consented health
// history; Prescription - the drafting/approval/close flow, gated by a stage
// lock that names the pending consult-complete step on pre_summary cases and
// jumps the doctor back to the handshake on the Pre-summary tab. For
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

import type { ChangeEvent, FormEvent, KeyboardEvent } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { ConsentedHistory } from "@/components/case/ConsentedHistory";
import { ErrorBanner } from "@/components/layout/ErrorBanner";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button, buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { ApiError } from "@/lib/api-errors";
import {
  fetchIntakeDetailForDoctor,
  fetchIntakeMediaBlob,
  fetchPreSummaryForReview,
  uploadDoctorMedia,
  type IntakeDetailView,
  type MediaRefView,
  type PreSummaryView,
} from "@/lib/intake/api";
import {
  approvePrescription,
  closeCaseWithoutRx,
  createRxDraft,
  fetchCareCase,
  fetchWorkingPrescription,
  markConsultComplete,
  rejectPrescription,
  saveRxRevision,
  submitDoctorInput,
  type CareCaseStage,
  type CaseDetailView,
  type CloseReason,
  type DoctorInputType,
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
type EditorRxItem = {
  name: string;
  dose: string;
  duration: string;
  frequency: string;
};

function toEditorItems(items: RxItemView[]): EditorRxItem[] {
  return items.map((i) => ({
    name: i.name,
    dose: i.dose ?? "",
    duration: i.duration ?? "",
    frequency: i.frequency ?? "",
  }));
}

function snapshotField(value: unknown): unknown {
  return value === undefined ? null : value;
}

/** Client mirror of ``modules/care.rx_facade._derive_edited_yn`` (audit-
    transparent, #494): the number of working items whose name/dose/duration/
    frequency differ from the immutable AI-draft snapshot, compared
    positionally like the approval-time audit. Missing snapshot fields are
    read as null so legacy pre-frequency snapshots stay comparable; a manual
    prescription (empty snapshot) reads as all items edited. The comparison
    is symmetric - a snapshot item the doctor deleted counts as edited too,
    so the tracker reads 0 only when the approval-time audit would derive
    ``edited_yn = false``. */
function countEditedRxItems(
  draftSnapshot: Record<string, unknown>,
  items: RxItemView[],
): number {
  const snapshotItems = Array.isArray(draftSnapshot.rx_items)
    ? (draftSnapshot.rx_items as Array<Record<string, unknown>>)
    : [];
  const length = Math.max(snapshotItems.length, items.length);
  let edited = 0;
  for (let idx = 0; idx < length; idx += 1) {
    const base = snapshotItems[idx];
    const issued = items[idx];
    const differs =
      base == null ||
      issued == null ||
      snapshotField(base.name) !== snapshotField(issued.name) ||
      snapshotField(base.dose) !== snapshotField(issued.dose) ||
      snapshotField(base.duration) !== snapshotField(issued.duration) ||
      snapshotField(base.frequency) !== snapshotField(issued.frequency);
    if (differs) edited += 1;
  }
  return edited;
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

function confidencePercent(value: number | null): string {
  if (value == null) return "-";
  return `${Math.round(value * 100)}%`;
}

function reviewStateDisplayName(
  state: string,
  t: Dictionary["caseWorkspace"],
): string {
  switch (state) {
    case "draft":
      return t.reviewStateDraft;
    case "reviewed":
      return t.reviewStateReviewed;
    case "final":
      return t.reviewStateFinal;
    default:
      return state;
  }
}

function formatDurationMs(ms: number | null): string {
  if (ms == null || ms < 0) return "";
  const totalSeconds = Math.round(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}

// The recording to play is always the most recent record attempt (#484).
function pickLatestMediaRef(
  mediaRefs: readonly MediaRefView[],
): MediaRefView | null {
  return mediaRefs.length === 0
    ? null
    : mediaRefs.reduce((a, b) =>
        b.record_attempt >= a.record_attempt ? b : a,
      );
}

// Workspace inner tabs (US-14, #484). Follows the prototype's tab pattern:
// role=tablist/tab/tabpanel, aria-selected, roving tabIndex, and arrow-key
// rotation so the tabs behave like a native tab control (keyboard
// navigation, screen-reader panel association).
type WorkspaceTab = "pre_summary" | "history" | "prescription";

const WORKSPACE_TABS: WorkspaceTab[] = [
  "pre_summary",
  "history",
  "prescription",
];

function WorkspaceTabs({
  active,
  onChange,
  t,
}: {
  active: WorkspaceTab;
  onChange: (tab: WorkspaceTab) => void;
  t: Dictionary["caseWorkspace"];
}) {
  const labels: Record<WorkspaceTab, string> = {
    pre_summary: t.tabPreSummary,
    history: t.tabHistory,
    prescription: t.tabPrescription,
  };

  function handleKeyDown(
    e: KeyboardEvent<HTMLButtonElement>,
    tab: WorkspaceTab,
  ) {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    e.preventDefault();
    const idx = WORKSPACE_TABS.indexOf(tab);
    const dir = e.key === "ArrowRight" ? 1 : -1;
    const next =
      WORKSPACE_TABS[
        (idx + dir + WORKSPACE_TABS.length) % WORKSPACE_TABS.length
      ];
    onChange(next);
  }

  return (
    <div
      role="tablist"
      aria-label={t.title}
      className="flex gap-1 border-b border-hairline"
      data-testid="workspace-tabs"
    >
      {WORKSPACE_TABS.map((tab) => {
        const selected = active === tab;
        return (
          <button
            key={tab}
            type="button"
            role="tab"
            data-tab={tab}
            id={`case-tab-${tab}`}
            aria-controls={`case-tabpanel-${tab}`}
            aria-selected={selected}
            tabIndex={selected ? 0 : -1}
            onClick={() => onChange(tab)}
            onKeyDown={(e) => handleKeyDown(e, tab)}
            className={cn(
              "flex-1 rounded-t-md border-b-2 px-3 py-2 text-sm font-medium transition-colors focus:outline-none focus:ring-1 focus:ring-accent",
              selected
                ? "border-accent text-accent-strong"
                : "border-transparent text-txt-muted hover:text-txt",
            )}
          >
            {labels[tab]}
          </button>
        );
      })}
    </div>
  );
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

export default function CaseWorkspacePage() {
  const params = useParams<{ caseId: string }>();
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

  // Workspace inner tabs (US-14, #484). A prescription-pending case opens on
  // the Prescription tab so the doctor lands where the work is; everything
  // else opens on the Pre-summary tab.
  const [activeTab, setActiveTab] = useState<WorkspaceTab>("pre_summary");

  // Pre-summary tab content (#484): the original intake transcript + audio
  // plus the finalized AI summary, all scoped to the assigned doctor.
  const [intakeDetail, setIntakeDetail] = useState<IntakeDetailView | null>(
    null,
  );
  const [preSummaryForReview, setPreSummaryForReview] =
    useState<PreSummaryView | null>(null);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [audioError, setAudioError] = useState(false);
  // Distinct from audioError: a failed doctor-side intake read is surfaced as
  // a load failure rather than being painted as "no transcript available".
  const [intakeDetailLoadFailed, setIntakeDetailLoadFailed] = useState(false);

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

  // Doctor-input capture (PHASE-8.1 T6, #490): an AI draft is only enabled
  // once the doctor has attached at least one voice note / photo / typed
  // addendum (the backend refuses AI drafts without a doctor-input row, so
  // the gate mirrors the seam). `manualMode` toggles the "type prescription
  // yourself" authoring flow before any working revision exists: creating a
  // manual draft with the doctor's own items is load-bearing for ADR-0015.
  const [hasDoctorInput, setHasDoctorInput] = useState(false);
  const [inputBusy, setInputBusy] = useState(false);
  const [inputError, setInputError] = useState<string | null>(null);
  const [addendumText, setAddendumText] = useState("");
  const [manualMode, setManualMode] = useState(false);

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

  // Load the pre-summary tab content (#484): the intake's original transcript
  // + media refs (doctor-scoped read keyed by the care case's pre-summary id),
  // then the finalized AI summary for the same intake. Both are best-effort -
  // a failure leaves the tab's empty/error states rather than failing the
  // whole workspace (the core care-case load already succeeded).
  const loadIntakeDetail = useCallback(async (preSummaryId: number) => {
    setIntakeDetail(null);
    setIntakeDetailLoadFailed(false);
    setPreSummaryForReview(null);
    setAudioUrl(null);
    setAudioError(false);
    try {
      const detail = await fetchIntakeDetailForDoctor(preSummaryId);
      setIntakeDetail(detail);
      try {
        const pre = await fetchPreSummaryForReview(detail.intake_id);
        setPreSummaryForReview(pre);
      } catch {
        setPreSummaryForReview(null);
      }
    } catch {
      setIntakeDetail(null);
      setIntakeDetailLoadFailed(true);
    }
  }, []);

  const load = useCallback(() => {
    setLoadStatus("loading");
    setBannerOpen(false);
    setHandshakeError(false);

    Promise.all([fetchCareCase(caseId), fetchPartnerMe()])
      .then(([c, me]) => {
        setCareCase(c);
        setDoctorMe(me);
        setLoadStatus("ready");
        // Open a born case (pre_summary) on the pre-summary tab; a
        // prescription-pending case on the prescription tab.
        setActiveTab(
          c.stage === "prescription_pending" ? "prescription" : "pre_summary",
        );
        if (c.pre_summary_id != null) {
          void loadIntakeDetail(c.pre_summary_id);
        }
        if (c.stage === "prescription_pending") {
          void loadWorkingRx();
        }
      })
      .catch((err: unknown) => {
        setErrorTraceId(err instanceof ApiError ? err.traceId : undefined);
        setLoadStatus("error");
        setBannerOpen(true);
      });
  }, [caseId, loadWorkingRx, loadIntakeDetail]);

  useEffect(() => {
    load();
  }, [load]);

  // Fetch the intake recording bytes as a blob (the media stream is not JSON
  // and the audio element cannot carry the Bearer header itself, so the blob
  // is fetched through authedFetch and presented via an object URL). Always
  // plays the latest record attempt. The object URL is revoked on teardown or
  // reload so a stale URL is never left alive after phoning to another intake.
  useEffect(() => {
    const detail = intakeDetail;
    const latest = pickLatestMediaRef(detail?.media_refs ?? []);
    if (detail == null || latest == null) {
      setAudioUrl(null);
      return;
    }
    let cancelled = false;
    let objectUrl: string | null = null;
    setAudioError(false);
    void fetchIntakeMediaBlob(detail.intake_id, latest.media_ref_id)
      .then((blob) => {
        if (cancelled) return;
        if (typeof URL.createObjectURL !== "function") {
          setAudioError(true);
          return;
        }
        objectUrl = URL.createObjectURL(blob);
        setAudioUrl(objectUrl);
      })
      .catch(() => {
        if (!cancelled) setAudioError(true);
      });
    return () => {
      cancelled = true;
      if (objectUrl != null && typeof URL.revokeObjectURL === "function") {
        URL.revokeObjectURL(objectUrl);
      }
      setAudioUrl(null);
    };
  }, [intakeDetail]);

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

  // Map the backend's distinct AI-draft refusals (#487) to specific in-language
  // messages; anything unrecognized keeps the catch-all as final fallback so a
  // confusing failure is never just re-wrapped in the generic copy.
  function draftFailureMessage(err: unknown): string {
    if (err instanceof ApiError) {
      switch (err.code) {
        case "CARE_RX_CONSENT_DENIED":
          return t.draftConsentDenied;
        case "CARE_RX_NO_DOCTOR_INPUT":
          return t.draftNoDoctorInput;
        case "CARE_RX_DRAFT_CAP_REACHED":
        case "ILLEGAL_PRESCRIPTION_TRANSITION":
          return t.draftCapReached;
        case "CARE_CASE_CLOSED":
          return t.draftCaseClosed;
        case "CARE_NOT_FOUND":
          return t.draftCaseNotFound;
        default:
          return t.requestDraftFail;
      }
    }
    return t.requestDraftFail;
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
      setManualMode(false);
      setRxLoadState("ready");
    } catch (err) {
      setDraftError(draftFailureMessage(err));
    } finally {
      setDrafting(false);
    }
  }

  async function handleSaveRevision(e: FormEvent) {
    e.preventDefault();
    if (!careCase) return;
    const items: RxItemInput[] = rxItems
      .map((r) => ({
        name: r.name.trim(),
        dose: r.dose.trim() || null,
        duration: r.duration.trim() || null,
        frequency: r.frequency.trim() || null,
      }))
      .filter((r) => r.name !== "");
    setSaving(true);
    setSaveError(false);
    setSaveSuccess(false);
    resetDecisionState();
    try {
      if (workingRx == null) {
        // Manual authoring before any working revision (ADR-0015): the doctor
        // writes the prescription themselves, so no consent or doctor input
        // is needed - the create call carries `source=manual` with the items.
        const rx = await createRxDraft(careCase.case_id, {
          source: "manual",
          items,
        });
        setWorkingRx(rx);
        setRxItems(toEditorItems(rx.items));
        setManualMode(false);
      } else {
        const rx = await saveRxRevision(
          careCase.case_id,
          workingRx.prescription_id,
          { rx_items: items },
        );
        setWorkingRx(rx);
        setRxItems(toEditorItems(rx.items));
      }
      setSaveSuccess(true);
    } catch {
      setSaveError(true);
    } finally {
      setSaving(false);
    }
  }

  // Voice note / photo capture: upload the bytes through the doctor media
  // route (rx_input prefix, #481) and attach the opaque media ticket to the
  // case as a doctor input, then the AI-draft gate opens.
  async function handleCapture(
    e: ChangeEvent<HTMLInputElement>,
    inputType: DoctorInputType,
  ) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!careCase || !file) return;
    setInputBusy(true);
    setInputError(null);
    try {
      const mediaRef = await uploadDoctorMedia(file, {
        filename: file.name,
        fileSizeBytes: file.size,
      });
      await submitDoctorInput(careCase.case_id, {
        input_type: inputType,
        media_ref: mediaRef.object_key,
      });
      setHasDoctorInput(true);
    } catch {
      setInputError(t.doctorInputFail);
    } finally {
      setInputBusy(false);
    }
  }

  // Typed addendum: the doctor's written note is persisted the same way as a
  // voice/photo input (the doctor media route stores the bytes durably under
  // `rx_input/` and answers the opaque media ticket), then the ticket rides
  // the existing doctor-input seam as its `media_ref`.
  async function handleAddendum(e: FormEvent) {
    e.preventDefault();
    const note = addendumText.trim();
    if (!careCase || note === "") return;
    setInputBusy(true);
    setInputError(null);
    try {
      const blob = new Blob([note], { type: "text/plain" });
      const mediaRef = await uploadDoctorMedia(blob, {
        filename: "addendum.txt",
      });
      await submitDoctorInput(careCase.case_id, {
        input_type: "voice",
        media_ref: mediaRef.object_key,
      });
      setAddendumText("");
      setHasDoctorInput(true);
    } catch {
      setInputError(t.doctorInputFail);
    } finally {
      setInputBusy(false);
    }
  }

  function handleStartManual() {
    setRxItems([{ name: "", dose: "", duration: "", frequency: "" }]);
    setDraftError(null);
    setSaveError(false);
    setSaveSuccess(false);
    setManualMode(true);
    setRxLoadState("ready");
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
    field: "name" | "dose" | "duration" | "frequency",
    value: string,
  ) {
    setRxItems((prev) =>
      prev.map((row, i) => (i === index ? { ...row, [field]: value } : row)),
    );
    setSaveSuccess(false);
  }

  function addRxItem() {
    setRxItems((prev) => [
      ...prev,
      { name: "", dose: "", duration: "", frequency: "" },
    ]);
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
  // Each state flag carries the null guard so TypeScript narrows `workingRx`
  // wherever the flag gates a section (the ready block now also hosts manual
  // authoring, where no working revision exists yet).
  const isReviewableRx =
    workingRx != null &&
    (rxStatus === "draft" || rxStatus === "doctor_reviewed");
  const isIssuedRx =
    workingRx != null && (rxStatus === "issued" || rxStatus === "fulfilled");
  const isRejectedRx = workingRx != null && rxStatus === "rejected";
  // Manual authoring edits before any working revision exists (ADR-0015
  // "an AI outage never strands a patient's visit"): the editor renders with
  // an empty row set and the create call carries `source=manual`.
  const isManualAuthoring = manualMode && workingRx == null;

  const closeReasons: Array<{ value: CloseReason; label: string }> = [
    { value: "patient_withdrawn", label: t.closeReasons.patientWithdrawn },
    { value: "doctor_rejected", label: t.closeReasons.doctorRejected },
    { value: "no_show", label: t.closeReasons.noShow },
    { value: "duplicate", label: t.closeReasons.duplicate },
  ];

  // Pre-summary tab derived values (#484): the transcript text (voice
  // transcription with forced-text fallback), the latest recording attempt,
  // and its formatted duration caption.
  const mediaRefs = intakeDetail?.media_refs ?? [];
  const latestMedia = pickLatestMediaRef(mediaRefs);
  const transcriptText = (
    intakeDetail?.transcript ??
    intakeDetail?.text ??
    ""
  ).trim();
  const audioDuration =
    latestMedia != null ? formatDurationMs(latestMedia.audio_duration_ms) : "";

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

          {/* Workspace inner tabs (US-14, #484): Pre-summary / History /
              Prescription. The stage stays pinned above the tabs; below them
              the active tab owns the panel (ARIA tablist pattern). */}
          <WorkspaceTabs active={activeTab} onChange={setActiveTab} t={t} />

          {/* ---- Pre-summary tab ---- */}
          <section
            role="tabpanel"
            id="case-tabpanel-pre_summary"
            aria-labelledby="case-tab-pre_summary"
            hidden={activeTab !== "pre_summary"}
            className="space-y-6"
            data-testid="tab-panel-pre-summary"
          >
            {/* Original intake transcript + recording playback (#484). The
                audio stream is not JSON and cannot carry the Bearer header on
                a bare <audio> element, so the clip is fetched as a blob and
                played through an object URL - latest record attempt wins. */}
            <section
              className="rounded-lg border border-border bg-bg p-4"
              data-testid="intake-transcript"
            >
              <h2 className="text-sm font-semibold text-txt">
                {t.transcriptHeading}
              </h2>
              {transcriptText !== "" ? (
                <p
                  className="mt-2 text-sm text-txt"
                  data-testid="transcript-text"
                >
                  {transcriptText}
                </p>
              ) : intakeDetailLoadFailed ? (
                <p
                  className="mt-2 text-sm text-danger"
                  role="alert"
                  data-testid="transcript-load-error"
                >
                  {t.transcriptLoadFail}
                </p>
              ) : (
                <p
                  className="mt-2 text-xs text-txt-muted"
                  data-testid="transcript-empty"
                >
                  {t.transcriptEmpty}
                </p>
              )}
              {latestMedia != null && (
                <div className="mt-3" data-testid="audio-playback">
                  <span className="text-xs font-medium text-txt-muted">
                    {t.audioPlayLabel}
                    {audioDuration !== "" ? ` \u00b7 ${audioDuration}` : ""}
                  </span>
                  {audioUrl != null && (
                    <audio
                      controls
                      src={audioUrl}
                      className="mt-1 w-full"
                      data-testid="audio-element"
                      preload="none"
                    />
                  )}
                  {audioError && (
                    <p
                      className="mt-1 text-sm text-danger"
                      role="alert"
                      data-testid="audio-load-error"
                    >
                      {t.audioLoadFail}
                    </p>
                  )}
                </div>
              )}
            </section>

            {/* Finalized AI summary for the assigned doctor (#484) - the
                structured summary the pre-summary stage produced. A born case
                always carries a final pre-summary, so no finalize action is
                offered here. */}
            {preSummaryForReview != null && (
              <section
                className="rounded-lg border border-border bg-bg p-4"
                data-testid="case-pre-summary"
              >
                <h2 className="text-sm font-semibold text-txt">
                  {t.summaryHeading}
                </h2>
                <div className="mt-3 space-y-3">
                  <div data-testid="case-pre-summary-complaints">
                    <span className="text-xs font-medium text-txt-muted">
                      {t.chiefComplaintsLabel}
                    </span>
                    <ul className="mt-1 list-disc pl-4">
                      {preSummaryForReview.structured_fields.chief_complaints.map(
                        (c) => (
                          <li key={c} className="text-sm text-txt">
                            {c}
                          </li>
                        ),
                      )}
                    </ul>
                  </div>
                  <div data-testid="case-pre-summary-symptoms">
                    <span className="text-xs font-medium text-txt-muted">
                      {t.symptomsLabel}
                    </span>
                    <ul className="mt-1 list-disc pl-4">
                      {preSummaryForReview.structured_fields.symptoms.map(
                        (s) => (
                          <li key={s} className="text-sm text-txt">
                            {s}
                          </li>
                        ),
                      )}
                    </ul>
                  </div>
                  <div data-testid="case-pre-summary-duration">
                    <span className="text-xs font-medium text-txt-muted">
                      {t.durationLabel}
                    </span>
                    <p className="text-sm text-txt">
                      {preSummaryForReview.structured_fields.duration ??
                        t.durationNotSet}
                    </p>
                  </div>
                  <div className="flex items-center gap-4">
                    <div data-testid="case-pre-summary-confidence">
                      <span className="text-xs font-medium text-txt-muted">
                        {t.confidenceLabel}
                      </span>
                      <span className="ml-1 text-sm text-txt">
                        {" "}
                        {confidencePercent(
                          preSummaryForReview.structuring_confidence,
                        )}
                      </span>
                    </div>
                    {preSummaryForReview.low_confidence && (
                      <span
                        data-testid="case-pre-summary-low-confidence"
                        className="inline-flex items-center rounded-full bg-warning-soft px-2 py-0.5 text-xs font-medium text-warning-text"
                      >
                        {consoleT.verifyChip}
                      </span>
                    )}
                  </div>
                  <div data-testid="case-pre-summary-patient-edits">
                    <span className="text-xs font-medium text-txt-muted">
                      {t.patientEditsLabel}
                    </span>
                    <p className="text-sm text-txt">
                      {Object.keys(preSummaryForReview.patient_edits ?? {})
                        .length > 0
                        ? Object.entries(
                            preSummaryForReview.patient_edits ?? {},
                          )
                            .map(([k, v]) => `${k}: ${v}`)
                            .join("; ")
                        : t.patientEditsNone}
                    </p>
                  </div>
                  <div data-testid="case-pre-summary-attribution">
                    <span className="text-xs font-medium text-txt-muted">
                      {t.attributionLabel}
                    </span>
                    <p className="text-sm text-txt">
                      {preSummaryForReview.review_attribution != null
                        ? preSummaryForReview.review_attribution
                        : t.notReviewedYet}
                    </p>
                  </div>
                  <div data-testid="case-pre-summary-review-state">
                    <span className="text-xs font-medium text-txt-muted">
                      {t.reviewStateLabel}
                    </span>
                    <span className="ml-1 text-sm text-txt">
                      {reviewStateDisplayName(
                        preSummaryForReview.review_state,
                        t,
                      )}
                    </span>
                    {preSummaryForReview.reviewed_at != null && (
                      <span className="ml-2 text-xs text-txt-muted">
                        ({t.reviewedOnLabel}:{" "}
                        {formatDateTime(preSummaryForReview.reviewed_at, lang)})
                      </span>
                    )}
                  </div>
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
          </section>

          {/* ---- History tab ---- */}
          <section
            role="tabpanel"
            id="case-tabpanel-history"
            aria-labelledby="case-tab-history"
            hidden={activeTab !== "history"}
            className="space-y-6"
            data-testid="tab-panel-history"
          >
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
          </section>

          {/* ---- Prescription tab ---- */}
          <section
            role="tabpanel"
            id="case-tabpanel-prescription"
            aria-labelledby="case-tab-prescription"
            hidden={activeTab !== "prescription"}
            className="space-y-6"
            data-testid="tab-panel-prescription"
          >
            {isPreSummaryStage && !handshakeDone ? (
              /* Stage lock (#484): a born case always has a finalized pre-
                  summary, so the only open step is the consult-complete
                  handshake. The action jumps the doctor to the Pre-summary
                  tab where the handshake form lives. */
              <section
                className="rounded-lg border border-warning/30 bg-warning-soft/40 p-4"
                data-testid="prescription-lock"
              >
                <h2 className="text-sm font-semibold text-warning-text">
                  {t.rxLockTitle}
                </h2>
                <ul className="mt-2 space-y-1 text-xs text-txt-muted">
                  <li data-testid="rx-lock-done">
                    <span aria-hidden="true">{"\u2713"}</span>{" "}
                    <span>{t.rxLockDone}</span>
                  </li>
                  <li data-testid="rx-lock-pending">
                    <span aria-hidden="true">{"\u2022"}</span>{" "}
                    <span>{t.rxLockPending}</span>
                  </li>
                </ul>
                <Button
                  type="button"
                  size="sm"
                  className="mt-3"
                  data-testid="rx-lock-action"
                  onClick={() => setActiveTab("pre_summary")}
                >
                  {t.rxLockAction}
                </Button>
              </section>
            ) : (
              <>
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
                        <div
                          className="space-y-2"
                          data-testid="prescription-loading"
                        >
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
                          <p className="text-xs text-txt-muted">
                            {t.noDraftYet}
                          </p>

                          {/* Doctor-input capture (PHASE-8.1 T6, #490): voice
                              note / photo / typed addendum all ride the doctor
                              media route (rx_input/) and post the opaque media
                              ticket to doctor-input, unlocking the AI draft. */}
                          <div
                            className="mt-3 space-y-2"
                            data-testid="rx-input-capture"
                          >
                            <p className="text-xs font-medium text-txt-muted">
                              {t.doctorInputHelp}
                            </p>
                            <div className="flex flex-wrap items-center gap-2">
                              <label
                                className={cn(
                                  "cursor-pointer",
                                  buttonVariants({
                                    variant: "outline",
                                    size: "sm",
                                  }),
                                )}
                              >
                                {t.voiceNoteAction}
                                <input
                                  type="file"
                                  accept="audio/*"
                                  className="sr-only"
                                  disabled={inputBusy}
                                  data-testid="rx-input-voice"
                                  onChange={(e) =>
                                    void handleCapture(e, "voice")
                                  }
                                />
                              </label>
                              <label
                                className={cn(
                                  "cursor-pointer",
                                  buttonVariants({
                                    variant: "outline",
                                    size: "sm",
                                  }),
                                )}
                              >
                                {t.photoAction}
                                <input
                                  type="file"
                                  accept="image/*"
                                  className="sr-only"
                                  disabled={inputBusy}
                                  data-testid="rx-input-photo"
                                  onChange={(e) =>
                                    void handleCapture(e, "photo")
                                  }
                                />
                              </label>
                              <span
                                className="text-xs text-txt-muted"
                                aria-hidden="true"
                              >
                                {inputBusy ? t.inputSubmitting : ""}
                              </span>
                            </div>

                            <form
                              onSubmit={handleAddendum}
                              className="flex flex-wrap items-start gap-2"
                            >
                              <label className="flex-1 min-w-48">
                                <span className="sr-only">
                                  {t.addendumLabel}
                                </span>
                                <textarea
                                  rows={2}
                                  value={addendumText}
                                  onChange={(e) =>
                                    setAddendumText(e.target.value)
                                  }
                                  placeholder={t.addendumPlaceholder}
                                  className="w-full rounded-md border border-hairline bg-bg px-3 py-2 text-sm text-txt focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
                                  data-testid="rx-input-addendum"
                                />
                              </label>
                              <Button
                                type="submit"
                                size="sm"
                                variant="outline"
                                disabled={
                                  inputBusy || addendumText.trim() === ""
                                }
                                loading={inputBusy}
                                data-testid="rx-input-addendum-submit"
                              >
                                {t.addendumSubmit}
                              </Button>
                            </form>

                            {inputError && (
                              <p
                                className="text-sm text-danger"
                                role="alert"
                                data-testid="rx-input-error"
                              >
                                {inputError}
                              </p>
                            )}
                            {hasDoctorInput && (
                              <p
                                className="text-xs text-success"
                                data-testid="rx-input-received"
                              >
                                {t.doctorInputReceived}
                              </p>
                            )}
                          </div>

                          <Button
                            type="button"
                            size="sm"
                            className="mt-3"
                            disabled={drafting || !hasDoctorInput}
                            loading={drafting}
                            onClick={() => void handleRequestDraft()}
                            data-testid="request-draft-action"
                          >
                            {drafting
                              ? t.requestingDraft
                              : t.requestDraftAction}
                          </Button>
                          {!hasDoctorInput && (
                            <p
                              className="mt-1 text-xs text-txt-muted"
                              data-testid="request-draft-blocked-help"
                            >
                              {t.requestDraftBlocked}
                            </p>
                          )}

                          <div className="mt-3 border-t border-hairline pt-3">
                            <p className="text-xs font-medium text-txt-muted">
                              {t.manualAuthoringHelp}
                            </p>
                            <Button
                              type="button"
                              size="sm"
                              variant="outline"
                              className="mt-2"
                              onClick={handleStartManual}
                              data-testid="manual-authoring-action"
                            >
                              {t.manualAuthoringAction}
                            </Button>
                          </div>

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

                      {rxLoadState === "ready" &&
                        (workingRx != null || isManualAuthoring) && (
                          <div
                            className="mt-3"
                            data-testid="prescription-review"
                          >
                            {workingRx != null && (
                              <div className="flex items-center gap-4">
                                <span className="text-xs font-medium text-txt-muted">
                                  {t.sourceLabel}:{" "}
                                  <span
                                    className="text-txt"
                                    data-testid="rx-source"
                                  >
                                    {sourceDisplayName(workingRx.source)}
                                  </span>
                                </span>
                                <span className="text-xs font-medium text-txt-muted">
                                  {t.rxStatusLabel}:{" "}
                                  <span
                                    className="text-txt"
                                    data-testid="rx-status"
                                  >
                                    {rxStatusDisplayName(workingRx.status, t)}
                                  </span>
                                </span>
                              </div>
                            )}

                            {/* Editor - drafting/reviewed states plus manual
                              authoring before a working revision exists
                              (#490); rejected rows are not editable
                              (#452/#453). */}
                            {(isReviewableRx || isManualAuthoring) && (
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
                                              updateRxItem(
                                                idx,
                                                "name",
                                                e.target.value,
                                              )
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
                                              updateRxItem(
                                                idx,
                                                "dose",
                                                e.target.value,
                                              )
                                            }
                                            placeholder={t.rxDoseLabel}
                                            className="h-9 w-full rounded-md border border-hairline bg-surface px-3 text-sm text-txt focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
                                            data-testid={`rx-item-dose-${idx}`}
                                          />
                                        </label>
                                        <label className="flex-1 min-w-28">
                                          <span className="sr-only">
                                            {t.rxFrequencyLabel}: {idx + 1}
                                          </span>
                                          <input
                                            type="text"
                                            value={row.frequency}
                                            onChange={(e) =>
                                              updateRxItem(
                                                idx,
                                                "frequency",
                                                e.target.value,
                                              )
                                            }
                                            placeholder={t.rxFrequencyLabel}
                                            className="h-9 w-full rounded-md border border-hairline bg-surface px-3 text-sm text-txt focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
                                            data-testid={`rx-item-frequency-${idx}`}
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
                                    {saving
                                      ? t.savingRevision
                                      : t.saveRevisionAction}
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

                            {/* Issued e-prescription after approval (US-20) -
                              rendered from the approve response so the doctor
                              sees what the patient receives. */}
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
                                      {formatDateTime(
                                        workingRx.issued_at,
                                        lang,
                                      )}
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
                                      {item.dose != null
                                        ? ` - ${item.dose}`
                                        : ""}
                                      {item.frequency != null
                                        ? ` - ${item.frequency}`
                                        : ""}
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
                                  {workingRx.attributed_doctor_name?.trim() ||
                                    t.issuedAttributedTo}
                                </p>
                              </div>
                            )}

                            {/* Rejected-draft state (US-21): reason recorded for
                              the patient, case stays open for a re-draft or a
                              close. */}
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
                                  {drafting
                                    ? t.requestingDraft
                                    : t.requestDraftAction}
                                </Button>
                              </div>
                            )}

                            {/* Doctor decision (US-19..21): approve gated on the
                              verification declaration, plus reject-with-
                              reason. */}
                            {isReviewableRx && (
                              <div
                                className="mt-4 rounded-md border border-hairline bg-surface p-3"
                                data-testid="review-decision"
                              >
                                <h3 className="text-sm font-semibold text-txt">
                                  {t.decisionHeading}
                                </h3>

                                {/* Edited-items tracker (#494): display-only
                                  summary counting working items that differ
                                  from the immutable AI-draft snapshot, so the
                                  doctor sees what the approval-time audit
                                  will derive before issuing. */}
                                <p
                                  className="mt-1 text-xs font-medium text-txt-muted"
                                  data-testid="edited-tracker"
                                >
                                  {t.editedTracker(
                                    countEditedRxItems(
                                      workingRx.draft_snapshot,
                                      workingRx.items,
                                    ),
                                  )}
                                </p>

                                <div
                                  className="mt-2"
                                  data-testid="approval-gate"
                                >
                                  <p className="text-xs text-txt-muted">
                                    {t.approvalGateTitle}. {t.approvalGateHelp}
                                  </p>
                                  <label className="mt-2 flex items-start gap-2 text-sm text-txt">
                                    <input
                                      type="checkbox"
                                      checked={declaration}
                                      onChange={(e) =>
                                        setDeclaration(e.target.checked)
                                      }
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
                                    onChange={(e) =>
                                      setRejectReason(e.target.value)
                                    }
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
                                    disabled={
                                      rejecting || rejectReason.trim() === ""
                                    }
                                    loading={rejecting}
                                    data-testid="reject-action"
                                  >
                                    {rejecting
                                      ? t.rejectingDraft
                                      : t.rejectAction}
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
              </>
            )}
          </section>
        </div>
      )}
    </>
  );
}
