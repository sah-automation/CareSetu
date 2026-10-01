import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ProfileIdentityBand } from "./ProfileIdentityBand";
import { PROFILE_ANCHORS, ProfileSectionIndex } from "./ProfileSectionIndex";
import type { DoctorProfileView } from "@/lib/doctor/api";
import { STRINGS } from "@/lib/i18n/dictionaries";

const t = STRINGS.en.doctorProfile;

function profile(
  overrides: Partial<DoctorProfileView> = {},
): DoctorProfileView {
  return {
    partner_id: 7,
    photo_ref: null,
    practice_name: "Asha Rao",
    clinic_name: "Asha Clinic",
    specialties: ["General Physician", "Paediatrics"],
    verified: true,
    practice_address: "Main Road",
    address_line: null,
    landmark: null,
    locality: null,
    city: null,
    pin_code: null,
    practice_latitude: 24.1957,
    practice_longitude: 85.3656,
    area: "Daltonganj",
    languages: [],
    experience_years: null,
    about: null,
    consultation_fee: null,
    consulting_days: [],
    consulting_hours: null,
    credentials: [],
    notification_preferences: {},
    ...overrides,
  };
}

// Nothing about the band needs transport, so the defaults are inert callbacks
// rather than mocks: a test that wants one to fire asks for it explicitly.
const noop = () => {};

function renderBand(overrides: Partial<DoctorProfileView> = {}) {
  return render(
    <ProfileIdentityBand
      profile={profile(overrides)}
      photoUrl={null}
      mediaAbsent={false}
      busy={false}
      failure={null}
      onPick={noop}
      onRemove={noop}
      onDismissFailure={noop}
    />,
  );
}

afterEach(cleanup);

describe("ProfileIdentityBand", () => {
  it("makes the doctor's name the page's only h1 and the clinic the line beneath", () => {
    renderBand();

    const heading = screen.getByRole("heading", { level: 1 });
    expect(heading).toHaveTextContent("Asha Rao");
    expect(screen.getByTestId("profile-clinic")).toHaveTextContent(
      "Asha Clinic",
    );
  });

  it("renders one chip per declared specialty", () => {
    renderBand();

    const chips = screen.getAllByTestId("profile-specialty");
    expect(chips.map((chip) => chip.textContent)).toEqual([
      "General Physician",
      "Paediatrics",
    ]);
    expect(screen.queryByTestId("profile-specialties-empty")).toBeNull();
  });

  it("names an empty selection instead of rendering a bare chip row", () => {
    renderBand({ specialties: [] });

    expect(screen.getByTestId("profile-specialties-empty")).toHaveTextContent(
      t.noSpecialtiesYet,
    );
  });

  it("ticks from the projection's own flag and nothing else", () => {
    // The tick is not derived here. A client that recomputed credential validity
    // to decide what to tick would be a second derivation site, and the two would
    // eventually disagree - which is the failure "tick gone = card gone" rules out.
    renderBand({ verified: true });
    expect(screen.getByTestId("profile-verified")).toHaveTextContent(
      t.verified,
    );

    cleanup();

    renderBand({ verified: false });
    expect(screen.getByTestId("profile-verified")).toHaveTextContent(
      t.notVerified,
    );
  });

  it("keeps the picker's camera control inside the band", () => {
    const onPick = vi.fn();
    const band = render(
      <ProfileIdentityBand
        profile={profile()}
        photoUrl={null}
        mediaAbsent={false}
        busy={false}
        failure={null}
        onPick={onPick}
        onRemove={noop}
        onDismissFailure={noop}
      />,
    );

    const upload = band.baseElement.querySelector(
      '[data-testid="profile-photo-upload"]',
    );
    // A control across the page from the face it replaces is the problem this
    // band exists to remove, so the button is inside the band by construction.
    expect(band.container.contains(upload)).toBe(true);
    // No photo yet, so it offers Upload and no Remove that cannot succeed.
    expect(upload).toHaveTextContent(t.photoUpload);
    expect(screen.queryByTestId("profile-photo-remove")).toBeNull();
  });

  it("offers Remove instead of a second Upload once a photo is stored", () => {
    renderBand({ photo_ref: "doctor/7/photo-1.enc" });

    expect(screen.getByTestId("profile-photo-upload")).toHaveTextContent(
      t.photoReplace,
    );
    expect(screen.getByTestId("profile-photo-remove")).toBeInTheDocument();
  });

  it("treats a ref the backend says has no bytes behind it as no photo", () => {
    // A set ref with nothing behind it offers Upload rather than a Remove that
    // cannot succeed - the "claim versus fact" rule the shared hook encodes.
    render(
      <ProfileIdentityBand
        profile={profile({ photo_ref: "doctor/7/photo-1.enc" })}
        photoUrl={null}
        mediaAbsent={true}
        busy={false}
        failure={null}
        onPick={noop}
        onRemove={noop}
        onDismissFailure={noop}
      />,
    );

    expect(screen.getByTestId("profile-photo-upload")).toHaveTextContent(
      t.photoUpload,
    );
    expect(screen.queryByTestId("profile-photo-remove")).toBeNull();
  });

  it("surfaces an upload failure with its trace id and no retry action", () => {
    render(
      <ProfileIdentityBand
        profile={profile()}
        photoUrl={null}
        mediaAbsent={false}
        busy={false}
        failure={{ traceId: "trace-9" }}
        onPick={noop}
        onRemove={noop}
        onDismissFailure={noop}
      />,
    );

    expect(screen.getByTestId("error-banner")).toHaveTextContent(t.photoFailed);
    expect(screen.getByTestId("error-banner-trace-id")).toHaveTextContent(
      "trace-9",
    );
    // No retry: a failed upload has no stored file to re-send, so the doctor
    // picks again from the button rather than re-sending nothing.
    expect(screen.queryByTestId("error-banner-retry")).toBeNull();
  });

  it("falls back through the name to the clinic to the page's own title", () => {
    // The h1 is the one element whose absence would leave a screen with no title
    // at all, so every one of these has to render something.
    renderBand({ practice_name: null });
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      "Asha Clinic",
    );
    cleanup();

    renderBand({ practice_name: null, clinic_name: null });
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      t.title,
    );
  });
});

describe("ProfileSectionIndex", () => {
  const anchors = [
    { id: PROFILE_ANCHORS.verified, label: t.verifiedBandTitle },
    { id: PROFILE_ANCHORS.practice, label: t.practiceSectionTitle },
  ];

  it("renders plain in-page hash links and nothing that holds state", () => {
    render(<ProfileSectionIndex anchors={anchors} />);

    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(2);
    expect(links[0].getAttribute("href")).toBe(`#${PROFILE_ANCHORS.verified}`);
    // "Holds no state" read as a prohibition: no button to collapse a section, no
    // aria-pressed marking an "active" section a scroll-spy would have to track,
    // and no handler of any kind on the row.
    expect(screen.queryByRole("button")).toBeNull();
    expect(document.querySelector("[aria-pressed]")).toBeNull();
    expect(document.querySelector("[aria-current]")).toBeNull();
  });

  it("names the region it is, so it is not just a row of links to a screen reader", () => {
    render(<ProfileSectionIndex anchors={anchors} />);

    expect(
      screen.getByRole("navigation", { name: t.sectionIndexLabel }),
    ).toBeInTheDocument();
  });

  it("puts the focus ring and the touch target on the anchor", () => {
    render(<ProfileSectionIndex anchors={anchors} />);

    for (const link of screen.getAllByRole("link")) {
      // The ring has to be on the `<a>`: `Badge` renders a `<div>` and its
      // `focus-visible:` classes can never match, so a ring declared there is
      // inert - and an inert ring is exactly what this assertion exists to stop
      // passing for. Asserted on the focused element, not on a descendant.
      expect(link.className).toContain("focus-visible:ring-1");
      expect(link.className).toContain("focus-visible:outline-none");
      // The ring colour is a token, not a hex (§9.4 names accent.border).
      expect(link.className).toContain("ring-accent-border");
      // `min-h-11` is 44px, and it is on the link rather than the pill: a chip
      // the reader can see but cannot comfortably tap fails the same floor a
      // missing ring does.
      expect(link.className).toContain("min-h-11");
    }
    expect(screen.getByRole("navigation").className).toContain("sticky");
  });
});
