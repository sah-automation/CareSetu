// PHASE-8.1 T11 (#449): the pick consent sheet suite (US-5/US-6). "Allow"
// records pick + consent atomically through the pick-doctor client (one
// action, no second gate), reports the backend result to the host page, and
// "Not now" closes without recording anything. An in-sheet failure keeps the
// patient in the sheet with a retryable Allow. Bilingual EN/HI.

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { __resetLangForTests } from "@/lib/i18n/LangContext";
import type { DirectoryEntry } from "@/lib/directory/search";
import { PickConsentSheet } from "./PickConsentSheet";

const { pickDoctor } = vi.hoisted(() => ({ pickDoctor: vi.fn() }));

vi.mock("@/lib/pick/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/pick/api")>();
  return { ...original, pickDoctor };
});

function entry(overrides: Partial<DirectoryEntry> = {}): DirectoryEntry {
  return {
    partner_id: 7,
    practice_name: "Dr. A. Kumar",
    partner_type: "doctor",
    specialty: "General Physician",
    area: null,
    distance_km: 1.2,
    verified: true,
    consultation_fee: 50000,
    ...overrides,
  };
}

const pickResult = {
  intake_id: 42,
  assigned_partner_id: 7,
  consent_id: 3,
  consent_lineage_ref: "C-42-001",
  consent_version: 1,
};

function setup(
  overrides: {
    open?: boolean;
    onPicked?: (result: typeof pickResult) => void;
    onOpenChange?: (open: boolean) => void;
  } = {},
) {
  const onPicked = overrides.onPicked ?? vi.fn();
  const onOpenChange = overrides.onOpenChange ?? vi.fn();
  render(
    <PickConsentSheet
      intakeId={42}
      entry={entry()}
      doctorName="Dr. A. Kumar"
      open={overrides.open ?? true}
      onOpenChange={onOpenChange}
      onPicked={onPicked}
    />,
  );
  return { onPicked, onOpenChange };
}

beforeEach(() => {
  __resetLangForTests();
  pickDoctor.mockReset();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("PickConsentSheet", () => {
  it("opens with the plain-language anatomy naming the picked doctor", async () => {
    setup();

    const dialog = await screen.findByRole("dialog");
    expect(dialog).toBeInTheDocument();
    expect(screen.getByTestId("pick-consent-title")).toHaveTextContent(
      "Sharing your pre-summary",
    );
    expect(screen.getByText("Who is asking")).toBeInTheDocument();
    expect(screen.getByTestId("pick-consent-doctor")).toHaveTextContent(
      "Dr. A. Kumar",
    );
    expect(screen.getByText("What they will see")).toBeInTheDocument();
    expect(screen.getByText("For how long")).toBeInTheDocument();
  });

  it("Allow records pick + consent atomically and reports the result once", async () => {
    pickDoctor.mockResolvedValue(pickResult);
    const { onPicked, onOpenChange } = setup();

    fireEvent.click(screen.getByTestId("pick-consent-allow"));

    await waitFor(() =>
      expect(pickDoctor).toHaveBeenCalledWith(42, 7, expect.any(String)),
    );
    await waitFor(() => expect(onPicked).toHaveBeenCalledWith(pickResult));
    expect(onOpenChange).not.toHaveBeenLastCalledWith(false);
  });

  it("Not now closes without recording anything", () => {
    const { onOpenChange } = setup();

    fireEvent.click(screen.getByTestId("pick-consent-cancel"));

    expect(pickDoctor).not.toHaveBeenCalled();
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("states the consultations and prescriptions scopes on the sheet (EN)", async () => {
    setup();

    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("consultations");
    expect(dialog).toHaveTextContent("prescriptions");
  });

  it("states the consultations and prescriptions scopes on the sheet (HI)", async () => {
    localStorage.setItem("caresetu.lang", "hi");
    setup();

    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("परामर्श");
    expect(dialog).toHaveTextContent("प्रिस्क्रिप्शन");
  });

  it("keeps the patient in the sheet with the error on a failed Allow", async () => {
    pickDoctor.mockRejectedValue(new Error("boom"));
    const { onPicked } = setup();

    fireEvent.click(screen.getByTestId("pick-consent-allow"));

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("boom"),
    );
    // Allow is still available for a retry - no pick recorded, sheet open.
    expect(onPicked).not.toHaveBeenCalled();
    expect(screen.getByTestId("pick-consent-allow")).toBeInTheDocument();
  });
});
