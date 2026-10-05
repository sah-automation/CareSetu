// PHASE-2.6 T06 (#197): AppShell variant suite - light density never renders
// a sidebar, full density collapses with per-role persistence, both densities
// render nav-config-driven tabs/top-nav with Soon semantics and bilingual
// labels; the retired matchMedia mechanics stay gone via source scan.

import {
  render,
  screen,
  fireEvent,
  cleanup,
  waitFor,
  within,
} from "@testing-library/react";
import {
  describe,
  it,
  expect,
  vi,
  beforeAll,
  beforeEach,
  afterEach,
} from "vitest";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

import { __resetLangForTests } from "@/lib/i18n/LangContext";
import { listOpenCases, type CaseDetailView } from "@/lib/care/api";
import {
  fetchDoctorProfile,
  fetchDoctorProfilePhoto,
  type DoctorProfileView,
} from "@/lib/doctor/api";
import * as axe from "axe-core";

import { AppShell } from "./AppShell";
import { maskedPhone } from "./BottomTabs";
import { DoctorProfileProvider } from "@/lib/doctor/DoctorProfileContext";
import {
  ProfileProvider,
  useOptionalProfile,
} from "@/lib/profile/ProfileContext";
import type { StoredPatientProfile } from "@/lib/profile/api";
import type { Role } from "./types";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockPathname = vi.fn();

vi.mock("next/navigation", () => ({
  usePathname: () => mockPathname(),
}));

vi.mock("next/link", () => ({
  default({
    href,
    children,
    ...props
  }: {
    href: string;
    children: React.ReactNode;
    [key: string]: unknown;
  }) {
    return (
      <a href={href} {...props}>
        {children}
      </a>
    );
  },
}));

const switchRole = vi.fn();
const logout = vi.fn();

// #557: mutable so a test can put the account menu in its patient branch (the
// shell's own role comes from the role prop, not from the session's choice).
// #567: `roles` is mutable too, so a test can hand the menu a session the
// backend would actually build. Forcing `selectedRole` to a value the session's
// own roles array does not contain is a payload /me never issues, which is the
// same class of fabricated fixture that hid the doctor branch.
const authState = vi.hoisted(() => ({
  selectedRole: "operator",
  roles: ["patient", "operator"],
}));

vi.mock("@/lib/auth/AuthContext", () => ({
  useAuth: () => ({
    user: { id: 1, phone: "+911234567890", roles: authState.roles },
    selectedRole: authState.selectedRole,
    switchRole,
    logout,
    isAuthenticated: true,
    isLoading: false,
  }),
}));

// #525: the patient account card reads the saved name/photo through the
// profile seam; mocked at the module boundary like the ProfileContext suites
// so the named-card branch can hydrate without HTTP. #557 adds the photo-byte
// read behind the same seam.
const profileApi = vi.hoisted(() => ({
  getProfile: vi.fn(),
  saveProfile: vi.fn(),
  fetchPatientPhoto: vi.fn(),
}));

vi.mock("@/lib/profile/api", () => ({
  getProfile: profileApi.getProfile,
  saveProfile: profileApi.saveProfile,
  fetchPatientPhoto: profileApi.fetchPatientPhoto,
}));

// PHASE-8.1 T8 (#483): the doctor shell's Cases count pill reads the existing
// open-cases feed; the whole care module is mocked so shell tests stay unit
// scoped.
vi.mock("@/lib/care/api", () => ({
  listOpenCases: vi.fn(),
}));

const getOpenCases = vi.mocked(listOpenCases);

// #569/#583: the doctor profile projection and the bytes behind its avatar. The
// read itself moved into the shared DoctorProfileProvider (#583), which the
// (doctor) route-group layout mounts above this shell; the whole doctor module
// is mocked for the same unit-scoped reason as the care module above.
vi.mock("@/lib/doctor/api", () => ({
  fetchDoctorProfile: vi.fn(),
  fetchDoctorProfilePhoto: vi.fn(),
}));

const getDoctorProfile = vi.mocked(fetchDoctorProfile);
const getDoctorPhoto = vi.mocked(fetchDoctorProfilePhoto);

// #569: the projection the shared doctor profile source hydrates from.
// `photo_ref` is an opaque object key in the doctor's own namespace
// (ADR-0020 D1) and `practice_name` is the only human-readable name a doctor
// has anywhere in the frontend, which is why the source takes the whole view.
function doctorProfileWith(photoRef: string | null): DoctorProfileView {
  return {
    partner_id: 7,
    photo_ref: photoRef,
    practice_name: "Asha Clinic",
    clinic_name: null,
    specialties: ["General"],
    verified: true,
    practice_address: "1 Clinic Road",
    address_line: "1 Clinic Road",
    landmark: null,
    locality: "Indiranagar",
    city: "Bengaluru",
    pin_code: "560038",
    practice_latitude: 12.97,
    practice_longitude: 77.59,
    area: "Indiranagar",
    languages: ["en"],
    experience_years: 9,
    about: null,
    consultation_fee: 400,
    consulting_days: [],
    consulting_hours: null,
    credentials: [],
    notification_preferences: {},
  };
}

// #525: a hydrated patient profile, shared by the named-card and #557 cases.
const NAMED_PROFILE: StoredPatientProfile = {
  name: "Asha Rao",
  age: 34,
  gender: "female",
  preferred_language: "en",
  area: null,
  emergency_contact: null,
  photo_ref: null,
};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

// Radix popper relies on ResizeObserver and opens menus on real pointer
// events, neither of which jsdom implements fully. Only the #557 account-menu
// test needs them; vitest isolates each test file in its own jsdom.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}

beforeAll(() => {
  window.ResizeObserver =
    window.ResizeObserver ??
    (ResizeObserverStub as unknown as typeof ResizeObserver);
  if (!window.PointerEvent) {
    class PointerEventStub extends MouseEvent {}
    window.PointerEvent = PointerEventStub as unknown as typeof PointerEvent;
  }
});

// #557: the only thing that moves a stored photo ref is the context's
// syncPhotoRef, so a replace is driven through the real context. This suite
// keeps its own fixture rather than sharing one - the repo has no shared
// test-helper module, and only the replace is needed here.
function PhotoRefControls() {
  const profile = useOptionalProfile();
  return (
    <button
      type="button"
      data-testid="replace-photo"
      onClick={() => profile?.syncPhotoRef("patient/7/photo-2.enc")}
    >
      replace
    </button>
  );
}

// #557: the <img> a surface ends up showing. Asserting inside waitFor is what
// makes it retry - a bare querySelector returns null and resolves immediately.
async function imageIn(root: ParentNode): Promise<HTMLImageElement> {
  return waitFor(() => {
    const img = root.querySelector("img");
    expect(img).not.toBeNull();
    return img;
  }).then((el) => el as HTMLImageElement);
}

// #557: object-URL plumbing for the shared photo resolver, which jsdom does
// not implement. A distinct URL per call, so a test can tell which generation
// of the photo a surface is showing.
let originalCreate: typeof URL.createObjectURL;
let originalRevoke: typeof URL.revokeObjectURL;
let photoUrls: number;

beforeEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
  __resetLangForTests();
  mockPathname.mockReturnValue("/patient");
  getOpenCases.mockResolvedValue([]);
  authState.selectedRole = "operator";
  authState.roles = ["patient", "operator"];
  // #525: default the profile read to "absent" so the masked-phone fallback
  // is the steady state; the named-profile branch re-seeds it per test.
  profileApi.getProfile.mockReset();
  profileApi.getProfile.mockResolvedValue({ set: false, profile: null });
  photoUrls = 0;
  originalCreate = URL.createObjectURL;
  originalRevoke = URL.revokeObjectURL;
  URL.createObjectURL = vi.fn(
    () => `blob:http://localhost/photo-${(photoUrls += 1)}`,
  ) as unknown as typeof URL.createObjectURL;
  URL.revokeObjectURL = vi.fn() as unknown as typeof URL.revokeObjectURL;
  profileApi.fetchPatientPhoto.mockResolvedValue(
    new Blob(["photo-bytes"], { type: "image/png" }),
  );
  // #569: the doctor feeds default to a projection with no photo, so the
  // person-icon disc is the steady state; the hydrated case re-seeds the ref.
  getDoctorProfile.mockReset();
  getDoctorProfile.mockResolvedValue(doctorProfileWith(null));
  getDoctorPhoto.mockReset();
  getDoctorPhoto.mockResolvedValue(
    new Blob(["doctor-photo-bytes"], { type: "image/png" }),
  );
});

afterEach(() => {
  // Unmounting drops the resolver's cache entry, so it has to happen before the
  // stubs come back - otherwise a live entry survives into the next test.
  cleanup();
  URL.createObjectURL = originalCreate;
  URL.revokeObjectURL = originalRevoke;
});

describe("AppShell light density (patient)", () => {
  it("never renders a sidebar at any width - topbar carries the desktop top-nav", () => {
    render(
      <AppShell role="patient">
        <h1>Patient home</h1>
      </AppShell>,
    );

    expect(screen.queryByTestId("sidebar")).not.toBeInTheDocument();
    expect(screen.getByTestId("topbar")).toHaveAttribute(
      "data-density",
      "light",
    );
    expect(screen.getByTestId("topnav")).toBeInTheDocument();
    // #501: the location chip mounts inside the desktop light top bar.
    expect(
      within(screen.getByTestId("topbar")).getByTestId("location-chip-topbar"),
    ).toBeInTheDocument();
    expect(screen.getByTestId("app-shell")).toHaveAttribute(
      "data-density",
      "light",
    );
  });

  it("derives the desktop top-nav from the patient nav-config, minus the center slot", () => {
    render(
      <AppShell role="patient">
        <h1>Patient home</h1>
      </AppShell>,
    );

    const topnav = screen.getByTestId("topnav");
    expect(topnav).toHaveTextContent("Home");
    expect(topnav).toHaveTextContent("Find Care");
    expect(topnav).toHaveTextContent("My Record");
    expect(topnav).toHaveTextContent("Inbox");
    // Start Visit lives only in the center accent column of the tab bar;
    // Profile & Settings stays in the More sheet / account cluster.
    expect(topnav).not.toHaveTextContent("Start");
    expect(topnav.textContent).toContain("Bookings & Orders");
    expect(topnav.textContent).toContain("Soon");
    expect(topnav.textContent).not.toContain("Profile & Settings");
    // PHASE-3 T7 (#216) un-sooned My Record: it renders as a live link on
    // every surface via the single source.
    expect(screen.getByTestId("nav-record")).toHaveAttribute(
      "href",
      "/patient/record",
    );
    // PHASE-8.1 T11 (#485): Inbox is coming-soon until Phase 13, so the
    // top-nav renders it (and Bookings) as dimmed non-interactive spans -
    // never a navigation to a dead page.
    expect(screen.getByTestId("nav-inbox")).toHaveAttribute(
      "data-soon",
      "true",
    );
    expect(screen.getByTestId("nav-inbox").tagName).toBe("SPAN");
    expect(screen.getByTestId("nav-bookings")).toHaveAttribute(
      "data-soon",
      "true",
    );
    // The finalized view also carries the language switch in this cluster.
    expect(screen.getByTestId("lang-toggle")).toBeInTheDocument();
  });

  it("renders Soon entries dimmed and non-interactive", () => {
    render(
      <AppShell role="patient">
        <h1>Patient home</h1>
      </AppShell>,
    );

    const bookings = screen.getByTestId("nav-bookings");
    expect(bookings.tagName).toBe("SPAN");
    expect(bookings).toHaveAttribute("aria-disabled", "true");

    const inbox = screen.getByTestId("nav-inbox");
    expect(inbox.tagName).toBe("SPAN");
    expect(inbox).toHaveAttribute("aria-disabled", "true");
  });

  it("marks the live destination matching the pathname as current", () => {
    render(
      <AppShell role="patient">
        <h1>Patient home</h1>
      </AppShell>,
    );

    expect(screen.getByTestId("nav-home")).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it("carries the five-column bottom bar with Start Visit pinned as the center accent", () => {
    render(
      <AppShell role="patient">
        <h1>Patient home</h1>
      </AppShell>,
    );

    const bar = screen.getByTestId("bottom-tabs");
    expect(bar.className).toContain("lg:hidden");

    const keys = ["home", "find", "start", "record"];
    keys.forEach((key) =>
      expect(screen.getByTestId(`tab-${key}`)).toBeInTheDocument(),
    );
    // Ratified five columns (#210): Home | Find | Start(center) | Record |
    // More - exactly five children, no sixth Inbox column.
    expect(screen.queryByTestId("tab-inbox")).not.toBeInTheDocument();
    expect(
      Array.from(bar.children).map((child) =>
        child.getAttribute("data-testid"),
      ),
    ).toEqual([
      "tab-home",
      "tab-find",
      "tab-start",
      "tab-record",
      "more-trigger",
    ]);
    // The center accent renders as a circular accent FAB inside its column.
    expect(
      screen
        .getByTestId("tab-start")
        .querySelector("span.rounded-full.bg-accent"),
    ).not.toBeNull();
    // PHASE-3 T7 (#216) un-sooned My Record: the tab column is a live link.
    expect(screen.getByTestId("tab-record")).toHaveAttribute(
      "href",
      "/patient/record",
    );
  });

  it("moves overflow destinations into the More sheet - Profile & Settings live, rest Soon", () => {
    render(
      <AppShell role="patient">
        <h1>Patient home</h1>
      </AppShell>,
    );

    expect(screen.queryByTestId("more-sheet")).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId("more-trigger"));

    const sheet = screen.getByTestId("more-sheet");
    expect(sheet).toHaveTextContent("Inbox");
    expect(sheet).toHaveTextContent("Bookings & Orders");
    expect(sheet).toHaveTextContent("Profile & Settings");

    // Inbox and Bookings stay coming-soon (#485): dimmed non-interactive
    // spans, so neither navigates to a dead page.
    for (const testid of ["more-inbox", "more-bookings"]) {
      expect(screen.getByTestId(testid).tagName).toBe("SPAN");
      expect(screen.getByTestId(testid)).toHaveAttribute(
        "aria-disabled",
        "true",
      );
    }
    // #524: Profile & Settings is a live, tappable row pointing at the real
    // route - no Soon badge, no aria-disabled.
    const profile = screen.getByTestId("more-profile-settings");
    expect(profile.tagName).toBe("A");
    expect(profile).toHaveAttribute("href", "/patient/profile");
    expect(profile).not.toHaveAttribute("aria-disabled");
    expect(within(sheet).getAllByTestId("soon-badge")).toHaveLength(2);
  });

  it("closes the More sheet when a live overflow row navigates (#524)", async () => {
    render(
      <AppShell role="patient">
        <h1>Patient home</h1>
      </AppShell>,
    );

    fireEvent.click(screen.getByTestId("more-trigger"));
    expect(screen.getByTestId("more-sheet")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("more-profile-settings"));

    await waitFor(() =>
      expect(screen.queryByTestId("more-sheet")).not.toBeInTheDocument(),
    );
  });

  it("renders nav labels bilingually through the i18n engine", () => {
    localStorage.setItem("caresetu.lang", "hi");
    render(
      <AppShell role="patient">
        <h1>Patient home</h1>
      </AppShell>,
    );

    expect(screen.getByTestId("tab-home")).toHaveTextContent("होम");
    expect(screen.getByTestId("tab-start")).toHaveTextContent("शुरू करें");
    expect(screen.getByTestId("nav-home")).toHaveTextContent("होम");
  });
});

describe("AppShell patient mobile account surface (#525)", () => {
  function renderPatient() {
    return render(
      <AppShell role="patient">
        <h1>Patient home</h1>
      </AppShell>,
    );
  }

  function openMore() {
    fireEvent.click(screen.getByTestId("more-trigger"));
    return screen.getByTestId("more-sheet");
  }

  it("puts the account card above the overflow rows in the More sheet", () => {
    renderPatient();
    const sheet = openMore();

    const card = within(sheet).getByTestId("more-account-card");
    const rows = Array.from(sheet.querySelectorAll('[data-testid^="more-"]'));
    expect(rows[0]).toBe(card);
    // The #524 overflow destinations still follow unchanged.
    expect(screen.getByTestId("more-inbox")).toBeInTheDocument();
    expect(screen.getByTestId("more-profile-settings")).toBeInTheDocument();
  });

  it("falls back to the masked phone and shows the full E.164 plus Profile & Settings", async () => {
    renderPatient();
    openMore();

    expect(screen.getByTestId("more-account-identity")).toHaveTextContent(
      "+91 XXXXXX7890",
    );
    expect(screen.getByTestId("more-account-card")).toHaveTextContent(
      "+911234567890",
    );
    expect(screen.getByTestId("more-account-card")).toHaveTextContent(
      "Profile & Settings",
    );
    // No saved profile yet, so the shared Avatar degrades to the person icon.
    expect(
      screen.getByTestId("more-account-card").querySelector("svg"),
    ).not.toBeNull();
  });

  it("shows the saved name and its initial once profile hydration lands", async () => {
    profileApi.getProfile.mockResolvedValue({
      set: true,
      profile: NAMED_PROFILE,
    });

    render(
      <ProfileProvider>
        <AppShell role="patient">
          <h1>Patient home</h1>
        </AppShell>
      </ProfileProvider>,
    );
    await waitFor(() => expect(profileApi.getProfile).toHaveBeenCalled());
    openMore();

    expect(screen.getByTestId("more-account-identity")).toHaveTextContent(
      "Asha Rao",
    );
    // The shared Avatar's name-initial fallback ("A") for the unnamed photo.
    expect(screen.getByTestId("more-account-card")).toHaveTextContent("A");
  });

  // #557: the card's avatar used to be handed the stored photo ref directly,
  // which the primitive can only reject as unrenderable - so a saved photo never
  // showed on the phone at all. The ref now goes through the one shared
  // resolver and the card receives a renderable source.
  it("#557 renders the account card's stored photo as a renderable source", async () => {
    profileApi.getProfile.mockResolvedValue({
      set: true,
      profile: { ...NAMED_PROFILE, photo_ref: "patient/7/photo-1.enc" },
    });

    render(
      <ProfileProvider>
        <AppShell role="patient">
          <h1>Patient home</h1>
        </AppShell>
      </ProfileProvider>,
    );
    await waitFor(() => expect(profileApi.getProfile).toHaveBeenCalled());
    const card = openMore();

    const img = await imageIn(card);
    expect(img.getAttribute("src")).toMatch(/^blob:/);
    // The stored ref is an opaque key: it is never a URL the browser can reach.
    expect(img.getAttribute("src")).not.toContain("photo-1.enc");
    // One read answers this card. (The session is on the staff role here, so the
    // topbar disc above it shows phone digits and asks for nothing - the shared
    // cache across surfaces is proved by the next test.)
    expect(profileApi.fetchPatientPhoto).toHaveBeenCalledTimes(1);
  });

  // The three chrome avatars are three views of one photo, so the ref-keyed
  // cache is what keeps opening the account surfaces snappy. The patient shell
  // carries all three at once: the topbar account trigger, the identity header
  // behind it, and the More-sheet account card. Counting requests is the only
  // assertion that would notice three per-consumer fetches.
  it("#557 the desktop trigger, the identity header and the account card read one ref once", async () => {
    authState.selectedRole = "patient";
    profileApi.getProfile.mockResolvedValue({
      set: true,
      profile: { ...NAMED_PROFILE, photo_ref: "patient/7/photo-1.enc" },
    });

    render(
      <ProfileProvider>
        <AppShell role="patient">
          <h1>Patient home</h1>
        </AppShell>
        <PhotoRefControls />
      </ProfileProvider>,
    );
    await waitFor(() => expect(profileApi.getProfile).toHaveBeenCalled());

    const trigger = screen.getByTestId("account-menu");
    const triggerImg = await imageIn(trigger);
    fireEvent.keyDown(trigger, { key: "Enter" });
    // Read the identity header before the More sheet opens: opening a sheet
    // dismisses the open dropdown, so the two overlays are not both up at once.
    await waitFor(() => expect(screen.getByRole("menu")).toBeInTheDocument());
    const headerImg = await imageIn(screen.getByRole("menu"));
    const card = openMore();
    const cardImg = await imageIn(card);

    for (const img of [triggerImg, headerImg, cardImg]) {
      expect(img.getAttribute("src")).toMatch(/^blob:/);
    }
    // Three avatars, one stored ref, one request - not one per surface.
    expect(profileApi.fetchPatientPhoto).toHaveBeenCalledTimes(1);

    // A replace moves every surface off the old bytes, on both seams at once:
    // one new read for the new ref, and nothing left showing the previous one.
    // Which consumer gets which object URL is not pinned - they are per
    // consumer - but none of them may keep the old one.
    const beforeTrigger = triggerImg.getAttribute("src");
    const beforeCard = cardImg.getAttribute("src");
    fireEvent.click(screen.getByTestId("replace-photo"));
    await waitFor(() => {
      const moved = trigger.querySelector("img")?.getAttribute("src");
      const movedCard = card.querySelector("img")?.getAttribute("src");
      expect(moved).toMatch(/^blob:/);
      expect(movedCard).toMatch(/^blob:/);
      expect(moved).not.toBe(beforeTrigger);
      expect(movedCard).not.toBe(beforeCard);
    });
    expect(profileApi.fetchPatientPhoto).toHaveBeenCalledTimes(2);
  });

  it("closes the More sheet when the account card navigates", async () => {
    renderPatient();
    openMore();

    expect(screen.getByTestId("more-account-card")).toHaveAttribute(
      "href",
      "/patient/profile",
    );
    fireEvent.click(screen.getByTestId("more-account-card"));
    await waitFor(() =>
      expect(screen.queryByTestId("more-sheet")).not.toBeInTheDocument(),
    );
  });

  it("renders a red Log out row that ends the session and closes the sheet", async () => {
    logout.mockClear();
    renderPatient();
    openMore();

    const logoutRow = screen.getByTestId("more-logout");
    expect(logoutRow).toHaveTextContent("Log out");
    expect(logoutRow.className).toContain("text-danger");

    fireEvent.click(logoutRow);

    expect(logout).toHaveBeenCalledTimes(1);
    await waitFor(() =>
      expect(screen.queryByTestId("more-sheet")).not.toBeInTheDocument(),
    );
  });

  it("keeps the open More sheet axe-clean (labels, landmarks, contrast)", async () => {
    renderPatient();
    const sheet = openMore();

    const { violations } = await axe.run(sheet);
    expect(violations).toEqual([]);
  });

  it("keeps staff bubbles free of the mobile account entirely", () => {
    mockPathname.mockReturnValue("/doctor");
    render(
      <AppShell role="doctor">
        <h1>Workspace</h1>
      </AppShell>,
    );

    // Doctor nav fits four columns (queue/cases/patients/profile), so the
    // staff bottom bar has no More trigger - and no account/logout rows to
    // hide behind it. The patient-only account surface cannot leak here.
    expect(screen.queryByTestId("more-trigger")).not.toBeInTheDocument();
    expect(screen.queryByTestId("more-account-card")).not.toBeInTheDocument();
    expect(screen.queryByTestId("more-logout")).not.toBeInTheDocument();
  });
});

describe("maskedPhone (#525)", () => {
  it("masks an E.164 number to the spec format +91 XXXXXX1234", () => {
    expect(maskedPhone("+911234567890")).toBe("+91 XXXXXX7890");
  });

  it("strips formatting noise before masking", () => {
    expect(maskedPhone("+91 12345 67890")).toBe("+91 XXXXXX7890");
  });

  it("renders values too short to be E.164 verbatim", () => {
    expect(maskedPhone("+91123")).toBe("+91123");
    expect(maskedPhone("")).toBe("");
  });
});

// One full-density render for every suite: the shell plus a neutral child, on
// the role's own pathname so nav-config's active highlighting is real.
function renderShell(role: Role, pathname = `/${role}`) {
  mockPathname.mockReturnValue(pathname);
  return render(
    <AppShell role={role}>
      <h1>Workspace</h1>
    </AppShell>,
  );
}

describe.each(["doctor", "partner", "operator"] as const)(
  "AppShell full density (%s)",
  (role) => {
    function setup() {
      return renderShell(role);
    }

    it("shows a collapsible sidebar plus topbar, with bottom tabs for phones", () => {
      setup();

      const sidebar = screen.getByTestId("sidebar");
      expect(sidebar).toBeInTheDocument();
      // Responsiveness is CSS-driven: removed from layout below lg entirely.
      expect(sidebar.className).toContain("hidden");
      expect(sidebar.className).toContain("lg:flex");
      expect(screen.getByTestId("topbar-page-slot")).toBeInTheDocument();
      expect(screen.getByTestId("bottom-tabs")).toBeInTheDocument();
    });

    it("renders the role's nav-config entries with active highlighting", () => {
      setup();

      const expected = {
        doctor: ["queue", "cases", "patients", "profile"],
        partner: ["orders", "history", "settlements", "profile"],
        operator: ["home", "verifications", "disputes", "audit"],
      }[role];

      expected.forEach((key) => {
        expect(screen.getByTestId(`nav-${key}`)).toBeInTheDocument();
        expect(screen.getByTestId(`tab-${key}`)).toBeInTheDocument();
      });
      expect(screen.getByTestId(`nav-${expected[0]}`)).toHaveAttribute(
        "aria-current",
        "page",
      );
    });

    it("keeps staff secondary entries dimmed, non-interactive, and badged", () => {
      setup();

      const soonItems = screen
        .getAllByTestId(/^nav-/)
        .filter((el) => el.getAttribute("data-soon") === "true");
      // #543: the doctor console carries no coming-soon row any more - queue,
      // cases, patients and profile all have live pages - so the dimmed-row
      // contract now only applies to the roles that still have one.
      if (role === "doctor") {
        expect(soonItems).toHaveLength(0);
        expect(screen.queryAllByTestId("soon-badge")).toHaveLength(0);
        return;
      }
      expect(soonItems.length).toBeGreaterThan(0);
      for (const item of soonItems) {
        expect(item).toHaveAttribute("aria-disabled", "true");
        expect(item.tagName).toBe("SPAN");
      }
      expect(screen.getAllByTestId("soon-badge").length).toBe(soonItems.length);
    });
  },
);

// #567: the whole thread, end to end, with no prop hand-fed at any step. The
// doctor shell knows its own role (its route group pins it), so the account
// menu inherits it - which is the only way a doctor-only affordance can be
// reachable at all, since a doctor's session role is `partner`.
describe("AppShell supplies its role to the account menu (#567)", () => {
  // A production-shaped doctor session: the grants table issues no "doctor"
  // role, so /me answers a doctor with a single `partner` role and doctor-ness
  // is the partner's type - which is precisely what the shell already encodes.
  // Byte-identical for both halves below, so the only variable is the shell.
  function renderDoctorSessionShell(role: Role) {
    authState.roles = ["partner"];
    authState.selectedRole = "partner";
    return renderShell(role);
  }

  it("renders the doctor affordances inside the doctor shell", async () => {
    renderDoctorSessionShell("doctor");

    const trigger = screen.getByTestId("account-menu");
    // The doctor's person-icon disc, not the phone digits a lab partner gets.
    expect(trigger).not.toHaveTextContent("90");
    expect(trigger.querySelector("svg")).not.toBeNull();

    fireEvent.keyDown(trigger, { key: "Enter" });
    await waitFor(() => expect(screen.getByRole("menu")).toBeInTheDocument());
    expect(screen.getByTestId("account-menu-doctor-profile")).toHaveAttribute(
      "href",
      "/doctor/profile",
    );
  });

  it("keeps the same session's staff treatment inside the partner shell", async () => {
    // Same session, different shell: the partner shell owes the phone-digit
    // trigger, so the answer is the shell's, never the session's.
    renderDoctorSessionShell("partner");

    const trigger = screen.getByTestId("account-menu");
    expect(trigger).toHaveTextContent("90");
    fireEvent.keyDown(trigger, { key: "Enter" });
    await waitFor(() => expect(screen.getByRole("menu")).toBeInTheDocument());
    expect(screen.queryByTestId("account-menu-doctor-profile")).toBeNull();
  });
});

describe("AppShell doctor Cases count pill (PHASE-8.1 T8, #483)", () => {
  function openCase(id: number) {
    return {
      case_id: id,
      patient_id: 3,
      doctor_id: 7,
      pre_summary_id: 5,
      stage: "prescription_pending",
      forced_review: false,
      closed_at: null,
      close_reason: null,
      created_at: "2026-09-12T10:00:00Z",
      updated_at: "2026-09-12T10:00:00Z",
    } as CaseDetailView;
  }

  function renderDoctor() {
    mockPathname.mockReturnValue("/doctor");
    return render(
      <AppShell role="doctor">
        <h1>Workspace</h1>
      </AppShell>,
    );
  }

  it("renders the Cases tab as a live link with the open-cases count pill", async () => {
    getOpenCases.mockResolvedValue([openCase(11), openCase(12)]);
    renderDoctor();

    await waitFor(() =>
      expect(screen.getByTestId("nav-cases")).toHaveAttribute(
        "href",
        "/doctor/cases",
      ),
    );
    expect(screen.getByTestId("nav-cases").tagName).toBe("A");
    expect(
      within(screen.getByTestId("nav-cases")).getByTestId("count-pill"),
    ).toHaveTextContent("2");
    // The phone tab bar carries the same count badge (same config entry).
    expect(
      within(screen.getByTestId("tab-cases")).getByTestId("count-pill"),
    ).toHaveTextContent("2");
  });

  it("marks the Cases tab current when on /doctor/cases", async () => {
    mockPathname.mockReturnValue("/doctor/cases");
    getOpenCases.mockResolvedValue([openCase(11)]);
    render(
      <AppShell role="doctor">
        <h1>Workspace</h1>
      </AppShell>,
    );

    await waitFor(() =>
      expect(screen.getByTestId("nav-cases")).toHaveAttribute(
        "aria-current",
        "page",
      ),
    );
    expect(screen.getByTestId("tab-cases")).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it("shows no count pill when there are no open cases", async () => {
    getOpenCases.mockResolvedValue([]);
    renderDoctor();

    await waitFor(() =>
      expect(screen.getByTestId("nav-cases")).toHaveAttribute(
        "href",
        "/doctor/cases",
      ),
    );
    expect(screen.queryByTestId("count-pill")).not.toBeInTheDocument();
  });

  it("shows no count pill when the cases feed fails", async () => {
    getOpenCases.mockRejectedValue(new Error("boom"));
    renderDoctor();

    await waitFor(() =>
      expect(screen.getByTestId("nav-cases")).toHaveAttribute(
        "href",
        "/doctor/cases",
      ),
    );
    expect(screen.queryByTestId("count-pill")).not.toBeInTheDocument();
  });

  it("links doctor Patients and Profile live (#541, #543)", async () => {
    renderDoctor();

    await waitFor(() =>
      expect(screen.getByTestId("nav-cases")).toHaveAttribute(
        "href",
        "/doctor/cases",
      ),
    );
    // #541: Patients un-sooned - /doctor/patients is a real page, so the
    // nav entry renders as a live link on every surface (sidebar + tab bar).
    expect(screen.getByTestId("nav-patients")).toHaveAttribute(
      "href",
      "/doctor/patients",
    );
    expect(screen.getByTestId("nav-patients").tagName).toBe("A");
    expect(screen.getByTestId("nav-patients")).not.toHaveAttribute("data-soon");
    // The same config entry drives the phone tab bar (#541): Patients now
    // renders as a live bottom tab, without regressing the other doctor tabs.
    expect(screen.getByTestId("tab-patients")).toHaveAttribute(
      "href",
      "/doctor/patients",
    );
    expect(screen.getByTestId("tab-patients").tagName).toBe("A");
    expect(screen.getByTestId("tab-patients")).not.toHaveAttribute("data-soon");
    // #543: Profile un-sooned - /doctor/profile is the live private profile
    // projection plus the fee editor, so it links on the sidebar and the
    // phone tab bar like the other real doctor destinations.
    expect(screen.getByTestId("nav-profile")).toHaveAttribute(
      "href",
      "/doctor/profile",
    );
    expect(screen.getByTestId("nav-profile").tagName).toBe("A");
    expect(screen.getByTestId("nav-profile")).not.toHaveAttribute("data-soon");
    expect(screen.getByTestId("tab-profile")).toHaveAttribute(
      "href",
      "/doctor/profile",
    );
    expect(screen.getByTestId("tab-profile").tagName).toBe("A");
    expect(screen.getByTestId("tab-profile")).not.toHaveAttribute("data-soon");
  });
});

// #583: the doctor account avatar in the shell chrome, fed by the shared doctor
// profile source the (doctor) route-group layout mounts above the shell. The
// shell no longer reads the projection and holds no identity data at all, so
// what is left here is the end-to-end property of one whole render: the source's
// one read hydrates the disc, both avatars share one byte read, a failed read
// degrades to the person icon, and a shell with no provider mounted - every
// partner and operator shell - starts no read at all.
//
// The read's own contract (one read per visit, the identity-keyed remount, the
// exact degrade warning, the adopt seam) belongs to the source's own suite; the
// source-shape pin that used to assert on AppShell.tsx's own text moved there
// with it. The cross-surface suite is what proves the chrome and the Profile
// page cannot disagree.
describe("AppShell renders the doctor account avatar from the shared source (#583)", () => {
  // The doctor shell is the one shell whose layout mounts the source, so it is
  // the only render here that wraps it. The other roles deliberately do not.
  function renderShellFor(role: Role) {
    // A production-shaped doctor session: one `partner` role, doctor-ness from
    // the shell alone.
    authState.roles = ["partner"];
    authState.selectedRole = "partner";
    mockPathname.mockReturnValue(`/${role}`);
    const shell = (
      <AppShell role={role}>
        <h1>Workspace</h1>
      </AppShell>
    );
    return render(
      role === "doctor" ? (
        <DoctorProfileProvider>{shell}</DoctorProfileProvider>
      ) : (
        shell
      ),
    );
  }

  it("hydrates the disc from the shared source's one read", async () => {
    getDoctorProfile.mockResolvedValue(
      doctorProfileWith("doctor/7/photo-1.enc"),
    );
    renderShellFor("doctor");

    const trigger = screen.getByTestId("account-menu");
    const img = await imageIn(trigger);
    expect(img.getAttribute("src")).toMatch(/^blob:/);
    // The stored key is opaque and never browser-reachable (ADR-0020 D1), so a
    // src that carried it would be the whole defect back.
    expect(img.getAttribute("src")).not.toContain("doctor/7/photo-1.enc");
    // One read for this whole render - not one for the shell and another for the
    // source, and not a second read to get the practice name. The shell adds
    // none, so the count is exactly the source's.
    expect(getDoctorProfile).toHaveBeenCalledTimes(1);
    expect(getDoctorPhoto).toHaveBeenCalledTimes(1);
  });

  it("shares the one byte read with the dropdown header's avatar", async () => {
    getDoctorProfile.mockResolvedValue(
      doctorProfileWith("doctor/7/photo-1.enc"),
    );
    renderShellFor("doctor");

    const trigger = screen.getByTestId("account-menu");
    const triggerImg = await imageIn(trigger);

    fireEvent.keyDown(trigger, { key: "Enter" });
    await waitFor(() => expect(screen.getByRole("menu")).toBeInTheDocument());
    const headerImg = await imageIn(screen.getByRole("menu"));
    expect(headerImg.getAttribute("src")).toBe(triggerImg.getAttribute("src"));
    // Two avatars, one ref, one request - the menu opened and nothing was
    // re-read.
    expect(getDoctorPhoto).toHaveBeenCalledTimes(1);
    expect(getDoctorProfile).toHaveBeenCalledTimes(1);
  });

  it("degrades a failed profile read to the person icon, silently and visibly logged", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    getDoctorProfile.mockRejectedValue(new Error("profile feed down"));
    renderShellFor("doctor");

    // Let the rejection settle before asserting the degrade, or this would pass
    // on a feed that has not answered yet. The exact warning prefix is the
    // source's own suite to pin, now that the read lives in its module.
    await waitFor(() => expect(warn).toHaveBeenCalled());
    const trigger = screen.getByTestId("account-menu");
    expect(trigger).not.toHaveTextContent("90");
    expect(trigger.querySelector("svg")).not.toBeNull();
    expect(trigger.querySelector("img")).toBeNull();
    // A chrome avatar that cannot resolve is not a broken one, and it costs no
    // byte read: there is no ref to ask for.
    expect(getDoctorPhoto).not.toHaveBeenCalled();
  });

  // The read is scoped structurally, not by a runtime role check: the source
  // mounts only in the (doctor) group layout, so a partner or operator shell has
  // no provider at all and the account menu's optional accessor yields null.
  // There is no code path in which one of them can start a doctor read.
  it("reads no doctor profile on the other shells", async () => {
    for (const role of ["patient", "partner", "operator"] as const) {
      const { unmount } = renderShellFor(role);
      await waitFor(() =>
        expect(screen.getByTestId("app-shell")).toBeVisible(),
      );
      unmount();
    }

    expect(getDoctorProfile).not.toHaveBeenCalled();
    expect(getDoctorPhoto).not.toHaveBeenCalled();
  });
});

describe("full-shell collapse preference persistence", () => {
  function renderOperator() {
    mockPathname.mockReturnValue("/operator");
    return render(
      <AppShell role="operator">
        <h1>Operator</h1>
      </AppShell>,
    );
  }

  it("defaults expanded, collapses on toggle, and persists per role", () => {
    const { unmount } = renderOperator();

    const sidebar = screen.getByTestId("sidebar");
    expect(sidebar.getAttribute("data-collapsed")).toBeNull();
    expect(sidebar.className).toContain("w-52");

    fireEvent.click(screen.getByTestId("sidebar-toggle"));

    expect(sidebar.getAttribute("data-collapsed")).toBe("true");
    expect(sidebar.className).toContain("w-16");
    expect(localStorage.getItem("caresetu.sidebar.operator")).toBe("collapsed");
    unmount();
  });

  it("adopts the stored preference on the next visit", () => {
    localStorage.setItem("caresetu.sidebar.operator", "collapsed");
    renderOperator();

    const sidebar = screen.getByTestId("sidebar");
    expect(sidebar.getAttribute("data-collapsed")).toBe("true");
    expect(sidebar.className).toContain("w-16");
  });

  it("keeps preferences independent between roles", () => {
    localStorage.setItem("caresetu.sidebar.operator", "collapsed");
    mockPathname.mockReturnValue("/partner");
    render(
      <AppShell role="partner">
        <h1>Partner</h1>
      </AppShell>,
    );

    // The partner shell ignores the operator's stored choice and starts
    // expanded, persisting its own default under its own key.
    expect(localStorage.getItem("caresetu.sidebar.partner")).toBe("expanded");
    expect(screen.getByTestId("sidebar").className).toContain("w-52");
  });

  it("labels toggle accessibly in both states", () => {
    const { unmount } = renderOperator();

    const toggle = screen.getByTestId("sidebar-toggle");
    expect(toggle).toHaveAttribute("aria-label", "Collapse sidebar");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-label", "Expand sidebar");
    unmount();
  });
});

describe("retired icon-rail / matchMedia mechanics", () => {
  const dashboardDir = join(__dirname);

  function dashboardSources(): string[] {
    return readdirSync(dashboardDir)
      .filter(
        (name) =>
          /\.(tsx|ts)$/.test(name) &&
          !name.endsWith(".test.tsx") &&
          !name.endsWith(".test.ts"),
      )
      .map((name) => readFileSync(join(dashboardDir, name), "utf8"));
  }

  it("no dashboard shell code consults matchMedia any more", () => {
    for (const source of dashboardSources()) {
      expect(source).not.toMatch(/matchMedia/);
    }
  });

  // PHASE-2.6 T07 (#198): the generic dashboard group split into per-role
  // route groups - each group layout pins one fixed role into the shared
  // AppShell instead of resolving it from the session.
  it("each per-role group layout wires its role through AppShell", () => {
    const roles = ["patient", "doctor", "partner", "operator"] as const;
    for (const role of roles) {
      const layout = readFileSync(
        join(__dirname, `../../app/(${role})/layout.tsx`),
        "utf8",
      );
      expect(layout).toContain("<AppShell");
      expect(layout).toContain(`role="${role}"`);
    }
  });
});
