// MOD-012 / FEAT-008 (#679, parent #673): the read-only health-background block
// both doctor
// surfaces render - the patient-detail profile and (from #682) the case
// workspace History tab. One presentational component means the two surfaces
// cannot drift into different renderings of the same facts. It takes the
// already-fetched `HealthBackgroundView` plus its labels and performs no API
// read: the caller owns the gated fetch, this block only renders the answer.
//
// Three states stay visually distinct, because they mean different things:
//   null view        - the patient has not shared this section: the calm
//                      locked "not shared" card (a set-but-empty section must
//                      never be confused with an unknown one);
//   null background  - shared but nothing recorded: the quiet empty note;
//   a background     - the blood group plus the five chip areas, an empty
//                      granted area rendering the plain "None recorded" text.
//
// #659 (US-58/59): each area renders as its own label + chip row instead of
// one comma-joined run-on. The label sits above its value with `break-words`
// and no fixed-width column, so a long Devanagari label ("पारिवारिक इतिहास")
// wraps onto its own line rather than colliding with the chips beside it. The
// chip container wraps (`flex-wrap`), so a long allergy list becomes more
// rows, never a horizontal overflow. A chip is a Badge, never a button: these
// are read-only facts about a patient, with no remove affordance.

import type { ReactNode } from "react";

import { NotSharedCard } from "@/components/doctor/NotSharedCard";
import { Badge } from "@/components/ui/badge";
import type { Dictionary } from "@/lib/i18n/dictionaries";
import type { HealthBackgroundView } from "@/lib/doctor/api";

// #659 (US-56/57): the accent chip tone the header band and the health
// background share - the same soft-accent pill the scope badges and the
// shared doctor card render, so every read-only chip on the doctor surface
// looks like one family.
export const CHIP_TONE = "bg-accent-soft text-accent-strong";

/** The copy this block renders; passed in so no new dictionary block forks. */
export type HealthBackgroundLabels = Pick<
  Dictionary["doctorPatients"],
  | "notSharedTitle"
  | "notSharedBody"
  | "healthBackgroundEmpty"
  | "bloodGroupLabel"
  | "conditionsLabel"
  | "allergiesLabel"
  | "medicationsLabel"
  | "immunizationsLabel"
  | "familyHistoryLabel"
  | "noneRecorded"
>;

// One health-background row: a wrap-safe label above its value. The label
// may wrap (break-words, no fixed-width column), so a long Devanagari label
// never collides with the chips on the line below (#659 / US-59).
function HealthRow({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <dt
        className="break-words text-xs font-medium uppercase tracking-wide text-txt-muted"
        data-testid="health-area-label"
      >
        {label}
      </dt>
      <dd className="min-w-0" data-testid="detail-field-value">
        {children}
      </dd>
    </div>
  );
}

export function HealthBackgroundBlock({
  healthBackground,
  labels,
}: {
  healthBackground: HealthBackgroundView | null;
  labels: HealthBackgroundLabels;
}) {
  if (healthBackground == null) {
    return (
      <NotSharedCard
        title={labels.notSharedTitle}
        body={labels.notSharedBody}
      />
    );
  }
  const bg = healthBackground.background;
  if (bg == null) {
    return (
      <div
        data-testid="health-background-empty"
        className="rounded-lg border border-hairline bg-surface px-4 py-4 text-sm text-txt-muted"
      >
        {labels.healthBackgroundEmpty}
      </div>
    );
  }
  const areas: Array<{ label: string; values: string[] }> = [
    { label: labels.conditionsLabel, values: bg.conditions },
    { label: labels.allergiesLabel, values: bg.allergies },
    { label: labels.medicationsLabel, values: bg.medications },
    { label: labels.immunizationsLabel, values: bg.immunizations },
    { label: labels.familyHistoryLabel, values: bg.family_history },
  ];
  return (
    <dl
      data-testid="health-background-set"
      className="space-y-4 rounded-lg border border-hairline bg-surface p-4"
    >
      <HealthRow label={labels.bloodGroupLabel}>
        <span className="text-sm text-txt">
          {bg.blood_group ?? labels.noneRecorded}
        </span>
      </HealthRow>
      {areas.map((area) => (
        <HealthRow key={area.label} label={area.label}>
          {area.values.length > 0 ? (
            <div className="flex flex-wrap items-center gap-1.5">
              {area.values.map((value, index) => (
                <Badge
                  key={`${area.label}-${index}`}
                  data-testid="health-chip"
                  className={CHIP_TONE}
                >
                  {value}
                </Badge>
              ))}
            </div>
          ) : (
            <span className="text-sm text-txt">{labels.noneRecorded}</span>
          )}
        </HealthRow>
      ))}
    </dl>
  );
}
