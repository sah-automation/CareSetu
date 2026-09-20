"use client";

// PHASE-2.6 T13 (#204): patient dashboard with profile nudges and
// completion meter (blueprint §5.9). PHASE-8.1 T2 (#488): the draft here
// comes from the patient ProfileProvider - hydrated from GET /v1/me/profile
// with the identity-scoped local draft as fallback - so nudge cards and the
// meter reflect what was actually completed server-side, on any device. Also
// includes the ProfileGateDemo showing the §5.9 gating matrix in action for
// care actions (intake, booking, medicine-delivery checkout).

import { PageHeader } from "@/components/layout/PageHeader";
import { LabBookingConsentDemo } from "@/components/patient/LabBookingConsentDemo";
import {
  ProfileCompletionMeter,
  ProfileNudgeCards,
} from "@/components/patient/profile/ProfileNudges";
import { ProfileGateDemo } from "@/components/patient/profile/ProfileGate";
import { useProfile } from "@/lib/profile/ProfileContext";

export default function PatientDashboardPage() {
  const { draft } = useProfile();

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
