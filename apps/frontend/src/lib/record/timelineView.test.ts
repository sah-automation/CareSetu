// PHASE-3 T7 (#216): unit suite for the record timeline's pure view-model
// helpers - defensive reverse-chron ordering, type filtering, entry-card
// shaping from documented payload fields only, and locale date formatting.

import { describe, expect, it } from "vitest";

import { STRINGS } from "@/lib/i18n/dictionaries";
import type { RecordEntryView } from "./api";
import {
  MORE_OVERFLOW_FILTERS,
  RECORD_FILTERS,
  applyRecordFilter,
  describeEntry,
  formatOccurredAt,
  sortTimelineDesc,
} from "./timelineView";

function entry(overrides: Partial<RecordEntryView>): RecordEntryView {
  return {
    entry_id: 1,
    entry_type: "consultation",
    payload: {},
    occurred_at: "2026-08-19T10:00:00Z",
    created_at: "2026-08-19T10:00:05Z",
    ...overrides,
  };
}

describe("sortTimelineDesc", () => {
  it("orders entries newest-first by clinical time regardless of input order", () => {
    const newest = entry({ entry_id: 3, occurred_at: "2026-08-22T08:00:00Z" });
    const middle = entry({ entry_id: 2, occurred_at: "2026-08-21T14:30:00Z" });
    const oldest = entry({ entry_id: 1, occurred_at: "2026-08-18T07:45:00Z" });

    expect(sortTimelineDesc([oldest, newest, middle]).map((e) => e.entry_id)) //
      .toEqual([3, 2, 1]);
  });

  it("breaks clinical-time ties by id, newest row first", () => {
    const laterRow = entry({
      entry_id: 9,
      occurred_at: "2026-08-21T14:30:00Z",
    });
    const earlierRow = entry({
      entry_id: 4,
      occurred_at: "2026-08-21T14:30:00Z",
    });

    expect(sortTimelineDesc([earlierRow, laterRow]).map((e) => e.entry_id)) //
      .toEqual([9, 4]);
  });

  it("never mutates the caller's array", () => {
    const list = [
      entry({ entry_id: 1, occurred_at: "2026-08-19T10:00:00Z" }),
      entry({ entry_id: 2, occurred_at: "2026-08-22T08:00:00Z" }),
    ];
    sortTimelineDesc(list);
    expect(list.map((e) => e.entry_id)).toEqual([1, 2]);
  });
});

describe("applyRecordFilter", () => {
  const entries = [
    entry({ entry_id: 1, entry_type: "prescription" }),
    entry({ entry_id: 2, entry_type: "lab_report" }),
    entry({ entry_id: 3, entry_type: "prescription" }),
  ];

  it("keeps everything under All", () => {
    expect(applyRecordFilter(entries, "all")).toHaveLength(3);
  });

  it("keeps only the picked type otherwise", () => {
    expect(
      applyRecordFilter(entries, "prescription").map((e) => e.entry_id),
    ).toEqual([1, 3]);
    expect(
      applyRecordFilter(entries, "lab_report").map((e) => e.entry_id),
    ).toEqual([2]);
  });
});

describe("filter vocabulary", () => {
  it("matches the binding prototype chip set and More overflow", () => {
    expect(RECORD_FILTERS).toEqual([
      "all",
      "consultation",
      "prescription",
      "lab_report",
      "metric",
    ]);
    expect(MORE_OVERFLOW_FILTERS).toEqual(["lab_report", "metric"]);
  });
});

describe("describeEntry", () => {
  const t = STRINGS.en.record;

  it("shapes a delivered prescription with the success Delivered badge", () => {
    const card = describeEntry(
      entry({
        entry_type: "prescription",
        payload: { prescription_id: 9, status: "delivered" },
        occurred_at: "2026-08-22T08:00:00Z",
      }),
      t,
      "en",
    );
    expect(card.badge).toEqual({ label: "Delivered", tone: "success" });
    expect(card.title).toBe("Prescription");
    expect(card.subtitle).toContain("Rx #9");
  });

  it("shapes an issued prescription with the warm Issued badge", () => {
    const card = describeEntry(
      entry({
        entry_type: "prescription",
        payload: { prescription_id: 12, status: "issued" },
      }),
      t,
      "en",
    );
    expect(card.badge).toEqual({ label: "Issued", tone: "warm" });
  });

  it("uses the uploaded filename as a lab report title when present", () => {
    const card = describeEntry(
      entry({
        entry_type: "lab_report",
        payload: { order_id: 1042, filename: "cbc-panel.pdf" },
      }),
      t,
      "en",
    );
    expect(card.title).toBe("cbc-panel.pdf");
    expect(card.subtitle).toContain("filed from booking #1042");
    expect(card.badge?.tone).toBe("accent");
  });

  it("falls back to the type label when a lab report has no filename yet", () => {
    const card = describeEntry(entry({ entry_type: "lab_report" }), t, "en");
    expect(card.title).toBe("Lab result");
  });

  it("renders consultation, metric and settlement cards from their own fields", () => {
    const consultation = describeEntry(
      entry({ entry_type: "consultation" }),
      t,
      "en",
    );
    expect(consultation.badge).toEqual({
      label: "Consultation",
      tone: "warm",
    });

    const metric = describeEntry(entry({ entry_type: "metric" }), t, "en");
    expect(metric.badge).toEqual({ label: "Metric", tone: "muted" });

    const settlement = describeEntry(
      entry({
        entry_type: "settlement",
        payload: { settlement_id: 77, order_ref: "CS-31", amount_paise: 45000 },
      }),
      t,
      "en",
    );
    expect(settlement.title).toBe("Settlement");
    expect(settlement.subtitle).toContain("\u20b9450.00");
    expect(settlement.subtitle).toContain("#CS-31");
  });

  it("formats clinical dates per active locale", () => {
    // Locale-sensitive but deterministic: en uses the latin short month,
    // hi uses Devanagari digits/months from Intl.
    expect(formatOccurredAt("2026-08-22T08:00:00Z", "en")).toMatch(/2026/);
    expect(formatOccurredAt("2026-08-22T08:00:00Z", "hi")).toMatch(/2026/);
    expect(formatOccurredAt("2026-08-22T08:00:00Z", "hi")).not.toBe(
      formatOccurredAt("2026-08-22T08:00:00Z", "en"),
    );
  });
});
