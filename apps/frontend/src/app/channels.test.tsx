import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import DoctorDashboardPage from "@/app/(doctor)/doctor/page";
import OperatorDashboardPage from "@/app/(operator)/operator/page";
import PartnerDashboardPage from "@/app/(partner)/partner/page";
import PatientDashboardPage from "@/app/(patient)/patient/page";

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

// PHASE-2.6 T07 (#198): the single generic dashboard group split into
// per-role route groups - each stub page re-homed under its role's group.

describe("per-role route-group scaffold pages", () => {
  it.each([
    ["patient", PatientDashboardPage, "Welcome, Patient"],
    ["doctor", DoctorDashboardPage, "Doctor console"],
    ["partner", PartnerDashboardPage, "Welcome, Partner"],
    ["operator", OperatorDashboardPage, "Verification queue"],
  ] as const)(
    "renders the %s dashboard scaffold page",
    (_role, Page, heading) => {
      render(<Page />);
      expect(
        screen.getByRole("heading", { name: heading, level: 1 }),
      ).toBeInTheDocument();
    },
  );
});
