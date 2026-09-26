// MOD-003 (FEAT-002 record / FEAT-018 metrics), gated by MOD-004 (FEAT-002
// consent), #549 AC 1/2/3: the patient profile's Health background zone. Two
// authored surfaces bound to the owner's own APIs - the snapshot (blood group
// plus five entry lists) and the append-only height/weight series. The zone
// composes two components that read independently, so a failure in either must
// not take the other away; that independence is asserted here rather than
// assumed.
//
// The behaviour that matters is the one-time first-save confirmation. The
// backend stamps `acknowledge_phi` on the first save and never re-asks, so the
// zone asks exactly once and only before that save: a patient who declines
// keeps their typed draft and is not shown the question again on the next tap,
// and a later edit saves straight through without it. The tests below pin both
// directions, because a zone that re-prompted forever - or one that saved
// without ever asking - would each be a real consent failure.
//
// The writes are idempotent (api-standards.md §5), and on an append-only series
// that is a clinical question rather than a technical one: a retry of a lost
// response must replay the same key, or the patient gets a measurement they
// never recorded. So the key handling is pinned in both directions too.

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import * as axe from "axe-core";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { HealthBackgroundZone } from "./HealthBackgroundZone";
import { ApiError } from "@/lib/api-errors";
import { __resetLangForTests } from "@/lib/i18n/LangContext";
import { STRINGS } from "@/lib/i18n/dictionaries";
import {
  HEIGHT_CM_MIN,
  HEIGHT_CM_MAX,
  WEIGHT_KG_MAX,
  WEIGHT_KG_MIN,
} from "@/lib/health-background/form";
import {
  appendHealthMetric,
  fetchHealthBackground,
  fetchHealthMetrics,
  saveHealthBackground,
  type HealthBackground,
  type HealthBackgroundView,
  type HealthMetricEntry,
} from "@/lib/health-background/api";

vi.mock("@/lib/health-background/api", async (importOriginal) => {
  const mod =
    await importOriginal<typeof import("@/lib/health-background/api")>();
  return {
    ...mod,
    fetchHealthBackground: vi.fn(),
    saveHealthBackground: vi.fn(),
    fetchHealthMetrics: vi.fn(),
    appendHealthMetric: vi.fn(),
  };
});

const mockFetchBackground = vi.mocked(fetchHealthBackground);
const mockSaveBackground = vi.mocked(saveHealthBackground);
const mockFetchMetrics = vi.mocked(fetchHealthMetrics);
const mockAppendMetric = vi.mocked(appendHealthMetric);

const storedBackground: HealthBackground = {
  blood_group: "B+",
  conditions: ["Asthma"],
  allergies: ["Penicillin"],
  medications: ["Salbutamol inhaler"],
  immunizations: ["Tetanus 2024"],
  family_history: ["Father - diabetes"],
};

const neverSet: HealthBackgroundView = {
  set: false,
  acknowledged: false,
  background: null,
};

const acknowledged: HealthBackgroundView = {
  set: true,
  acknowledged: true,
  background: storedBackground,
};

const firstEntry: HealthMetricEntry = {
  entry_id: 12,
  height_cm: 170,
  weight_kg: 68.5,
  recorded_at: "2026-09-26T10:00:00Z",
};

function type(testId: string, value: string) {
  fireEvent.change(screen.getByTestId(testId), { target: { value } });
}

/** Render the zone and wait for both owner reads to settle. */
async function renderZone() {
  render(<HealthBackgroundZone />);
  await waitFor(() =>
    expect(screen.getByTestId("ps-hb-snapshot-form")).toBeInTheDocument(),
  );
}

beforeEach(() => {
  window.localStorage.clear();
  __resetLangForTests();
  mockFetchBackground.mockReset();
  mockSaveBackground.mockReset();
  mockFetchMetrics.mockReset();
  mockAppendMetric.mockReset();
  mockFetchBackground.mockResolvedValue(neverSet);
  mockSaveBackground.mockResolvedValue({
    set: true,
    acknowledged: true,
    background: storedBackground,
  });
  mockFetchMetrics.mockResolvedValue({ items: [], total: 0 });
  mockAppendMetric.mockResolvedValue(firstEntry);
});

afterEach(() => {
  cleanup();
});

// #549 AC 1: the zone renders the snapshot form and the series, bound to the
// snapshot and metrics APIs.
describe("Health background zone surface (#549)", () => {
  it("reads the owner snapshot and the series on mount", async () => {
    await renderZone();

    expect(mockFetchBackground).toHaveBeenCalled();
    expect(mockFetchMetrics).toHaveBeenCalled();
  });

  it("prefills every snapshot field from the stored snapshot", async () => {
    mockFetchBackground.mockResolvedValue(acknowledged);
    await renderZone();

    await waitFor(() =>
      expect(screen.getByTestId("ps-hb-blood-group")).toHaveValue("B+"),
    );
    expect(screen.getByTestId("ps-hb-conditions")).toHaveValue("Asthma");
    expect(screen.getByTestId("ps-hb-allergies")).toHaveValue("Penicillin");
    expect(screen.getByTestId("ps-hb-medications")).toHaveValue(
      "Salbutamol inhaler",
    );
    expect(screen.getByTestId("ps-hb-immunizations")).toHaveValue(
      "Tetanus 2024",
    );
    expect(screen.getByTestId("ps-hb-family_history")).toHaveValue(
      "Father - diabetes",
    );
  });

  it("hydrates from a never-set snapshot as an empty form, not an error", async () => {
    await renderZone();

    expect(screen.getByTestId("ps-health-pending")).toBeInTheDocument();
    expect(screen.getByTestId("ps-hb-blood-group")).toHaveValue("");
    expect(screen.getByTestId("ps-hb-conditions")).toHaveValue("");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("sends the six authored areas as lists, without blank lines", async () => {
    // A blank line must not become an empty entry a doctor would read as a
    // real condition, and the blood group must travel as null when the box is
    // untouched - not as an empty string.
    await renderZone();

    type("ps-hb-blood-group", "O+");
    type("ps-hb-conditions", "Asthma\n\n  Diabetes  \n");
    type("ps-hb-allergies", "Penicillin");
    type("ps-hb-medications", "");
    type("ps-hb-immunizations", "");
    type("ps-hb-family_history", "");
    fireEvent.click(screen.getByTestId("ps-hb-snapshot-save"));
    fireEvent.click(await screen.findByTestId("ps-hb-consent-confirm"));
    fireEvent.click(screen.getByTestId("ps-hb-snapshot-save"));

    await waitFor(() =>
      expect(mockSaveBackground).toHaveBeenCalledWith(
        {
          blood_group: "O+",
          conditions: ["Asthma", "Diabetes"],
          allergies: ["Penicillin"],
          medications: [],
          immunizations: [],
          family_history: [],
        },
        expect.objectContaining({ acknowledgePhi: true }),
      ),
    );
  });

  it("lists the stored measurements newest-first with their date", async () => {
    const t = STRINGS.en.profileZones;
    mockFetchMetrics.mockResolvedValue({
      items: [firstEntry, { ...firstEntry, entry_id: 11, height_cm: null }],
      total: 2,
    });
    await renderZone();

    const list = await screen.findByTestId("ps-hb-metric-12");
    expect(within(list).getByText(`170 ${t.heightUnit}`)).toBeInTheDocument();
    expect(within(list).getByText(`68.5 ${t.weightUnit}`)).toBeInTheDocument();
    expect(within(list).getByText(/2026/)).toBeInTheDocument();
    // A measurement recorded without a height says so rather than rendering 0.
    expect(
      within(screen.getByTestId("ps-hb-metric-11")).getByText(
        STRINGS.en.profileZones.metricNotRecorded,
      ),
    ).toBeInTheDocument();
  });

  it("appends a measurement and shows it in the series without a reload", async () => {
    await renderZone();

    type("ps-hb-metric-height", "170");
    type("ps-hb-metric-weight", "68.5");
    type("ps-hb-metric-recorded-at", "2026-09-26T10:00");
    fireEvent.click(screen.getByTestId("ps-hb-metric-add"));

    await waitFor(() => expect(mockAppendMetric).toHaveBeenCalled());
    // The payload carries the three authored values and no row id: the id is
    // the table's to mint.
    const [metric] = mockAppendMetric.mock.calls[0];
    expect(metric.heightCm).toBe(170);
    expect(metric.weightKg).toBe(68.5);
    expect(Number.isNaN(Date.parse(metric.recordedAt))).toBe(false);
    await waitFor(() =>
      expect(screen.getByTestId("ps-hb-metric-12")).toBeInTheDocument(),
    );
  });

  it("clears the measurement inputs after a successful append", async () => {
    await renderZone();

    type("ps-hb-metric-height", "170");
    type("ps-hb-metric-recorded-at", "2026-09-26T10:00");
    fireEvent.click(screen.getByTestId("ps-hb-metric-add"));

    // Otherwise the next tap would append the measurement the patient just
    // recorded, twice.
    await waitFor(() =>
      expect(screen.getByTestId("ps-hb-metric-height")).toHaveValue(""),
    );
  });

  it("refuses a measurement with neither height nor weight, naming the fields", async () => {
    await renderZone();

    type("ps-hb-metric-recorded-at", "2026-09-26T10:00");
    fireEvent.click(screen.getByTestId("ps-hb-metric-add"));

    expect(mockAppendMetric).not.toHaveBeenCalled();
    expect(screen.getByTestId("ps-hb-metric-error-values")).toHaveTextContent(
      STRINGS.en.profileZones.metricValueRequired,
    );
  });

  it("refuses an implausible measurement against the field it belongs to", async () => {
    await renderZone();

    type("ps-hb-metric-height", "900");
    type("ps-hb-metric-recorded-at", "2026-09-26T10:00");
    fireEvent.click(screen.getByTestId("ps-hb-metric-add"));

    expect(mockAppendMetric).not.toHaveBeenCalled();
    // The message quotes the bounds the same form enforces, so a change to
    // either cannot leave the other behind.
    expect(screen.getByTestId("ps-hb-metric-error-height")).toHaveTextContent(
      STRINGS.en.profileZones.metricHeightRange(HEIGHT_CM_MIN, HEIGHT_CM_MAX),
    );
  });

  it("refuses text in a measurement box instead of saving it as absent", async () => {
    // The dangerous case is a stray word in ONE box while the other holds a
    // real number: treating it as "not recorded" would store the measurement
    // with the patient's own reading silently missing.
    await renderZone();

    type("ps-hb-metric-height", "tall");
    type("ps-hb-metric-weight", "68.5");
    type("ps-hb-metric-recorded-at", "2026-09-26T10:00");
    fireEvent.click(screen.getByTestId("ps-hb-metric-add"));

    expect(mockAppendMetric).not.toHaveBeenCalled();
    expect(screen.getByTestId("ps-hb-metric-error-height")).toHaveTextContent(
      STRINGS.en.profileZones.metricValueNotANumber,
    );
  });

  it("asks for the measurement date when it is missing, rather than saying it is unreadable", async () => {
    // "Pick it again" over a box the patient never touched reads as a broken
    // screen; the two mistakes are different and must not share a message.
    await renderZone();

    type("ps-hb-metric-height", "170");
    fireEvent.click(screen.getByTestId("ps-hb-metric-add"));

    expect(mockAppendMetric).not.toHaveBeenCalled();
    expect(
      screen.getByTestId("ps-hb-metric-error-recordedAt"),
    ).toHaveTextContent(STRINGS.en.profileZones.metricRecordedAtRequired);
    expect(
      screen.getByTestId("ps-hb-metric-error-recordedAt"),
    ).not.toHaveTextContent(STRINGS.en.profileZones.metricDateInvalid);
  });

  it("pages the series from total rather than showing only the first page", async () => {
    // A patient with a long history would otherwise see their series stop at
    // an arbitrary cut-off with no hint that anything is missing.
    mockFetchMetrics.mockImplementation(async ({ page = 1 } = {}) =>
      page === 1
        ? { items: [firstEntry], total: 2 }
        : { items: [{ ...firstEntry, entry_id: 9 }], total: 2 },
    );
    await renderZone();

    fireEvent.click(screen.getByTestId("ps-hb-metrics-load-more"));

    await waitFor(() =>
      expect(mockFetchMetrics).toHaveBeenCalledWith({ page: 2 }),
    );
    // The page already on screen stays put: replacing the list would make it
    // jump under the button the patient just tapped.
    await waitFor(() =>
      expect(screen.getByTestId("ps-hb-metric-9")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("ps-hb-metric-12")).toBeInTheDocument();
    // The whole series is now on screen, so there is nothing left to ask for.
    await waitFor(() =>
      expect(screen.queryByTestId("ps-hb-metrics-load-more")).toBeNull(),
    );
  });

  it("keeps the earlier pages when a later page fails, and offers a retry", async () => {
    mockFetchMetrics.mockImplementation(async ({ page = 1 } = {}) => {
      if (page === 1) return { items: [firstEntry], total: 2 };
      throw new Error("offline");
    });
    await renderZone();

    fireEvent.click(screen.getByTestId("ps-hb-metrics-load-more"));

    await waitFor(() =>
      expect(
        screen.getByTestId("ps-hb-metrics-more-failed"),
      ).toBeInTheDocument(),
    );
    // A page that will not load must not cost the patient the page they can
    // already see.
    expect(screen.getByTestId("ps-hb-metric-12")).toBeInTheDocument();
    expect(screen.getByTestId("ps-hb-metrics-load-more")).toBeInTheDocument();
  });

  it("offers no paging control once the whole series is on screen", async () => {
    mockFetchMetrics.mockResolvedValue({ items: [firstEntry], total: 1 });
    await renderZone();

    expect(screen.queryByTestId("ps-hb-metrics-load-more")).toBeNull();
  });

  it("replays the same append key on a retry, so a lost response cannot duplicate the row", async () => {
    mockAppendMetric.mockRejectedValueOnce(new Error("offline"));
    mockAppendMetric.mockResolvedValueOnce(firstEntry);
    await renderZone();

    type("ps-hb-metric-height", "170");
    type("ps-hb-metric-recorded-at", "2026-09-26T10:00");
    fireEvent.click(screen.getByTestId("ps-hb-metric-add"));
    await waitFor(() =>
      expect(screen.getByTestId("ps-hb-metric-add-failed")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("ps-hb-metric-add"));

    await waitFor(() => expect(mockAppendMetric).toHaveBeenCalledTimes(2));
    const [, firstKey] = mockAppendMetric.mock.calls[0];
    const [, retryKey] = mockAppendMetric.mock.calls[1];
    // A fresh key would make the retry a SECOND measurement the patient never
    // intended to record.
    expect(firstKey).toBeTruthy();
    expect(retryKey).toBe(firstKey);
  });

  it("mints a fresh append key for the next measurement once one has landed", async () => {
    // The opposite failure: reusing a spent key would let the second
    // measurement replay as the first one and quietly vanish.
    await renderZone();

    type("ps-hb-metric-height", "170");
    type("ps-hb-metric-recorded-at", "2026-09-26T10:00");
    fireEvent.click(screen.getByTestId("ps-hb-metric-add"));
    await waitFor(() =>
      expect(screen.getByTestId("ps-hb-metric-added")).toBeInTheDocument(),
    );
    type("ps-hb-metric-height", "171");
    type("ps-hb-metric-recorded-at", "2026-09-27T10:00");
    fireEvent.click(screen.getByTestId("ps-hb-metric-add"));

    await waitFor(() => expect(mockAppendMetric).toHaveBeenCalledTimes(2));
    expect(mockAppendMetric.mock.calls[1][1]).not.toBe(
      mockAppendMetric.mock.calls[0][1],
    );
  });

  it("spends the append key when the draft is edited, so a correction is not replayed away", async () => {
    // The subtle one: the same key with a DIFFERENT body makes the gateway
    // replay the original result and report success, so the corrected value
    // would vanish behind a "Measurement added." with no complaint anywhere.
    mockAppendMetric.mockRejectedValueOnce(new Error("offline"));
    await renderZone();

    type("ps-hb-metric-height", "170");
    type("ps-hb-metric-recorded-at", "2026-09-26T10:00");
    fireEvent.click(screen.getByTestId("ps-hb-metric-add"));
    await waitFor(() =>
      expect(screen.getByTestId("ps-hb-metric-add-failed")).toBeInTheDocument(),
    );
    // The patient corrects their own number before retrying.
    type("ps-hb-metric-height", "171");
    mockAppendMetric.mockResolvedValueOnce({
      ...firstEntry,
      height_cm: 171,
    });
    fireEvent.click(screen.getByTestId("ps-hb-metric-add"));

    await waitFor(() => expect(mockAppendMetric).toHaveBeenCalledTimes(2));
    expect(mockAppendMetric.mock.calls[1][0].heightCm).toBe(171);
    expect(mockAppendMetric.mock.calls[1][1]).not.toBe(
      mockAppendMetric.mock.calls[0][1],
    );
    // And the correction is what the patient sees, not the value they replaced.
    await waitFor(() =>
      expect(
        within(screen.getByTestId("ps-hb-metric-12")).getByText(
          `171 ${STRINGS.en.profileZones.heightUnit}`,
        ),
      ).toBeInTheDocument(),
    );
  });

  it("spends the save key when the snapshot draft is edited before a retry", async () => {
    mockSaveBackground.mockRejectedValueOnce(new Error("offline"));
    mockFetchBackground.mockResolvedValue(acknowledged);
    await renderZone();

    type("ps-hb-blood-group", "A+");
    fireEvent.click(screen.getByTestId("ps-hb-snapshot-save"));
    await waitFor(() =>
      expect(screen.getByTestId("ps-hb-save-failed")).toBeInTheDocument(),
    );
    type("ps-hb-blood-group", "A-");
    mockSaveBackground.mockResolvedValueOnce({
      set: true,
      acknowledged: true,
      background: { ...storedBackground, blood_group: "A-" },
    });
    fireEvent.click(screen.getByTestId("ps-hb-snapshot-save"));

    await waitFor(() => expect(mockSaveBackground).toHaveBeenCalledTimes(2));
    expect(mockSaveBackground.mock.calls[1][0].blood_group).toBe("A-");
    expect(mockSaveBackground.mock.calls[1][1]?.retryKey).not.toBe(
      mockSaveBackground.mock.calls[0][1]?.retryKey,
    );
  });

  it("replays the same save key when a refused save is retried", async () => {
    mockSaveBackground.mockRejectedValueOnce(new Error("offline"));
    mockSaveBackground.mockResolvedValueOnce({
      set: true,
      acknowledged: true,
      background: storedBackground,
    });
    mockFetchBackground.mockResolvedValue(acknowledged);
    await renderZone();

    type("ps-hb-blood-group", "A+");
    fireEvent.click(screen.getByTestId("ps-hb-snapshot-save"));
    await waitFor(() =>
      expect(screen.getByTestId("ps-hb-save-failed")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("ps-hb-snapshot-save"));

    await waitFor(() => expect(mockSaveBackground).toHaveBeenCalledTimes(2));
    expect(mockSaveBackground.mock.calls[0][1]?.retryKey).toBeTruthy();
    expect(mockSaveBackground.mock.calls[1][1]?.retryKey).toBe(
      mockSaveBackground.mock.calls[0][1]?.retryKey,
    );
  });
});

// #549 AC 2: the first save shows and requires the confirmation; later edits
// do not re-prompt and the ack is persisted with the snapshot PUT.
describe("Health background first-save confirmation (#549)", () => {
  it("does not save until the confirmation is answered", async () => {
    await renderZone();

    type("ps-hb-blood-group", "B+");
    fireEvent.click(screen.getByTestId("ps-hb-snapshot-save"));

    const sheet = await screen.findByTestId("ps-hb-consent-sheet");
    expect(within(sheet).getByTestId("ps-hb-consent-title")).toHaveTextContent(
      STRINGS.en.profileZones.healthConsentTitle,
    );
    // Nothing was written while the question was open.
    expect(mockSaveBackground).not.toHaveBeenCalled();
  });

  it("names who gains visibility, what they see, and how to take it back", async () => {
    await renderZone();

    fireEvent.click(screen.getByTestId("ps-hb-snapshot-save"));
    const sheet = await screen.findByTestId("ps-hb-consent-sheet");

    // A blanket "your data will be shared" line would not tell the patient
    // what actually changes hands, so the copy is specific.
    expect(sheet).toHaveTextContent(STRINGS.en.profileZones.healthConsentBody);
    expect(sheet).toHaveTextContent(
      STRINGS.en.profileZones.healthConsentRecall,
    );
  });

  it("sends the acknowledgment with the first save once confirmed", async () => {
    await renderZone();

    type("ps-hb-blood-group", "B+");
    fireEvent.click(screen.getByTestId("ps-hb-snapshot-save"));
    fireEvent.click(await screen.findByTestId("ps-hb-consent-confirm"));
    fireEvent.click(screen.getByTestId("ps-hb-snapshot-save"));

    await waitFor(() =>
      expect(mockSaveBackground).toHaveBeenCalledWith(
        expect.objectContaining({ blood_group: "B+" }),
        expect.objectContaining({ acknowledgePhi: true }),
      ),
    );
  });

  it("saves without re-asking once the snapshot is acknowledged", async () => {
    // `acknowledged: true` from the read is what "already asked once" looks
    // like, so a later edit must not put the question back in front of them.
    mockFetchBackground.mockResolvedValue(acknowledged);
    await renderZone();

    type("ps-hb-blood-group", "A+");
    fireEvent.click(screen.getByTestId("ps-hb-snapshot-save"));

    await waitFor(() =>
      expect(mockSaveBackground).toHaveBeenCalledWith(
        expect.objectContaining({ blood_group: "A+" }),
        expect.objectContaining({ acknowledgePhi: false }),
      ),
    );
    expect(screen.queryByTestId("ps-hb-consent-sheet")).toBeNull();
  });

  it("stops asking after the first confirmed save, in the same visit", async () => {
    await renderZone();

    type("ps-hb-blood-group", "B+");
    fireEvent.click(screen.getByTestId("ps-hb-snapshot-save"));
    fireEvent.click(await screen.findByTestId("ps-hb-consent-confirm"));
    fireEvent.click(screen.getByTestId("ps-hb-snapshot-save"));
    await waitFor(() => expect(mockSaveBackground).toHaveBeenCalledTimes(1));

    type("ps-hb-blood-group", "AB+");
    fireEvent.click(screen.getByTestId("ps-hb-snapshot-save"));

    await waitFor(() => expect(mockSaveBackground).toHaveBeenCalledTimes(2));
    expect(screen.queryByTestId("ps-hb-consent-sheet")).toBeNull();
    expect(mockSaveBackground).toHaveBeenLastCalledWith(
      expect.objectContaining({ blood_group: "AB+" }),
      expect.objectContaining({ acknowledgePhi: false }),
    );
  });

  it("keeps the typed draft when the patient answers Not now", async () => {
    await renderZone();

    type("ps-hb-blood-group", "B+");
    fireEvent.click(screen.getByTestId("ps-hb-snapshot-save"));
    fireEvent.click(await screen.findByTestId("ps-hb-consent-cancel"));

    expect(mockSaveBackground).not.toHaveBeenCalled();
    // Declining is not losing work: the answer is theirs to change.
    expect(screen.getByTestId("ps-hb-blood-group")).toHaveValue("B+");
    expect(screen.queryByTestId("ps-hb-consent-sheet")).toBeNull();
  });

  it("asks again on the next tap after a decline, still having saved nothing", async () => {
    await renderZone();

    type("ps-hb-blood-group", "B+");
    fireEvent.click(screen.getByTestId("ps-hb-snapshot-save"));
    fireEvent.click(await screen.findByTestId("ps-hb-consent-cancel"));
    fireEvent.click(screen.getByTestId("ps-hb-snapshot-save"));

    // Not-now declines the share, it does not answer the question for good.
    expect(
      await screen.findByTestId("ps-hb-consent-sheet"),
    ).toBeInTheDocument();
    expect(mockSaveBackground).not.toHaveBeenCalled();
  });

  it("tells the patient the snapshot is now visible to their doctors", async () => {
    await renderZone();

    type("ps-hb-blood-group", "B+");
    fireEvent.click(screen.getByTestId("ps-hb-snapshot-save"));
    fireEvent.click(await screen.findByTestId("ps-hb-consent-confirm"));
    fireEvent.click(screen.getByTestId("ps-hb-snapshot-save"));

    await waitFor(() =>
      expect(screen.getByTestId("ps-hb-saved")).toHaveTextContent(
        STRINGS.en.profileZones.snapshotSharedNote,
      ),
    );
  });

  it("keeps the draft and re-asks when the acknowledged save is refused", async () => {
    // The backend refuses a first save that somehow arrives unacknowledged
    // (422 HEALTH_BACKGROUND_ACK_REQUIRED). Nothing was stored, so the
    // question is still unanswered and the zone must not mark it answered.
    mockSaveBackground.mockRejectedValue(
      new ApiError({
        code: "HEALTH_BACKGROUND_ACK_REQUIRED",
        message: "ack required",
        trace_id: "trace-hb-549",
        details: {},
      }),
    );
    await renderZone();

    type("ps-hb-blood-group", "B+");
    fireEvent.click(screen.getByTestId("ps-hb-snapshot-save"));
    fireEvent.click(await screen.findByTestId("ps-hb-consent-confirm"));
    fireEvent.click(screen.getByTestId("ps-hb-snapshot-save"));

    await waitFor(() =>
      expect(screen.getByTestId("ps-hb-save-failed")).toHaveTextContent(
        STRINGS.en.profileZones.snapshotSaveFailed,
      ),
    );
    expect(screen.getByTestId("ps-hb-blood-group")).toHaveValue("B+");
    fireEvent.click(screen.getByTestId("ps-hb-snapshot-save"));
    expect(
      await screen.findByTestId("ps-hb-consent-sheet"),
    ).toBeInTheDocument();
  });
});

// #549 AC 3: the zone states what it knows, and never shows a raw failure as
// if it were the patient's data.
describe("Health background zone states (#549)", () => {
  it("shows a loading line while the owner read is in flight", async () => {
    let resolveRead: (value: HealthBackgroundView) => void = () => {};
    mockFetchBackground.mockReturnValue(
      new Promise<HealthBackgroundView>((resolve) => {
        resolveRead = resolve;
      }),
    );
    render(<HealthBackgroundZone />);

    expect(screen.getByTestId("ps-hb-loading")).toHaveTextContent(
      STRINGS.en.profileZones.healthLoading,
    );
    // No form yet: a half-hydrated form would show blank fields as if the
    // patient had never filled anything in.
    expect(screen.queryByTestId("ps-hb-snapshot-form")).toBeNull();

    resolveRead(neverSet);
    await waitFor(() =>
      expect(screen.getByTestId("ps-hb-snapshot-form")).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("ps-hb-loading")).toBeNull();
  });

  it("offers a retry when the snapshot read fails, and recovers", async () => {
    mockFetchBackground.mockRejectedValue(
      new ApiError({
        code: "HEALTH_INTERNAL",
        message: "boom",
        trace_id: "trace-hb-read",
        details: {},
      }),
    );
    render(<HealthBackgroundZone />);

    await waitFor(() =>
      expect(screen.getByTestId("ps-hb-load-failed")).toHaveTextContent(
        STRINGS.en.profileZones.healthLoadFailed,
      ),
    );
    expect(screen.getByTestId("ps-hb-load-failed")).toHaveTextContent(
      "trace-hb-read",
    );
    // No form over a failed read: the patient must not retype a snapshot the
    // API may already be holding.
    expect(screen.queryByTestId("ps-hb-snapshot-form")).toBeNull();

    mockFetchBackground.mockResolvedValue(acknowledged);
    fireEvent.click(screen.getByTestId("ps-hb-retry"));

    await waitFor(() =>
      expect(screen.getByTestId("ps-hb-blood-group")).toHaveValue("B+"),
    );
    expect(screen.queryByTestId("ps-hb-load-failed")).toBeNull();
  });

  it("offers a retry when the series read fails, keeping the form usable", async () => {
    mockFetchMetrics.mockRejectedValue(new Error("network down"));
    await renderZone();

    await waitFor(() =>
      expect(screen.getByTestId("ps-hb-metrics-failed")).toHaveTextContent(
        STRINGS.en.profileZones.metricsLoadFailed,
      ),
    );
    // The snapshot and the series are separate reads: one failing must not
    // take the other away.
    expect(screen.getByTestId("ps-hb-snapshot-form")).toBeInTheDocument();

    mockFetchMetrics.mockResolvedValue({ items: [firstEntry], total: 1 });
    fireEvent.click(screen.getByTestId("ps-hb-metrics-retry"));

    await waitFor(() =>
      expect(screen.getByTestId("ps-hb-metric-12")).toBeInTheDocument(),
    );
  });

  it("renders the empty series as a state, not a blank box", async () => {
    await renderZone();

    expect(screen.getByTestId("ps-hb-metrics-empty")).toHaveTextContent(
      STRINGS.en.profileZones.metricsEmpty,
    );
  });

  it("names the value in each measurement row, so a screen reader is not left with two bare numbers", async () => {
    // axe cannot catch this: two unlabelled spans pass every rule and still
    // read as "170 cm, 68.5 kg" with nothing saying which is which.
    mockFetchMetrics.mockResolvedValue({ items: [firstEntry], total: 1 });
    await renderZone();

    const row = await screen.findByTestId("ps-hb-metric-12");
    const t = STRINGS.en.profileZones;
    expect(
      within(row).getByText(`${170} ${t.heightUnit}`, { exact: false }),
    ).toBeInTheDocument();
    expect(within(row).getByLabelText(t.heightUnit)).toHaveTextContent(
      `${170} ${t.heightUnit}`,
    );
    expect(within(row).getByLabelText(t.weightUnit)).toHaveTextContent(
      `${68.5} ${t.weightUnit}`,
    );
  });

  it("keeps the typed snapshot when the save fails", async () => {
    mockFetchBackground.mockResolvedValue(acknowledged);
    mockSaveBackground.mockRejectedValue(new Error("offline"));
    await renderZone();

    type("ps-hb-blood-group", "A-");
    fireEvent.click(screen.getByTestId("ps-hb-snapshot-save"));

    await waitFor(() =>
      expect(screen.getByTestId("ps-hb-save-failed")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("ps-hb-blood-group")).toHaveValue("A-");
  });

  it("keeps the typed measurement when the append fails", async () => {
    mockAppendMetric.mockRejectedValue(new Error("offline"));
    await renderZone();

    type("ps-hb-metric-height", "170");
    type("ps-hb-metric-recorded-at", "2026-09-26T10:00");
    fireEvent.click(screen.getByTestId("ps-hb-metric-add"));

    await waitFor(() =>
      expect(screen.getByTestId("ps-hb-metric-add-failed")).toBeInTheDocument(),
    );
    // A retry of the same measurement must not need retyping it.
    expect(screen.getByTestId("ps-hb-metric-height")).toHaveValue("170");
  });

  it("speaks the whole zone in the chosen locale (EN/HI parity)", async () => {
    // A returning patient whose stored preference is Hindi: the zone renders
    // in whichever locale is active, with no separate translation path.
    window.localStorage.setItem("caresetu.lang", "hi");
    await renderZone();

    const hi = STRINGS.hi.profileZones;
    expect(screen.getByTestId("ps-hb-zone")).toHaveTextContent(
      hi.bloodGroupLabel,
    );
    expect(screen.getByTestId("ps-hb-zone")).toHaveTextContent(
      hi.metricsHeading,
    );
    expect(screen.getByTestId("ps-hb-snapshot-save")).toHaveTextContent(
      hi.snapshotSave,
    );

    fireEvent.click(screen.getByTestId("ps-hb-snapshot-save"));
    const sheet = await screen.findByTestId("ps-hb-consent-sheet");
    // The confirmation is the one moment the patient must understand before
    // agreeing, so it is pinned in both locales - not just the field labels.
    expect(sheet).toHaveTextContent(hi.healthConsentTitle);
    expect(sheet).toHaveTextContent(hi.healthConsentBody);
    expect(
      within(sheet).getByTestId("ps-hb-consent-confirm"),
    ).toHaveTextContent(hi.healthConsentConfirm);
  });

  it("scans clean on the empty first-visit state, not just the loaded one", async () => {
    // The state a new patient actually lands on: two empty-state notes over a
    // blank form. A scan of only the populated state would never see it. The
    // scan renders inside a `main` landmark because that is where the page puts
    // the zone, and the landmark rule has nothing to be satisfied by otherwise.
    render(
      <main>
        <HealthBackgroundZone />
      </main>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("ps-hb-snapshot-form")).toBeInTheDocument(),
    );

    expect((await axe.run(document.body)).violations).toEqual([]);
  });

  it("scans clean on axe with the form, the series and the open confirmation", async () => {
    mockFetchMetrics.mockResolvedValue({ items: [firstEntry], total: 1 });
    render(<HealthBackgroundZone />);
    await waitFor(() =>
      expect(screen.getByTestId("ps-hb-snapshot-form")).toBeInTheDocument(),
    );

    type("ps-hb-blood-group", "A+");
    fireEvent.click(screen.getByTestId("ps-hb-snapshot-save"));

    await screen.findByTestId("ps-hb-consent-sheet");
    // The confirmation renders in a portal, so the scan covers the document
    // rather than the zone's own container.
    expect((await axe.run(document.body)).violations).toEqual([]);
  });
});
