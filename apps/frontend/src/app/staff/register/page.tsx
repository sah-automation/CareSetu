"use client";

// PHASE-2.6 T11 (#202): public provider-application surface
// (/staff/register, blueprint §4.3). Applicants are unauthenticated - this
// page is the public carve-out of the staff route group and sits outside the
// proxy's app-group matcher (src/proxy.ts), like /staff/login.
//
// The ?type= preset rides in from the homepage providers band and staff
// login CTAs (ticket 09's hrefs); the wizard normalizes it and defaults to
// doctor when absent or junk. Nothing here reads or mints session state.

import { Suspense } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";

import { ProviderRegisterWizard } from "@/components/auth/staff/ProviderRegisterWizard";
import { BrandMark } from "@/components/brand/BrandMark";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";

function RegisterView() {
  const { lang } = useLang();
  const t = STRINGS[lang].staffAuth.register;
  const searchParams = useSearchParams();

  return (
    <main className="mx-auto w-full max-w-xl px-4 pb-12 pt-[4vh]">
      <div className="flex items-center justify-between gap-4">
        <Link className="inline-flex items-center gap-2 text-txt" href="/">
          <BrandMark size={30} />
          <span className="text-lg font-bold">CareSetu</span>
        </Link>
      </div>
      <p className="mt-1 text-sm text-txt-muted">{t.subtitle}</p>

      <div className="mt-5">
        <ProviderRegisterWizard presetType={searchParams.get("type")} />
      </div>
    </main>
  );
}

export default function StaffRegisterPage() {
  // useSearchParams requires a Suspense boundary during static prerender.
  return (
    <Suspense fallback={null}>
      <RegisterView />
    </Suspense>
  );
}
