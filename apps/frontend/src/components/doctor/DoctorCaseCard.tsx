// MOD-012 / FEAT-008 (#676): the one adapter from an enriched case row to the
// shared DoctorListCard, so the cases index and the dashboard's open-cases
// section render a case identically - patient name plus age, the amber Verify
// chip on a forced review, the shared stage chip, the citable case id + the
// relative "updated" meta line, and one whole-card link whose accessible name
// includes the patient (US-66/67). Both surfaces read the same feed
// (listDoctorCases); this adapter is the single place the card anatomy is
// decided, so a new chip or meta field lands on both at once.

import type { DoctorCaseRow } from "@/lib/doctor/api";
import { caseUpdatedText } from "@/lib/doctor/caseTime";
import { stageChipView, WARN_TONE } from "@/lib/doctor/stageChip";
import type { Dictionary } from "@/lib/i18n/dictionaries";

import { DoctorListCard } from "./DoctorListCard";

export interface DoctorCaseCardProps {
  row: DoctorCaseRow;
  t: Dictionary["doctorConsole"];
}

export function DoctorCaseCard({ row, t }: DoctorCaseCardProps) {
  const patient = row.patient_name ?? t.patientFallback;
  const updated = caseUpdatedText(row.updated_at, t);
  return (
    <DoctorListCard
      href={`/doctor/cases/${row.case_id}`}
      name={patient}
      ageText={row.patient_age != null ? t.patientAge(row.patient_age) : null}
      chips={
        row.forced_review
          ? [
              {
                key: "verify",
                label: t.verifyChip,
                tone: WARN_TONE,
                testId: "case-item-verify",
              },
            ]
          : []
      }
      stage={stageChipView(row.stage, t)}
      stageTestId="case-item-stage"
      meta={
        <span className="flex flex-wrap items-center gap-x-2">
          <span data-testid="case-item-id">{t.caseItemMeta(row.case_id)}</span>
          {updated !== null && (
            <span data-testid="case-item-updated">{updated}</span>
          )}
        </span>
      }
      accessibleName={t.caseCardA11y(patient)}
      nameTestId="case-item-patient"
      linkTestId="case-item-open"
    />
  );
}
