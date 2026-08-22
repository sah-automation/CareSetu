"use client";

// PHASE-2.6 T09 (#200): homepage section 1 - sticky public header
// (blueprint §3.1 row 1, §3.3). Wordmark left; Doctors/Labs/Chemists anchor
// nav (hidden below md per the mobile collapse rule); right cluster is the
// EN/Hindi toggle immediately left of the session-aware auth button (§3.4).
// The auth button reads truthfully from root AuthContext: Login -> /login
// when signed out, Dashboard -> role dashboard when signed in.

import Link from "next/link";

import { LangToggle } from "@/components/dashboard/LangToggle";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/lib/auth/AuthContext";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useRoleHomeHref } from "@/lib/auth/useRoleHomeHref";
import { useLang } from "@/lib/i18n/LangContext";

function Wordmark() {
  return (
    <svg
      width="26"
      height="26"
      viewBox="0 0 32 32"
      fill="none"
      aria-hidden="true"
    >
      <path
        d="M8 24v-8M24 24v-8"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
      />
      <path
        d="M8 16Q16 5 24 16"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
      />
      <path
        d="M4 27h24"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
      />
    </svg>
  );
}

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
      className="sticky top-0 z-40 border-b border-hairline bg-surface"
    >
      <div className="mx-auto flex h-14 w-full max-w-6xl items-center gap-4 px-4">
        <Link
          href="/"
          className="flex items-center gap-2 text-lg font-semibold text-accent"
        >
          <Wordmark />
          CareSetu
        </Link>
        <nav
          aria-label="Primary"
          className="hidden items-center gap-5 text-sm text-txt-sub md:flex"
        >
          <a className="hover:text-accent" href="#doctors">
            {t.nav.doctors}
          </a>
          <a className="hover:text-accent" href="#labs">
            {t.nav.labs}
          </a>
          <a className="hover:text-accent" href="#chemists">
            {t.nav.chemists}
          </a>
        </nav>
        <div className="ml-auto flex items-center gap-3">
          <LangToggle />
          <Button asChild size="sm">
            <Link href={authHref} data-testid="header-auth-button">
              {authLabel}
            </Link>
          </Button>
        </div>
      </div>
    </header>
  );
}
