"use client";

// PHASE-2.6 T09 (#200): session-aware landing target for public primary CTAs
// (blueprint §3.2 role-entry model). An authenticated visitor's Get started /
// Dashboard controls land on their role's dashboard home; everyone else gets
// the patient login surface. Shared by the header, hero, and final CTA so the
// session rule lives in exactly one place.

import { resolveRole, ROLE_HOME } from "@/components/dashboard/types";
import { useAuth } from "@/lib/auth/AuthContext";
import { PATIENT_LOGIN_ROUTE } from "@/lib/directory/links";

export function useRoleHomeHref(): string {
  const { isAuthenticated, selectedRole } = useAuth();
  return isAuthenticated
    ? ROLE_HOME[resolveRole(selectedRole)]
    : PATIENT_LOGIN_ROUTE;
}
