// PHASE-2.6 T06 (#197): the role union gains "doctor" alongside the session
// model's existing roles. No staff session can select it yet (staff auth is
// Phase 5), but the nav-config and shell family are typed for all four roles
// so each config ships complete.
export type Role = "patient" | "doctor" | "partner" | "operator";

export const ROLE_LABELS: Record<Role, string> = {
  patient: "Patient",
  doctor: "Doctor",
  partner: "Partner",
  operator: "Operator",
};

export function roleLabel(role: Role): string {
  return ROLE_LABELS[role];
}

// Single role-validity predicate: ROLE_LABELS' keys are the authoritative
// set, so both the session coercion below and account-menu filtering derive
// from this one shape.
export function isAppRole(value: string): value is Role {
  return value in ROLE_LABELS;
}

// Session-selected roles arrive as free strings from /me; anything outside the
// union (or nothing) falls back to the patient shell.
export function resolveRole(value: string | null | undefined): Role {
  return value && isAppRole(value) ? value : "patient";
}

// Single source for each role's home surface - the Dashboard target of the
// §3.2 role-entry model and each NAV_CONFIG config's first destination.
// Kept dependency-free so session-aware public chrome (PHASE-2.6 T09 #200)
// can resolve dashboard targets without pulling the full nav graph (icons
// et al) into every page bundle. nav-config derives its home entries from
// this table, and a unit test pins the two together.
export const ROLE_HOME: Record<Role, string> = {
  patient: "/patient",
  doctor: "/doctor",
  partner: "/partner",
  operator: "/operator",
};
