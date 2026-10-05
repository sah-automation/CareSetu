import * as React from "react";

import { cn } from "@/lib/utils";

// Copied from the shadcn/ui Tailwind v3 registry (new-york style) per #600.
// Token bridge: upstream's `bg-transparent` becomes bg-surface so the field is
// the white surface token rather than whatever sits behind it, and its stock
// `shadow-sm` is dropped because it resolves through no token (#193). Two
// additions: an explicit text-foreground so the ink is a token rather than
// whatever the field inherits, and a h-10 / py-2 box instead of upstream's
// h-9 / py-1, because this app's fields are touch targets on a 4G phone and
// the app's own field markup (HeroSearch.tsx) already uses px-3 py-2.
const Input = React.forwardRef<HTMLInputElement, React.ComponentProps<"input">>(
  ({ className, type, ...props }, ref) => {
    return (
      <input
        type={type}
        className={cn(
          "flex h-10 w-full rounded-md border border-input bg-surface px-3 py-2 text-base text-foreground transition-colors file:border-0 file:bg-transparent file:text-sm file:font-medium file:text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50 md:text-sm",
          className,
        )}
        ref={ref}
        {...props}
      />
    );
  },
);
Input.displayName = "Input";

export { Input };
