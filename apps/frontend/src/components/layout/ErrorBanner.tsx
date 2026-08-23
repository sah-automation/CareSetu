"use client";

// PHASE-2.6 T08 (#199): the page-scoped error pattern (blueprint §9.1) -
// a dismissible banner at the top of the content area with a Retry action
// and a short trace id for support correlation. The trace id is generated
// client-side per banner instance (no backend dependency this phase); when
// the caller has an API-provided trace id it wins.

import { useEffect, useState, type ReactNode } from "react";

// Short correlation token: exactly 8 lowercase base-36 chars. Drawn in a loop
// because Math.random().toString(36) can round-trip shorter than 8 chars.
function makeTraceId(): string {
  let id = Math.random().toString(36).slice(2);
  while (id.length < 8) {
    id += Math.random().toString(36).slice(2);
  }
  return id.slice(0, 8);
}

interface ErrorBannerProps {
  message: ReactNode;
  onRetry?: () => void;
  onDismiss?: () => void;
  /** API-provided trace id; defaults to a client-generated short id. */
  traceId?: string;
}

export function ErrorBanner({
  message,
  onRetry,
  onDismiss,
  traceId,
}: ErrorBannerProps) {
  // Generated in an effect (not during render) so server and client renders
  // of a pre-error page agree during hydration.
  const [resolvedTraceId, setResolvedTraceId] = useState(traceId ?? "");
  useEffect(() => {
    setResolvedTraceId((current) => current || traceId || makeTraceId());
  }, [traceId]);

  return (
    <div
      role="alert"
      className="mb-4 flex items-start justify-between gap-3 rounded-lg border border-danger-border bg-danger-soft px-4 py-3"
      data-testid="error-banner"
    >
      <div className="min-w-0 text-sm">
        <p className="font-medium text-danger">{message}</p>
        <p
          className="mt-0.5 font-mono text-xs text-txt-muted"
          data-testid="error-banner-trace-id"
        >
          Trace: {resolvedTraceId}
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        {onRetry && (
          <button
            type="button"
            onClick={onRetry}
            className="rounded-md border border-danger-border px-2 py-1 text-xs font-medium text-danger hover:bg-danger-soft/60"
            data-testid="error-banner-retry"
          >
            Retry
          </button>
        )}
        {onDismiss && (
          <button
            type="button"
            onClick={onDismiss}
            aria-label="Dismiss"
            className="rounded-md px-1.5 py-1 text-txt-muted hover:text-txt"
            data-testid="error-banner-dismiss"
          >
            &#10005;
          </button>
        )}
      </div>
    </div>
  );
}
