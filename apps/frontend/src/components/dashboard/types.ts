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
