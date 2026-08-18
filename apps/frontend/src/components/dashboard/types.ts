export type Role = "patient" | "partner" | "operator";

export const ROLE_LABELS: Record<Role, string> = {
  patient: "Patient",
  partner: "Partner",
  operator: "Operator",
};

export const SIDEBAR_WIDTH_EXPANDED = "w-60";
export const SIDEBAR_WIDTH_COLLAPSED = "w-16";
export const SIDEBAR_MARGIN_EXPANDED = "pl-60";
export const SIDEBAR_MARGIN_COLLAPSED = "pl-16";

export function roleLabel(role: Role): string {
  return ROLE_LABELS[role];
}
