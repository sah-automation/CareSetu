"use client";

// PHASE-2.6 T06 (#197): shared nav-config item renderer for the text-bearing
// variants (full-shell sidebar, patient desktop top-nav). Mobile tab-bar
// columns render their own compact markup in BottomTabs. Labels resolve
// through the i18n engine (blueprint §9.2); Soon entries render dimmed,
// non-interactive, badged (§2.7).

import Link from "next/link";
import { usePathname } from "next/navigation";

import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import { cn } from "@/lib/utils";

import type { NavItemDef } from "./nav-config";

export type NavVariant = "sidebar" | "topnav";

const VARIANT_BASE: Record<NavVariant, string> = {
  sidebar:
    "flex min-h-11 items-center gap-3 whitespace-nowrap rounded px-3 py-2 text-sm",
  topnav: "flex items-center gap-1.5 rounded-full px-3 py-1.5 text-sm",
};

export function SoonBadge() {
  return (
    <span
      className="rounded border border-dashed border-hairline bg-hairline-soft px-1.5 py-0.5 text-[10px] font-medium tracking-wide text-txt-muted uppercase"
      data-testid="soon-badge"
    >
      Soon
    </span>
  );
}

export function CountPill({ count }: { count: number }) {
  return (
    <span
      className="ml-auto rounded-full bg-accent px-1.5 text-[11px] leading-5 font-bold text-on-accent"
      data-testid="count-pill"
    >
      {count}
    </span>
  );
}

interface NavItemLinkProps {
  item: NavItemDef;
  variant: NavVariant;
  // Collapsed full-shell sidebar: icon-only columns (labels, badges, and
  // count pills hide, mirroring the prototype's collapsed-sidebar rules).
  hideLabel?: boolean;
}

export function NavItemLink({
  item,
  variant,
  hideLabel = false,
}: NavItemLinkProps) {
  const pathname = usePathname();
  const { lang } = useLang();
  const label = STRINGS[lang].nav[item.labelKey];
  const Icon = item.icon;
  const active = !item.soon && pathname === item.href;

  const className = cn(
    VARIANT_BASE[variant],
    active
      ? "bg-accent-soft font-semibold text-accent-strong"
      : "font-medium text-txt-sub hover:bg-accent-soft hover:text-txt",
    hideLabel && "justify-center px-0",
  );

  const body = (
    <>
      <Icon size={variant === "sidebar" ? 20 : 16} className="shrink-0" />
      {!hideLabel && (
        <>
          <span className="min-w-0 flex-1 truncate">{label}</span>
          {item.soon && <SoonBadge />}
          {typeof item.count === "number" && !item.soon && (
            <CountPill count={item.count} />
          )}
        </>
      )}
    </>
  );

  if (item.soon) {
    return (
      <span
        aria-disabled="true"
        className={cn(className, "cursor-not-allowed opacity-60")}
        data-soon="true"
        data-testid={`nav-${item.key}`}
      >
        {body}
      </span>
    );
  }

  return (
    <Link
      href={item.href}
      aria-current={active ? "page" : undefined}
      className={className}
      data-active={active || undefined}
      data-testid={`nav-${item.key}`}
    >
      {body}
    </Link>
  );
}
