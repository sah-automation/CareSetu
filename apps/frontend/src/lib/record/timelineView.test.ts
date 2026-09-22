// PHASE-3 T7 (#216): unit suite for the record timeline's pure view-model
// helpers - defensive reverse-chron ordering, type filtering, entry-card
// shaping from documented payload fields only, and locale date formatting.

import { describe, expect, it } from "vitest";

import { STRINGS } from "@/lib/i18n/dictionaries";
import type { RecordEntryView } from "./api";
import {
  ENTRY_TONE,
  MORE_OVERFLOW_FILTERS,
  RECORD_FILTERS,
  applyRecordFilter,
  countByType,
  describeEntry,
  entryFlagRows,
  flaggedValues,
  formatMonthYear,
  formatOccurredAt,
  groupTimeline,
  isDeliveredPrescription,
  issuedPrescriptionCount,
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

  it("shapes a legacy issued prescription with the lean Rx form and Active badge", () => {
    const card = describeEntry(
      entry({
        entry_type: "prescription",
        payload: { prescription_id: 12, status: "issued" },
      }),
      t,
      "en",
    );
    expect(card.badge).toEqual({ label: "Active", tone: "success" });
    expect(card.title).toBe("Prescription");
    expect(card.subtitle).toContain("Rx #12");
  });

  it("shapes an issued enriched prescription with an Active success badge", () => {
    const card = describeEntry(
      entry({
        entry_type: "prescription",
        payload: {
          prescription_id: 12,
          status: "issued",
          items: [
            { name: "Amlodipine", dose: "5 mg", frequency: "once daily" },
          ],
          attributed_doctor_name: "Dr. A. Kumar",
        },
      }),
      t,
      "en",
    );
    expect(card.badge).toEqual({ label: "Active", tone: "success" });
    expect(card.title).toBe("Amlodipine");
    expect(card.subtitle).toContain("5 mg · once daily");
    expect(card.subtitle).toContain("issued by Dr. A. Kumar");
  });

  it("renders the full dose line and neutral attribution when the doctor name is null", () => {
    const card = describeEntry(
      entry({
        entry_type: "prescription",
        payload: {
          prescription_id: 40,
          status: "issued",
          items: [
            {
              name: "Telmisartan",
              dose: "40 mg",
              frequency: "once daily",
              duration: "30 tablets",
            },
          ],
          attributed_doctor_name: null,
        },
      }),
      t,
      "en",
    );
    expect(card.title).toBe("Telmisartan");
    expect(card.subtitle).toContain("40 mg · once daily · 30 tablets");
    expect(card.subtitle).toContain(t.issuedByNeutral);
    expect(card.subtitle).not.toContain("issued by Dr.");
  });

  it("renders the chemist line only when a delivered payload carries one", () => {
    const withChemist = describeEntry(
      entry({
        entry_type: "prescription",
        payload: {
          prescription_id: 9,
          status: "delivered",
          items: [{ name: "Amlodipine", dose: "5 mg" }],
          attributed_doctor_name: "Dr. A. Kumar",
          chemist_name: "Ramesh Medical Store",
        },
      }),
      t,
      "en",
    );
    expect(withChemist.badge).toEqual({ label: "Delivered", tone: "success" });
    expect(withChemist.title).toBe("Amlodipine");
    expect(withChemist.subtitle).toContain("Ramesh Medical Store");

    const withoutChemist = describeEntry(
      entry({
        entry_type: "prescription",
        payload: {
          prescription_id: 9,
          status: "delivered",
          items: [{ name: "Amlodipine", dose: "5 mg" }],
        },
      }),
      t,
      "en",
    );
    expect(withoutChemist.subtitle).not.toContain("Ramesh Medical Store");
  });

  it("shows a +N more tally on multi-item prescriptions in both locales", () => {
    const enCard = describeEntry(
      entry({
        entry_type: "prescription",
        payload: {
          prescription_id: 41,
          status: "issued",
          items: [
            { name: "Amlodipine", dose: "5 mg", frequency: "once daily" },
            { name: "Atorvastatin", dose: "10 mg", frequency: "at night" },
            { name: "Metformin", dose: "500 mg", frequency: "twice daily" },
          ],
        },
      }),
      t,
      "en",
    );
    expect(enCard.title).toBe("Amlodipine");
    expect(enCard.subtitle).toContain(STRINGS.en.record.moreItems(2));

    const hiCard = describeEntry(
      entry({
        entry_type: "prescription",
        payload: {
          prescription_id: 41,
          status: "issued",
          items: [
            { name: "Amlodipine", dose: "5 mg", frequency: "once daily" },
            { name: "Atorvastatin", dose: "10 mg", frequency: "at night" },
          ],
        },
      }),
      STRINGS.hi.record,
      "hi",
    );
    expect(hiCard.title).toBe("Amlodipine");
    expect(hiCard.subtitle).toContain(STRINGS.hi.record.moreItems(1));
  });

  it("ignores malformed items rows and degrades to the lean form", () => {
    const card = describeEntry(
      entry({
        entry_type: "prescription",
        payload: {
          prescription_id: 42,
          status: "issued",
          items: [null, "junk", { dose: "5 mg" }],
        },
      }),
      t,
      "en",
    );
    expect(card.title).toBe("Prescription");
    expect(card.subtitle).toContain("Rx #42");
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

// Local-day fixtures: build timestamps relative to *now* so the buckets are
// deterministic no matter which wall-clock day the suite runs on.
function localDay(offsetDays: number, hour = 12): Date {
  const now = new Date();
  return new Date(
    now.getFullYear(),
    now.getMonth(),
    now.getDate() + offsetDays,
    hour,
    0,
    0,
  );
}

describe("groupTimeline", () => {
  const labels = { today: "Today", yesterday: "Yesterday" };

  // Fixture pinned to the *previous* calendar month: always a month bucket,
  // never Today/Yesterday, and never dependent on which wall-clock day the
  // suite runs on.
  function prevMonthDay(day: number, hour = 12): Date {
    const now = new Date();
    return new Date(now.getFullYear(), now.getMonth() - 1, day, hour, 0, 0);
  }

  it("buckets entries into today, yesterday and month groups newest-first", () => {
    const today = entry({
      entry_id: 5,
      occurred_at: localDay(0, 9).toISOString(),
    });
    const yesterday = entry({
      entry_id: 4,
      occurred_at: localDay(-1, 18).toISOString(),
    });
    const thisMonth = entry({
      entry_id: 3,
      occurred_at: prevMonthDay(18).toISOString(),
    });
    const olderMonth = entry({
      entry_id: 2,
      occurred_at: new Date(
        new Date().getFullYear(),
        new Date().getMonth() - 2,
        18,
        12,
        0,
        0,
      ).toISOString(),
    });

    const groups = groupTimeline(
      [thisMonth, today, olderMonth, yesterday],
      labels,
      "en",
    );

    expect(groups.map((g) => g.key)).toEqual([
      "today",
      "yesterday",
      expect.stringMatching(/^\d{4}-\d{2}$/),
      expect.stringMatching(/^\d{4}-\d{2}$/),
    ]);
    expect(groups[0].label).toBe("Today");
    expect(groups[0].entries.map((e) => e.entry_id)).toEqual([5]);
    expect(groups[1].label).toBe("Yesterday");
    expect(groups[1].entries.map((e) => e.entry_id)).toEqual([4]);
    expect(groups[2].entries.map((e) => e.entry_id)).toEqual([3]);
    expect(groups[3].entries.map((e) => e.entry_id)).toEqual([2]);
  });

  it("collapses same-month entries into one ordered month group", () => {
    const a = entry({
      entry_id: 7,
      occurred_at: prevMonthDay(22, 8).toISOString(),
    });
    const b = entry({
      entry_id: 8,
      occurred_at: prevMonthDay(3, 17).toISOString(),
    });

    const groups = groupTimeline([b, a], labels, "en");

    // Both within the previous calendar month => one group, newest-first.
    expect(groups).toHaveLength(1);
    expect(groups[0].key).toMatch(/^\d{4}-\d{2}$/);
    expect(groups[0].entries.map((e) => e.entry_id)).toEqual([7, 8]);
  });

  it("labels months via Intl in both locales and never hardcodes a month name", () => {
    const monthDate = new Date(2026, 7, 15);
    const expectedEn = formatMonthYear(monthDate, "en");
    const expectedHi = formatMonthYear(monthDate, "hi");

    expect(expectedEn).toContain("2026");
    expect(expectedHi).toContain("2026");
    expect(expectedHi).not.toBe(expectedEn);
    expect(expectedEn).not.toMatch(/^\d/);

    // Both fixtures fall inside the same previous month, so the single group
    // label must equal the locale's Intl month+year rendering for that month.
    const a = entry({
      entry_id: 1,
      occurred_at: prevMonthDay(5).toISOString(),
    });
    const b = entry({
      entry_id: 2,
      occurred_at: prevMonthDay(25).toISOString(),
    });
    const fixtureMonth = new Date(prevMonthDay(5)).getMonth();
    const fixtureYear = new Date(prevMonthDay(5)).getFullYear();

    const hi = groupTimeline([a, b], labels, "hi");
    expect(hi[0].label).toBe(
      new Intl.DateTimeFormat("hi-IN", {
        month: "long",
        year: "numeric",
      }).format(new Date(fixtureYear, fixtureMonth, 1)),
    );

    const en = groupTimeline([a, b], labels, "en");
    expect(en[0].label).toBe(
      new Intl.DateTimeFormat("en-IN", {
        month: "long",
        year: "numeric",
      }).format(new Date(fixtureYear, fixtureMonth, 1)),
    );
  });
});

describe("countByType", () => {
  it("counts every filter type plus the truthy `all` total", () => {
    const entries = [
      entry({ entry_type: "prescription" }),
      entry({ entry_type: "lab_report" }),
      entry({ entry_type: "prescription" }),
      entry({ entry_type: "metric" }),
    ];
    expect(countByType(entries)).toEqual({
      all: 4,
      consultation: 0,
      prescription: 2,
      lab_report: 1,
      metric: 1,
    });
  });

  it("folds settlement entries into `all` only (no dedicated filter)", () => {
    const entries = [
      entry({ entry_type: "settlement" }),
      entry({ entry_type: "consultation" }),
      entry({ entry_type: "settlement" }),
    ];
    const counts = countByType(entries);
    expect(counts.all).toBe(3);
    expect(counts.consultation).toBe(1);
    expect(counts.prescription).toBe(0);
  });

  it("reports a truthful zero for every type on an empty timeline", () => {
    expect(countByType([])).toEqual({
      all: 0,
      consultation: 0,
      prescription: 0,
      lab_report: 0,
      metric: 0,
    });
  });
});

function labEntry(payload: Record<string, unknown>): RecordEntryView {
  return entry({ entry_type: "lab_report", payload });
}

describe("entryFlagRows", () => {
  it("returns only out-of-range rows when results carries them", () => {
    const rows = entryFlagRows(
      labEntry({
        results: [
          { test: "Hb", value: "11.2 g/dL", status: "below_range" },
          { test: "Neutrophils", value: "76%", status: "above_range" },
          { test: "WBC", value: "7,400", status: "in_range" },
        ],
      }),
    );
    expect(rows).toEqual([
      { test: "Hb", value: "11.2 g/dL", status: "below_range" },
      { test: "Neutrophils", value: "76%", status: "above_range" },
    ]);
  });

  it("ignores missing or malformed rows and never throws", () => {
    expect(entryFlagRows(labEntry({ results: [] }))).toEqual([]);
    expect(entryFlagRows(labEntry({}))).toEqual([]);
    expect(
      entryFlagRows(
        labEntry({
          results: [
            null,
            "junk",
            { value: "no test key" },
            { test: "X", value: "1", status: "unknown" },
          ],
        }),
      ),
    ).toEqual([]);
  });

  it("returns nothing for non-lab entry types", () => {
    expect(entryFlagRows(entry({ entry_type: "metric", payload: {} }))).toEqual(
      [],
    );
  });
});

describe("flaggedValues", () => {
  it("counts flagged entries and out-of-range values across a timeline", () => {
    const entries = [
      labEntry({
        results: [
          { test: "Hb", value: "11.2", status: "below_range" },
          { test: "WBC", value: "7,400", status: "in_range" },
        ],
      }),
      labEntry({
        results: [{ test: "Neutrophils", value: "76%", status: "above_range" }],
      }),
      labEntry({ results: [] }),
      labEntry({}),
      entry({ entry_type: "metric", payload: {} }),
    ];
    expect(flaggedValues(entries)).toEqual({ entries: 2, values: 2 });
  });

  it("returns truthful zeros over an empty or flag-free timeline", () => {
    expect(flaggedValues([])).toEqual({ entries: 0, values: 0 });
    expect(flaggedValues([labEntry({}), labEntry({ results: [] })])).toEqual({
      entries: 0,
      values: 0,
    });
  });
});

describe("isDeliveredPrescription", () => {
  it("is true only for prescriptions whose documented status is delivered", () => {
    expect(
      isDeliveredPrescription(
        entry({
          entry_type: "prescription",
          payload: { status: "delivered" },
        }),
      ),
    ).toBe(true);
  });

  it("treats any other status, an absent status, and non-prescriptions as not delivered", () => {
    for (const status of ["issued", "dispensed", "cancelled"]) {
      expect(
        isDeliveredPrescription(
          entry({ entry_type: "prescription", payload: { status } }),
        ),
      ).toBe(false);
    }
    expect(
      isDeliveredPrescription(
        entry({ entry_type: "prescription", payload: {} }),
      ),
    ).toBe(false);
    expect(isDeliveredPrescription(entry({ entry_type: "consultation" }))).toBe(
      false,
    );
  });
});

describe("issuedPrescriptionCount", () => {
  it("counts prescriptions whose documented status is not delivered", () => {
    const entries = [
      entry({
        entry_type: "prescription",
        payload: { prescription_id: 12, status: "issued" },
      }),
      entry({
        entry_type: "prescription",
        payload: { prescription_id: 9, status: "delivered" },
      }),
      entry({ entry_type: "prescription", payload: {} }),
      entry({ entry_type: "consultation", payload: {} }),
    ];
    expect(issuedPrescriptionCount(entries)).toBe(2);
  });

  it("returns a truthful zero when every rx is delivered or none exists", () => {
    expect(issuedPrescriptionCount([])).toBe(0);
    expect(
      issuedPrescriptionCount([
        entry({
          entry_type: "prescription",
          payload: { status: "delivered" },
        }),
      ]),
    ).toBe(0);
  });
});

describe("ENTRY_TONE", () => {
  it("maps every entry type to a stripe + icon-chip theme", () => {
    const types = [
      "consultation",
      "prescription",
      "lab_report",
      "metric",
      "settlement",
    ] as const;
    for (const type of types) {
      expect(ENTRY_TONE[type].stripe).toContain("border-l-");
      expect(ENTRY_TONE[type].chip).toContain("bg-");
    }
    expect(ENTRY_TONE.consultation).not.toEqual(ENTRY_TONE.prescription);
    expect(ENTRY_TONE.metric).toEqual(ENTRY_TONE.settlement);
  });
});
