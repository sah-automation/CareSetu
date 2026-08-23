"use client";

// PHASE-2.6 T10 (#201): the SCOPED staff-role picker (/staff/roles,
// blueprint §4.5). Appears only for accounts holding more than one staff
// role; patient sessions never see it and patient roles never render here.
// Single-staff-role accounts are bounced straight to their home, and the
// interim /choose-role entry stays untouched until Phase 5 deletes it (§4.6).

import { useEffect } from "react";
import { useRouter } from "next/navigation";

import {
  isStaffRole,
  STAFF_LOGIN_ROUTE,
  type StaffRole,
} from "@/lib/auth/staff-routing";
import { useAuth } from "@/lib/auth/AuthContext";
import { readSelectedRole, saveSelectedRole } from "@/lib/auth/session";
import { ROLE_HOME, roleLabel } from "@/components/dashboard/types";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { useLang } from "@/lib/i18n/LangContext";

const ROLE_DESC_KEYS: Record<
  StaffRole,
  "doctorDesc" | "partnerDesc" | "operatorDesc"
> = {
  doctor: "doctorDesc",
  partner: "partnerDesc",
  operator: "operatorDesc",
};

export default function StaffRolesPage() {
  const router = useRouter();
  const { lang } = useLang();
  const t = STRINGS[lang].staffAuth.picker;
  const { user, isLoading, isAuthenticated, switchRole } = useAuth();

  // Stable reference so the redirect effect does not churn every render.
  const staffRoles = (user?.roles ?? []).filter(isStaffRole);

  useEffect(() => {
    if (isLoading) {
      return;
    }
    if (!isAuthenticated) {
      router.replace(STAFF_LOGIN_ROUTE);
      return;
    }
    if (staffRoles.length === 0) {
      // No staff role to scope to; the interim entry sorts out whatever the
      // session does hold.
      router.replace("/choose-role");
      return;
    }
    if (staffRoles.length === 1) {
      const home = ROLE_HOME[staffRoles[0]];
      saveSelectedRole(home.slice(1));
      router.replace(home);
      return;
    }
    // Multi-role: a previously saved valid staff choice short-circuits back
    // to its console, mirroring the interim choose-role contract.
    const saved = readSelectedRole();
    if (saved && isStaffRole(saved) && staffRoles.includes(saved)) {
      router.replace(ROLE_HOME[saved]);
    }
  }, [isLoading, isAuthenticated, router, staffRoles]);

  function choose(role: (typeof staffRoles)[number]) {
    switchRole(role);
    router.replace(ROLE_HOME[role]);
  }

  if (isLoading || !isAuthenticated || staffRoles.length <= 1) {
    return null;
  }

  return (
    <main className="mx-auto w-full max-w-md px-4 pb-12 pt-[8vh]">
      <section
        aria-labelledby="staff-roles-title"
        className="rounded-lg border border-hairline bg-surface p-6 shadow-card"
        data-testid="staff-role-picker"
      >
        <h1 id="staff-roles-title" className="text-xl font-bold">
          {t.title}
        </h1>
        <p className="mt-1 text-sm text-txt-muted">{t.sub}</p>

        <div className="mt-4 grid gap-3">
          {staffRoles.map((role) => (
            <button
              key={role}
              type="button"
              onClick={() => choose(role)}
              data-testid={`pick-${role}`}
              className="rounded-lg border border-hairline bg-surface px-4 py-3 text-left shadow-card transition-colors hover:border-accent-border"
            >
              <span className="block font-semibold">{roleLabel(role)}</span>
              <span className="mt-0.5 block text-sm text-txt-muted">
                {t[ROLE_DESC_KEYS[role]]}
              </span>
            </button>
          ))}
        </div>
      </section>
    </main>
  );
}
