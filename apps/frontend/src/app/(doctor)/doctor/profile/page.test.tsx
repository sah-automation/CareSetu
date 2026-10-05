// PRD trace: FEAT-005 (Provider Profiles and Credential Display).
// PHASE-8.1 (#543): doctor console Profile page suite. Renders the private
// profile projection from #542 (photo preview, practice details, experience,
// languages, about, availability, credential/verified status, notification
// toggles), runs the consultation-fee editor through the unchanged PATCH fee path
// it inherited from the landing, drives photo upload/remove over the
// profile-media-backed endpoints, shows the read-only public-directory preview
// link, and covers load failure with retry plus bilingual EN/HI parity (REQ-006).
//
// #617 retired the transitional whole-form PUT and its page-level save. The four
// declared sections now save through four section writers - practice, address,
// about, notifications - so every editable case below names the writer it expects
// and asserts the other three stayed untouched, and the declared band is asserted
// as a plain section grouping the four cards rather than a card holding one save.

import {
  cleanup,
  fireEvent,
  render,
  renderHook,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import * as axe from "axe-core";
import {
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";
import type { ReactNode } from "react";

import DoctorProfilePage from "./page";
import { ApiError } from "@/lib/api-errors";
import { ABOUT_LIMITS } from "@/components/doctor/profile/aboutCardFields";
import { PRACTICE_LIMITS } from "@/components/doctor/profile/practiceCardFields";
import { DoctorProfileProvider } from "@/lib/doctor/DoctorProfileContext";
import {
  deleteDoctorProfilePhoto,
  fetchDoctorProfile,
  fetchDoctorProfilePhoto,
  updateDoctorProfileAbout,
  updateDoctorProfileAddress,
  updateDoctorProfileNotifications,
  updateDoctorProfilePractice,
  uploadDoctorProfilePhoto,
  type DoctorProfileAddressView,
  type DoctorProfileView,
} from "@/lib/doctor/api";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { __resetLangForTests, useLang } from "@/lib/i18n/LangContext";
import { updateConsultationFee } from "@/lib/partner/api";
import { useProfilePhotoSource } from "@/lib/profile/useProfilePhotoSource";

vi.mock("next/link", () => {
  return {
    default: ({
      href,
      children,
      ...rest
    }: {
      href: string;
      children: ReactNode;
    }) => (
      <a href={href} {...rest}>
        {children}
      </a>
    ),
  };
});

vi.mock("@/lib/doctor/api", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/doctor/api")>();
  return {
    ...mod,
    fetchDoctorProfile: vi.fn(),
    updateDoctorProfileAddress: vi.fn(),
    updateDoctorProfilePractice: vi.fn(),
    updateDoctorProfileAbout: vi.fn(),
    updateDoctorProfileNotifications: vi.fn(),
    uploadDoctorProfilePhoto: vi.fn(),
    fetchDoctorProfilePhoto: vi.fn(),
    deleteDoctorProfilePhoto: vi.fn(),
  };
});

vi.mock("@/lib/partner/api", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/partner/api")>();
  return { ...mod, updateConsultationFee: vi.fn() };
});

// #583: the page no longer reads the projection for itself - the shared doctor
// profile source does, once, and the page renders whatever that source holds.
// The source keys its state on the doctor's identity, so this suite supplies one
// directly: standing up the real AuthProvider would put an async /me between the
// mount and the identity, and with it a remount and a second byte read, neither
// of which belongs to what this suite is about.
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
const hiT = STRINGS.hi.doctorProfile;
const getProfile = vi.mocked(fetchDoctorProfile);
// #617: the transitional whole-form write is gone from the page, and #623 took
// its client export with it, so there is no longer a function here to stub. A card
// reaching for the retired route fails at the type level and at runtime on an
// unmocked network call rather than quietly succeeding against a fake. The cases
// below assert the four SECTION writers, and the "no single save" assertion in
// the shell suite is what keeps it that way.
const savePractice = vi.mocked(updateDoctorProfilePractice);
const saveAbout = vi.mocked(updateDoctorProfileAbout);
const saveNotifications = vi.mocked(updateDoctorProfileNotifications);
const saveAddress = vi.mocked(updateDoctorProfileAddress);
const uploadPhoto = vi.mocked(uploadDoctorProfilePhoto);
const getPhoto = vi.mocked(fetchDoctorProfilePhoto);
const deletePhoto = vi.mocked(deleteDoctorProfilePhoto);
const setFee = vi.mocked(updateConsultationFee);

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
    landmark: null,
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
    // #617: vocabulary MEMBERS, not the wire slugs this fixture carried before the
    // vocabularies existed. A stored value outside the closed list has no label, so
    // the cards would render nothing for it and the fixture would be quietly
    // describing an empty selection while claiming a two-day one.
    consulting_days: ["Monday", "Tuesday"],
    consulting_hours: "Mon-Sat, 9am-1pm",
    credentials: [
      {
        credential_type: "medical_registration",
        status: "verified",
        expires_at: "2027-04-01T00:00:00Z",
      },
    ],
    notification_preferences: { new_consultations: true },
    ...overrides,
  };
}

// #616: what the address write answers with - the projection as the backend
// reassembles it from the structured parts, plus the outside-the-belt warning
// only this write evaluates. `practice_address` is the server's own assembled
// display string, so the fixture rebuilds it the same way rather than echoing the
// doctor's input back.
function addressAnswer(
  overrides: Partial<DoctorProfileAddressView> = {},
): DoctorProfileAddressView {
  const parts = [
    overrides.address_line,
    overrides.landmark,
    overrides.locality,
    overrides.city,
    overrides.pin_code,
  ].filter((part): part is string => part != null && part !== "");
  // The belt defaults come BEFORE `overrides`, so a case that reports an
  // outside-the-belt position is not silently overwritten by them.
  return {
    ...profile(),
    outside_peri_urban_belt: false,
    distance_from_belt_centre_km: 0,
    ...overrides,
    practice_address: parts.join(", "),
  };
}

// #583: the page is rendered inside the shared doctor profile source, as the
// (doctor) route-group layout does in production. The source owns the read, so
// the only thing the page's own render needs seeded is what the source answers.
async function renderReady(view: DoctorProfileView = profile()) {
  getProfile.mockResolvedValue(view);
  const { container } = render(
    <DoctorProfileProvider>
      <DoctorProfilePage />
    </DoctorProfileProvider>,
  );
  await waitFor(() => screen.getByTestId("profile-declared-band"));
  // The address card seeds its edit buffer from the shared answer in an effect, so
  // it has nothing to render for one commit after the page itself is ready. Waiting
  // for it here keeps every test on a page that is ready in the same sense: no chip
  // pointing at an anchor that has not landed yet.
  await waitFor(() => screen.getByTestId("profile-address-card"));
  // The other three seed from the same shared answer in their own effects, so they
  // land one commit later than the address card did. Waiting for the last of the
  // four means the returned container is a page with all four cards present - which
  // is what an axe scan needs, and what a save assertion needs so that the click it
  // makes lands on a rendered button rather than on nothing.
  await waitFor(() => screen.getByTestId("profile-notification-card"));
  await waitFor(() => screen.getByTestId("profile-about-card"));
  await waitFor(() => screen.getByTestId("profile-practice-card"));
  return { container };
}

// ---------------------------------------------------------------------------
// jsdom plumbing
// ---------------------------------------------------------------------------

// Radix's `Switch` sizes its thumb through `@radix-ui/react-use-size`, which is
// the one adopted primitive on this page that observes an element. jsdom has no
// `ResizeObserver` and no layout, so the observer's first callback would throw out
// of a layout effect - surfacing as an unhandled exception that fails all 47 cases
// here without any of them saying why. The stub reports nothing and never fires
// again, which is the honest answer for a layout that does not exist; nothing in
// this page resizes itself from the observed size.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}

beforeAll(() => {
  window.ResizeObserver =
    window.ResizeObserver ??
    (ResizeObserverStub as unknown as typeof ResizeObserver);
});

let originalCreate: typeof URL.createObjectURL;
let originalRevoke: typeof URL.revokeObjectURL;

// The defaults every test starts from are installed in `beforeEach`, not
// `afterEach`: a save now hands its reply to the shared source, so a test that
// saves has to be holding a real projection to hand over, and a default left to
// the previous test's teardown is one `clearAllMocks` away from being nothing at
// all. Installed here, every test starts from the same known answers.
beforeEach(() => {
  originalCreate = URL.createObjectURL;
  originalRevoke = URL.revokeObjectURL;
  URL.createObjectURL = vi.fn(
    () => "blob:http://localhost/doctor-photo",
  ) as typeof URL.createObjectURL;
  URL.revokeObjectURL = vi.fn() as unknown as typeof URL.revokeObjectURL;
  getProfile.mockResolvedValue(profile());
  // #623: the whole-form `saveProfile` mock is gone with the export it stubbed.
  // #611 removed `PUT /v1/doctor/profile` and every section writes its own route,
  // so this mock was never called and never asserted against - it only made the
  // suite look like it covered the retired write. If a test wanted the old
  // behaviour back it would have to name the four section mocks below instead.
  // #617: each section write is answered with the projection carrying that section's
  // own change, and nothing else. A mock that echoed the whole stored view would
  // hide a card that re-seeded itself from a sibling's field.
  savePractice.mockImplementation(async (update) => profile({ ...update }));
  saveAbout.mockImplementation(async (update) => profile({ ...update }));
  saveNotifications.mockImplementation(async (update) =>
    profile({
      notification_preferences: update.notification_preferences,
    }),
  );
  // #616: the address card's own write, answered with the projection plus the two
  // fields only that write produces. A default that reported an outside-the-belt
  // position would put a notice on the page in tests that are about something else.
  saveAddress.mockImplementation(async (update) =>
    addressAnswer({
      ...update,
      outside_peri_urban_belt: false,
      distance_from_belt_centre_km: 0,
    }),
  );
  uploadPhoto.mockResolvedValue({ photo_ref: "doctor/7/photo-1.enc" });
  getPhoto.mockResolvedValue(new Blob(["photo"], { type: "image/jpeg" }));
  deletePhoto.mockResolvedValue(undefined);
  setFee.mockResolvedValue({ partner_id: 7, status: "Active", round: 0 });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  __resetLangForTests();
  URL.createObjectURL = originalCreate;
  URL.revokeObjectURL = originalRevoke;
});

// #615: the rebuilt shell's own four acceptance criteria, each stated as the
// smallest observable claim it makes. The one inside a band is asserted through
// the band's own testid rather than by text, because the same copy also appears
// in the anchor chip that jumps to it.
describe("DoctorProfilePage shell (#615)", () => {
  it("heads the page with an identity band: the name, the clinic, the tick and the specialties", async () => {
    await renderReady();

    const band = screen.getByTestId("profile-identity");
    // The doctor's name is the page's heading, not a label above a form.
    expect(within(band).getByRole("heading", { level: 1 })).toHaveTextContent(
      "Sunrise Clinic",
    );
    expect(screen.getByTestId("profile-clinic")).toHaveTextContent(
      "Sunrise Clinic",
    );
    // Both trust cues come from the one flag, so the chip row and the verified
    // band below cannot end up telling two different stories.
    expect(screen.getByTestId("profile-identity-verified")).toHaveTextContent(
      t.verified,
    );
    expect(
      within(screen.getByTestId("profile-verified-band")).getByText(
        t.verifiedBandTitle,
      ),
    ).toBeInTheDocument();
    // The picker sits in the band, not across the page from the face it replaces.
    expect(
      within(band).getByTestId("profile-photo-upload"),
    ).toBeInTheDocument();

    // The identity band is not the only h1 on the page: the section headings
    // below it stay h2s, which is the outline the whole split rests on.
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
  });

  it("names an empty specialty selection instead of rendering no chip at all", async () => {
    await renderReady(profile({ specialties: [] }));

    expect(screen.getByTestId("profile-specialties-empty")).toHaveTextContent(
      t.noSpecialtiesYet,
    );
    expect(screen.queryByTestId("profile-specialty")).toBeNull();
  });

  it("shows the credentials in the verified band and the typed details in the declared one", async () => {
    await renderReady();

    // What the platform derived and checked sits in the verified band...
    const verified = screen.getByTestId("profile-verified-band");
    expect(
      within(verified).getByTestId("profile-credential"),
    ).toBeInTheDocument();
    expect(
      within(verified).getByTestId("profile-public-preview"),
    ).toBeInTheDocument();

    // ...and what the doctor declared sits in the declared band, which says so in
    // words rather than leaving the distinction to colour alone (§1.6, §9.4).
    const declared = screen.getByTestId("profile-declared-band");
    expect(within(declared).getByText(t.declaredBandHelp)).toBeInTheDocument();
    expect(
      within(declared).getByTestId("profile-practice-name"),
    ).toBeInTheDocument();
    expect(
      within(declared).getByTestId("profile-notification-case_updates"),
    ).toBeInTheDocument();
    // #617: FOUR saving cards inside the band and no band-level save. The band
    // groups them; it does not write them. A single save here would be one button
    // writing four different bodies, which is the failure AC 2 names.
    for (const testId of [
      "profile-practice-save",
      "profile-address-save",
      "profile-about-save",
      "profile-notifications-save",
    ]) {
      expect(within(declared).getByTestId(testId)).toBeInTheDocument();
    }
    expect(within(declared).queryByTestId("profile-save")).toBeNull();
    // Nothing the doctor declared leaked into the verified band.
    expect(within(verified).queryByTestId("profile-practice-name")).toBeNull();
  });

  // #617: the band is a plain section grouping four cards, not a fifth card. A
  // card inside a card is two nested surfaces reading as one, and the assertion
  // that catches it is the DOM shape rather than the styling class.
  it("groups the four declared cards without nesting a card inside one", async () => {
    await renderReady();

    const band = screen.getByTestId("profile-declared-band");
    expect(band.tagName).toBe("SECTION");
    // The band's own heading and its sentence, which is what makes it a band.
    expect(
      within(band).getByRole("heading", { name: t.declaredBandTitle }),
    ).toBeInTheDocument();
    for (const testId of [
      "profile-practice-card",
      "profile-address-card",
      "profile-about-card",
      "profile-notification-card",
    ]) {
      const card = within(band).getByTestId(testId);
      expect(card.tagName).toBe("FORM");
      // Not nested: a card's ancestor chain back to the band holds no other card.
      let node = card.parentElement;
      let nested = false;
      while (node != null && node !== band) {
        if (node.getAttribute("data-testid")?.startsWith("profile-") === true) {
          nested = true;
        }
        node = node.parentElement;
      }
      expect(nested, `${testId} sits inside another card`).toBe(false);
    }
  });

  it("drops the tick and still shows the credentials when the flag is false", async () => {
    // A doctor whose credentials are pending or expired is not verified, and a
    // band that kept a tick beside that list would be claiming a check that did
    // not happen - the exact failure "tick gone = card gone" rules out.
    await renderReady(profile({ verified: false }));

    expect(screen.getByTestId("profile-identity-verified")).toHaveTextContent(
      t.notVerified,
    );
    const verified = screen.getByTestId("profile-verified-band");
    expect(
      within(verified).getByTestId("profile-credential-status"),
    ).toHaveTextContent(t.credentialStatus.verified);
  });

  it("states the verification status in words, off the one flag, when true", async () => {
    // AC 3: "the credentials AND activation state render in the verified band
    // carrying the tick". The verdict is a stated value, not just a tick's
    // presence - a tick a screen reader never announces tells a blind doctor
    // nothing about what CareSetu actually decided.
    //
    // #623: the row reads `t.verificationStateLabel`, not an activation label.
    // It renders the composite `verified` flag, so naming it "activation state"
    // told an Active doctor with one lapsed credential that their activation was
    // not verified, which is false.
    await renderReady(profile({ verified: true }));

    const state = within(
      screen.getByTestId("profile-verified-band"),
    ).getByTestId("profile-verification-state");
    expect(state).toHaveTextContent(t.verificationStateLabel);
    expect(state).toHaveTextContent(t.verified);
    expect(within(state).getByText(t.verifiedTickLabel)).toBeInTheDocument();
  });

  it("says the verification status is not verified, with no tick beside it", async () => {
    await renderReady(profile({ verified: false }));

    // The value and the symbol are the same claim, so neither can be present
    // alone: a false flag gets the words and loses the tick.
    const state = within(
      screen.getByTestId("profile-verified-band"),
    ).getByTestId("profile-verification-state");
    expect(state).toHaveTextContent(t.notVerified);
    expect(within(state).queryByText(t.verifiedTickLabel)).toBeNull();
    expect(state.querySelector("svg")).toBeNull();
  });

  // #623: the flag is a composite, so the label must not name one of its two
  // inputs. A row titled "Activation state" reading "Not verified" is a false
  // claim about an Active doctor's activation, and this pins the word that makes
  // the row describe what is rendered instead.
  it("never labels the composite flag as an activation state", async () => {
    await renderReady(profile({ verified: false }));

    const state = within(
      screen.getByTestId("profile-verified-band"),
    ).getByTestId("profile-verification-state");
    expect(state.textContent).not.toMatch(/activation/i);
  });

  it("never claims the outcome in the verified band's own heading", async () => {
    // The band's title says what KIND of thing it is, not the verdict. Were it
    // "Verified by CareSetu", a doctor whose flag is false would read a claim
    // the backend is not making - overclaiming is the §1.6 failure.
    await renderReady(profile({ verified: false }));

    const band = screen.getByTestId("profile-verified-band");
    expect(within(band).getByText(t.verifiedBandTitle)).toBeInTheDocument();
    expect(band.textContent).not.toContain("Verified by CareSetu");
  });

  it("offers a sticky anchor chip per section, each pointing at an id the page renders", async () => {
    await renderReady();

    const index = screen.getByTestId("profile-section-index");
    // The chips' labels are the sections' own headings, read from the dictionary.
    const labels = [
      t.verifiedBandTitle,
      t.declaredBandTitle,
      t.practiceSectionTitle,
      t.addressSectionTitle,
      t.aboutSectionTitle,
      t.notificationsHeading,
      t.feeHeading,
    ];
    for (const label of labels) {
      expect(within(index).getAllByText(label).length).toBeGreaterThan(0);
    }

    // Every chip resolves to an element that is actually in the document: a chip
    // pointing at an id nothing renders is a dead control, not a jump.
    const hrefs = within(index)
      .getAllByRole("link")
      .map((link) => link.getAttribute("href") ?? "");
    expect(hrefs.length).toBe(labels.length);
    for (const href of hrefs) {
      expect(href.startsWith("#")).toBe(true);
      const target = document.querySelector(href);
      expect(target).not.toBeNull();
    }

    // The two bands, the fee card and the four declared cards all carry a heading
    // at their anchor. #617 gave the last three their own headings: what used to be
    // a field group inside the band is a card that is individually linked, so a
    // heading has to be what the chip names.
    const withHeading = [
      "verified",
      "declared",
      "practice",
      "address",
      "about",
      "notifications",
      "fee",
    ];
    for (const key of withHeading) {
      const target = document.querySelector(`#profile-section-${key}`);
      expect(
        target?.querySelector("h2") ??
          target?.parentElement?.querySelector("h2"),
      ).not.toBeNull();
    }

    // "Holds no state" read as a prohibition: no scroll-spy, no observer, no
    // scroll listener, nothing that hides a section body, and every save button
    // still beside its own fields rather than collected at the top.
    expect(within(index).queryByRole("button")).toBeNull();
    expect(within(index).getAllByRole("link")).toHaveLength(labels.length);
  });

  it("never renders the service-area vocabulary name to the doctor", async () => {
    // The fixture carries an `area` that is deliberately not a substring of
    // anything else on the page, so "this value is absent from the document"
    // cannot pass by coincidence - and a unique value keeps the assertion about
    // the AREA field rather than about a locality string the address also
    // happens to contain. The area is a platform seed; the neighbourhood a
    // practice sits in is `locality`, which is a different field under a
    // different name.
    const area = "Zzz-platform-seed-area";
    await renderReady(profile({ area }));

    // Still absent from the WHOLE page, live preview included: the preview maps
    // the declared locality onto the public projection's `area`, so a regression
    // that reached for the platform seed would show this string.
    expect(screen.queryByText(area)).toBeNull();

    // #618 changed where the WORD lives, not what it may label. The doctor's own
    // copy still never names a service area - but the live preview does, because
    // the public profile labels the declared locality "Service area" and the whole
    // point of the preview is that it says what the patient surface says. So the
    // word's absence is asserted over the doctor's own copy, with the preview
    // excluded rather than the assertion weakened.
    const clone = document.body.cloneNode(true) as HTMLElement;
    for (const node of clone.querySelectorAll(
      '[data-testid="profile-live-preview"]',
    )) {
      node.remove();
    }
    expect(clone.textContent).not.toMatch(/area/i);

    // And inside the preview it is the locality on the patient surface's own
    // label - never the platform seed beside it. #619 moved that label from the
    // solid-edged summary into the declared band, and this is the assertion for
    // it: the patient surface says "Locality" now, so a preview still saying
    // "Service area" would be showing the doctor a page we do not ship.
    const preview = screen.getByTestId("profile-live-preview");
    expect(preview).not.toHaveTextContent("Service area");
    expect(
      within(preview).getByTestId("profile-declared-address-locality"),
    ).toHaveTextContent("Daltonganj");
  });
});

describe("DoctorProfilePage projection", () => {
  it("renders the private projection and the read-only public preview link", async () => {
    await renderReady();

    // #615: the identity band carries the page's own h1 (the doctor's name), so
    // the ready state has no separate `PageHeader` title to find.
    expect(
      screen.getByRole("heading", { level: 1, name: "Sunrise Clinic" }),
    ).toBeInTheDocument();
    expect(screen.getByTestId("profile-practice-name")).toHaveValue(
      "Sunrise Clinic",
    );
    expect(screen.getByTestId("profile-specialty")).toHaveTextContent(
      "General Physician",
    );
    expect(screen.getByTestId("profile-identity-verified")).toHaveTextContent(
      t.verified,
    );
    // #616: the address renders from the projection's STRUCTURED parts now, in its
    // own card, rather than as the declared band's free-text blob. Same stored
    // address, one editor, and the parts the backend assembles the display string
    // from are the ones the doctor can correct.
    expect(screen.getByTestId("profile-address-line")).toHaveValue("Main Road");
    expect(screen.getByTestId("profile-address-locality")).toHaveValue(
      "Daltonganj",
    );
    expect(screen.getByTestId("profile-address-pin")).toHaveValue("822001");
    expect(screen.queryByTestId("profile-address")).toBeNull();
    expect(screen.getByTestId("profile-experience")).toHaveValue(12);
    // #617: the languages are CHOSEN from the closed list now, not typed into a box
    // the page parsed by commas. So the projection's two stored members have to be
    // two pressed chips, and the free-text editor this used to be is gone.
    expect(screen.getByTestId("profile-about-languages-hindi")).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(
      screen.getByTestId("profile-about-languages-english"),
    ).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByTestId("profile-languages")).toBeNull();
    // The same holds for the day chips the free-text field replaced.
    expect(screen.getByTestId("profile-about-days-monday")).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByTestId("profile-about-days-tuesday")).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByTestId("profile-about-days-wednesday")).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    // Hours stayed prose: "Mon-Sat, 9am-1pm" is a sentence a doctor wrote, not a
    // value any closed list could have named, so it survives in a textarea as typed.
    expect(screen.getByTestId("profile-consulting-hours")).toHaveValue(
      "Mon-Sat, 9am-1pm",
    );
    expect(screen.getByTestId("profile-about")).toHaveValue(
      "Twelve years of primary care.",
    );
    expect(
      screen.getByTestId("profile-notification-new_consultations"),
    ).toBeChecked();
    expect(
      screen.getByTestId("profile-notification-case_updates"),
    ).not.toBeChecked();
    expect(screen.getByTestId("profile-credential-status")).toHaveTextContent(
      t.credentialStatus.verified,
    );

    // The public directory entry is a read-only preview, never an editor here.
    const preview = screen.getByTestId("profile-public-preview");
    expect(preview).toHaveAttribute("href", "/providers/7");
    expect(preview).toHaveTextContent(t.publicPreviewAction);
  });

  it("shows the credential status vocabulary per credential", async () => {
    await renderReady(
      profile({
        credentials: [
          {
            credential_type: "medical_registration",
            status: "expired",
            expires_at: null,
          },
          {
            credential_type: "qualification_certificate",
            status: "reverification_failed",
            expires_at: null,
          },
        ],
      }),
    );

    const statuses = screen.getAllByTestId("profile-credential-status");
    expect(statuses).toHaveLength(2);
    expect(statuses[0]).toHaveTextContent(t.credentialStatus.expired);
    expect(statuses[1]).toHaveTextContent(
      t.credentialStatus.reverification_failed,
    );
    expect(screen.queryByTestId("profile-credential-expiry")).toBeNull();
  });

  it("labels the credential kinds instead of showing the raw API literal", async () => {
    await renderReady(
      profile({
        credentials: [
          {
            credential_type: "medical_registration",
            status: "verified",
            expires_at: null,
          },
          {
            // An unexpected literal still renders, rather than going blank.
            credential_type: "pharmacist_registration",
            status: "verified",
            expires_at: null,
          },
        ],
      }),
    );

    const rows = screen.getAllByTestId("profile-credential");
    expect(rows[0]).toHaveTextContent(t.credentialType.medical_registration);
    expect(rows[1]).toHaveTextContent("pharmacist_registration");
  });

  it("surfaces the retryable error state when the profile read fails", async () => {
    getProfile.mockRejectedValue(
      new ApiError({
        code: "INTERNAL_ERROR",
        message: "boom",
        trace_id: "trace-p9001",
        details: {},
      }),
    );
    render(
      <DoctorProfileProvider>
        <DoctorProfilePage />
      </DoctorProfileProvider>,
    );

    await waitFor(() => screen.getByTestId("error-banner"));
    expect(screen.getByText(t.loadFailed)).toBeInTheDocument();

    getProfile.mockResolvedValue(profile());
    fireEvent.click(screen.getByTestId("error-banner-retry"));
    await waitFor(() => screen.getByTestId("profile-declared-band"));
    expect(getProfile).toHaveBeenCalledTimes(2);
  });
});

// #617: the four declared sections save through four section writers, each
// carrying only its own columns. Every case here states which writer was called
// AND that the other three were not - a page that quietly reached the
// transitional whole-form PUT would satisfy a body assertion on its own, and this
// is the assertion that says it did not.
describe("DoctorProfilePage editable fields (#617)", () => {
  // §9.5 says validate on blur AND on submit. The submit half is covered by the
  // refusal cases below; these three cover the blur half, which is the half that is
  // easy to leave out and the half a doctor meets first.
  describe("validation on blur", () => {
    it("says a field is wrong when it loses focus, without a save", async () => {
      await renderReady();

      // The seeded value is usable, so nothing is wrong until the doctor breaks it.
      expect(
        screen.queryByTestId("profile-practice-name-error"),
      ).not.toBeInTheDocument();

      fireEvent.change(screen.getByTestId("profile-practice-name"), {
        target: { value: "   " },
      });
      // Mid-edit: still silent. Announcing a field wrong while it is being typed
      // is how a message gets ignored.
      expect(
        screen.queryByTestId("profile-practice-name-error"),
      ).not.toBeInTheDocument();

      fireEvent.blur(screen.getByTestId("profile-practice-name"));

      expect(
        screen.getByTestId("profile-practice-name-error"),
      ).toHaveTextContent(t.practiceNameRequired);
      expect(screen.getByTestId("profile-practice-name")).toHaveAttribute(
        "aria-invalid",
        "true",
      );
      // A blur is not a submit, so no write and no count-and-focus summary.
      expect(savePractice).not.toHaveBeenCalled();
      expect(
        screen.queryByTestId("profile-practice-summary"),
      ).not.toBeInTheDocument();
    });

    it("clears the message as soon as the value becomes usable again", async () => {
      await renderReady();

      fireEvent.change(screen.getByTestId("profile-practice-name"), {
        target: { value: "   " },
      });
      fireEvent.blur(screen.getByTestId("profile-practice-name"));
      expect(
        screen.getByTestId("profile-practice-name-error"),
      ).toBeInTheDocument();

      fireEvent.change(screen.getByTestId("profile-practice-name"), {
        target: { value: "Sunrise Clinic 9" },
      });

      // Still blurred, so still checked - and now the pass has nothing to say, so
      // the message goes rather than lingering until the next blur.
      expect(
        screen.queryByTestId("profile-practice-name-error"),
      ).not.toBeInTheDocument();
      expect(screen.getByTestId("profile-practice-name")).toHaveAttribute(
        "aria-invalid",
        "false",
      );
    });

    it("does not drag focus back to the field being left", async () => {
      await renderReady();

      fireEvent.change(screen.getByTestId("profile-practice-name"), {
        target: { value: "   " },
      });
      const name = screen.getByTestId("profile-practice-name");
      name.focus();
      fireEvent.blur(name);
      const clinic = screen.getByTestId("profile-practice-clinic");
      clinic.focus();

      // The focus walk is gated on a submit. Ungated, a blur-time check would pull
      // focus straight back to the field the doctor just left, which is the exact
      // opposite of what blur validation is for.
      expect(document.activeElement).toBe(clinic);
    });

    it("catches the About card's own bounds on blur, through the same hook", async () => {
      await renderReady();

      fireEvent.change(screen.getByTestId("profile-about"), {
        target: { value: "x".repeat(ABOUT_LIMITS.about + 1) },
      });
      fireEvent.blur(screen.getByTestId("profile-about"));

      expect(screen.getByTestId("profile-about-error")).toHaveTextContent(
        t.aboutTooLong,
      );
    });
  });

  it("saves the practice card's own columns and nothing from its siblings", async () => {
    await renderReady();

    fireEvent.change(screen.getByTestId("profile-practice-name"), {
      target: { value: "Sunrise Clinic 2" },
    });
    fireEvent.change(screen.getByTestId("profile-experience"), {
      target: { value: "13" },
    });
    // A specialty is a CHOICE now, so it is toggled rather than typed. The stored
    // selection already holds "General Physician"; adding a second member is what
    // a doctor's actual edit looks like.
    fireEvent.click(screen.getByTestId("profile-practice-specialties-dentist"));
    fireEvent.click(screen.getByTestId("profile-practice-save"));

    await waitFor(() =>
      expect(screen.getByTestId("profile-practice-saved")).toHaveTextContent(
        t.practiceSaved,
      ),
    );

    expect(savePractice).toHaveBeenCalledWith(
      {
        // `full_name`, not `practice_name`: the section write names the column it
        // owns, and the projection's display string is assembled from it elsewhere.
        full_name: "Sunrise Clinic 2",
        clinic_name: "Sunrise Clinic",
        specialties: ["General Physician", "Dentist"],
        experience_years: 13,
      },
      expect.any(String),
    );
    // The other three sections were not dragged along, and no about text,
    // notification flag or address part was in that body.
    expect(saveAbout).not.toHaveBeenCalled();
    expect(saveNotifications).not.toHaveBeenCalled();
    expect(saveAddress).not.toHaveBeenCalled();
    const body = savePractice.mock.calls[0][0];
    expect(Object.keys(body).sort()).toEqual([
      "clinic_name",
      "experience_years",
      "full_name",
      "specialties",
    ]);
  });

  it("saves the about card's vocabulary selections, prose hours and text", async () => {
    await renderReady();

    // Two decisions at once, one per vocabulary: add a language, drop a day. The
    // stored selection is Hindi+English over Monday+Tuesday, so the clicks below
    // are one turn on and one turn off - a toggle group has to do both, and a
    // select-multiple could not express the second without clearing the first.
    fireEvent.click(screen.getByTestId("profile-about-languages-maithili"));
    fireEvent.click(screen.getByTestId("profile-about-days-tuesday"));
    fireEvent.change(screen.getByTestId("profile-consulting-hours"), {
      target: { value: "Mon-Sat, 9am-1pm, 5pm-8pm" },
    });
    fireEvent.change(screen.getByTestId("profile-about"), {
      target: { value: "Now also runs evening clinics." },
    });
    fireEvent.click(screen.getByTestId("profile-about-save"));

    await waitFor(() =>
      expect(screen.getByTestId("profile-about-saved")).toHaveTextContent(
        t.aboutSaved,
      ),
    );

    expect(saveAbout).toHaveBeenCalledWith(
      {
        about: "Now also runs evening clinics.",
        languages: ["Hindi", "English", "Maithili"],
        consulting_days: ["Monday"],
        // Prose, exactly as typed. Nothing parses it, nothing reformats it, and no
        // vocabulary owns it - which is why it is a textarea and not chips.
        consulting_hours: "Mon-Sat, 9am-1pm, 5pm-8pm",
      },
      expect.any(String),
    );
    expect(savePractice).not.toHaveBeenCalled();
    expect(saveNotifications).not.toHaveBeenCalled();
    expect(saveAddress).not.toHaveBeenCalled();
    // The selection is DECLARED, so what is stored comes back in the card's own
    // vocabulary order rather than in click order.
    expect(screen.getByTestId("profile-about-days-tuesday")).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    expect(screen.getByTestId("profile-about-days-monday")).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("sends the notification card exactly the five known keys", async () => {
    await renderReady();

    fireEvent.click(screen.getByTestId("profile-notification-case_updates"));
    fireEvent.click(screen.getByTestId("profile-notifications-save"));

    await waitFor(() =>
      expect(
        screen.getByTestId("profile-notifications-saved"),
      ).toHaveTextContent(t.notificationsSaved),
    );

    expect(saveNotifications).toHaveBeenCalledWith(
      {
        notification_preferences: {
          new_consultations: true,
          record_shared: false,
          pre_summary_ready: false,
          case_updates: true,
          credential_status: false,
        },
      },
      expect.any(String),
    );
    expect(savePractice).not.toHaveBeenCalled();
    expect(saveAbout).not.toHaveBeenCalled();
    expect(saveAddress).not.toHaveBeenCalled();
  });

  // #617: the five switches are a CLOSED set, and this is the case that says so
  // from the wire side. #602's `require_notification_preferences` refuses any key
  // outside the five, so a client that echoed a stored `sms_digest` back would 422
  // on every save. The preservation of that key is the backend's merge
  // (`merge_notification_preferences`), not this card's - so what the card must
  // NOT do is send it, and what it must DO is keep rendering the five it knows.
  it("never echoes a stored key outside the five back at the backend", async () => {
    await renderReady(
      profile({ notification_preferences: { sms_digest: true } }),
    );

    fireEvent.click(
      screen.getByTestId("profile-notification-new_consultations"),
    );
    fireEvent.click(screen.getByTestId("profile-notifications-save"));

    await waitFor(() => expect(saveNotifications).toHaveBeenCalledTimes(1));
    const sent = saveNotifications.mock.calls[0][0].notification_preferences;
    expect(Object.keys(sent).sort()).toEqual([
      "case_updates",
      "credential_status",
      "new_consultations",
      "pre_summary_ready",
      "record_shared",
    ]);
    expect(sent).not.toHaveProperty("sms_digest");
    // And the flip that drove the save is still on screen: the unknown key was
    // dropped at the seam, not by failing the save. A stored dict holding only
    // `sms_digest` seeds the five as false, so one click turns one on.
    expect(
      screen.getByTestId("profile-notification-new_consultations"),
    ).toBeChecked();
  });

  // #617: a stored value outside a vocabulary has no label, so the card cannot
  // render it. The declared outcome is that it is dropped from the selection - and
  // that the doctor then sees the selection they can actually see, rather than a
  // chip whose text is a raw wire string.
  it("narrows a stored value outside the vocabulary out of the shown selection", async () => {
    await renderReady(
      profile({
        specialties: ["General Physician", "Quantum Surgery"],
        languages: ["Hindi", "Klingon"],
      }),
    );

    // The known member is pressed, the unknown one is not offered at all, and the
    // card's own count reflects only what it can render.
    expect(
      await screen.findByTestId(
        "profile-practice-specialties-general-physician",
      ),
    ).toHaveAttribute("aria-pressed", "true");
    expect(
      screen.queryByTestId("profile-practice-specialties-quantum-surgery"),
    ).toBeNull();
    expect(screen.getByTestId("profile-about-languages-hindi")).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.queryByTestId("profile-about-languages-klingon")).toBeNull();

    // Saving declares the narrowed selection, and the server accepts it because
    // every value in it is a member.
    fireEvent.click(screen.getByTestId("profile-about-save"));
    await waitFor(() => expect(saveAbout).toHaveBeenCalledTimes(1));
    expect(saveAbout.mock.calls[0][0]).toMatchObject({
      languages: ["Hindi"],
    });
  });

  // #583, story 16: an answer that lands while the doctor is typing must not
  // throw the typing away. Object identity alone does not decide this - a save's
  // reply and an upload's ref are each a *new* projection, so both would reseed
  // the buffer and wipe whatever was typed since. Both writes are held open here
  // so the answer provably lands *after* the keystrokes; a write that resolved on
  // the spot would be adopted before the typing and prove nothing.
  it("keeps in-progress typing when a section save's own reply lands after it", async () => {
    await renderReady();
    let settle: (view: DoctorProfileView) => void = () => {};
    savePractice.mockImplementationOnce(
      () =>
        new Promise<DoctorProfileView>((resolve) => {
          settle = resolve;
        }),
    );

    fireEvent.click(screen.getByTestId("profile-practice-save"));
    await waitFor(() => expect(savePractice).toHaveBeenCalledTimes(1));
    fireEvent.change(screen.getByTestId("profile-practice-name"), {
      target: { value: "Sunrise Clinic, typing" },
    });

    // The write lands now, carrying the name as it was when it was clicked.
    settle(profile({ practice_name: "Sunrise Clinic" }));
    await waitFor(() =>
      expect(screen.getByTestId("profile-practice-saved")).toHaveTextContent(
        t.practiceSaved,
      ),
    );

    expect(screen.getByTestId("profile-practice-name")).toHaveValue(
      "Sunrise Clinic, typing",
    );
  });

  // #617: the same late-answer rule across cards. A save's reply adopts the WHOLE
  // projection onto the shared source, and every card re-seeds from that source in
  // an effect - so without the dirty-buffer guard one card's late reply would wipe
  // what the doctor is typing into a DIFFERENT card. The two cards here are held
  // open in opposite order, so the adoption lands while the other is mid-edit.
  it("keeps one card's late reply from wiping the typing in another", async () => {
    await renderReady();
    let settleAbout: (view: DoctorProfileView) => void = () => {};
    saveAbout.mockImplementationOnce(
      () =>
        new Promise<DoctorProfileView>((resolve) => {
          settleAbout = resolve;
        }),
    );

    fireEvent.click(screen.getByTestId("profile-about-save"));
    await waitFor(() => expect(saveAbout).toHaveBeenCalledTimes(1));

    // The doctor moves on and starts typing in the practice card.
    fireEvent.change(screen.getByTestId("profile-practice-name"), {
      target: { value: "Sunrise Clinic, typing" },
    });
    fireEvent.change(screen.getByTestId("profile-experience"), {
      target: { value: "14" },
    });

    // The about write lands, adopting a projection whose own about fields are the
    // ones from BEFORE the doctor opened this page.
    settleAbout(
      profile({
        about: "Stale about text",
        languages: ["Hindi"],
        consulting_days: ["Monday"],
        consulting_hours: "Stale hours",
      }),
    );
    await waitFor(() =>
      expect(screen.getByTestId("profile-about-saved")).toHaveTextContent(
        t.aboutSaved,
      ),
    );

    expect(screen.getByTestId("profile-practice-name")).toHaveValue(
      "Sunrise Clinic, typing",
    );
    expect(screen.getByTestId("profile-experience")).toHaveValue(14);
  });

  it("keeps in-progress typing when an upload's answer lands after it", async () => {
    await renderReady();
    fireEvent.change(screen.getByTestId("profile-about"), {
      target: { value: "Mid-sentence edit." },
    });
    let settle: (ref: { photo_ref: string }) => void = () => {};
    uploadPhoto.mockImplementationOnce(
      () =>
        new Promise<{ photo_ref: string }>((resolve) => {
          settle = resolve;
        }),
    );

    fireEvent.change(screen.getByTestId("profile-photo-input"), {
      target: {
        files: [new File(["photo"], "me.jpg", { type: "image/jpeg" })],
      },
    });
    await waitFor(() => expect(uploadPhoto).toHaveBeenCalled());
    settle({ photo_ref: "doctor/7/photo-2.enc" });

    // The photo answer reseeds nothing the doctor was writing. Waited on the
    // settled preview rather than the button, because the reseed lands in an
    // effect after the commit that hides the button.
    await waitFor(() =>
      expect(
        screen.getByTestId("profile-identity").querySelector("img"),
      ).not.toBeNull(),
    );
    expect(screen.getByTestId("profile-about")).toHaveValue(
      "Mid-sentence edit.",
    );
  });

  it("reuses one idempotency key across a retry of the same save", async () => {
    savePractice.mockRejectedValueOnce(
      new ApiError({
        code: "INTERNAL_ERROR",
        message: "boom",
        trace_id: "t",
        details: {},
      }),
    );
    await renderReady();

    fireEvent.click(screen.getByTestId("profile-practice-save"));
    await waitFor(() => expect(savePractice).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByTestId("error-banner-retry"));
    await waitFor(() => expect(savePractice).toHaveBeenCalledTimes(2));

    expect(savePractice.mock.calls[0][1]).toBe(savePractice.mock.calls[1][1]);
  });

  it("mints a new idempotency key once the card is edited", async () => {
    savePractice.mockRejectedValue(
      new ApiError({
        code: "INTERNAL_ERROR",
        message: "boom",
        trace_id: "t",
        details: {},
      }),
    );
    await renderReady();

    fireEvent.click(screen.getByTestId("profile-practice-save"));
    await waitFor(() => expect(savePractice).toHaveBeenCalledTimes(1));

    fireEvent.change(screen.getByTestId("profile-practice-name"), {
      target: { value: "Sunrise Clinic 3" },
    });
    fireEvent.click(screen.getByTestId("profile-practice-save"));
    await waitFor(() => expect(savePractice).toHaveBeenCalledTimes(2));

    expect(savePractice.mock.calls[0][1]).not.toBe(
      savePractice.mock.calls[1][1],
    );
  });

  // #616: the declared band's free-text address is gone, and #617 retired the
  // whole-form validator that used to guard it, so there is neither a field to blank
  // nor a rule that a blank field would have blocked. The address now has exactly one
  // editor - the card's own - whose validation its own suite asserts. What this
  // asserts is the absence, which is a stronger guarantee than a red textarea.
  it("offers no free-text address in the declared band any more", async () => {
    await renderReady();

    expect(screen.queryByTestId("profile-address")).toBeNull();
    expect(
      await screen.findByTestId("profile-address-card"),
    ).toBeInTheDocument();
    // And the anchor moved with it: one id, one element, so the Address chip's
    // target is the card rather than a coin toss between two elements.
    expect(document.querySelectorAll("#profile-section-address")).toHaveLength(
      1,
    );
  });

  // #615: the coordinates are server-written and derived from the declared PIN
  // code (#609), so there is nothing for the doctor to get wrong and nothing on
  // this page for them to fix. The two rules that used to sit beside this one -
  // a latitude inside its bound and a longitude inside its own - are the same
  // rule now: the page never asks.
  it("shows no coordinate input at all", async () => {
    await renderReady();

    expect(screen.queryByTestId("profile-latitude")).toBeNull();
    expect(screen.queryByTestId("profile-longitude")).toBeNull();
    // And the retired free-text availability blob's input is gone with it.
    expect(screen.queryByTestId("profile-availability")).toBeNull();
  });

  it("blocks an over-long free-text field before calling the API", async () => {
    await renderReady();

    fireEvent.change(screen.getByTestId("profile-about"), {
      target: { value: "x".repeat(5001) },
    });
    fireEvent.click(screen.getByTestId("profile-about-save"));

    // The card's own summary counts what it refused, and it is an `alert` so the
    // refusal is announced rather than only coloured.
    const summary = await screen.findByTestId("profile-about-summary");
    expect(summary).toHaveAttribute("role", "alert");
    expect(summary).toHaveTextContent(t.invalidSummary(1));
    expect(saveAbout).not.toHaveBeenCalled();
    expect(screen.getByTestId("profile-about")).toHaveAttribute(
      "aria-invalid",
      "true",
    );
    // The over-long field is the ONLY reason the save was refused: its sibling in
    // the same card is explicitly not invalid, and no other card's writer ran.
    expect(screen.getByTestId("profile-consulting-hours")).toHaveAttribute(
      "aria-invalid",
      "false",
    );
    expect(saveNotifications).not.toHaveBeenCalled();
    expect(savePractice).not.toHaveBeenCalled();
  });

  // #617: the language field is a closed pick-list now, so "too many languages"
  // and "a language that does not exist" are not reachable states - the one cap
  // that still exists is how many members the list itself offers. Asserting the
  // bound here rather than in the card suite keeps the page honest about the
  // thing it used to let a doctor type: a free-text list of unknown length.
  it("offers a closed language list rather than a free-text one", async () => {
    await renderReady();

    // No text input anywhere in the card, so there is nothing to type a value the
    // domain would refuse.
    expect(screen.queryByTestId("profile-languages")).toBeNull();
    // Every offered chip is a member, and the count matches the vocabulary's.
    const chips = screen
      .getByTestId("profile-about-languages")
      .querySelectorAll('[data-testid^="profile-about-languages-"]');
    expect(chips).toHaveLength(23);
    for (const chip of chips) {
      expect(chip.getAttribute("aria-pressed")).toMatch(/true|false/);
    }
    // A member the doctor does not currently speak is offered unchecked, and
    // clicking it adds it: the selection grows by choosing, never by typing.
    const tamil = screen.getByTestId("profile-about-languages-tamil");
    expect(tamil).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(tamil);
    expect(tamil).toHaveAttribute("aria-pressed", "true");
    // And the day list is the same kind of control over seven members.
    expect(
      screen
        .getByTestId("profile-about-days")
        .querySelectorAll('[data-testid^="profile-about-days-"]'),
    ).toHaveLength(7);
  });

  it("surfaces the save failure with the API trace id and a retry", async () => {
    savePractice.mockRejectedValue(
      new ApiError({
        code: "INTERNAL_ERROR",
        message: "boom",
        trace_id: "trace-save-543",
        details: {},
      }),
    );
    await renderReady();

    fireEvent.click(screen.getByTestId("profile-practice-save"));

    const banner = await screen.findByTestId("error-banner");
    expect(banner).toHaveTextContent(t.practiceSaveFailed);
    // The banner is inside the card that failed, so it is not a card the doctor
    // was not editing and not a page-level error standing over the other three.
    const card = screen.getByTestId("profile-practice-card");
    expect(within(card).getByTestId("error-banner-trace-id")).toHaveTextContent(
      "trace-save-543",
    );
  });
});

describe("DoctorProfilePage photo", () => {
  it("previews the stored photo through an object URL, never the media key", async () => {
    await renderReady(profile({ photo_ref: "doctor/7/photo-1.enc" }));

    await waitFor(() => expect(getPhoto).toHaveBeenCalled());
    const avatar = screen.getByTestId("profile-identity").querySelector("img");
    await waitFor(() => expect(avatar).not.toBeNull());
    expect(avatar?.getAttribute("src")).toBe(
      "blob:http://localhost/doctor-photo",
    );
    expect(avatar?.getAttribute("src")).not.toBe("doctor/7/photo-1.enc");
  });

  it("reads the doctor's photo once, shared with any other surface on that ref", async () => {
    await renderReady(profile({ photo_ref: "doctor/7/photo-1.enc" }));
    // A second surface on the same ref - the account menu and the dropdown
    // header are later work - asks the shared seam, not this page, so the bytes
    // are read once between them rather than once each.
    const other = renderHook(() =>
      useProfilePhotoSource("doctor/7/photo-1.enc", fetchDoctorProfilePhoto),
    );

    await waitFor(() => expect(other.result.current.src).not.toBeNull());
    expect(getPhoto).toHaveBeenCalledTimes(1);
    expect(other.result.current.src).toBe("blob:http://localhost/doctor-photo");
  });

  it("uploads a picked photo and re-streams the stored one", async () => {
    await renderReady();
    const file = new File(["photo"], "me.jpg", { type: "image/jpeg" });

    fireEvent.change(screen.getByTestId("profile-photo-input"), {
      target: { files: [file] },
    });

    await waitFor(() =>
      expect(uploadPhoto).toHaveBeenCalledWith(file, expect.any(String)),
    );
    await waitFor(() => expect(getPhoto).toHaveBeenCalled());
    expect(screen.getByTestId("profile-photo-remove")).toBeInTheDocument();
  });

  it("removes the photo and falls back to the avatar placeholder", async () => {
    await renderReady(profile({ photo_ref: "doctor/7/photo-1.enc" }));
    await waitFor(() => expect(getPhoto).toHaveBeenCalled());

    fireEvent.click(screen.getByTestId("profile-photo-remove"));

    await waitFor(() => expect(deletePhoto).toHaveBeenCalled());
    await waitFor(() =>
      expect(screen.queryByTestId("profile-photo-remove")).toBeNull(),
    );
    // The preview effect clears the object URL once the ref drops, so the
    // avatar is asserted on the settled state, not the first render after.
    await waitFor(() =>
      expect(
        screen.getByTestId("profile-identity").querySelector("img"),
      ).toBeNull(),
    );
  });

  it("reports an upload failure with the API trace, keeping the stored photo", async () => {
    uploadPhoto.mockRejectedValue(
      new ApiError({
        code: "INVALID_ARGS",
        message: "unsupported type",
        trace_id: "trace-photo-543",
        details: {},
      }),
    );
    await renderReady(profile({ photo_ref: "doctor/7/photo-1.enc" }));

    fireEvent.change(screen.getByTestId("profile-photo-input"), {
      target: { files: [new File(["x"], "x.txt", { type: "text/plain" })] },
    });

    const banner = await screen.findByTestId("error-banner");
    expect(banner).toHaveTextContent(t.photoFailed);
    expect(screen.getByTestId("error-banner-trace-id")).toHaveTextContent(
      "trace-photo-543",
    );
    // A failed upload leaves the stored photo in place and offers no retry:
    // the picked file is gone, so the doctor picks again.
    expect(screen.getByTestId("profile-photo-remove")).toBeInTheDocument();
    expect(
      within(screen.getByTestId("error-banner")).queryByTestId(
        "error-banner-retry",
      ),
    ).toBeNull();
  });

  it("degrades to the avatar fallback when the photo stream fails", async () => {
    getPhoto.mockRejectedValue(
      new ApiError({
        code: "DOCTOR_PROFILE_PHOTO_NOT_FOUND",
        message: "no photo",
        trace_id: "t",
        details: {},
      }),
    );
    await renderReady(profile({ photo_ref: "doctor/7/photo-1.enc" }));

    await waitFor(() => expect(getPhoto).toHaveBeenCalled());
    expect(
      screen.getByTestId("profile-identity").querySelector("img"),
    ).toBeNull();
    expect(screen.queryByTestId("error-banner")).toBeNull();
    // Nothing is behind the ref, so there is nothing to remove: a definite
    // absence offers Upload rather than a Remove that cannot succeed.
    expect(screen.queryByTestId("profile-photo-remove")).toBeNull();
    expect(screen.getByTestId("profile-photo-upload")).toHaveTextContent(
      t.photoUpload,
    );
  });

  it("keeps the stored photo removable when the read fails rather than finding no photo", async () => {
    getPhoto.mockRejectedValue(
      new ApiError({
        code: "NETWORK_ERROR",
        message: "offline",
        trace_id: "t",
        details: {},
      }),
    );
    await renderReady(profile({ photo_ref: "doctor/7/photo-1.enc" }));

    await waitFor(() => expect(getPhoto).toHaveBeenCalled());
    // A blip is not an absence, so the preview falls back to the avatar and
    // offers no error surface, but the stored photo still reads as a photo the
    // doctor can clear.
    expect(
      screen.getByTestId("profile-identity").querySelector("img"),
    ).toBeNull();
    expect(screen.queryByTestId("error-banner")).toBeNull();
    expect(screen.getByTestId("profile-photo-remove")).toBeInTheDocument();
  });
});

describe("DoctorProfilePage fee editor (moved from the landing)", () => {
  it("shows the current fee from the profile projection", async () => {
    await renderReady();

    expect(screen.getByTestId("fee-editor")).toBeInTheDocument();
    expect(screen.getByTestId("fee-current")).toHaveTextContent("\u20B9400");
    expect(screen.getByTestId("fee-clear")).toBeInTheDocument();
  });

  it("saves the fee through the unchanged fee path", async () => {
    await renderReady();

    fireEvent.change(screen.getByTestId("fee-input"), {
      target: { value: "500" },
    });
    fireEvent.click(screen.getByTestId("fee-save"));

    await waitFor(() =>
      expect(screen.getByTestId("fee-message")).toHaveTextContent(t.feeSaved),
    );
    expect(setFee).toHaveBeenCalledWith(50000, expect.any(String));
    expect(screen.getByTestId("fee-current")).toHaveTextContent("\u20B9500");
  });

  it("names a negative amount instead of silently ignoring the save", async () => {
    await renderReady();

    fireEvent.change(screen.getByTestId("fee-input"), {
      target: { value: "-5" },
    });
    fireEvent.click(screen.getByTestId("fee-save"));

    await waitFor(() =>
      expect(screen.getByTestId("fee-invalid")).toHaveTextContent(t.feeInvalid),
    );
    expect(setFee).not.toHaveBeenCalled();
  });

  it("clears the fee back to unset", async () => {
    await renderReady();

    fireEvent.click(screen.getByTestId("fee-clear"));

    await waitFor(() =>
      expect(screen.getByTestId("fee-message")).toHaveTextContent(t.feeSaved),
    );
    expect(setFee).toHaveBeenCalledWith(null, expect.any(String));
    expect(screen.queryByTestId("fee-current")).toBeNull();
    expect(screen.queryByTestId("fee-clear")).toBeNull();
  });

  it("surfaces the fee save failure with the API trace id", async () => {
    setFee.mockRejectedValue(
      new ApiError({
        code: "INTERNAL_ERROR",
        message: "boom",
        trace_id: "trace-fee-543",
        details: {},
      }),
    );
    await renderReady();

    fireEvent.change(screen.getByTestId("fee-input"), {
      target: { value: "500" },
    });
    fireEvent.click(screen.getByTestId("fee-save"));

    const banner = await within(screen.getByTestId("fee-editor")).findByTestId(
      "error-banner",
    );
    expect(banner).toHaveTextContent(t.feeSaveFailed);
    expect(
      within(screen.getByTestId("fee-editor")).getByTestId(
        "error-banner-trace-id",
      ),
    ).toHaveTextContent("trace-fee-543");
  });
});

describe("DoctorProfilePage bilingual parity (REQ-006)", () => {
  function LangFlipHost() {
    const { lang, setLang } = useLang();
    return (
      <>
        <button
          type="button"
          onClick={() => setLang(lang === "en" ? "hi" : "en")}
        >
          flip-lang
        </button>
        <DoctorProfilePage />
      </>
    );
  }

  it("renders the profile copy in Hindi when the locale flips", async () => {
    getProfile.mockResolvedValue(profile());
    render(
      <DoctorProfileProvider>
        <LangFlipHost />
      </DoctorProfileProvider>,
    );
    await waitFor(() => screen.getByTestId("profile-declared-band"));

    fireEvent.click(screen.getByText("flip-lang"));
    // #615: the ready state has no `PageHeader` title - the identity band's own
    // h1 and the two band headings are the copy that has to flip with the locale.
    // `getAllByText` because the declared band's title is deliberately in the
    // document twice: once as its heading, once as its anchor chip's label.
    await waitFor(() =>
      expect(screen.getAllByText(hiT.declaredBandTitle).length).toBeGreaterThan(
        0,
      ),
    );

    // #617: each card has its own Hindi title and its own save copy, and the chips
    // carry Hindi LABELS over the same machine values - which is the whole point of
    // keeping labels in the dictionary and values out of it.
    for (const [testId, title] of [
      ["profile-practice-card", hiT.practiceSectionTitle],
      ["profile-about-card", hiT.aboutSectionTitle],
      ["profile-notification-card", hiT.notificationsHeading],
    ] as const) {
      expect(
        within(screen.getByTestId(testId)).getByRole("heading", {
          name: title,
        }),
      ).toBeInTheDocument();
    }
    expect(screen.getByTestId("profile-about-save")).toHaveTextContent(
      hiT.save,
    );
    expect(
      screen.getByTestId("profile-notification-new_consultations"),
    ).toHaveAccessibleName(hiT.notificationLabels.new_consultations);
    expect(
      screen.getByTestId("profile-about-languages-hindi"),
    ).toHaveTextContent(hiT.languageLabels.Hindi);
    expect(screen.getByTestId("fee-editor")).toHaveTextContent(hiT.feeHeading);
    expect(screen.getByTestId("profile-public-preview")).toHaveTextContent(
      hiT.publicPreviewAction,
    );
  });

  // #617 (REQ-006): the two dictionaries carry the same KEYS for everything this
  // ticket added. Key parity is the failure that actually ships - a missing Hindi
  // string renders as `undefined` on the page, and a missing Hindi vocabular
  // LABEL renders a chip whose text is a machine key, which is exactly the thing
  // this ticket replaced. Asserted structurally so the shape cannot drift.
  it("gives every practice/about/notification key a Hindi string", () => {
    const added = [
      "practiceSectionTitle",
      "practiceSectionHelp",
      "practiceFullNameLabel",
      "practiceFullNameHelp",
      "practiceClinicNameLabel",
      "practiceClinicNameHelp",
      "practiceSpecialtiesLabel",
      "practiceNameRequired",
      "practiceNameTooLong",
      "practiceClinicNameTooLong",
      "practiceExperienceInvalid",
      "practiceSpecialtiesRejected",
      "practiceSaved",
      "practiceSaveFailed",
      "aboutSectionTitle",
      "aboutSectionHelp",
      "aboutLabel",
      "aboutHelp",
      "aboutTooLong",
      "aboutSaved",
      "aboutSaveFailed",
      "languagesLabel",
      "languagesHelp",
      "languagesRejected",
      "consultingDaysLabel",
      "consultingDaysHelp",
      "consultingDaysRejected",
      "consultingHoursLabel",
      "consultingHoursHelp",
      "consultingHoursPlaceholder",
      "notificationsHeading",
      "notificationsHelp",
      "notificationGroupLabel",
      "notificationPreferencesRejected",
      "notificationsSaved",
      "notificationsSaveFailed",
      "specialtyLabels",
      "languageLabels",
      "dayLabels",
      "notificationLabels",
    ] as const;
    for (const key of added) {
      expect(
        Object.prototype.hasOwnProperty.call(hiT, key),
        `hi.doctorProfile.${key} is missing`,
      ).toBe(true);
    }
    // Every member of all three vocabularies plus the five keys is labelled in
    // BOTH locales. A count alone would pass with a member renamed, so each side
    // is checked against the same member list the card renders.
    expect(Object.keys(hiT.specialtyLabels).sort()).toEqual(
      Object.keys(t.specialtyLabels).sort(),
    );
    expect(Object.keys(hiT.languageLabels).sort()).toEqual(
      Object.keys(t.languageLabels).sort(),
    );
    expect(Object.keys(hiT.dayLabels).sort()).toEqual(
      Object.keys(t.dayLabels).sort(),
    );
    expect(Object.keys(hiT.notificationLabels).sort()).toEqual(
      Object.keys(t.notificationLabels).sort(),
    );
    expect(Object.keys(hiT.specialtyLabels)).toHaveLength(20);
    expect(Object.keys(hiT.languageLabels)).toHaveLength(23);
    expect(Object.keys(hiT.dayLabels)).toHaveLength(7);
    expect(Object.keys(hiT.notificationLabels)).toHaveLength(5);
    // A Hindi label that is a copy of the machine value is the failure this
    // ticket exists to prevent: the chip would read "Hindi" in English too, and
    // for the twelve languages whose name is not itself Hindi the doctor would be
    // choosing from a value instead of a label.
    for (const [member, label] of Object.entries(hiT.languageLabels)) {
      expect(label.length, `${member} has no Hindi label`).toBeGreaterThan(0);
    }
  });
});

// #617 (AC 1, AC 2): keyboard operability and the ROLE, both asserted through what
// a screen reader announces rather than through the control's class or its internal
// state.
//
// #623: this suite used to drive the keyboard with `fireEvent` on the stated
// grounds that the repo had no `user-event`, and compensated by following each key
// event with a synthetic `fireEvent.click`. That compensation meant every assertion
// in the activation steps below was reached by a mouse - the suite asserted
// keyboard operability in its comments while proving only that clicking worked, and
// it could not have failed for a chip the keyboard could not reach. `user-event` is
// now a dependency, so the keypress performs the activation itself: it runs the
// browser's default action for the key on the focused native `<button>`, and the
// state a screen reader reads arrives from the keystroke that caused it.
describe("DoctorProfilePage keyboard and roles (#617)", () => {
  // ACTIVATION and NAVIGATION are both the browser's own behaviour on a native
  // `<button>`, and both are now driven by real key presses rather than simulated.
  // The one thing still worth knowing is that jsdom has no default-action machinery
  // of its own, so that behaviour comes from `user-event` here; what is asserted is
  // what the browser does with the key, which is the part this page controls.
  it("announces pressed state and walks between chips with the arrow keys", async () => {
    await renderReady();

    const chip = screen.getByTestId(
      "profile-about-languages-maithili",
    ) as HTMLButtonElement;
    // What it IS: a toggle button whose state is "pressed", not a checkbox and not
    // a button that says "selected". A screen reader announces exactly this, so
    // this is the assertion that proves the primitive was composed rather than
    // hand-rolled to look like it.
    expect(chip.tagName).toBe("BUTTON");
    expect(chip).toHaveAttribute("aria-pressed", "false");
    expect(chip).toHaveAccessibleName(t.languageLabels.Maithili);

    // Roaming tabindex, in the state a page actually loads in: until focus has
    // entered, Radix puts the single tab stop on the GROUP and leaves every chip at
    // -1, so Tab reaches the control once rather than walking twenty-three chips.
    const group = screen.getByTestId("profile-about-languages");
    const chips: (HTMLButtonElement | null)[] = [
      group.querySelector<HTMLButtonElement>(
        '[data-testid="profile-about-languages-assamese"]',
      ),
      group.querySelector<HTMLButtonElement>(
        '[data-testid="profile-about-languages-bengali"]',
      ),
      group.querySelector<HTMLButtonElement>(
        '[data-testid="profile-about-languages-bodo"]',
      ),
    ];
    for (const el of chips) expect(el?.tabIndex).toBe(-1);
    expect(group).toHaveAttribute("tabindex", "0");

    // Entering the group and pressing the arrow key moves focus along it, and the
    // chip that now holds focus becomes the tab stop - so the next Tab returns to
    // where the keyboard left off rather than to the top of the list. Radix defers
    // the move by a task so a re-render cannot steal the focus it is setting, so
    // this is awaited rather than asserted synchronously.
    const user = userEvent.setup();
    const start = chips[0] as HTMLButtonElement;

    // Entering the group and pressing the arrow key moves focus along it, and the
    // chip that now holds focus becomes the tab stop - so the next Tab returns to
    // where the keyboard left off rather than to the top of the list. Radix defers
    // the move by a task so a re-render cannot steal the focus it is setting, so
    // this is awaited rather than asserted synchronously.
    start.focus();
    await user.keyboard("{ArrowRight}");
    await waitFor(() => expect(document.activeElement).toBe(chips[1]));
    expect(chips[1]?.tabIndex).toBe(0);
    expect(chips[0]?.tabIndex).toBe(-1);

    // Activating a chip flips the state a screen reader reads, and that selection
    // is what a save declares. Nothing here clicks the chip: the space keypress is
    // the cause of the `aria-pressed` change asserted right after it.
    chip.focus();
    await user.keyboard(" ");
    expect(chip).toHaveAttribute("aria-pressed", "true");

    // Save is reached and pressed from the keyboard too, so a doctor who never
    // touches a pointer can commit the selection the walk produced.
    const save = screen.getByTestId("profile-about-save");
    save.focus();
    await user.keyboard("{Enter}");
    await waitFor(() => expect(saveAbout).toHaveBeenCalledTimes(1));
    expect(saveAbout.mock.calls[0][0].languages).toContain("Maithili");
  });

  // #623: the help text used to sit inside the wrapping `<label>`, which made it
  // part of the control's ACCESSIBLE NAME - a hint read as "Languages Separate with
  // commas". The hint is now a DESCRIPTION, which is what it is. Asserted on the
  // rendered name AND on the description binding, because either half alone would
  // pass a broken fix, and on both field shapes because they take different routes:
  // `ProfileField` clones its single control, `ProfileToggleField` names a group.
  it("keeps a field's hint out of its accessible name and binds it as a description", async () => {
    await renderReady();

    // The single-input shape: a number input whose label wraps it.
    const experience = screen.getByRole("spinbutton", {
      name: t.experienceLabel,
    });
    expect(experience).toHaveAccessibleName(t.experienceLabel);
    expect(experience).toHaveAccessibleDescription(t.experienceHelp);

    // The group shape: twenty-three chips that a wrapping label would have named
    // all twenty-three times. The group's name is the label alone.
    const languages = screen.getByTestId("profile-about-languages");
    expect(languages).toHaveAccessibleName(t.languagesLabel);
    expect(languages).toHaveAccessibleDescription(t.languagesHelp);

    // And a field carrying both a hint and a validation message: the PIN input's
    // error and its hint are two descriptions of one control, and the merge must
    // keep both rather than letting either replace the other.
    const pin = screen.getByTestId("profile-address-pin");
    expect(pin.getAttribute("aria-describedby")?.split(/\s+/)).toContain(
      "profile-address-pin-help",
    );
  });

  // #623: a refusal rendered as a sibling live region is ANNOUNCED when it appears,
  // but it is not ASSOCIATED - tabbing into the twenty-three language chips gave no
  // hint that the server had just refused the last attempt, and an accessibility
  // checker reports the group as undescribed. The group's `aria-describedby` now
  // carries the refusal's id alongside the help text.
  it("associates a toggle group's refusal with the group, not just the page", async () => {
    // A real `ApiError` carrying a 422 that names `languages`: the hook reads the
    // refusal out of `details.errors[].path`, so a plain object here would be
    // correctly ignored and the test would prove nothing.
    saveAbout.mockRejectedValue(
      new ApiError({
        code: "DOCTOR_PROFILE_INVALID_CONSULT_LANGUAGE",
        message: "that language is not offered",
        trace_id: "t-rx-lang",
        details: { errors: [{ path: "languages", reason: "not_offered" }] },
      }),
    );
    await renderReady();

    fireEvent.click(screen.getByTestId("profile-about-save"));
    const refusal = await screen.findByTestId("profile-about-languages-error");

    const group = screen.getByTestId("profile-about-languages");
    expect(group.getAttribute("aria-describedby")?.split(/\s+/)).toContain(
      refusal.id,
    );
    // The help text is still described too - a refusal does not replace the guidance.
    expect(group.getAttribute("aria-describedby")?.split(/\s+/)).toContain(
      "profile-about-languages-help",
    );
  });

  // The same association on the OTHER toggle group. #623 wired About's language and
  // consulting-day chips first and missed the Practice card's specialty group, so
  // it was the one chip row on the page still describing itself with help text
  // alone. Asserted here rather than only for About because the point of the fix
  // is a rule about toggle groups, and a rule pinned on one instance is not a
  // rule - it is a patch that the next toggle group walks straight past.
  it("associates the specialty group's refusal with the group as well", async () => {
    savePractice.mockRejectedValue(
      new ApiError({
        code: "DOCTOR_PROFILE_INVALID_SPECIALTY",
        message: "that specialty is not offered",
        trace_id: "t-rx-spec",
        details: { errors: [{ path: "specialties", reason: "not_offered" }] },
      }),
    );
    await renderReady();

    fireEvent.click(screen.getByTestId("profile-practice-save"));
    const refusal = await screen.findByTestId(
      "profile-practice-specialties-error",
    );

    const group = screen.getByTestId("profile-practice-specialties");
    const described = group.getAttribute("aria-describedby")?.split(/\s+/);
    expect(described).toContain(refusal.id);
    // And the help text still rides along, as on the About group.
    expect(described).toContain("profile-practice-specialties-help");
  });

  it("names each notification control as a switch rather than a bare checkbox", async () => {
    await renderReady();

    // The role assertion, by accessible name rather than by test id: this is what
    // replaced a bare `<input type="checkbox">`, and a control that kept the old
    // role would still pass every other assertion in this file.
    const first = screen.getByRole("switch", {
      name: t.notificationLabels.new_consultations,
    });
    expect(first).toHaveAttribute("aria-checked", "true");

    // Radix's switch carries a hidden native input so the value participates in a
    // form POST. It is `aria-hidden` and untabbable, so it is not a control a doctor
    // can reach or a second thing announced - which is what "not a bare checkbox"
    // has to mean for a switch that is still a button.
    const natives = screen
      .getByTestId("profile-notification-group")
      .querySelectorAll<HTMLInputElement>('input[type="checkbox"]');
    expect(natives).toHaveLength(5);
    for (const native of natives) {
      expect(native).toHaveAttribute("aria-hidden", "true");
      expect(native.tabIndex).toBe(-1);
    }
    // Exactly five controls in the group, and the fifth is reachable by name too.
    expect(
      screen
        .getAllByRole("switch")
        .map((el) => el.getAttribute("aria-checked")),
    ).toHaveLength(5);
    const second = screen.getByRole("switch", {
      name: t.notificationLabels.record_shared,
    });
    fireEvent.click(second);
    expect(second).toHaveAttribute("aria-checked", "true");

    fireEvent.click(screen.getByTestId("profile-notifications-save"));
    await waitFor(() => expect(saveNotifications).toHaveBeenCalledTimes(1));
    expect(
      saveNotifications.mock.calls[0][0].notification_preferences,
    ).toMatchObject({ record_shared: true, new_consultations: true });
  });
  // §9.4's floor, pinned. axe cannot catch this one: `target-size` is a WCAG 2.2
  // rule and jsdom has no layout, so the class list is the only observable a unit
  // test has. `min-h-11`/`h-11` are Tailwind's 44px and nothing else, and a
  // "simplification" to a shorter size here would pass every other assertion in
  // this file while shipping forty-seven sub-44px tap targets.
  it("keeps every new control at or above the 44px touch-target floor", async () => {
    await renderReady();

    // Each notification row is the tap target, because the switch inside it is not.
    const rows = screen
      .getByTestId("profile-notification-group")
      .querySelectorAll("label");
    expect(rows).toHaveLength(5);
    for (const row of rows) {
      expect(row.className).toContain("min-h-11");
    }
    // And every vocabulary chip resolves to the 44px size rather than the 36px one.
    const chips = screen
      .getByTestId("profile-about-languages")
      .querySelectorAll("button");
    expect(chips.length).toBe(23);
    for (const chip of chips) {
      expect(chip.className).toContain("h-11");
      expect(chip.className).not.toContain("h-9");
    }
  });
});

// #617 (REQ): the declared band now carries 47 chips that did not exist before -
// 20 specialties, 23 languages and 7 days, each a focusable control with a name.
// A chip with no name, or a group of chips announced as one control, is exactly the
// failure a scan catches and a unit assertion about `aria-pressed` cannot. The scan
// is local to this suite and runs over this page's own container, so it says
// something about THIS page rather than asserting some shared helper stays quiet.
//
// Two states, because the interesting one is the state with the error surfaces up:
// an alert region that has been given focus, and a card whose fields are marked
// invalid, are new nodes since the ready state was scanned.
describe("DoctorProfilePage axe (REQ)", () => {
  it("scans clean with the four declared cards rendered", async () => {
    const { container } = await renderReady();

    // The three vocabularies really are on the page in this state - a scan of a page
    // that rendered no chips would pass without having checked anything.
    expect(
      container.querySelectorAll(
        '[data-testid^="profile-practice-specialties-"]',
      ).length,
    ).toBe(20);
    expect((await axe.run(container)).violations).toEqual([]);
  });

  // A client-side REFUSAL, which puts the card's own `role="alert"` summary on the
  // page holding focus. The over-long value cannot reach the network, so this case
  // is about the summary and nothing else - the server-refusal state is the next
  // case, and the pending state the one after it.
  it("scans clean with a client-refused save on screen", async () => {
    const { container } = await renderReady();

    fireEvent.change(screen.getByTestId("profile-practice-name"), {
      target: { value: "x".repeat(PRACTICE_LIMITS.fullName + 1) },
    });
    fireEvent.click(screen.getByTestId("profile-practice-save"));
    await waitFor(() =>
      expect(
        screen.getByTestId("profile-practice-summary"),
      ).toBeInTheDocument(),
    );
    // The refusal is client-side, so nothing was called: the state on screen is the
    // summary, not an error banner.
    expect(savePractice).not.toHaveBeenCalled();

    expect((await axe.run(container)).violations).toEqual([]);
  });

  // A rejected WRITE, not a client refusal: only one of the two puts the error
  // banner and its trace id on the page. A blank name would have been refused
  // before the request left, which is the case above wearing this one's name.
  it("scans clean with a server-refused save on screen", async () => {
    savePractice.mockRejectedValue(
      new ApiError({
        code: "INTERNAL_ERROR",
        message: "boom",
        trace_id: "trace-axe-617",
        details: {},
      }),
    );
    const { container } = await renderReady();

    fireEvent.change(screen.getByTestId("profile-practice-name"), {
      target: { value: "Sunrise Clinic 3" },
    });
    fireEvent.click(screen.getByTestId("profile-practice-save"));
    await waitFor(() =>
      expect(
        within(screen.getByTestId("profile-practice-card")).getByTestId(
          "error-banner-trace-id",
        ),
      ).toHaveTextContent("trace-axe-617"),
    );

    expect((await axe.run(container)).violations).toEqual([]);
  });

  // The pending state is its own scan because the shell swaps the save button for a
  // spinner and mutes it, and a spinner with no accessible name is announced as
  // nothing at all.
  it("scans clean with a save in flight", async () => {
    const { container } = await renderReady();
    let settle: (view: DoctorProfileView) => void = () => {};
    savePractice.mockImplementationOnce(
      () =>
        new Promise<DoctorProfileView>((resolve) => {
          settle = resolve;
        }),
    );

    fireEvent.change(screen.getByTestId("profile-practice-name"), {
      target: { value: "Sunrise Clinic 4" },
    });
    fireEvent.click(screen.getByTestId("profile-practice-save"));
    await waitFor(() =>
      expect(screen.getByTestId("profile-practice-save")).toBeDisabled(),
    );

    expect((await axe.run(container)).violations).toEqual([]);
    settle(profile({ practice_name: "Sunrise Clinic 4" }));
  });
});

describe("DoctorProfilePage live preview (#618)", () => {
  it("renders the public profile's renderer beside the form", async () => {
    await renderReady();

    // The preview is not a summary the page wrote: it is the same renderer the
    // public route runs, which the no-drift suite in `components/public` pins.
    expect(screen.getByTestId("profile-live-preview")).toBeInTheDocument();
    expect(
      within(screen.getByTestId("profile-live-preview")).getByTestId(
        "profile-hero",
      ),
    ).toBeInTheDocument();
    expect(screen.getByTestId("profile-live-preview")).toHaveTextContent(
      t.livePreviewHelp,
    );
  });

  it("follows the practice name as the doctor types, with no save in between", async () => {
    // The whole reason the preview exists: what the doctor is about to publish is
    // visible while they are still deciding it.
    await renderReady();

    const preview = () => screen.getByTestId("profile-live-preview");
    expect(preview()).toHaveTextContent("Sunrise Clinic");

    fireEvent.change(screen.getByTestId("profile-practice-name"), {
      target: { value: "Sunrise Clinic 4" },
    });

    expect(within(preview()).getByTestId("profile-name")).toHaveTextContent(
      "Sunrise Clinic 4",
    );
  });

  it("follows the declared locality as the doctor types it", async () => {
    // The public projection serves the DECLARED locality, so the locality field is
    // the one address input the preview can honestly show. The PIN, the street and
    // the city are not on the public surface at all.
    //
    // #619: it now appears in the DECLARED band rather than the solid-edged
    // summary, because that is where the public page renders it and a preview that
    // put it somewhere else would teach the doctor a page we do not ship.
    await renderReady();

    fireEvent.change(screen.getByTestId("profile-address-locality"), {
      target: { value: "Medininagar" },
    });

    expect(
      within(screen.getByTestId("profile-live-preview")).getByTestId(
        "profile-declared-address-locality",
      ),
    ).toHaveTextContent("Medininagar");
  });

  it("leaves the page with exactly one h1", async () => {
    // The preview renders the same name the public page shows as its heading, so
    // the level is a prop: a second `h1` here would give a screen reader two
    // titles and undo what the identity band was built to do.
    await renderReady();

    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(
      within(screen.getByTestId("profile-live-preview")).getByTestId(
        "profile-name",
      ).tagName,
    ).toBe("H2");
  });
});
