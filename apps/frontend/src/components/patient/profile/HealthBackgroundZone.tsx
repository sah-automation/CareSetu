"use client";

// MOD-003 (FEAT-002 record / FEAT-018 metrics), gated by MOD-004 (FEAT-002
// consent), #549: the patient profile's Health background zone - the snapshot
// the patient authors about themselves (US-21/US-22) plus the height/weight
// series they keep over time (US-23), on the owner's own endpoints from
// #534/#535.
//
// This is the composition, nothing more. The snapshot and the series are two
// independent surfaces with two independent reads, and a failure in either must
// not take the other away: the series failing still leaves the patient able to
// correct their blood group, and a denied snapshot still leaves them able to
// record a measurement. Each owns its own loading, error and form state for
// exactly that reason.
//
// A denied or missing snapshot renders the empty state rather than a fabricated
// one. The read is the only source of what is on this zone - the client never
// invents a value the API did not answer, and a failed read offers a retry
// rather than a form that would let the patient retype a snapshot the API may
// already be holding.

import { HealthBackgroundSnapshotForm } from "@/components/patient/profile/HealthBackgroundSnapshotForm";
import { HealthMetricsSeries } from "@/components/patient/profile/HealthMetricsSeries";

export function HealthBackgroundZone() {
  return (
    <div data-testid="ps-hb-zone" className="mt-4 flex flex-col gap-5">
      <HealthBackgroundSnapshotForm />
      <HealthMetricsSeries />
    </div>
  );
}
