import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

// Copied from the shadcn/ui Tailwind v3 registry (new-york style) per #600.
// Token bridge: the variants name only slots that exist in the app's token
// vocabulary (#193) - primary/secondary/destructive are bridged to the
// accent/warm/danger ramps - and the outline variant takes `border-input`,
// since a bare `border` would fall back to Tailwind's default grey outside the
// token source. Three shape changes away from upstream: `rounded-md` becomes
// `rounded-full` because the pill is this app's own chip idiom
// (ServicesGrid.tsx, HealthSnapshotCard.tsx); `focus:` becomes
// `focus-visible:` with ring-1 and no offset, matching the already-adopted
// Button (#199) rather than upstream's ring-2 + ring-offset-2, so a mouse
// click leaves no ring; and upstream's stock `shadow` on the default and
// destructive variants is dropped - a badge is inline text, not a raised
// surface, and the stock shadow resolves through no token.
const badgeVariants = cva(
  "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
  {
    variants: {
      variant: {
        default:
          "border-transparent bg-primary text-primary-foreground hover:bg-primary/80",
        secondary:
          "border-transparent bg-secondary text-secondary-foreground hover:bg-secondary/80",
        destructive:
          "border-transparent bg-destructive text-destructive-foreground hover:bg-destructive/80",
        outline: "border-input text-foreground",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return (
    <div className={cn(badgeVariants({ variant }), className)} {...props} />
  );
}

export { Badge, badgeVariants };
