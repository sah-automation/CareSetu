import {
  render,
  screen,
  fireEvent,
  cleanup,
  waitFor,
} from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import * as axe from "axe-core";

import { ConsentSheet, type ConsentDecision } from "./ConsentSheet";
import { __resetLangForTests } from "@/lib/i18n/LangContext";
import { useLang } from "@/lib/i18n/LangContext";
import * as consentApi from "@/lib/consent/api";

beforeEach(() => {
  __resetLangForTests();
  vi.spyOn(consentApi, "grantConsent").mockResolvedValue({
    consent_id: 1,
    lineage_ref: "C-2026-001",
    patient_id: 1,
    counterparty_type: "lab",
    counterparty_id: "lab-123",
    record_scope: "prescriptions",
    status: "granted",
    version: 1,
    created_at: "2026-08-25T10:00:00Z",
    updated_at: "2026-08-25T10:00:00Z",
    events: [
      {
        kind: "granted",
        version: 1,
        actor_patient_id: 1,
        occurred_at: "2026-08-25T10:00:00Z",
      },
    ],
  });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function LangFlip() {
  const { lang, setLang } = useLang();
  return (
    <button type="button" onClick={() => setLang(lang === "en" ? "hi" : "en")}>
      flip-lang
    </button>
  );
}

interface SetupOptions {
  onDecision?: (decision: ConsentDecision) => void;
  withLangFlip?: boolean;
}

function setup({ onDecision, withLangFlip }: SetupOptions = {}) {
  return render(
    <>
      <ConsentSheet
        requesterName="Sahyog Path Lab"
        requesterContext="via your booking · Dr. A. Kumar reference"
        scope="Your prescriptions from the last 3 months"
        validity="This one booking only. You can revoke anytime."
        counterpartyType="lab"
        counterpartyId="lab-123"
        recordScope="prescriptions"
        onDecision={onDecision}
      >
        <button type="button" data-testid="consent-trigger">
          Continue booking
        </button>
      </ConsentSheet>
      {withLangFlip && <LangFlip />}
    </>,
  );
}

async function openSheet(): Promise<HTMLElement> {
  fireEvent.click(screen.getByTestId("consent-trigger"));
  const dialog = await waitFor(() => screen.getByRole("dialog"));
  await waitFor(() => expect(dialog.getAttribute("data-state")).toBe("open"));
  return dialog;
}

describe("ConsentSheet", () => {
  it("renders only the trigger while closed", () => {
    setup();

    expect(screen.getByTestId("consent-trigger")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("shows the full §5.10 anatomy when opened", async () => {
    setup();

    await openSheet();

    expect(screen.getByText("Sharing permission")).toBeInTheDocument();
    expect(screen.getByText("Who is asking")).toBeInTheDocument();
    expect(screen.getByTestId("consent-requester-name")).toHaveTextContent(
      "Sahyog Path Lab",
    );
    // Verified badge with its icon.
    const badge = screen.getByTestId("consent-verified-badge");
    expect(badge).toHaveTextContent("Verified");
    expect(badge.querySelector("svg")).not.toBeNull();
    expect(
      screen.getByText("via your booking · Dr. A. Kumar reference"),
    ).toBeInTheDocument();
    expect(screen.getByText("What they will see")).toBeInTheDocument();
    expect(
      screen.getByText("Your prescriptions from the last 3 months"),
    ).toBeInTheDocument();
    expect(screen.getByText("For how long")).toBeInTheDocument();
    expect(
      screen.getByText("This one booking only. You can revoke anytime."),
    ).toBeInTheDocument();
    expect(screen.getByTestId("consent-allow")).toHaveTextContent("Allow");
    expect(screen.getByTestId("consent-deny")).toHaveTextContent("Not now");
    expect(screen.getByTestId("consent-log-link")).toHaveTextContent(
      "See all permissions",
    );
  });

  it("Allow calls grant API, shows receipt, then calls onDecision(allow)", async () => {
    const onDecision = vi.fn();
    setup({ onDecision });

    await openSheet();
    fireEvent.click(screen.getByTestId("consent-allow"));

    // Loading state
    await waitFor(() =>
      expect(screen.getByText("Recording permission...")).toBeInTheDocument(),
    );

    // Receipt state
    await waitFor(() =>
      expect(screen.getByTestId("consent-receipt-title")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("consent-receipt-line1")).toHaveTextContent(
      "You allowed Sahyog Path Lab to read your prescriptions from the last 3 months.",
    );
    expect(screen.getByTestId("consent-receipt-line2")).toHaveTextContent(
      "It is valid this one booking only. you can revoke anytime.",
    );
    expect(screen.getByTestId("consent-receipt-line3")).toHaveTextContent(
      "Receipt ref #C-2026-001 v1 · recorded just now",
    );

    // Click "Got it" to close
    fireEvent.click(screen.getByText("Got it"));

    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    expect(onDecision).toHaveBeenCalledTimes(1);
    expect(onDecision).toHaveBeenCalledWith("allow");
    expect(consentApi.grantConsent).toHaveBeenCalledWith({
      counterparty_type: "lab",
      counterparty_id: "lab-123",
      record_scope: "prescriptions",
    });
  });

  it("Not-now shows denied explanation and calls onDecision(deny) without API call", async () => {
    const onDecision = vi.fn();
    setup({ onDecision });

    await openSheet();
    fireEvent.click(screen.getByTestId("consent-deny"));

    await waitFor(() =>
      expect(screen.getByTestId("consent-denied-title")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("consent-denied-body")).toHaveTextContent(
      "Without permission, Sahyog Path Lab cannot read your prescriptions from the last 3 months. The action still proceeds - it simply starts without your record context. Changed your mind? Allow it anytime from your Consent log.",
    );

    fireEvent.click(screen.getByText("Got it"));

    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    expect(onDecision).toHaveBeenCalledTimes(1);
    expect(onDecision).toHaveBeenCalledWith("deny");
    expect(consentApi.grantConsent).not.toHaveBeenCalled();
  });

  it("shows error on grant API failure and stays in prompt", async () => {
    const onDecision = vi.fn();
    vi.spyOn(consentApi, "grantConsent").mockRejectedValueOnce(
      new Error("Network error"),
    );
    setup({ onDecision });

    await openSheet();
    fireEvent.click(screen.getByTestId("consent-allow"));

    // Error message appears
    await waitFor(() =>
      expect(screen.getByText("Network error")).toBeInTheDocument(),
    );
    // Back to prompt state
    await waitFor(() =>
      expect(screen.getByTestId("consent-allow")).toBeInTheDocument(),
    );
    expect(onDecision).not.toHaveBeenCalled();
  });

  it("moves focus into the sheet on open", async () => {
    setup();

    const dialog = await openSheet();

    expect(dialog.contains(document.activeElement)).toBe(true);
  });

  it("traps Tab focus inside the sheet while open", async () => {
    setup();

    const dialog = await openSheet();
    const focusablesInDialog = () =>
      Array.from(
        dialog.querySelectorAll<HTMLElement>(
          "button, [href], input, select, textarea",
        ),
      ).filter((el) => !el.hasAttribute("disabled"));

    // Forward Tab from the last focusable wraps to the first.
    const tabbables = focusablesInDialog();
    expect(tabbables.length).toBeGreaterThan(1);
    tabbables[tabbables.length - 1].focus();
    fireEvent.keyDown(tabbables[tabbables.length - 1], {
      key: "Tab",
      code: "Tab",
    });
    await waitFor(() =>
      expect(tabbables.indexOf(document.activeElement as HTMLElement)).toBe(0),
    );

    // Shift+Tab from the first focusable wraps back to the last.
    fireEvent.keyDown(tabbables[0], {
      key: "Tab",
      code: "Tab",
      shiftKey: true,
    });
    await waitFor(() =>
      expect(tabbables.indexOf(document.activeElement as HTMLElement)).toBe(
        tabbables.length - 1,
      ),
    );
  });

  it("closes on Escape and returns focus to the trigger", async () => {
    setup();

    const trigger = screen.getByTestId("consent-trigger");
    await openSheet();
    expect(trigger).not.toHaveFocus();

    fireEvent.keyDown(document.activeElement ?? document.body, {
      key: "Escape",
    });
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );

    expect(trigger).toHaveFocus();
  });

  it("scans clean on axe while open", async () => {
    const { container } = setup();

    await openSheet();
    const results = await axe.run(document.body);

    expect(results.violations).toEqual([]);
    expect(container).toBeTruthy();
  });

  it("flips its chrome copy to Hindi at equal quality", async () => {
    // Requester/scope/validity are host-supplied and stay as passed; every
    // component-owned string flips with the locale.
    setup({ withLangFlip: true });

    fireEvent.click(screen.getByText("flip-lang"));
    await openSheet();

    expect(screen.getByText("साझा करने की अनुमति")).toBeInTheDocument();
    expect(screen.getByText("कौन पूछ रहा है")).toBeInTheDocument();
    expect(screen.getByText("वे क्या देखेंगे")).toBeInTheDocument();
    expect(screen.getByTestId("consent-requester-name")).toHaveTextContent(
      "Sahyog Path Lab",
    );
    expect(screen.getByTestId("consent-verified-badge")).toHaveTextContent(
      "सत्यापित",
    );
    expect(screen.getByText("कितने समय के लिए")).toBeInTheDocument();
    expect(screen.getByTestId("consent-allow")).toHaveTextContent("अनुमति दें");
    expect(screen.getByTestId("consent-deny")).toHaveTextContent("अभी नहीं");
    expect(screen.getByTestId("consent-log-link")).toHaveTextContent(
      "सभी अनुमतियाँ देखें",
    );
  });

  it("shows Hindi receipt copy after Allow in Hindi locale", async () => {
    const onDecision = vi.fn();
    setup({ withLangFlip: true, onDecision });

    fireEvent.click(screen.getByText("flip-lang"));
    await openSheet();
    fireEvent.click(screen.getByTestId("consent-allow"));

    await waitFor(() =>
      expect(screen.getByTestId("consent-receipt-title")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("consent-receipt-line1")).toHaveTextContent(
      "आपने Sahyog Path Lab को Your prescriptions from the last 3 months पढ़ने की अनुमति दी।",
    );
    expect(screen.getByTestId("consent-receipt-line2")).toHaveTextContent(
      'यह "This one booking only. You can revoke anytime." तक मान्य है।',
    );
    expect(screen.getByTestId("consent-receipt-line3")).toHaveTextContent(
      "रसीद संदर्भ #C-2026-001 v1 · अभी दर्ज हुई",
    );

    fireEvent.click(screen.getByText("समझा"));

    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    expect(onDecision).toHaveBeenCalledWith("allow");
  });

  it("shows Hindi denied copy after Not-now in Hindi locale", async () => {
    const onDecision = vi.fn();
    setup({ withLangFlip: true, onDecision });

    fireEvent.click(screen.getByText("flip-lang"));
    await openSheet();
    fireEvent.click(screen.getByTestId("consent-deny"));

    await waitFor(() =>
      expect(screen.getByTestId("consent-denied-title")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("consent-denied-body")).toHaveTextContent(
      "अनुमति के बिना Sahyog Path Lab your prescriptions from the last 3 months नहीं पढ़ पाएंगे। यह क्रिया फिर भी होगी - बस रिकॉर्ड संदर्भ के बिना। मन बदले, तो अनुमति लॉग से कभी भी दे सकते हैं।",
    );

    fireEvent.click(screen.getByText("समझा"));

    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    expect(onDecision).toHaveBeenCalledWith("deny");
  });
});
