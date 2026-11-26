"use client";

import * as React from "react";
import * as ToggleGroupPrimitive from "@radix-ui/react-toggle-group";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

// Copied from the shadcn/ui Tailwind v3 registry (new-york style) per #600.
// Upstream imports `toggleVariants` from a sibling toggle.tsx that this ticket
// does not adopt, so the variant map is declared here and exported, ready for a
// future standalone toggle to reuse rather than duplicate.
// Token bridge: the selected state is the one real collision. Upstream paints
// it with `bg-accent text-accent-foreground`, but this app's `accent` group is
// the solid brand teal (#193) and `accent-foreground` is not a token at all, so
// the selected surface resolves to the accent-soft / accent-strong pair the
// already-adopted Button (#199 ghost + outline) uses for the same job. Two
// further changes away from upstream: the outline variant's bare `border`
// becomes `border-input` (a bare border falls back to Tailwind's default grey,
// outside the token source) with its stock `shadow-sm` replaced by the
// shadow-card token, and the focus ring is ring-1 with no offset rather than
// upstream's ring-2 + offset, per Button. The `bg-transparent` below is
// upstream's and stays: the token gate treats `transparent` as a CSS-wide
// value, not a palette entry.
const toggleVariants = cva(
  "inline-flex items-center justify-center rounded-md text-sm font-medium transition-colors hover:bg-accent-soft hover:text-accent-strong focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50 data-[state=on]:bg-accent-soft data-[state=on]:text-accent-strong",
  {
    variants: {
      variant: {
        default: "bg-transparent",
        outline:
          "border border-input bg-transparent shadow-card hover:bg-accent-soft hover:text-accent-strong",
      },
      size: {
        default: "h-10 px-3",
        sm: "h-9 px-2.5",
        lg: "h-11 px-5",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
);

// Seeded with the default variant and size, as upstream does. Radix throws
// when an item renders outside a group, so the seed is never reached in
// practice - it is kept so the fallback matches upstream. The consequence
// inside a group is that a group-level value always wins over an item's own
// (see `context.variant || variant` below); the suite pins that precedence
// rather than leaving it surprising.
const ToggleGroupContext = React.createContext<
  VariantProps<typeof toggleVariants>
>({
  size: "default",
  variant: "default",
});

// Radix types the group root as a single/multiple discriminated union, so the
// variant props compose as a type alias rather than the interface SheetContent
// uses for its non-union part.
type ToggleGroupProps = React.ComponentPropsWithoutRef<
  typeof ToggleGroupPrimitive.Root
> &
  VariantProps<typeof toggleVariants>;

const ToggleGroup = React.forwardRef<
  React.ElementRef<typeof ToggleGroupPrimitive.Root>,
  ToggleGroupProps
>(({ className, variant, size, children, ...props }, ref) => (
  <ToggleGroupPrimitive.Root
    ref={ref}
    className={cn("flex items-center justify-center gap-1", className)}
    {...props}
  >
    <ToggleGroupContext.Provider value={{ variant, size }}>
      {children}
    </ToggleGroupContext.Provider>
  </ToggleGroupPrimitive.Root>
));
ToggleGroup.displayName = ToggleGroupPrimitive.Root.displayName;

const ToggleGroupItem = React.forwardRef<
  React.ElementRef<typeof ToggleGroupPrimitive.Item>,
  React.ComponentPropsWithoutRef<typeof ToggleGroupPrimitive.Item> &
    VariantProps<typeof toggleVariants>
>(({ className, children, variant, size, ...props }, ref) => {
  const context = React.useContext(ToggleGroupContext);
  return (
    <ToggleGroupPrimitive.Item
      ref={ref}
      className={cn(
        toggleVariants({
          variant: context.variant || variant,
          size: context.size || size,
        }),
        className,
      )}
      {...props}
    >
      {children}
    </ToggleGroupPrimitive.Item>
  );
});
ToggleGroupItem.displayName = ToggleGroupPrimitive.Item.displayName;

export { ToggleGroup, ToggleGroupItem, toggleVariants };
