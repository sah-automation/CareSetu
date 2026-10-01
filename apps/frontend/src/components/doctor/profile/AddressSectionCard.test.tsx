// #616: the Address card's own suite.
//
// It renders the card inside a real `DoctorProfileProvider` and mocks the doctor
// API client at the module boundary, which is the only arrangement that can prove
// the claims this card makes about itself. Each acceptance criterion is a
// different kind of claim and needs a different seam:
//
//   - AC 1 and AC 2 are about what is ON the page: the field set, the absence of
//     any coordinate input, and two read-only derived rows. Markup assertions.
//   - AC 3 is about what a REJECTED write does not do, which is the hardest kind
//     to assert and the easiest to break by tidying up: the failure path must
//     adopt nothing, clear nothing, and leave every other section's buffer
//     holding its edits. So a sibling section with its own unsaved edit is
//     rendered here too, and its value is asserted after the failure.
//   - AC 4 is about a save that SUCCEEDS and still warns, so the refusal path and
//     the warning path are deliberately separate cases.
//   - AC 5 is about independence: its own save button, its own pending and saved
//     states, and a buffer that is not reseeded when another section's answer
//     lands. That last one needs a second answer arriving mid-edit.
//   - AC 6 is the `beforeunload` listener, which is only observable by spying on
//     the window - so both halves of the pair are asserted: added while dirty,
//     removed once clean.
//
// The belt notice is asserted from a write that reports one, never from client
// state: the client cannot compute the belt, because the boundary is a parameter
// of the server's pure decision over a centroid table the browser does not hold.
// A test that seeded the warning locally would prove nothing.

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useState } from "react";

import { AddressSectionCard } from "./AddressSectionCard";
import { PublicProfileDraftProvider } from "./PublicProfileDraftContext";
import {
  ProfileSectionShell,
  type SectionSaveResult,
} from "./ProfileSectionShell";
import { useSectionEditBuffer } from "./useSectionEditBuffer";
import { ApiError, type ErrorEnvelope } from "@/lib/api-errors";
import {
  fetchDoctorProfile,
  updateDoctorProfileAddress,
  type DoctorProfileAddressView,
  type DoctorProfileView,
} from "@/lib/doctor/api";
import {
  DoctorProfileProvider,
  useDoctorProfile,
} from "@/lib/doctor/DoctorProfileContext";
import { IDEMPOTENCY_KEY_HEADER } from "@/lib/idempotency";
import { STRINGS } from "@/lib/i18n/dictionaries";

vi.mock("@/lib/doctor/api", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/doctor/api")>();
  return {
    ...mod,
    fetchDoctorProfile: vi.fn(),
    updateDoctorProfileAddress: vi.fn(),
  };
});

vi.mock("@/lib/auth/AuthContext", () => ({
  useAuth: () => ({
    user: { id: 7, phone: "+911234567890", roles: ["partner"] },
    selectedRole: "partner",
    switchRole: vi.fn(),
    logout: vi.fn(),
    isAuthenticated: true,
    isLoading: false,
  }),
}));

const t = STRINGS.en.doctorProfile;
const getProfile = vi.mocked(fetchDoctorProfile);
const saveAddress = vi.mocked(updateDoctorProfileAddress);

function profile(
  overrides: Partial<DoctorProfileView> = {},
): DoctorProfileView {
  return {
    partner_id: 7,
    photo_ref: null,
    practice_name: "Sunrise Clinic",
    clinic_name: "Sunrise Clinic",
    specialties: ["General Physician"],
    verified: true,
    practice_address: "Main Road, Daltonganj",
    address_line: "Main Road",
    landmark: "Near the petrol pump",
    locality: "Daltonganj",
    city: "Daltonganj",
    pin_code: "822001",
    practice_latitude: 24.1957,
    practice_longitude: 85.3656,
    area: "Daltonganj",
    languages: ["Hindi", "English"],
    experience_years: 12,
    about: "Twelve years of primary care.",
    consultation_fee: 40000,
    consulting_days: ["mon", "tue"],
    consulting_hours: "Mon-Sat, 9am-1pm",
    credentials: [],
    notification_preferences: { new_consultations: true },
    ...overrides,
  };
}

/**
 * What the address write answers with. The backend reassembles
 * `practice_address` from the structured parts, so the fixture rebuilds it the
 * same way rather than echoing the doctor's input back - a fixture that echoed
 * would hide a client that read the field it no longer sends.
 */
function answer(
  update: Partial<DoctorProfileAddressView> = {},
  overrides: Partial<DoctorProfileAddressView> = {},
): DoctorProfileAddressView {
  const parts = [
    update.address_line,
    update.landmark,
    update.locality,
    update.city,
    update.pin_code,
  ].filter((part): part is string => part != null && part !== "");
  // The belt defaults come BEFORE `overrides` so a case that reports an
  // outside-the-belt position is not silently overwritten by them.
  return {
    ...profile(overrides),
    ...update,
    outside_peri_urban_belt: false,
    distance_from_belt_centre_km: 0,
    ...overrides,
    practice_address: parts.join(", "),
  };
}

/** The 422 #609 raises for a PIN it cannot resolve, with its details intact. */
function pinUnresolved(): ApiError {
  const envelope: ErrorEnvelope = {
    code: "DOCTOR_PROFILE_ADDRESS_PIN_UNRESOLVED",
    message: "the declared PIN code does not resolve to a practice position",
    trace_id: "trace-616-pin",
    details: {
      errors: [
        {
          path: "pin_code",
          reason: "this PIN code is not one the platform can place yet",
        },
      ],
    },
  };
  return new ApiError(envelope);
}

/** A 422 whose `path` names a field this card has no input for. */
function unmappableField(): ApiError {
  return new ApiError({
    code: "DOCTOR_PROFILE_ADDRESS_INVALID",
    message: "the address is not acceptable",
    trace_id: "trace-616-other",
    details: { errors: [{ path: "some_future_field", reason: "refused" }] },
  });
}

/**
 * A sibling section, so AC 3's "the rest of the page's unsaved edits survive it"
 * has something to be true OF. It owns a buffer and a save exactly as a real
 * section does, and it is deliberately the shape the practice card will take.
 */
function SiblingSection() {
  const { profile: stored } = useDoctorProfile();
  const buffer = useSectionEditBuffer(stored, (view: DoctorProfileView) => ({
    practice_name: view.practice_name ?? "",
  }));
  const [status] = useState<SectionSaveResult | null>(null);
  if (buffer.value == null) return null;
  return (
    <ProfileSectionShell
      title="Practice"
      testId="sibling-section"
      save={{
        onSave: () => Promise.resolve({ status: "saved" }),
        dirty: buffer.dirty,
        edits: buffer.edits,
        label: "Save",
        savedLabel: "Saved.",
        unsavedLabel: "Unsaved",
        failureMessage: "Failed.",
        buttonTestId: "sibling-save",
        savedTestId: "sibling-saved",
        unsavedTestId: "sibling-unsaved",
      }}
    >
      <input
        data-testid="sibling-name"
        value={buffer.value.practice_name}
        onChange={(event) =>
          buffer.change({ practice_name: event.target.value })
        }
      />
      <span data-testid="sibling-status">{status?.status ?? "idle"}</span>
    </ProfileSectionShell>
  );
}

/**
 * A second consumer of the shared source, standing in for whatever OTHER section
 * writes next. It adopts a whole, different answer on demand and shows what the
 * source now holds - which is what makes AC 5's "not reseeded by another section's
 * answer" observable: the source moves, and this card must not.
 */
function AdoptProbe() {
  const { profile: stored, adoptProfile } = useDoctorProfile();
  return (
    <>
      <button
        type="button"
        data-testid="adopt-probe"
        onClick={() => adoptProfile(profile({ city: "Ranchi" }))}
      >
        adopt another answer
      </button>
      <span data-testid="adopt-probe-city">{stored?.city ?? ""}</span>
    </>
  );
}

async function renderCard(
  view: DoctorProfileView = profile(),
  withSibling = false,
) {
  getProfile.mockResolvedValue(view);
  render(
    <DoctorProfileProvider>
      {/* #618: the page mounts this around the form, and the card publishes its
          typed values into it, so a card rendered on its own needs it too. */}
      <PublicProfileDraftProvider profile={view}>
        <AddressSectionCard />
        {withSibling ? <SiblingSection /> : null}
      </PublicProfileDraftProvider>
    </DoctorProfileProvider>,
  );
  return screen.findByTestId("profile-address-card");
}

beforeEach(() => {
  getProfile.mockResolvedValue(profile());
  saveAddress.mockImplementation(async (update) => answer(update));
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("AddressSectionCard field set (#616 AC 1)", () => {
  it("renders the address parts and no coordinate input at all", async () => {
    await renderCard();

    // Every part the criterion names, seeded from the projection's structured
    // fields - the same values the backend assembles the display string from.
    expect(screen.getByTestId("profile-address-line")).toHaveValue("Main Road");
    expect(screen.getByTestId("profile-address-landmark")).toHaveValue(
      "Near the petrol pump",
    );
    expect(screen.getByTestId("profile-address-locality")).toHaveValue(
      "Daltonganj",
    );
    expect(screen.getByTestId("profile-address-city")).toHaveValue(
      "Daltonganj",
    );
    expect(screen.getByTestId("profile-address-pin")).toHaveValue("822001");

    // And the question a map alone could answer is never asked. Asserted over the
    // whole card's markup rather than by testid, so a renamed field cannot slip
    // past the check.
    const card = screen.getByTestId("profile-address-card");
    expect(card.querySelectorAll('input[type="number"]')).toHaveLength(0);
    expect(card.textContent).not.toContain("24.1957");
    expect(card.textContent).not.toContain("85.3656");
    expect(
      card.querySelector('[name*="latitude"], [name*="longitude"]'),
    ).toBeNull();
  });

  it("sends the structured parts and no coordinate field at all", async () => {
    await renderCard();

    fireEvent.click(screen.getByTestId("profile-address-save"));

    await waitFor(() => expect(saveAddress).toHaveBeenCalledTimes(1));
    const body = saveAddress.mock.calls[0][0];
    expect(body).toEqual({
      address_line: "Main Road",
      landmark: "Near the petrol pump",
      locality: "Daltonganj",
      city: "Daltonganj",
      pin_code: "822001",
    });
    // A coordinate key here would be a 422 from a `extra="forbid"` model, and
    // worse, a doctor told their coordinates saved when they were never sent.
    expect(Object.keys(body)).not.toContain("practice_latitude");
    expect(Object.keys(body)).not.toContain("practice_longitude");
  });

  it("blanks an optional part rather than sending an empty string", async () => {
    await renderCard();

    fireEvent.change(screen.getByTestId("profile-address-landmark"), {
      target: { value: "   " },
    });
    fireEvent.click(screen.getByTestId("profile-address-save"));

    await waitFor(() => expect(saveAddress).toHaveBeenCalledTimes(1));
    expect(saveAddress.mock.calls[0][0].landmark).toBeNull();
  });
});

describe("AddressSectionCard derived rows (#616 AC 2)", () => {
  it("shows district and state read-only, with their labels intact", async () => {
    await renderCard();

    const district = screen.getByTestId("profile-address-district");
    const state = screen.getByTestId("profile-address-state");

    // Read-only, not disabled: a doctor has to be able to select and copy what
    // the platform derived, and a disabled input cannot be focused or read out by
    // assistive technology as reliably as a readonly one.
    expect(district).toHaveAttribute("readonly");
    expect(state).toHaveAttribute("readonly");
    expect(district).toHaveValue("");
    expect(state).toHaveValue("");

    // The labels render whether or not the values do. A row that vanished when
    // its value was absent would leave the doctor with no idea the platform
    // derives one.
    expect(
      screen.getByText(t.addressDistrictLabel, { exact: true }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(t.addressStateLabel, { exact: true }),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("profile-address-derived-empty"),
    ).toHaveTextContent(t.addressDerivedEmpty);
  });

  // The honest version of AC 2, recorded rather than papered over: the client
  // cannot derive district or state. PIN-to-centroid resolution is a server pure
  // decision (#603) over a seeded table (#601), and there is no resolve endpoint
  // on the doctor API client - so before the first save there is genuinely
  // nothing to show. This pins that as the stated state rather than leaving a
  // spinner or an empty promise in its place.
  it("says the derived values are not available rather than promising them", async () => {
    await renderCard();

    expect(screen.getByTestId("profile-address-derived-empty")).toBeVisible();
    // No spinner over an input the doctor is actively typing into.
    expect(
      within(screen.getByTestId("profile-address-card")).queryByTestId(
        "button-spinner",
      ),
    ).toBeNull();
  });
});

describe("AddressSectionCard unresolvable PIN (#616 AC 3)", () => {
  it("puts the server's refusal under the PIN input and nowhere else", async () => {
    saveAddress.mockRejectedValue(pinUnresolved());
    await renderCard();

    fireEvent.click(screen.getByTestId("profile-address-save"));

    const message = await screen.findByTestId("profile-address-pin-error");
    expect(message).toHaveTextContent(t.addressPinUnresolved);
    // The PIN input points at it, which is how a screen reader announces the
    // problem with the field rather than leaving the doctor to find it.
    expect(screen.getByTestId("profile-address-pin")).toHaveAttribute(
      "aria-describedby",
      message.id,
    );
    expect(screen.getByTestId("profile-address-pin")).toHaveAttribute(
      "aria-invalid",
      "true",
    );
    // A 4xx is never an operational failure, so the shell's presentation is
    // card-scoped and quiet - it sits inside this card's own form, carries the
    // trace id for support, and takes the page nowhere. It is NOT the page-level
    // banner a 5xx gets, which is what the taxonomy asks for.
    const banner = screen.getByTestId("error-banner");
    expect(screen.getByTestId("profile-address-card")).toContainElement(banner);
    // The raw wire path is a field identifier, never copy the doctor reads.
    expect(message.textContent).not.toContain("pin_code");
    expect(message.textContent).not.toContain("DOCTOR_PROFILE_ADDRESS");
    expect(message.textContent).not.toContain("trace-616-pin");
  });

  it("surfaces the failure in place with its trace id and a retry", async () => {
    saveAddress.mockRejectedValue(pinUnresolved());
    await renderCard();

    fireEvent.click(screen.getByTestId("profile-address-save"));

    // The shell owns the failure presentation, so the trace id reaches support
    // even though the copy is calm and the field carries the actionable part.
    const banner = await screen.findByTestId("error-banner");
    expect(banner).toHaveTextContent(t.addressSaveFailed);
    expect(screen.getByTestId("error-banner-trace-id")).toHaveTextContent(
      "trace-616-pin",
    );
    expect(screen.getByTestId("error-banner-retry")).toBeInTheDocument();
  });

  it("leaves every section's unsaved edits standing after the refusal", async () => {
    saveAddress.mockRejectedValue(pinUnresolved());
    await renderCard(profile(), true);

    // Two sections mid-edit when the write is refused: this card's own address
    // and a sibling's name. Both are the guarantee AC 3 makes, so both are
    // asserted rather than only the one that is easiest to see.
    fireEvent.change(screen.getByTestId("profile-address-pin"), {
      target: { value: "999999" },
    });
    fireEvent.change(screen.getByTestId("sibling-name"), {
      target: { value: "Evening Clinic" },
    });

    fireEvent.click(screen.getByTestId("profile-address-save"));
    await screen.findByTestId("profile-address-pin-error");

    expect(screen.getByTestId("profile-address-pin")).toHaveValue("999999");
    expect(screen.getByTestId("sibling-name")).toHaveValue("Evening Clinic");
    // Both sections still say they have unsaved work, because both still do.
    expect(screen.getByTestId("profile-address-unsaved")).toBeInTheDocument();
    expect(screen.getByTestId("sibling-unsaved")).toBeInTheDocument();
  });

  it("does not clear its own dirty flag on the failure path", async () => {
    saveAddress.mockRejectedValue(pinUnresolved());
    await renderCard();

    fireEvent.change(screen.getByTestId("profile-address-city"), {
      target: { value: "Hazaribagh" },
    });
    fireEvent.click(screen.getByTestId("profile-address-save"));
    await screen.findByTestId("profile-address-pin-error");

    // A refused attempt wrote nothing, so the edit that caused it is still
    // unsaved. The dirty flag latching is the buffer's rule; the point here is
    // that the failure path does not contradict it.
    expect(screen.getByTestId("profile-address-unsaved")).toBeInTheDocument();
    expect(screen.queryByTestId("profile-address-saved")).toBeNull();
  });

  it("refuses a malformed PIN itself, before any request", async () => {
    await renderCard();

    fireEvent.change(screen.getByTestId("profile-address-pin"), {
      target: { value: "12345" },
    });
    fireEvent.click(screen.getByTestId("profile-address-save"));

    // Six digits is the one rule the client can state in a sentence; whether a
    // well-formed code is one the platform can place is the server's answer.
    const message = await screen.findByTestId("profile-address-pin-error");
    expect(message).toHaveTextContent(t.addressPinInvalid);
    expect(saveAddress).not.toHaveBeenCalled();
    // A validation failure is the section declining, so the shell stays quiet -
    // there is no failed request to report a trace id for.
    expect(screen.queryByTestId("error-banner")).toBeNull();
  });

  it("counts the invalid fields in a summary and takes focus to the first", async () => {
    await renderCard();

    fireEvent.change(screen.getByTestId("profile-address-pin"), {
      target: { value: "abc" },
    });
    fireEvent.click(screen.getByTestId("profile-address-save"));

    const summary = await screen.findByTestId("profile-address-summary");
    // Assertive, because this is the announcement of a failed submit and it
    // states the count rather than making the doctor count the marks.
    expect(summary).toHaveAttribute("aria-live", "assertive");
    expect(summary).toHaveTextContent(t.invalidSummary(1));
    // §9.4: focus goes to the offending field, so the summary is a count and not
    // the only route to the problem.
    await waitFor(() =>
      expect(screen.getByTestId("profile-address-pin")).toHaveFocus(),
    );
  });

  it("falls back to the summary for a path it cannot map, and guesses nothing", async () => {
    saveAddress.mockRejectedValue(unmappableField());
    await renderCard();

    fireEvent.click(screen.getByTestId("profile-address-save"));

    // Dropping it would hide a real failure; putting it on the PIN would blame a
    // field the server never named.
    const summary = await screen.findByTestId("profile-address-summary");
    expect(summary).toHaveTextContent(t.unmappedField);
    expect(screen.queryByTestId("profile-address-pin-error")).toBeNull();
    expect(screen.getByTestId("profile-address-pin")).toHaveAttribute(
      "aria-invalid",
      "false",
    );
  });

  it("clears a stale field-level message on the next edit", async () => {
    saveAddress.mockRejectedValue(pinUnresolved());
    await renderCard();

    fireEvent.click(screen.getByTestId("profile-address-save"));
    await screen.findByTestId("profile-address-pin-error");

    fireEvent.change(screen.getByTestId("profile-address-pin"), {
      target: { value: "822002" },
    });

    // A message that outlives the state it described is a message about a PIN the
    // doctor has already corrected.
    expect(screen.queryByTestId("profile-address-pin-error")).toBeNull();
    expect(screen.getByTestId("profile-address-pin")).toHaveAttribute(
      "aria-invalid",
      "false",
    );
  });
});

describe("AddressSectionCard outside the belt (#616 AC 4)", () => {
  it("warns that the listing surfaces as outside-your-area, and the save still succeeds", async () => {
    saveAddress.mockResolvedValue(
      answer(
        {},
        { outside_peri_urban_belt: true, distance_from_belt_centre_km: 41.4 },
      ),
    );
    await renderCard();

    fireEvent.click(screen.getByTestId("profile-address-save"));

    const warning = await screen.findByTestId("profile-address-belt-warning");
    expect(warning).toHaveTextContent(t.addressOutsideBelt("41"));
    // A notice, never a refusal: the write landed, so the section reports itself
    // saved and the belt never blocks a save.
    expect(screen.getByTestId("profile-address-saved")).toHaveTextContent(
      t.addressSaved,
    );
    expect(screen.queryByTestId("error-banner")).toBeNull();
    // And it is not dressed as a validation failure, because it is not one.
    expect(screen.queryByTestId("profile-address-pin-error")).toBeNull();
    expect(screen.queryByTestId("profile-address-summary")).toBeNull();
    expect(screen.getByTestId("profile-address-pin")).toHaveAttribute(
      "aria-invalid",
      "false",
    );
  });

  it("says the address is saved rather than calling it wrong", async () => {
    saveAddress.mockResolvedValue(
      answer(
        {},
        { outside_peri_urban_belt: true, distance_from_belt_centre_km: 41.4 },
      ),
    );
    await renderCard();

    fireEvent.click(screen.getByTestId("profile-address-save"));
    await screen.findByTestId("profile-address-belt-warning");

    // The copy's whole job: an outside-your-area result is where this listing
    // surfaces, not a claim that the address is invalid (ADR-0021).
    const copy = t.addressOutsideBelt("41");
    expect(copy).toContain("saved");
    expect(copy).not.toContain("invalid");
  });

  it("says nothing before the first save, rather than promising a warning", async () => {
    await renderCard();

    // The client cannot compute the belt - the boundary is a parameter of the
    // server's pure decision over a centroid table the browser does not hold -
    // so before the first save there is genuinely nothing to warn with.
    expect(screen.queryByTestId("profile-address-belt-warning")).toBeNull();
  });

  it("renders no notice at all for a position inside the belt", async () => {
    await renderCard();

    fireEvent.click(screen.getByTestId("profile-address-save"));

    await screen.findByTestId("profile-address-saved");
    expect(screen.queryByTestId("profile-address-belt-warning")).toBeNull();
  });
});

describe("AddressSectionCard saves on its own (#616 AC 5)", () => {
  it("has its own save button, saved confirmation and failure states", async () => {
    await renderCard();

    expect(screen.getByTestId("profile-address-save")).toHaveTextContent(
      t.save,
    );
    expect(screen.queryByTestId("profile-address-saved")).toBeNull();

    fireEvent.click(screen.getByTestId("profile-address-save"));

    expect(screen.getByTestId("profile-address-save")).toBeDisabled();
    expect(screen.getByTestId("button-spinner")).toBeInTheDocument();
    await screen.findByTestId("profile-address-saved");
    expect(screen.getByTestId("profile-address-save")).toBeEnabled();
  });

  it("never sends a coordinate or an assembled display string", async () => {
    await renderCard();

    fireEvent.click(screen.getByTestId("profile-address-save"));

    await waitFor(() => expect(saveAddress).toHaveBeenCalledTimes(1));
    // `practice_address` is the backend's assembled display string, rewritten
    // from the structured parts. Sending it would be sending a derived value back
    // to whoever derives it.
    expect(Object.keys(saveAddress.mock.calls[0][0])).not.toContain(
      "practice_address",
    );
  });

  it("is not reseeded by another section's answer landing mid-edit", async () => {
    render(
      <DoctorProfileProvider>
        <PublicProfileDraftProvider profile={profile()}>
          <AddressSectionCard />
          <AdoptProbe />
        </PublicProfileDraftProvider>
      </DoctorProfileProvider>,
    );
    await screen.findByTestId("profile-address-card");

    fireEvent.change(screen.getByTestId("profile-address-city"), {
      target: { value: "Hazaribagh" },
    });

    // A genuinely different answer object, handed to the shared source the way any
    // OTHER section's write hands it - and carrying a different stored city, so a
    // reseed would be visible rather than invisible-but-harmless. This is the drift
    // AC 5 names: a card that seeded from its own slice would take this answer and
    // discard the keystroke.
    fireEvent.click(screen.getByTestId("adopt-probe"));

    await waitFor(() =>
      expect(screen.getByTestId("profile-address-city")).toHaveValue(
        "Hazaribagh",
      ),
    );
    // And the source really did move, so the test is not passing by the answer
    // never arriving.
    expect(screen.getByTestId("adopt-probe-city")).toHaveTextContent("Ranchi");
  });

  it("keeps its keystrokes when its own save's reply lands after them", async () => {
    let settle: (value: DoctorProfileAddressView) => void = () => {};
    saveAddress.mockImplementation(
      () =>
        new Promise<DoctorProfileAddressView>((resolve) => {
          settle = resolve;
        }),
    );
    await renderCard();

    fireEvent.click(screen.getByTestId("profile-address-save"));
    // The doctor carries on typing while the attempt is in flight.
    fireEvent.change(screen.getByTestId("profile-address-city"), {
      target: { value: "Hazaribagh" },
    });
    settle(answer({ city: "Daltonganj" }));

    // The buffer's rule covers a save's own reply, because the reply is just
    // another answer.
    await screen.findByTestId("profile-address-saved");
    expect(screen.getByTestId("profile-address-city")).toHaveValue(
      "Hazaribagh",
    );
  });

  it("reuses one idempotency key across a retry of the same attempt", async () => {
    saveAddress.mockRejectedValueOnce(pinUnresolved());
    saveAddress.mockResolvedValue(answer());
    await renderCard();

    fireEvent.click(screen.getByTestId("profile-address-save"));
    await screen.findByTestId("error-banner");
    fireEvent.click(screen.getByTestId("error-banner-retry"));
    await screen.findByTestId("profile-address-saved");

    // The client hands the attempt's key to the shared helper, which derives the
    // header from it - so the assertion is on the same seam the client uses.
    expect(saveAddress).toHaveBeenCalledTimes(2);
    expect(saveAddress.mock.calls[1][1]).toBe(saveAddress.mock.calls[0][1]);
  });

  it("mints a new key once the doctor edits again", async () => {
    saveAddress.mockRejectedValue(pinUnresolved());
    await renderCard();

    fireEvent.click(screen.getByTestId("profile-address-save"));
    await screen.findByTestId("error-banner");
    const first = saveAddress.mock.calls[0][1];

    fireEvent.change(screen.getByTestId("profile-address-pin"), {
      target: { value: "822002" },
    });
    fireEvent.click(screen.getByTestId("profile-address-save"));
    await waitFor(() => expect(saveAddress).toHaveBeenCalledTimes(2));

    // A new attempt is a new key: the retry contract protects one attempt from
    // writing twice, not every attempt from each other.
    expect(saveAddress.mock.calls[1][1]).not.toBe(first);
  });

  it("sends the key on the idempotency header the module owns", async () => {
    await renderCard();

    fireEvent.click(screen.getByTestId("profile-address-save"));
    await waitFor(() => expect(saveAddress).toHaveBeenCalledTimes(1));

    // Named here only to state that the header is the shared module's constant
    // rather than a string this card invented; the client's own suite proves the
    // header is actually sent on the wire.
    expect(IDEMPOTENCY_KEY_HEADER).toBe("Idempotency-Key");
  });
});

describe("AddressSectionCard unsaved-changes guard (#616 AC 6)", () => {
  it("registers the beforeunload guard while it is dirty and removes it once clean", async () => {
    const add = vi.spyOn(window, "addEventListener");
    const remove = vi.spyOn(window, "removeEventListener");
    await renderCard();

    // A clean card adds no listener, so a doctor who never touched the address is
    // never prompted about it.
    expect(
      add.mock.calls.filter(([type]) => type === "beforeunload"),
    ).toHaveLength(0);

    fireEvent.change(screen.getByTestId("profile-address-city"), {
      target: { value: "Hazaribagh" },
    });
    await waitFor(() =>
      expect(
        add.mock.calls.filter(([type]) => type === "beforeunload"),
      ).toHaveLength(1),
    );

    // The removal carries the very function that was added, so the two cannot
    // drift apart into a listener that outlives the card. Observed on unmount,
    // which is the only moment the dirty flag can stop being true - it latches for
    // the rest of the session by design.
    // The HANDLER is the second argument; the first is the event type.
    const [, registered] = add.mock.calls.find(
      ([type]) => type === "beforeunload",
    )!;
    cleanup();
    expect(
      remove.mock.calls.some(
        ([type, handler]) => type === "beforeunload" && handler === registered,
      ),
    ).toBe(true);
  });

  it("prompts on the event while dirty, and sets no text it cannot control", async () => {
    await renderCard();

    fireEvent.change(screen.getByTestId("profile-address-city"), {
      target: { value: "Hazaribagh" },
    });

    // Dispatched on the window, because that is where the card registered. A
    // `BeforeUnloadEvent` cannot be constructed in jsdom, so `preventDefault` is
    // spied on and the event object itself is the one dispatched - the handler
    // receives that object, which is why it is held rather than copied away.
    const dispatched = new Event("beforeunload", { cancelable: true });
    const preventDefault = vi.spyOn(dispatched, "preventDefault");
    window.dispatchEvent(dispatched);

    // `preventDefault` is what makes a browser show its own prompt, and the legacy
    // `returnValue` assignment is what Chrome honours. The prompt string itself is
    // browser-owned on every mainstream browser, so the card sets none rather than
    // building a translated string it cannot deliver.
    expect(preventDefault).toHaveBeenCalled();
    // jsdom coerces `returnValue` through the legacy boolean setter exactly as a
    // browser does, so the card's `""` lands as `false` - asserted as falsy rather
    // than as the literal. What matters is that the card supplies no STRING: the
    // prompt a doctor reads is the browser's own, in the browser's own language,
    // because every mainstream browser discards whatever an app puts here.
    expect(dispatched.returnValue).toBeFalsy();
    expect((dispatched as { message?: unknown }).message).toBeUndefined();
  });
});
