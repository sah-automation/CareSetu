"use client";

// MOD-003 (record timeline) / FEAT-003 (patient trust view) + FEAT-006 (patient
// home): #671 one own-record read per homepage visit, shared between the rail's
// "At a glance", "Who accessed my record", the health snapshot, and recent
// activity - parity must not multiply the patient's API traffic.
//
// #904: the hand-rolled external store became a shared TanStack query so the
// dedupe generalizes: every consumer mounts the same identity-scoped query
// ("record", "own", identityId), the in-flight read is shared by construction,
// and a client-side navigation inside the stale window answers from cache
// instead of refetching. Loading/error postures are unchanged: a failed read
// with no cached answer hides the consuming sections rather than claiming the
// record is empty (the record page's honesty rule), a cached answer keeps
// rendering while a background refetch fails, and the failure is logged
// (coding-standards §8).

import { useEffect, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { useAuth } from "@/lib/auth/AuthContext";
import { fetchOwnRecord, type RecordTimeline } from "@/lib/record/api";
import {
  countByType,
  flaggedValues,
  issuedPrescriptionCount,
  sortTimelineDesc,
  type LabFlagSummary,
  type RecordCounts,
} from "@/lib/record/timelineView";

// Navigating back to the home (or the record page) within a minute reuses the
// cached timeline instead of paying for a second read.
export const OWN_RECORD_STALE_TIME = 60_000;

export function ownRecordQueryKey(
  identityId: number | undefined,
): readonly unknown[] {
  // The signed-out segment can never match a signed-in key, and the query is
  // disabled without an identity - the sentinel only keeps the array typed.
  return ["record", "own", identityId ?? "signed-out"] as const;
}

type LoadStatus = "loading" | "ready" | "error";

export interface OwnRecordTimelineView {
  status: LoadStatus;
  /** The raw timeline, null until the single read resolves. */
  timeline: RecordTimeline | null;
  /** True while a fetch (initial or retry) is in flight. */
  refetching: boolean;
  /** The failure behind an "error" status (an ApiError with a trace id). */
  error: unknown;
  refetch: () => void;
}

/**
 * The one own-record read every record-consuming surface mounts. Gated on the
 * session identity (the query key carries it, so a different session can never
 * be served another patient's cached timeline).
 */
export function useOwnRecordTimeline(): OwnRecordTimelineView {
  const { user } = useAuth();
  const identityId = user?.id;

  const query = useQuery({
    queryKey: ownRecordQueryKey(identityId),
    queryFn: () => fetchOwnRecord(),
    enabled: identityId !== undefined,
    staleTime: OWN_RECORD_STALE_TIME,
  });

  // Cached data wins over a failed background refetch (stale-while-error): the
  // surfaces keep rendering the timeline they already hold, and the failure is
  // logged so it stays reproducible (coding-standards §8) - once per failed
  // fetch, not on every render.
  useEffect(() => {
    if (query.isError) {
      console.warn(
        "[own-record] record fetch failed, hiding record surfaces:",
        query.error,
      );
    }
  }, [query.isError, query.error]);

  return {
    status: query.isPending ? "loading" : query.data ? "ready" : "error",
    timeline: query.data ?? null,
    refetching: query.isFetching,
    error: query.error,
    refetch: () => void query.refetch(),
  };
}

export interface OwnRecordView {
  status: LoadStatus;
  /** Payload-derived counts, null until the single read resolves. */
  counts: RecordCounts | null;
  issuedCount: number;
  flagged: LabFlagSummary;
  /** The record owner's identity, null until the read resolves. */
  patientId: number | null;
}

export function useOwnRecord(): OwnRecordView {
  const { status, timeline } = useOwnRecordTimeline();

  const derived = useMemo(() => {
    const sorted = sortTimelineDesc(timeline?.entries ?? []);
    return {
      counts: timeline ? countByType(sorted) : null,
      issuedCount: issuedPrescriptionCount(sorted),
      flagged: flaggedValues(sorted),
    };
  }, [timeline]);

  return {
    status,
    counts: derived.counts,
    issuedCount: derived.issuedCount,
    flagged: derived.flagged,
    patientId: timeline?.patient_id ?? null,
  };
}
