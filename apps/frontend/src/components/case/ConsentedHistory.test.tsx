// #658 (one history read, #645 US-62..65): the consented-history component's
// three-state timeline contract. An array renders exactly what it was given
// and never reads on its own; an explicit null is the patient's "not shared"
// answer and renders the calm locked note with no fetch, no error and no
// retry; no prop at all keeps the fail-closed consented read on its unchanged
// `consultations` scope, loading and error states included - trace id and
// retry affordance first among them, since that is the one path where a
// retry can actually help.

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ConsentedHistory } from "./ConsentedHistory";
import { ApiError } from "@/lib/api-errors";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { __resetLangForTests } from "@/lib/i18n/LangContext";
import { readConsentedHistory, type RecordTimeline } from "@/lib/record/api";

vi.mock("@/lib/record/api", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/record/api")>();
  return { ...mod, readConsentedHistory: vi.fn() };
});

const t = STRINGS.en.caseWorkspace;
const notSharedT = STRINGS.en.doctorPatients;
const getHistory = vi.mocked(readConsentedHistory);

function timeline(overrides: Partial<RecordTimeline> = {}): RecordTimeline {
  return {
    record_id: 1,
    patient_id: 3,
    created_at: "2026-01-01T00:00:00Z",
    entries: [
      {
        entry_id: 11,
        entry_type: "prescription",
        payload: {},
        occurred_at: "2026-09-01T00:00:00Z",
        created_at: "2026-09-01T00:00:00Z",
      },
      {
        entry_id: 12,
        entry_type: "consultation",
        payload: {},
        occurred_at: "2026-08-15T00:00:00Z",
        created_at: "2026-08-15T00:00:00Z",
      },
    ],
    ...overrides,
  };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  __resetLangForTests();
});

describe("ConsentedHistory supplied timeline (#658)", () => {
  it("renders the supplied entries without a consented read of its own", () => {
    render(
      <ConsentedHistory patientId={3} partnerId={7} timeline={timeline()} />,
    );

    const entries = screen.getAllByTestId("history-entry");
    expect(entries).toHaveLength(2);
    expect(entries[0]).toHaveTextContent("Prescription");
    expect(entries[0]).toHaveTextContent(/\d{1,2} Sep?t? 2026/);
    expect(getHistory).not.toHaveBeenCalled();
  });

  it("renders the empty note for a supplied timeline with no entries", () => {
    render(
      <ConsentedHistory
        patientId={3}
        partnerId={7}
        timeline={timeline({ entries: [] })}
      />,
    );

    expect(screen.getByText(t.historyEmpty)).toBeInTheDocument();
    expect(screen.queryByTestId("history-list")).not.toBeInTheDocument();
    expect(getHistory).not.toHaveBeenCalled();
  });

  it("renders the calm not-shared note for a null prop without fetching", () => {
    render(<ConsentedHistory patientId={3} partnerId={7} timeline={null} />);

    const note = screen.getByTestId("locked-section");
    expect(note).toHaveTextContent(notSharedT.notSharedTitle);
    expect(note).toHaveTextContent(notSharedT.notSharedBody);
    expect(screen.queryByTestId("history-error")).not.toBeInTheDocument();
    expect(screen.queryByTestId("history-retry")).not.toBeInTheDocument();
    expect(screen.queryByTestId("history-loading")).not.toBeInTheDocument();
    expect(getHistory).not.toHaveBeenCalled();
  });
});

describe("ConsentedHistory consented-read fallback (#658)", () => {
  it("reads the unchanged consultations scope when no timeline is given", async () => {
    getHistory.mockResolvedValue(timeline());

    render(<ConsentedHistory patientId={3} partnerId={7} />);

    await waitFor(() =>
      expect(getHistory).toHaveBeenCalledWith({
        patient_id: 3,
        scope: "consultations",
        counterparty_id: 7,
        counterparty_type: "doctor",
      }),
    );
    // The call-arg assertion above pins the scope; widening it would fail
    // here, which is exactly the consent boundary this ticket must not move.
    expect(await screen.findByTestId("history-list")).toBeInTheDocument();
    expect(screen.getAllByTestId("history-entry")).toHaveLength(2);
  });

  it("keeps the loading, error, trace and retry path recoverable", async () => {
    getHistory.mockRejectedValueOnce(
      new ApiError({
        code: "CONSENT_DENIED",
        message: "denied",
        trace_id: "t-403",
        details: {},
      }),
    );

    render(<ConsentedHistory patientId={3} partnerId={7} />);

    expect(screen.getByTestId("history-loading")).toBeInTheDocument();

    const error = await screen.findByTestId("history-error");
    expect(error).toHaveTextContent(t.historyLoadFail);
    expect(screen.getByTestId("history-trace")).toHaveTextContent("t-403");

    getHistory.mockResolvedValue(timeline());
    fireEvent.click(screen.getByTestId("history-retry"));

    expect(await screen.findByTestId("history-list")).toBeInTheDocument();
    expect(getHistory).toHaveBeenCalledTimes(2);
    expect(screen.queryByTestId("history-error")).not.toBeInTheDocument();
  });
});
