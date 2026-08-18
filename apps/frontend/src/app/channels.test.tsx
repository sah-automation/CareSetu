import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import PatientDashboardPage from "@/app/(dashboard)/patient/page";
import PartnerDashboardPage from "@/app/(dashboard)/partner/page";
import OperatorDashboardPage from "@/app/(dashboard)/operator/page";

describe("dashboard scaffold pages", () => {
  it.each([
    ["patient", PatientDashboardPage, "Welcome, Patient"],
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
