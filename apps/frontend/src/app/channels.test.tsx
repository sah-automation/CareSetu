import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import DoctorDashboardPage from "@/app/(doctor)/doctor/page";
import OperatorDashboardPage from "@/app/(operator)/operator/page";
import PartnerDashboardPage from "@/app/(partner)/partner/page";
import PatientDashboardPage from "@/app/(patient)/patient/page";

// PHASE-2.6 T07 (#198): the single generic dashboard group split into
// per-role route groups - each stub page re-homed under its role's group.

describe("per-role route-group scaffold pages", () => {
  it.each([
    ["patient", PatientDashboardPage, "Welcome, Patient"],
    ["doctor", DoctorDashboardPage, "Welcome, Doctor"],
    ["partner", PartnerDashboardPage, "Welcome, Partner"],
    ["operator", OperatorDashboardPage, "Welcome, Operator"],
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
