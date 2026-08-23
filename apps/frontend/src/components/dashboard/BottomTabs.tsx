"use client";

// PHASE-2.6 T06 (#197): mobile bottom tab bar for both densities, rendered
// from the role's nav-config via splitMobileTabs (blueprint §2.4). Up to five
// destination columns; the center accent slot (patient Start Visit) is pinned
// to the middle column; overflow destinations live in the More sheet. Pure
// CSS visibility: `lg:hidden` swaps it out for the sidebar/top-nav at the
// breakpoint. The patient light shell never renders a sidebar at any width.

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { MoreHorizontal } from "lucide-react";

import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import { cn } from "@/lib/utils";

import { NAV_CONFIG, splitMobileTabs } from "./nav-config";
import { SoonBadge } from "./NavItemLink";
import type { NavItemDef } from "./nav-config";
import type { Role } from "./types";

export function BottomTabs({ role }: { role: Role }) {
  const pathname = usePathname();
  const { lang } = useLang();
  const [moreOpen, setMoreOpen] = useState(false);
  const { tabs, overflow, hasMore } = splitMobileTabs(NAV_CONFIG[role]);
  const strings = STRINGS[lang].nav;

  return (
    <>
      <nav
        aria-label="Primary"
        className="fixed inset-x-0 bottom-0 z-40 grid border-t border-hairline bg-surface lg:hidden"
        data-testid="bottom-tabs"
        style={{
          gridTemplateColumns: `repeat(${
            tabs.length + (hasMore ? 1 : 0)
          }, minmax(0, 1fr))`,
          paddingBottom: "env(safe-area-inset-bottom, 0px)",
        }}
      >
        {tabs.map((item) => (
          <TabColumn
            key={item.key}
            item={item}
            active={!item.soon && pathname === item.href}
            label={strings[item.labelKey]}
          />
        ))}
        {hasMore && (
          <button
            type="button"
            onClick={() => setMoreOpen(true)}
            aria-haspopup="dialog"
            data-testid="more-trigger"
            className="flex min-h-16 flex-col items-center justify-center gap-0.5 px-1 py-2 text-[11px] font-medium text-txt-muted"
          >
            <MoreHorizontal size={22} />
            <span>{strings.more}</span>
          </button>
        )}
      </nav>

      <Sheet open={moreOpen} onOpenChange={setMoreOpen}>
        <SheetContent
          side="bottom"
          className="px-4 pb-8"
          data-testid="more-sheet"
        >
          <SheetHeader>
            <SheetTitle>{strings.more}</SheetTitle>
          </SheetHeader>
          <div className="mt-2 flex flex-col">
            {overflow.map((item) => (
              <OverflowRow
                key={item.key}
                item={item}
                label={strings[item.labelKey]}
              />
            ))}
          </div>
        </SheetContent>
      </Sheet>
    </>
  );
}

function TabColumn({
  item,
  active,
  label,
}: {
  item: NavItemDef;
  active: boolean;
  label: string;
}) {
  const Icon = item.icon;

  if (item.soon) {
    return (
      <span
        aria-disabled="true"
        className="flex min-h-16 flex-col items-center justify-center gap-0.5 px-1 py-2 text-[11px] font-medium text-txt-muted opacity-60"
        data-soon="true"
        data-testid={`tab-${item.key}`}
      >
        <Icon size={22} />
        <span>{label}</span>
      </span>
    );
  }

  if (item.center) {
    return (
      <Link
        href={item.href}
        aria-label={label}
        data-testid={`tab-${item.key}`}
        className="flex min-h-16 flex-col items-center justify-end gap-0.5 px-1 pt-2 pb-2 text-[11px] font-semibold text-accent-strong"
      >
        <span className="-mt-6 flex h-[52px] w-[52px] items-center justify-center rounded-full bg-accent text-on-accent shadow-pop">
          <Icon size={24} />
        </span>
        <span>{label}</span>
      </Link>
    );
  }

  return (
    <Link
      href={item.href}
      aria-current={active ? "page" : undefined}
      data-testid={`tab-${item.key}`}
      className={cn(
        "flex min-h-16 flex-col items-center justify-center gap-0.5 px-1 py-2 text-[11px] font-medium",
        active ? "text-accent-strong font-semibold" : "text-txt-muted",
      )}
    >
      <Icon size={22} />
      <span>{label}</span>
    </Link>
  );
}

function OverflowRow({ item, label }: { item: NavItemDef; label: string }) {
  const Icon = item.icon;
  const className =
    "flex min-h-12 w-full items-center gap-3 rounded px-2 py-2 text-sm font-medium";

  if (item.soon) {
    return (
      <span
        aria-disabled="true"
        className={cn(className, "cursor-not-allowed text-txt-sub opacity-60")}
        data-testid={`more-${item.key}`}
      >
        <Icon size={20} className="shrink-0" />
        <span className="flex-1">{label}</span>
        <SoonBadge />
      </span>
    );
  }

  return (
    <Link
      href={item.href}
      className={cn(
        className,
        "text-txt-sub hover:bg-accent-soft hover:text-txt",
      )}
      data-testid={`more-${item.key}`}
    >
      <Icon size={20} className="shrink-0" />
      <span className="flex-1">{label}</span>
    </Link>
  );
}
