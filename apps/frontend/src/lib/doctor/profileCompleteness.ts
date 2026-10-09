// #678: the one spot that decides which profile fields a doctor has filled in.
// The dashboard's profile-status card (#678) and its getting-started checklist
// (#674) are complementary views over the same four gaps (verified, fee, about
// text, clinic name), so both derive their state from this single projection
// instead of re-testing the fields and drifting apart.

import type { DoctorProfileView } from "@/lib/doctor/api";

export interface ProfileCompleteness {
  verified: boolean;
  fee: boolean;
  about: boolean;
  clinic: boolean;
}

export function profileCompleteness(
  profile: DoctorProfileView,
): ProfileCompleteness {
  const hasText = (value: string | null): boolean =>
    value != null && value.trim().length > 0;
  return {
    verified: profile.verified,
    fee: profile.consultation_fee != null,
    about: hasText(profile.about),
    clinic: hasText(profile.clinic_name),
  };
}
