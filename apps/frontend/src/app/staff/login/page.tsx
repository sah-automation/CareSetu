"use client";

// PHASE-2.6 T10 (#201): the split-auth staff entry surface (/staff/login,
// blueprint §4.2). One professional login for doctor, lab, chemist and
// operator - composition and flow deliberately distinct from the patient OTP
// wizard. Pages only this phase: the form submits honestly (naming Phase 5),
// no session is ever minted here.
//
// Already-signed-in users with a staff role route immediately by the §4.5
// rules; the interim /choose-role entry stays until Phase 5 replaces staff
// auth (§4.6).

import { Suspense, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { BrandMark } from "@/components/brand/BrandMark";
import { StaffLoginForm } from "@/components/auth/staff/StaffLoginForm";
import type { StaffLoginRole } from "@/components/auth/staff/staffLoginState";
import { useAuth } from "@/lib/auth/AuthContext";
import {
  CHOOSE_ROLE_ROUTE,
  STAFF_LOGIN_SURFACE,
  isStaffRole,
  postLoginTarget,
} from "@/lib/auth/staff-routing";
import { providerRegisterHref } from "@/lib/directory/links";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";

function Wordmark() {
  return (
    <a className="inline-flex items-center gap-2 text-txt" href="/">
      <BrandMark size={30} />
      <span className="text-lg font-bold">CareSetu</span>
    </a>
  );
}

function StaffLoginView() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { lang } = useLang();
  const t = STRINGS[lang].staffAuth.login;
  const { user, isLoading, isAuthenticated } = useAuth();

  const returnTarget = searchParams.get("return");

  // #302: the surface is split by role - partners (default) get email +
  // password, operators (?role=operator) get phone + TOTP. The param is
  // supplied by the operator console redirect (#303); anything that is not
  // exactly "operator" falls back to the partner flow.
  const role: StaffLoginRole =
    searchParams.get("role") === "operator" ? "operator" : "partner";

  // A visitor who already holds a staff session lands by the same §4.5
  // routing matrix the sign-in itself will use - never on this form.
  const staffRoles = (user?.roles ?? []).filter(isStaffRole);
  useEffect(() => {
    if (isLoading || !isAuthenticated || staffRoles.length === 0) {
      return;
    }
    router.replace(
      postLoginTarget({
        surface: STAFF_LOGIN_SURFACE,
        roles: user?.roles,
        returnTarget,
      }),
    );
  }, [
    isLoading,
    isAuthenticated,
    staffRoles.length,
    router,
    user?.roles,
    returnTarget,
  ]);

  return (
    <main className="mx-auto w-full max-w-md px-4 pb-12 pt-[4vh]">
      <div className="text-center">
        <Wordmark />
        <p className="mt-1 text-sm text-txt-muted">{t.subtitle}</p>
      </div>

      <div className="mt-6 rounded-lg border border-hairline bg-surface p-6 shadow-card">
        <h1 className="mb-4 text-xl font-bold">{t.heading}</h1>
        <StaffLoginForm role={role} />
      </div>

      <hr className="my-6 border-hairline-soft" />

      <div className="text-center">
        <p className="font-semibold">{t.newHereTitle}</p>
        <p className="mt-1 text-sm text-txt-muted">{t.newHereBody}</p>
        <div className="mt-3 flex flex-wrap justify-center gap-2">
          <a
            href={providerRegisterHref("doctor")}
            data-testid="register-doctor"
            className="rounded-md border border-hairline bg-surface px-3 py-1.5 text-sm"
          >
            {t.registerDoctor}
          </a>
          <a
            href={providerRegisterHref("lab")}
            data-testid="register-lab"
            className="rounded-md border border-hairline bg-surface px-3 py-1.5 text-sm"
          >
            {t.registerLab}
          </a>
          <a
            href={providerRegisterHref("chemist")}
            data-testid="register-chemist"
            className="rounded-md border border-hairline bg-surface px-3 py-1.5 text-sm"
          >
            {t.registerChemist}
          </a>
        </div>
      </div>

      <div className="mt-6 space-y-2 text-center text-xs text-txt-muted">
        <p>{t.noRolePickerNote}</p>
        <p>
          {t.interimNote}{" "}
          <a
            href={CHOOSE_ROLE_ROUTE}
            className="underline"
            data-testid="choose-role-link"
          >
            {t.chooseRoleLink}
          </a>
        </p>
      </div>
    </main>
  );
}

export default function StaffLoginPage() {
  // useSearchParams requires a Suspense boundary during static prerender.
  return (
    <Suspense fallback={null}>
      <StaffLoginView />
    </Suspense>
  );
}
