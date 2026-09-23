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
import { ChevronRight, LogOut, MoreHorizontal } from "lucide-react";

import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Avatar } from "@/components/ui/avatar";
import { useAuth } from "@/lib/auth/AuthContext";
import { useOptionalProfile } from "@/lib/profile/ProfileContext";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";
import { cn } from "@/lib/utils";

import { NAV_CONFIG, splitMobileTabs } from "./nav-config";
import { CountPill, SoonBadge } from "./NavItemLink";
import type { NavItemDef } from "./nav-config";
import type { Role } from "./types";

export function BottomTabs({
  role,
  items,
}: {
  role: Role;
  // Render-time nav override: the AppShell attaches the open-cases count to
  // the doctor Cases item here (#483), which the tab column and More sheet
  // render as a badge. Defaults to the static NAV_CONFIG.
  items?: NavItemDef[];
}) {
  const pathname = usePathname();
  const { lang } = useLang();
  const [moreOpen, setMoreOpen] = useState(false);
  const config = items ?? NAV_CONFIG[role];
  const { tabs, overflow, hasMore } = splitMobileTabs(config);
  const strings = STRINGS[lang].nav;

  // #525 mobile account surface: for the patient role the More sheet opens
  // with an account card (avatar, name or masked phone, full E.164 phone)
  // that navigates to Profile & Settings, plus a red Log out row. Staff
  // shells keep their overflow rows unchanged - and since the ProfileProvider
  // only mounts under the patient group, useOptionalProfile() is null there
  // anyway.
  const { user, logout } = useAuth();
  const profile = useOptionalProfile();
  const isPatient = role === "patient";

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
            {isPatient && (
              <AccountCard
                name={profile?.savedProfile?.name}
                photoRef={profile?.savedProfile?.photo_ref}
                identity={accountIdentity(profile?.savedProfile?.name, user)}
                fullPhone={user?.phone}
                profileSettingsLabel={strings.profileSettings}
                onNavigate={() => setMoreOpen(false)}
              />
            )}
            {overflow.map((item) => (
              <OverflowRow
                key={item.key}
                item={item}
                label={strings[item.labelKey]}
                onNavigate={() => setMoreOpen(false)}
              />
            ))}
            {isPatient && (
              <LogoutRow
                label={strings.logOut}
                onLogout={() => {
                  setMoreOpen(false);
                  logout();
                }}
              />
            )}
          </div>
        </SheetContent>
      </Sheet>
    </>
  );
}

// #525: the mobile account card top of the More sheet. Shares the stale-
// session degrade with the desktop menu: a missing phone falls back to
// "Subject #id" rather than crashing (#199 convention).
function accountIdentity(
  savedName: string | null | undefined,
  user: { phone?: string; id: number } | null,
): string {
  const trimmedName = savedName?.trim();
  if (trimmedName) return trimmedName;
  if (user?.phone) return maskedPhone(user.phone);
  return user ? `Subject #${user.id}` : "";
}

// Display-only mask per spec #520: "+91 XXXXXX1234" - the country prefix
// (E.164, CONTEXT pins +91) plus the last four digits survive, everything
// else is X. Values too short to be an E.164 number render verbatim instead
// of letting local digits masquerade as a country code.
const MASK = "XXXXXX";
const E164_COUNTRY_DIGITS = 2;
const VISIBLE_SUFFIX_DIGITS = 4;

function maskedPhone(phone: string): string {
  const digits = phone.replace(/\D/g, "");
  if (digits.length < 10) return phone;
  return `+${digits.slice(0, E164_COUNTRY_DIGITS)} ${MASK}${digits.slice(
    -VISIBLE_SUFFIX_DIGITS,
  )}`;
}

// Export for unit tests: the mask format is an explicit acceptance criterion
// of #525 and this pure helper is the single source of it.
export { maskedPhone };

function AccountCard({
  name,
  photoRef,
  identity,
  fullPhone,
  profileSettingsLabel,
  onNavigate,
}: {
  name?: string | null;
  photoRef?: string | null;
  identity: string;
  fullPhone?: string;
  profileSettingsLabel: string;
  onNavigate: () => void;
}) {
  return (
    <Link
      href="/patient/profile"
      onClick={onNavigate}
      data-testid="more-account-card"
      className="flex min-h-12 items-center gap-3 rounded-lg px-2 py-2 transition-colors hover:bg-accent-soft focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
    >
      <Avatar
        photoRef={photoRef}
        name={name}
        className="h-11 w-11 shrink-0 bg-accent-soft text-base font-semibold text-accent-strong"
      />
      <span className="min-w-0 flex-1">
        <span
          className="block truncate text-sm font-semibold text-txt"
          data-testid="more-account-identity"
        >
          {identity}
        </span>
        {fullPhone && (
          <span className="block truncate text-xs text-txt-muted">
            {fullPhone}
          </span>
        )}
      </span>
      <span className="flex shrink-0 items-center gap-0.5 text-xs font-medium text-accent">
        {profileSettingsLabel}
        <ChevronRight size={16} aria-hidden="true" />
      </span>
    </Link>
  );
}

function LogoutRow({
  label,
  onLogout,
}: {
  label: string;
  onLogout: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onLogout}
      data-testid="more-logout"
      className="flex min-h-12 items-center gap-3 rounded-lg px-2 py-2 text-sm font-medium text-danger transition-colors hover:bg-danger-soft focus:outline-none focus-visible:ring-2 focus-visible:ring-danger"
    >
      <LogOut size={20} aria-hidden="true" className="shrink-0" />
      <span className="flex-1 text-left">{label}</span>
    </button>
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
      <span className="relative">
        <Icon size={22} />
        {typeof item.count === "number" && (
          <span
            data-testid="count-pill"
            className="absolute -top-1.5 -right-2 rounded-full bg-accent px-1 text-[10px] leading-4 font-bold text-on-accent"
          >
            {item.count}
          </span>
        )}
      </span>
      <span>{label}</span>
    </Link>
  );
}

function OverflowRow({
  item,
  label,
  onNavigate,
}: {
  item: NavItemDef;
  label: string;
  // Fires when a live row navigates so the sheet closes on the way out
  // (#524): the Radix dialog is state-driven and would otherwise stay open
  // over the destination page.
  onNavigate: () => void;
}) {
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
      onClick={onNavigate}
      className={cn(
        className,
        "text-txt-sub hover:bg-accent-soft hover:text-txt",
      )}
      data-testid={`more-${item.key}`}
    >
      <Icon size={20} className="shrink-0" />
      <span className="flex-1">{label}</span>
      {typeof item.count === "number" && <CountPill count={item.count} />}
    </Link>
  );
}
