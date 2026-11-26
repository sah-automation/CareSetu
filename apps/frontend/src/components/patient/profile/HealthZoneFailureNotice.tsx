"use client";

// MOD-003 (FEAT-002 record / FEAT-018 metrics), #549: the failure banner both
// of the Health background zone's reads share. Both answer "we could not load
// this" the same way - a plain sentence, the trace id so support can start from
// what the patient is looking at, and one retry - so the shape lives here
// instead of being written twice inside this zone.
//
// The message never names the backend error code. A code like
// HEALTH_BACKGROUND_ACK_REQUIRED is for the code and the logs; what the patient
// needs to know is that the tap did not work and that trying again is safe.

export interface HealthZoneFailure {
  /** Envelope trace id, when the failure carried one. */
  traceId?: string;
}

export function HealthZoneFailureNotice({
  message,
  retryLabel,
  failure,
  onRetry,
  testId,
  retryTestId,
  className = "",
}: {
  message: string;
  retryLabel: string;
  failure: HealthZoneFailure;
  onRetry: () => void;
  testId: string;
  retryTestId: string;
  className?: string;
}) {
  return (
    <div
      role="alert"
      data-testid={testId}
      className={`flex flex-wrap items-center gap-3 rounded-md border border-danger-border bg-danger-soft px-3 py-2 text-sm text-danger ${className}`}
    >
      <span>
        {message}
        {failure.traceId && (
          <span className="ml-1 font-mono text-xs">({failure.traceId})</span>
        )}
      </span>
      <button
        type="button"
        onClick={onRetry}
        className="rounded-md border border-danger-border px-2 py-1 text-xs font-medium text-danger"
        data-testid={retryTestId}
      >
        {retryLabel}
      </button>
    </div>
  );
}
