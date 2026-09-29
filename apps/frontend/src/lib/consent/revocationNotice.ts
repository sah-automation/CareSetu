// #565: the two places a patient revokes a standing grant - the Settings-zone
// consent panel and the record's consent log - confirm with the same treatment
// and dismiss it the same way.
//
// The two call sites were duplicated on the claim that they "read the same way"
// and nothing enforced it. Only the duration was shared, and only as a literal
// nobody could see: the panel held it in a ref with an unmount cleanup, the log
// re-armed a raw inline timer with no teardown, and a broken class name ended
// up sitting in both files under a comment insisting they were one. Importing
// the treatment and the duration turns that comment into something the compiler
// checks, which is what stops a third copy drifting.

/** How long the confirmation stays on screen before it clears itself. */
export const REVOCATION_NOTICE_MS = 3500;

/**
 * The approved positive-message treatment, byte-identical to the substring the
 * save-status notice and the health-background save confirmation share. It is
 * a static inline notice rather than a floating toast, so the confirmation
 * renders in normal flow as the last child of its container. The save-status
 * notice additionally prefixes `flex items-start gap-2` because it wraps an
 * icon; this one has no icon, so that prefix is not part of the treatment.
 */
export const REVOCATION_NOTICE_CLASS =
  "rounded-md border border-success-soft bg-success-soft px-3 py-2 text-sm text-success-text";
