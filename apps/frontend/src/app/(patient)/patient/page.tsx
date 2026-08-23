"use client";

// PHASE-2.6 T13 (#204): patient dashboard with profile nudges and
// completion meter (blueprint §5.9). Nudge cards surface skipped profile
// items as gentle Home reminders; the meter reflects draft completeness.
// Also includes the ProfileGateDemo showing the §5.9 gating matrix in
// action for care actions (intake, booking, medicine-delivery checkout).

import { useEffect, useState } from "react";

import { PageHeader } from "@/components/layout/PageHeader";
import { LabBookingConsentDemo } from "@/components/patient/LabBookingConsentDemo";
import {
  ProfileCompletionMeter,
  ProfileNudgeCards,
} from "@/components/patient/profile/ProfileNudges";
import { ProfileGateDemo } from "@/components/patient/profile/ProfileGate";
import {
  initialDraft,
  loadDraft,
  type ProfileDraft,
} from "@/lib/profile/profileState";

export default function PatientDashboardPage() {
  // Start at the empty draft and adopt the stored one after mount
  // (hydration-safe, mirrors AppShell's storage convention).
  const [draft, setDraft] = useState<ProfileDraft>(initialDraft);

  useEffect(() => {
    setDraft(loadDraft());
  }, []);

  return (
    <>
      <PageHeader title="Welcome, Patient" />
      <div className="space-y-6">
        <ProfileCompletionMeter draft={draft} />
        <ProfileNudgeCards draft={draft} />
        <LabBookingConsentDemo />
        <ProfileGateDemo />
      </div>
    </>
  );
}
