// MOD-003 record HTTP surface client for the patient PWA (PHASE-3 T7, #216).
// Thin fetch wrapper over the backend's GET /v1/records own-record read; the
// response shapes mirror modules/health/facade.py's RecordTimeline /
// RecordEntryView exactly (entry_type vocabulary is the schema CHECK
// constraint). The session travels as the API-origin httpOnly cookie
// (ADR-0005), so the read sends credentials like every other authed call.

import { API_BASE_URL, authedFetch } from "@/lib/api-base";
import {
  ApiError,
  parseErrorEnvelope,
  extractTraceId,
  type ErrorEnvelope,
} from "@/lib/api-errors";

export type { ErrorEnvelope } from "@/lib/api-errors";
export { ApiError as RecordApiError } from "@/lib/api-errors";

export type RecordEntryType =
  | "consultation"
  | "prescription"
  | "lab_report"
  | "metric"
  | "settlement";

export interface RecordEntryView {
  entry_id: number;
  entry_type: RecordEntryType;
  payload: Record<string, unknown>;
  /** ISO 8601 clinical time; entries arrive reverse-chronological by it. */
  occurred_at: string;
  created_at: string;
}

export interface RecordTimeline {
  record_id: number;
  patient_id: number;
  created_at: string;
  entries: RecordEntryView[];
}

export async function fetchOwnRecord(): Promise<RecordTimeline> {
  let response: Response;
  try {
    response = await authedFetch(`${API_BASE_URL}/v1/records`);
  } catch {
    throw new ApiError({
      code: "NETWORK_ERROR",
      message: "Could not reach the CareSetu API",
      trace_id: "",
      details: {},
    });
  }

  if (!response.ok) {
    throw new ApiError(await parseErrorEnvelope(response));
  }

  return (await response.json()) as RecordTimeline;
}
