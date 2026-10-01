// PHASE-6 T06 (#312), retargeted by #618: the shared public-profile renderer
// suite. The verified-safe rendering rules (FEAT-005/ADR-0011) are unchanged - the
// verified indicator derives strictly from the backend field, credential display is
// type + status + expiry labels only (never raw documents), a 404 renders the
// clear not-found state, an unexpected failure renders the retryable error state,
// and the payload fields the API does not carry (fee, languages, experience,
// services) are never invented.
//
// #618 added the property the whole ticket exists for: the renderer is rendered
// ONCE, and both hosts are asserted to produce that same markup. Before this the
// suite could only prove the public page was right; nothing stopped a second copy
// of a band from appearing next to it and drifting.
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ProviderProfile } from "./ProviderProfile";
import { ProviderProfileBody } from "./ProviderProfileBody";
import type { ProviderProfile as ProviderProfileShape } from "@/lib/directory/profile";
import type { DoctorProfileView } from "@/lib/doctor/api";
import { ProfileLivePreview } from "@/components/doctor/profile/ProfileLivePreview";
import { PublicProfileDraftProvider } from "@/components/doctor/profile/PublicProfileDraftContext";
import {
  draftFromProfile,
  projectPublicProfile,
} from "@/components/doctor/profile/publicProfileProjection";
import {
  LangProvider,
  useLang,
  __resetLangForTests,
} from "@/lib/i18n/LangContext";

vi.mock("@/lib/directory/profile", async (importOriginal) => {
  const original =
    await importOriginal<typeof import("@/lib/directory/profile")>();
  return { ...original, fetchProviderProfile: vi.fn() };
});

const { emitPartnerSelected } = vi.hoisted(() => ({
  emitPartnerSelected: vi.fn(),
}));

vi.mock("@/lib/directory/emit", () => ({ emitPartnerSelected }));

// Import after the mock declaration so the suite binds the mocked function.
import { fetchProviderProfile } from "@/lib/directory/profile";

const mockFetch = vi.mocked(fetchProviderProfile);

function doctorProfile(): ProviderProfileShape {
  return {
    partner_id: 7,
    practice_name: "Dr. Rakesh Sharma",
    partner_type: "doctor",
    specialty: "General Physician",
    area: "Daltonganj",
    verified: true,
    credentials: [
      {
        credential_type: "medical_registration",
        status: "verified",
        expires_at: "2030-04-30T00:00:00Z",
      },
      {
        credential_type: "qualification_certificate",
        status: "verified",
        expires_at: null,
      },
    ],
  };
}

function labProfile(): ProviderProfileShape {
  return {
    partner_id: 9,
    practice_name: "Sahyog Path Lab",
    partner_type: "lab",
    specialty: null,
    area: "Daltonganj",
    verified: true,
    credentials: [
      {
        credential_type: "accreditation",
        status: "verified",
        expires_at: "2027-03-31T00:00:00Z",
      },
    ],
  };
}

function LangSwitcher() {
  const { lang, setLang } = useLang();
  return (
    <button type="button" onClick={() => setLang(lang === "en" ? "hi" : "en")}>
      {lang === "en" ? "\u0939\u093F\u0902" : "EN"}
    </button>
  );
}

/**
 * The private projection the doctor's own page holds, chosen so that projecting it
 * produces EXACTLY the `doctorProfile()` fixture above - the same partner, the
 * same declared name, the first of the same two specialties, the same declared
 * locality, the same credentials and the same flag. That equality is what makes
 * the no-drift assertion below a comparison of markup rather than of two things
 * that merely look alike.
 */
function doctorView(
  overrides: Partial<DoctorProfileView> = {},
): DoctorProfileView {
  return {
    partner_id: 7,
    photo_ref: null,
    practice_name: "Dr. Rakesh Sharma",
    clinic_name: null,
    specialties: ["General Physician", "Paediatrics"],
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
    languages: ["English", "Hindi"],
    experience_years: 12,
    about: null,
    consultation_fee: null,
    consulting_days: ["mon"],
    consulting_hours: "9am-5pm",
    credentials: [
      {
        credential_type: "medical_registration",
        status: "verified",
        expires_at: "2030-04-30T00:00:00Z",
      },
      {
        credential_type: "qualification_certificate",
        status: "verified",
        expires_at: null,
      },
    ],
    notification_preferences: {},
    ...overrides,
  };
}

function renderProfile(partnerId = 7) {
  return render(
    <LangProvider>
      <LangSwitcher />
      <ProviderProfile partnerId={partnerId} />
    </LangProvider>,
  );
}

beforeEach(() => {
  mockFetch.mockReset();
  emitPartnerSelected.mockClear();
  __resetLangForTests();
  document.documentElement.lang = "en";
});

afterEach(() => {
  cleanup();
});

describe("ProviderProfile loading", () => {
  it("shows a skeleton while the profile is in flight", () => {
    mockFetch.mockReturnValue(new Promise(() => {}));

    renderProfile();

    expect(screen.getByTestId("profile-loading")).toBeInTheDocument();
    expect(screen.queryByTestId("profile-hero")).not.toBeInTheDocument();
    expect(screen.queryByTestId("profile-not-found")).not.toBeInTheDocument();
  });
});

describe("ProviderProfile rendering a reachable profile", () => {
  it("shows the hero with name, verified badge, type and specialty", async () => {
    mockFetch.mockResolvedValue({ status: "found", profile: doctorProfile() });

    renderProfile();

    await waitFor(() =>
      expect(screen.getByTestId("profile-hero")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("profile-name")).toHaveTextContent(
      "Dr. Rakesh Sharma",
    );
    // Verified indicator derives from the backend field (FEAT-005) - a
    // reachable profile carries the CareSetu seal.
    expect(screen.getByTestId("profile-verified")).toHaveTextContent(
      "Verified by CareSetu",
    );
    expect(screen.getByTestId("profile-subtitle")).toHaveTextContent("Doctor");
    expect(screen.getByTestId("profile-subtitle")).toHaveTextContent(
      "General Physician",
    );
  });

  it("renders credential type labels plus expiry, never raw documents", async () => {
    mockFetch.mockResolvedValue({ status: "found", profile: doctorProfile() });

    renderProfile();

    await screen.findByTestId("profile-credentials");
    const rows = screen.getAllByTestId("credential-row");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("Medical registration");
    expect(rows[0]).toHaveTextContent("Expires 30 Apr 2030");
    expect(rows[0]).toHaveTextContent("Verified");
    // Non-expiring credential renders no expiry line.
    expect(rows[1]).toHaveTextContent("Qualification certificate");
    expect(rows[1]).not.toHaveTextContent("Expires");
  });

  it("shows the doctor practice-details heading and no invented fields", async () => {
    mockFetch.mockResolvedValue({ status: "found", profile: doctorProfile() });

    renderProfile();

    await screen.findByTestId("profile-details");
    expect(
      screen.getByRole("heading", { name: "Practice details" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Type")).toBeInTheDocument();
    expect(screen.getByText("Specialty")).toBeInTheDocument();
    expect(screen.getByText("Service area")).toBeInTheDocument();
    // Fields the API payload does not carry are never invented (fee, consult
    // types, languages, experience, services).
    expect(screen.queryByText(/consultation fee/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/languages/i)).not.toBeInTheDocument();
  });

  it("renders the lab variant with the credentials & licenses heading", async () => {
    mockFetch.mockResolvedValue({ status: "found", profile: labProfile() });

    renderProfile(9);

    await screen.findByTestId("profile-hero");
    expect(screen.getByTestId("profile-name")).toHaveTextContent(
      "Sahyog Path Lab",
    );
    expect(
      screen.getByRole("heading", { name: "Credentials & licenses" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Details" }),
    ).toBeInTheDocument();
    // No specialty row for labs.
    expect(screen.queryByText("Specialty")).not.toBeInTheDocument();
    expect(screen.getByTestId("profile-subtitle")).toHaveTextContent(
      "Laboratory",
    );
  });

  it("never renders private fields even if the payload carried extra keys", async () => {
    // FEAT-005 worst case: the payload shape guard passes (all required
    // fields), but the page must still not render emails/phones/PHI.
    const withExtras = {
      ...doctorProfile(),
      email: "rakesh@example.com",
      phone: "+91 90000 00000",
    } as unknown as ProviderProfileShape;
    mockFetch.mockResolvedValue({ status: "found", profile: withExtras });

    renderProfile();

    await screen.findByTestId("profile-hero");
    expect(screen.queryByText(/rakesh@example\.com/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/\+91 90000 00000/i)).not.toBeInTheDocument();
  });

  it("does not render the verified seal when the backend marks the profile unverified", async () => {
    const unverified = { ...doctorProfile(), verified: false };
    mockFetch.mockResolvedValue({ status: "found", profile: unverified });

    renderProfile();

    await screen.findByTestId("profile-hero");
    expect(screen.queryByTestId("profile-verified")).not.toBeInTheDocument();
  });
});

describe("ProviderProfile not-found and error states", () => {
  it("renders the clear not-found state on a backend 404", async () => {
    mockFetch.mockResolvedValue({ status: "not-found" });

    renderProfile(99);

    expect(await screen.findByTestId("profile-not-found")).toBeInTheDocument();
    expect(screen.getByText("Provider not found")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Browse the directory" }),
    ).toHaveAttribute("href", "/directory");
  });

  it("renders the retryable error state on a fetch failure and retries", async () => {
    mockFetch.mockRejectedValue(new Error("network down"));

    renderProfile();

    expect(await screen.findByTestId("profile-error")).toBeInTheDocument();
    expect(
      screen.getByText("We could not load this provider profile."),
    ).toBeInTheDocument();

    mockFetch.mockResolvedValue({ status: "found", profile: doctorProfile() });
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));

    await waitFor(() =>
      expect(screen.getByTestId("profile-hero")).toBeInTheDocument(),
    );
  });
});

describe("ProviderProfile bilingual parity (REQ-006)", () => {
  it("renames the copy to Hindi when the language flips", async () => {
    mockFetch.mockResolvedValue({ status: "found", profile: doctorProfile() });
    const { unmount } = renderProfile();

    await screen.findByTestId("profile-hero");
    fireEvent.click(screen.getByRole("button", { name: "\u0939\u093F\u0902" }));

    expect(await screen.findByTestId("profile-verified")).toHaveTextContent(
      "CareSetu द्वारा सत्यापित",
    );
    expect(screen.getByTestId("profile-name")).toHaveTextContent(
      "Dr. Rakesh Sharma",
    );
    expect(screen.getByText("मेडिकल पंजीकरण")).toBeInTheDocument();
    unmount();
  });
});

describe("ProviderProfile partner.selected emission (T6)", () => {
  it("fires the anonymous pick exactly once on mount", async () => {
    mockFetch.mockResolvedValue({ status: "found", profile: doctorProfile() });

    renderProfile();

    // The pick fires on open - one anonymous emission with the profile facts.
    await waitFor(() => expect(emitPartnerSelected).toHaveBeenCalledTimes(1));
    expect(emitPartnerSelected).toHaveBeenCalledWith({
      partner_id: 7,
      partner_type: null,
      source: "provider_profile",
    });
  });

  it("fires once across re-renders - never double-fires on re-render", async () => {
    mockFetch.mockResolvedValue({ status: "found", profile: doctorProfile() });
    const { unmount } = renderProfile();

    await screen.findByTestId("profile-hero");
    expect(emitPartnerSelected).toHaveBeenCalledTimes(1);

    // A language flip re-renders the surface; the mount-once pick stays single.
    fireEvent.click(screen.getByRole("button", { name: "\u0939\u093F\u0902" }));
    await screen.findByTestId("profile-verified");
    expect(emitPartnerSelected).toHaveBeenCalledTimes(1);

    unmount();
  });
});

// #618 AC 1: the presentational component on its own. Nothing about rendering a
// projection needs a request, so nothing may make one - a component that fetched
// its own data could not be fed a draft, which is the entire premise of the
// preview.
describe("ProviderProfileBody renders a projection and fetches nothing", () => {
  it("renders from its prop with no request at all", () => {
    render(
      <LangProvider>
        <ProviderProfileBody profile={doctorProfile()} headingLevel={1} />
      </LangProvider>,
    );

    expect(screen.getByTestId("profile-hero")).toBeInTheDocument();
    expect(screen.getByTestId("profile-name")).toHaveTextContent(
      "Dr. Rakesh Sharma",
    );
    // The client is mocked for this whole suite, so a single call would be visible.
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it("states the heading level its host owns, and changes nothing else", () => {
    // Same text, same element, only the level differs: the console already spends
    // its `h1` on the identity band's name, and a second `h1` on one page gives a
    // screen reader two titles.
    render(
      <LangProvider>
        <ProviderProfileBody profile={doctorProfile()} headingLevel={2} />
      </LangProvider>,
    );

    expect(screen.getByTestId("profile-name").tagName).toBe("H2");
    expect(screen.getByTestId("profile-name")).toHaveTextContent(
      "Dr. Rakesh Sharma",
    );
  });
});

// #618 AC 4: the no-drift property. One render of the renderer, and both hosts
// asserted byte-equal to it. Markup, not test ids - a host that reworded a band
// inside the body, re-ordered the sections, or changed a class would change this
// string. It cannot see a band a host adds OUTSIDE `public-profile-body`; that is
// out of scope for "one renderer", which is about the body itself.
describe("the public page and the doctor's preview render through the same component", () => {
  /**
   * The heading tag is the one thing a host states, so it is normalised away and
   * everything else has to match exactly. A host that reworded a band, re-ordered
   * the sections or grew its own copy of one changes this string.
   */
  function normalise(markup: string): string {
    return markup.replace(/<(\/?)h[12]/g, "<$1h@");
  }

  /** The renderer's own markup, captured from one render of the renderer. */
  function renderBodyOnce(): string {
    render(
      <LangProvider>
        <ProviderProfileBody profile={doctorProfile()} headingLevel={1} />
      </LangProvider>,
    );
    const markup = normalise(
      screen.getByTestId("public-profile-body").innerHTML,
    );
    cleanup();
    return markup;
  }

  it("gives both hosts the renderer's own markup, byte for byte", async () => {
    const expected = renderBodyOnce();

    // The public page: the API's answer, through the fetching container.
    mockFetch.mockResolvedValue({ status: "found", profile: doctorProfile() });
    renderProfile();
    await screen.findByTestId("profile-hero");
    expect(normalise(screen.getByTestId("public-profile-body").innerHTML)).toBe(
      expected,
    );

    cleanup();

    // The doctor's preview: local form state, through the draft projection. The
    // equality below is the guard that makes the markup comparison meaningful - if
    // the projection did not produce the very same profile, the two would differ
    // for the right reason and this test would fail for the wrong one.
    const view = doctorView();
    expect(projectPublicProfile(view, draftFromProfile(view))).toEqual(
      doctorProfile(),
    );

    render(
      <LangProvider>
        <PublicProfileDraftProvider profile={view}>
          <ProfileLivePreview />
        </PublicProfileDraftProvider>
      </LangProvider>,
    );
    expect(normalise(screen.getByTestId("public-profile-body").innerHTML)).toBe(
      expected,
    );
  });

  it("renders no verified marker for a profile the API did not mark verified", () => {
    // AC 5, from the doctor's side: the preview is fed typed state, so this is
    // where a fabrication would happen. Every declared field is filled in and the
    // flag is false, and no tick may appear - on the hero, in the trust cue or
    // beside a credential (ADR-0011: the tick is derived, never stored).
    const view = doctorView({
      verified: false,
      credentials: [
        {
          credential_type: "medical_registration",
          status: "pending",
          expires_at: "2030-04-30T00:00:00Z",
        },
      ],
    });

    render(
      <LangProvider>
        <PublicProfileDraftProvider profile={view}>
          <ProfileLivePreview />
        </PublicProfileDraftProvider>
      </LangProvider>,
    );

    const preview = within(screen.getByTestId("profile-live-preview"));
    expect(preview.queryByTestId("profile-verified")).toBeNull();
    expect(preview.queryByText("Verified by CareSetu")).toBeNull();
    expect(preview.getByTestId("credential-row")).not.toHaveTextContent(
      "Verified",
    );
    // The declared fields are all still there - what is withheld is the claim, not
    // the profile.
    expect(preview.getByTestId("profile-name")).toHaveTextContent(
      "Dr. Rakesh Sharma",
    );
  });
});
