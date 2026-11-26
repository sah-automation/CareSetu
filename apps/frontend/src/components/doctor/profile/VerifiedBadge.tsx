"use client";

// #623: the one badge that renders a doctor's verification verdict.
//
// The verdict is one flag, `profile.verified`, derived server-side from activation
// state plus credential dates (ADR-0011). Two places on the rebuilt profile page
// render it - the identity band's chip row and the credential band's activation
// row - and each had written the same four decisions out separately: the variant,
// the two-branch class string, the `BadgeCheck` gated on the flag, and the
// `verified ? verified : notVerified` text. Four copies of the same judgement, two
// of which are free to drift, and the drift that matters here is a tick on one
// and a word on the other.
//
// One component, so the tick and its word cannot come apart: `verified` renders
// both, `!verified` renders neither icon and the negative word. There is no
// branch that produces a tick without its verdict, which is the claim this
// product cannot make ("if the tick is gone, the card is gone").
//
// It renders the FLAG and nothing else. Recomputing credential validity in the
// client would be a second derivation site that eventually disagrees with the
// backend's - the disagreement being the failure this band exists to prevent - so
// the verdict is read, never re-derived. This is why the caller supplies the flag
// and the copy and the badge decides only how to draw them.

import { BadgeCheck } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

export interface VerifiedBadgeProps {
  /** The backend's derived verdict. Never recomputed here. */
  verified: boolean;
  /** The affirmative verdict word, shown when `verified`. */
  verifiedLabel: string;
  /** The negative verdict word, shown when not `verified`. */
  notVerifiedLabel: string;
  className?: string;
  "data-testid"?: string;
}

export function VerifiedBadge({
  verified,
  verifiedLabel,
  notVerifiedLabel,
  className,
  "data-testid": testId,
}: VerifiedBadgeProps) {
  return (
    <Badge
      variant={verified ? "default" : "secondary"}
      className={cn(
        "inline-flex items-center gap-1",
        verified
          ? "bg-success-soft text-success-text"
          : "bg-accent-soft text-accent-strong",
        className,
      )}
      data-testid={testId}
    >
      {/* The name goes on the tick, not only on the text beside it: the icon is
          decorative and the verdict it qualifies is already spelled out next to
          it. Gated on the flag, so a false verdict draws no tick at all. */}
      {verified && <BadgeCheck aria-hidden="true" className="h-3.5 w-3.5" />}
      {verified ? verifiedLabel : notVerifiedLabel}
    </Badge>
  );
}
