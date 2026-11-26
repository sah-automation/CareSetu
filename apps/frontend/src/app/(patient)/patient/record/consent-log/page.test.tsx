// PHASE-3 T9 (#218): Consent log screen suite - pending-first ordering,
// receipt expansion, inline-confirm revoke flow, revoked-stays-visible with
// stop-forward copy, egress slice, and bilingual EN/HI contract.

import {
  act,
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

import ConsentLogPage from "./page";
import { __resetLangForTests, useLang } from "@/lib/i18n/LangContext";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { REVOCATION_NOTICE_MS } from "@/lib/consent/revocationNotice";
import {
  fetchConsentLog,
  revokeConsent,
  fetchEgressLog,
  type ConsentView,
  type ConsentLog,
  type EgressLog,
  type EgressLogEntry,
} from "@/lib/consent/api";

vi.mock("@/lib/consent/api", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/consent/api")>();
  return {
    ...mod,
    fetchConsentLog: vi.fn(),
    revokeConsent: vi.fn(),
    fetchEgressLog: vi.fn(),
  };
});

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  usePathname: () => "/patient/record/consent-log",
}));

vi.mock("@/lib/auth/AuthContext", () => ({
  useAuth: () => ({
    user: { id: 7, phone: "+911234567890", roles: ["patient"] },
    selectedRole: "patient",
    switchRole: vi.fn(),
    logout: vi.fn(),
    isAuthenticated: true,
    isLoading: false,
  }),
}));

const mockFetchConsentLog = vi.mocked(fetchConsentLog);
const mockRevokeConsent = vi.mocked(revokeConsent);
const mockFetchEgressLog = vi.mocked(fetchEgressLog);

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

function langFlip() {
  const { lang, setLang } = useLang();
  return (
    <button type="button" onClick={() => setLang(lang === "en" ? "hi" : "en")}>
      flip-lang
    </button>
  );
}

function consent(overrides: Partial<ConsentView>): ConsentView {
  return {
    consent_id: 1,
    lineage_ref: "C-2026-001",
    patient_id: 7,
    counterparty_type: "doctor",
    counterparty_id: "dr-kumar",
    counterparty_display_name: null,
    record_scope: "Reading your last 3 months of history",
    status: "granted",
    version: 1,
    created_at: "2026-08-19T10:00:00Z",
    updated_at: "2026-08-19T11:00:00Z",
    events: [
      {
        kind: "requested",
        version: 1,
        actor_patient_id: 7,
        occurred_at: "2026-08-19T09:58:00Z",
      },
      {
        kind: "granted",
        version: 1,
        actor_patient_id: 7,
        occurred_at: "2026-08-19T11:00:00Z",
      },
    ],
    ...overrides,
  };
}

function egressEntry(overrides: Partial<EgressLogEntry>): EgressLogEntry {
  return {
    egress_id: 1,
    patient_id: 7,
    consent_id: 1,
    lineage_ref: "C-2026-001",
    version: 1,
    counterparty_type: "doctor",
    counterparty_id: "dr-kumar",
    counterparty_display_name: null,
    record_scope: "Visit history, last 3 months",
    disclosed_entry_ids: [10, 11],
    disclosed_at: "2026-08-19T12:00:00Z",
    ...overrides,
  };
}

const CONSENT_LOG: ConsentLog = {
  items: [
    // Pending request (should sort first)
    consent({
      consent_id: 3,
      lineage_ref: "RQ-2026-031",
      counterparty_type: "chemist",
      counterparty_id: "sharma-chemist",
      record_scope: "Your prescription RX-2331 for order #CS-1043",
      status: "requested",
      created_at: "2026-08-24T03:45:00Z",
      updated_at: "2026-08-24T03:45:00Z",
      events: [
        {
          kind: "requested",
          version: 1,
          actor_patient_id: 7,
          occurred_at: "2026-08-24T03:45:00Z",
        },
      ],
    }),
    // Active grant - carries a resolved counterparty name (#654)
    consent({
      consent_id: 1,
      lineage_ref: "C-2026-014",
      counterparty_type: "lab",
      counterparty_id: "sahyog-path-lab",
      counterparty_display_name: "Sahyog Diagnostics",
      record_scope: "Filing your CBC panel report for booking #CS-1042",
      status: "granted",
      created_at: "2026-08-21T04:35:00Z",
      updated_at: "2026-08-21T05:01:00Z",
      events: [
        {
          kind: "requested",
          version: 1,
          actor_patient_id: 7,
          occurred_at: "2026-08-21T04:35:00Z",
        },
        {
          kind: "granted",
          version: 1,
          actor_patient_id: 7,
          occurred_at: "2026-08-21T05:01:00Z",
        },
      ],
    }),
    // Revoked grant (older updated_at, should sort below active) - resolved name
    consent({
      consent_id: 2,
      lineage_ref: "C-2026-011",
      counterparty_type: "doctor",
      counterparty_id: "dr-kumar",
      counterparty_display_name: "Dr Anil Kumar",
      record_scope:
        "Reading your last 3 months of history during the consultation",
      status: "revoked",
      created_at: "2026-08-19T11:28:00Z",
      updated_at: "2026-08-19T16:10:00Z",
      events: [
        {
          kind: "requested",
          version: 1,
          actor_patient_id: 7,
          occurred_at: "2026-08-19T11:28:00Z",
        },
        {
          kind: "granted",
          version: 1,
          actor_patient_id: 7,
          occurred_at: "2026-08-19T12:12:00Z",
        },
        {
          kind: "revoked",
          version: 1,
          actor_patient_id: 7,
          occurred_at: "2026-08-19T16:10:00Z",
        },
      ],
    }),
  ],
};

const EGRESS_LOG: EgressLog = {
  items: [
    egressEntry({
      egress_id: 1,
      consent_id: 2,
      lineage_ref: "C-2026-011",
      counterparty_type: "doctor",
      counterparty_id: "dr-kumar",
      counterparty_display_name: "Dr Anil Kumar",
      record_scope: "Visit history, last 3 months",
      disclosed_at: "2026-08-19T12:30:00Z",
    }),
    egressEntry({
      egress_id: 2,
      consent_id: 1,
      lineage_ref: "C-2026-014",
      counterparty_type: "lab",
      counterparty_id: "sahyog-path-lab",
      counterparty_display_name: "Sahyog Diagnostics",
      record_scope: "CBC panel report (filing)",
      disclosed_at: "2026-08-21T05:03:00Z",
    }),
  ],
};

function resolveWith(log: ConsentLog | null, egress: EgressLog | null) {
  mockFetchConsentLog.mockImplementation(() =>
    log === null
      ? Promise.reject(new Error("network down"))
      : Promise.resolve(log),
  );
  mockFetchEgressLog.mockImplementation(() =>
    egress === null
      ? Promise.reject(new Error("network down"))
      : Promise.resolve(egress),
  );
}

beforeEach(() => {
  __resetLangForTests();
  resolveWith(CONSENT_LOG, EGRESS_LOG);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.useRealTimers();
});

/** Flush the load and revoke promises under fake timers, where `waitFor`
 *  cannot advance the clock itself. */
async function flush() {
  await act(async () => {});
}

async function waitForLog() {
  // Wait for either pending or history section to appear
  await waitFor(() => {
    expect(
      screen.queryByTestId("pending-section") ??
        screen.queryByTestId("history-section"),
    ).not.toBeNull();
  });
}

describe("ConsentLogPage", () => {
  it("shows skeletons while loading", () => {
    resolveWith(null, null);
    render(<ConsentLogPage />);
    expect(screen.getByTestId("consent-log-loading")).toBeInTheDocument();
  });

  it("shows error banner when fetch fails and recovers on retry", async () => {
    resolveWith(null, null);
    render(<ConsentLogPage />);
    await screen.findByTestId("error-banner");

    resolveWith(CONSENT_LOG, EGRESS_LOG);
    fireEvent.click(screen.getByTestId("error-banner-retry"));
    await waitForLog();
    expect(screen.queryByTestId("error-banner")).not.toBeInTheDocument();
  });

  it("shows empty state when consent log is empty", async () => {
    resolveWith({ items: [] }, { items: [] });
    render(<ConsentLogPage />);
    expect(await screen.findByTestId("empty-state")).toHaveTextContent(
      "No consent history yet",
    );
  });

  it("renders breadcrumbs with Record / Consent log", async () => {
    render(<ConsentLogPage />);
    await waitForLog();
    expect(screen.getByTestId("breadcrumb-current")).toHaveTextContent(
      "Consent log",
    );
  });

  it("renders page header with title and description", async () => {
    render(<ConsentLogPage />);
    await waitForLog();
    expect(
      screen.getByRole("heading", { name: "Consent log" }),
    ).toBeInTheDocument();
  });
});

describe("Pending-first ordering", () => {
  it("places pending requests above history items", async () => {
    render(<ConsentLogPage />);
    await waitForLog();

    const pending = screen.getByTestId("pending-section");
    const history = screen.getByTestId("history-section");

    // Pending section should come before history in DOM order
    expect(
      pending.compareDocumentPosition(history) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();

    // Pending should contain the requested consent
    expect(pending).toHaveTextContent(
      STRINGS.en.consentLog.counterparty.chemist,
    );
    expect(pending).toHaveTextContent("Requested");

    // History should contain active and revoked
    expect(history).toHaveTextContent(STRINGS.en.consentLog.counterparty.lab);
    expect(history).toHaveTextContent(
      STRINGS.en.consentLog.counterparty.doctor,
    );
  });
});

describe("Receipt expansion", () => {
  it("expands receipt timeline on click", async () => {
    render(<ConsentLogPage />);
    await waitForLog();

    const receipt = screen.getByTestId("receipt-1");
    const summary = receipt.querySelector("summary")!;

    // Collapsed by default
    expect(receipt).not.toHaveAttribute("open");

    fireEvent.click(summary);

    // Should be open and show event details
    await waitFor(() => {
      expect(receipt).toHaveAttribute("open");
    });
    expect(receipt).toHaveTextContent("Requested on");
    expect(receipt).toHaveTextContent("Granted on");
  });
});

describe("Inline-confirm revoke flow", () => {
  it("opens revoke sheet, confirms, and updates badge", async () => {
    const updatedConsent = consent({
      consent_id: 1,
      status: "revoked",
      events: [
        {
          kind: "requested",
          version: 1,
          actor_patient_id: 7,
          occurred_at: "2026-08-21T04:35:00Z",
        },
        {
          kind: "granted",
          version: 1,
          actor_patient_id: 7,
          occurred_at: "2026-08-21T05:01:00Z",
        },
        {
          kind: "revoked",
          version: 1,
          actor_patient_id: 7,
          occurred_at: "2026-08-25T10:00:00Z",
        },
      ],
    });
    mockRevokeConsent.mockResolvedValue(updatedConsent);

    render(<ConsentLogPage />);
    await waitForLog();

    // Click revoke on the active grant (consent_id 1)
    fireEvent.click(screen.getByTestId("revoke-1"));

    // Sheet should open
    await screen.findByTestId("revoke-sheet");
    expect(
      screen.getByRole("heading", { name: "Take back this permission?" }),
    ).toBeInTheDocument();

    // Confirm revoke
    fireEvent.click(screen.getByTestId("revoke-confirm"));

    await waitFor(() => {
      expect(mockRevokeConsent).toHaveBeenCalledWith(1);
    });

    // Toast should appear
    await screen.findByTestId("toast");
    expect(screen.getByTestId("toast")).toHaveTextContent(
      "Permission taken back - future sharing stopped.",
    );
  });

  // #565: this screen and the Settings consent panel are one confirmation shown
  // in two places, so both carry the same treatment and dismiss it the same way.
  it("confirms the revoke with the shared positive-message treatment (#565)", async () => {
    mockRevokeConsent.mockResolvedValue(
      consent({ consent_id: 1, status: "revoked" }),
    );

    render(<ConsentLogPage />);
    await waitForLog();

    fireEvent.click(screen.getByTestId("revoke-1"));
    await screen.findByTestId("revoke-sheet");
    fireEvent.click(screen.getByTestId("revoke-confirm"));

    const notice = await screen.findByTestId("toast");
    // Exact string, and load-bearing: this environment loads no stylesheet, so
    // a colour utility naming a token that does not exist emits no CSS and no
    // rendered-surface, snapshot, contrast or axe assertion here can see it
    // (axe reads the accessibility tree, not the cascade). The class list is
    // the only observable a unit test has for a treatment decision, and
    // containment - `toHaveClass("bg-success-soft")` - passes on the string
    // this replaces. Do not "simplify" it into a containment check.
    expect(notice.className).toBe(
      "rounded-md border border-success-soft bg-success-soft px-3 py-2 text-sm text-success-text",
    );
    // The outcome is announced, not left for the patient to spot.
    expect(notice).toHaveAttribute("role", "status");
  });

  it("dismisses the confirmation on its own and leaves no timer behind on unmount (#565)", async () => {
    mockRevokeConsent.mockResolvedValue(
      consent({ consent_id: 1, status: "revoked" }),
    );
    vi.useFakeTimers();
    const setTimeoutSpy = vi.spyOn(globalThis, "setTimeout");
    const clearTimeoutSpy = vi.spyOn(globalThis, "clearTimeout");

    const { unmount } = render(<ConsentLogPage />);
    await flush();
    fireEvent.click(screen.getByTestId("revoke-1"));
    await flush();
    fireEvent.click(screen.getByTestId("revoke-confirm"));
    await flush();

    expect(screen.getByTestId("toast")).toBeTruthy();
    // The countdown is the timer armed for the shared duration. This screen
    // used to arm a raw inline setTimeout with no handle and no teardown, so a
    // patient who navigated away mid-countdown left it running against a gone
    // tree. The teardown is measured, not asserted: unmounting must clear this
    // exact handle, not merely reduce some timer count.
    const armed = setTimeoutSpy.mock.results
      .map((result, index) => ({
        handle: result.value,
        delay: setTimeoutSpy.mock.calls[index]?.[1],
      }))
      .find((entry) => entry.delay === REVOCATION_NOTICE_MS);
    expect(armed).toBeDefined();

    unmount();
    expect(clearTimeoutSpy).toHaveBeenCalledWith(armed?.handle);
  });

  it("clears the confirmation on its own after the shared countdown (#565)", async () => {
    mockRevokeConsent.mockResolvedValue(
      consent({ consent_id: 1, status: "revoked" }),
    );
    vi.useFakeTimers();

    render(<ConsentLogPage />);
    await flush();
    fireEvent.click(screen.getByTestId("revoke-1"));
    await flush();
    fireEvent.click(screen.getByTestId("revoke-confirm"));
    await flush();

    expect(screen.getByTestId("toast")).toBeTruthy();

    // One named duration, imported from the same place the Settings panel reads
    // it - not a second literal that can drift from the first.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(REVOCATION_NOTICE_MS);
    });
    expect(screen.queryByTestId("toast")).toBeNull();
  });

  it("cancel closes the sheet without revoking", async () => {
    render(<ConsentLogPage />);
    await waitForLog();

    fireEvent.click(screen.getByTestId("revoke-1"));
    await screen.findByTestId("revoke-sheet");

    fireEvent.click(screen.getByTestId("revoke-cancel"));

    await waitFor(() => {
      expect(screen.queryByTestId("revoke-sheet")).not.toBeInTheDocument();
    });
    expect(mockRevokeConsent).not.toHaveBeenCalled();
  });
});

describe("Revoked grants stay visible with stop-forward copy", () => {
  it("shows revoked badge and stop-forward statement", async () => {
    render(<ConsentLogPage />);
    await waitForLog();

    const revokedCard = screen.getByTestId("consent-2");
    expect(revokedCard).toHaveTextContent("Revoked");
    expect(revokedCard).toHaveTextContent(
      "Revocation does not erase what was already seen",
    );
  });

  it("does not show revoke button on revoked grants", async () => {
    render(<ConsentLogPage />);
    await waitForLog();

    const revokedCard = screen.getByTestId("consent-2");
    expect(
      revokedCard.querySelector('[data-testid="revoke-2"]'),
    ).not.toBeInTheDocument();
  });
});

describe("Egress slice", () => {
  it("renders egress table with correct columns", async () => {
    render(<ConsentLogPage />);
    await waitForLog();

    const section = screen.getByTestId("egress-section");
    expect(section).toHaveTextContent("What has left your record");

    const table = screen.getByTestId("egress-table");
    const headers = table.querySelectorAll("th");
    expect(headers).toHaveLength(4);
    expect(headers[0]).toHaveTextContent("When");
    expect(headers[1]).toHaveTextContent("What");
    expect(headers[2]).toHaveTextContent("To whom");
    expect(headers[3]).toHaveTextContent("Under which permission");

    const rows = table.querySelectorAll("tbody tr");
    expect(rows).toHaveLength(2);
  });
});

describe("Counterparty names on the consent surfaces (#654)", () => {
  it("shows a resolved counterparty name with the role in words on the card", async () => {
    render(<ConsentLogPage />);
    await waitForLog();

    const card = screen.getByTestId("consent-2");
    expect(card).toHaveTextContent("Dr Anil Kumar");
    expect(card).toHaveTextContent(STRINGS.en.consentLog.counterparty.doctor);
    expect(card).not.toHaveTextContent("dr-kumar");
  });

  it("says the type word rather than a bare number when nothing resolves the counterparty", async () => {
    resolveWith(
      {
        items: [
          consent({
            consent_id: 9,
            counterparty_type: "chemist",
            counterparty_id: "9918",
            counterparty_display_name: null,
          }),
        ],
      },
      {
        items: [
          egressEntry({
            egress_id: 9,
            counterparty_type: "chemist",
            counterparty_id: "9918",
            counterparty_display_name: null,
          }),
        ],
      },
    );
    render(<ConsentLogPage />);
    await waitForLog();

    const card = screen.getByTestId("consent-9");
    expect(card).toHaveTextContent(STRINGS.en.consentLog.counterparty.chemist);
    expect(card).not.toHaveTextContent("9918");
    // The label carries the word, so the role field must not repeat it.
    const chemistWord = STRINGS.en.consentLog.counterparty.chemist;
    const seen = (card.textContent ?? "").split(chemistWord).length - 1;
    expect(seen).toBe(1);

    const rows = screen
      .getByTestId("egress-table")
      .querySelectorAll("tbody tr");
    expect(rows).toHaveLength(1);
    expect(rows[0]).toHaveTextContent(
      STRINGS.en.consentLog.counterparty.chemist,
    );
    expect(rows[0]).not.toHaveTextContent("9918");
  });

  it("reads the AI intake counterparty as the AI on the card and the To whom row", async () => {
    resolveWith(
      {
        items: [
          consent({
            consent_id: 7,
            counterparty_type: "doctor",
            counterparty_id: "intake-ai",
            counterparty_display_name: null,
          }),
        ],
      },
      {
        items: [
          egressEntry({
            egress_id: 7,
            counterparty_type: "doctor",
            counterparty_id: "intake-ai",
            counterparty_display_name: null,
          }),
        ],
      },
    );
    render(<ConsentLogPage />);
    await waitForLog();

    const en = STRINGS.en.consentLog.counterparty;
    const card = screen.getByTestId("consent-7");
    expect(card).toHaveTextContent(en.aiService);
    expect(card).toHaveTextContent(en.aiRole);
    expect(card).not.toHaveTextContent("intake-ai");
    expect(card).not.toHaveTextContent(en.doctor);

    const rows = screen
      .getByTestId("egress-table")
      .querySelectorAll("tbody tr");
    expect(rows).toHaveLength(1);
    expect(rows[0]).toHaveTextContent(en.aiService);
    expect(rows[0]).not.toHaveTextContent("intake-ai");
    expect(rows[0]).not.toHaveTextContent(en.doctor);
  });

  it("shows resolved names in the To whom column instead of the ids", async () => {
    render(<ConsentLogPage />);
    await waitForLog();

    const rows = screen
      .getByTestId("egress-table")
      .querySelectorAll("tbody tr");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("Dr Anil Kumar");
    expect(rows[0]).not.toHaveTextContent("dr-kumar");
    expect(rows[1]).toHaveTextContent("Sahyog Diagnostics");
    expect(rows[1]).not.toHaveTextContent("sahyog-path-lab");
  });

  it("names the AI counterparty in Hindi too when the language flips", async () => {
    function LangFlipHost() {
      return (
        <>
          {langFlip()}
          <ConsentLogPage />
        </>
      );
    }

    resolveWith(
      {
        items: [
          consent({
            consent_id: 7,
            counterparty_type: "doctor",
            counterparty_id: "intake-ai",
            counterparty_display_name: null,
          }),
        ],
      },
      { items: [] },
    );
    render(<LangFlipHost />);
    await waitForLog();

    fireEvent.click(screen.getByText("flip-lang"));

    const card = screen.getByTestId("consent-7");
    expect(card).toHaveTextContent(
      STRINGS.hi.consentLog.counterparty.aiService,
    );
    expect(card).toHaveTextContent(STRINGS.hi.consentLog.counterparty.aiRole);
  });
});

describe("ConsentLogPage bilingual EN/HI", () => {
  it("switches all visible text to Hindi on flip", async () => {
    function LangFlipHost() {
      return (
        <>
          {langFlip()}
          <ConsentLogPage />
        </>
      );
    }

    render(<LangFlipHost />);
    await waitForLog();

    fireEvent.click(screen.getByText("flip-lang"));

    expect(
      screen.getByRole("heading", { name: "अनुमति लॉग" }),
    ).toBeInTheDocument();

    // Pending heading
    expect(screen.getByTestId("pending-section")).toHaveTextContent(
      "आपके जवाब की ज़रूरत",
    );

    // History heading
    expect(screen.getByTestId("history-section")).toHaveTextContent(
      "पहले की अनुमतियाँ",
    );

    // Revoked stop-forward copy
    expect(screen.getByTestId("stop-forward-2")).toHaveTextContent(
      "वापसी से पहले देखी गई जानकारी मिटती नहीं",
    );

    // Egress heading
    expect(screen.getByTestId("egress-section")).toHaveTextContent(
      "आपके रिकॉर्ड से क्या निकला",
    );
  });
});
