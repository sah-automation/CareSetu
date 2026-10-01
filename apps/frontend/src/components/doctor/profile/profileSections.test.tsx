import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { STRINGS } from "@/lib/i18n/dictionaries";
import { AboutFields } from "./AboutFields";
import { AddressFields } from "./AddressFields";
import { NotificationFields } from "./NotificationFields";
import { PracticeFields } from "./PracticeFields";
import { PROFILE_ANCHORS } from "./ProfileSectionIndex";
import type { ProfileForm } from "./profileForm";

const t = STRINGS.en.doctorProfile;

function form(overrides: Partial<ProfileForm> = {}): ProfileForm {
  return {
    practice_name: "Sunrise Clinic",
    practice_address: "Main Road, Daltonganj",
    practice_latitude: "24.1957",
    practice_longitude: "85.3656",
    experience_years: "12",
    languages: "Hindi, English",
    about: "Twelve years of primary care.",
    notifications: { new_consultations: true },
    ...overrides,
  };
}

afterEach(cleanup);

describe("PracticeFields", () => {
  it("edits the name and experience", () => {
    render(<PracticeFields form={form()} invalid={[]} onChange={() => {}} />);

    expect(screen.getByLabelText(t.practiceNameLabel)).toHaveValue(
      "Sunrise Clinic",
    );
    expect(screen.getByLabelText(t.experienceLabel)).toHaveValue(12);
  });

  it("marks only the fields the validation pass named", () => {
    render(
      <PracticeFields
        form={form({ practice_name: "x".repeat(121) })}
        invalid={["practice_name"]}
        onChange={() => {}}
      />,
    );

    // `maxLength` stops the browser from ever producing this state, so the
    // validation pass is asserted through the prop the page actually passes -
    // the aria flag is the only thing a doctor or a screen reader can see.
    expect(screen.getByTestId("profile-practice-name")).toHaveAttribute(
      "aria-invalid",
      "true",
    );
    expect(screen.getByTestId("profile-experience")).toHaveAttribute(
      "aria-invalid",
      "false",
    );
  });
});

describe("AddressFields", () => {
  it("edits the languages", () => {
    render(<AddressFields form={form()} invalid={[]} onChange={() => {}} />);

    // Matched by prefix: the field's help text sits inside its label, so the
    // control's accessible name carries both ("Languages Separate with commas").
    // That is one binding for the label and its hint, which is what the pre-split
    // `Field` helper did too, and it beats a bare placeholder for a screen reader.
    expect(screen.getByLabelText(new RegExp(t.languagesLabel))).toHaveValue(
      "Hindi, English",
    );
  });

  it("offers no coordinate field at all", () => {
    const { container } = render(
      <AddressFields form={form()} invalid={[]} onChange={() => {}} />,
    );

    // The doctor is never asked a question only a map could answer. The two
    // values still travel in the write, seeded from the projection; they are
    // simply not on the page.
    expect(container.querySelectorAll('input[type="number"]')).toHaveLength(0);
    expect(screen.queryByText("24.1957")).toBeNull();
    expect(screen.queryByText("85.3656")).toBeNull();
  });

  // #616: the address moved to its own card, and this is the assertion that keeps
  // it from moving BACK. Two editors for one address is the failure this is
  // written against - they would disagree, and nothing on the page would tell the
  // doctor which one the listing shows.
  it("no longer renders a free-text address beside the address card", () => {
    const { container } = render(
      <AddressFields form={form()} invalid={[]} onChange={() => {}} />,
    );

    expect(screen.queryByTestId("profile-address")).toBeNull();
    // And the anchor went with it: `PROFILE_ANCHORS.address` is the card's id now,
    // so two elements carrying it would make the chip's target a coin toss.
    expect(container.querySelector(`#${PROFILE_ANCHORS.address}`)).toBeNull();
  });
});

describe("AboutFields", () => {
  it("edits the about prose", () => {
    render(<AboutFields form={form()} invalid={[]} onChange={() => {}} />);

    expect(screen.getByLabelText(t.aboutLabel)).toHaveValue(
      "Twelve years of primary care.",
    );
  });
});

// The sections are a SPLIT (#615), not a re-design: the brief puts the practice
// and about cards' contents in #617 and the address card's in #616. These three
// assertions are what keep the split a split - they fail the moment someone adds
// a read-only row for a field the projection carries, which is the drift the brief
// names as out of scope, and they fail before #616/#617 have written the sections
// that legitimately own those fields.
describe("the sections add no content of their own", () => {
  it("leaves the structured address parts to #616's address card", () => {
    render(<AddressFields form={form()} invalid={[]} onChange={() => {}} />);

    // The projection serves `address_line` and `pin_code` so the address card's
    // editable form can seed from them. Printing them here read-only would put
    // the address in two places and hand a doctor a PIN code nobody explains.
    expect(screen.queryByText("822001")).toBeNull();
    expect(screen.queryByTestId("profile-address-line")).toBeNull();
    expect(screen.queryByTestId("profile-pin-code")).toBeNull();
  });

  it("leaves the consulting days and hours to #617's about card", () => {
    render(<AboutFields form={form()} invalid={[]} onChange={() => {}} />);

    // Raw wire values ("mon, tue") are not doctor-facing copy, and the closed day
    // labels plus the hours editor are #617's to write.
    expect(screen.queryByTestId("profile-consulting-days")).toBeNull();
    expect(screen.queryByTestId("profile-consulting-hours")).toBeNull();
    expect(screen.queryByText("Mon-Sat, 9am-1pm")).toBeNull();
  });

  it("leaves the clinic and the specialty selection to the identity band", () => {
    render(<PracticeFields form={form()} invalid={[]} onChange={() => {}} />);

    // Both are already on the page, in the band that heads it - the clinic
    // beneath the name and the selection as chips. A second read-only copy is a
    // second place to delete when the real editor lands.
    expect(screen.queryByTestId("profile-clinic-field")).toBeNull();
    expect(screen.queryByTestId("profile-specialties-field")).toBeNull();
  });
});

describe("NotificationFields", () => {
  it("renders the canonical key vocabulary, not whatever the stored dict holds", () => {
    render(
      <NotificationFields
        form={form({
          notifications: {
            new_consultations: true,
            case_updates: true,
            // A key the backend does not know: carried through the save by the
            // page's seeding, and deliberately not given a toggle here.
            legacy_opt_in: true,
          },
        })}
        onToggle={() => {}}
      />,
    );

    const toggles = screen.getAllByRole("checkbox");
    expect(toggles).toHaveLength(5);
    expect(screen.queryByText("legacy_opt_in")).toBeNull();
    expect(
      screen.getByTestId("profile-notification-case_updates"),
    ).toBeChecked();
    expect(
      screen.getByTestId("profile-notification-credential_status"),
    ).not.toBeChecked();
  });

  it("keeps every row at the 44px touch-target floor", () => {
    render(<NotificationFields form={form()} onToggle={() => {}} />);

    for (const toggle of screen.getAllByRole("checkbox")) {
      const row = toggle.closest("label");
      // `min-h-11` is 44px: the accessibility floor is a minimum, not a preference.
      expect(row?.className).toContain("min-h-11");
    }
  });
});

// The anchor ids are what the page's chips point at, so a section that stops
// rendering its id would silently turn its chip into a dead control. This is the
// cheapest place to catch that, because the sections are what carry the ids.
describe("section anchors", () => {
  it("each section component renders exactly the id its chip addresses", () => {
    const practice = render(
      <PracticeFields form={form()} invalid={[]} onChange={() => {}} />,
    );
    expect(
      document.querySelector(`#${PROFILE_ANCHORS.practice}`),
    ).not.toBeNull();
    practice.unmount();

    // #616: the address anchor is NOT asserted here. It moved to
    // `AddressSectionCard`, which needs the shared doctor profile source to
    // render and so cannot stand up in this file, which has no provider - the
    // page suite asserts that one id renders exactly once on the real page, which
    // is the claim that matters.

    const about = render(
      <AboutFields form={form()} invalid={[]} onChange={() => {}} />,
    );
    expect(document.querySelector(`#${PROFILE_ANCHORS.about}`)).not.toBeNull();
    about.unmount();

    render(<NotificationFields form={form()} onToggle={() => {}} />);
    expect(
      document.querySelector(`#${PROFILE_ANCHORS.notifications}`),
    ).not.toBeNull();
  });
});
