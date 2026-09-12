"use client";

// PHASE-7 T16 (#360): voice intake recorder page (blueprint §5.4, finalized
// PROTO-PHASE-7/8 intake-voice.html is the binding copy spec). A large
// always-visible mic target with a live duration counter capped at 180
// seconds, playback + re-record before submit to fix a bad take, at most 3
// voice attempts before the patient is asked to type instead (B3 ladder, the
// server's MAX_RECORD_ATTEMPTS cap), and a plain-language re-record-or-type
// prompt when a take is under the 3-second floor or the server reports the
// audio unusable - never a silent proceed (FEAT-006 scenario 2). Uploads ride
// an auto-retry ladder (x3, exponential backoff) so a flaky connection never
// silently loses a capture. Submit shows an in-button Structuring pending
// state per §9.1 (never a full-page spinner), then advances to the pre-summary
// review link once the intake reaches ready_for_review.

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  LoaderCircle,
  Mic,
  Pause,
  Play,
  RotateCcw,
  Square,
} from "lucide-react";

import { ErrorBanner } from "@/components/layout/ErrorBanner";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api-errors";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import {
  fetchIntake,
  reRecordIntake,
  submitIntake,
  uploadIntakeMedia,
} from "@/lib/intake/api";
import {
  type RecorderSession,
  openMicrophoneRecorder,
} from "@/lib/intake/recorder";
import {
  INTAKE_POLL_INTERVAL_MS,
  MAX_INTAKE_POLLS,
  MAX_RECORD_ATTEMPTS,
  MAX_RECORD_MS,
  MIN_RECORD_MS,
  fmtDuration,
  uploadWithRetry,
  type VoiceStage,
} from "@/lib/intake/voice";
import { cn } from "@/lib/utils";

type ErrorKind = "mic" | "upload";

const MIC_BUTTON_BASE =
  "inline-flex h-32 w-32 items-center justify-center rounded-full border-2 border-accent-border bg-accent-soft text-accent-strong shadow-card transition-[transform,background-color,color,box-shadow] duration-150 hover:scale-[1.02] hover:bg-accent hover:text-on-accent active:scale-[0.985] disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:scale-100 disabled:hover:bg-accent-soft disabled:hover:text-accent-strong";

export default function VoiceIntakePage() {
  const { lang } = useLang();
  const dict = STRINGS[lang].intake;
  const nav = STRINGS[lang].nav;
  const t = dict.voice;

  const [stage, setStage] = useState<VoiceStage>("idle");
  const [elapsedMs, setElapsedMs] = useState(0);
  const [paused, setPaused] = useState(false);
  const [attemptsUsed, setAttemptsUsed] = useState(0);
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
  const elapsedRef = useRef(0);
  const audioElRef = useRef<HTMLAudioElement | null>(null);
  const audioUrlRef = useRef<string | null>(null);

  const [playing, setPlaying] = useState(false);

  const handleAudioPlay = useCallback(() => {
    setPlaying(true);
  }, []);

  const handleAudioStop = useCallback(() => {
    setPlaying(false);
  }, []);

  /** Pause and detach any in-flight playback and release the object URL. */
  const revokeAudioUrl = useCallback(() => {
    const audioEl = audioElRef.current;
    if (audioEl) {
      audioEl.removeEventListener("play", handleAudioPlay);
      audioEl.removeEventListener("pause", handleAudioStop);
      audioEl.removeEventListener("ended", handleAudioStop);
      audioEl.pause();
      audioEl.currentTime = 0;
    }
    audioElRef.current = null;
    if (audioUrlRef.current && typeof URL.revokeObjectURL === "function") {
      URL.revokeObjectURL(audioUrlRef.current);
    }
    audioUrlRef.current = null;
    setPlaying(false);
  }, [handleAudioPlay, handleAudioStop]);

  /** Surface a terminal failure as a banner plus the stage to fall back into. */
  const failWith = useCallback(
    (kind: ErrorKind, next: VoiceStage, traceId?: string) => {
      setErrorBanner({
        title: kind === "mic" ? t.micUnavailableTitle : t.uploadErrorTitle,
        body: kind === "mic" ? t.micUnavailableBody : t.uploadErrorBody,
        traceId,
      });
      setErrorKind(kind);
      setStage(next);
    },
    [t],
  );

  const handleStartRecording = useCallback(async () => {
    revokeAudioUrl();
    try {
      const recorder = await openMicrophoneRecorder();
      recorderRef.current = recorder;
      recorder.start();
      elapsedRef.current = 0;
      setElapsedMs(0);
      setPaused(false);
      setErrorBanner(null);
      setErrorKind(null);
      setStage("recording");
    } catch {
      failWith("mic", "idle");
    }
  }, [failWith, revokeAudioUrl]);

  const handleStopCapture = useCallback(async () => {
    const recorder = recorderRef.current;
    if (!recorder) return;
    try {
      const blob = await recorder.stop();
      captureRef.current = blob;
    } catch {
      failWith("mic", "idle");
      return;
    } finally {
      recorder.close();
      recorderRef.current = null;
    }
    setPaused(false);
    setStage("preview");
  }, [failWith]);

  useEffect(() => {
    if (stage !== "recording" || paused) {
      return;
    }
    const id = window.setInterval(() => {
      setElapsedMs((prev) => {
        const next = Math.min(prev + 1000, MAX_RECORD_MS);
        elapsedRef.current = next;
        return next;
      });
    }, 1000);
    return () => window.clearInterval(id);
  }, [stage, paused]);

  // Auto-stop at the 180s cap - the counter never overruns MAX_RECORD_MS.
  useEffect(() => {
    if (stage === "recording" && !paused && elapsedMs >= MAX_RECORD_MS) {
      void handleStopCapture();
    }
  }, [elapsedMs, stage, paused, handleStopCapture]);

  const handlePauseToggle = () => {
    const recorder = recorderRef.current;
    if (!recorder) return;
    if (paused) {
      recorder.resume();
      setPaused(false);
    } else {
      recorder.pause();
      setPaused(true);
    }
  };

  const handlePlayPreview = () => {
    const blob = captureRef.current;
    if (!blob || typeof URL.createObjectURL !== "function") {
      return;
    }
    // Second click while playing stops playback and rewinds - always restart
    // from the top, never a paused playhead resume.
    if (playing && audioElRef.current) {
      audioElRef.current.pause();
      audioElRef.current.currentTime = 0;
      return;
    }
    if (audioUrlRef.current) {
      revokeAudioUrl();
    }
    const url = URL.createObjectURL(blob);
    audioUrlRef.current = url;
    if (typeof Audio !== "undefined") {
      if (!audioElRef.current) {
        audioElRef.current = new Audio();
      }
      audioElRef.current.src = url;
      audioElRef.current.addEventListener("play", handleAudioPlay);
      audioElRef.current.addEventListener("pause", handleAudioStop);
      audioElRef.current.addEventListener("ended", handleAudioStop);
      void audioElRef.current.play();
    }
  };

  // Page teardown mid-playback must stop audio and detach its listeners, so
  // leaving the page never leaves a stale in-progress state or leaked audio.
  useEffect(() => {
    return () => revokeAudioUrl();
  }, [revokeAudioUrl]);

  const handleRecordAgain = useCallback(() => {
    revokeAudioUrl();
    captureRef.current = null;
    void handleStartRecording();
  }, [handleStartRecording, revokeAudioUrl]);

  const handleSubmit = useCallback(async () => {
    const blob = captureRef.current;
    if (!blob) {
      return;
    }
    const durationMs = elapsedRef.current;

    // Client-side usability floor: a take under MIN_RECORD_MS is never
    // submitted silently - the re-record-or-type prompt is shown instead.
    if (durationMs < MIN_RECORD_MS) {
      setStage("poor");
      return;
    }

    setStage("pending");
    setErrorBanner(null);
    setErrorKind(null);
    setStructuringId(null);
    revokeAudioUrl();

    try {
      const mediaRef = await uploadWithRetry(() =>
        uploadIntakeMedia(blob, {
          filename: "recording.webm",
          audioDurationMs: durationMs,
          fileSizeBytes: blob.size,
        }),
      );

      let submittedIntakeId: number;
      if (intakeId === null) {
        const submitted = await submitIntake({
          mode: "voice",
          language: lang,
          media_ref: mediaRef,
        });
        submittedIntakeId = submitted.intake_id;
        setIntakeId(submitted.intake_id);
        setAttemptsUsed(1);
      } else {
        const rerecorded = await reRecordIntake(intakeId, mediaRef);
        setAttemptsUsed(rerecorded.record_attempts);
        if (rerecorded.forced_text) {
          // The server capped voice attempts and routed the intake to text.
          setStage("poor");
          return;
        }
        submittedIntakeId = intakeId;
      }

      setStructuringId(submittedIntakeId);
    } catch (error) {
      // Upload or submit failed after the retry ladder: the capture stays in
      // memory, the page returns to preview, and nothing is silently lost.
      failWith(
        "upload",
        "preview",
        error instanceof ApiError ? error.traceId : undefined,
      );
    }
  }, [intakeId, lang, failWith, revokeAudioUrl]);

  // Poll the server detail while Structuring (in-button pending, §9.1):
  // ready_for_review -> done (pre-summary link), re_record / unusable ->
  // poor prompt, failed -> error with the capture preserved. A slow pipeline
  // releases after MAX_INTAKE_POLLS so the flow never stalls here.
  useEffect(() => {
    if (stage !== "pending" || structuringId === null) {
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
            setAttemptsUsed(detail.record_attempts);
            setStage("done");
          } else if (
            detail.status === "re_record" ||
            detail.transcript_usability === "unusable"
          ) {
            cancelled = true;
            window.clearInterval(timer);
            setAttemptsUsed(detail.record_attempts);
            setStage("poor");
          } else if (detail.status === "failed") {
            cancelled = true;
            window.clearInterval(timer);
            failWith("upload", "preview");
          } else if (ticks >= MAX_INTAKE_POLLS) {
            cancelled = true;
            window.clearInterval(timer);
            setStage("done");
          }
        } catch {
          if (ticks >= MAX_INTAKE_POLLS) {
            cancelled = true;
            window.clearInterval(timer);
            setStage("done");
          }
        }
      })();
    }, INTAKE_POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [stage, structuringId, failWith]);

  const isMicLive = stage === "recording";
  const micHidden = stage === "poor" || stage === "done";
  // The duration counter's live status readout: one label per stage, with the
  // recording stage further split by pause state.
  const stageStatus: Record<VoiceStage, keyof typeof t> = {
    idle: "statusIdle",
    recording: "statusRecording",
    preview: "statusPreview",
    pending: "statusPending",
    poor: "statusPoor",
    done: "statusDone",
  };
  const statusKey: keyof typeof t =
    stage === "recording" && paused ? "statusPaused" : stageStatus[stage];

  const ladderExhausted = attemptsUsed >= MAX_RECORD_ATTEMPTS;

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
        className="mx-auto flex max-w-xl flex-col items-stretch gap-4 rounded-lg border border-hairline bg-surface p-6 text-center shadow-card"
        data-testid="voice-recorder"
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
                void handleStartRecording();
              } else if (captureRef.current) {
                void handleSubmit();
              }
            }}
            onDismiss={() => {
              setErrorBanner(null);
              setErrorKind(null);
            }}
          />
        )}

        {!micHidden && (
          <div
            className="flex flex-col items-center gap-2"
            data-testid="mic-wrap"
          >
            <button
              type="button"
              aria-label={t.statusRecording}
              data-testid="mic-button"
              disabled={stage === "pending"}
              className={cn(
                MIC_BUTTON_BASE,
                isMicLive && "bg-accent text-on-accent",
              )}
              onClick={() => {
                if (stage === "recording") {
                  void handleStopCapture();
                } else {
                  void handleStartRecording();
                }
              }}
            >
              {isMicLive ? (
                <Square size={40} strokeWidth={1.8} aria-hidden="true" />
              ) : (
                <Mic size={48} strokeWidth={1.8} aria-hidden="true" />
              )}
            </button>
            <output
              className="text-2xl font-bold tracking-wider tabular-nums"
              data-testid="duration"
              aria-live="off"
              aria-label={t[statusKey]}
            >
              {fmtDuration(elapsedMs / 1000)}
            </output>
            <p
              className="text-sm text-txt-sub"
              data-testid="status-line"
              aria-live="polite"
            >
              {t[statusKey]}
            </p>
          </div>
        )}

        {/* RECORDING controls */}
        {stage === "recording" && (
          <div
            className="flex flex-wrap justify-center gap-2"
            data-testid="ctrl-record"
          >
            <Button
              type="button"
              variant="outline"
              size="lg"
              data-testid="btn-pause"
              onClick={handlePauseToggle}
            >
              <Pause size={16} className="mr-2" aria-hidden="true" />
              {paused ? t.resume : t.pause}
            </Button>
            <Button
              type="button"
              size="lg"
              data-testid="btn-stop"
              onClick={() => void handleStopCapture()}
            >
              <Square size={16} className="mr-2" aria-hidden="true" />
              {t.stop}
            </Button>
          </div>
        )}

        {/* PLAYBACK controls */}
        {stage === "preview" && (
          <div
            className="flex flex-wrap justify-center gap-2"
            data-testid="ctrl-preview"
          >
            <Button
              type="button"
              variant="outline"
              size="lg"
              className={
                playing
                  ? "bg-accent text-on-accent hover:bg-accent hover:text-on-accent"
                  : undefined
              }
              aria-label={playing ? t.playing : t.play}
              aria-busy={playing || undefined}
              data-testid="btn-play"
              onClick={handlePlayPreview}
            >
              {playing ? (
                <LoaderCircle
                  size={16}
                  className="mr-2 shrink-0 animate-spin"
                  aria-hidden="true"
                  data-testid="button-spinner"
                />
              ) : (
                <Play size={16} className="mr-2" aria-hidden="true" />
              )}
              {playing ? t.playing : t.play}
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="lg"
              data-testid="btn-again"
              onClick={handleRecordAgain}
            >
              <RotateCcw size={16} className="mr-2" aria-hidden="true" />
              {t.recordAgain}
            </Button>
            <Button
              type="button"
              size="lg"
              data-testid="btn-submit"
              onClick={() => void handleSubmit()}
            >
              {t.submit}
            </Button>
          </div>
        )}

        {/* SUBMIT-PENDING: in-button Structuring state, never a page spinner */}
        {stage === "pending" && (
          <div
            className="flex flex-wrap justify-center gap-2"
            data-testid="ctrl-pending"
          >
            <Button type="button" size="lg" disabled loading>
              {t.submitting}
            </Button>
          </div>
        )}

        {/* POOR-AUDIO (FEAT-006 scenario 2): re-record or switch to typing,
            never a silent proceed. At the 3-attempt cap, typing is the only
            path (the server has already routed the intake to forced text). */}
        {stage === "poor" && (
          <div className="space-y-3" role="alert" data-testid="warn-zone">
            <div className="rounded-lg border border-hairline bg-warn-soft px-4 py-3 text-left">
              <strong className="text-warn-text">{t.poorTitle}</strong>
              <br />
              <span className="text-warn-text">
                {ladderExhausted ? t.attemptsExhausted : t.poorBody}
              </span>
            </div>
            {!ladderExhausted && (
              <Button
                type="button"
                variant="outline"
                size="lg"
                className="w-full"
                data-testid="btn-retry"
                onClick={handleRecordAgain}
              >
                <RotateCcw size={16} className="mr-2" aria-hidden="true" />
                {t.poorRetry}
              </Button>
            )}
            <Button asChild size="lg" className="w-full" data-testid="btn-type">
              <Link href="/patient/intake/text">{t.poorType}</Link>
            </Button>
          </div>
        )}

        {/* DONE: captured + path to the pre-summary review. A re-record
            affordance stays available (prototype btn-again2) until the
            server's 3-attempt cap is reached - past the cap the intake is
            already routed to typing, so only the pre-summary link remains. */}
        {stage === "done" && intakeId !== null && (
          <div className="flex flex-col gap-3" data-testid="done-zone">
            <p className="inline-flex items-center justify-center gap-2 rounded-lg bg-success-soft p-3 font-medium text-success-text">
              <span aria-hidden="true">✓</span>
              {t.doneBody}
            </p>
            <Button asChild data-testid="btn-next">
              <Link href={`/patient/intake/${intakeId}/pre-summary`}>
                {t.next}
              </Link>
            </Button>
            {!ladderExhausted && (
              <Button
                type="button"
                variant="ghost"
                data-testid="btn-again2"
                onClick={handleRecordAgain}
              >
                <RotateCcw size={16} className="mr-2" aria-hidden="true" />
                {t.recordAgain}
              </Button>
            )}
          </div>
        )}
      </div>
    </>
  );
}
