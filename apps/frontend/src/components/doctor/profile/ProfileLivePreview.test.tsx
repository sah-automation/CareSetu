// #618 AC 2: the doctor's live preview. What this suite holds is the preview's
// own job rather than the renderer's (the renderer is pinned by the no-drift suite
// in `components/public/ProviderProfile.test.tsx`): that it tracks the form as it
// is typed, that it is out of the way on a phone and in reach on a desktop, and
// that nothing a doctor types can reach a verified marker.

import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  PublicProfileDraftProvider,
  usePublicProfileDraft,
} from "./PublicProfileDraftContext";
import { ProfileLivePreview } from "./ProfileLivePreview";
import { addressDraftFromFields } from "./publicProfileProjection";
import type { DoctorProfileView } from "@/lib/doctor/api";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { LangProvider } from "@/lib/i18n/LangContext";

const t = STRINGS.en.doctorProfile;

const { emitPartnerSelected } = vi.hoisted(() => ({
  emitPartnerSelected: vi.fn(),
}));

// The preview shares a renderer with the public page, so the anonymous pick seam
// is the one thing it could inherit by accident: a doctor re-rendering their own
// editor must never look like a patient choosing them.
vi.mock("@/lib/directory/emit", () => ({ emitPartnerSelected }));

function profile(
  overrides: Partial<DoctorProfileView> = {},
): DoctorProfileView {
  return {
    partner_id: 7,
    photo_ref: null,
    practice_name: "Asha Rao",
    clinic_name: "Asha Clinic",
    specialties: ["General Physician", "Pediatrician"],
    verified: true,
    practice_address: "Main Road",
    address_line: null,
    landmark: null,
    locality: "Daltonganj",
    city: "Daltonganj",
    pin_code: "826001",
    practice_latitude: 24.1957,
    practice_longitude: 85.3656,
    area: "Daltonganj",
    languages: ["English"],
    experience_years: 12,
    about: null,
    consultation_fee: null,
    consulting_days: ["Monday"],
    consulting_hours: "9am-5pm",
    credentials: [
      {
        credential_type: "medical_registration",
        status: "verified",
        expires_at: "2030-04-30T00:00:00Z",
      },
    ],
    notification_preferences: {},
    ...overrides,
  };
}

/**
 * A minimal publisher standing in for the section cards: one button per slice, so
 * this suite can drive the draft without mounting the whole console form. The
 * cards' own suites cover that they publish on a keystroke; this one covers that
 * the preview reacts.
 */
function DraftPublisher() {
  const { publish } = usePublicProfileDraft();
  return (
    <div>
      <button
        type="button"
        data-testid="type-name"
        onClick={() => publish("practice", { practiceName: "Asha R. Verma" })}
      >
        name
      </button>
      <button
        type="button"
        data-testid="type-specialties"
        onClick={() =>
          publish("practice", {
            practiceName: "Asha R. Verma",
            specialties: ["Pediatrician"],
          })
        }
      >
        specialties
      </button>
      <button
        type="button"
        data-testid="clear-specialties"
        onClick={() => publish("practice", { specialties: [] })}
      >
        clear
      </button>
      <button
        type="button"
        data-testid="type-locality"
        onClick={() =>
          publish(
            "address",
            addressDraftFromFields({ locality: "Medininagar" }),
          )
        }
      >
        locality
      </button>
    </div>
  );
}

function renderPreview(view: DoctorProfileView = profile()) {
  return render(
    <LangProvider>
      <PublicProfileDraftProvider profile={view}>
        <ProfileLivePreview />
        <DraftPublisher />
      </PublicProfileDraftProvider>
    </LangProvider>,
  );
}

beforeEach(() => {
  emitPartnerSelected.mockClear();
});

afterEach(cleanup);

describe("ProfileLivePreview layout", () => {
  it("is sticky on a desktop and offers no control that could unstick it", () => {
    renderPreview();

    const preview = screen.getByTestId("profile-live-preview");
    expect(preview.className).toContain("lg:sticky");
    // A tall profile scrolls inside its rail rather than running past the fold with
    // none of the form left on screen.
    expect(preview.className).toContain("lg:overflow-y-auto");

    // The disclosure is `lg:hidden`: on a desktop the rail is a permanent column,
    // and a button that could take the preview away would be a control over what
    // the doctor can see of their own profile.
    const toggle = screen.getByTestId("profile-live-preview-toggle");
    expect(toggle.className).toContain("lg:hidden");
  });

  it("collapses and expands on a phone, and says which state it is in", () => {
    renderPreview();

    const toggle = screen.getByTestId("profile-live-preview-toggle");
    const content = screen.getByTestId("profile-live-preview-content");

    // Open by default on both sizes: a preview the doctor has to discover before
    // it updates is a preview that fails its one job.
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(toggle).toHaveAttribute("aria-controls", content.getAttribute("id"));
    expect(content.className).toContain("block");
    expect(toggle).toHaveTextContent(t.livePreviewHide);

    fireEvent.click(toggle);

    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle).toHaveTextContent(t.livePreviewShow);
    // Visibility is CSS, not the `hidden` attribute: the UA rule for `[hidden]` is
    // beaten by an author `lg:block`, so an attribute would read as "always
    // collapsed" on a desktop.
    expect(content.className).toContain("hidden");
    // The desktop behaviour is unconditional in both states.
    expect(content.className).toContain("lg:block");
  });

  it("names itself and says where the tick in it comes from", () => {
    renderPreview();

    const preview = screen.getByTestId("profile-live-preview");
    expect(
      within(preview).getByRole("heading", { name: t.livePreviewHeading }),
    ).toBeInTheDocument();
    // A doctor who cannot tell CareSetu's tick from their own typing is being shown
    // a verification they did not earn.
    expect(preview).toHaveTextContent(t.livePreviewHelp);
  });

  it("emits no patient pick, however many times it re-renders", () => {
    renderPreview();

    fireEvent.click(screen.getByTestId("type-name"));
    fireEvent.click(screen.getByTestId("type-locality"));

    expect(emitPartnerSelected).not.toHaveBeenCalled();
  });
});

describe("ProfileLivePreview tracks the form", () => {
  it("shows a typed name and a typed locality with no save in between", () => {
    renderPreview();

    expect(screen.getByTestId("profile-name")).toHaveTextContent("Asha Rao");

    fireEvent.click(screen.getByTestId("type-name"));
    expect(screen.getByTestId("profile-name")).toHaveTextContent(
      "Asha R. Verma",
    );

    fireEvent.click(screen.getByTestId("type-locality"));
    // #619: the typed locality renders in the DECLARED band, because that is where
    // a provider's own claim belongs. It used to appear in the solid-edged summary,
    // which is exactly the reading the band exists to stop - and this preview is
    // where that mistake would have taught a doctor the wrong page.
    expect(
      screen.getByTestId("profile-declared-address-locality"),
    ).toHaveTextContent("Medininagar");
  });

  it("shows the declared specialties and drops the row when the selection empties", () => {
    // Two claims, and #619 is why both hold. The hero's subtitle publishes the
    // FIRST member of the selection, because that is the single label the narrow
    // directory surfaces render and a preview that joined the list would show a
    // doctor something the card behind it cannot. The declared band shows EVERY
    // member, because that is what the profile page renders for a patient. The
    // preview has to agree with both, or it teaches the doctor the wrong page.
    renderPreview();

    // Saved selection: the band shows every kind of care, not just the one the
    // hero's subtitle names.
    expect(
      screen.getByTestId("profile-declared-specialties"),
    ).toHaveTextContent("General Physician, Pediatrician");

    fireEvent.click(screen.getByTestId("type-specialties"));
    expect(screen.getByTestId("profile-subtitle")).toHaveTextContent(
      "Pediatrician",
    );
    expect(screen.getByTestId("profile-subtitle")).not.toHaveTextContent(
      "General Physician",
    );
    expect(
      screen.getByTestId("profile-declared-specialties"),
    ).toHaveTextContent("Pediatrician");

    fireEvent.click(screen.getByTestId("clear-specialties"));
    const declared = screen.getByTestId("profile-declared");
    expect(within(declared).queryByText("Specialties")).toBeNull();
    expect(screen.getByTestId("profile-subtitle")).not.toHaveTextContent(
      "Pediatrician",
    );
  });

  it("renders no tick for a doctor the API has not verified", () => {
    renderPreview(profile({ verified: false }));

    expect(
      within(screen.getByTestId("profile-live-preview")).queryByTestId(
        "profile-verified",
      ),
    ).toBeNull();
  });

  it("keeps uncommitted edits when a new server answer lands under them", () => {
    // The draft follows the section edit buffer's discipline: a doctor's typing
    // outranks a server fact they have already been told, and a save's own reply
    // can land mid-sentence. A preview that reseeded would snap back to the saved
    // value while the input still said otherwise.
    const view = profile();
    const { rerender } = render(
      <LangProvider>
        <PublicProfileDraftProvider profile={view}>
          <ProfileLivePreview />
          <DraftPublisher />
        </PublicProfileDraftProvider>
      </LangProvider>,
    );

    fireEvent.click(screen.getByTestId("type-name"));

    rerender(
      <LangProvider>
        <PublicProfileDraftProvider
          profile={profile({ practice_name: "Someone Else" })}
        >
          <ProfileLivePreview />
          <DraftPublisher />
        </PublicProfileDraftProvider>
      </LangProvider>,
    );

    expect(screen.getByTestId("profile-name")).toHaveTextContent(
      "Asha R. Verma",
    );
  });

  it("takes the saved answer for a section nobody has edited", () => {
    // The mirror of the rule above, and the one that would rot silently: an
    // untouched slice must still follow the server. Freezing every slice the
    // moment any card is dirty would make a preview that could go permanently
    // stale behind an edit nobody remembers making.
    const { rerender } = render(
      <LangProvider>
        <PublicProfileDraftProvider profile={profile()}>
          <ProfileLivePreview />
          <DraftPublisher />
        </PublicProfileDraftProvider>
      </LangProvider>,
    );

    fireEvent.click(screen.getByTestId("type-name"));

    rerender(
      <LangProvider>
        <PublicProfileDraftProvider
          profile={profile({ locality: "Medininagar" })}
        >
          <ProfileLivePreview />
          <DraftPublisher />
        </PublicProfileDraftProvider>
      </LangProvider>,
    );

    // The address card published nothing, so its slice reseeded to the new answer -
    // in the declared band, which is where the locality renders.
    expect(
      screen.getByTestId("profile-declared-address-locality"),
    ).toHaveTextContent("Medininagar");
    // And the practice card's own edits were not dragged along with it.
    expect(screen.getByTestId("profile-name")).toHaveTextContent(
      "Asha R. Verma",
    );
  });
});
