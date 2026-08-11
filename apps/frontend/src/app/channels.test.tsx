import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import OperatorChannelPage from "@/app/(operator)/operator/page";
import PartnerChannelPage from "@/app/(partner)/partner/page";
import PatientChannelPage from "@/app/(patient)/patient/page";

describe("channel hello-world routes", () => {
  it.each([
    ["patient", PatientChannelPage, "Patient channel - hello world"],
    ["partner", PartnerChannelPage, "Partner channel - hello world"],
    ["operator", OperatorChannelPage, "Operator channel - hello world"],
  ] as const)(
    "renders the %s channel hello-world page",
    (_channel, Page, heading) => {
      render(<Page />);
      expect(
        screen.getByRole("heading", { name: heading, level: 1 }),
      ).toBeInTheDocument();
    },
  );
});
