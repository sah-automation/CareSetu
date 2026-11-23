"use client";

// PHASE-2.6 T09 (#200): homepage section 1 - sticky public header
// (blueprint §3.1 row 1, §3.3). Wordmark left; Doctors/Labs/Chemists anchor
// nav (hidden below md per the mobile collapse rule); right cluster is the
// EN/Hindi toggle immediately left of the session-aware auth button (§3.4).
// The auth button reads truthfully from root AuthContext: Login -> /login
// when signed out, Dashboard -> role dashboard when signed in.
//
// #961: frosted sticky treatment per prototype homepage-resolved-v2 - translucent
// white + backdrop blur + hairline, 64px height, the bridge-cross mark inside
// its teal gradient tile, pill nav anchors and the segmented language toggle.

import Link from "next/link";

import { BrandMark } from "@/components/brand/BrandMark";
import { LangToggle } from "@/components/dashboard/LangToggle";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/lib/auth/AuthContext";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useRoleHomeHref } from "@/lib/auth/useRoleHomeHref";
import { useLang } from "@/lib/i18n/LangContext";

const NAV_ANCHORS = [
  { key: "doctors", href: "#doctors" },
  { key: "labs", href: "#labs" },
  { key: "chemists", href: "#chemists" },
] as const;

export function PublicHeader() {
  const { lang } = useLang();
  const t = STRINGS[lang].home;
  const { isAuthenticated } = useAuth();

  const authHref = useRoleHomeHref();
  const authLabel = isAuthenticated
    ? t.authButton.dashboard
    : t.authButton.login;

  return (
    <header
      data-testid="section-header"
      className="sticky top-0 z-40 border-b border-hairline-soft bg-white/85 backdrop-blur-md"
    >
      <div className="mx-auto flex h-16 w-full max-w-6xl items-center gap-2 px-4">
        <Link
          href="/"
          className="flex items-center gap-2.5 text-lg font-bold tracking-tight text-accent-strong"
        >
          <span
            aria-hidden="true"
            className="home-brand-tile flex h-9 w-9 shrink-0 items-center justify-center rounded-[11px]"
          >
            <BrandMark size={20} />
          </span>
          CareSetu
        </Link>
        <nav
          aria-label="Primary"
          className="ml-4 hidden items-center gap-1 md:flex"
        >
          {NAV_ANCHORS.map((anchor) => (
            <a
              key={anchor.key}
              className="rounded-full px-3.5 py-2 text-sm font-medium text-txt-sub transition-colors hover:bg-accent-soft hover:text-accent-strong focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent"
              href={anchor.href}
            >
              {t.nav[anchor.key]}
            </a>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-3">
          <LangToggle />
          <Button
            asChild
            size="sm"
            className="rounded-full px-4 text-sm font-semibold shadow-sm"
          >
            <Link href={authHref} data-testid="header-auth-button">
              {authLabel}
            </Link>
          </Button>
        </div>
      </div>
    </header>
  );
}
