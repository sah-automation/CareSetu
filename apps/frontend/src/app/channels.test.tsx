import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import OperatorChannelPage from "@/app/(operator)/operator/page";
import PartnerChannelPage from "@/app/(partner)/partner/page";

describe("channel hello-world routes", () => {
  it.each([
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
