// PRD trace: FEAT-005 (Provider Profiles and Credential Display).
// #623 (F19): the doctor profile view's runtime guard.
//
// `fetchDoctorProfile` runs every answer through `isDoctorProfileView` before the
// rest of the app is allowed to read it, so this guard is the boundary between a
// typed contract and an untyped JSON body. It had grown from a handful of checks to
// twenty-four `in` tests and four array tests with no test of its own, which means
// every field a ticket added to `DoctorProfileView` widened the guard by editing a
// condition no suite would notice if it were wrong in the permissive direction.
//
// The direction that matters is the one a type-only reviewer cannot see: a guard
// that accepts a body missing a field it claims to require passes every
// happy-path test in the app and then hands `undefined` to a component. So each
// case below is a REMOVAL - the shape minus one field - and the assertion is a
// refusal.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fetchDoctorProfile } from "./api";
import { request } from "@/lib/request";

vi.mock("@/lib/request", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/request")>();
  return { ...mod, request: vi.fn() };
});

const ask = vi.mocked(request);

/** A complete, valid answer. Every case is this with one thing taken away. */
function completeView(): Record<string, unknown> {
  return {
    partner_id: "partner-1",
    photo_ref: null,
    practice_name: "Sunrise Clinic",
    clinic_name: null,
    specialties: ["General Physician"],
    verified: true,
    practice_address: "Main Road, Daltonganj",
    address_line: "Main Road",
    landmark: null,
    locality: "Daltonganj",
    city: "Daltonganj",
    pin_code: "822101",
    practice_latitude: 24.4166,
    practice_longitude: 85.3666,
    area: "Daltonganj",
    languages: ["Hindi"],
    experience_years: 12,
    about: "Twelve years of primary care.",
    consultation_fee: 40000,
    consulting_days: ["mon"],
    consulting_hours: "9am-5pm",
    credentials: [
      { credential_type: "medical", status: "verified", expires_at: null },
    ],
    notification_preferences: { new_consultations: true },
  };
}

/** Every field the guard names, so the removal loop below cannot silently skip one. */
const REQUIRED_KEYS = Object.keys(completeView());

/**
 * Ask the real read path to accept a body, and report whether it refused.
 *
 * Going through `fetchDoctorProfile` rather than importing the guard is deliberate:
 * the guard is module-private, and this is the only route a caller has to it - so
 * the only thing worth pinning is the behaviour a caller can observe. A refusal
 * arrives as a thrown `Error` carrying the guard's message; anything else means the
 * body was waved through.
 */
async function refuses(shape: unknown): Promise<boolean> {
  ask.mockResolvedValue(shape);
  try {
    await fetchDoctorProfile();
    return false;
  } catch (error) {
    expect(String(error)).toContain("unexpected doctor profile shape");
    return true;
  }
}

beforeEach(() => {
  ask.mockReset();
});

afterEach(() => {
  ask.mockReset();
});

describe("the doctor profile view guard (#623 F19)", () => {
  it("accepts a complete answer and hands it back", async () => {
    ask.mockResolvedValue(completeView());

    const view = await fetchDoctorProfile();

    expect(view.partner_id).toBe("partner-1");
    expect(view.specialties).toEqual(["General Physician"]);
    expect(view.credentials[0].status).toBe("verified");
    // The two guards a permissive regression would most easily break: a credential
    // read and a preferences read both depend on the guard's array and object tests.
    expect(view.notification_preferences.new_consultations).toBe(true);
  });

  // One case per field, generated rather than written out: the whole point is that
  // a field added to the view gets a removal case without anyone remembering.
  it.each(REQUIRED_KEYS)("refuses an answer missing %s", async (key) => {
    const partial = completeView();
    delete partial[key];

    expect(await refuses(partial)).toBe(true);
  });

  it("refuses an answer whose specialties are not an array", async () => {
    // A bare string is the realistic drift: the backend serialises one value and
    // the client's `specialties.map` would then be `undefined`.
    expect(
      await refuses({ ...completeView(), specialties: "General Physician" }),
    ).toBe(true);
  });

  it("refuses an answer whose consulting_days are not an array", async () => {
    expect(
      await refuses({ ...completeView(), consulting_days: { mon: true } }),
    ).toBe(true);
  });

  it("refuses a credential list holding something that is not a credential", async () => {
    // The realistic version of this drift is a status the client has not heard of:
    // the backend adds a sixth credential status and this list is not updated.
    expect(
      await refuses({
        ...completeView(),
        credentials: [
          { credential_type: "medical", status: "archived", expires_at: null },
        ],
      }),
    ).toBe(true);
  });

  it("refuses an answer whose notification preferences are null", async () => {
    // `typeof null === "object"`, so a plain type test waves this through and every
    // later `preferences[key]` read throws at the notification switch instead.
    expect(
      await refuses({ ...completeView(), notification_preferences: null }),
    ).toBe(true);
  });

  it("refuses a body that is not an object at all", async () => {
    expect(await refuses(null)).toBe(true);
    expect(await refuses("a profile")).toBe(true);
    expect(await refuses([])).toBe(true);
  });
});
