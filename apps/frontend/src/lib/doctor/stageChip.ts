// MOD-012 / FEAT-008 (#645/#651): the one stage-chip tone + label map shared
// by the doctor lists. Both lists (patients here, cases in #652) render the
// care-case stage enum (care/api.ts), so the tone and the label are extracted
// once here - a stage looks the same wherever it appears. The three-way
// mapping follows the cases index's existing split (pre-summary = warn,
// prescription-pending = accent, closed = muted hairline); the other inline
// copies in the app are deliberately left alone. An unknown stage falls back
// to the muted hairline tone and renders as itself, like the cases index.
// Precedent: lib/record/timelineView.ts (BADGE_TONE as the single tone map).

import type { Dictionary } from "@/lib/i18n/dictionaries";

/** Unknown stages and the closed stage read as quiet metadata, never accent. */
const MUTED_TONE = "bg-hairline-soft text-txt-muted";

export interface StageChip {
  /** Tailwind classes for the chip tone. */
  readonly tone: string;
  /**
   * Dictionary key into doctorConsole for the stage label. Absent for unknown
   * stages: those render the stage value itself, so nothing is ever invented.
   */
  readonly labelKey?: keyof Pick<
    Dictionary["doctorConsole"],
    "stagePreSummary" | "stagePrescriptionPending" | "stageClosed"
  >;
}

/** The chip the list should render for one stage. */
export interface StageChipView {
  readonly label: string;
  readonly tone: string;
}

export const STAGE_CHIPS: Record<string, StageChip> = {
  pre_summary: {
    tone: "bg-warn-soft text-warn-text",
    labelKey: "stagePreSummary",
  },
  prescription_pending: {
    tone: "bg-accent-soft text-accent-strong",
    labelKey: "stagePrescriptionPending",
  },
  closed: { tone: MUTED_TONE, labelKey: "stageClosed" },
};

const STAGE_CHIP_FALLBACK: StageChip = { tone: MUTED_TONE };

/**
 * The label + tone for one stage in the active language: a known stage from
 * the map, else a muted chip whose label is the stage value itself. Single
 * lookup, so a caller never pairs a label from one place with a tone from
 * another.
 */
export function stageChipView(
  stage: string,
  t: Dictionary["doctorConsole"],
): StageChipView {
  const chip = STAGE_CHIPS[stage] ?? STAGE_CHIP_FALLBACK;
  return {
    label: chip.labelKey ? t[chip.labelKey] : stage,
    tone: chip.tone,
  };
}
