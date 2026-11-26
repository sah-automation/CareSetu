// PRD trace: FEAT-005 (Provider Profiles and Credential Display).
import { describe, expect, it } from "vitest";

import type { DoctorProfileView } from "@/lib/doctor/api";

import {
  invalidNotificationFields,
  NOTIFICATION_KEYS,
  notificationsFromProfile,
  notificationsUpdateFromFields,
  type NotificationFields,
} from "./notificationCardFields";

function profile(
  overrides: Partial<DoctorProfileView> = {},
): DoctorProfileView {
  return {
    partner_id: 1,
    photo_ref: null,
    practice_name: "Sunrise Clinic",
    clinic_name: "Sunrise Building",
    specialties: [],
    verified: true,
    practice_address: "Main Road, Daltonganj",
    address_line: null,
    landmark: null,
    locality: null,
    city: null,
    pin_code: "822001",
    practice_latitude: 24.1957,
    practice_longitude: 85.3656,
    area: null,
    languages: [],
    experience_years: null,
    about: null,
    consultation_fee: null,
    consulting_days: [],
    consulting_hours: null,
    credentials: [],
    notification_preferences: { new_consultations: true },
    ...overrides,
  };
}

function notifications(
  overrides: Partial<NotificationFields> = {},
): NotificationFields {
  return { ...notificationsFromProfile(profile()), ...overrides };
}

describe("the Notification slice", () => {
  it("seeds all five, and starts an absent key off rather than guessing", () => {
    expect(
      notificationsFromProfile(
        profile({ notification_preferences: { new_consultations: true } }),
      ).preferences,
    ).toEqual({
      new_consultations: true,
      record_shared: false,
      pre_summary_ready: false,
      case_updates: false,
      credential_status: false,
    });
  });

  it("does not hold a stored key the five do not name", () => {
    const seeded = notificationsFromProfile(
      profile({
        notification_preferences: {
          new_consultations: true,
          legacy_opt_in: true,
        },
      }),
    );

    // `require_notification_preferences` refuses an unknown submitted key, so a
    // slice that echoed one back would make every save a 422. Preserving it is the
    // server's merge to do, and it does.
    expect(Object.keys(seeded.preferences)).toEqual([...NOTIFICATION_KEYS]);
  });

  it("treats a non-boolean stored value as absent rather than truthy", () => {
    // `Boolean("false")` is the exact opposite of what such a value says, which is
    // why the backend narrows on the way IN and carries a stored value verbatim.
    expect(
      notificationsFromProfile(
        profile({
          notification_preferences: {
            new_consultations: "false",
          } as unknown as Record<string, boolean>,
        }),
      ).preferences.new_consultations,
    ).toBe(false);
  });

  it("submits exactly the five, whatever the slice holds", () => {
    const fields = notifications();
    // The slice's own type forbids a sixth key, so the extra one is forced in: the
    // point is that the BODY builder is safe even for a slice that has one, which
    // is a stronger claim than the type making it unreachable.
    (fields.preferences as Record<string, boolean>).legacy_opt_in = true;

    // Structural rather than incidental: a sixth key cannot get into the body even
    // if a field is added to the slice by mistake.
    expect(
      Object.keys(
        notificationsUpdateFromFields(fields).notification_preferences,
      ),
    ).toEqual([...NOTIFICATION_KEYS]);
  });

  it("sends five falses when every switch is off, because that is an answer", () => {
    const body = notificationsUpdateFromFields(
      notifications({
        preferences: {
          new_consultations: false,
          record_shared: false,
          pre_summary_ready: false,
          case_updates: false,
          credential_status: false,
        },
      }),
    );

    expect(Object.values(body.notification_preferences)).toEqual([
      false,
      false,
      false,
      false,
      false,
    ]);
  });

  it("refuses nothing, because nothing on this card can be entered wrongly", () => {
    expect(invalidNotificationFields(notifications())).toEqual([]);
  });
});
