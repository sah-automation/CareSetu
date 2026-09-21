import { render, screen, cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import DoctorDashboardPage from "@/app/(doctor)/doctor/page";
import OperatorDashboardPage from "@/app/(operator)/operator/page";
import PartnerDashboardPage from "@/app/(partner)/partner/page";
import PatientDashboardPage from "@/app/(patient)/patient/page";
import { ProfileProvider } from "@/lib/profile/ProfileContext";

// The operator page (PHASE-5 T5, #284) fetches the verification queue on
// mount; mock the api seam so the scaffold render is synchronous and no
// promise can settle after the test environment tears down.
vi.mock("@/lib/operator/api", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/operator/api")>();
  return {
    ...mod,
    fetchVerificationQueue: vi.fn().mockResolvedValue({ items: [] }),
  };
});

// PHASE-8.1 T12 (#450): the doctor page now loads review queue + open cases
// on mount via fetchReviewQueue and listOpenCases; mock both seams so the
// scaffold render is synchronous.

vi.mock("@/lib/intake/api", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/intake/api")>();
  return { ...mod, fetchReviewQueue: vi.fn().mockResolvedValue([]) };
});

vi.mock("@/lib/care/api", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/care/api")>();
  return { ...mod, listOpenCases: vi.fn().mockResolvedValue([]) };
});

vi.mock("@/lib/partner/api", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/partner/api")>();
  return { ...mod, updateConsultationFee: vi.fn().mockResolvedValue({}) };
});

// PHASE-8.1 T2 (#488): the patient dashboard reads its draft from the
// ProfileProvider, which needs a signed-in identity and the profile client;
// stub both so the scaffold render is synchronous over the same seams.

vi.mock("@/lib/auth/AuthContext", () => ({
  useAuth: () => ({
    user: { id: 7, phone: "+91 98765 43210", roles: ["patient"] },
    selectedRole: null,
    switchRole: vi.fn(),
    logout: vi.fn(),
    isAuthenticated: true,
    isLoading: false,
  }),
}));

vi.mock("@/lib/profile/api", () => ({
  getProfile: vi.fn().mockResolvedValue({ set: false, profile: null }),
  saveProfile: vi.fn().mockResolvedValue(null),
}));

// #502: the patient home search card routes through fresh navigation; stub
// the router/link seams so the scaffold render is synchronous.
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("next/link", () => {
  return {
    default: ({
      href,
      children,
    }: {
      href: string;
      children: React.ReactNode;
    }) => <a href={href}>{children}</a>,
  };
});

// PHASE-2.6 T07 (#198): the single generic dashboard group split into
// per-role route groups - each stub page re-homed under its role's group.

// Vitest runs without `globals`, so @testing-library/react's auto-cleanup is
// off. Unmount the previous page before the next it() renders, otherwise React
// 19's scheduler keeps work queued that fires after the jsdom env tears down
// and surfaces as "window is not defined" unhandled errors.
afterEach(cleanup);

describe("per-role route-group scaffold pages", () => {
  // PHASE-2.7 T1 (#499): the patient home greeting is now i18n-driven and
  // name-personalized, so its scaffold heading is pinned by a stable testid
  // instead of the removed "Welcome, Patient" literal. Other roles keep their
  // fixed h1 copy.
  it.each([
    ["patient", PatientDashboardPage, "testid", "patient-home-greeting"],
    ["doctor", DoctorDashboardPage, "heading", "Doctor console"],
    ["partner", PartnerDashboardPage, "heading", "Welcome, Partner"],
    ["operator", OperatorDashboardPage, "heading", "Verification queue"],
  ] as const)(
    "renders the %s dashboard scaffold page",
    (role, Page, kind, target) => {
      // The patient dashboard reads its draft from the ProfileProvider
      // (#488); mount it here so the scaffold render is complete. The other
      // role pages don't read it and are unaffected.
      render(
        role === "patient" ? (
          <ProfileProvider>
            <Page />
          </ProfileProvider>
        ) : (
          <Page />
        ),
      );
      const found =
        kind === "testid"
          ? screen.getByTestId(target)
          : screen.getByRole("heading", { name: target, level: 1 });
      expect(found).toBeInTheDocument();
    },
  );
});
