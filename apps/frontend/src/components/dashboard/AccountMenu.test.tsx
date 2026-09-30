// PHASE-2.6 T08 (#199): dedicated accessibility suite for the §2.6 account
// menu - trigger semantics, keyboard open/close with focus return, menu-item
// roles, the stale-session phone-missing degrade, and both shell densities.
// #521: patient avatar trigger (precedence chain, Devanagari initial, phone
// hidden until open) and the staff-role regression pinning the old phone-
// digit trigger/dropdown verbatim.
// #526: the patient dropdown as a real account menu - identity header (name or
// masked phone, full E.164), live Profile & Settings, the basics-gated
// Complete-your-profile CTA, role switching kept for multi-role accounts and
// absent for single-role, a red dictionary-driven Log out, bilingual copy, the
// stale-session Subject #id degrade with Log out still working, and an axe
// scan of the opened menu.
// #567: the suite is rebuilt around a production-shaped doctor session - a
// `partner` role, because that is all the grants table can issue - and every
// render now names the shell the menu sits inside. The synthetic
// `roles: ["doctor"]` fixture that made the doctor branch look covered is
// gone, so this class of bug cannot be hidden by a fixture again.
// #569: the doctor's disc is hydrated from the shell-held profile projection -
// the object URL, the single read shared with the dropdown header, and both
// ways a read can fail to resolve - with the un-hydrated icon case kept pinned.

import {
  render,
  screen,
  act,
  fireEvent,
  cleanup,
  waitFor,
  within,
} from "@testing-library/react";
import type { ReactNode } from "react";
import {
  describe,
  it,
  expect,
  vi,
  beforeAll,
  beforeEach,
  afterEach,
} from "vitest";
import * as axe from "axe-core";
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { AccountMenu } from "./AccountMenu";
import { AuthProvider } from "@/lib/auth/AuthContext";
import type { StoredSession } from "@/lib/auth/session";
import {
  ProfileProvider,
  useOptionalProfile,
} from "@/lib/profile/ProfileContext";
import { useProfilePhotoSource } from "@/lib/profile/useProfilePhotoSource";
import {
  DoctorProfileProvider,
  useOptionalDoctorProfile,
} from "@/lib/doctor/DoctorProfileContext";
import type { StoredPatientProfile } from "@/lib/profile/api";
import type { DoctorProfileView } from "@/lib/doctor/api";
import { ApiError } from "@/lib/api-errors";
import { __resetLangForTests } from "@/lib/i18n/LangContext";
import { maskedPhone } from "./BottomTabs";
import type { Role } from "./types";

// Profile client mocked at the module boundary (ProfileContext.test prior
// art) so the patient trigger can hydrate a saved name/photo without HTTP.
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

// #569/#583: the doctor's private photo bytes, read over the doctor transport
// the shared profile source resolves through, and - since the read moved out of
// the shell - the projection read itself. Mocked at the module boundary for the
// same reason as the profile module: the menu must be able to seed a projection
// and fail a byte read without HTTP. Both exports are needed: the account menu
// reaches the photo reader directly, and it reaches the projection read
// transitively through the shared source it now reads.
const doctorApi = vi.hoisted(() => ({
  fetchDoctorProfile: vi.fn(),
  fetchDoctorProfilePhoto: vi.fn(),
}));

vi.mock("@/lib/doctor/api", () => ({
  fetchDoctorProfile: doctorApi.fetchDoctorProfile,
  fetchDoctorProfilePhoto: doctorApi.fetchDoctorProfilePhoto,
}));

const VALID_SESSION: StoredSession = {
  jwt: "test-jwt-token",
  refresh_token: "test-refresh-token",
  jti: "jti-1",
  scope: "patient",
  identity_id: 42,
  phone: "+911234567890",
};

const ME_RESPONSE_SINGLE_ROLE = {
  subject_id: "42",
  phone: "+911234567890",
  roles: ["patient"],
};

// #567: a partner-role session. This is ALSO the production-shaped doctor
// session: the grants table issues only patient|partner|operator, so a doctor
// signs in with `["partner"]` and is a doctor by partner *type*, not by role.
// Nothing in this payload distinguishes a doctor from a lab, which is exactly
// why the shell - and only the shell - decides doctor-ness. The suite used to
// fabricate `roles: ["doctor"]` here, a payload the backend cannot issue, and
// that fixture is what kept the doctor branch unreachable in production.
const ME_RESPONSE_PARTNER = {
  subject_id: "42",
  phone: "+911234567890",
  roles: ["partner"],
};

// A stale session payload predating T05's additive phone field.
const ME_RESPONSE_NO_PHONE = {
  subject_id: "42",
  roles: ["patient"],
};

// #570: an operator session - the third non-doctor staff shell. It shares the
// staff branch with a lab or chemist partner, and the doctor's parity work must
// not reach it either.
const ME_RESPONSE_OPERATOR = {
  subject_id: "42",
  phone: "+911234567890",
  roles: ["operator"],
};

const NAMED_PROFILE: StoredPatientProfile = {
  name: "Asha Devi",
  age: 30,
  gender: "female",
  preferred_language: "en",
  area: null,
  emergency_contact: null,
  photo_ref: null,
};

const DEVANAGARI_PROFILE: StoredPatientProfile = {
  ...NAMED_PROFILE,
  name: "अंकिता शर्मा",
};

const PHOTO_PROFILE: StoredPatientProfile = {
  ...NAMED_PROFILE,
  photo_ref: "https://cdn.example.test/me.jpg",
};

// #569: the projection the shared doctor profile source hydrates from. `photo_ref`
// is an opaque object key in the doctor's own namespace (ADR-0020 D1) and
// `practice_name` is the only human-readable name a doctor has anywhere in the
// frontend, which is why the source takes the whole view.
function doctorProfileWith(
  photoRef: string | null,
  practiceName: string | null = "Asha Clinic",
): DoctorProfileView {
  return {
    partner_id: 7,
    photo_ref: photoRef,
    practice_name: practiceName,
    specialty: "General",
    verified: true,
    practice_address: "1 Clinic Road",
    practice_latitude: 12.97,
    practice_longitude: 77.59,
    area: "Indiranagar",
    languages: ["en"],
    experience_years: 9,
    about: null,
    consultation_fee: 400,
    availability: null,
    credentials: [],
    notification_preferences: {},
  };
}

function setStoredSession(session: StoredSession) {
  localStorage.setItem("caresetu.session", JSON.stringify(session));
  localStorage.setItem("caresetu.access_jwt", session.jwt);
  localStorage.setItem("caresetu.refresh_token", session.refresh_token);
}

// #567: every render names the shell it sits inside. The parameter is required
// on purpose - a default would let a staff test silently land in the patient
// branch, and would let a doctor test forget the very answer it is testing.
// #583: `doctorProjection` seeds the shared doctor profile source, which the
// (doctor) route-group layout mounts above the menu in production. Leaving it
// undefined is the real state for every other shell, which mounts no source at
// all and whose menu therefore reads nothing.
function renderAccountMenu(
  shellRole: Role,
  doctorProjection?: DoctorProfileView,
) {
  return render(
    <AuthProvider>
      {doctorProjection === undefined ? (
        <AccountMenu shellRole={shellRole} />
      ) : (
        <DoctorProfileProvider>
          <AccountMenu shellRole={shellRole} />
        </DoctorProfileProvider>
      )}
    </AuthProvider>,
  );
}

function mockMeResponse(payload: unknown) {
  vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
    new Response(JSON.stringify(payload), { status: 200 }),
  );
}

// #521: the patient trigger reads name/photo through the shared profile
// seam. When `profile` is given, wrap in the real ProfileProvider so
// hydration ordering is exercised (name/photo arrive async). `shellRole` is
// the role of the shell the menu renders inside (#567).
// #583: `doctorProjection` seeds the shared doctor profile source the doctor's
// branch now reads, standing in for the (doctor) route-group layout so this leaf
// suite can exercise the doctor's branch without standing up the shell. Passing
// it undefined is the real state for every non-doctor shell, which mounts no
// source and therefore starts no read.
async function renderClosedTrigger(
  mePayload: unknown,
  shellRole: Role,
  profile?: StoredPatientProfile | null,
  doctorProjection?: DoctorProfileView,
) {
  setStoredSession(VALID_SESSION);
  const menu = <AccountMenu shellRole={shellRole} />;
  // Each source is named once and stacked, rather than spelled out again per
  // combination: a doctor source exists only where a doctor projection was asked
  // for, a patient source only where a patient profile was, and a shell with
  // neither mounts no source at all - which is the state every non-doctor case
  // runs in, and the reason `useOptionalDoctorProfile` exists.
  const sources: ((node: ReactNode) => ReactNode)[] = [];
  if (profile !== undefined) {
    sources.push((node) => <ProfileProvider>{node}</ProfileProvider>);
  }
  if (doctorProjection !== undefined) {
    sources.push((node) => (
      <DoctorProfileProvider>{node}</DoctorProfileProvider>
    ));
  }
  const app = (
    <AuthProvider>
      {sources.reduceRight<ReactNode>(
        (node, withSource) => withSource(node),
        menu,
      )}
    </AuthProvider>
  );
  if (profile !== undefined) {
    profileApi.getProfile.mockResolvedValue({
      set: profile !== null,
      profile,
    });
  }
  if (doctorProjection !== undefined) {
    doctorApi.fetchDoctorProfile.mockResolvedValue(doctorProjection);
  }
  mockMeResponse(mePayload);
  render(app);
  const trigger = await waitFor(() =>
    expect(screen.getByTestId("account-menu")).toBeInTheDocument(),
  ).then(() => screen.getByTestId("account-menu"));
  if (profile !== undefined) {
    await waitFor(() => expect(profileApi.getProfile).toHaveBeenCalled());
  }
  if (doctorProjection !== undefined) {
    await waitFor(() =>
      expect(doctorApi.fetchDoctorProfile).toHaveBeenCalled(),
    );
  }
  return trigger;
}

function renderPatientWithProfile(profile: StoredPatientProfile | null) {
  return renderClosedTrigger(ME_RESPONSE_SINGLE_ROLE, "patient", profile);
}

// #557: the only thing that moves a stored photo ref is the profile context's
// syncPhotoRef, so the replace/clear path is driven through the real context
// rather than a faked setter.
function PhotoRefControls() {
  const profile = useOptionalProfile();
  return (
    <div>
      <button
        type="button"
        data-testid="replace-photo"
        onClick={() => profile?.syncPhotoRef("patient/7/photo-2.enc")}
      >
        replace
      </button>
      <button
        type="button"
        data-testid="clear-photo"
        onClick={() => profile?.syncPhotoRef(null)}
      >
        clear
      </button>
    </div>
  );
}

// #569: the seam's internal distinction is invisible in chrome - a definite
// "no media" answer and a transport blip both render the same person icon, and
// That is the point. This probe reads the *same* resolution the menu is showing
// (one cached read per ref, so it adds no request) and reports which answer it
// got, so the two can be told apart in a test without a production attribute
// that exists only for the assertion.
function PhotoAbsenceProbe() {
  // The probe reads the ref from the same shared source the menu reads it from
  // rather than taking it as a prop, so it cannot hold a resolution the menu is
  // not showing: it picks the ref up on the same commit the menu does, and the
  // one cached read serves both.
  const doctor = useOptionalDoctorProfile();
  const { absent } = useProfilePhotoSource(
    doctor?.profile?.photo_ref ?? null,
    doctorApi.fetchDoctorProfilePhoto,
  );
  return <span data-testid="photo-absent">{String(absent)}</span>;
}

async function openViaKeyboard() {
  await waitFor(() =>
    expect(screen.getByTestId("account-menu")).toBeInTheDocument(),
  );
  const trigger = screen.getByTestId("account-menu");
  fireEvent.keyDown(trigger, { key: "Enter" });
  await waitFor(() => expect(screen.getByRole("menu")).toBeInTheDocument());
  return trigger;
}

// Radix popper relies on ResizeObserver and opens menus on real pointer
// events, neither of which jsdom implements fully. Vitest isolates each test
// file in its own jsdom environment, so these stubs cannot leak elsewhere.
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

const mockReplace = vi.fn();
const mockPush = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mockReplace, push: mockPush }),
  usePathname: () => "/patient",
}));

// next/link reads its own app-router context (not the mocked useRouter), so
// clicks on the menu's asChild links fall through to jsdom navigation. Mock
// it as a click-aware anchor that composes the incoming handler (Radix's
// select/close) and then records the same router.push(next/link) would
// perform, exercising the activation path of both profile entries.
vi.mock("next/link", () => ({
  default({
    href,
    children,
    onClick,
    ...props
  }: {
    href: string;
    children: React.ReactNode;
    onClick?: (event: React.MouseEvent<HTMLAnchorElement>) => void;
    [key: string]: unknown;
  }) {
    return (
      <a
        href={href}
        {...props}
        onClick={(event) => {
          onClick?.(event);
          if (!event.defaultPrevented) {
            event.preventDefault();
            mockPush(href);
          }
        }}
      >
        {children}
      </a>
    );
  },
}));

// #557: the <img> a surface ends up showing. Asserting inside waitFor is what
// makes it retry - a bare querySelector returns null and resolves immediately.
async function imageIn(root: ParentNode): Promise<HTMLImageElement> {
  return waitFor(() => {
    const img = root.querySelector("img");
    expect(img).not.toBeNull();
    return img;
  }).then((el) => el as HTMLImageElement);
}

// #557: object-URL plumbing for the shared photo resolver. jsdom implements
// neither, so the suite supplies them and restores whatever the host has.
let originalCreate: typeof URL.createObjectURL;
let originalRevoke: typeof URL.revokeObjectURL;
let photoUrls: number;

beforeEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
  __resetLangForTests();
  mockReplace.mockReset();
  mockPush.mockReset();
  // restoreAllMocks clears the hoisted module-mock implementations too;
  // re-seed the default "no saved profile" answer every test starts from.
  profileApi.getProfile.mockResolvedValue({ set: false, profile: null });
  // #557: the stored photo ref resolves to an object URL, and jsdom has no
  // createObjectURL of its own. A distinct URL per call so a test can tell
  // *which* generation of the photo a surface is showing.
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
  // #583: the shared doctor source reads the projection. Default to a profile
  // with no photo, so the person-icon disc is the steady state and a doctor's
  // tests that care about the photo re-seed it; the non-doctor tests never mount
  // the source, so this default is never read on their behalf.
  doctorApi.fetchDoctorProfile.mockResolvedValue(doctorProfileWith(null));
  doctorApi.fetchDoctorProfilePhoto.mockResolvedValue(
    new Blob(["doctor-photo-bytes"], { type: "image/png" }),
  );
});

afterEach(() => {
  // Unmounting is what drops the hook's cache entry, so it has to happen before
  // the stubs come back - otherwise a live entry survives into the next test.
  cleanup();
  URL.createObjectURL = originalCreate;
  URL.revokeObjectURL = originalRevoke;
});

describe("AccountMenu accessibility", () => {
  it("trigger announces itself as a menu opener (aria-haspopup)", async () => {
    setStoredSession(VALID_SESSION);
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(ME_RESPONSE_SINGLE_ROLE), { status: 200 }),
    );

    renderAccountMenu("patient");
    const trigger = await waitFor(() =>
      expect(screen.getByTestId("account-menu")).toBeInTheDocument(),
    ).then(() => screen.getByTestId("account-menu"));

    expect(trigger.getAttribute("aria-label")).toBe("Account menu");
    expect(trigger.getAttribute("aria-haspopup")).toBe("menu");
  });

  it("opens via Enter key into a role=menu with role=menuitem entries", async () => {
    setStoredSession(VALID_SESSION);
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(ME_RESPONSE_SINGLE_ROLE), { status: 200 }),
    );

    renderAccountMenu("patient");
    await openViaKeyboard();

    expect(
      screen.getByRole("menuitem", { name: "Log out" }),
    ).toBeInTheDocument();
  });

  it("closes on Escape and returns focus to the trigger", async () => {
    setStoredSession(VALID_SESSION);
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(ME_RESPONSE_SINGLE_ROLE), { status: 200 }),
    );

    renderAccountMenu("patient");
    const trigger = await openViaKeyboard();

    fireEvent.keyDown(screen.getByRole("menu"), { key: "Escape" });
    await waitFor(() =>
      expect(screen.queryByRole("menu")).not.toBeInTheDocument(),
    );
    expect(document.activeElement).toBe(trigger);
  });

  it("consolidates phone, role badge, and logout - no standalone controls", async () => {
    setStoredSession(VALID_SESSION);
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(ME_RESPONSE_SINGLE_ROLE), { status: 200 }),
    );

    renderAccountMenu("patient");
    await openViaKeyboard();

    expect(screen.getByText("+911234567890")).toBeInTheDocument();
    expect(screen.getByTestId("account-menu-role-badge")).toHaveTextContent(
      "Patient",
    );
    expect(
      screen.getByRole("menuitem", { name: "Log out" }),
    ).toBeInTheDocument();
  });
});

describe("AccountMenu patient avatar trigger (#521)", () => {
  it("falls back to the person icon when no profile is saved", async () => {
    const trigger = await renderClosedTrigger(
      ME_RESPONSE_SINGLE_ROLE,
      "patient",
    );

    // No digit text and no name: just the icon branch of the chain.
    expect(trigger).toHaveTextContent("");
    expect(trigger.querySelector("svg")).not.toBeNull();
    expect(trigger.querySelector("img")).toBeNull();
    await waitFor(() =>
      expect(trigger).toHaveAttribute("data-session-resolved", "true"),
    );
  });

  it("shows the first letter of the saved name, no icon", async () => {
    const trigger = await renderPatientWithProfile(NAMED_PROFILE);

    await waitFor(() => expect(trigger).toHaveTextContent("A"));
    expect(trigger.querySelector("svg")).toBeNull();
    expect(trigger.querySelector("img")).toBeNull();
    // No stored photo means nothing to ask the backend for, so the bytes
    // endpoint is never touched.
    expect(profileApi.fetchPatientPhoto).not.toHaveBeenCalled();
  });

  it("renders a Devanagari initial intact", async () => {
    const trigger = await renderPatientWithProfile(DEVANAGARI_PROFILE);

    await waitFor(() => expect(trigger).toHaveTextContent("अ"));
  });

  // #557: the ref is an opaque object key, so the primitive can no longer be
  // handed it directly. The trigger shows the bytes the backend streams back,
  // never the stored ref as a browser-reachable URL (ADR-0020 D2).
  it("photo_ref resolves to a renderable source, never the ref itself", async () => {
    const trigger = await renderClosedTrigger(
      ME_RESPONSE_SINGLE_ROLE,
      "patient",
      PHOTO_PROFILE,
    );

    const img = await imageIn(trigger);
    expect(img.getAttribute("src")).toBe("blob:http://localhost/photo-1");
    expect(img.getAttribute("src")).not.toContain("cdn.example.test");
    expect(trigger).not.toHaveTextContent("A");
    expect(profileApi.fetchPatientPhoto).toHaveBeenCalledTimes(1);
  });

  it("a stored photo ref renders an image in the trigger and in the identity header", async () => {
    const trigger = await renderClosedTrigger(
      ME_RESPONSE_SINGLE_ROLE,
      "patient",
      {
        ...NAMED_PROFILE,
        photo_ref: "patient/7/photo-1.enc",
      },
    );

    const triggerImg = await imageIn(trigger);
    expect(triggerImg.getAttribute("src")).toMatch(/^blob:/);

    fireEvent.keyDown(trigger, { key: "Enter" });
    await waitFor(() => expect(screen.getByRole("menu")).toBeInTheDocument());

    const headerImg = await imageIn(screen.getByRole("menu"));
    expect(headerImg.getAttribute("src")).toBe(triggerImg.getAttribute("src"));
    // Two avatars, one ref, one request: the menu header reads the same
    // resolution the trigger is already showing.
    expect(profileApi.fetchPatientPhoto).toHaveBeenCalledTimes(1);
  });

  it("a photo ref that fails to resolve degrades to the initial, not a broken image", async () => {
    profileApi.fetchPatientPhoto.mockRejectedValue(new Error("network down"));

    const trigger = await renderClosedTrigger(
      ME_RESPONSE_SINGLE_ROLE,
      "patient",
      {
        ...NAMED_PROFILE,
        photo_ref: "patient/7/photo-1.enc",
      },
    );
    await waitFor(() =>
      expect(profileApi.fetchPatientPhoto).toHaveBeenCalled(),
    );
    await waitFor(() => expect(trigger).toHaveTextContent("A"));

    // A blip is not a photo failure notice: the chrome avatar shows the initial
    // and nothing else, and no <img> is left pointing at nothing.
    expect(trigger.querySelector("img")).toBeNull();
    expect(trigger).toHaveTextContent("A");
  });

  // The cache is keyed by the ref, so syncPhotoRef is what invalidates it. A
  // replace or a clear moves every surface at once and never answers from the
  // bytes the previous ref produced.
  it("a replaced photo ref re-reads the bytes, and a cleared one falls back to the initial", async () => {
    setStoredSession(VALID_SESSION);
    profileApi.getProfile.mockResolvedValue({
      set: true,
      profile: { ...NAMED_PROFILE, photo_ref: "patient/7/photo-1.enc" },
    });
    mockMeResponse(ME_RESPONSE_SINGLE_ROLE);
    render(
      <AuthProvider>
        <ProfileProvider>
          <AccountMenu shellRole="patient" />
          <PhotoRefControls />
        </ProfileProvider>
      </AuthProvider>,
    );
    const trigger = await waitFor(() =>
      expect(screen.getByTestId("account-menu")).toBeInTheDocument(),
    ).then(() => screen.getByTestId("account-menu"));

    const first = await imageIn(trigger);
    expect(first.getAttribute("src")).toBe("blob:http://localhost/photo-1");

    fireEvent.click(screen.getByTestId("replace-photo"));
    // The new ref is a new cache key: a second read, a new object URL, and the
    // bytes the previous ref produced are no longer in any view.
    await waitFor(() =>
      expect(trigger.querySelector("img")?.getAttribute("src")).toBe(
        "blob:http://localhost/photo-2",
      ),
    );
    expect(profileApi.fetchPatientPhoto).toHaveBeenCalledTimes(2);

    // The header behind the trigger moves with it, not one commit behind.
    fireEvent.keyDown(trigger, { key: "Enter" });
    await waitFor(() => expect(screen.getByRole("menu")).toBeInTheDocument());
    expect(
      screen.getByRole("menu").querySelector("img")?.getAttribute("src"),
    ).toBe("blob:http://localhost/photo-2");

    fireEvent.click(screen.getByTestId("clear-photo"));
    await waitFor(() => expect(trigger).toHaveTextContent("A"));
    expect(trigger.querySelector("img")).toBeNull();
  });

  it("patient branch keeps the name off the trigger and the phone hidden until the menu opens", async () => {
    const trigger = await renderPatientWithProfile(NAMED_PROFILE);

    // No name label beside the circle; no full phone while closed.
    expect(trigger).not.toHaveTextContent("Asha");
    expect(screen.queryByText("Asha Devi")).toBeNull();
    expect(screen.queryByText("+911234567890")).toBeNull();

    fireEvent.keyDown(trigger, { key: "Enter" });
    await waitFor(() => expect(screen.getByRole("menu")).toBeInTheDocument());

    expect(screen.getByText("+911234567890")).toBeInTheDocument();
  });

  it("#538 shows the doctor a person-icon account avatar instead of phone digits", async () => {
    // #567: a production-shaped doctor session - the grants table issues no
    // "doctor" role, so this payload reads `["partner"]` and the doctor-ness
    // comes entirely from the shell the menu is rendered inside. A component
    // that went back to asking the session would take the else branch here and
    // fail on the "90" assertion.
    // #569: the shell-held projection carries no photo ref, so the disc has
    // nothing to resolve and keeps the person icon. The person-icon path stays
    // pinned for the doctor-with-no-photo case even though the hydrated case
    // exists now.
    const trigger = await renderClosedTrigger(
      ME_RESPONSE_PARTNER,
      "doctor",
      undefined,
      doctorProfileWith(null),
    );

    // The generic person icon entry point - no digit text, and no <img> where
    // a ref was never stored.
    expect(trigger).not.toHaveTextContent("90");
    expect(trigger.querySelector("svg")).not.toBeNull();
    expect(trigger.querySelector("img")).toBeNull();
    // Let hydration settle first: a read that arrives a tick late is still a
    // read, so this has to be an assertion about the branch, not about timing.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    // No ref, so no bytes endpoint is touched - over either transport. And a
    // doctor never reads the patient one: the shell told us whose photo it is.
    expect(doctorApi.fetchDoctorProfilePhoto).not.toHaveBeenCalled();
    expect(profileApi.fetchPatientPhoto).not.toHaveBeenCalled();

    // The dropdown behind the avatar still carries the full phone, role badge
    // and dictionary-driven Log out. #570: the badge now follows the shell the
    // doctor is sitting in rather than the session's grant, so it reads
    // "Doctor" - the session could only ever answer "partner", which is the
    // same word a lab partner's badge shows.
    await openViaKeyboard();
    expect(screen.getByText("+911234567890")).toBeInTheDocument();
    expect(screen.getByTestId("account-menu-role-badge")).toHaveTextContent(
      "Doctor",
    );
    expect(
      screen.getByRole("menuitem", { name: "Log out" }),
    ).toBeInTheDocument();
  });

  // #569: the whole of the defect, inverted. The doctor disc shows the photo
  // the backend streams, never the stored key, and the read is the doctor's
  // own private one - the ref arrives from the shell, the bytes from the doctor
  // transport, and the patient endpoint is never touched.
  it("#569 renders the doctor's stored photo as an object URL, never the stored key", async () => {
    const trigger = await renderClosedTrigger(
      ME_RESPONSE_PARTNER,
      "doctor",
      undefined,
      doctorProfileWith("doctor/7/photo-1.enc"),
    );

    const img = await imageIn(trigger);
    expect(img.getAttribute("src")).toMatch(/^blob:/);
    // ADR-0020 D1/D2: the key is opaque and never browser-reachable, so a src
    // that contained it would be the whole defect back.
    expect(img.getAttribute("src")).not.toContain("doctor/7/photo-1.enc");
    expect(doctorApi.fetchDoctorProfilePhoto).toHaveBeenCalledTimes(1);
    // The doctor's own bytes, not the patient's.
    expect(profileApi.fetchPatientPhoto).not.toHaveBeenCalled();
  });

  it("#569 shares one doctor read between the trigger and the dropdown header", async () => {
    const trigger = await renderClosedTrigger(
      ME_RESPONSE_PARTNER,
      "doctor",
      undefined,
      doctorProfileWith("doctor/7/photo-1.enc"),
    );

    const triggerImg = await imageIn(trigger);
    expect(triggerImg.getAttribute("src")).toMatch(/^blob:/);

    fireEvent.keyDown(trigger, { key: "Enter" });
    await waitFor(() => expect(screen.getByRole("menu")).toBeInTheDocument());

    const headerImg = await imageIn(screen.getByRole("menu"));
    expect(headerImg.getAttribute("src")).toBe(triggerImg.getAttribute("src"));
    // Two avatars, one ref, one request - counted, not inferred.
    expect(doctorApi.fetchDoctorProfilePhoto).toHaveBeenCalledTimes(1);
  });

  it("#569 degrades a failed doctor photo read to the person icon, not a broken image", async () => {
    doctorApi.fetchDoctorProfilePhoto.mockRejectedValue(
      new Error("network down"),
    );
    const trigger = await renderClosedTrigger(
      ME_RESPONSE_PARTNER,
      "doctor",
      undefined,
      doctorProfileWith("doctor/7/photo-1.enc"),
    );

    await waitFor(() =>
      expect(doctorApi.fetchDoctorProfilePhoto).toHaveBeenCalled(),
    );
    // The call is made before the rejection settles, so "no img yet" would
    // pass on a read that has not answered. Flush it before asserting the
    // degrade - the same settle the un-hydrated #538 assertion used.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    // A blip is not a failure notice on a chrome avatar: the icon, and nothing
    // else, with no <img> left pointing at nothing.
    expect(trigger.querySelector("img")).toBeNull();
    expect(trigger.querySelector("svg")).not.toBeNull();
    expect(trigger).not.toHaveTextContent("90");
  });

  it("#569 tells a definitely-absent doctor photo from a blip, though both show the icon", async () => {
    // The seam reads absence off a not-found code only, so a stored ref whose
    // media is gone reads as absent while a blip leaves it looking present - the
    // difference a later pass on the identity header will need, invisible in
    // chrome today. The probe holds the same ref, so the two share one read.
    async function renderAgainst(rejection: unknown) {
      // Each render is its own mount, and the seam drops a ref's cached read
      // when the last consumer lets go - so the count is per render, not per
      // test.
      doctorApi.fetchDoctorProfilePhoto.mockReset();
      doctorApi.fetchDoctorProfilePhoto.mockRejectedValue(rejection);
      doctorApi.fetchDoctorProfile.mockResolvedValue(
        doctorProfileWith("doctor/7/photo-1.enc"),
      );
      setStoredSession(VALID_SESSION);
      mockMeResponse(ME_RESPONSE_PARTNER);
      render(
        <AuthProvider>
          <DoctorProfileProvider>
            <AccountMenu shellRole="doctor" />
            <PhotoAbsenceProbe />
          </DoctorProfileProvider>
        </AuthProvider>,
      );
      const trigger = screen.getByTestId("account-menu");
      await waitFor(() =>
        expect(doctorApi.fetchDoctorProfilePhoto).toHaveBeenCalled(),
      );
      return trigger;
    }

    const absentTrigger = await renderAgainst(
      new ApiError({
        code: "DOCTOR_PROFILE_PHOTO_NOT_FOUND",
        message: "no photo",
        trace_id: "trace-569",
        details: {},
      }),
    );
    expect(absentTrigger.querySelector("img")).toBeNull();
    expect(absentTrigger.querySelector("svg")).not.toBeNull();
    // Absence is the settled answer and the pending one is not, so this wait is
    // the settle - it cannot pass on a read that has not answered yet.
    await waitFor(() =>
      expect(screen.getByTestId("photo-absent")).toHaveTextContent("true"),
    );
    // Menu and probe, one ref, one read - the probe observed, it did not add.
    expect(doctorApi.fetchDoctorProfilePhoto).toHaveBeenCalledTimes(1);
    cleanup();

    const blipTrigger = await renderAgainst(
      new ApiError({
        code: "NETWORK_ERROR",
        message: "connection reset",
        trace_id: "trace-569",
        details: {},
      }),
    );
    expect(blipTrigger.querySelector("img")).toBeNull();
    expect(blipTrigger.querySelector("svg")).not.toBeNull();
    // A blip settles looking present, so the answer has to be read after the
    // rejection has actually run - and the contrast with the case above is the
    // point: same icon, different internal verdict.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(screen.getByTestId("photo-absent")).toHaveTextContent("false");
    expect(doctorApi.fetchDoctorProfilePhoto).toHaveBeenCalledTimes(1);
  });

  it("#543 opens the doctor Profile page from the avatar dropdown", async () => {
    await renderClosedTrigger(ME_RESPONSE_PARTNER, "doctor");
    await openViaKeyboard();

    const profileItem = screen.getByTestId("account-menu-doctor-profile");
    expect(profileItem).toHaveAttribute("href", "/doctor/profile");
    // #604: the whole label, not the "Profile" prefix it used to match - the
    // row now reads Profile & Settings from its own accountMenu key.
    expect(profileItem).toHaveTextContent("Profile & Settings");
  });

  it("#543 keeps the Profile row off non-doctor staff menus", async () => {
    await renderClosedTrigger(ME_RESPONSE_PARTNER, "partner");
    await openViaKeyboard();

    expect(screen.queryByTestId("account-menu-doctor-profile")).toBeNull();
  });

  it("non-doctor staff keeps the phone-digit trigger and dropdown verbatim", async () => {
    const trigger = await renderClosedTrigger(ME_RESPONSE_PARTNER, "partner");

    expect(trigger).toHaveTextContent("90");
    expect(trigger.querySelector("svg")).toBeNull();
    expect(trigger.querySelector("img")).toBeNull();

    await openViaKeyboard();

    expect(screen.getByText("+911234567890")).toBeInTheDocument();
    expect(screen.getByTestId("account-menu-role-badge")).toHaveTextContent(
      "Partner",
    );
    expect(
      screen.getByRole("menuitem", { name: "Log out" }),
    ).toBeInTheDocument();
  });

  // #567: the direction of the fix, pinned from both ends of the same session.
  // One production-shaped doctor payload - a `partner` role, the only thing
  // the grants table can issue - rendered inside the doctor shell gains the
  // doctor affordances; the byte-identical session inside the partner shell
  // keeps the staff ones. Nothing in the session differs, so a component that
  // re-derived doctor-ness from the session's roles could only fail the first
  // half, never pass both.
  //
  // Deliberately not a duplicate of the two neighbours: it is their
  // conjunction over ONE shared fixture, which is the only place the claim
  // "the session is identical and only the shell moved" is visible rather than
  // something a reader has to reconstruct across three tests. AppShell's suite
  // asserts the same pair one level up, with the role threaded rather than
  // hand-fed.
  it("reads doctor-ness from the shell it sits in, not from the session's roles", async () => {
    const doctorShell = await renderClosedTrigger(
      ME_RESPONSE_PARTNER,
      "doctor",
    );
    expect(doctorShell).not.toHaveTextContent("90");
    expect(doctorShell.querySelector("svg")).not.toBeNull();
    await openViaKeyboard();
    expect(
      screen.getByTestId("account-menu-doctor-profile"),
    ).toBeInTheDocument();
    cleanup();

    const partnerShell = await renderClosedTrigger(
      ME_RESPONSE_PARTNER,
      "partner",
    );
    expect(partnerShell).toHaveTextContent("90");
    expect(partnerShell.querySelector("svg")).toBeNull();
    await openViaKeyboard();
    expect(screen.queryByTestId("account-menu-doctor-profile")).toBeNull();
  });
});

describe("AccountMenu mobile placement (#525)", () => {
  it("hides the patient trigger below lg so the phone account lives only in the More sheet", async () => {
    const trigger = await renderClosedTrigger(
      ME_RESPONSE_SINGLE_ROLE,
      "patient",
    );

    expect(trigger.className).toContain("hidden");
    expect(trigger.className).toContain("lg:inline-flex");
    // The shared Avatar still resolves to the patient person icon.
    expect(trigger.querySelector("svg")).not.toBeNull();
  });

  it("keeps the non-doctor staff phone-digit trigger fully visible at every width", async () => {
    const trigger = await renderClosedTrigger(ME_RESPONSE_PARTNER, "partner");

    expect(trigger).toHaveTextContent("90");
    expect(trigger.className).toContain("flex");
    expect(trigger.className).not.toContain("hidden");
  });
});

describe("AccountMenu desktop identity dropdown (#526)", () => {
  function openPatientMenu() {
    return renderPatientWithProfile(NAMED_PROFILE).then((trigger) => {
      fireEvent.keyDown(trigger, { key: "Enter" });
      return waitFor(() =>
        expect(screen.getByRole("menu")).toBeInTheDocument(),
      );
    });
  }

  it("identity header shows the saved name, full E.164 phone and avatar initial", async () => {
    await openPatientMenu();

    expect(screen.getByTestId("account-menu-identity")).toHaveTextContent(
      "Asha Devi",
    );
    expect(screen.getByText("+911234567890")).toBeInTheDocument();
    // The header avatar owns the named initial inside the open menu.
    expect(within(screen.getByRole("menu")).getByText("A")).toBeInTheDocument();
  });

  it("falls back to the masked phone and still shows the full E.164 without a saved name", async () => {
    const trigger = await renderPatientWithProfile(null);
    fireEvent.keyDown(trigger, { key: "Enter" });
    await waitFor(() => expect(screen.getByRole("menu")).toBeInTheDocument());

    expect(screen.getByTestId("account-menu-identity")).toHaveTextContent(
      maskedPhone("+911234567890"),
    );
    expect(screen.getByTestId("account-menu-identity")).toHaveTextContent(
      "+91 XXXXXX7890",
    );
    expect(screen.getByText("+911234567890")).toBeInTheDocument();
  });

  it("renders a live Profile & Settings entry pointing at the profile page", async () => {
    await openPatientMenu();

    const entry = screen.getByRole("menuitem", {
      name: "Profile & Settings",
    });
    expect(entry.tagName).toBe("A");
    expect(entry).toHaveAttribute("href", "/patient/profile");
  });

  it("navigates to the profile page when the Profile & Settings entry is activated", async () => {
    await openPatientMenu();

    fireEvent.click(
      screen.getByRole("menuitem", { name: "Profile & Settings" }),
    );

    await waitFor(() =>
      expect(mockPush).toHaveBeenCalledWith("/patient/profile"),
    );
  });

  it("shows the Complete your profile CTA only while basics are missing", async () => {
    const trigger = await renderPatientWithProfile(null);
    fireEvent.keyDown(trigger, { key: "Enter" });
    await waitFor(() => expect(screen.getByRole("menu")).toBeInTheDocument());

    const cta = screen.getByTestId("account-menu-complete-profile");
    expect(cta).toHaveTextContent("Complete your profile");
    expect(cta).toHaveAttribute("href", "/patient/profile");
  });

  it("navigates to the profile page when the CTA is activated", async () => {
    const trigger = await renderPatientWithProfile(null);
    fireEvent.keyDown(trigger, { key: "Enter" });
    await waitFor(() => screen.getByRole("menu"));

    fireEvent.click(screen.getByTestId("account-menu-complete-profile"));

    await waitFor(() =>
      expect(mockPush).toHaveBeenCalledWith("/patient/profile"),
    );
  });

  it("keeps the CTA when a saved profile is missing a basic field", async () => {
    const trigger = await renderClosedTrigger(
      ME_RESPONSE_SINGLE_ROLE,
      "patient",
      {
        ...NAMED_PROFILE,
        name: "  ",
      },
    );
    fireEvent.keyDown(trigger, { key: "Enter" });
    await waitFor(() => expect(screen.getByRole("menu")).toBeInTheDocument());

    expect(
      screen.getByTestId("account-menu-complete-profile"),
    ).toBeInTheDocument();
  });

  it("hides the CTA once basics (name, age, gender) are saved", async () => {
    await openPatientMenu();

    expect(
      screen.queryByTestId("account-menu-complete-profile"),
    ).not.toBeInTheDocument();
  });

  it("keeps role switching for multi-role accounts", async () => {
    // #567: a real role pair. This used to be ["patient", "doctor"], which the
    // backend cannot issue - role switching is offered for the *session's*
    // roles, so the vocabulary it is exercised against is the real one.
    const trigger = await renderClosedTrigger(
      {
        subject_id: "42",
        phone: "+911234567890",
        roles: ["patient", "partner"],
      },
      "patient",
      NAMED_PROFILE,
    );
    fireEvent.keyDown(trigger, { key: "Enter" });
    await waitFor(() => expect(screen.getByRole("menu")).toBeInTheDocument());

    expect(
      screen.getByRole("menuitem", { name: "Switch to Partner" }),
    ).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("menuitem", { name: "Switch to Partner" }),
    );
    // Radix closes on select; reopening shows the role did switch.
    fireEvent.keyDown(screen.getByTestId("account-menu"), { key: "Enter" });
    await waitFor(() => expect(screen.getByRole("menu")).toBeInTheDocument());
    expect(screen.getByTestId("account-menu-role-badge")).toHaveTextContent(
      "Partner",
    );
  });

  it("keeps the single-role patient menu free of role-switch clutter", async () => {
    await openPatientMenu();

    expect(screen.queryByText(/Switch to/)).not.toBeInTheDocument();
  });

  it("renders a red dictionary-driven Log out that ends the session", async () => {
    await openPatientMenu();

    const logoutItem = screen.getByRole("menuitem", { name: "Log out" });
    expect(logoutItem.className).toContain("text-danger");

    fireEvent.click(logoutItem);
    expect(mockReplace).toHaveBeenCalledWith("/");
    expect(localStorage.getItem("caresetu.session")).toBeNull();
  });

  it("renders the account menu strings bilingually", async () => {
    localStorage.setItem("caresetu.lang", "hi");
    setStoredSession(VALID_SESSION);
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(ME_RESPONSE_SINGLE_ROLE), { status: 200 }),
    );

    renderAccountMenu("patient");
    const trigger = await waitFor(() =>
      expect(screen.getByTestId("account-menu")).toBeInTheDocument(),
    ).then(() => screen.getByTestId("account-menu"));

    expect(trigger.getAttribute("aria-label")).toBe("अकाउंट मेन्यू");

    fireEvent.keyDown(trigger, { key: "Enter" });
    await waitFor(() => expect(screen.getByRole("menu")).toBeInTheDocument());

    expect(
      screen.getByRole("menuitem", { name: "लॉग आउट" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("menuitem", { name: "प्रोफ़ाइल और सेटिंग" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("menuitem", { name: "अपनी प्रोफ़ाइल पूरी करें" }),
    ).toBeInTheDocument();
  });

  it("keeps the patient dropdown axe-clean", async () => {
    const trigger = await renderPatientWithProfile(null);
    fireEvent.keyDown(trigger, { key: "Enter" });
    await waitFor(() => expect(screen.getByRole("menu")).toBeInTheDocument());

    const { violations } = await axe.run(screen.getByRole("menu"));
    expect(violations).toEqual([]);
  });
});

// #570: the doctor branch reaches the patient branch's treatment, and these
// cases are the patient's own assertion shapes driven by the production-shaped
// doctor session - a `partner` role, since that is all the grants table issues,
// with doctor-ness coming from the shell alone. The three properties that make
// the difference are pinned separately: what the identity header carries, how
// wide the content is, and which rows are full-size tap targets.
describe("AccountMenu doctor dropdown parity (#570)", () => {
  function openDoctorMenu(
    mePayload: unknown = ME_RESPONSE_PARTNER,
    photoRef: string | null = null,
    practiceName: string | null = "Asha Clinic",
  ) {
    return renderClosedTrigger(
      mePayload,
      "doctor",
      undefined,
      doctorProfileWith(photoRef, practiceName),
    ).then((trigger) => {
      fireEvent.keyDown(trigger, { key: "Enter" });
      return waitFor(() =>
        expect(screen.getByRole("menu")).toBeInTheDocument(),
      );
    });
  }

  it("identity header shows the practice name, the full E.164 and the Doctor badge", async () => {
    await openDoctorMenu();

    // The practice name off the shell-held projection is the only human-readable
    // name a doctor has anywhere in the frontend, and it resolves through the
    // same shared name -> masked phone -> "Subject #id" chain the patient uses.
    expect(screen.getByTestId("account-menu-identity")).toHaveTextContent(
      "Asha Clinic",
    );
    // The FULL E.164, not the masked form and not the last two digits.
    expect(screen.getByText("+911234567890")).toBeInTheDocument();
    expect(screen.queryByText(maskedPhone("+911234567890"))).toBeNull();
    // The session can only answer "partner"; the shell knows which partner this
    // is, so the badge follows the shell and reads from the same ROLE_LABELS
    // vocabulary every other badge reads.
    expect(screen.getByTestId("account-menu-role-badge")).toHaveTextContent(
      "Doctor",
    );
  });

  it("header avatar shows the doctor's own photo, never the stored ref", async () => {
    await openDoctorMenu(ME_RESPONSE_PARTNER, "doctor/7/photo-1.enc");

    const img = await imageIn(screen.getByRole("menu"));
    expect(img.getAttribute("src")).toMatch(/^blob:/);
    expect(img.getAttribute("src")).not.toContain("doctor/7/photo-1.enc");
  });

  it("with no stored photo the header keeps the person icon and reads no bytes", async () => {
    await openDoctorMenu();

    const menu = screen.getByRole("menu");
    expect(menu.querySelector("img")).toBeNull();
    expect(menu.querySelector("svg")).not.toBeNull();
    // No ref, so nothing to resolve - the icon rather than an initial borrowed
    // from the practice name, which is a clinic and not a person (#538).
    expect(doctorApi.fetchDoctorProfilePhoto).not.toHaveBeenCalled();
  });

  it("falls back to the masked phone when the projection carries no practice name", async () => {
    await openDoctorMenu(ME_RESPONSE_PARTNER, null, null);

    expect(screen.getByTestId("account-menu-identity")).toHaveTextContent(
      maskedPhone("+911234567890"),
    );
    // The full number is still on its own line, exactly as for a patient.
    expect(screen.getByText("+911234567890")).toBeInTheDocument();
  });

  it("renders a live Profile row, one click from the dropdown", async () => {
    await openDoctorMenu();

    const entry = screen.getByTestId("account-menu-doctor-profile");
    // #604: full label, so a future drift back to the sidebar's bare "Profile"
    // fails here instead of passing on a prefix match.
    expect(entry).toHaveTextContent("Profile & Settings");
    expect(entry).toHaveAttribute("href", "/doctor/profile");

    fireEvent.click(entry);
    await waitFor(() =>
      expect(mockPush).toHaveBeenCalledWith("/doctor/profile"),
    );
  });

  it("every row is a full-size tap target, the patient's >=44px contract", async () => {
    await openDoctorMenu({
      subject_id: "42",
      phone: "+911234567890",
      roles: ["partner", "patient"],
    });

    for (const testId of [
      "account-menu-doctor-profile",
      "switch-to-patient",
      "account-menu-doctor-logout",
    ]) {
      expect(screen.getByTestId(testId).className).toContain("min-h-11");
    }
  });

  it("opens at the wider content width the patient menu uses", async () => {
    await openDoctorMenu();

    // The patient's own value, adopted - not a third width.
    expect(screen.getByRole("menu").className).toContain("w-60");
  });

  it("renders a red dictionary-driven Log out that ends the session", async () => {
    await openDoctorMenu();

    const logoutItem = screen.getByTestId("account-menu-doctor-logout");
    expect(logoutItem.className).toContain("text-danger");
    expect(logoutItem.className).toContain("focus:bg-danger-soft");

    fireEvent.click(logoutItem);
    expect(mockReplace).toHaveBeenCalledWith("/");
    expect(localStorage.getItem("caresetu.session")).toBeNull();
  });

  it("always draws the divider above the sign-out row", async () => {
    // A single-role session is the case the staff branch drops its divider on,
    // so this only passes if the doctor's is unconditional, as the patient's is.
    await openDoctorMenu();

    expect(screen.getByRole("separator")).toBeInTheDocument();
  });

  it("keeps the role-switch row for a multi-role doctor, and off a single-role one", async () => {
    await openDoctorMenu({
      subject_id: "42",
      phone: "+911234567890",
      roles: ["partner", "patient"],
    });

    const switchRow = screen.getByTestId("switch-to-patient");
    expect(switchRow).toHaveTextContent("Switch to Patient");

    // The same shared `switchRole` wiring the patient menu uses: selecting it
    // hands the session over and Radix closes the menu.
    fireEvent.click(switchRow);
    await waitFor(() =>
      expect(screen.queryByRole("menu")).not.toBeInTheDocument(),
    );
    cleanup();

    await openDoctorMenu();
    expect(screen.queryByText(/Switch to/)).not.toBeInTheDocument();
  });

  it("never offers the patient Complete your profile CTA", async () => {
    await openDoctorMenu();

    // Gated on a patient profile a doctor does not have, so it must not be
    // inherited by a later "just reuse the patient branch" edit.
    expect(screen.queryByTestId("account-menu-complete-profile")).toBeNull();
  });

  it("renders the doctor's account menu strings bilingually", async () => {
    localStorage.setItem("caresetu.lang", "hi");
    setStoredSession(VALID_SESSION);
    mockMeResponse(ME_RESPONSE_PARTNER);

    renderAccountMenu("doctor", doctorProfileWith(null));
    const trigger = await waitFor(() =>
      expect(screen.getByTestId("account-menu")).toBeInTheDocument(),
    ).then(() => screen.getByTestId("account-menu"));

    expect(trigger.getAttribute("aria-label")).toBe("अकाउंट मेन्यू");

    fireEvent.keyDown(trigger, { key: "Enter" });
    await waitFor(() => expect(screen.getByRole("menu")).toBeInTheDocument());

    expect(
      screen.getByRole("menuitem", { name: "लॉग आउट" }),
    ).toBeInTheDocument();
    // #604: the doctor's own row label in Hindi, read by accessible name so
    // this proves the whole string - not a prefix - and not the sidebar's
    // nav.profile ("प्रोफ़ाइल") that it used to borrow.
    expect(
      screen.getByRole("menuitem", { name: "प्रोफ़ाइल और सेटिंग" }),
    ).toBeInTheDocument();
  });

  it("keeps the accent, the width and the row sizing off non-doctor staff menus", async () => {
    // The same doctor payload in the partner shell: a lab or chemist partner.
    // The doctor's icon treatment must not leak onto it, and the staff branch's
    // own rows stay exactly as narrow, as small and as neutral as they were.
    await renderClosedTrigger(ME_RESPONSE_PARTNER, "partner");
    await openViaKeyboard();

    const menu = screen.getByRole("menu");
    expect(menu.className).toContain("w-52");
    const staffLogout = screen.getByTestId("logout-button");
    expect(staffLogout.className).not.toContain("text-danger");
    expect(staffLogout.className).not.toContain("min-h-11");
    expect(screen.getByTestId("account-menu-role-badge")).toHaveTextContent(
      "Partner",
    );
    // No identity header, no avatar: the staff header is the two-part
    // phone/badge row, with the doctor's identity layout kept off it.
    expect(screen.queryByTestId("account-menu-identity")).toBeNull();
    expect(menu.querySelector("img")).toBeNull();
    expect(menu.querySelector("svg")).toBeNull();
  });

  it("leaves the operator's account menu exactly as it was", async () => {
    // Pinned rather than assumed: the operator shares the staff branch, so
    // "unchanged" has to be a claim about the operator's own session, not an
    // inference from the partner shell's case.
    await renderClosedTrigger(ME_RESPONSE_OPERATOR, "operator");
    await openViaKeyboard();

    const menu = screen.getByRole("menu");
    expect(menu.className).toContain("w-52");
    expect(screen.getByTestId("account-menu-role-badge")).toHaveTextContent(
      "Operator",
    );
    const operatorLogout = screen.getByTestId("logout-button");
    expect(operatorLogout.className).not.toContain("text-danger");
    expect(operatorLogout.className).not.toContain("min-h-11");
    // Still the two-part phone/badge header: the phone on its own, no identity
    // line, no avatar.
    expect(screen.getByText("+911234567890")).toBeInTheDocument();
    expect(screen.queryByTestId("account-menu-identity")).toBeNull();
    expect(menu.querySelector("img")).toBeNull();
  });
});

describe("AccountMenu stale sessions", () => {
  it("degrades to subject-id-only when /me carries no phone field", async () => {
    setStoredSession(VALID_SESSION);
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(ME_RESPONSE_NO_PHONE), { status: 200 }),
    );

    renderAccountMenu("patient");
    await openViaKeyboard();

    expect(screen.getByText("Subject #42")).toBeInTheDocument();
    expect(screen.queryByText("+911234567890")).toBeNull();
  });

  it("renders Subject #id in the identity header and Log out still works", async () => {
    setStoredSession(VALID_SESSION);
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(ME_RESPONSE_NO_PHONE), { status: 200 }),
    );

    renderAccountMenu("patient");
    await openViaKeyboard();

    expect(screen.getByTestId("account-menu-identity")).toHaveTextContent(
      "Subject #42",
    );
    fireEvent.click(screen.getByRole("menuitem", { name: "Log out" }));
    expect(mockReplace).toHaveBeenCalledWith("/");
    expect(localStorage.getItem("caresetu.session")).toBeNull();
  });
});

// #584: the reported defect, and the guard against it. Two client-side faults
// stacked: the account menu picked its *surface* from the session's role, and
// `resolveRole` answers "patient" for an unresolved identity - so a doctor shell
// whose session had not resolved, or was still the stale patient session a
// dual-registered phone carries, opened the PATIENT menu. One assertion shape
// runs over every shell and both identity states, because the claim is a single
// rule: the shell owns the surface, the session owns the badges and the
// role-switch rows.
describe("AccountMenu surface belongs to the shell, not the session (#584)", () => {
  // The rows that only exist on one surface. A doctor's menu is the patient's
  // minus Complete-your-profile; a staff menu is neither. Presence or absence
  // of these test ids IS the surface, so a whole row list is the assertion.
  const DOCTOR_ROWS = [
    "account-menu-doctor-profile",
    "account-menu-doctor-logout",
  ];
  const PATIENT_ROWS = [
    "account-menu-profile-settings",
    "account-menu-complete-profile",
  ];

  /** The identity the doctor shell is asked to render under. */
  type ShellIdentity =
    // Nothing stored at all: a cold load where /me has not answered, so
    // `user` is null and the session's role is not merely stale - it is absent.
    | { kind: "unresolved" }
    // The report's exact state: the same phone already holds a patient
    // session, so the identity resolves to "patient" inside the doctor shell.
    | { kind: "stale-patient" };

  // The existing helpers all seed a session, which is the state the bug did
  // NOT happen in. This one is the only place either identity state is built,
  // and the shell role stays a required parameter for the same reason it is
  // everywhere else: a default would let a staff case slip into the patient
  // branch and still pass.
  function renderInShell(
    shellRole: Role,
    identity: ShellIdentity,
    doctorProjection?: DoctorProfileView,
  ) {
    if (identity.kind === "stale-patient") {
      setStoredSession(VALID_SESSION);
      mockMeResponse(ME_RESPONSE_SINGLE_ROLE);
    }
    if (doctorProjection !== undefined) {
      doctorApi.fetchDoctorProfile.mockResolvedValue(doctorProjection);
    }
    // Only a stored session causes a /me read at all, so the unresolved case
    // deliberately mocks nothing: an unanswered identity, not a failed one.
    render(
      <AuthProvider>
        {doctorProjection === undefined ? (
          <AccountMenu shellRole={shellRole} />
        ) : (
          <DoctorProfileProvider>
            <AccountMenu shellRole={shellRole} />
          </DoctorProfileProvider>
        )}
      </AuthProvider>,
    );
  }

  function expectRows(testIds: string[], present: boolean) {
    for (const id of testIds) {
      if (present) {
        expect(screen.getByTestId(id)).toBeInTheDocument();
      } else {
        expect(screen.queryByTestId(id)).toBeNull();
      }
    }
  }

  // Waits for the identity the case is actually about before opening, so a
  // doctor row can never win by having been rendered a moment before /me
  // answered. The trigger is re-queried rather than held: the identity
  // resolution re-renders it, so a captured node goes stale.
  async function openInShell(
    shellRole: Role,
    identity: ShellIdentity,
    doctorProjection?: DoctorProfileView,
  ) {
    renderInShell(shellRole, identity, doctorProjection);
    await waitFor(() =>
      expect(screen.getByTestId("account-menu")).toHaveAttribute(
        "data-session-resolved",
        identity.kind === "unresolved" ? "false" : "true",
      ),
    );
    const trigger = await openViaKeyboard();
    return trigger;
  }

  it("a doctor shell with an UNRESOLVED identity shows the doctor menu, not the patient's", async () => {
    await openInShell(
      "doctor",
      { kind: "unresolved" },
      doctorProfileWith(null),
    );

    // On a cold load the shell already knows it is a doctor shell, so the
    // patient menu is never the correct answer at any moment - including the
    // moment before /me answers, which the next test pins directly.
    expectRows(DOCTOR_ROWS, true);
    expectRows(PATIENT_ROWS, false);
  });

  it("a doctor shell's FIRST paint is already the doctor's, never a patient frame", () => {
    // A4's "never flashes the patient menu first", asserted with no wait at
    // all: the very first commit, while /me is still unanswered, must already
    // carry the doctor's trigger. Waiting for the identity to settle first would
    // let a patient frame in between go unnoticed, and that frame is the
    // visible half of the report.
    renderInShell("doctor", { kind: "unresolved" }, doctorProfileWith(null));

    const firstPaint = screen.getByTestId("account-menu");
    expect(firstPaint).toHaveAttribute("data-session-resolved", "false");
    // The doctor's 36px disc, not the patient's 44px mobile-only trigger: the
    // patient trigger is hidden below lg, so a patient frame would be absent
    // from view entirely.
    expect(firstPaint).toHaveClass("h-9", "w-9");
    expect(firstPaint).not.toHaveClass("hidden");
    expect(firstPaint.querySelector("svg")).not.toBeNull();
  });

  it("a doctor shell holding a STALE PATIENT session still shows the doctor menu", async () => {
    // The dual-registered phone from the report. The session really does say
    // "patient" here, and the doctor menu must still win.
    await openInShell(
      "doctor",
      { kind: "stale-patient" },
      doctorProfileWith(null),
    );

    expectRows(DOCTOR_ROWS, true);
    expectRows(PATIENT_ROWS, false);
  });

  it("a doctor shell's avatar shows the person icon, never the phone digits", async () => {
    const trigger = await openInShell("doctor", { kind: "unresolved" });

    // #538/A5: the doctor trigger never borrows the phone digits, which is
    // what the staff branch is for. Asserted on the trigger so a correct menu
    // cannot hide a wrong avatar.
    expect(trigger).not.toHaveTextContent("90");
    expect(trigger.querySelector("img")).toBeNull();
    expect(trigger.querySelector("svg")).not.toBeNull();
  });

  // A7: the staff shells must keep their own treatment, not merely lack the
  // doctor and patient rows. `logout-button` cannot do that job alone - the
  // patient branch reuses the same test id - so the trigger's shape and the
  // width carry it: digits where the other surfaces draw an icon, and `w-52`
  // against the real menus' `w-60`. The digits are the identity's own, so an
  // unresolved identity shows the branch's `?` fallback rather than "90".
  function expectStaffTreatment(trigger: HTMLElement, digits: string) {
    expect(trigger).toHaveTextContent(digits);
    expect(trigger.querySelector("svg")).toBeNull();
    expect(trigger.querySelector("img")).toBeNull();
    expect(screen.getByRole("menu")).toHaveClass("w-52");
    expect(screen.getByRole("menu")).not.toHaveClass("w-60");
    expect(screen.getByRole("menuitem", { name: "Log out" })).not.toHaveClass(
      "text-danger",
    );
  }

  it("keeps a lab or chemist partner on the staff menu under both identity states", async () => {
    let trigger = await openInShell("partner", { kind: "unresolved" });
    expectRows(DOCTOR_ROWS, false);
    expectRows(PATIENT_ROWS, false);
    expectStaffTreatment(trigger, "?");
    cleanup();

    trigger = await openInShell("partner", { kind: "stale-patient" });
    expectRows(DOCTOR_ROWS, false);
    expectRows(PATIENT_ROWS, false);
    expectStaffTreatment(trigger, "90");
  });

  it("keeps the operator on the staff menu under both identity states", async () => {
    let trigger = await openInShell("operator", { kind: "unresolved" });
    expectRows(DOCTOR_ROWS, false);
    expectRows(PATIENT_ROWS, false);
    expectStaffTreatment(trigger, "?");
    cleanup();

    trigger = await openInShell("operator", { kind: "stale-patient" });
    expectRows(DOCTOR_ROWS, false);
    expectRows(PATIENT_ROWS, false);
    expectStaffTreatment(trigger, "90");
  });

  it("opens a doctor menu at the wider real-account width, not the staff one", async () => {
    await openInShell(
      "doctor",
      { kind: "unresolved" },
      doctorProfileWith(null),
    );

    // The width is the cheapest thing that separates a real account menu from
    // the staff branch, since both draw a Log out row.
    expect(screen.getByRole("menu")).toHaveClass("w-60");
  });

  it("pins the patient menu unchanged in the patient shell", async () => {
    await openInShell("patient", { kind: "stale-patient" });

    // A9: the fix moves the *selection*, never the patient branch's content.
    expectRows(PATIENT_ROWS, true);
    expectRows(DOCTOR_ROWS, false);
  });
});

// #567: a cheap negative guard on the one file that used to get this wrong.
// The three behavioural tests above and AppShell's suite already prove the
// direction; these only catch the specific shape coming back in a *different*
// spot in this file - a second, session-derived doctor check beside the
// threaded one. Deliberately negative-only: a positive regex would pin
// implementation text and break on a rename with no behaviour change.
// Note what this does NOT prove - that the role is threaded from the shell.
// That needs both files, so it is AppShell's end-to-end test's job, not this.
describe("AccountMenu never re-derives doctor-ness from the session (#567)", () => {
  const source = readFileSync(join(__dirname, "AccountMenu.tsx"), "utf8");

  it("asks the session's role about nothing doctor-specific", () => {
    // The exact shape that made every doctor affordance unreachable, since the
    // session can only answer patient|partner|operator.
    expect(source).not.toMatch(/currentRole === "doctor"/);
    expect(source).not.toMatch(/selectedRole === "doctor"/);
    expect(source).not.toMatch(/resolveRole\([^)]*\)\s*===\s*"doctor"/);
  });
});
