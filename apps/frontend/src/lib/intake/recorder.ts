// PHASE-7 T16 (#360): microphone recording seam over the browser MediaRecorder
// API. Kept as a tiny injectable module so the voice page drives a plain
// RecorderSession interface and tests can substitute a fake (jsdom has no
// getUserMedia / MediaRecorder). One session owns one microphone stream; the
// caller must close() it when leaving the recording stage.

export interface RecorderSession {
  start(): void;
  pause(): void;
  resume(): void;
  /** Stop capture and resolve the recorded Blob (throws on a failed take). */
  stop(): Promise<Blob>;
  /** Release the microphone stream - call when the take is done with. */
  close(): void;
}

/**
 * Open the microphone and answer a live RecorderSession. Rejects when the
 * browser has no media capture support or the user denies the mic.
 */
export async function openMicrophoneRecorder(): Promise<RecorderSession> {
  if (
    typeof navigator === "undefined" ||
    typeof navigator.mediaDevices?.getUserMedia !== "function"
  ) {
    throw new Error("Microphone capture is not supported in this browser");
  }
  if (typeof MediaRecorder === "undefined") {
    throw new Error("MediaRecorder is not supported in this browser");
  }

  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });

  let recorder: MediaRecorder;
  try {
    recorder = new MediaRecorder(stream);
  } catch {
    stream.getTracks().forEach((track) => track.stop());
    throw new Error("MediaRecorder could not start for this microphone");
  }

  let chunks: BlobPart[] = [];
  let resolveStop: ((blob: Blob) => void) | null = null;
  let rejectStop: ((error: Error) => void) | null = null;

  recorder.ondataavailable = (event) => {
    if (event.data && event.data.size > 0) {
      chunks.push(event.data);
    }
  };
  recorder.onstop = () => {
    if (resolveStop) {
      const blob = new Blob(chunks, {
        type: recorder.mimeType || "audio/webm",
      });
      chunks = [];
      const resolve = resolveStop;
      resolveStop = null;
      rejectStop = null;
      resolve(blob);
    }
  };
  recorder.onerror = (event) => {
    if (rejectStop) {
      const reject = rejectStop;
      resolveStop = null;
      rejectStop = null;
      reject(new Error(event.error?.name ?? "Recording failed"));
    }
  };

  return {
    start() {
      chunks = [];
      recorder.start();
    },
    pause() {
      if (recorder.state === "recording") {
        recorder.pause();
      }
    },
    resume() {
      if (recorder.state === "paused") {
        recorder.resume();
      }
    },
    stop() {
      return new Promise<Blob>((resolve, reject) => {
        resolveStop = resolve;
        rejectStop = reject;
        if (recorder.state !== "inactive") {
          recorder.stop();
        } else {
          const empty = new Blob([], { type: recorder.mimeType });
          resolveStop = null;
          rejectStop = null;
          resolve(empty);
        }
      });
    },
    close() {
      if (recorder.state !== "inactive") {
        try {
          recorder.stop();
        } catch {
          // already stopped or failing - releasing the tracks is what matters
        }
      }
      stream.getTracks().forEach((track) => track.stop());
    },
  };
}
