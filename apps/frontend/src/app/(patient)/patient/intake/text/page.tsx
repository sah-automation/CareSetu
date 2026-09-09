"use client";

// PHASE-7 T17 (#361): text intake page (blueprint §5.4, finalized
// PROTO-PHASE-7/8 intake-text.html is the binding copy spec). A prominent
// large textarea capped at 2000 characters in-page (the server caps too,
// T07/T12) with a bilingual hint that Hindi and English are both accepted.
// An optional voice-note attach rides alongside the text as a doctor-only
// audio artifact - stored for the doctor to listen to, never fed to the
// structuring pipeline, and strictly non-blocking: the note is never
// required and never gates the text submit (FEAT-006 Rule 2). The note
// uploads through the same NFR-PERF-002 retry ladder as the voice page so a
// flaky connection never silently loses a capture. Submit shows an in-button
// Structuring pending state per §9.1 (never a page spinner), then advances to
// the pre-summary review link once the intake reaches ready_for_review.

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Mic, Square, X } from "lucide-react";

import { ErrorBanner } from "@/components/layout/ErrorBanner";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api-errors";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import { fetchIntake, submitIntake, uploadIntakeMedia } from "@/lib/intake/api";
import {
  type RecorderSession,
  openMicrophoneRecorder,
} from "@/lib/intake/recorder";
import {
  INTAKE_POLL_INTERVAL_MS,
  MAX_INTAKE_POLLS,
  MAX_RECORD_MS,
  fmtDuration,
  uploadWithRetry,
} from "@/lib/intake/voice";

export const TEXT_INTAKE_CAP = 2000;

type NoteStage = "idle" | "recording" | "preview";
type SubmitStage = "idle" | "pending" | "done";
type ErrorKind = "mic" | "upload";

export default function TextIntakePage() {
  const { lang } = useLang();
  const dict = STRINGS[lang].intake;
  const nav = STRINGS[lang].nav;
  const t = dict.text;

  const [text, setText] = useState("");
  const [noteStage, setNoteStage] = useState<NoteStage>("idle");
  const [noteElapsed, setNoteElapsed] = useState(0);
  const [submitStage, setSubmitStage] = useState<SubmitStage>("idle");
  const [intakeId, setIntakeId] = useState<number | null>(null);
  const [structuringId, setStructuringId] = useState<number | null>(null);
  const [errorBanner, setErrorBanner] = useState<{
    title: string;
    body: string;
    traceId?: string;
  } | null>(null);
  const [errorKind, setErrorKind] = useState<ErrorKind | null>(null);

  const recorderRef = useRef<RecorderSession | null>(null);
  const captureRef = useRef<Blob | null>(null);
  const noteElapsedRef = useRef(0);

  const failWith = useCallback(
    (kind: ErrorKind, next: NoteStage, traceId?: string) => {
      setErrorBanner({
        title: kind === "mic" ? t.micUnavailableTitle : t.uploadErrorTitle,
        body: kind === "mic" ? t.micUnavailableBody : t.uploadErrorBody,
        traceId,
      });
      setErrorKind(kind);
      setNoteStage(next);
    },
    [t],
  );

  const handleAttach = useCallback(async () => {
    if (noteStage === "recording") {
      return;
    }
    try {
      const recorder = await openMicrophoneRecorder();
      recorderRef.current = recorder;
      recorder.start();
      noteElapsedRef.current = 0;
      setNoteElapsed(0);
      setErrorBanner(null);
      setErrorKind(null);
      setNoteStage("recording");
    } catch {
      failWith("mic", "idle");
    }
  }, [noteStage, failWith]);

  const handleStop = useCallback(async () => {
    const recorder = recorderRef.current;
    if (!recorder) return;
    try {
      captureRef.current = await recorder.stop();
    } catch {
      failWith("mic", "idle");
      return;
    } finally {
      recorder.close();
      recorderRef.current = null;
    }
    setNoteStage("preview");
  }, [failWith]);

  // Live duration while recording, hard-capped at the voice-page 180s so a
  // runaway take is never recorded indefinitely (auto-stop at the cap).
  useEffect(() => {
    if (noteStage !== "recording") {
      return;
    }
    const id = window.setInterval(() => {
      setNoteElapsed((prev) => {
        const next = Math.min(prev + 1, MAX_RECORD_MS / 1000);
        noteElapsedRef.current = next;
        return next;
      });
    }, 1000);
    return () => window.clearInterval(id);
  }, [noteStage]);

  useEffect(() => {
    if (noteStage === "recording" && noteElapsed >= MAX_RECORD_MS / 1000) {
      void handleStop();
    }
  }, [noteElapsed, noteStage, handleStop]);

  const handleRemoveNote = useCallback(() => {
    noteElapsedRef.current = 0;
    captureRef.current = null;
    setNoteStage("idle");
  }, []);

  const handleSubmit = useCallback(async () => {
    const content = text.trim();
    if (content.length === 0) {
      return;
    }
    setSubmitStage("pending");
    setErrorBanner(null);
    setErrorKind(null);
    setStructuringId(null);

    const blob = captureRef.current;
    try {
      // The voice note is doctor-only: it rides as an opaque media_ref,
      // stored for the doctor to listen to and never fed as text or into the
      // structuring pipeline. When no note was recorded, media_ref is omitted
      // entirely (one-mode-per-intake, text-only).
      const mediaRef = blob
        ? await uploadWithRetry(() =>
            uploadIntakeMedia(blob, {
              filename: "voice-note.webm",
              audioDurationMs: noteElapsedRef.current * 1000,
              fileSizeBytes: blob.size,
            }),
          )
        : undefined;
      const submitted = await submitIntake({
        mode: "text",
        language: lang,
        text: content,
        media_ref: mediaRef,
      });
      setIntakeId(submitted.intake_id);
      setStructuringId(submitted.intake_id);
    } catch (error) {
      // Upload or submit failed after the retry ladder: the text and any
      // recorded note stay in memory and the page returns to the form - the
      // patient never loses input and the note is never a blocker.
      setSubmitStage("idle");
      failWith(
        "upload",
        blob ? "preview" : "idle",
        error instanceof ApiError ? error.traceId : undefined,
      );
    }
  }, [text, lang, failWith]);

  // Poll the server detail while Structuring (in-button pending, §9.1):
  // ready_for_review -> done (pre-summary link), failed -> error with the
  // form preserved, any other status -> keep waiting. A slow pipeline
  // releases after MAX_INTAKE_POLLS so the flow never stalls here.
  useEffect(() => {
    if (submitStage !== "pending" || structuringId === null) {
      return;
    }
    let cancelled = false;
    let ticks = 0;
    const timer = window.setInterval(() => {
      ticks += 1;
      void (async () => {
        if (cancelled) {
          return;
        }
        try {
          const detail = await fetchIntake(structuringId);
          if (detail.status === "ready_for_review") {
            cancelled = true;
            window.clearInterval(timer);
            setSubmitStage("done");
          } else if (detail.status === "failed") {
            cancelled = true;
            window.clearInterval(timer);
            setSubmitStage("idle");
            failWith("upload", noteStage);
          } else if (ticks >= MAX_INTAKE_POLLS) {
            cancelled = true;
            window.clearInterval(timer);
            setSubmitStage("done");
          }
        } catch {
          if (ticks >= MAX_INTAKE_POLLS) {
            cancelled = true;
            window.clearInterval(timer);
            setSubmitStage("done");
          }
        }
      })();
    }, INTAKE_POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [submitStage, structuringId, failWith, noteStage]);

  const synopsisReady = submitStage === "idle";
  const canSubmit =
    synopsisReady && noteStage !== "recording" && text.trim().length > 0;

  return (
    <>
      <PageHeader
        title={t.title}
        description={t.reassure}
        breadcrumbs={[
          { label: nav.home, href: "/patient" },
          { label: dict.breadcrumb, href: "/patient/intake" },
          { label: t.breadcrumb },
        ]}
      />

      <div
        className="mx-auto flex max-w-xl flex-col gap-4 rounded-lg border border-hairline bg-surface p-6 shadow-card"
        data-testid="text-form"
      >
        {errorBanner && (
          <ErrorBanner
            message={
              <>
                <strong className="font-semibold">{errorBanner.title}</strong>
                <span className="block">{errorBanner.body}</span>
              </>
            }
            traceId={errorBanner.traceId}
            onRetry={() => {
              const kind = errorKind;
              setErrorBanner(null);
              setErrorKind(null);
              if (kind === "mic") {
                void handleAttach();
              } else {
                void handleSubmit();
              }
            }}
            onDismiss={() => {
              setErrorBanner(null);
              setErrorKind(null);
            }}
          />
        )}

        {/* Prominent textarea - first-class input, not a fallback (REQ-007
            Rule 2). The 2000-char cap is enforced in-page via maxLength and a
            live counter; the server also caps (T07/T12). */}
        <div className="flex flex-col gap-1.5">
          <textarea
            id="symptom-input"
            data-testid="textarea"
            value={text}
            onChange={(event) =>
              setText(event.target.value.slice(0, TEXT_INTAKE_CAP))
            }
            maxLength={TEXT_INTAKE_CAP}
            placeholder={t.placeholder}
            rows={6}
            disabled={submitStage === "pending"}
            aria-label={t.title}
            autoFocus
            className="min-h-[140px] w-full resize-y rounded-md border border-hairline bg-surface p-3.5 text-base leading-relaxed text-txt transition-[border-color,box-shadow] focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
          />
          <div className="flex items-center justify-between gap-2">
            <p className="inline-flex items-center gap-1.5 text-[0.8125rem] text-txt-muted">
              <svg
                width="14"
                height="14"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
                aria-hidden="true"
              >
                <circle cx="12" cy="12" r="10" />
                <path d="M12 16v-4M12 8h.01" />
              </svg>
              <span data-testid="lang-hint">{t.langHint}</span>
            </p>
            <output
              className="text-xs italic text-txt-muted tabular-nums"
              data-testid="char-count"
              aria-label={`${text.length} / ${TEXT_INTAKE_CAP}`}
            >
              {text.length} / {TEXT_INTAKE_CAP}
            </output>
          </div>
        </div>

        {/* Optional voice-note attach - doctor-only, strictly non-blocking
            (§5.4 REQ-007 Rule 2). Rendering an attach state machine of
            idle -> recording -> preview; the recorded note uploads with the
            text submit as an opaque media ref the doctor can listen to. */}
        <div data-testid="voice-attach-zone">
          <button
            type="button"
            data-testid="note-attach"
            onClick={() => void handleAttach()}
            disabled={submitStage === "pending"}
            aria-disabled={submitStage === "pending" || undefined}
            hidden={noteStage !== "idle"}
            className="flex w-full items-center gap-2.5 rounded-md border border-dashed border-hairline bg-hairline-soft/40 px-3.5 py-2.5 text-left transition-[border-color,background-color] hover:border-accent-border hover:bg-accent-soft disabled:pointer-events-none disabled:opacity-50"
          >
            <span className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-hairline-soft text-txt-sub">
              <Mic size={16} strokeWidth={1.8} aria-hidden="true" />
            </span>
            <span className="flex min-w-0 flex-1 flex-col gap-0.5">
              <strong className="text-sm font-semibold text-txt">
                {t.voiceAttach}
              </strong>
              <span className="text-xs text-txt-muted">
                {t.voiceAttachHint}
              </span>
            </span>
          </button>

          <div
            className="flex items-center gap-2 rounded-md bg-accent-soft px-3.5 py-2.5"
            data-testid="note-recording"
            hidden={noteStage !== "recording"}
          >
            <span className="h-2.5 w-2.5 shrink-0 rounded-full bg-danger animate-pulse" />
            <span className="flex-1 text-sm font-medium text-accent-strong">
              {t.voiceRecording}
            </span>
            <output
              className="text-sm font-semibold tabular-nums text-txt-sub"
              data-testid="note-rec-dur"
              aria-live="off"
            >
              {fmtDuration(noteElapsed)}
            </output>
            <Button
              type="button"
              size="sm"
              data-testid="note-stop"
              onClick={() => void handleStop()}
            >
              <Square size={14} className="mr-1.5" aria-hidden="true" />
              {t.voiceStop}
            </Button>
          </div>

          <div
            className="flex items-center gap-2 rounded-md bg-accent-soft px-3.5 py-2.5"
            data-testid="note-preview"
            hidden={noteStage !== "preview"}
          >
            <span className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-accent text-on-accent">
              <svg
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill="currentColor"
                aria-hidden="true"
              >
                <path d="M8 5v14l11-7z" />
              </svg>
            </span>
            <span className="flex-1 text-sm font-medium text-accent-strong">
              {t.voicePreview}
            </span>
            <button
              type="button"
              data-testid="note-remove"
              onClick={handleRemoveNote}
              disabled={submitStage === "pending"}
              className="inline-flex shrink-0 items-center gap-1 rounded px-1.5 py-1 text-xs text-txt-muted transition-[color,background-color] hover:bg-danger-soft hover:text-danger"
            >
              <X size={14} aria-hidden="true" />
              {t.voiceRemove}
            </button>
          </div>
        </div>

        {/* Submit / Structuring pending / done (§9.1 in-button spinner, never
            a full-page spinner). */}
        <div
          className="flex flex-col gap-2"
          data-testid="submit-zone"
          hidden={!synopsisReady}
        >
          {text.trim().length === 0 && (
            <p
              className="rounded-md bg-warn-soft px-3 py-2 text-sm text-warn-text"
              data-testid="warn-empty"
            >
              <strong className="font-semibold">{t.emptyTitle}</strong>
              <span className="block">{t.emptyBody}</span>
            </p>
          )}
          <Button
            type="button"
            size="lg"
            className="w-full"
            data-testid="btn-submit"
            disabled={!canSubmit}
            onClick={() => void handleSubmit()}
          >
            {t.submit}
          </Button>
        </div>

        <div data-testid="ctrl-pending" hidden={submitStage !== "pending"}>
          <Button type="button" size="lg" className="w-full" disabled loading>
            {t.submitting}
          </Button>
        </div>

        {submitStage === "done" && intakeId !== null && (
          <div className="flex flex-col gap-3" data-testid="done-zone">
            <p className="inline-flex items-center justify-center gap-2 rounded-lg bg-success-soft p-3 font-medium text-success-text">
              <span aria-hidden="true">✓</span>
              <span data-testid="done-body">{t.doneBody}</span>
            </p>
            <Button asChild size="lg" className="w-full" data-testid="btn-next">
              <Link href={`/patient/intake/${intakeId}/pre-summary`}>
                {t.next}
              </Link>
            </Button>
          </div>
        )}
      </div>
    </>
  );
}
