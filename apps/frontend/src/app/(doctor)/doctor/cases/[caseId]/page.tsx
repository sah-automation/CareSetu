"use client";

// PHASE-8.1 T13/T14/T15 (#451/#452/#453): case workspace for the open-cases
// entry path. The console's "Open cases" deep-links to /doctor/cases/[caseId]
// (one per active care case). This page shows the case stage, the forced-
// review requirement (if any), and splits the workspace into three inner tabs
// (US-14, #484): Pre-summary - the original intake transcript + recording
// playback plus the finalized AI summary and the consult-complete handshake
// for pre_summary-stage cases; History - the patient's consented consultation
// history plus the shared health background (#682), both fed by one console
// detail projection read; Prescription - the drafting/approval/close flow,
// gated by a stage
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
import { useCallback, useEffect, useRef, useState } from "react";

import { ConsentedHistory } from "@/components/case/ConsentedHistory";
import { HealthBackgroundBlock } from "@/components/doctor/HealthBackgroundBlock";
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
import {
  fetchDoctorPatientDetail,
  type DoctorPatientDetailView,
} from "@/lib/doctor/api";
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

// #657: the three instruction fields the editor refuses to issue unreadable.
// A value that is ONLY digits, decimals and whitespace is a bare number with
// no unit ("9", "0.5", "9 3 3") and is refused at save time; "9 mg",
// "2 tablets", "BD" and "9/3/3" all pass, because the rule is narrow on
// purpose - a validator that rejects "2 tablets" would reject real
// prescriptions. The medicine name is deliberately absent from this union:
// real product names carry numbers ("Zinc 20", "Vitamin D3 60k"), so a
// numeric rule on the name would refuse legitimate medicines. A refusal,
// never a rewrite: the pass only reports WHICH field and why it is
// unreadable; nothing is corrected on the doctor's behalf and no row is
// dropped. DOM order (dose, frequency, duration) so the focus walk reads the
// row the way the doctor sees it. The union is derived from the one list
// below, so a field can never be validated without also being declared there.
const RX_INSTRUCTION_FIELDS = ["dose", "frequency", "duration"] as const;
type RxItemField = (typeof RX_INSTRUCTION_FIELDS)[number];

interface RxItemProblem {
  row: number;
  field: RxItemField;
}

function invalidRxItemFields(items: EditorRxItem[]): RxItemProblem[] {
  const invalid: RxItemProblem[] = [];
  items.forEach((row, idx) => {
    for (const field of RX_INSTRUCTION_FIELDS) {
      const value = row[field].trim();
      if (value !== "" && /^[\d.\s]+$/.test(value)) {
        invalid.push({ row: idx, field });
      }
    }
  });
  return invalid;
}

/** The focus-walk / ref map key for one instruction field. */
function rxFieldKey(row: number, field: RxItemField): string {
  return `${row}:${field}`;
}

/** The id a refused input points at with `aria-describedby`. */
function rxErrorId(row: number, field: RxItemField): string {
  return `rx-item-${field}-error-${row}`;
}

/** The label and the bare-number message for one instruction field. */
function rxFieldCopy(
  t: Dictionary["caseWorkspace"],
  field: RxItemField,
): { label: string; message: string } {
  switch (field) {
    case "dose":
      return { label: t.rxDoseLabel, message: t.rxDoseBareNumber };
    case "frequency":
      return { label: t.rxFrequencyLabel, message: t.rxFrequencyBareNumber };
    case "duration":
      return { label: t.rxDurationLabel, message: t.rxDurationBareNumber };
  }
}

interface RxInstructionFieldProps {
  row: number;
  field: RxItemField;
  label: string;
  message: string;
  value: string;
  refused: boolean;
  onChange: (value: string) => void;
  inputRef: (el: HTMLInputElement | null) => void;
}

/** One instruction field of the rx-item editor (#657): a dose, frequency or
    duration input whose refusal message is wired to it via
    `aria-describedby`. Presentational and per-field rather than per-row, so
    the three fields cannot drift apart in their aria wiring. */
function RxInstructionField({
  row,
  field,
  label,
  message,
  value,
  refused,
  onChange,
  inputRef,
}: RxInstructionFieldProps) {
  const errorId = rxErrorId(row, field);
  return (
    <div className="flex-1 min-w-28">
      <label className="block">
        <span className="sr-only">
          {label}: {row + 1}
        </span>
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={label}
          aria-invalid={refused}
          aria-describedby={refused ? errorId : undefined}
          className="h-9 w-full rounded-md border border-hairline bg-surface px-3 text-sm text-txt focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
          ref={inputRef}
          data-testid={`rx-item-${field}-${row}`}
        />
      </label>
      {refused && (
        <p
          id={errorId}
          className="mt-1 text-xs text-danger"
          role="alert"
          data-testid={errorId}
        >
          {message}
        </p>
      )}
    </div>
  );
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

// Four-step case stepper (FEAT-008, PROTO-8 binding): Pre-Summary ->
// Consult Complete -> Rx Pending -> Issued. Visual-only progress tracker
// mirroring the prototype's .case-stepper; the active step is highlighted
// and completed steps show a check.
type CaseStep = "pre_summary" | "consult_complete" | "rx_pending" | "issued";

const CASE_STEPS: CaseStep[] = [
  "pre_summary",
  "consult_complete",
  "rx_pending",
  "issued",
];

function CaseStepper({
  currentStage,
  handshakeDone,
  t,
}: {
  currentStage: CareCaseStage;
  handshakeDone: boolean;
  t: Dictionary["caseWorkspace"];
}) {
  const stepStatus: Record<CaseStep, "pending" | "active" | "done"> = {
    pre_summary:
      currentStage === "pre_summary"
        ? "active"
        : currentStage === "prescription_pending" ||
            currentStage === "closed" ||
            handshakeDone
          ? "done"
          : "pending",
    consult_complete:
      currentStage === "pre_summary"
        ? "pending"
        : currentStage === "prescription_pending" ||
            currentStage === "closed" ||
            handshakeDone
          ? "done"
          : handshakeDone
            ? "active"
            : "pending",
    rx_pending:
      currentStage === "prescription_pending"
        ? "active"
        : currentStage === "closed"
          ? "done"
          : "pending",
    issued: currentStage === "closed" ? "done" : "pending",
  };

  const stepLabels: Record<CaseStep, string> = {
    pre_summary: t.tabPreSummary,
    consult_complete: t.consultCompleteStep,
    rx_pending: t.rxPendingStep,
    issued: t.issuedStep,
  };

  return (
    <div
      className="grid grid-cols-4 gap-1 mx-2 mb-4"
      data-testid="case-stepper"
      role="list"
      aria-label={t.caseProgressLabel}
    >
      {CASE_STEPS.map((step, idx) => {
        const status = stepStatus[step];
        const isLast = idx === CASE_STEPS.length - 1;
        return (
          <div
            key={step}
            className={cn(
              "flex flex-col items-center gap-1.5 relative",
              status === "active" && "text-accent-strong",
              status === "done" && "text-accent-strong",
            )}
            role="listitem"
            aria-current={status === "active" ? "step" : undefined}
          >
            <span
              className={cn(
                "flex h-8 w-8 items-center justify-center rounded-full text-xs font-bold border-2 transition-colors",
                status === "done"
                  ? "bg-accent-soft border-accent text-accent-strong"
                  : status === "active"
                    ? "bg-accent border-accent text-on-accent"
                    : "bg-surface border-hairline text-txt-muted",
              )}
              data-testid={`step-dot-${step}`}
            >
              {status === "done" ? (
                <svg
                  width="10"
                  height="10"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="3"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden="true"
                >
                  <path d="M20 6 9 17l-5-5" />
                </svg>
              ) : (
                idx + 1
              )}
            </span>
            <span
              className={cn(
                "text-[0.6875rem] font-semibold text-center leading-snug px-1",
                status === "active"
                  ? "text-accent-strong"
                  : status === "done"
                    ? "text-accent-strong"
                    : "text-txt-muted",
              )}
              data-testid={`step-label-${step}`}
            >
              {stepLabels[step]}
            </span>
            {!isLast && (
              <span
                className={cn(
                  "absolute top-[9px] left-1/2 w-full h-0.5 -z-10",
                  status === "done" ? "bg-accent" : "bg-hairline",
                )}
                aria-hidden="true"
              />
            )}
          </div>
        );
      })}
    </div>
  );
}

// Workspace inner tabs (US-14, #484). Follows the patient shell's tab
// pattern (PROTO-2.7 binding, shell-light.html `.tabs`): a clean underline
// indicator on the active tab, no hairline under the whole group. Role
// semantics remain: role=tablist/tab/tabpanel, aria-selected, roving
// tabIndex, and arrow-key rotation so the tabs behave like a native tab
// control (keyboard navigation, screen-reader panel association).
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
      className="flex gap-6 border-b border-hairline pb-px"
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
              "relative py-3 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent focus-visible:ring-offset-2 rounded-sm",
              selected ? "text-accent-strong" : "text-txt-muted hover:text-txt",
              selected &&
                "after:absolute after:bottom-[-1px] after:left-0 after:right-0 after:h-0.5 after:bg-accent",
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
    <div className="space-y-4" data-testid="case-skeleton">
      {Array.from({ length: 3 }).map((_, i) => (
        <div
          key={i}
          className="rounded-lg border border-hairline bg-surface p-4 animate-pulse"
        >
          <div className="h-5 w-1/3 rounded bg-hairline-soft" />
          <div className="mt-3 h-4 w-1/2 rounded bg-hairline-soft" />
          <div className="mt-2 h-3 w-1/4 rounded bg-hairline-soft" />
        </div>
      ))}
    </div>
  );
}

// #658 (one history read, #645 US-62) + #682 (parent #673): the console
// detail projection for the case patient - the very read the patient-detail
// page renders, so the two doctor surfaces cannot disagree. Widened in #682
// from the bare consultation history to the whole projection, because one
// settled read now feeds both History-tab sections (consultation history and
// health background) instead of only one. Best-effort by design: a failed
// projection read answers undefined instead of throwing, so the workspace
// still opens and the history tab keeps the consented-history component's
// own fail-closed consented read as its fallback. The degradation is logged
// (error-handling-observability: a denied read is a calm lock, a failed
// read is a logged warning - never a page failure).
async function readConsoleDetailProjection(
  patientId: number,
): Promise<DoctorPatientDetailView | undefined> {
  try {
    return await fetchDoctorPatientDetail(patientId);
  } catch (err) {
    console.warn(
      "[case-workspace] console detail projection read failed:",
      err,
    );
    return undefined;
  }
}

export default function CaseWorkspacePage() {
  const params = useParams<{ caseId: string }>();
  const caseId = Number(params.caseId);
  const { lang } = useLang();
  const t = STRINGS[lang].caseWorkspace;
  const consoleT = STRINGS[lang].doctorConsole;
  // #682: the health-background section reuses the doctorPatients label
  // bundle - the same copy the patient-detail page renders, and the same the
  // shared health-background block expects, so the two surfaces cannot drift
  // and no new dictionary block is forked (REQ-006 parity holds as-is).
  const patientsT = STRINGS[lang].doctorPatients;

  const [loadStatus, setLoadStatus] = useState<"loading" | "ready" | "error">(
    "loading",
  );
  const [errorTraceId, setErrorTraceId] = useState<string | undefined>();
  const [bannerOpen, setBannerOpen] = useState(false);

  const [careCase, setCareCase] = useState<CaseDetailView | null>(null);
  const [doctorMe, setDoctorMe] = useState<PartnerMeView | null>(null);

  // #658 (one history read, #645 US-62) + #682: the History tab renders the
  // console detail projection - the same read the patient-detail page
  // renders - rather than a second, separately scoped view of the same
  // patient. One settled projection feeds both sections: its
  // `consultation_history` (array / denied null / failed undefined) drives
  // ConsentedHistory's three-state contract, and its `health_background`
  // drives the medical-history block. The read is best-effort and never
  // gates the workspace: undefined means the projection read failed, leaving
  // the consented-history component to its fail-closed consented read as the
  // fallback and hiding the health-background section rather than claiming a
  // denial the patient never gave. The tab mounts the sections only once the
  // read has settled, so the components' contracts are never raced by a
  // live read.
  const [patientDetail, setPatientDetail] = useState<
    DoctorPatientDetailView | undefined
  >(undefined);
  const [detailLoadState, setDetailLoadState] = useState<
    "idle" | "loading" | "ready"
  >("idle");

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

  // #657: the bare-number refusal. Save is disabled while the pass reports
  // anything, so the refusal has to explain itself WITHOUT a submit - a
  // silent disabled button would tell a keyboard or screen-reader user
  // nothing about why (unlike the address card, whose enabled button can be
  // pressed to elicit the message). The message is therefore live: the pass
  // derives from `rxItems` every render, so a bare number names its field and
  // reason the moment it is typed and a usable value clears it at once. One
  // message per field means continuous typing does not re-announce.
  const invalidRxFields = invalidRxItemFields(rxItems);
  // The focus-walk targets, keyed `row:field`.
  const rxInputRefs = useRef<Record<string, HTMLInputElement | null>>({});

  /** The pass refuses this field right now, so its message shows. */
  function rxRefuses(row: number, field: RxItemField): boolean {
    return invalidRxFields.some(
      (problem) => problem.row === row && problem.field === field,
    );
  }

  // Issuance + closure state (US-19..22, #453). The approve request is only
  // ever sent once the doctor ticks both verification declarations; rejection
  // carries a plain-language reason; close-without-prescription ends the case.
  const [approving, setApproving] = useState(false);
  const [approveError, setApproveError] = useState(false);
  const [declaration, setDeclaration] = useState(false);
  const [confirmIssue, setConfirmIssue] = useState(false);
  const [rejecting, setRejecting] = useState(false);
  const [rejectError, setRejectError] = useState(false);
  const [rejectReason, setRejectReason] = useState("");
  const [closing, setClosing] = useState(false);
  const [closeError, setCloseError] = useState(false);
  const [closeReason, setCloseReason] = useState<CloseReason | "">("");

  function resetDecisionState() {
    setDeclaration(false);
    setConfirmIssue(false);
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

  // #658 + #682: the one projection source for both doctor surfaces. Best-
  // effort and fire-and-forget like the other side reads - a slow or failed
  // projection read must never hold the workspace open. The History tab
  // gates on `detailLoadState` settling before it mounts either section, so
  // a denied (null) or failed (undefined) answer is already the components'
  // settled prop and never a mid-flight race.
  const loadPatientDetail = useCallback(async (patientId: number) => {
    setDetailLoadState("loading");
    const detail = await readConsoleDetailProjection(patientId);
    setPatientDetail(detail);
    setDetailLoadState("ready");
  }, []);

  const load = useCallback(() => {
    setLoadStatus("loading");
    setBannerOpen(false);
    setHandshakeError(false);
    setPatientDetail(undefined);
    setDetailLoadState("idle");

    Promise.all([fetchCareCase(caseId), fetchPartnerMe()])
      .then(([c, me]) => {
        setCareCase(c);
        setDoctorMe(me);
        setLoadStatus("ready");
        // The AI-draft gate hydrates from the server: an input recorded on an
        // earlier session unlocks the draft button without a re-upload (#492
        // review fix - the capture surface was re-shown and the lock re-set on
        // any hard refresh of a PrescriptionPending case).
        setHasDoctorInput(c.has_doctor_input);
        // Open a born case (pre_summary) on the pre-summary tab; a
        // prescription-pending case on the prescription tab.
        setActiveTab(
          c.stage === "prescription_pending" ? "prescription" : "pre_summary",
        );
        // Best-effort side reads fire after ready so none of them gate the
        // workspace's availability.
        if (c.pre_summary_id != null) {
          void loadIntakeDetail(c.pre_summary_id);
        }
        if (c.stage === "prescription_pending") {
          void loadWorkingRx();
        }
        void loadPatientDetail(c.patient_id);
      })
      .catch((err: unknown) => {
        setErrorTraceId(err instanceof ApiError ? err.traceId : undefined);
        setLoadStatus("error");
        setBannerOpen(true);
      });
  }, [caseId, loadWorkingRx, loadIntakeDetail, loadPatientDetail]);

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
    // #657: the refusal. The save button is already disabled while the pass
    // reports a bare number, so this is the belt to that button's braces (an
    // implicit form submit). The refused messages are already on screen, so
    // the focus walk (ui-blueprint §9.4) simply lands the doctor on the first
    // refusal they can act on.
    if (invalidRxFields.length > 0) {
      const first = invalidRxFields[0];
      rxInputRefs.current[rxFieldKey(first.row, first.field)]?.focus();
      return;
    }
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
        input_type: "text",
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

      {isReady && (
        <CaseStepper
          currentStage={currentStage}
          handshakeDone={handshakeDone}
          t={t}
        />
      )}

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
            className="rounded-lg border border-hairline bg-surface p-4"
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
                  "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium",
                  currentStage === "pre_summary"
                    ? "bg-warn-soft text-warn-text"
                    : currentStage === "prescription_pending"
                      ? "bg-accent-soft text-accent-strong"
                      : "bg-hairline-soft text-txt-muted",
                )}
              >
                {stageDisplayName(currentStage, consoleT)}
              </span>
            </div>

            {careCase.forced_review && (
              <div
                className="mt-3 rounded-md border border-hairline bg-warn-soft px-3 py-2.5"
                data-testid="forced-review-banner"
              >
                <div className="flex items-start gap-2">
                  <svg
                    className="shrink-0 mt-0.5 text-warn-text"
                    width="16"
                    height="16"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    aria-hidden="true"
                  >
                    <circle cx="12" cy="12" r="10" />
                    <path d="M12 8v4M12 16h.01" />
                  </svg>
                  <div className="min-w-0 flex-1">
                    <span className="inline-flex items-center gap-1 text-xs font-semibold text-warn-text">
                      {t.forcedReviewChip}
                    </span>
                    <p className="mt-1 text-xs text-txt-muted">
                      {t.forcedReviewDetail}
                    </p>
                  </div>
                </div>
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
              className="rounded-lg border border-hairline bg-surface p-4"
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
                className="rounded-lg border border-hairline bg-surface p-4"
                data-testid="case-pre-summary"
              >
                <h2 className="text-sm font-semibold text-txt">
                  {t.summaryHeading}
                </h2>
                <div className="mt-3 space-y-3">
                  {/* Chief complaints - field group */}
                  <div
                    className="border-t border-hairline"
                    data-testid="case-pre-summary-complaints"
                  >
                    <div className="pt-3 pb-1.5 px-1 font-semibold text-xs text-txt-muted uppercase tracking-wider flex items-center gap-2">
                      {t.chiefComplaintsLabel}
                    </div>
                    {preSummaryForReview.structured_fields.chief_complaints
                      .length > 0 ? (
                      <ul className="space-y-1.5">
                        {preSummaryForReview.structured_fields.chief_complaints.map(
                          (c, idx) => (
                            <li
                              key={idx}
                              className="grid grid-cols-[140px_1fr] gap-3 text-sm"
                            >
                              <span className="text-txt-muted">#{idx + 1}</span>
                              <span className="font-medium text-txt">{c}</span>
                            </li>
                          ),
                        )}
                      </ul>
                    ) : (
                      <p className="text-sm text-txt-muted mt-1">
                        {t.durationNotSet}
                      </p>
                    )}
                  </div>

                  {/* Symptoms - field group */}
                  <div
                    className="border-t border-hairline"
                    data-testid="case-pre-summary-symptoms"
                  >
                    <div className="pt-3 pb-1.5 px-1 font-semibold text-xs text-txt-muted uppercase tracking-wider flex items-center gap-2">
                      {t.symptomsLabel}
                    </div>
                    {preSummaryForReview.structured_fields.symptoms.length >
                    0 ? (
                      <ul className="space-y-1.5">
                        {preSummaryForReview.structured_fields.symptoms.map(
                          (s, idx) => (
                            <li
                              key={idx}
                              className="grid grid-cols-[140px_1fr] gap-3 text-sm"
                            >
                              <span className="text-txt-muted">#{idx + 1}</span>
                              <span className="font-medium text-txt">{s}</span>
                            </li>
                          ),
                        )}
                      </ul>
                    ) : (
                      <p className="text-sm text-txt-muted mt-1">
                        {t.durationNotSet}
                      </p>
                    )}
                  </div>

                  {/* Duration - field group */}
                  <div
                    className="border-t border-hairline"
                    data-testid="case-pre-summary-duration"
                  >
                    <div className="pt-3 pb-1.5 px-1 font-semibold text-xs text-txt-muted uppercase tracking-wider flex items-center gap-2">
                      {t.durationLabel}
                    </div>
                    <div className="grid grid-cols-[140px_1fr] gap-3 text-sm">
                      <span className="text-txt-muted">{t.durationLabel}</span>
                      <span className="font-medium text-txt">
                        {preSummaryForReview.structured_fields.duration ??
                          t.durationNotSet}
                      </span>
                    </div>
                  </div>

                  {/* Confidence + review state - key/value row matching the
                      Duration and other field rows so the label-to-value
                      spacing lines up (#675). The verify chip stays in the
                      value cell next to the percentage. */}
                  <div
                    className="grid grid-cols-[140px_1fr] gap-3 text-sm"
                    data-testid="case-pre-summary-confidence"
                  >
                    <span className="text-txt-muted">{t.confidenceLabel}</span>
                    <span className="font-medium text-txt">
                      {confidencePercent(
                        preSummaryForReview.structuring_confidence,
                      )}
                      {preSummaryForReview.low_confidence && (
                        <span
                          data-testid="case-pre-summary-low-confidence"
                          className="ml-2 inline-flex items-center rounded-full bg-warn-soft px-2 py-0.5 text-xs font-medium text-warn-text"
                        >
                          {consoleT.verifyChip}
                        </span>
                      )}
                    </span>
                  </div>

                  {/* Patient edits - field group */}
                  <div
                    className="border-t border-hairline"
                    data-testid="case-pre-summary-patient-edits"
                  >
                    <div className="pt-3 pb-1.5 px-1 font-semibold text-xs text-txt-muted uppercase tracking-wider flex items-center gap-2">
                      {t.patientEditsLabel}
                    </div>
                    <div className="grid grid-cols-[140px_1fr] gap-3 text-sm">
                      <span className="text-txt-muted">
                        {t.patientEditsLabel}
                      </span>
                      <span className="font-medium text-txt">
                        {Object.keys(preSummaryForReview.patient_edits ?? {})
                          .length > 0
                          ? Object.entries(
                              preSummaryForReview.patient_edits ?? {},
                            )
                              .map(([k, v]) => `${k}: ${v}`)
                              .join("; ")
                          : t.patientEditsNone}
                      </span>
                    </div>
                  </div>

                  {/* Attribution - field group */}
                  <div
                    className="border-t border-hairline"
                    data-testid="case-pre-summary-attribution"
                  >
                    <div className="pt-3 pb-1.5 px-1 font-semibold text-xs text-txt-muted uppercase tracking-wider flex items-center gap-2">
                      {t.attributionLabel}
                    </div>
                    <div className="grid grid-cols-[140px_1fr] gap-3 text-sm">
                      <span className="text-txt-muted">
                        {t.attributionLabel}
                      </span>
                      <span className="font-medium text-txt">
                        {preSummaryForReview.review_attribution != null
                          ? preSummaryForReview.review_attribution
                          : t.notReviewedYet}
                      </span>
                    </div>
                  </div>

                  {/* Review state - field group */}
                  <div
                    className="border-t border-hairline"
                    data-testid="case-pre-summary-review-state"
                  >
                    <div className="pt-3 pb-1.5 px-1 font-semibold text-xs text-txt-muted uppercase tracking-wider flex items-center gap-2">
                      {t.reviewStateLabel}
                    </div>
                    <div className="grid grid-cols-[140px_1fr] gap-3 text-sm">
                      <span className="text-txt-muted">
                        {t.reviewStateLabel}
                      </span>
                      <span className="font-medium text-txt">
                        {reviewStateDisplayName(
                          preSummaryForReview.review_state,
                          t,
                        )}
                        {preSummaryForReview.reviewed_at != null && (
                          <>
                            {" "}
                            ({t.reviewedOnLabel}:{" "}
                            {formatDateTime(
                              preSummaryForReview.reviewed_at,
                              lang,
                            )}
                            )
                          </>
                        )}
                      </span>
                    </div>
                  </div>
                </div>
              </section>
            )}

            {/* Handshake action - pre_summary stage only */}
            {showHandshake && (
              <section
                className="rounded-lg border border-hairline bg-surface p-4"
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
                    <p className="mt-2 text-sm text-danger" role="alert">
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
            {/* Both cards mount only once the projection read has settled
                (#658/#682): each component's contract is fed a finished
                answer - array, denied null, or failed undefined - never a
                mid-flight read it would have to race. */}
            {doctorMe != null && detailLoadState === "ready" && (
              <>
                <section
                  className="rounded-lg border border-hairline bg-surface p-4"
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
                      timeline={patientDetail?.consultation_history}
                    />
                  </div>
                </section>
                {/* #682: the medical-history section rides the same settled
                    projection read - one read feeds both sections, so the
                    patient-detail page and this tab cannot disagree. The
                    section hides entirely when the projection read failed
                    (undefined): the workspace has no answer, and painting a
                    lock would claim a denial the patient never gave. A
                    settled null is the real not-shared, rendered by the
                    shared block as its calm locked card. */}
                {patientDetail !== undefined && (
                  <section
                    className="rounded-lg border border-hairline bg-surface p-4"
                    data-testid="case-health-background"
                  >
                    <h2 className="text-sm font-semibold text-txt">
                      {patientsT.healthBackgroundHeading}
                    </h2>
                    <p className="mt-1 text-xs text-txt-muted">
                      {t.historyConsentNote}
                    </p>
                    <div className="mt-3">
                      <HealthBackgroundBlock
                        healthBackground={patientDetail.health_background}
                        labels={patientsT}
                      />
                    </div>
                  </section>
                )}
              </>
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
              /* Stage lock (#484, PROTO-8 binding): a born case always has a
                  finalized pre-summary, so the only open step is the
                  consult-complete handshake. The lock names exactly what is
                  missing with one-tap jump to the relevant tab/action. */
              <section
                className="rounded-lg border border-dashed border-hairline bg-surface p-6 text-center"
                data-testid="prescription-lock"
              >
                <div
                  className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-hairline-soft text-txt-muted"
                  aria-hidden="true"
                >
                  <svg
                    width="24"
                    height="24"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.8"
                    strokeLinecap="round"
                  >
                    <rect x="4" y="11" width="16" height="10" rx="2" />
                    <path d="M8 11V7a4 4 0 0 1 8 0v4" />
                  </svg>
                </div>
                <h2 className="text-sm font-semibold text-txt">
                  {t.rxLockTitle}
                </h2>
                <p className="mt-1 text-xs text-txt-muted max-w-[34em] mx-auto">
                  {t.rxLockSubtitle}
                </p>
                <div className="mt-4 max-w-[30em] mx-auto space-y-2 text-left">
                  {/* Pre-summary finalized */}
                  <div
                    className={cn(
                      "flex items-center gap-3 rounded-lg border p-3 bg-surface",
                      handshakeDone ? "border-success" : "border-hairline",
                    )}
                    data-testid="rx-lock-presummary"
                  >
                    <span className="flex-1 text-sm text-txt-sub">
                      {t.rxLockPreSummary}
                    </span>
                    {!handshakeDone && (
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        className="shrink-0"
                        onClick={() => setActiveTab("pre_summary")}
                        data-testid="rx-lock-presummary-action"
                      >
                        {t.rxLockGoToSummary}
                      </Button>
                    )}
                    {handshakeDone && (
                      <span
                        className="shrink-0 text-sm font-semibold text-success"
                        aria-hidden="true"
                      >
                        {"\u2713"}
                      </span>
                    )}
                  </div>
                  {/* Consult marked complete */}
                  <div
                    className={cn(
                      "flex items-center gap-3 rounded-lg border p-3 bg-surface",
                      handshakeDone ? "border-success" : "border-hairline",
                    )}
                    data-testid="rx-lock-handshake"
                  >
                    <span className="flex-1 text-sm text-txt-sub">
                      {t.rxLockHandshake}
                    </span>
                    {!handshakeDone && (
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        className="shrink-0"
                        onClick={() => setActiveTab("pre_summary")}
                        data-testid="rx-lock-handshake-action"
                      >
                        {t.rxLockMarkComplete}
                      </Button>
                    )}
                    {handshakeDone && (
                      <span
                        className="shrink-0 text-sm font-semibold text-success"
                        aria-hidden="true"
                      >
                        {"\u2713"}
                      </span>
                    )}
                  </div>
                </div>
              </section>
            ) : (
              <>
                {/* Handshake success / prescription-pending state */}
                {isPrescriptionPending && (
                  <div
                    className="rounded-md bg-success-soft px-3 py-3 text-sm text-success-text"
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
                    className="rounded-lg border border-hairline bg-surface p-4"
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
                          <div className="h-4 w-1/3 rounded bg-hairline-soft animate-pulse" />
                          <div className="h-4 w-1/2 rounded bg-hairline-soft animate-pulse" />
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
                                  className="w-full rounded-md border border-hairline bg-surface px-3 py-2 text-sm text-txt focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
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
                                    {rxItems.map((row, idx) => {
                                      return (
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
                                          {/* The name is free text with no rule
                                              (#657): real product names carry
                                              digits. The three instruction
                                              fields each refuse a bare number
                                              through the shared field below. */}
                                          {RX_INSTRUCTION_FIELDS.map(
                                            (field) => {
                                              const copy = rxFieldCopy(
                                                t,
                                                field,
                                              );
                                              return (
                                                <RxInstructionField
                                                  key={field}
                                                  row={idx}
                                                  field={field}
                                                  label={copy.label}
                                                  message={copy.message}
                                                  value={row[field]}
                                                  refused={rxRefuses(
                                                    idx,
                                                    field,
                                                  )}
                                                  onChange={(value) =>
                                                    updateRxItem(
                                                      idx,
                                                      field,
                                                      value,
                                                    )
                                                  }
                                                  inputRef={(el) => {
                                                    rxInputRefs.current[
                                                      rxFieldKey(idx, field)
                                                    ] = el;
                                                  }}
                                                />
                                              );
                                            },
                                          )}
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
                                      );
                                    })}
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
                                    // #657: disabled while any row holds a
                                    // bare number, so an invalid revision is
                                    // never submitted - and never silently:
                                    // each refused field states why beside its
                                    // own input.
                                    disabled={
                                      saving || invalidRxFields.length > 0
                                    }
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
                                className="mt-3 rounded-md border border-hairline bg-warn-soft p-3"
                                data-testid="rx-rejected"
                              >
                                <h3 className="text-sm font-semibold text-warn-text">
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
                                  className="mt-2 space-y-4"
                                  data-testid="approval-gate"
                                >
                                  {/* Step 1: Review & approve */}
                                  <div
                                    className="rounded-lg border border-hairline bg-surface p-4"
                                    data-testid="confirm-step-1"
                                  >
                                    <h4 className="text-sm font-semibold text-txt">
                                      {t.approvalGateTitle}
                                    </h4>
                                    <p className="mt-1 text-xs text-txt-muted">
                                      {t.approvalGateHelp}
                                    </p>
                                    <label className="mt-3 flex items-start gap-2 text-sm text-txt cursor-pointer">
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
                                  </div>

                                  {/* Step 2: Confirm issue details - shown only after step 1 */}
                                  {declaration && (
                                    <div
                                      className="rounded-lg border border-hairline bg-surface p-4"
                                      data-testid="confirm-step-2"
                                    >
                                      <h4 className="text-sm font-semibold text-txt">
                                        {t.confirmIssueTitle}
                                      </h4>
                                      <p className="mt-1 text-xs text-txt-muted">
                                        {t.confirmIssueHelp}
                                      </p>
                                      <label className="mt-3 flex items-start gap-2 text-sm text-txt cursor-pointer">
                                        <input
                                          type="checkbox"
                                          checked={confirmIssue}
                                          onChange={(e) =>
                                            setConfirmIssue(e.target.checked)
                                          }
                                          className="mt-0.5 h-4 w-4"
                                          data-testid="confirm-issue-declaration"
                                        />
                                        <span>{t.confirmIssueDeclaration}</span>
                                      </label>
                                    </div>
                                  )}

                                  {!declaration && (
                                    <p
                                      className="text-xs text-txt-muted"
                                      data-testid="approve-blocked-help"
                                    >
                                      {t.approveBlockedHelp}
                                    </p>
                                  )}

                                  <Button
                                    type="button"
                                    size="sm"
                                    className="w-full"
                                    disabled={!declaration || !confirmIssue}
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
                                    className="mt-1 w-full rounded-md border border-hairline bg-surface px-3 py-2 text-sm text-txt focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
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
                    className="rounded-lg border border-hairline bg-surface p-4"
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
                    className="rounded-md bg-hairline-soft px-3 py-3 text-sm text-txt-muted"
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
