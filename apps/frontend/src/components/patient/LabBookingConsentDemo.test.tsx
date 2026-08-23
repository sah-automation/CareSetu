import {
  render,
  screen,
  fireEvent,
  cleanup,
  waitFor,
} from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

import { LabBookingConsentDemo } from "./LabBookingConsentDemo";
import {
  __resetConsentGateForTests,
  clearDenied,
  hasBeenDenied,
  markDenied,
} from "@/lib/consent/consentGate";
import { __resetLangForTests, useLang } from "@/lib/i18n/LangContext";

function LangFlip() {
  const { lang, setLang } = useLang();
  return (
    <button type="button" onClick={() => setLang(lang === "en" ? "hi" : "en")}>
      flip-lang
    </button>
  );
}

beforeEach(() => {
  __resetLangForTests();
  __resetConsentGateForTests();
});

afterEach(() => {
  cleanup();
});

async function openSheet() {
  fireEvent.click(screen.getByTestId("consent-demo-trigger"));
  const dialog = await waitFor(() => screen.getByRole("dialog"));
  await waitFor(() => expect(dialog.getAttribute("data-state")).toBe("open"));
  return dialog;
}

describe("LabBookingConsentDemo", () => {
  it("starts idle behind an explicit demo-care-action affordance", () => {
    render(<LabBookingConsentDemo />);

    expect(screen.getByTestId("consent-demo-card")).toBeInTheDocument();
    expect(screen.getByText("Demo care action")).toBeInTheDocument();
    expect(screen.getByTestId("consent-demo-trigger")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(
      screen.queryByTestId("consent-demo-outcome-allow"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByTestId("consent-demo-outcome-deny"),
    ).not.toBeInTheDocument();
  });

  it("Allow proceeds: sheet closes with the granted outcome", async () => {
    render(<LabBookingConsentDemo />);

    await openSheet();
    fireEvent.click(screen.getByTestId("consent-allow"));

    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    expect(screen.getByTestId("consent-demo-outcome-allow")).toHaveTextContent(
      "Allowed - recorded in your consent log.",
    );
    // A grant never shows the denial explanation.
    expect(
      screen.queryByTestId("consent-demo-outcome-deny"),
    ).not.toBeInTheDocument();
    expect(hasBeenDenied("demo.lab-booking.history")).toBe(false);
  });

  it("Not-now blocks the action and explains plainly what stays blocked", async () => {
    render(<LabBookingConsentDemo />);

    await openSheet();
    fireEvent.click(screen.getByTestId("consent-deny"));

    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    const outcome = screen.getByTestId("consent-demo-outcome-deny");
    expect(outcome).toHaveTextContent(
      "Without permission the lab cannot attach your history to this booking",
    );
    expect(outcome).toHaveTextContent("you can still book");
    // Blocked means no granted outcome exists.
    expect(
      screen.queryByTestId("consent-demo-outcome-allow"),
    ).not.toBeInTheDocument();
    expect(hasBeenDenied("demo.lab-booking.history")).toBe(true);
  });

  it("repeat denials never nag: nothing reopens on its own", async () => {
    render(<LabBookingConsentDemo />);

    // First denial.
    await openSheet();
    fireEvent.click(screen.getByTestId("consent-deny"));
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );

    // No spontaneous dialog, no stacked explanations after the first denial.
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    // Second explicit pass behaves identically - same single explanation.
    await openSheet();
    fireEvent.click(screen.getByTestId("consent-deny"));
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );

    expect(screen.getAllByTestId("consent-demo-outcome-deny")).toHaveLength(1);
    expect(
      screen.queryByTestId("consent-demo-outcome-allow"),
    ).not.toBeInTheDocument();
  });

  it("keeps the standing denial across remounts within the session", async () => {
    const { unmount } = render(<LabBookingConsentDemo />);
    await openSheet();
    fireEvent.click(screen.getByTestId("consent-deny"));
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    unmount();

    // Returning to the surface resumes the denial conversation instead of
    // pretending nothing happened - but still without any auto-opened sheet.
    render(<LabBookingConsentDemo />);
    expect(screen.getByTestId("consent-demo-outcome-deny")).toHaveTextContent(
      "You chose Not now earlier - nothing has been shared.",
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("a later Allow supersedes an earlier standing denial across remounts", async () => {
    // Session already holds a denial from earlier this session.
    markDenied("demo.lab-booking.history");
    const { unmount } = render(<LabBookingConsentDemo />);
    expect(screen.getByTestId("consent-demo-outcome-deny")).toBeInTheDocument();
    expect(
      screen.queryByTestId("consent-demo-outcome-allow"),
    ).not.toBeInTheDocument();

    // The patient changes their mind: Allow.
    await openSheet();
    fireEvent.click(screen.getByTestId("consent-allow"));
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    expect(hasBeenDenied("demo.lab-booking.history")).toBe(false);
    unmount();

    // Grants have no client-side memory by design (no pretending
    // persistence) - so the returning card is idle again, but crucially it
    // does NOT resurrect the earlier denial.
    render(<LabBookingConsentDemo />);
    expect(
      screen.queryByTestId("consent-demo-outcome-deny"),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    clearDenied("demo.lab-booking.history");
  });

  it("carries the full demo copy bilingually at equal quality", async () => {
    render(
      <>
        <LabBookingConsentDemo />
        <LangFlip />
      </>,
    );

    fireEvent.click(screen.getByText("flip-lang"));

    expect(screen.getByText("डेमो केयर एक्शन")).toBeInTheDocument();
    expect(screen.getByText("लैब टेस्ट बुक करें")).toBeInTheDocument();
    expect(screen.getByTestId("consent-demo-trigger")).toHaveTextContent(
      "बुकिंग जारी रखें",
    );

    await openSheet();
    expect(screen.getByText("साझा करने की अनुमति")).toBeInTheDocument();
    expect(screen.getByTestId("consent-requester-name")).toHaveTextContent(
      "सहयोग पैथ लैब",
    );
    expect(
      screen.getByText("आपकी पिछले 3 महीने की प्रिस्क्रिप्शन"),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("consent-allow"));

    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    expect(screen.getByTestId("consent-demo-outcome-allow")).toHaveTextContent(
      "अनुमति मिल गई - आपके अनुमति लॉग में दर्ज हुई।",
    );
  });
});
