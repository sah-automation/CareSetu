"use client";

import * as React from "react";
import * as SwitchPrimitives from "@radix-ui/react-switch";

import { cn } from "@/lib/utils";

// Copied from the shadcn/ui Tailwind v3 registry (new-york style) per #600.
// Token bridge. Checked track: keeps upstream's bg-primary, because this app's
// `primary` slot is already the solid brand teal (#193) - unlike `accent`, which
// is the solid brand and so cannot double as the selected surface. Unchecked
// track: keeps upstream's bg-input, but that slot is the app's hairline grey
// here, which is a track you can barely see on a white surface, so it also
// takes the matching `data-[state=unchecked]:border-input` edge. Thumb: upstream's
// bg-background is the page tint in this app, not white, so the knob would read
// grey on the teal track and it takes bg-surface instead.
// Changes away from upstream. The stock `shadow-sm` on the track and `shadow-lg`
// on the thumb both become the shadow-card token, and the thumb's `ring-0` is
// dropped since no ring is drawn on it. The track is h-6 w-11 against upstream's
// h-5 w-9 because a 44px control is the comfortable touch line on a 4G phone.
// The focus ring is ring-1 with no offset, matching the already-adopted Button
// (#199) rather than upstream's ring-2 + ring-offset-2.
const Switch = React.forwardRef<
  React.ElementRef<typeof SwitchPrimitives.Root>,
  React.ComponentPropsWithoutRef<typeof SwitchPrimitives.Root>
>(({ className, ...props }, ref) => (
  <SwitchPrimitives.Root
    className={cn(
      "peer inline-flex h-6 w-11 shrink-0 cursor-pointer items-center rounded-full border-2 border-transparent transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50 data-[state=checked]:bg-primary data-[state=unchecked]:border-input data-[state=unchecked]:bg-input",
      className,
    )}
    {...props}
    ref={ref}
  >
    <SwitchPrimitives.Thumb className="pointer-events-none block h-5 w-5 rounded-full bg-surface shadow-card transition-transform data-[state=checked]:translate-x-5 data-[state=unchecked]:translate-x-0" />
  </SwitchPrimitives.Root>
));
Switch.displayName = SwitchPrimitives.Root.displayName;

export { Switch };
