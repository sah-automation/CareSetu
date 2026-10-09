"use client";

// #671: one own-record read per homepage visit, shared between the rail's new
// "At a glance" and "Who accessed my record" sections (story 33) - parity must
// not multiply the patient's API traffic. Mirrors the AccessHistoryAccordion
// store pattern: a module-level external store whose single fetch is started on
// the first subscriber and dropped once the last listener unmounts, so a fresh
// visit refetches while a transient remount reuses the in-flight read. The hook
// hands the new sections exactly what they need - the summary counts and the
// patient id - so neither re-derives from a second response. HealthSnapshotCard
// keeps its own self-fetch, and the record page keeps passing its already-loaded
// timeline down, per the spec's Implementation Decisions.

import { useMemo, useSyncExternalStore } from "react";

import { fetchOwnRecord, type RecordTimeline } from "@/lib/record/api";
import {
  countByType,
  flaggedValues,
  issuedPrescriptionCount,
  sortTimelineDesc,
  type LabFlagSummary,
  type RecordCounts,
} from "@/lib/record/timelineView";

type LoadStatus = "loading" | "ready" | "error";

interface OwnRecordState {
  status: LoadStatus;
  timeline: RecordTimeline | null;
}

const INITIAL_STATE: OwnRecordState = { status: "loading", timeline: null };

class OwnRecordStore {
  private state: OwnRecordState = INITIAL_STATE;
  private listeners = new Set<() => void>();
  private started = false;

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    if (!this.started) this.load();
    return () => {
      this.listeners.delete(listener);
      if (this.listeners.size === 0) {
        // Deferred so a transient mount/unmount/mount (StrictMode, or a
        // same-tick remount) reuses the store instead of refetching; a real
        // navigation unmounts, the microtask drops the store, and the next
        // mount starts a fresh read.
        queueMicrotask(() => {
          if (this.listeners.size === 0 && store === this) store = null;
        });
      }
    };
  };

  getSnapshot = (): OwnRecordState => this.state;

  private setState(patch: Partial<OwnRecordState>): void {
    this.state = { ...this.state, ...patch };
    this.listeners.forEach((listener) => listener());
  }

  load = (): void => {
    this.started = true;
    this.setState({ status: "loading" });
    fetchOwnRecord()
      .then((timeline) => this.setState({ timeline, status: "ready" }))
      .catch(() => this.setState({ timeline: null, status: "error" }));
  };
}

let store: OwnRecordStore | null = null;

function getStore(): OwnRecordStore {
  if (!store) store = new OwnRecordStore();
  return store;
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
  const active = useMemo(getStore, []);
  const state = useSyncExternalStore(
    active.subscribe,
    active.getSnapshot,
    active.getSnapshot,
  );

  const derived = useMemo(() => {
    const sorted = sortTimelineDesc(state.timeline?.entries ?? []);
    return {
      counts: state.timeline ? countByType(sorted) : null,
      issuedCount: issuedPrescriptionCount(sorted),
      flagged: flaggedValues(sorted),
    };
  }, [state.timeline]);

  return {
    status: state.status,
    counts: derived.counts,
    issuedCount: derived.issuedCount,
    flagged: derived.flagged,
    patientId: state.timeline?.patient_id ?? null,
  };
}
