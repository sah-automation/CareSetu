import * as React from "react";

import { cn } from "@/lib/utils";

// Copied from the shadcn/ui Tailwind v3 registry (new-york style) per #600.
// Shares the Input's token bridge: bg-surface instead of upstream's
// bg-transparent, and the stock `shadow-sm` dropped because it resolves through
// no token (#193). The min height moves from upstream's arbitrary
// min-h-[60px] to the min-h-20 step so the box is sized from the scale, and the
// ink is an explicit text-foreground rather than an inherited colour.
const Textarea = React.forwardRef<
  HTMLTextAreaElement,
  React.ComponentProps<"textarea">
>(({ className, ...props }, ref) => {
  return (
    <textarea
      className={cn(
        "flex min-h-20 w-full rounded-md border border-input bg-surface px-3 py-2 text-base text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50 md:text-sm",
        className,
      )}
      ref={ref}
      {...props}
    />
  );
});
Textarea.displayName = "Textarea";

export { Textarea };
