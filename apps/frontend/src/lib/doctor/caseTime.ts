// MOD-012 / FEAT-008 (#652 / #676): the relative "Updated 3 hr ago" line
// shared by the cases index and the dashboard's open-cases section - one copy
// so the two surfaces cannot drift out of step on the same case. Granularity
// buckets at minutes / hours / days, coarse enough that a test fixture's fixed
// clock cannot flip the bucket between renders. Words come from
// doctorConsole's caseUpdatedAgo / caseUpdatedJustNow / timeAgo* keys; no date
// library, the wrapper + three units keep the whole sentence translatable per
// locale (REQ-006).

import type { Dictionary } from "@/lib/i18n/dictionaries";

/** Minutes since `iso`, or null when the timestamp is not a parseable date. */
export function minutesSince(iso: string, now: number): number | null {
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return null;
  return Math.max(0, Math.floor((now - then) / 60_000));
}

/**
 * "Updated 3 hr ago" in the active language, or null when the timestamp does
 * not parse - a card then drops the line rather than dating a case with a
 * lie.
 */
export function caseUpdatedText(
  iso: string,
  t: Dictionary["doctorConsole"],
  now: number = Date.now(),
): string | null {
  const minutes = minutesSince(iso, now);
  if (minutes === null) return null;
  if (minutes < 1) return t.caseUpdatedJustNow;
  if (minutes < 60) return t.caseUpdatedAgo(t.timeAgoMinutes(minutes));
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return t.caseUpdatedAgo(t.timeAgoHours(hours));
  return t.caseUpdatedAgo(t.timeAgoDays(Math.floor(hours / 24)));
}
