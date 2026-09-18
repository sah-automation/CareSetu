// PHASE-2.6 T10 (#201): the post-login routing matrix (blueprint §4.4/§4.5)
// pinned as a table of cases. This is the done-verify "routing logic per
// login surface" suite.

import { describe, expect, it } from "vitest";

import {
  CHOOSE_ROLE_ROUTE,
  PARTNER_PENDING_ROUTE,
  PARTNER_REJECTED_ROUTE,
  PATIENT_LOGIN_SURFACE,
  SCOPED_ROLE_PICKER_ROUTE,
  STAFF_LOGIN_SURFACE,
  partnerStatusToState,
  postLoginTarget,
} from "./staff-routing";
import { PATIENT_HOME } from "./return-url";

describe("postLoginTarget", () => {
  it("lands the patient surface on the patient home without a return target", () => {
    expect(postLoginTarget({ surface: PATIENT_LOGIN_SURFACE })).toBe(
      PATIENT_HOME,
    );
  });

  it.each([
    ["no roles at all", undefined],
    ["an empty roles list", []],
    ["patient-only roles", ["patient"]],
    ["unknown role spellings only", ["warp_drive_operator"]],
  ])(
    "sends staff-surface sessions with %s to the interim choose-role entry",
    (_label, roles) => {
      expect(postLoginTarget({ surface: STAFF_LOGIN_SURFACE, roles })).toBe(
        CHOOSE_ROLE_ROUTE,
      );
    },
  );

  it.each([["doctor" as const], ["partner" as const], ["operator" as const]])(
    "lands a single-%s staff account straight on its home",
    (role) => {
      expect(
        postLoginTarget({ surface: STAFF_LOGIN_SURFACE, roles: [role] }),
      ).toBe(`/${role}`);
    },
  );

  it("keeps a mixed single-staff-role session (staff + patient) on the staff home", () => {
    expect(
      postLoginTarget({
        surface: STAFF_LOGIN_SURFACE,
        roles: ["patient", "doctor"],
      }),
    ).toBe("/doctor");
  });

  it("routes multi-staff-role accounts to the scoped picker", () => {
    expect(
      postLoginTarget({
        surface: STAFF_LOGIN_SURFACE,
        roles: ["doctor", "operator"],
      }),
    ).toBe(SCOPED_ROLE_PICKER_ROUTE);
  });

  it("scopes the picker decision to staff roles even when patient is among them", () => {
    // One staff role + patient = still a direct staff landing, not a picker.
    expect(
      postLoginTarget({
        surface: STAFF_LOGIN_SURFACE,
        roles: ["patient", "partner", "chemist"],
      }),
    ).toBe("/partner");
  });

  it.each([
    ["pending", PARTNER_PENDING_ROUTE],
    ["rejected", PARTNER_REJECTED_ROUTE],
  ] as const)(
    "diverts a %s partner to the status screen before any role rule",
    (state, expected) => {
      expect(
        postLoginTarget({
          surface: STAFF_LOGIN_SURFACE,
          roles: ["partner"],
          partnerState: state,
        }),
      ).toBe(expected);
      // The override holds for multi-role accounts too.
      expect(
        postLoginTarget({
          surface: STAFF_LOGIN_SURFACE,
          roles: ["partner", "operator"],
          partnerState: state,
        }),
      ).toBe(expected);
    },
  );

  it("honors a deep-link return inside the single staff role's territory", () => {
    expect(
      postLoginTarget({
        surface: STAFF_LOGIN_SURFACE,
        roles: ["doctor"],
        returnTarget: "/doctor/cases/42",
      }),
    ).toBe("/doctor/cases/42");
  });

  it("honors a return into the scoped picker for multi-role accounts", () => {
    expect(
      postLoginTarget({
        surface: STAFF_LOGIN_SURFACE,
        roles: ["doctor", "operator"],
        returnTarget: SCOPED_ROLE_PICKER_ROUTE,
      }),
    ).toBe(SCOPED_ROLE_PICKER_ROUTE);
  });

  it.each([
    ["another group's territory", "/patient/inbox"],
    ["a foreign role's home tree", "/doctor/cases/1"],
    ["an off-site absolute URL", "https://evil.example.test/deep"],
    ["a protocol-relative target", "//evil.example.test"],
  ])("ignores a stale return pointing at %s", (_label, returnTarget) => {
    expect(
      postLoginTarget({
        surface: STAFF_LOGIN_SURFACE,
        roles: ["operator"],
        returnTarget,
      }),
    ).toBe("/operator");
  });

  it("never lets a staff-surface return cross into the patient app via a bare home path", () => {
    expect(
      postLoginTarget({
        surface: STAFF_LOGIN_SURFACE,
        roles: ["operator"],
        returnTarget: PATIENT_HOME,
      }),
    ).toBe("/operator");
  });
});

describe("partnerStatusToState", () => {
  it.each([
    ["Registered", "pending"],
    ["Under Verification", "pending"],
    ["Rejected", "rejected"],
  ] as const)(
    "maps partner status %s to routing state %s",
    (status, expected) => {
      expect(partnerStatusToState(status)).toBe(expected);
    },
  );

  it("yields no override for an active partner", () => {
    expect(partnerStatusToState("Active")).toBeUndefined();
  });
});

describe("partner status landing matrix", () => {
  // The full status -> landing contract for §4.4 (F014-T09a): a pending /
  // under-verification partner sits on the waiting screen, a rejected partner
  // on the rejection-reason screen, and an active partner lands on the role
  // home via normal routing.
  it.each([
    ["Registered", "pending", PARTNER_PENDING_ROUTE],
    ["Under Verification", "pending", PARTNER_PENDING_ROUTE],
    ["Rejected", "rejected", PARTNER_REJECTED_ROUTE],
  ] as const)(
    "lands a %s partner on %s via the %s target",
    (_status, state, expected) => {
      expect(
        postLoginTarget({
          surface: STAFF_LOGIN_SURFACE,
          roles: ["partner"],
          partnerState: state,
        }),
      ).toBe(expected);
    },
  );

  it("lands an active partner on the partner home via normal role routing", () => {
    expect(
      postLoginTarget({
        surface: STAFF_LOGIN_SURFACE,
        roles: ["partner"],
        partnerState: partnerStatusToState("Active"),
      }),
    ).toBe("/partner");
  });

  it("holds the partner-state override for multi-role accounts", () => {
    expect(
      postLoginTarget({
        surface: STAFF_LOGIN_SURFACE,
        roles: ["partner", "operator"],
        partnerState: "pending",
        returnTarget: "/operator",
      }),
    ).toBe(PARTNER_PENDING_ROUTE);
  });
});

describe("return target + partner state matrix (F014-T09b)", () => {
  it("honors a deep-link return inside its own territory for an active partner", () => {
    expect(
      postLoginTarget({
        surface: STAFF_LOGIN_SURFACE,
        roles: ["partner"],
        partnerState: undefined,
        returnTarget: "/partner/orders/42",
      }),
    ).toBe("/partner/orders/42");
  });

  it.each([
    ["pending", PARTNER_PENDING_ROUTE],
    ["rejected", PARTNER_REJECTED_ROUTE],
  ] as const)(
    "routes a %s partner to its status screen even when the return points into the partner territory",
    (state, expected) => {
      expect(
        postLoginTarget({
          surface: STAFF_LOGIN_SURFACE,
          roles: ["partner"],
          partnerState: state,
          returnTarget: "/partner/orders/42",
        }),
      ).toBe(expected);
    },
  );

  it("lands an active partner on the partner home for an off-site return after sanitize fallback", () => {
    expect(
      postLoginTarget({
        surface: STAFF_LOGIN_SURFACE,
        roles: ["partner"],
        returnTarget: "https://evil.example.test/phish",
      }),
    ).toBe("/partner");
  });

  it("ignores a return pointing into another staff group's territory for a partner", () => {
    expect(
      postLoginTarget({
        surface: STAFF_LOGIN_SURFACE,
        roles: ["partner"],
        returnTarget: "/doctor/cases/9",
      }),
    ).toBe("/partner");
  });
});
