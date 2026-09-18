// PHASE-2.6 T10 (#201): post-login landing rules, extracted as a pure module
// so the routing matrix (blueprint §4.4/§4.5) is unit-testable without a DOM.
// The rule of record: route by the LOGIN SURFACE USED - the patient OTP wizard
// lands in the patient app; staff login lands on the account's staff-role
// home, or the scoped picker when it holds several staff roles. Partner
// verification state overrides both (§4.4): a pending/rejected partner lands
// on its status screen instead of any channel home.

import { sanitizeReturnTarget } from "@/lib/auth/return-url";
import { isAppRole, ROLE_HOME, type Role } from "@/components/dashboard/types";
import type { PartnerStatus, PartnerType } from "@/lib/partner/api";
import { fetchPartnerMe } from "@/lib/partner/api";

// Entry surfaces (blueprint §4.x). The patient surface keeps its Phase 2.5
// behavior; STAFF_LOGIN_ROUTE is this ticket's page.
export const PATIENT_LOGIN_SURFACE = "patient" as const;
export const STAFF_LOGIN_SURFACE = "staff" as const;
export type LoginSurface =
  | typeof PATIENT_LOGIN_SURFACE
  | typeof STAFF_LOGIN_SURFACE;

export const STAFF_LOGIN_ROUTE = "/staff/login";

// Scoped staff-role picker for multi-staff-role accounts (§4.5). Patient
// sessions never see it; the interim /choose-role entry stays until Phase 5
// replaces staff auth (§4.6).
export const SCOPED_ROLE_PICKER_ROUTE = "/staff/roles";

// Interim cross-role entry retained until Phase 5 (§4.6).
export const CHOOSE_ROLE_ROUTE = "/choose-role";

// Status screens inside the partner channel group (full shell + session
// guard via the /partner/:path* proxy matcher).
export const PARTNER_PENDING_ROUTE = "/partner/status/pending";
export const PARTNER_REJECTED_ROUTE = "/partner/status/rejected";

// Partner lifecycle slice the client can act on (§4.4). Absent = active or
// not a partner - normal routing applies.
export type PartnerStatusState = "pending" | "rejected";

/**
 * Map the partner API status vocabulary to the post-login routing state
 * (`PartnerStatusState`). `Active` yields no override so a live partner lands
 * by the normal role rule on the partner home.
 */
export function partnerStatusToState(
  status: PartnerStatus,
): PartnerStatusState | undefined {
  if (status === "Rejected") {
    return "rejected";
  }
  if (status === "Registered" || status === "Under Verification") {
    return "pending";
  }
  return undefined;
}

/**
 * The caller's partner routing inputs, reduced from one /v1/partner/me read:
 * `partnerState` drives the status-screen override (§4.4) and `partnerType`
 * decides whether an active doctor lands on the doctor console instead of the
 * generic partner home (#475). `Active` yields no state override while the
 * type stays available, so doctor-ness never needs a second round-trip.
 */
export interface PartnerRouteState {
  partnerState: PartnerStatusState | undefined;
  partnerType: PartnerType | undefined;
}

/**
 * Resolve the caller's partner routing inputs from their own fetched status.
 * Shared by every landing seam (fresh-login and already-signed-in) so the
 * status read + map + degradation path stays in one place, and a non-partner
 * session short-circuits without any /v1/partner/me read. Returns
 * { undefined, undefined } (fall back to role routing) when the caller is not
 * a partner or the status cannot be read; the failure is logged, never
 * silently swallowed.
 */
export async function fetchPartnerRouteState(
  roles: string[] | undefined,
): Promise<PartnerRouteState> {
  if (!roles?.includes("partner")) {
    return { partnerState: undefined, partnerType: undefined };
  }
  try {
    const me = await fetchPartnerMe();
    return {
      partnerState: partnerStatusToState(me.status),
      partnerType: me.partner_type,
    };
  } catch (error) {
    console.error(
      "[staff-routing] partner status unreadable; routing by role",
      error,
    );
    return { partnerState: undefined, partnerType: undefined };
  }
}

// Staff roles are every app role except patient; derived from ROLE_LABELS'
// authoritative key set so a new staff role needs no edit here.
const STAFF_ROLES: readonly Role[] = (Object.keys(ROLE_HOME) as Role[]).filter(
  (role) => role !== "patient",
);

function staffRolesOf(roles: string[] | undefined): Role[] {
  if (!roles) {
    return [];
  }
  return STAFF_ROLES.filter((role) => roles.includes(role));
}

export interface PostLoginInput {
  /** Which sign-in surface the user just completed (blueprint §4.5). */
  surface: LoginSurface;
  /** Raw role strings from the session (`user.roles`); free strings. */
  roles?: string[];
  /** Partner verification state when known (Phase 5 wires this). */
  partnerState?: PartnerStatusState;
  /** The partner's `partner_type` (doctor/lab/chemist) when known (#475). A
   * doctor partner lands on the doctor console; lab/chemist stay on /partner. */
  partnerType?: PartnerType;
  /**
   * Sanitized-or-raw `?return=` target. Honored only when it stays inside the
   * landing territory the surface+roles already grant, so a stale param can
   * never cross a group boundary.
   */
  returnTarget?: string | null;
}

function returnAllowed(
  returnTarget: string,
  roles: Role[],
  partnerType: PartnerType | undefined,
): boolean {
  const homes = roles.map((role) => ROLE_HOME[role]);
  // An active doctor partner's territory additionally covers the doctor
  // console (blueprint §6.1), so a proxied /doctor deep link round-trips to
  // the console item instead of being dropped.
  if (partnerType === "doctor") {
    homes.push(ROLE_HOME.doctor);
  }
  if (roles.length > 1) {
    homes.push(SCOPED_ROLE_PICKER_ROUTE);
  }
  return homes.some(
    (home) => returnTarget === home || returnTarget.startsWith(`${home}/`),
  );
}

/**
 * Where a just-completed sign-in lands.
 *
 * Patient surface: unchanged Phase 2.5 contract - sanitized return target,
 * else the patient app home.
 * Staff surface (in order): partner status screen (§4.4 override), deep-link
 * return into an owned territory, single staff-role home (active doctors land
 * on the doctor console, #475), scoped picker for several staff roles, interim
 * /choose-role when no staff role resolves.
 */
export function postLoginTarget(input: PostLoginInput): string {
  if (input.surface === PATIENT_LOGIN_SURFACE) {
    return sanitizeReturnTarget(input.returnTarget);
  }

  const roles = staffRolesOf(input.roles);

  if (input.partnerState === "pending") {
    return PARTNER_PENDING_ROUTE;
  }
  if (input.partnerState === "rejected") {
    return PARTNER_REJECTED_ROUTE;
  }

  if (input.returnTarget) {
    // Sanitize FIRST (shared guard rejects off-site/protocol-relative
    // targets, falling back to the patient home), then check territory - a
    // rejected target never matches a staff territory and falls through.
    const target = sanitizeReturnTarget(input.returnTarget);
    if (returnAllowed(target, roles, input.partnerType)) {
      return target;
    }
  }

  if (roles.length === 1) {
    const role = roles[0];
    // Doctor-ness is a partner_type, never an iam role (the grants table
    // only allows patient|partner|operator), so an active doctor partner
    // lands on the doctor console via type rather than a doctor role.
    if (role === "partner" && input.partnerType === "doctor") {
      return ROLE_HOME.doctor;
    }
    return ROLE_HOME[role];
  }
  if (roles.length > 1) {
    return SCOPED_ROLE_PICKER_ROUTE;
  }
  // A session without staff roles has no staff landing; the interim entry
  // sorts out whatever roles it does hold (patient-only accounts included).
  return CHOOSE_ROLE_ROUTE;
}

// Re-exported so consumers (and tests) share one vocabulary for "is this a
// staff card" instead of re-filtering raw strings ad hoc.
export type StaffRole = Exclude<Role, "patient">;

export function isStaffRole(value: string): value is StaffRole {
  return isAppRole(value) && value !== "patient";
}
