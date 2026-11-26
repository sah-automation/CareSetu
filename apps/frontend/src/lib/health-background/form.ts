// MOD-003 (FEAT-002 record / FEAT-018 metrics), #549: the health-background
// form's pure value handling, kept out of the components so the two places a
// silent data bug could hide are testable on their own: the entry-list textarea
// round-trip and the measurement parse.
//
// The round-trip matters because the wire shape is a list of strings and the
// editing shape is one entry per line. Saving must not turn a blank line the
// patient typed into an empty entry (a doctor would then read a blank bullet),
// and loading must not reflow a stored entry. The measurement parse matters
// because the backend refuses an implausible height or weight with a generic
// 422; checking the same bounds here turns that into a field-level message
// instead of a save that appears to fail for no reason.
//
// The bounds below mirror the `health_background_metrics` column CHECKs and the
// `HealthBackground.blood_group` max_length in the backend - the client needs
// them to say WHY a value is refused rather than round-tripping a generic 422.
// Each constant names its source so a schema change is greppable from here.

import type { HealthMetricInput } from "./api";

/** Render a stored entry list as one-entry-per-line text for a textarea. */
export function entriesToText(entries: readonly string[]): string {
  return entries.join("\n");
}

/**
 * Parse one-entry-per-line text into the wire list: trim each line and drop
 * the blank ones, so trailing newlines and spacing never become empty entries.
 */
export function textToEntries(text: string): string[] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line !== "");
}

/** A blood group is a short label; an empty box means "not recorded". */
export const BLOOD_GROUP_MAX_LENGTH = 16; // facade.py HealthBackground.blood_group

export function normalizeBloodGroup(value: string): string | null {
  const trimmed = value.trim();
  return trimmed === "" ? null : trimmed.slice(0, BLOOD_GROUP_MAX_LENGTH);
}

/** Plausible measurement bounds, matching the backend's column CHECKs. */
export const HEIGHT_CM_MIN = 30; // health_background_metrics.height_cm CHECK
export const HEIGHT_CM_MAX = 250;
export const WEIGHT_KG_MIN = 1; // health_background_metrics.weight_kg CHECK
export const WEIGHT_KG_MAX = 500;

/** Which authored measurement value a parse complaint is about. */
export type MeasurementField = "values" | "height" | "weight" | "recordedAt";

/**
 * Why a measurement cannot be sent, as a code the caller turns into copy. The
 * reason is a code rather than a sentence so this module stays free of any
 * locale and the message lives in the dictionary beside its translation.
 */
export type MeasurementComplaint =
  | "value-required"
  | "value-not-a-number"
  | "height-out-of-range"
  | "weight-out-of-range"
  | "recorded-at-required"
  | "recorded-at-invalid";

export type MeasurementParse =
  | { ok: true; value: HealthMetricInput }
  | { ok: false; field: MeasurementField; reason: MeasurementComplaint };

/** The raw strings a datetime-local input yields, all possibly blank. */
export interface MeasurementDraft {
  heightCm: string;
  weightKg: string;
  recordedAt: string;
}

/**
 * A typed box is three states, not two: blank, a number, or something that is
 * not a number. Collapsing the third into "blank" would let "tall" in the
 * height box save as a weight-only measurement - the patient's own reading
 * silently dropped, with no complaint anywhere.
 */
type RawNumber =
  | { kind: "blank" }
  | { kind: "number"; value: number }
  | { kind: "not-a-number" };

function parseNumber(raw: string): RawNumber {
  const trimmed = raw.trim();
  if (trimmed === "") return { kind: "blank" };
  const parsed = Number(trimmed);
  return Number.isFinite(parsed)
    ? { kind: "number", value: parsed }
    : { kind: "not-a-number" };
}

function inRange(value: number, min: number, max: number): boolean {
  return value >= min && value <= max;
}

/**
 * Turn the three raw input strings into the append payload, or name the field
 * that is wrong. A blank height or weight means "not recorded" and is left out
 * of the payload, but at least one of the two must be there - the backend
 * rejects a measurement with neither, and a bare timestamp is not a
 * measurement.
 */
export function parseMeasurement(draft: MeasurementDraft): MeasurementParse {
  const rawHeight = parseNumber(draft.heightCm);
  const rawWeight = parseNumber(draft.weightKg);

  if (rawHeight.kind === "not-a-number") {
    return { ok: false, field: "height", reason: "value-not-a-number" };
  }
  if (rawWeight.kind === "not-a-number") {
    return { ok: false, field: "weight", reason: "value-not-a-number" };
  }

  const heightCm = rawHeight.kind === "number" ? rawHeight.value : null;
  const weightKg = rawWeight.kind === "number" ? rawWeight.value : null;

  if (heightCm === null && weightKg === null) {
    return { ok: false, field: "values", reason: "value-required" };
  }
  if (heightCm !== null && !inRange(heightCm, HEIGHT_CM_MIN, HEIGHT_CM_MAX)) {
    return { ok: false, field: "height", reason: "height-out-of-range" };
  }
  if (weightKg !== null && !inRange(weightKg, WEIGHT_KG_MIN, WEIGHT_KG_MAX)) {
    return { ok: false, field: "weight", reason: "weight-out-of-range" };
  }
  const recordedAt = draft.recordedAt.trim();
  // A blank date and an unreadable date are different mistakes: one is a
  // missing answer, the other a control the patient cannot have meant.
  if (recordedAt === "") {
    return { ok: false, field: "recordedAt", reason: "recorded-at-required" };
  }
  if (Number.isNaN(Date.parse(recordedAt))) {
    return { ok: false, field: "recordedAt", reason: "recorded-at-invalid" };
  }

  return {
    ok: true,
    value: {
      heightCm,
      weightKg,
      // The wire contract is an ISO instant; a datetime-local box yields a
      // local wall-clock string, which only becomes an instant here.
      recordedAt: new Date(recordedAt).toISOString(),
    },
  };
}
