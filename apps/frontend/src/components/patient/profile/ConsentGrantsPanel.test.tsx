// #548: the Settings-zone consent grants panel. Settings has to answer "who
// can see my records" and give a way out, so this lists the patient's live
// granted consents and revokes them. A `health_background` grant is listed and
// revoked exactly like any other scope - it is the one grant whose loss the
// patient must be able to undo from here.

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import {
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";

import { ConsentGrantsPanel } from "./ConsentGrantsPanel";
import { ApiError } from "@/lib/api-errors";
import { __resetLangForTests } from "@/lib/i18n/LangContext";
import { STRINGS } from "@/lib/i18n/dictionaries";
import {
  fetchConsentLog,
  revokeConsent,
  type ConsentView,
} from "@/lib/consent/api";

vi.mock("@/lib/consent/api", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/consent/api")>();
  return { ...mod, fetchConsentLog: vi.fn(), revokeConsent: vi.fn() };
});

const mockFetchConsentLog = vi.mocked(fetchConsentLog);
const mockRevokeConsent = vi.mocked(revokeConsent);

class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}

beforeAll(() => {
  window.ResizeObserver =
    window.ResizeObserver ??
    (ResizeObserverStub as unknown as typeof ResizeObserver);
  if (!window.PointerEvent) {
    class PointerEventStub extends MouseEvent {}
    window.PointerEvent = PointerEventStub as unknown as typeof PointerEvent;
  }
});

const t = STRINGS.en.profileZones;

function consent(overrides: Partial<ConsentView> = {}): ConsentView {
  return {
    consent_id: 1,
    lineage_ref: "C-2026-001",
    patient_id: 7,
    counterparty_type: "doctor",
    counterparty_id: "dr-kumar",
    record_scope: "consultations",
    status: "granted",
    version: 1,
    created_at: "2026-08-19T10:00:00Z",
    updated_at: "2026-08-19T11:00:00Z",
    events: [],
    ...overrides,
  };
}

beforeEach(() => {
  window.localStorage.clear();
  __resetLangForTests();
  mockFetchConsentLog.mockReset();
  mockRevokeConsent.mockReset();
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("ConsentGrantsPanel", () => {
  it("lists the patient's granted consents with a labelled scope", async () => {
    mockFetchConsentLog.mockResolvedValue({
      items: [
        consent(),
        consent({ consent_id: 2, record_scope: "lab_results" }),
      ],
    });
    render(<ConsentGrantsPanel />);

    await waitFor(() =>
      expect(screen.getByTestId("ps-consent-1")).toBeTruthy(),
    );
    expect(screen.getByTestId("ps-consent-2")).toBeTruthy();
    expect(screen.getByTestId("ps-consent-scope-1")).toHaveTextContent(
      t.scopeLabels.consultations,
    );
    expect(screen.getByTestId("ps-consent-scope-2")).toHaveTextContent(
      t.scopeLabels.lab_results,
    );
  });

  it("lists a health_background grant and revokes it like any other scope", async () => {
    const hb = consent({
      consent_id: 9,
      record_scope: "health_background",
      counterparty_id: "dr-vyas",
    });
    mockFetchConsentLog.mockResolvedValue({ items: [hb] });
    mockRevokeConsent.mockResolvedValue({ ...hb, status: "revoked" });
    render(<ConsentGrantsPanel />);

    await waitFor(() =>
      expect(screen.getByTestId("ps-consent-9")).toBeTruthy(),
    );
    expect(screen.getByTestId("ps-consent-scope-9")).toHaveTextContent(
      t.scopeLabels.health_background,
    );

    fireEvent.click(screen.getByTestId("ps-consent-revoke-9"));
    fireEvent.click(await screen.findByTestId("ps-consent-confirm"));

    await waitFor(() => expect(mockRevokeConsent).toHaveBeenCalledWith(9));
    await waitFor(() =>
      expect(screen.queryByTestId("ps-consent-9")).toBeNull(),
    );
    expect(screen.getByTestId("ps-consent-empty")).toBeTruthy();
  });

  it("hides consents that are not granted - they are not access the patient holds", async () => {
    mockFetchConsentLog.mockResolvedValue({
      items: [
        consent({ consent_id: 1 }),
        consent({ consent_id: 2, status: "revoked" }),
        consent({ consent_id: 3, status: "requested" }),
        consent({ consent_id: 4, status: "declined" }),
      ],
    });
    render(<ConsentGrantsPanel />);

    await waitFor(() =>
      expect(screen.getByTestId("ps-consent-1")).toBeTruthy(),
    );
    expect(screen.queryByTestId("ps-consent-2")).toBeNull();
    expect(screen.queryByTestId("ps-consent-3")).toBeNull();
    expect(screen.queryByTestId("ps-consent-4")).toBeNull();
  });

  it("says so plainly when the patient has granted nothing", async () => {
    mockFetchConsentLog.mockResolvedValue({ items: [] });
    render(<ConsentGrantsPanel />);

    await waitFor(() =>
      expect(screen.getByTestId("ps-consent-empty")).toHaveTextContent(
        t.consentEmpty,
      ),
    );
  });

  it("keeps the grants on a failed load and offers a retry", async () => {
    mockFetchConsentLog.mockRejectedValueOnce(
      new ApiError({
        code: "NETWORK_ERROR",
        message: "offline",
        trace_id: "t-1",
        details: {},
      }),
    );
    mockFetchConsentLog.mockResolvedValue({ items: [consent()] });
    render(<ConsentGrantsPanel />);

    await waitFor(() =>
      expect(screen.getByTestId("ps-consent-failed")).toHaveTextContent(
        t.consentLoadFailed,
      ),
    );
    fireEvent.click(screen.getByTestId("ps-consent-retry"));

    await waitFor(() =>
      expect(screen.getByTestId("ps-consent-1")).toBeTruthy(),
    );
    expect(mockFetchConsentLog).toHaveBeenCalledTimes(2);
  });

  it("keeps the grant and the sheet open when a revoke fails", async () => {
    mockFetchConsentLog.mockResolvedValue({ items: [consent()] });
    mockRevokeConsent.mockRejectedValue(
      new ApiError({
        code: "CONSENT_ILLEGAL_TRANSITION",
        message: "nope",
        trace_id: "t-2",
        details: {},
      }),
    );
    render(<ConsentGrantsPanel />);

    await waitFor(() =>
      expect(screen.getByTestId("ps-consent-1")).toBeTruthy(),
    );
    fireEvent.click(screen.getByTestId("ps-consent-revoke-1"));
    fireEvent.click(await screen.findByTestId("ps-consent-confirm"));

    await waitFor(() =>
      expect(screen.getByTestId("ps-consent-revoke-failed")).toHaveTextContent(
        t.consentRevokeFailed,
      ),
    );
    // The grant is untouched, so the patient can retry rather than re-read.
    expect(screen.getByTestId("ps-consent-1")).toBeTruthy();
  });

  it("does not revoke until the confirm step, and can be cancelled", async () => {
    mockFetchConsentLog.mockResolvedValue({ items: [consent()] });
    render(<ConsentGrantsPanel />);

    await waitFor(() =>
      expect(screen.getByTestId("ps-consent-1")).toBeTruthy(),
    );
    fireEvent.click(screen.getByTestId("ps-consent-revoke-1"));

    expect(mockRevokeConsent).not.toHaveBeenCalled();
    fireEvent.click(await screen.findByTestId("ps-consent-cancel"));
    await waitFor(() =>
      expect(screen.queryByTestId("ps-consent-confirm")).toBeNull(),
    );
    expect(mockRevokeConsent).not.toHaveBeenCalled();
  });

  it("names the counterparty in the confirm step", async () => {
    mockFetchConsentLog.mockResolvedValue({ items: [consent()] });
    render(<ConsentGrantsPanel />);

    await waitFor(() =>
      expect(screen.getByTestId("ps-consent-1")).toBeTruthy(),
    );
    fireEvent.click(screen.getByTestId("ps-consent-revoke-1"));

    const sheet = await screen.findByTestId("ps-consent-sheet");
    expect(sheet).toHaveTextContent(t.consentRevokeBody("dr-kumar"));
  });
});
