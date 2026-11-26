// FEAT-008 (#677, parent #673): the shared record-entry renderer. These tests pin the
// presentational contract: the scan line (type tag + date) every entry keeps,
// the per-type detail for prescription/lab_report/settlement, the defensive
// fallback for consultation/metric/unknown/empty payloads, and the absence of
// any read. Labels are the real dictionary bundles, so EN/HI parity is
// exercised end to end.

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RecordEntryItem } from "./RecordEntryItem";
import { STRINGS } from "@/lib/i18n/dictionaries";
import type { RecordEntryType, RecordEntryView } from "@/lib/record/api";

function entry(overrides: Partial<RecordEntryView>): RecordEntryView {
  return {
    entry_id: 1,
    entry_type: "consultation",
    payload: {},
    occurred_at: "2026-09-01T00:00:00Z",
    created_at: "2026-09-01T00:00:00Z",
    ...overrides,
  };
}

function renderEntry(
  record: RecordEntryView,
  options: {
    lang?: "en" | "hi";
    testId?: string;
  } = {},
) {
  const lang = options.lang ?? "en";
  return render(
    <ul>
      <RecordEntryItem
        entry={record}
        labels={STRINGS[lang].record}
        lang={lang}
        testId={options.testId}
      />
    </ul>,
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("RecordEntryItem scan line", () => {
  it("renders the type tag and date for a consultation", () => {
    renderEntry(entry({ entry_type: "consultation" }));

    expect(screen.getByTestId("record-entry-type")).toHaveTextContent(
      STRINGS.en.record.badge.consultation,
    );
    expect(screen.getByTestId("record-entry")).toHaveTextContent(/1 Sep/);
    expect(screen.queryByTestId("record-entry-detail")).not.toBeInTheDocument();
  });

  it("keeps the tag-plus-date form for a metric", () => {
    renderEntry(entry({ entry_type: "metric" }));

    expect(screen.getByTestId("record-entry-type")).toHaveTextContent(
      STRINGS.en.record.badge.metric,
    );
    expect(screen.queryByTestId("record-entry-detail")).not.toBeInTheDocument();
  });

  it("honours a custom test id and its derived hooks", () => {
    renderEntry(entry({ entry_type: "consultation" }), {
      testId: "history-entry",
    });

    expect(screen.getByTestId("history-entry")).toBeInTheDocument();
    expect(screen.getByTestId("history-entry-type")).toBeInTheDocument();
    expect(screen.queryByTestId("record-entry")).not.toBeInTheDocument();
  });

  it("renders an unparseable date verbatim instead of Invalid Date", () => {
    renderEntry(entry({ occurred_at: "not-a-date" }));

    expect(screen.getByTestId("record-entry")).toHaveTextContent("not-a-date");
  });
});

describe("RecordEntryItem prescription detail", () => {
  it("renders status, each medicine field and the attributed doctor", () => {
    renderEntry(
      entry({
        entry_type: "prescription",
        payload: {
          status: "delivered",
          attributed_doctor_name: "Dr. A. Kumar",
          items: [
            {
              name: "Amlodipine",
              dose: "5 mg",
              frequency: "once daily",
              duration: "30 days",
            },
          ],
        },
      }),
    );

    const detail = screen.getByTestId("record-entry-detail");
    expect(detail).toHaveTextContent(STRINGS.en.record.history.status);
    expect(detail).toHaveTextContent(STRINGS.en.record.badge.delivered);
    expect(screen.getByTestId("record-entry-medicine")).toHaveTextContent(
      "Amlodipine",
    );
    expect(detail).toHaveTextContent("Dose: 5 mg");
    expect(detail).toHaveTextContent("Frequency: once daily");
    expect(detail).toHaveTextContent("Duration: 30 days");
    expect(detail).toHaveTextContent(STRINGS.en.record.prescribedBy);
    expect(detail).toHaveTextContent("Dr. A. Kumar");
  });

  it("renders one line per medicine", () => {
    renderEntry(
      entry({
        entry_type: "prescription",
        payload: {
          items: [
            { name: "Amlodipine", dose: "5 mg" },
            { name: "Metformin", dose: "500 mg" },
          ],
        },
      }),
    );

    const lines = screen.getAllByTestId("record-entry-medicine");
    expect(lines).toHaveLength(2);
    expect(lines[0]).toHaveTextContent("Amlodipine");
    expect(lines[1]).toHaveTextContent("Metformin");
  });

  it("shows only the fields a medicine documents, never blank labels", () => {
    renderEntry(
      entry({
        entry_type: "prescription",
        payload: { items: [{ name: "Amlodipine", dose: "5 mg" }] },
      }),
    );

    const line = screen.getByTestId("record-entry-medicine");
    expect(line).toHaveTextContent("Dose: 5 mg");
    expect(line).not.toHaveTextContent(
      STRINGS.en.record.detail.medicine.frequency,
    );
    expect(line).not.toHaveTextContent(
      STRINGS.en.record.detail.medicine.duration,
    );
  });

  it("falls back to the scan line for an empty payload", () => {
    renderEntry(entry({ entry_type: "prescription", payload: {} }));

    expect(screen.getByTestId("record-entry-type")).toHaveTextContent(
      STRINGS.en.record.badge.prescription,
    );
    expect(screen.queryByTestId("record-entry-detail")).not.toBeInTheDocument();
  });

  it("ignores malformed medicine rows and falls back cleanly", () => {
    renderEntry(
      entry({
        entry_type: "prescription",
        payload: { items: [null, "junk", { dose: "5 mg" }] },
      }),
    );

    expect(screen.queryByTestId("record-entry-detail")).not.toBeInTheDocument();
    expect(screen.getByTestId("record-entry")).toHaveTextContent(/1 Sep/);
  });
});

describe("RecordEntryItem lab-report detail", () => {
  it("renders the file name and order reference", () => {
    renderEntry(
      entry({
        entry_type: "lab_report",
        payload: { filename: "cbc-panel.pdf", order_id: 1042 },
      }),
    );

    const detail = screen.getByTestId("record-entry-detail");
    expect(detail).toHaveTextContent(STRINGS.en.record.history.file);
    expect(detail).toHaveTextContent("cbc-panel.pdf");
    expect(detail).toHaveTextContent(STRINGS.en.record.history.order);
    expect(detail).toHaveTextContent("#1042");
  });

  it("falls back to the scan line for an empty payload", () => {
    renderEntry(entry({ entry_type: "lab_report", payload: {} }));

    expect(screen.queryByTestId("record-entry-detail")).not.toBeInTheDocument();
  });
});

describe("RecordEntryItem settlement detail", () => {
  it("renders the paise-formatted amount and order reference", () => {
    renderEntry(
      entry({
        entry_type: "settlement",
        payload: { amount_paise: 45000, order_ref: "CS-31" },
      }),
    );

    const detail = screen.getByTestId("record-entry-detail");
    expect(detail).toHaveTextContent(STRINGS.en.record.history.amount);
    expect(detail).toHaveTextContent("\u20B9450");
    expect(detail).toHaveTextContent(STRINGS.en.record.history.order);
    expect(detail).toHaveTextContent("#CS-31");
  });

  it("formats a whole-rupee amount without paise decimals", () => {
    renderEntry(
      entry({
        entry_type: "settlement",
        payload: { amount_paise: 300 },
      }),
    );

    expect(screen.getByTestId("record-entry-detail")).toHaveTextContent(
      "\u20B93",
    );
  });

  it("falls back to the scan line for an empty payload", () => {
    renderEntry(entry({ entry_type: "settlement", payload: {} }));

    expect(screen.queryByTestId("record-entry-detail")).not.toBeInTheDocument();
  });
});

describe("RecordEntryItem unknown payloads", () => {
  it("falls back to the raw type string and date for an unknown type", () => {
    renderEntry(entry({ entry_type: "mystery" as unknown as RecordEntryType }));

    expect(screen.getByTestId("record-entry-type")).toHaveTextContent(
      "mystery",
    );
    expect(screen.getByTestId("record-entry")).toHaveTextContent(/1 Sep/);
    expect(screen.queryByTestId("record-entry-detail")).not.toBeInTheDocument();
  });
});

describe("RecordEntryItem presentational", () => {
  it("performs no read when rendering a rich entry", () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);

    renderEntry(
      entry({
        entry_type: "prescription",
        payload: {
          items: [{ name: "Amlodipine", dose: "5 mg" }],
          attributed_doctor_name: "Dr. A. Kumar",
        },
      }),
    );

    expect(fetchSpy).not.toHaveBeenCalled();
  });
});

describe("RecordEntryItem Hindi parity", () => {
  it("renders the type tag and detail labels in Hindi", () => {
    renderEntry(
      entry({
        entry_type: "prescription",
        payload: {
          items: [{ name: "Amlodipine", dose: "5 mg" }],
          attributed_doctor_name: "Dr. A. Kumar",
        },
      }),
      { lang: "hi" },
    );

    expect(screen.getByTestId("record-entry-type")).toHaveTextContent(
      STRINGS.hi.record.badge.prescription,
    );
    const detail = screen.getByTestId("record-entry-detail");
    expect(detail).toHaveTextContent(STRINGS.hi.record.history.medicines);
    expect(detail).toHaveTextContent(STRINGS.hi.record.prescribedBy);
  });
});
