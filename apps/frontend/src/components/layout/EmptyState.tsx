"use client";

// PHASE-2.6 T08 (#199): the empty-state pattern (blueprint §9.1) - every
// list/canvas ships one. Anatomy: plain-language what-this-is, why it is
// empty, exactly one next action. Neutral/soft accent styling, never
// error-like; never blames the user.

import type { ReactNode } from "react";

interface EmptyStateProps {
  /** What this area is, in plain language. */
  title: ReactNode;
  /** Why it is empty right now. */
  body?: ReactNode;
  /** Exactly one next action. */
  action?: ReactNode;
}

export function EmptyState({ title, body, action }: EmptyStateProps) {
  return (
    <div
      className="flex flex-col items-center gap-2 rounded-lg border border-hairline bg-accent-soft px-6 py-10 text-center"
      data-testid="empty-state"
    >
      <p className="font-medium text-txt" data-testid="empty-state-title">
        {title}
      </p>
      {body && <p className="max-w-sm text-sm text-txt-muted">{body}</p>}
      {action && <div className="mt-3">{action}</div>}
    </div>
  );
}
