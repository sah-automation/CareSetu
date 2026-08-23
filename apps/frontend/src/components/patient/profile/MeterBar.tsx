"use client";

// PHASE-2.6 T13 (#204): shared completion-meter bar. One markup source for
// the wizard's inline meter and the Home-surface meter so the progressbar
// semantics (and the pc-meter testids) can never drift apart.

export function MeterBar({ pct, label }: { pct: number; label: string }) {
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={pct}
      data-testid="pc-meter"
      className="h-2 flex-1 overflow-hidden rounded-full bg-accent-soft"
    >
      <div
        className="h-full rounded-full bg-primary transition-all"
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}
