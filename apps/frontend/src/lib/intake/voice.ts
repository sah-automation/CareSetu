// PHASE-7 T16 (#360): voice intake page logic - pure, DOM-free helpers and
// constants for the recorder page state machine (blueprint §5.4, finalized
// PROTO-PHASE-7/8 intake-voice.html is the binding copy spec). The 180s cap,
// the 3s usability floor, and the 3-attempt record ladder mirror the backend
// domain constants (MAX_RECORD_ATTEMPTS in modules/intake/domain/state_machine.py);
// the upload retry ladder mirrors the facade's NFR-PERF-002 backoff curve.

//: Longest a take may run; the recorder auto-stops at the cap.
export const MAX_RECORD_MS = 180_000;

//: Usability floor: a take shorter than this is never submitted silently -
//  the re-record-or-type prompt is shown instead (FEAT-006 scenario 2).
export const MIN_RECORD_MS = 3_000;

//: Total voice recording attempts before the patient is asked to type
//  instead (B3 fallback ladder, matches MAX_RECORD_ATTEMPTS server-side).
export const MAX_RECORD_ATTEMPTS = 3;

//: Upload-transfer ladder: initial try + retries up to this many total calls,
//  with exponential backoff before each retry (NFR-PERF-002, US-10).
export const MAX_UPLOAD_ATTEMPTS = 3;

//: Base backoff before the first retry, doubled each subsequent retry -
//  500ms then 1000ms, the same curve as the facade's _upload_backoff_delay.
export const UPLOAD_RETRY_BASE_MS = 500;

//: How often the server intake detail is polled while a submit is structuring.
export const INTAKE_POLL_INTERVAL_MS = 2_000;

//: Longest structuring wait on this page before releasing to the pre-summary
//  link (the review page itself owns the authoritative readiness states).
export const MAX_INTAKE_POLLS = 15;

/** The voice intake page's interactive stages (mirrors the prototype states). */
export type VoiceStage =
  | "idle"
  | "recording"
  | "preview"
  | "pending"
  | "poor"
  | "done";

/** Format seconds as a mm:ss stopwatch readout. */
export function fmtDuration(totalSeconds: number): string {
  const clamped = Math.max(0, Math.floor(totalSeconds));
  const m = String(Math.floor(clamped / 60)).padStart(2, "0");
  const s = String(clamped % 60).padStart(2, "0");
  return `${m}:${s}`;
}

/** Backoff before retry ordinal (1-based): 500ms, 1000ms, 2000ms, ... */
export function uploadBackoffDelayMs(retryOrdinal: number): number {
  return UPLOAD_RETRY_BASE_MS * 2 ** Math.max(0, retryOrdinal - 1);
}

/** Resolve after ms - the injectable sleep used by the retry ladder. */
export function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

/**
 * Run an upload-producing action through the resilience ladder: up to
 * MAX_UPLOAD_ATTEMPTS calls with exponential backoff between retries. When
 * every attempt fails, the last error rethrows - the caller keeps the
 * capture so nothing is silently lost on a flaky connection.
 */
export async function uploadWithRetry<T>(action: () => Promise<T>): Promise<T> {
  let lastError: unknown = undefined;
  for (let attempt = 1; attempt <= MAX_UPLOAD_ATTEMPTS; attempt++) {
    try {
      return await action();
    } catch (error) {
      lastError = error;
      if (attempt < MAX_UPLOAD_ATTEMPTS) {
        await sleep(uploadBackoffDelayMs(attempt));
      }
    }
  }
  throw lastError;
}
