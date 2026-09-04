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

// PHASE-2.6 T07 (#198): the single generic dashboard group split into
// per-role route groups - each stub page re-homed under its role's group.

describe("per-role route-group scaffold pages", () => {
  it.each([
    ["patient", PatientDashboardPage, "Welcome, Patient"],
    ["doctor", DoctorDashboardPage, "Welcome, Doctor"],
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
