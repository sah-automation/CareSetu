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

beforeEach(() => {
  __resetLangForTests();
});

afterEach(() => {
  cleanup();
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

  it("Allow reports the allow decision and closes", async () => {
    const onDecision = vi.fn();
    setup({ onDecision });

    await openSheet();
    fireEvent.click(screen.getByTestId("consent-allow"));

    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    expect(onDecision).toHaveBeenCalledTimes(1);
    expect(onDecision).toHaveBeenCalledWith("allow");
  });

  it("Not-now reports the deny decision and closes", async () => {
    const onDecision = vi.fn();
    setup({ onDecision });

    await openSheet();
    fireEvent.click(screen.getByTestId("consent-deny"));

    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    expect(onDecision).toHaveBeenCalledTimes(1);
    expect(onDecision).toHaveBeenCalledWith("deny");
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
});
